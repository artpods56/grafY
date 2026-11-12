import math
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from grafy_tiler.grant import Grant
from grafy_tiler.raster import (
    PageNotFound,
    SourceError,
    SourceMismatch,
    SourceTooLarge,
    describe,
    level_size,
    max_level_for,
    min_level_for,
    source_path,
    thumbnail_size,
    tile_window,
)
from grafy_tiler.settings import Settings
from tests.conftest import BUCKET, SHA, Writer


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [(1, 1, 0), (2, 1, 1), (512, 512, 9), (513, 10, 10), (14652, 8620, 14)],
)
def test_top_level_is_the_power_of_two_that_covers_the_longest_side(
    width: int, height: int, expected: int
) -> None:
    assert max_level_for(width, height) == expected


def test_each_level_halves_and_rounds_up() -> None:
    top = max_level_for(14652, 8620)
    assert level_size(14652, 8620, top, top) == (14652, 8620)
    assert level_size(14652, 8620, top, top - 1) == (7326, 4310)
    assert level_size(14652, 8620, top, top - 2) == (3663, 2155)
    assert level_size(14652, 8620, top, top - 3) == (1832, 1078)
    assert level_size(14652, 8620, top, 0) == (1, 1)


def test_min_level_is_the_first_level_that_fits_one_tile() -> None:
    assert min_level_for(14652, 8620, 512) == 9  # level 9 is 458 x 270
    assert min_level_for(300, 200, 512) == max_level_for(300, 200)  # already one tile


def test_full_resolution_edge_tile_is_cropped_not_padded() -> None:
    width, height = 1300, 700
    top = max_level_for(width, height)  # 11
    window, out_width, out_height = tile_window(width, height, top, 512, top, 2, 1)  # pyright: ignore[reportGeneralTypeIssues]
    assert (window.col_off, window.row_off) == (1024, 512)
    assert (window.width, window.height) == (276, 188)
    assert (out_width, out_height) == (276, 188)


def test_lower_levels_cover_more_source_per_tile() -> None:
    width, height = 1300, 700
    top = max_level_for(width, height)
    window, out_width, out_height = tile_window(width, height, top, 512, top - 1, 0, 0)  # pyright: ignore[reportGeneralTypeIssues]
    assert (window.col_off, window.row_off, window.width, window.height) == (
        0,
        0,
        1024,
        700,
    )
    assert (out_width, out_height) == (512, 350)


def test_tiles_of_one_level_tile_the_level_without_gaps() -> None:
    width, height = 1300, 700
    top = max_level_for(width, height)
    level = top - 1
    level_width, level_height = level_size(width, height, top, level)
    covered = 0
    for y in range(math.ceil(level_height / 512)):
        for x in range(math.ceil(level_width / 512)):
            placed = tile_window(width, height, top, 512, level, x, y)
            assert placed is not None
            covered += placed[1] * placed[2]
    assert covered == level_width * level_height


@pytest.mark.parametrize(
    ("level", "x", "y"),
    [(-1, 0, 0), (12, 0, 0), (11, 3, 0), (11, 0, 2), (11, -1, 0), (5, 1, 0)],
)
def test_tiles_outside_the_pyramid_have_no_window(level: int, x: int, y: int) -> None:
    assert tile_window(1300, 700, 11, 512, level, x, y) is None


def test_thumbnail_keeps_the_aspect_ratio_and_never_upscales() -> None:
    assert thumbnail_size(14652, 8620, 256) == (256, 151)
    assert thumbnail_size(100, 50, 256) == (100, 50)
    assert thumbnail_size(1, 5000, 128) == (1, 128)


# -- describing real files -------------------------------------------------


def test_opaque_eight_bit_scan_is_jpeg(settings: Settings, gray8: Writer) -> None:
    info = describe(str(gray8()), 0, settings)
    assert (info.width, info.height, info.kind, info.tile_format) == (
        1300,
        700,
        "gray",
        "jpg",
    )
    assert not info.has_alpha and not info.georeferenced and info.value_range is None
    assert info.max_level == 11 and info.page_count == 1


