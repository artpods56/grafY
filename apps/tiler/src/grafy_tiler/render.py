"""Normalize TIFF pixels for image-space and Web Mercator rendering."""

import numpy as np
from morecantile import Tile
from numpy.typing import NDArray
from rasterio.enums import ColorInterp
from rasterio.io import DatasetReader
from rasterio.transform import Affine, from_bounds
from rasterio.windows import Window
from rio_tiler.constants import WEB_MERCATOR_TMS
from rio_tiler.io import Reader
from rio_tiler.models import ImageData
from rio_tiler.reader import read as read_region

from grafy_tiler.raster import ImageInfo, TileFormat, is_bilevel

type Pixels = NDArray[np.uint8]

# Samples per output pixel, per axis, when blending a two-colour scan.
_SUPERSAMPLE = 8
GEO_TILE_SIZE = 256


def render_region(
    ds: DatasetReader,
    info: ImageInfo,
    window: Window,
    out_width: int,
    out_height: int,
    *,
    tile_format: TileFormat,
    jpeg_quality: int,
) -> bytes:
    pixels, valid = _read_pixels(ds, info, window, out_width, out_height)
    masked = np.ma.MaskedArray(pixels, mask=np.broadcast_to(~valid, pixels.shape))
    image = ImageData(masked)  # pyright: ignore[reportCallIssue] -- attrs defaults
    if tile_format == "jpg":
        return image.render(img_format="JPEG", add_mask=False, quality=jpeg_quality)
    return image.render(img_format="PNG", add_mask=info.has_alpha)


def render_geo_tile(
    ds: DatasetReader,
    info: ImageInfo,
    z: int,
    x: int,
    y: int,
    *,
    tile_format: TileFormat,
    jpeg_quality: int,
) -> bytes:
    image = render_geo_tile_image(ds, info, z, x, y)
    opaque = bool(np.all(image.mask == 255))
    if tile_format == "jpg" and opaque:
        return image.render(img_format="JPEG", add_mask=False, quality=jpeg_quality)
    return image.render(img_format="PNG", add_mask=not opaque)


def render_geo_tile_image(
    ds: DatasetReader, info: ImageInfo, z: int, x: int, y: int
) -> ImageData:
    """Warp one Web Mercator tile to display pixels plus 0..255 coverage."""
    # Ask GDAL to warp directly to the tile grid. The default rio-tiler VRT
    # can describe the entire tile at native resolution before downsampling.
    size = GEO_TILE_SIZE
    bounds = WEB_MERCATOR_TMS.xy_bounds(Tile(x, y, z))
    with Reader(None, dataset=ds) as reader:  # pyright: ignore[reportCallIssue] -- attrs defaults
        tile = reader.tile(
            x,
            y,
            z,
            tilesize=size,
            indexes=_geo_indexes(info, ds),
            vrt_options={
                "transform": from_bounds(*bounds, size, size),
                "width": size,
                "height": size,
            },
        )
    return _display_image(tile, info, ds)


class GeoMosaicComposer:
    """Composites Web Mercator tiles top to bottom with premultiplied dst-over.

    The caller adds the topmost sheet first. Each lower sheet only fills the
    coverage the sheets above it left, so anti-aliased edges blend without
    halos and the caller can stop as soon as the tile is opaque.
    """

    def __init__(self, size: int = GEO_TILE_SIZE) -> None:
        self._rgb = np.zeros((3, size, size), dtype=np.float32)
        self._alpha = np.zeros((size, size), dtype=np.float32)
        self._has_pixels = False

    @property
    def is_opaque(self) -> bool:
        return self._has_pixels and float(self._alpha.min()) >= 1.0 - (0.5 / 255.0)

    @property
    def is_empty(self) -> bool:
        return not self._has_pixels

    def add_below(self, image: ImageData) -> None:
        coverage = image.mask
        if not np.any(coverage > 0):
            return
        layer_rgb = image.array.data
        if layer_rgb.shape[0] == 1:
            layer_rgb = np.repeat(layer_rgb, 3, axis=0)
        else:
            layer_rgb = layer_rgb[:3]
        weight = (coverage.astype(np.float32) / 255.0) * (1.0 - self._alpha)
        if not np.any(weight > 0.0):
            return
        self._rgb += layer_rgb.astype(np.float32) * weight[None, :, :]
        self._alpha += weight
        self._has_pixels = True

    def encode(self, *, tile_format: TileFormat, jpeg_quality: int) -> bytes:
        if not self._has_pixels:
            raise ValueError("Cannot encode an empty mosaic tile")
        out_rgb = np.zeros_like(self._rgb)
        covered = self._alpha > 0.0
        out_rgb[:, covered] = self._rgb[:, covered] / self._alpha[covered]
        pixels = np.rint(np.clip(out_rgb, 0.0, 255.0)).astype(np.uint8)
        alpha = np.rint(np.clip(self._alpha * 255.0, 0.0, 255.0)).astype(np.uint8)
        image = ImageData(np.ma.MaskedArray(pixels), alpha_mask=alpha)  # pyright: ignore[reportCallIssue] -- attrs defaults
        opaque = bool(np.all(alpha == 255))
        if tile_format == "jpg" and opaque:
            return image.render(img_format="JPEG", add_mask=False, quality=jpeg_quality)
        return image.render(img_format="PNG", add_mask=not opaque)


