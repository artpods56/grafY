"""Turn a window of a TIFF into JPEG or PNG bytes.

One function, :func:`render_region`, serves tiles, thumbnails and the lazy
overview: the caller picks the source window and the output size, this module
makes the pixels displayable. Pixel space only; georeferencing is ignored.

TODO(geo-open-on-map): a later "open on map" for georeferenced TIFFs adds a
Web Mercator reader here (rio-tiler's ``Reader`` over the same source). It must
stay a separate path: pixel-space tiles are what non-georeferenced scans need.
"""

import numpy as np
from numpy.typing import NDArray
from rasterio.io import DatasetReader
from rasterio.windows import Window
from rio_tiler.models import ImageData
from rio_tiler.reader import read as read_region

from .raster import ImageInfo, TileFormat, is_bilevel

type Pixels = NDArray[np.uint8]

# Samples per output pixel, per axis, when blending a two-colour scan.
_SUPERSAMPLE = 8


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
    values = region.array.data
    valid = ~np.ma.getmaskarray(region.array).any(axis=0)

    if info.bit_depth < 8:
        values = values * (255.0 / ((1 << info.bit_depth) - 1))
    elif precise:
        assert info.value_range is not None
        low, high = info.value_range
        values = (values - low) * (255.0 / (high - low))
    pixels = np.clip(np.nan_to_num(values), 0, 255).astype(np.uint8)

    if info.kind == "cmyk":
        pixels = _cmyk_to_rgb(pixels)
    return pixels, valid


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
