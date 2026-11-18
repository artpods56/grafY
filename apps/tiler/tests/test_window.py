"""`GET /window`: exact source pixels, and an honest account of where they came from.

Every test compares the PNG with the stored file rather than with a rendered
tile, because the whole point of the route is that it is not the display path.
"""

import io
from collections.abc import Callable
from pathlib import Path
from typing import Any, Self

import httpx
import numpy as np
import pytest
import rasterio
from affine import Affine
from fastapi import FastAPI
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator
from rasterio.windows import Window

from grafy_tiler import window as window_module
from grafy_tiler.service import TileService
from grafy_tiler.settings import Settings
from grafy_tiler.window import (
    WINDOW_MAX_PNG_BYTES,
    WindowTooLarge,
    read_window,
)
from tests.conftest import BUCKET, Writer

WINDOW_HEADER = "X-Grafy-Window"


# The API parses this header with a strict, closed model. Kept as a replica so
# a tiler change that would break its caller fails here instead.
class Placement(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, allow_inf_nan=False
    )

    col: int = Field(ge=0)
    row: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    affine: tuple[float, float, float, float, float, float] | None
    crs: str | None = Field(min_length=1)

    @model_validator(mode="after")
    def _together(self) -> Self:
        if (self.affine is None) != (self.crs is None):
            raise ValueError("affine and CRS must be present together")
        return self


def _pixels(response: httpx.Response) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(response.content)))


def _placement(response: httpx.Response) -> Placement:
    return Placement.model_validate_json(response.headers[WINDOW_HEADER])


def _stored(path: Path, col: int, row: int, width: int, height: int) -> np.ndarray:
    """(bands, height, width) as GDAL keeps them, straight from the file."""
    with rasterio.open(path) as ds:
        return ds.read(window=Window(col, row, width, height))


async def _window(
    client: httpx.AsyncClient, headers: dict[str, str], **rectangle: int
) -> httpx.Response:
    return await client.get("/window", headers=headers, params=rectangle)


async def test_a_window_is_the_crop_that_was_asked_for(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], gray8: Writer
) -> None:
    path = gray8()
    rectangle = {"col": 17, "row": 23, "width": 37, "height": 11}
    response = await _window(client, auth(path.name), **rectangle)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert np.array_equal(_pixels(response), _stored(path, **rectangle)[0])
    placement = _placement(response)
    assert (placement.col, placement.row, placement.width, placement.height) == (
        17,
        23,
        37,
        11,
    )
    repeated = await _window(client, auth(path.name), **rectangle)
    assert repeated.content == response.content
    assert repeated.headers[WINDOW_HEADER] == response.headers[WINDOW_HEADER]


async def test_jpeg_ycbcr_window_preserves_the_decoded_rgb_pixels(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    rgb_tiled_with_overviews: Writer,
) -> None:
    path = rgb_tiled_with_overviews()
    source = path.with_name("ycbcr.tif")
    with rasterio.open(path) as original:
        profile = original.profile
        profile.update(
            compress="JPEG",
            photometric="YCbCr",
            interleave="pixel",
            tiled=True,
            blockxsize=256,
            blockysize=256,
        )
        with rasterio.open(source, "w", **profile) as output:
            output.write(original.read())

    rectangle = {"col": 241, "row": 245, "width": 37, "height": 29}
    response = await _window(client, auth(source.name), **rectangle)
    assert response.status_code == 200, response.text
    assert np.array_equal(
        _pixels(response), np.moveaxis(_stored(source, **rectangle), 0, -1)
    )
    assert _placement(response).col == 241


async def test_the_stored_value_is_not_stretched(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], gray8: Writer
) -> None:
    """`gray8` is a 0..255 ramp: a crop of it keeps its own narrow values, which
    a display render would have widened."""
    path = gray8()
    rectangle = {"col": 100, "row": 3, "width": 40, "height": 7}
    response = await _window(client, auth(path.name), **rectangle)
    crop = _pixels(response)
    whole = _stored(path, 0, 0, 1300, 700)[0]
    assert (int(whole.min()), int(whole.max())) == (0, 255)
    assert int(crop.max()) < 60  # the ramp's own values, not a widened 0..255
    assert np.array_equal(crop, _stored(path, **rectangle)[0])


