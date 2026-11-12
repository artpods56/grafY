"""What a TIFF is, and where its pixels sit in the deep-zoom pyramid.

Everything here is cheap metadata. Rendering lives in :mod:`grafy_tiler.render`.
"""

import math
from dataclasses import asdict, dataclass
from typing import Final, Literal

import numpy as np
import rasterio
from rasterio.enums import ColorInterp, MaskFlags
from rasterio.errors import RasterioError
from rasterio.io import DatasetReader
from rasterio.warp import transform_bounds
from rasterio.windows import Window
from rio_tiler.reader import read as read_region

from grafy_tiler.grant import Grant
from grafy_tiler.settings import OVERVIEW_EDGE, Settings

# Bump when rendering output changes for the same source. It is part of every
# cache key and of the ETag the API derives, so old tiles simply stop matching.
RENDERER_VERSION: Final = "1"

Kind = Literal["gray", "rgb", "palette", "cmyk"]
TileFormat = Literal["jpg", "png"]
Resampling = Literal["nearest", "average"]


class SourceError(Exception):
    """The object is missing, unreadable, or not a TIFF GDAL can open."""


class SourceTooLarge(Exception):
    """The object exceeds a configured size, pixel or page limit."""


class SourceMismatch(Exception):
    """The stored object is not the one the grant describes."""


class PageNotFound(Exception):
    """The TIFF has no such page."""


@dataclass(frozen=True, slots=True)
class ImageInfo:
    width: int
    height: int
    page: int
    page_count: int
    band_count: int
    dtype: str
    bit_depth: int
    kind: Kind
    # True when some pixels are transparent: alpha band, per-dataset mask or
    # nodata. Those images are served as PNG so transparency survives.
    has_alpha: bool
    tile_size: int
    min_level: int
    max_level: int
    tile_format: TileFormat
    resampling: Resampling
    overview_count: int
    # Level at which a lazily built overview takes over, or None.
    overview_level: int | None
    # 2nd to 98th percentile of the rendered bands, for >8-bit and float data.
    value_range: tuple[float, float] | None
    # Palette entries as (r, g, b, a), only for `palette` images.
    palette: tuple[tuple[int, int, int, int], ...] | None
    # TODO(geo-open-on-map): these three feed a later "open on map" for
    # georeferenced TIFFs. Nothing renders in map space yet; tiles stay in
    # pixel space and ignore the georeferencing.
    georeferenced: bool
    crs: str | None
    bounds_wgs84: tuple[float, float, float, float] | None

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_json_dict(cls, data: dict[str, object]) -> "ImageInfo":
        fields = dict(data)
        for name in ("value_range", "bounds_wgs84"):
            value = fields.get(name)
            if value is not None:
                fields[name] = tuple(value)  # pyright: ignore[reportArgumentType]
        palette = fields.get("palette")
        if palette is not None:
            fields["palette"] = tuple(tuple(entry) for entry in palette)  # pyright: ignore[reportGeneralTypeIssues]
        return cls(**fields)  # pyright: ignore[reportArgumentType]

    @property
    def level_count(self) -> int:
        return self.max_level + 1


def max_level_for(width: int, height: int) -> int:
    """Deep-zoom top level: level 0 is one pixel, each level doubles."""
    return (max(width, height) - 1).bit_length()


def level_size(width: int, height: int, top_level: int, level: int) -> tuple[int, int]:
    scale = 1 << (top_level - level)
    return math.ceil(width / scale), math.ceil(height / scale)


def min_level_for(width: int, height: int, tile_size: int) -> int:
    """Lowest level worth requesting: the largest one that fits a single tile."""
    top = max_level_for(width, height)
    for level in range(top, -1, -1):
        if max(level_size(width, height, top, level)) <= tile_size:
            return level
    return 0


def pixel_window(col: int, row: int, width: int, height: int) -> Window:
    # rasterio ships no stubs and pyright misreads its attrs-based Window.
    return Window(col, row, width, height)  # pyright: ignore[reportCallIssue]


def tile_window(
    width: int,
    height: int,
    top_level: int,
    tile_size: int,
    level: int,
    x: int,
    y: int,
) -> tuple[Window, int, int] | None:
    """Source window and output size of tile (level, x, y), or None if outside.

    `top_level` is the level at which one source pixel is one output pixel.
    Edge tiles are cropped to the level's size, never padded.
    """
    if not 0 <= level <= top_level or x < 0 or y < 0:
        return None
    level_width, level_height = level_size(width, height, top_level, level)
    out_x, out_y = x * tile_size, y * tile_size
    if out_x >= level_width or out_y >= level_height:
        return None
    out_width = min(tile_size, level_width - out_x)
    out_height = min(tile_size, level_height - out_y)
    scale = 1 << (top_level - level)
    window = pixel_window(
        out_x * scale,
        out_y * scale,
        min(out_width * scale, width - out_x * scale),
        min(out_height * scale, height - out_y * scale),
    )
    return window, out_width, out_height


