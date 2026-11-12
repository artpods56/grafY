import io
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import replace

import httpx
import pytest
from fastapi.routing import APIRoute
from PIL import Image

from grafy_tiler.app import create_app
from grafy_tiler.grant import Grant, sign_grant
from grafy_tiler.service import Overloaded, TileService
from grafy_tiler.settings import Settings

from .conftest import BUCKET, SIGNING_KEY, Writer

GRANT_HEADER = "X-Grafy-Grant"


@pytest.fixture
async def client(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://tiler"
        ) as http:
            yield http


@pytest.fixture
def auth(
    grant_for: Callable[..., Grant], token_for: Callable[[Grant], str]
) -> Callable[..., dict[str, str]]:
    def headers(name: str, **changes: object) -> dict[str, str]:
        grant = replace(grant_for(name), **changes)  # pyright: ignore[reportArgumentType]
        return {GRANT_HEADER: token_for(grant)}

    return headers


def _image(response: httpx.Response) -> Image.Image:
    return Image.open(io.BytesIO(response.content))


async def test_health_proves_the_cache_is_writable(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200 and response.json()["status"] == "ok"


async def test_health_fails_when_the_cache_is_not_writable(
    client: httpx.AsyncClient, settings: Settings
) -> None:
    for entry in settings.cache_dir.rglob("*"):
        if entry.is_file():
            entry.unlink()
    settings.cache_dir.rmdir()
    settings.cache_dir.write_bytes(b"in the way")
    assert (await client.get("/health")).status_code == 503


async def test_info_describes_the_image(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], gray8: Writer
) -> None:
    response = await client.get("/info", headers=auth(gray8().name))
    document = response.json()
    assert response.status_code == 200
    assert (document["width"], document["height"], document["tile_format"]) == (
        1300,
        700,
        "jpg",
    )
    assert document["max_level"] == 11 and document["tile_size"] == 512


async def test_tiles_decode_with_the_advertised_format(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    gray8: Writer,
    rgba: Writer,
) -> None:
    opaque = await client.get("/tiles/11/2/1.jpg", headers=auth(gray8().name))
    assert opaque.status_code == 200 and opaque.headers["content-type"] == "image/jpeg"
    assert _image(opaque).size == (276, 188)

    transparent = await client.get("/tiles/9/0/0.png", headers=auth(rgba().name))
    assert transparent.status_code == 200, transparent.text
    assert transparent.headers["content-type"] == "image/png"
    assert _image(transparent).mode == "RGBA"


async def test_thumbnail_ladder(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], gray8: Writer
) -> None:
    headers = auth(gray8().name)
    for edge, width in ((128, 128), (512, 512), (1024, 1024)):
        response = await client.get(f"/thumbnail?edge={edge}", headers=headers)
        assert response.status_code == 200, response.text
        assert _image(response).width == width
    assert (await client.get("/thumbnail?edge=300", headers=headers)).status_code == 422
    assert _image(await client.get("/thumbnail", headers=headers)).width == 256


async def test_a_png_request_for_a_jpeg_image_is_not_found(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], gray8: Writer
) -> None:
    assert (
        await client.get("/tiles/11/0/0.png", headers=auth(gray8().name))
    ).status_code == 404
    assert (
        await client.get("/tiles/11/9/0.jpg", headers=auth("gray8.tif"))
    ).status_code == 404
    assert (
        await client.get("/tiles/11/0/0.gif", headers=auth("gray8.tif"))
    ).status_code == 404


async def test_pages_are_selected_by_the_grant(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], multipage: Writer
) -> None:
    name = multipage().name
    assert (await client.get("/info", headers=auth(name, page=1))).json()[
        "width"
    ] == 400
    assert (await client.get("/info", headers=auth(name, page=5))).status_code == 404


@pytest.mark.parametrize("path", ["/info", "/tiles/11/0/0.jpg", "/thumbnail"])
async def test_every_data_route_demands_a_grant(
    client: httpx.AsyncClient, path: str
) -> None:
    assert (await client.get(path)).status_code == 403


async def test_forged_expired_and_foreign_grants_are_refused(
    client: httpx.AsyncClient, grant_for: Callable[..., Grant], gray8: Writer
) -> None:
    name = gray8().name
    good = grant_for(name)

    def get(token: str) -> "object":
        return client.get("/info", headers={GRANT_HEADER: token})

    forged = sign_grant(good, b"x" * 40)
    expired = sign_grant(
        replace(good, expires_at=int(time.time()) - 600), SIGNING_KEY.encode()
    )
    other_bucket = sign_grant(replace(good, bucket="other"), SIGNING_KEY.encode())
    traversal = sign_grant(replace(good, key="../../etc/passwd"), SIGNING_KEY.encode())
    for token in (forged, expired, other_bucket, traversal, "junk"):
        response = await get(token)  # pyright: ignore[reportGeneralTypeIssues]
        assert response.status_code == 403, token  # pyright: ignore[reportAttributeAccessIssue]
        assert "grant refused" in response.text  # pyright: ignore[reportAttributeAccessIssue]


async def test_the_granted_size_must_match_the_stored_object(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], gray8: Writer
) -> None:
    response = await client.get("/info", headers=auth(gray8().name, byte_size=17))
    assert response.status_code == 409


async def test_missing_unreadable_and_oversize_sources(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    garbage: Writer,
    gray8: Writer,
) -> None:
    assert (await client.get("/info", headers=auth(garbage().name))).status_code == 422
    missing = Grant(BUCKET, "nope.tif", "a" * 64, 10, 0, int(time.time()) + 60)
    token = sign_grant(missing, SIGNING_KEY.encode())
    assert (await client.get("/info", headers={GRANT_HEADER: token})).status_code == 422
    huge = auth(gray8().name, byte_size=2 * 1024**3)
    assert (
        await client.get("/info", headers=huge)
    ).status_code == 403  # over TILER_MAX_SOURCE_BYTES


async def test_overload_asks_the_caller_to_retry(
    client: httpx.AsyncClient,
    auth: Callable[..., dict[str, str]],
    gray8: Writer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def overloaded(*_: object) -> bytes:
        raise Overloaded

    monkeypatch.setattr(TileService, "tile", overloaded)
    response = await client.get("/tiles/11/0/0.jpg", headers=auth(gray8().name))
    assert response.status_code == 503 and response.headers["retry-after"] == "2"


async def test_no_route_accepts_a_url_path_or_bucket(settings: Settings) -> None:
    """The SSRF guard: the only things a caller can vary are tile coordinates,
    a thumbnail size, and the signed grant header."""
    app = create_app(settings)  # inspected, never started
    allowed = {"z", "x", "y", "extension", "edge"}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        dependant = route.dependant
        names = {p.name for p in (*dependant.path_params, *dependant.query_params)}
        for dependency in dependant.dependencies:
            names |= {
                p.name for p in (*dependency.path_params, *dependency.query_params)
            }
        assert names <= allowed, (route.path, names - allowed)
        headers = {p.alias for p in dependant.header_params}
        for dependency in dependant.dependencies:
            headers |= {p.alias for p in dependency.header_params}
        assert headers <= {GRANT_HEADER}, (route.path, headers)


async def test_url_like_query_parameters_are_ignored(
    client: httpx.AsyncClient, auth: Callable[..., dict[str, str]], gray8: Writer
) -> None:
    headers = auth(gray8().name)
    plain = await client.get("/info", headers=headers)
    tricked = await client.get(
        "/info?url=http://169.254.169.254/latest/meta-data&bucket=other&key=../x&path=/etc/passwd",
        headers=headers,
    )
    assert tricked.status_code == 200 and tricked.json() == plain.json()