async def test_a_window_reaches_the_last_pixel_and_no_further(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], gray8: Writer
) -> None:
    path = gray8()  # 1300 x 700
    headers = auth(path.name)
    corner = await _window(client, headers, col=1299, row=699, width=1, height=1)
    assert corner.status_code == 200
    assert _pixels(corner).shape == (1, 1)
    assert _pixels(corner)[0, 0] == _stored(path, 1299, 699, 1, 1)[0, 0, 0]

    over = await _window(client, headers, col=1299, row=699, width=2, height=1)
    assert over.status_code == 422
    assert (
        await _window(client, headers, col=1299, row=699, width=1, height=2)
    ).status_code == 422


@pytest.mark.parametrize(
    "rectangle",
    [
        {"col": -1, "row": 0, "width": 4, "height": 4},
        {"col": 0, "row": -1, "width": 4, "height": 4},
        {"col": 0, "row": 0, "width": 0, "height": 4},
        {"col": 0, "row": 0, "width": 4, "height": -2},
        {"col": 1300, "row": 0, "width": 1, "height": 1},  # starts outside
        {"col": 0, "row": 700, "width": 1, "height": 1},
        {"col": 1295, "row": 0, "width": 10, "height": 1},  # ends outside
    ],
)
async def test_a_window_that_is_not_wholly_inside_is_refused(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    gray8: Writer,
    rectangle: dict[str, int],
) -> None:
    response = await _window(client, auth(gray8().name), **rectangle)
    assert response.status_code == 422, rectangle


async def test_fractional_syntax_is_refused(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], gray8: Writer
) -> None:
    response = await client.get(
        "/window",
        headers=auth(gray8().name),
        params={"col": "1.0", "row": "0", "width": "1", "height": "1"},
    )
    assert response.status_code == 422


async def test_a_window_on_a_georeferenced_page_carries_an_affine(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    rgb_tiled_with_overviews: Writer,
) -> None:
    path = rgb_tiled_with_overviews()
    rectangle = {"col": 13, "row": 29, "width": 41, "height": 17}
    response = await _window(client, auth(path.name), **rectangle)
    placement = _placement(response)

    with rasterio.open(path) as ds:
        source = ds.transform
        assert placement.crs is not None and "Pseudo-Mercator" in placement.crs
    assert placement.affine is not None
    a, b, c, d, e, f = placement.affine
    # Crop-local pixel corners land where the full-raster transform puts them.
    for x, y in ((0, 0), (41, 0), (0, 17), (41, 17)):
        assert (a * x + b * y + c, d * x + e * y + f) == pytest.approx(
            source @ (x + 13, y + 29)
        )


async def test_rotation_and_shear_survive_as_an_affine(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    rotated_geotiff: Writer,
) -> None:
    path = rotated_geotiff()
    rectangle = {"col": 7, "row": 5, "width": 13, "height": 9}
    response = await _window(client, auth(path.name), **rectangle)
    placement = _placement(response)

    source = Affine(2.0, 0.5, 500_000.0, -0.5, -2.0, 4_000_000.0)
    assert placement.affine is not None
    a, b, c, d, e, f = placement.affine
    assert (b, d) != (0.0, 0.0)  # the crop is not axis-aligned in source CRS
    for x, y in ((0, 0), (13, 0), (0, 9), (13, 9)):
        assert (a * x + b * y + c, d * x + e * y + f) == pytest.approx(
            source @ (x + 7, y + 5)
        )
    assert np.array_equal(
        _pixels(response), _stored(path, **rectangle).transpose(1, 2, 0)
    )


async def test_a_scan_without_georeferencing_reports_no_affine(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], gray8: Writer
) -> None:
    response = await _window(
        client, auth(gray8().name), col=0, row=0, width=8, height=8
    )
    placement = _placement(response)
    assert (placement.affine, placement.crs) == (None, None)
    # The offsets are still the answer to where the crop came from.
    assert (placement.col, placement.row) == (0, 0)


async def test_a_window_ignores_the_overviews_the_source_carries(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    rgb_tiled_with_overviews: Writer,
) -> None:
    """The pyramid exists and is used by tiles; a window must not be a resample."""
    path = rgb_tiled_with_overviews()
    with rasterio.open(path) as ds:
        assert ds.overviews(1) == [2, 4, 8]
    rectangle = {"col": 640, "row": 320, "width": 64, "height": 64}
    response = await _window(client, auth(path.name), **rectangle)
    assert np.array_equal(
        _pixels(response), _stored(path, **rectangle).transpose(1, 2, 0)
    )


