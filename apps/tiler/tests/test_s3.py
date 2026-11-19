"""Reads through GDAL's /vsis3/ against a real S3 endpoint served over HTTP.

moto runs in-process on a loopback port, so this exercises the same path a
deployment uses with MinIO: path-style requests, SigV4 credentials, ranges.
"""

import hashlib
import io
import socket
import time
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import replace
from pathlib import Path

import boto3
import httpx
import pytest
from grafy_crypto.grants import Grant
from moto.server import ThreadedMotoServer
from PIL import Image
from pydantic import SecretStr

from grafy_tiler.app import create_app
from grafy_tiler.settings import Settings
from tests.conftest import BUCKET, SIGNING_KEY, Writer

ACCESS_KEY = "test-access-key"
SECRET_KEY = "test-secret-key"


@pytest.fixture(scope="module")
def s3_endpoint() -> Iterator[str]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = ThreadedMotoServer(ip_address="127.0.0.1", port=port, verbose=False)
    server.start()
    yield f"http://127.0.0.1:{port}"
    server.stop()


@pytest.fixture
def uploaded(s3_endpoint: str, storage_root: Path) -> Callable[[Path, str], Grant]:
    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name="us-east-1",
    )
    existing = {item["Name"] for item in client.list_buckets()["Buckets"]}
    if BUCKET not in existing:
        client.create_bucket(Bucket=BUCKET)

    def upload(path: Path, key: str) -> Grant:
        body = path.read_bytes()
        client.put_object(Bucket=BUCKET, Key=key, Body=body)
        return Grant(
            bucket=BUCKET,
            key=key,
            sha256=hashlib.sha256(body).hexdigest(),
            byte_size=len(body),
            page=0,
            expires_at=int(time.time()) + 60,
        )

    return upload


@pytest.fixture
async def s3_client(
    settings: Settings, s3_endpoint: str
) -> AsyncIterator[httpx.AsyncClient]:
    configured = settings.model_copy(
        update={
            "storage": "s3",
            "local_root": None,
            "s3_endpoint_url": s3_endpoint,
            "s3_access_key_id": SecretStr(ACCESS_KEY),
            "s3_secret_access_key": SecretStr(SECRET_KEY),
            "s3_force_path_style": True,
        }
    )
    app = create_app(configured)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://tiler"
        ) as http:
            yield http


def _headers(grant: Grant) -> dict[str, str]:
    return {"X-Grafy-Grant": grant.sign_grant(SIGNING_KEY.encode())}


async def test_display_and_native_windows_read_through_vsis3(
    s3_client: httpx.AsyncClient,
    uploaded: Callable[[Path, str], Grant],
    rgb_tiled_with_overviews: Writer,
) -> None:
    grant = uploaded(rgb_tiled_with_overviews(), "ws-1/artifacts/ab/scan.tif")
    crop = await s3_client.get(
        "/window?col=300&row=71&width=1&height=1", headers=_headers(grant)
    )
    assert crop.status_code == 200, crop.text
    assert Image.open(io.BytesIO(crop.content)).getpixel((0, 0)) == (200, 51, 40)

    info = await s3_client.get("/info", headers=_headers(grant))
    assert info.status_code == 200, info.text
    assert (info.json()["width"], info.json()["overview_count"]) == (1500, 3)

    tile = await s3_client.get("/tiles/10/0/0.jpg", headers=_headers(grant))
    assert tile.status_code == 200
    assert Image.open(io.BytesIO(tile.content)).size == (512, 450)

    thumbnail = await s3_client.get("/thumbnail?edge=128", headers=_headers(grant))
    assert Image.open(io.BytesIO(thumbnail.content)).size == (128, 77)


async def test_a_later_page_of_a_multipage_tiff_is_read_through_vsis3(
    s3_client: httpx.AsyncClient,
    uploaded: Callable[[Path, str], Grant],
    multipage: Writer,
) -> None:
    grant = uploaded(multipage(), "ws-1/artifacts/cd/book.tif")
    second = replace(grant, page=1)
    response = await s3_client.get("/info", headers=_headers(second))
    assert (response.status_code, response.json()["width"]) == (200, 400)
    crop = await s3_client.get(
        "/window?col=399&row=239&width=1&height=1", headers=_headers(second)
    )
    assert crop.status_code == 200, crop.text
    image = Image.open(io.BytesIO(crop.content))
    assert image.size == (1, 1)
    assert image.getpixel((0, 0)) == (0, 255, 0)


async def test_a_missing_object_is_unprocessable_not_a_crash(
    s3_client: httpx.AsyncClient, uploaded: Callable[[Path, str], Grant], gray8: Writer
) -> None:
    grant = uploaded(gray8(), "ws-1/artifacts/ef/real.tif")
    ghost = replace(grant, key="ws-1/artifacts/ef/ghost.tif", sha256="e" * 64)
    assert (await s3_client.get("/info", headers=_headers(ghost))).status_code == 422


async def test_a_grant_for_another_bucket_never_reaches_storage(
    s3_client: httpx.AsyncClient, uploaded: Callable[[Path, str], Grant], gray8: Writer
) -> None:
    grant = uploaded(gray8(), "ws-1/artifacts/12/ok.tif")
    other = replace(grant, bucket="someone-elses-bucket")
    assert (await s3_client.get("/info", headers=_headers(other))).status_code == 403
