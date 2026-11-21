import io
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import httpx
import numpy as np
import pytest
import rasterio
from fastapi import FastAPI
from grafy_crypto.grants import Grant
from morecantile import Tile
from PIL import Image
from rasterio.transform import Affine, from_bounds
from rio_tiler.constants import WEB_MERCATOR_TMS

from grafy_tiler import service
from grafy_tiler.raster import RENDERER_VERSION
from grafy_tiler.service import Overloaded, RenderPool
from tests.conftest import BUCKET, GRANT_HEADER, Writer

_TILE = "/geo/tiles/3/4/3"


def _open_image(response: httpx.Response) -> Image.Image:
    assert response.status_code == 200, response.text
    assert response.headers["X-Grafy-Renderer"] == RENDERER_VERSION
    return Image.open(io.BytesIO(response.content))


def _transform(width: int, height: int) -> Affine:
    return from_bounds(*WEB_MERCATOR_TMS.xy_bounds(Tile(4, 3, 3)), width, height)


@pytest.mark.parametrize(
    ("extension", "media_type"), [("png", "image/png"), ("jpg", "image/jpeg")]
)
@pytest.mark.parametrize("zoom", [0, 3, 24])
async def test_geo_tile_renders_mercator_tile(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    storage_root: Path,
    extension: str,
    media_type: str,
    zoom: int,
) -> None:
    # Geographic source coordinates require a reprojection to the tile grid.
    path = storage_root / BUCKET / "geographic.tif"
    x, y = (0, 0) if zoom == 0 else (1 << (zoom - 1), (1 << (zoom - 1)) - 1)
    bounds = WEB_MERCATOR_TMS.bounds(Tile(x, y, zoom))
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=256,
        height=256,
        count=1,
        dtype="uint8",
        crs="EPSG:4326",
        transform=from_bounds(*bounds, 256, 256),
    ) as ds:
        ds.write(np.full((256, 256), 70, dtype=np.uint8), 1)

    response = await client.get(
        f"/geo/tiles/{zoom}/{x}/{y}.{extension}", headers=auth(path.name)
    )
    image = _open_image(response)
    assert response.headers["content-type"] == media_type
    assert image.size == (256, 256)
    assert image.getextrema() == (70, 70)


async def test_geo_tile_outside_source_bounds_is_not_found(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    rgb_tiled_with_overviews: Writer,
) -> None:
    response = await client.get(
        "/geo/tiles/3/0/0.png", headers=auth(rgb_tiled_with_overviews().name)
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "tile is outside the image"}


@pytest.mark.parametrize(
    "path",
    [
        "/geo/tiles/25/0/0.png",
        "/geo/tiles/-1/0/0.png",
        "/geo/tiles/no/0/0.png",
        f"{_TILE}.gif",
    ],
)
async def test_invalid_geo_zoom_or_extension_is_not_found(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    gray8: Writer,
    path: str,
) -> None:
    assert (await client.get(path, headers=auth(gray8().name))).status_code == 404


async def test_geo_tile_requires_georeferencing(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], gray8: Writer
) -> None:
    response = await client.get(f"{_TILE}.png", headers=auth(gray8().name))
    assert response.status_code == 422
    assert response.json() == {"detail": "TIFF page is not georeferenced"}


@pytest.mark.parametrize("headers", [{}, {GRANT_HEADER: "invalid"}])
async def test_geo_tile_requires_a_valid_grant(
    client: httpx.AsyncClient, headers: dict[str, str]
) -> None:
    assert (await client.get(f"{_TILE}.png", headers=headers)).status_code == 403


async def test_geo_tile_reuses_disk_cache(
    client: httpx.AsyncClient,
    app: FastAPI,
    auth: Callable[..., dict[str, str]],
    grant_for: Callable[..., Grant],
    rgb_tiled_with_overviews: Writer,
) -> None:
    path = rgb_tiled_with_overviews()
    headers = auth(path.name)
    url = "/geo/tiles/3/4/2.jpg"
    response = await client.get(url, headers=headers)
    image = _open_image(response)
    assert image.mode == "RGBA" and response.headers["content-type"] == "image/png"
    assert image.getchannel("A").getextrema() == (0, 255)
    digest = grant_for(path.name).sha256
    key = f"geotile:{RENDERER_VERSION}:{digest}:0:jpg:3/4/2"
    assert app.state.cache.get(key) == response.content
    path.unlink()
    cached = await client.get(url, headers=headers)
    assert cached.status_code == 200
    assert cached.headers["content-type"] == "image/png"
    assert cached.content == response.content