async def test_a_graded_alpha_band_is_carried_as_it_is_stored(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    rgb_alpha_ramp: Writer,
) -> None:
    path = rgb_alpha_ramp()
    rectangle = {"col": 3, "row": 2, "width": 20, "height": 5}
    response = await _window(client, auth(path.name), **rectangle)

    pixels = _pixels(response)
    assert Image.open(io.BytesIO(response.content)).mode == "RGBA"
    bands = _stored(path, **rectangle)
    assert np.array_equal(pixels[..., :3], bands[:3].transpose(1, 2, 0))
    assert np.array_equal(pixels[..., 3], bands[3])
    assert len(np.unique(pixels[..., 3])) > 2  # not flattened to on/off


async def test_an_internal_mask_becomes_an_alpha_channel(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    gray_internal_mask: Writer,
) -> None:
    path = gray_internal_mask()  # transparent in the bottom-right quadrant
    rectangle = {"col": 24, "row": 24, "width": 20, "height": 20}
    response = await _window(client, auth(path.name), **rectangle)

    pixels = _pixels(response)
    assert Image.open(io.BytesIO(response.content)).mode == "LA"
    assert np.array_equal(pixels[..., 0], np.full((20, 20), 9))
    expected = np.full((20, 20), 255, dtype=np.uint8)
    expected[8:, 8:] = 0  # source rows and columns 32 up
    assert np.array_equal(pixels[..., 1], expected)


async def test_an_internal_mask_preserves_alpha_at_valid_pixels(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    rgb_alpha_ramp: Writer,
) -> None:
    path = rgb_alpha_ramp()
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True), rasterio.open(path, "r+") as ds:
        mask = np.full((ds.height, ds.width), 255, dtype=np.uint8)
        mask[2, 4] = 0
        ds.write_mask(mask)
    response = await _window(client, auth(path.name), col=3, row=2, width=3, height=1)
    assert response.status_code == 200
    assert _pixels(response).tolist() == [
        [[250, 3, 0, 3], [250, 4, 0, 0], [250, 5, 0, 5]]
    ]


async def test_nodata_marks_a_pixel_without_changing_its_value(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    nodata_gray: Writer,
) -> None:
    path = nodata_gray()  # 40 x 40 of 7 with one 0 at (20, 20)
    rectangle = {"col": 18, "row": 18, "width": 6, "height": 6}
    response = await _window(client, auth(path.name), **rectangle)

    pixels = _pixels(response)
    assert np.array_equal(pixels[..., 0], _stored(path, **rectangle)[0])
    assert pixels[2, 2].tolist() == [0, 0]  # stored value, fully transparent
    assert pixels[0, 0].tolist() == [7, 255]


@pytest.mark.parametrize(
    ("fixture", "name"),
    [
        ("uint16", "not 8-bit"),
        ("float32", "not integer samples"),
        ("palette", "a colour table to interpret"),
        ("cmyk", "four process colours"),
        ("cmyk_libtiff", "CMYK auto-converted by the display reader"),
    ],
)
async def test_a_window_refuses_pixels_it_would_have_to_guess(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    request: pytest.FixtureRequest,
    fixture: str,
    name: str,
) -> None:
    path: Path = request.getfixturevalue(fixture)()
    response = await _window(client, auth(path.name), col=0, row=0, width=16, height=16)
    assert response.status_code == 415, name


@pytest.mark.parametrize(
    "count,options",
    [(1, {"nbits": 4}), (4, {"compress": "JPEG", "photometric": "CMYK"})],
)
async def test_source_metadata_can_make_a_uint8_layout_unsupported(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    storage_root: Path,
    count: int,
    options: dict[str, Any],
) -> None:
    name = "unsupported.tif"
    with rasterio.open(
        storage_root / BUCKET / name,
        "w",
        driver="GTiff",
        width=32,
        height=16,
        count=count,
        dtype="uint8",
        **options,
    ) as ds:
        ds.write(np.full((count, 16, 32), 7, dtype=np.uint8))
    response = await _window(client, auth(name), col=3, row=2, width=4, height=3)
    assert response.status_code == 415


