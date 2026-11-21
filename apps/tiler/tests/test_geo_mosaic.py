import io
import time
from collections.abc import Callable
from pathlib import Path

import httpx
import numpy as np
import pytest
import rasterio
from fastapi import FastAPI
from grafy_crypto.grants import Grant, GrantSource, MosaicGrant, mosaic_digest
from morecantile import Tile
from numpy.typing import NDArray
from PIL import Image
from rasterio.transform import from_bounds
from rio_tiler.constants import WEB_MERCATOR_TMS

from grafy_tiler import service
from grafy_tiler.raster import RENDERER_VERSION
from tests.conftest import BUCKET, GRANT_HEADER, SIGNING_KEY

_TILE = "/geo/mosaic/tiles/3/4/3"

type Sheet = Callable[..., Path]
type MosaicToken = Callable[..., str]


@pytest.fixture
def sheet(storage_root: Path) -> Sheet:
    """Write a 256 px EPSG:3857 sheet that exactly covers tile 3/4/3."""

    def write(
        name: str, bands: list[int], alpha: NDArray[np.uint8] | None = None
    ) -> Path:
        path = storage_root / BUCKET / name
        count = len(bands) + (1 if alpha is not None else 0)
        with rasterio.open(
            path,
            "w",
            driver="GTiff",
            width=256,
            height=256,
            count=count,
            dtype="uint8",
            crs="EPSG:3857",
            transform=from_bounds(*WEB_MERCATOR_TMS.xy_bounds(Tile(4, 3, 3)), 256, 256),
            alpha="YES" if alpha is not None else "NO",
        ) as ds:
            for index, value in enumerate(bands, start=1):
                ds.write(np.full((256, 256), value, dtype=np.uint8), index)
            if alpha is not None:
                ds.write(alpha, count)
        return path

    return write


@pytest.fixture
def mosaic_token(grant_for: Callable[..., Grant]) -> MosaicToken:
    def sign(*names: str, **changes: object) -> str:
        sources = tuple(
            GrantSource(
                key=grant.key,
                sha256=grant.sha256,
                byte_size=grant.byte_size,
                page=grant.page,
            )
            for grant in (grant_for(name) for name in names)
        )
        fields: dict[str, object] = {
            "bucket": BUCKET,
            "sources": sources,
            "expires_at": int(time.time()) + 60,
        }
        fields.update(changes)
        grant = MosaicGrant(**fields)  # pyright: ignore[reportArgumentType]
        return grant.sign_grant(SIGNING_KEY.encode())

    return sign


def _open_image(response: httpx.Response) -> Image.Image:
    assert response.status_code == 200, response.text
    assert response.headers["X-Grafy-Renderer"] == RENDERER_VERSION
    return Image.open(io.BytesIO(response.content))


def _half_alpha() -> NDArray[np.uint8]:
    """Opaque left half, a 50 % column at 128..143, transparent beyond."""
    alpha = np.zeros((256, 256), dtype=np.uint8)
    alpha[:, :128] = 255
    alpha[:, 128:144] = 128
    return alpha


async def test_mosaic_paints_bottom_to_top_and_blends_soft_edges(
    client: httpx.AsyncClient, sheet: Sheet, mosaic_token: MosaicToken
) -> None:
    bottom = sheet("bottom.tif", [50])
    top = sheet("top.tif", [200, 0, 0], alpha=_half_alpha())

    response = await client.post(
        f"{_TILE}.png", json={"grant": mosaic_token(bottom.name, top.name)}
    )
    image = _open_image(response).convert("RGBA")

    assert image.getpixel((32, 128)) == (200, 0, 0, 255)
    # 128/255 red over gray, with no dark or light halo.
    assert image.getpixel((136, 128)) == (125, 25, 25, 255)
    # The bottom sheet shows through the top's transparent half.
    assert image.getpixel((224, 128)) == (50, 50, 50, 255)


async def test_mosaic_order_decides_which_sheet_wins(
    client: httpx.AsyncClient, sheet: Sheet, mosaic_token: MosaicToken
) -> None:
    gray = sheet("gray.tif", [50])
    red = sheet("red.tif", [200, 0, 0])

    red_on_top = await client.post(
        f"{_TILE}.png", json={"grant": mosaic_token(gray.name, red.name)}
    )
    gray_on_top = await client.post(
        f"{_TILE}.png", json={"grant": mosaic_token(red.name, gray.name)}
    )

    assert _open_image(red_on_top).convert("RGB").getpixel((5, 5)) == (200, 0, 0)
    assert _open_image(gray_on_top).convert("RGB").getpixel((5, 5)) == (50, 50, 50)