async def test_geo_tile_overload_asks_the_caller_to_retry(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    rgb_tiled_with_overviews: Writer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def overloaded(*_: object) -> None:
        raise Overloaded

    monkeypatch.setattr(RenderPool, "run", overloaded)
    response = await client.get(
        f"{_TILE}.png", headers=auth(rgb_tiled_with_overviews().name)
    )
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "2"


@pytest.mark.parametrize("mask_kind", ["alpha", "nodata", "internal", "alpha_nodata"])
@pytest.mark.filterwarnings("ignore::rasterio.errors.NodataShadowWarning")
async def test_geo_tile_preserves_transparency(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    storage_root: Path,
    mask_kind: str,
) -> None:
    path = storage_root / BUCKET / f"{mask_kind}.tif"
    has_alpha = mask_kind.startswith("alpha")
    has_nodata = mask_kind.endswith("nodata")
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=256,
        height=256,
        count=4 if has_alpha else 1,
        dtype="uint8",
        crs="EPSG:3857",
        transform=_transform(256, 256),
        alpha="YES" if has_alpha else "NO",
        nodata=0 if has_nodata else None,
    ) as ds:
        data = np.full((256, 256), 200, dtype=np.uint8)
        if has_nodata:
            data[:, 192:] = 0
        for index in range(1, 4 if has_alpha else 2):
            ds.write(data, index)
        if has_alpha:
            alpha = np.full((256, 256), 128, dtype=np.uint8)
            alpha[:, :64] = 0
            ds.write(alpha, 4)
        if mask_kind == "internal":
            valid = np.full((256, 256), 255, dtype=np.uint8)
            valid[:, 192:] = 0
            ds.write_mask(valid)

    response = await client.get(f"{_TILE}.jpg", headers=auth(path.name))
    image = _open_image(response)
    assert response.headers["content-type"] == "image/png"
    alpha = image.getchannel("A")
    assert alpha.getpixel((128, 128)) == (128 if has_alpha else 255)
    assert alpha.getpixel((32 if has_alpha else 224, 128)) == 0
    if has_nodata:
        assert alpha.getpixel((224, 128)) == 0


@pytest.mark.parametrize("kind", ["uint16", "palette", "cmyk"])
async def test_geo_tile_normalizes_display_bands(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    uint16: Writer,
    palette: Writer,
    cmyk: Writer,
    kind: Literal["uint16", "palette", "cmyk"],
) -> None:
    path = {"uint16": uint16, "palette": palette, "cmyk": cmyk}[kind]()
    with rasterio.open(path, "r+") as ds:
        ds.crs = "EPSG:3857"
        ds.transform = _transform(ds.width, ds.height)
    image = _open_image(await client.get(f"{_TILE}.png", headers=auth(path.name)))
    if kind == "uint16":
        assert image.mode == "L"
        assert image.getpixel((0, 128)) == 0
        assert image.getpixel((255, 128)) == 255
    else:
        assert image.mode == "RGB"
        expected = (
            ((255, 0, 0), (0, 0, 255))
            if kind == "palette"
            else ((0, 255, 255), (0, 0, 0))
        )
        assert (image.getpixel((16, 128)), image.getpixel((240, 128))) == expected


async def test_large_geo_tiff_reuses_a_georeferenced_overview(
    client: httpx.AsyncClient,
    app: FastAPI,
    auth: Callable[..., dict[str, str]],
    storage_root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = storage_root / BUCKET / "large.tif"
    width, height = 6144, 1024
    with rasterio.open(
        path,
        "w",
        driver="GTiff",
        width=width,
        height=height,
        count=1,
        dtype="uint8",
        crs="EPSG:3857",
        transform=_transform(width, height),
    ) as ds:
        ds.write(np.full((height, width), 75, dtype=np.uint8), 1)

    headers = auth(path.name)
    first = await client.get(f"{_TILE}.png", headers=headers)
    assert _open_image(first).getextrema() == (75, 75)
    assert app.state.cache.entry_count == 3  # source info, overview, and tile

    def unexpected_overview(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("overview was rebuilt")

    monkeypatch.setattr(service, "render_geo_overview", unexpected_overview)
    # Different tile cache key, same source overview.
    second = await client.get(f"{_TILE}.jpg", headers=headers)
    assert _open_image(second).getextrema() == (75, 75)
    assert second.headers["content-type"] == "image/jpeg"
