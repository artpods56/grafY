"""Read a bounded native TIFF crop as PNG with source pixel placement."""

import json
import math
from dataclasses import dataclass
from typing import Final

import numpy as np
from affine import Affine
from rasterio.enums import ColorInterp, MaskFlags
from rasterio.errors import RasterioError
from rasterio.io import DatasetReader
from rio_tiler.errors import InvalidFormat
from rio_tiler.utils import render as encode_image

from grafy_tiler.raster import (
    SourceError,
    SourceTooLarge,
    check_page,
    open_page,
    page_count,
    pixel_window,
)
from grafy_tiler.settings import Settings

# Contract limits. They are constants, not settings: the API's callers are told
# these numbers, so an operator must not be able to move them under the client.
WINDOW_MAX_PIXELS: Final = 1_000_000
WINDOW_MAX_PNG_BYTES: Final = 8 * 1024 * 1024
# A response header has to survive HTTP framing; WKT for a projected CRS is
# ~2 kB once JSON-escaped, so this only trips on something pathological.
WINDOW_MAX_HEADER_BYTES: Final = 8 * 1024

_GRAY: Final = (ColorInterp.gray,)
_RGB: Final = (ColorInterp.red, ColorInterp.green, ColorInterp.blue)
# A band past the picture bands is only allowed to be the transparency channel:
# rasterio reports internal masks through `mask_flag_enums`, never as a band.
_ALPHA: Final = (ColorInterp.alpha,)


class WindowOutOfBounds(Exception):
    """The rectangle is not strictly inside the granted page."""


class WindowTooLarge(Exception):
    """The crop, its PNG, or the source blocks it would decode exceed a limit."""


class UnsupportedPixelFormat(Exception):
    """The page is not native uint8 grayscale or RGB that PNG can carry exactly."""


@dataclass(frozen=True, slots=True)
class WindowRead:
    """The PNG body and the JSON value of its ``X-Grafy-Window`` header."""

    png: bytes
    header: str


@dataclass(frozen=True, slots=True)
class _Layout:
    """Picture and transparency inputs for one native window."""

    indexes: tuple[int, ...]
    alpha_index: int | None
    mask_indexes: tuple[int, ...]


def limit_output_pixels(width: int, height: int) -> None:
    """Refuse a crop that is too big to be worth reading before reading it."""
    if width * height > WINDOW_MAX_PIXELS:
        raise WindowTooLarge(f"a window holds at most {WINDOW_MAX_PIXELS} pixels")


def check_output_shape(width: int, height: int) -> None:
    """A window is a non-empty rectangle; anything else is a bad request."""
    if width < 1 or height < 1:
        raise WindowOutOfBounds("window width and height must be positive")


def read_window(
    path: str,
    page: int,
    col: int,
    row: int,
    width: int,
    height: int,
    settings: Settings,
) -> WindowRead:
    """Read ``[col, col+width) x [row, row+height)`` of one page as PNG.

    Runs on a render thread. Validate source layout, placement and decode
    budget before reading any pixels.
    """
    check_output_shape(width, height)
    limit_output_pixels(width, height)
    pages = page_count(path)
    check_page(page, pages, settings)
    with open_page(path, page) as ds:
        check_bounds(ds.width, ds.height, col, row, width, height)
        if ds.width * ds.height > settings.max_pixels:
            raise SourceTooLarge("image has too many pixels")
        layout = _layout(ds)
        check_decode_bound(ds, layout, col, row, width, height, settings)
        affine, crs = _georeference(ds, col, row)
        placement = _placement_json(col, row, width, height, affine, crs)
        png = _encode_png(_read_bands(ds, layout, col, row, width, height))
    return WindowRead(png, placement)


def check_bounds(
    width: int, height: int, col: int, row: int, out_width: int, out_height: int
) -> None:
    """Half-open and strictly inside: a window is never clipped or padded."""
    if col < 0 or row < 0:
        raise WindowOutOfBounds("window origin must not be negative")
    if col + out_width > width or row + out_height > height:
        raise WindowOutOfBounds("window is outside the image")


def _layout(ds: DatasetReader) -> _Layout:
    """The band plan, or a refusal when "PNG of these values" is not one thing.

    Supported: uint8 grayscale and uint8 RGB (including JPEG YCbCr decoded to
    RGB by GDAL), each optionally carrying
    transparency as an alpha band, an internal mask, or nodata. Everything else
    (palette, CMYK, 16-bit, float, multi-spectral, sub-byte) would need a
    conversion decision this path does not get to make.
    """
    # GDAL can report RGB(A) band roles after a photometric conversion.
    structure = ds.tags(ns="IMAGE_STRUCTURE")
    source_color = structure.get("SOURCE_COLOR_SPACE")
    if source_color and not (
        source_color == "YCbCr"
        and structure.get("COMPRESSION") == "YCbCr JPEG"
        and tuple(ds.colorinterp) == _RGB
    ):
        raise UnsupportedPixelFormat("unsupported TIFF color conversion")
    if any(dtype != "uint8" for dtype in ds.dtypes):
        raise UnsupportedPixelFormat("windows are limited to uint8 samples")
    for index in ds.indexes:
        if ds.tags(index, ns="IMAGE_STRUCTURE").get("NBITS", "8") != "8":
            raise UnsupportedPixelFormat("windows are limited to 8-bit samples")

    interps = tuple(ds.colorinterp)
    if interps[: len(_GRAY)] == _GRAY:
        indexes: tuple[int, ...] = (1,)
    elif interps[: len(_RGB)] == _RGB:
        indexes = (1, 2, 3)
    else:
        raise UnsupportedPixelFormat("windows are limited to grayscale or RGB bands")
    extras = interps[len(indexes) :]
    if extras not in ((), _ALPHA):
        raise UnsupportedPixelFormat("this image has bands a window cannot carry")

    alpha_index = len(indexes) + 1 if extras else None
    flags_by_band = ds.mask_flag_enums
    mask_indexes = tuple(
        index
        for index in indexes
        if MaskFlags.all_valid not in flags_by_band[index - 1]
        and MaskFlags.alpha not in flags_by_band[index - 1]
    )
    return _Layout(indexes, alpha_index, mask_indexes)