def thumbnail_size(width: int, height: int, edge: int) -> tuple[int, int]:
    """Fit inside `edge` x `edge`, keep the aspect ratio, never upscale."""
    scale = min(1.0, edge / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def source_path(settings: Settings, grant: Grant) -> str:
    """The only place a path to read is built, from validated grant fields."""
    if settings.storage == "s3":
        return f"/vsis3/{grant.bucket}/{grant.key}"
    assert settings.local_root is not None
    root = settings.local_root.resolve()
    candidate = (root / grant.bucket / grant.key).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise SourceError("object not found")
    if candidate.stat().st_size != grant.byte_size:
        raise SourceMismatch("stored object size differs from the grant")
    return str(candidate)


def open_page(path: str, page: int) -> DatasetReader:
    target = path if page == 0 else f"GTIFF_DIR:{page + 1}:{path}"
    try:
        return rasterio.open(target, driver="GTiff", sharing=False)
    except RasterioError as error:
        raise SourceError("not a readable TIFF") from error


def describe(path: str, page: int, settings: Settings) -> ImageInfo:
    with open_page(path, 0) as first:
        page_count = max(1, len(first.subdatasets))
    if page_count > settings.max_pages:
        raise SourceTooLarge("too many pages")
    if page >= page_count:
        raise PageNotFound(f"page {page} of {page_count}")
    with open_page(path, page) as ds:
        return _describe(ds, page, page_count, settings)


def _describe(
    ds: DatasetReader, page: int, page_count: int, settings: Settings
) -> ImageInfo:
    width, height = ds.width, ds.height
    if width < 1 or height < 1 or width * height > settings.max_pixels:
        raise SourceTooLarge("image has too many pixels")
    interpretation = ds.colorinterp
    if interpretation[0] == ColorInterp.palette:
        kind: Kind = "palette"
    elif ds.count >= 4 and tuple(interpretation[:4]) == (
        ColorInterp.cyan,
        ColorInterp.magenta,
        ColorInterp.yellow,
        ColorInterp.black,
    ):
        kind = "cmyk"
    elif ds.count >= 3:
        kind = "rgb"
    else:
        kind = "gray"

    dtype = ds.dtypes[0]
    bit_depth = _bit_depth(ds, dtype)
    palette = _palette(ds) if kind == "palette" else None
    flags = ds.mask_flag_enums[0]
    has_alpha = any(
        flag in flags
        for flag in (MaskFlags.alpha, MaskFlags.per_dataset, MaskFlags.nodata)
    ) or (palette is not None and any(entry[3] < 255 for entry in palette))
    overviews = ds.overviews(1)
    resampling: Resampling
    if kind == "palette":
        # GDAL never averages paletted bands. Two-colour scans are blended by
        # the renderer itself (see `_read_bilevel`).
        resampling = "nearest"
    elif bit_depth < 8 or not overviews:
        resampling = "average"
    else:
        # GDAL answers a downsampled read from the smallest sufficient overview.
        resampling = "nearest"

    top = max_level_for(width, height)
    overview_level: int | None = None
    if not overviews and max(width, height) > settings.overview_min_pixels:
        overview_level = max(
            level
            for level in range(top + 1)
            if max(level_size(width, height, top, level)) <= OVERVIEW_EDGE
        )

    georeferenced = ds.crs is not None and not ds.transform.is_identity
    crs = ds.crs.to_string() if georeferenced and ds.crs is not None else None
    bounds: tuple[float, float, float, float] | None = None
    if georeferenced and ds.crs is not None:
        try:
            west, south, east, north = transform_bounds(ds.crs, "EPSG:4326", *ds.bounds)
            bounds = (west, south, east, north)
        except Exception:  # noqa: BLE001 -- informational only, never fatal
            bounds = None

    # Anything that is not plain 8-bit is stretched with one fixed range.
    needs_range = bit_depth >= 8 and dtype != "uint8"
    value_range = _value_range(ds, kind) if needs_range else None
    return ImageInfo(
        width=width,
        height=height,
        page=page,
        page_count=page_count,
        band_count=ds.count,
        dtype=dtype,
        bit_depth=bit_depth,
        kind=kind,
        has_alpha=has_alpha,
        tile_size=settings.tile_size,
        min_level=min_level_for(width, height, settings.tile_size),
        max_level=top,
        tile_format="png" if has_alpha or kind == "palette" else "jpg",
        resampling=resampling,
        overview_count=len(overviews),
        overview_level=overview_level,
        value_range=value_range,
        palette=palette,
        georeferenced=georeferenced,
        crs=crs,
        bounds_wgs84=bounds,
    )


def _bit_depth(ds: DatasetReader, dtype: str) -> int:
    declared = ds.tags(ns="IMAGE_STRUCTURE").get("NBITS")
    if declared is not None and declared.isdigit():
        return int(declared)
    if dtype in ("float32", "float64"):
        return 32 if dtype == "float32" else 64
    return int(np.dtype(dtype).itemsize * 8)


def _palette(ds: DatasetReader) -> tuple[tuple[int, int, int, int], ...]:
    table = ds.colormap(1)
    size = max(table) + 1
    return tuple(tuple(table.get(index, (0, 0, 0, 255))) for index in range(size))  # pyright: ignore[reportReturnType]


def is_bilevel(info: ImageInfo) -> bool:
    return info.kind == "palette" and _is_bilevel(info.palette)


def _is_bilevel(palette: tuple[tuple[int, int, int, int], ...] | None) -> bool:
    return palette is not None and len(palette) <= 2


def _value_range(ds: DatasetReader, kind: Kind) -> tuple[float, float]:
    """Percentile range from a small overview-sized read, once per image.

    One fixed range for every tile of the image is what keeps neighbouring
    tiles from showing seams.
    """
    indexes = [1, 2, 3, 4] if kind == "cmyk" else ([1, 2, 3] if ds.count >= 3 else [1])
    sample = read_region(ds, indexes=indexes, max_size=1024, out_dtype="float32")
    values = sample.array.compressed()
    values = values[np.isfinite(values)]
    if values.size == 0:
        return 0.0, 1.0
    low, high = (float(v) for v in np.percentile(values, [2, 98]))
    if high <= low:
        low, high = float(values.min()), float(values.max())
    if high <= low:
        high = low + 1.0
    return low, high