def test_transparency_and_palettes_are_png(
    settings: Settings, rgba: Writer, palette: Writer
) -> None:
    assert describe(str(rgba()), 0, settings).tile_format == "png"
    info = describe(str(palette()), 0, settings)
    assert (info.kind, info.tile_format, info.resampling) == (
        "palette",
        "png",
        "nearest",
    )


def test_overviews_select_nearest_resampling_and_georeferencing_is_reported(
    settings: Settings, rgb_tiled_with_overviews: Writer
) -> None:
    info = describe(str(rgb_tiled_with_overviews()), 0, settings)
    assert (info.resampling, info.overview_count) == ("nearest", 3)
    assert info.georeferenced and info.crs == "EPSG:3857"
    assert info.bounds_wgs84 is not None and 17 < info.bounds_wgs84[0] < 19


def test_sixteen_bit_and_float_get_one_fixed_range(
    settings: Settings, uint16: Writer, float32: Writer
) -> None:
    low, high = describe(str(uint16()), 0, settings).value_range or (0, 0)
    assert 1000 <= low < high <= 5000
    low, high = describe(str(float32()), 0, settings).value_range or (0, 0)
    assert -1.5 <= low < high <= 2.5


def test_pages_are_counted_and_selected(settings: Settings, multipage: Writer) -> None:
    path = str(multipage())
    first, second = describe(path, 0, settings), describe(path, 1, settings)
    assert first.page_count == second.page_count == 3
    assert (first.width, second.width) == (320, 400)
    with pytest.raises(PageNotFound):
        describe(path, 3, settings)


def test_page_limit(settings: Settings, multipage: Writer) -> None:
    limited = settings.model_copy(update={"max_pages": 2})
    with pytest.raises(SourceTooLarge):
        describe(str(multipage()), 0, limited)


def test_pixel_limit(settings: Settings, gray8: Writer) -> None:
    limited = settings.model_copy(update={"max_pixels": 1000})
    with pytest.raises(SourceTooLarge):
        describe(str(gray8()), 0, limited)


def test_garbage_is_a_source_error(settings: Settings, garbage: Writer) -> None:
    with pytest.raises(SourceError):
        describe(str(garbage()), 0, settings)


def test_a_png_is_not_read_as_a_tiff(settings: Settings, storage_root: Path) -> None:
    from PIL import Image

    path = storage_root / BUCKET / "photo.tif"
    Image.new("RGB", (40, 40)).save(path, format="PNG")
    with pytest.raises(SourceError):
        describe(str(path), 0, settings)


def test_large_source_without_overviews_gets_a_lazy_overview_level(
    settings: Settings, bilevel_lines: Writer
) -> None:
    small = describe(str(bilevel_lines()), 0, settings)
    assert small.overview_level is None  # 3000 px is under the threshold
    big_settings = settings.model_copy(update={"overview_min_pixels": 2048})
    big = describe(str(bilevel_lines()), 0, big_settings)
    assert big.overview_level is not None
    assert (
        max(level_size(big.width, big.height, big.max_level, big.overview_level))
        <= 2048
    )


# -- source paths ---------------------------------------------------------


def test_s3_path_is_built_from_validated_grant_fields(settings: Settings) -> None:
    s3 = settings.model_copy(update={"storage": "s3"})
    grant = Grant(BUCKET, "ws/a/b.tif", SHA, 10, 0, 0)
    assert source_path(s3, grant) == f"/vsis3/{BUCKET}/ws/a/b.tif"


def test_local_path_must_exist_and_match_the_granted_size(
    settings: Settings, gray8: Writer, grant_for: Callable[..., Grant]
) -> None:
    gray8()
    assert source_path(settings, grant_for("gray8.tif")).endswith("gray8.tif")
    with pytest.raises(SourceMismatch):
        source_path(settings, grant_for("gray8.tif", size=5))
    with pytest.raises(SourceError):
        source_path(settings, Grant(BUCKET, "missing.tif", SHA, 5, 0, 0))


def test_local_path_cannot_follow_a_symlink_out_of_the_root(
    settings: Settings, storage_root: Path, tmp_path: Path
) -> None:
    secret = tmp_path / "secret.tif"
    secret.write_bytes(b"secret")
    os.symlink(secret, storage_root / BUCKET / "link.tif")
    with pytest.raises(SourceError):
        source_path(settings, Grant(BUCKET, "link.tif", SHA, 6, 0, 0))