def check_decode_bound(
    ds: DatasetReader,
    layout: _Layout,
    col: int,
    row: int,
    width: int,
    height: int,
    settings: Settings,
) -> None:
    """Bound what GDAL decodes, which is blocks, not the crop.

    A crop touches whole blocks or whole strips, and a striped or coarsely tiled
    file can make a small window decode the whole image. The estimate is the
    block envelope of the crop times the bands actually read.
    """
    bands = ds.count + len(layout.mask_indexes)
    decoded = _block_envelope(ds, col, row, width, height) * bands
    if decoded > settings.max_window_decode_bytes:
        raise WindowTooLarge("this window would decode too much of the source")


def _block_envelope(
    ds: DatasetReader,
    col: int,
    row: int,
    width: int,
    height: int,
) -> int:
    pixels = 0
    for block_height, block_width in ds.block_shapes:
        block_height, block_width = max(1, block_height), max(1, block_width)
        rows = (row + height - 1) // block_height - row // block_height + 1
        columns = (col + width - 1) // block_width - col // block_width + 1
        pixels = max(pixels, rows * block_height * columns * block_width)
    return pixels


def _read_bands(
    ds: DatasetReader,
    layout: _Layout,
    col: int,
    row: int,
    width: int,
    height: int,
) -> np.ndarray:
    """(bands, height, width) uint8: the picture bands, then alpha when needed.

    A 1:1 window read is a plain block copy on GDAL's side; no out_shape, no
    resampling, no masked array that would flatten a graded alpha to a boolean.
    """
    window = pixel_window(col, row, width, height)
    indexes = list(layout.indexes)
    if layout.alpha_index is not None:
        indexes.append(layout.alpha_index)
    bands = ds.read(indexes=indexes, window=window)
    if not layout.mask_indexes:
        return bands
    masks = ds.read_masks(indexes=list(layout.mask_indexes), window=window)
    validity = np.minimum.reduce(masks, axis=0)
    if layout.alpha_index is not None:
        # GDAL's internal mask or nodata can take precedence over the alpha
        # band's mask flags. Preserve both by keeping the lower opacity.
        np.minimum(bands[-1], validity, out=bands[-1])
        return bands
    return np.concatenate([bands, validity[np.newaxis]])


def _encode_png(bands: np.ndarray) -> bytes:
    """Encode unscaled uint8 samples with GDAL's lossless PNG driver."""
    try:
        png = encode_image(bands, img_format="PNG")
    except InvalidFormat as error:
        raise SourceError("this window could not be encoded as PNG") from error
    if len(png) > WINDOW_MAX_PNG_BYTES:
        raise WindowTooLarge("the PNG for this window is larger than 8 MiB")
    return png


def _georeference(
    ds: DatasetReader, col: int, row: int
) -> tuple[tuple[float, ...] | None, str | None]:
    """Crop-local pixel corner to source CRS, or (None, None) if unusable."""
    crs = ds.crs
    transform = ds.transform
    if crs is None or transform.is_identity or transform.is_degenerate:
        return None, None
    if not all(math.isfinite(value) for value in transform):
        return None, None
    try:
        wkt = crs.to_wkt()
    except RasterioError:
        return None, None
    if wkt.strip() == "":
        return None, None
    # Composing with the crop translation keeps the linear part (so rotation and
    # shear survive) and moves the origin to the crop's own (0, 0).
    shifted = transform @ Affine.translation(col, row)
    coefficients = (shifted.a, shifted.b, shifted.c, shifted.d, shifted.e, shifted.f)
    if not all(math.isfinite(value) for value in coefficients):
        return None, None
    return coefficients, wkt


def _placement_json(
    col: int,
    row: int,
    width: int,
    height: int,
    affine: tuple[float, ...] | None,
    crs: str | None,
) -> str:
    """The `X-Grafy-Window` value: ASCII, one line, no extra members."""
    document = json.dumps(
        {
            "col": col,
            "row": row,
            "width": width,
            "height": height,
            "affine": None if affine is None else [float(value) for value in affine],
            "crs": crs,
        },
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    if len(document.encode("ascii")) > WINDOW_MAX_HEADER_BYTES:
        raise WindowTooLarge("the placement header for this window is too large")
    return document