async def test_the_page_comes_from_the_grant(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], multipage: Writer
) -> None:
    name = multipage().name  # pages are 320, 400 and 480 wide, all 240 high
    second = await _window(
        client, auth(name, page=1), col=399, row=239, width=1, height=1
    )
    assert second.status_code == 200
    assert _pixels(second)[0, 0][1] == 255  # page 1 is pure green
    assert (
        await _window(client, auth(name, page=1), col=400, row=0, width=1, height=1)
    ).status_code == 422
    assert (
        await _window(client, auth(name, page=5), col=0, row=0, width=4, height=4)
    ).status_code == 404


async def test_the_output_pixel_limit_is_checked_before_the_source_is_read(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], gray8: Writer
) -> None:
    headers = auth(gray8().name)
    # 1,000,000 pixels is allowed by the limit; this file is too small for it, so
    # the request fails on bounds. One pixel more than the limit fails on size.
    assert (
        await _window(client, headers, col=0, row=0, width=1000, height=1000)
    ).status_code == 422
    assert (
        await _window(client, headers, col=0, row=0, width=1000, height=1001)
    ).status_code == 413


async def test_a_png_larger_than_eight_mebibytes_is_refused(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    gray8: Writer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert WINDOW_MAX_PNG_BYTES == 8 * 1024 * 1024
    rectangle = {"col": 0, "row": 0, "width": 200, "height": 200}
    headers = auth(gray8().name)
    assert (await _window(client, headers, **rectangle)).status_code == 200
    # The check is on the encoded body, so a smaller cap has to refuse the very
    # crop that just succeeded.
    monkeypatch.setattr(window_module, "WINDOW_MAX_PNG_BYTES", 128)
    assert (await _window(client, headers, **rectangle)).status_code == 413


async def test_a_coarsely_stored_source_is_bounded_by_what_it_decodes(
    coarsely_tiled_gray: Writer, settings: Settings
) -> None:
    """One tile means any window decodes all of it: 1 MB here. Harmless, but it
    is the same shape as a gigabyte scan, so the bound is what stops that."""
    path = coarsely_tiled_gray()
    assert settings.max_window_decode_bytes == 64 * 1024 * 1024
    narrow = settings.model_copy(update={"max_window_decode_bytes": 512 * 1024})

    with pytest.raises(WindowTooLarge):
        read_window(str(path), 0, 10, 10, 8, 8, settings=narrow)

    read = read_window(str(path), 0, 10, 10, 8, 8, settings=settings)
    assert np.array_equal(
        np.asarray(Image.open(io.BytesIO(read.png))),
        _stored(path, 10, 10, 8, 8)[0],
    )


async def test_windows_write_nothing_to_the_cache(
    client: httpx.AsyncClient,
    app: FastAPI,
    auth: Callable[..., dict[str, str]],
    gray8: Writer,
) -> None:
    name = gray8().name
    cache = app.state.cache
    assert cache.entry_count == 0
    await _window(client, auth(name), col=4, row=4, width=32, height=32)
    await _window(client, auth(name), col=40, row=4, width=32, height=32)
    assert (cache.entry_count, cache.total_bytes) == (0, 0)

    # The cache itself is live, so its silence above means something.
    assert (await client.get("/info", headers=auth(name))).status_code == 200
    assert cache.entry_count == 1
    assert (
        await client.get("/tiles/11/0/0.jpg", headers=auth(name))
    ).status_code == 200
    assert cache.entry_count == 2


async def test_a_window_runs_on_the_bounded_render_pool(
    client: httpx.AsyncClient,
    app: FastAPI,
    auth: Callable[..., dict[str, str]],
    gray8: Writer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service: TileService = app.state.service
    run = service.pool.run
    held: list[int] = []

    async def counted(work: Callable[[], Any]) -> Any:
        def while_scheduled() -> Any:
            held.append(service.pool.pending)
            return work()

        return await run(while_scheduled)

    monkeypatch.setattr(service.pool, "run", counted)
    response = await _window(
        client, auth(gray8().name), col=0, row=0, width=16, height=16
    )
    assert response.status_code == 200
    assert held == [1]  # it waited on the pool's slots like any other render
    assert service.pool.pending == 0


def test_a_placement_larger_than_a_header_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(window_module, "WINDOW_MAX_HEADER_BYTES", 40)
    with pytest.raises(WindowTooLarge):
        window_module._placement_json(  # pyright: ignore[reportPrivateUsage]
            0, 0, 2, 2, (1.0, 0.0, 0.0, 0.0, -1.0, 0.0), 'PROJCS["a"]' * 4
        )
