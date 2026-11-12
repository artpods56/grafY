import io

import numpy as np
import pytest
from PIL import Image

from grafy_tiler.raster import (
    ImageInfo,
    describe,
    max_level_for,
    open_page,
    pixel_window,
    tile_window,
)
from grafy_tiler.render import (
    _cmyk_to_rgb,  # pyright: ignore[reportPrivateUsage]
    render_region,
)
from grafy_tiler.settings import Settings

from .conftest import Writer


def px(image: Image.Image, at: tuple[int, int]) -> tuple[int, ...]:
    value = image.getpixel(at)
    if isinstance(value, tuple):
        return tuple(int(v or 0) for v in value)
    return (int(value or 0),)


def _tile(
    settings: Settings, path: str, level_offset: int = 0, x: int = 0, y: int = 0
) -> tuple[Image.Image, ImageInfo]:
    info = describe(path, 0, settings)
    placed = tile_window(
        info.width,
        info.height,
        info.max_level,
        info.tile_size,
        info.max_level - level_offset,
        x,
        y,
    )
    assert placed is not None
    window, out_width, out_height = placed
    with open_page(path, 0) as ds:
        data = render_region(
            ds,
            info,
            window,
            out_width,
            out_height,
            tile_format=info.tile_format,
            jpeg_quality=90,
        )
    image = Image.open(io.BytesIO(data))
    image.load()
    return image, info


def test_eight_bit_gray_is_a_gray_jpeg_of_the_cropped_size(
    settings: Settings, gray8: Writer
) -> None:
    image, _ = _tile(settings, str(gray8()), x=2, y=1)
    assert (image.format, image.mode, image.size) == ("JPEG", "L", (276, 188))
    assert px(image, (275, 10))[0] > 200  # the right end of the ramp is bright


def test_overviewed_rgb_scan_renders_colour(
    settings: Settings, rgb_tiled_with_overviews: Writer
) -> None:
    image, info = _tile(settings, str(rgb_tiled_with_overviews()), level_offset=2)
    assert (image.format, image.mode) == (
        "JPEG",
        "RGB",
    ) and info.resampling == "nearest"
    red, _, blue = px(image, (5, 5))
    assert red > 150 and blue < 90


def test_transparency_survives_as_png_alpha(settings: Settings, rgba: Writer) -> None:
    image, info = _tile(settings, str(rgba()))
    assert (image.format, image.mode) == ("PNG", "RGBA") and info.has_alpha
    assert px(image, (10, 10))[3] == 255
    assert px(image, (image.width - 10, 10))[3] == 0


def test_one_bit_scan_keeps_thin_lines_as_gray_when_zoomed_out(
    settings: Settings, bilevel_lines: Writer
) -> None:
    # One black row in every four, shown at a quarter of the resolution, must be
    # a uniform mid-gray. Dropping to nearest would give pure white or pure black.
    image, info = _tile(settings, str(bilevel_lines()), level_offset=2)
    assert info.kind == "palette" and image.mode == "L"
    values = np.asarray(image)
    assert 150 < values.mean() < 220 and values.min() > 100


def test_palette_images_keep_exact_colours(settings: Settings, palette: Writer) -> None:
    image, _ = _tile(settings, str(palette()))
    assert image.mode == "RGB"
    assert px(image, (5, 5)) == (255, 0, 0)
    assert px(image, (image.width - 5, 5)) == (0, 0, 255)


def test_sixteen_bit_ramp_is_stretched_and_monotonic(
    settings: Settings, uint16: Writer
) -> None:
    image, info = _tile(settings, str(uint16()), level_offset=1)  # whole image
    row = np.asarray(image)[10].astype(int)
    assert info.value_range is not None
    assert row[0] < 20 and row[-1] > 235
    assert (np.diff(row) >= -3).all()  # JPEG noise only; no seams or inversions


def test_neighbouring_tiles_share_one_stretch_so_there_are_no_seams(
    settings: Settings, uint16: Writer
) -> None:
    path = str(uint16(width=1100, height=300))
    left, _ = _tile(settings, path, x=0)
    right, _ = _tile(settings, path, x=1)
    edge_left = np.asarray(left)[:, -1].astype(int).mean()
    edge_right = np.asarray(right)[:, 0].astype(int).mean()
    assert abs(edge_left - edge_right) < 8


def test_float_data_is_stretched(settings: Settings, float32: Writer) -> None:
    image, _ = _tile(settings, str(float32()))
    row = np.asarray(image)[5].astype(int)
    assert row[0] < 20 and row[-1] > 235


@pytest.mark.parametrize("dtype", ["uint8", "uint16"])
def test_raw_cmyk_is_converted_naively(
    settings: Settings, cmyk: Writer, dtype: str
) -> None:
    image, info = _tile(settings, str(cmyk(name=f"cmyk-{dtype}.tif", dtype=dtype)))
    assert info.kind == "cmyk" and image.mode == "RGB"
    cyan = px(image, (10, 10))
    black = px(image, (image.width - 10, 10))
    assert cyan[0] < 25 and cyan[1] > 230 and cyan[2] > 230
    assert max(black) < 25


def test_libtiff_converted_cmyk_still_renders(
    settings: Settings, cmyk_libtiff: Writer
) -> None:
    image, _ = _tile(settings, str(cmyk_libtiff()))
    assert px(image, (10, 10))[:3] == (0, 255, 255)


def test_cmyk_formula() -> None:
    ink = np.array(
        [[[0, 255, 0]], [[0, 0, 0]], [[0, 0, 255]], [[0, 0, 128]]], dtype=np.uint8
    )
    rgb = _cmyk_to_rgb(ink)
    assert rgb[:, 0, 0].tolist() == [255, 255, 255]  # no ink is white
    assert rgb[:, 0, 1].tolist() == [0, 255, 255]  # full cyan removes red
    assert (
        all(abs(int(v) - 127) <= 1 for v in rgb[:2, 0, 2]) and rgb[2, 0, 2] == 0
    )  # half black darkens, yellow removes blue


def test_pages_render_independently(settings: Settings, multipage: Writer) -> None:
    path = str(multipage())
    info = describe(path, 2, settings)
    with open_page(path, 2) as ds:
        data = render_region(
            ds,
            info,
            pixel_window(0, 0, info.width, info.height),
            info.width,
            info.height,
            tile_format="jpg",
            jpeg_quality=90,
        )
    pixel = px(Image.open(io.BytesIO(data)), (5, 5))
    assert pixel[2] > 200 and pixel[0] < 40  # page 3 is blue


def test_every_level_of_the_pyramid_renders(settings: Settings, gray8: Writer) -> None:
    path = str(gray8())
    info = describe(path, 0, settings)
    top = max_level_for(info.width, info.height)
    assert top == info.max_level
    for offset in range(top + 1):
        image, _ = _tile(settings, path, level_offset=offset)
        assert image.width >= 1 and image.height >= 1