def render_geo_overview(
    ds: DatasetReader, info: ImageInfo, width: int, height: int
) -> bytes:
    # Sparse nearest-neighbour sampling lets GDAL skip unsampled strips.
    # The cached overview keeps the pixel grid's rotation as well as its CRS.
    region = read_region(
        ds,
        indexes=_geo_indexes(info, ds),
        width=width,
        height=height,
        resampling_method="nearest",
    )
    image = _display_image(region, info, ds)
    return image.render(
        img_format="GTiff",
        transform=ds.transform @ Affine.scale(ds.width / width, ds.height / height),
        crs=ds.crs,
        compress="deflate",
        alpha="yes",
    )


def _display_image(region: ImageData, info: ImageInfo, ds: DatasetReader) -> ImageData:
    values = region.array
    alpha = region.alpha_mask
    if ds.nodata is not None and ColorInterp.alpha in ds.colorinterp:
        values, alpha = values[:-1], values.data[-1]
        alpha = np.where(np.ma.getmaskarray(values).all(axis=0), 0, alpha)
    if alpha is None:
        coverage = np.where(~np.ma.getmaskarray(values).all(axis=0), 255, 0)
    else:
        coverage = _alpha_as_byte(alpha, ds)
    if info.palette is not None:
        table = np.asarray(info.palette, dtype=np.uint8)
        indexed = np.clip(values.data[0], 0, len(table) - 1)
        colours = table[indexed]
        pixels = np.moveaxis(colours[..., :3], -1, 0)
        coverage = np.minimum(coverage, colours[..., 3])
    else:
        pixels = _normalize(values.data, info)
    return ImageData(np.ma.MaskedArray(pixels), alpha_mask=coverage.astype(np.uint8))  # pyright: ignore[reportCallIssue] -- attrs defaults


def _geo_indexes(info: ImageInfo, ds: DatasetReader) -> list[int]:
    indexes = _display_indexes(info)
    if ds.nodata is not None and ColorInterp.alpha in ds.colorinterp:
        # rio-tiler exposes the nodata mask alone in this case. Read the
        # source alpha as a band as well, then combine both in _display_image.
        indexes.append(ds.colorinterp.index(ColorInterp.alpha) + 1)
    return indexes


def _alpha_as_byte(alpha: NDArray[np.generic], ds: DatasetReader) -> Pixels:
    alpha_index = ds.colorinterp.index(ColorInterp.alpha) + 1
    declared = ds.tags(alpha_index, ns="IMAGE_STRUCTURE").get("NBITS")
    opaque = 1
    if alpha.dtype.kind in "iu":
        opaque = (
            (1 << int(declared)) - 1 if declared else np.iinfo(alpha.dtype.name).max
        )
    return np.rint(np.clip(alpha.astype(np.float64) * (255.0 / opaque), 0, 255)).astype(
        np.uint8
    )