async def test_mosaic_keeps_uncovered_pixels_transparent(
    client: httpx.AsyncClient, sheet: Sheet, mosaic_token: MosaicToken
) -> None:
    left = np.zeros((256, 256), dtype=np.uint8)
    left[:, :64] = 255
    middle = np.zeros((256, 256), dtype=np.uint8)
    middle[:, 64:128] = 255
    first = sheet("left.tif", [10, 20, 30], alpha=left)
    second = sheet("middle.tif", [90], alpha=middle)

    response = await client.post(
        f"{_TILE}.jpg", json={"grant": mosaic_token(first.name, second.name)}
    )
    image = _open_image(response)

    # Not opaque, so a JPEG request still answers with a transparent PNG.
    assert response.headers["content-type"] == "image/png"
    assert image.mode == "RGBA"
    assert image.getpixel((16, 16)) == (10, 20, 30, 255)
    assert image.getpixel((96, 16)) == (90, 90, 90, 255)
    assert image.getchannel("A").getpixel((200, 16)) == 0


async def test_opaque_top_sheet_skips_the_sheets_below(
    client: httpx.AsyncClient,
    sheet: Sheet,
    mosaic_token: MosaicToken,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hidden = sheet("hidden.tif", [10])
    cover = sheet("cover.tif", [80, 90, 100])
    rendered: list[int] = []
    original = service.render_geo_tile_image

    def counting(ds: rasterio.DatasetReader, *args: object) -> object:
        rendered.append(ds.count)
        return original(ds, *args)  # pyright: ignore[reportArgumentType]

    monkeypatch.setattr(service, "render_geo_tile_image", counting)
    response = await client.post(
        f"{_TILE}.jpg", json={"grant": mosaic_token(hidden.name, cover.name)}
    )

    assert response.headers["content-type"] == "image/jpeg"
    assert _open_image(response).size == (256, 256)
    assert rendered == [3]


async def test_mosaic_tile_outside_every_source_is_not_found(
    client: httpx.AsyncClient, sheet: Sheet, mosaic_token: MosaicToken
) -> None:
    token = mosaic_token(sheet("a.tif", [1]).name, sheet("b.tif", [2]).name)
    response = await client.post("/geo/mosaic/tiles/3/0/0.png", json={"grant": token})
    assert response.status_code == 404
    assert response.json() == {"detail": "tile is outside the image"}


async def test_mosaic_requires_every_source_to_be_georeferenced(
    client: httpx.AsyncClient,
    sheet: Sheet,
    gray8: Callable[..., Path],
    mosaic_token: MosaicToken,
) -> None:
    token = mosaic_token(sheet("geo.tif", [1]).name, gray8().name)
    response = await client.post(f"{_TILE}.png", json={"grant": token})
    assert response.status_code == 422
    assert response.json() == {"detail": "TIFF page is not georeferenced"}


async def test_mosaic_route_refuses_anything_but_a_valid_mosaic_grant(
    client: httpx.AsyncClient,
    sheet: Sheet,
    mosaic_token: MosaicToken,
    auth: Callable[..., dict[str, str]],
) -> None:
    path = sheet("only.tif", [1])
    single = auth(path.name)[GRANT_HEADER]
    expired = mosaic_token(path.name, expires_at=int(time.time()) - 3_600)
    forged = mosaic_token(path.name)[:-4] + "AAAA"
    for token in (single, expired, forged):
        response = await client.post(f"{_TILE}.png", json={"grant": token})
        assert response.status_code == 403, token
    assert (await client.post(f"{_TILE}.png", json={})).status_code == 422

    # A mosaic token is never accepted where a single-source grant is expected.
    response = await client.get(
        "/geo/tiles/3/4/3.png", headers={GRANT_HEADER: mosaic_token(path.name)}
    )
    assert response.status_code == 403


async def test_mosaic_tile_is_served_from_the_disk_cache(
    client: httpx.AsyncClient,
    app: FastAPI,
    sheet: Sheet,
    mosaic_token: MosaicToken,
    grant_for: Callable[..., Grant],
) -> None:
    first = sheet("one.tif", [40])
    second = sheet("two.tif", [200, 0, 0], alpha=_half_alpha())
    token = mosaic_token(first.name, second.name)
    response = await client.post(f"{_TILE}.png", json={"grant": token})
    assert response.status_code == 200

    sources = [
        GrantSource(key=name, sha256=grant_for(name).sha256, byte_size=1)
        for name in (first.name, second.name)
    ]
    key = f"geomosaic:{RENDERER_VERSION}:{mosaic_digest(sources)}:png:3/4/3"
    assert app.state.cache.get(key) == response.content

    first.unlink()
    second.unlink()
    cached = await client.post(f"{_TILE}.png", json={"grant": token})
    assert cached.status_code == 200
    assert cached.content == response.content