def _read_pixels(
    ds: DatasetReader,
    info: ImageInfo,
    window: Window,
    out_width: int,
    out_height: int,
) -> tuple[Pixels, NDArray[np.bool_]]:
    """Return (bands, height, width) uint8 pixels and a (height, width) validity mask."""
    if info.kind == "palette":
        return _read_palette(ds, info, window, out_width, out_height)

    indexes = _display_indexes(info)
    # Averaging integers rounds each output pixel. Bilevel and low-bit scans
    # (0/1 values) would collapse back to black and white, so read as float.
    precise = info.bit_depth != 8 or info.dtype != "uint8"
    region = read_region(
        ds,
        window=window,
        width=out_width,
        height=out_height,
        indexes=indexes,
        resampling_method=info.resampling,
        out_dtype="float32" if precise else None,
    )
    valid = ~np.ma.getmaskarray(region.array).any(axis=0)
    return _normalize(region.array.data, info), valid


def _normalize(values: NDArray[np.generic], info: ImageInfo) -> Pixels:
    if info.bit_depth < 8:
        values = values.astype(np.float32, copy=False) * (
            255.0 / ((1 << info.bit_depth) - 1)
        )
    elif info.bit_depth != 8 or info.dtype != "uint8":
        assert info.value_range is not None
        low, high = info.value_range
        values = (values.astype(np.float32, copy=False) - low) * (255.0 / (high - low))
    pixels = np.clip(np.nan_to_num(values), 0, 255).astype(np.uint8)

    if info.kind == "cmyk":
        pixels = _cmyk_to_rgb(pixels)
    return pixels


def _display_indexes(info: ImageInfo) -> list[int]:
    if info.kind == "cmyk":
        return [1, 2, 3, 4]
    if info.kind == "rgb":
        # Beyond three bands there is no colour interpretation; show the first
        # three. A fourth alpha band is carried by the mask, not as a band.
        return [1, 2, 3]
    return [1]


def _cmyk_to_rgb(cmyk: Pixels) -> Pixels:
    """Naive conversion, no ICC profile: R = 255 * (1 - C) * (1 - K)."""
    inverse = 1.0 - cmyk.astype(np.float32) / 255.0
    rgb = 255.0 * inverse[:3] * inverse[3]
    return np.clip(rgb, 0, 255).astype(np.uint8)


def _read_palette(
    ds: DatasetReader,
    info: ImageInfo,
    window: Window,
    out_width: int,
    out_height: int,
) -> tuple[Pixels, NDArray[np.bool_]]:
    assert info.palette is not None
    if is_bilevel(info):
        return _read_bilevel(ds, info, window, out_width, out_height)

    region = read_region(
        ds,
        window=window,
        width=out_width,
        height=out_height,
        indexes=[1],
        resampling_method="nearest",
    )
    table = np.zeros((256, 4), dtype=np.uint8)
    table[:, 3] = 255
    for index, entry in enumerate(info.palette[:256]):
        table[index] = entry
    indexed = region.array.data[0]
    colours = table[indexed]
    valid = ~np.ma.getmaskarray(region.array)[0] & (colours[..., 3] > 0)
    return np.moveaxis(colours[..., :3], -1, 0), valid


def _read_bilevel(
    ds: DatasetReader,
    info: ImageInfo,
    window: Window,
    out_width: int,
    out_height: int,
) -> tuple[Pixels, NDArray[np.bool_]]:
    """Two-colour scans blend between their two colours when downsampled, so
    text stays legible instead of dropping out.

    GDAL will not average a paletted band, so sample the window on a regular
    grid finer than the output and average the samples here.
    """
    assert info.palette is not None
    ratio = max(window.width / out_width, window.height / out_height)
    factor = max(1, min(_SUPERSAMPLE, int(ratio)))
    region = read_region(
        ds,
        window=window,
        width=out_width * factor,
        height=out_height * factor,
        indexes=[1],
        resampling_method="nearest",
    )
    samples = region.array.data[0].astype(np.float32)
    fraction = samples.reshape(out_height, factor, out_width, factor).mean(axis=(1, 3))
    fraction = np.clip(fraction, 0.0, 1.0)
    first = np.array(info.palette[0][:3], dtype=np.float32)
    last = np.array(info.palette[-1][:3], dtype=np.float32)
    blended = first[:, None, None] + (last - first)[:, None, None] * fraction
    pixels = np.clip(blended, 0, 255).astype(np.uint8)
    if np.array_equal(first, np.full(3, first[0])) and np.array_equal(
        last, np.full(3, last[0])
    ):
        pixels = pixels[:1]
    invalid = np.ma.getmaskarray(region.array)[0]
    valid = ~invalid.reshape(out_height, factor, out_width, factor).any(axis=(1, 3))
    return pixels, valid
