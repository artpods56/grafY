"""Presigned uploads through the same-origin gateway's `/storage/` location.

Requires MinIO behind ``infra/docker/gateway/nginx.conf``; see
``infra/docker/compose.storage-gateway-test.yaml``.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import uuid4

import botocore.session
import httpx
import pytest
import pytest_asyncio
from grafy_storage.adapters.s3 import S3ObjectStore

pytestmark = pytest.mark.skipif(
    "GRAFY_TEST_S3_GATEWAY_URL" not in os.environ
    or "GRAFY_TEST_S3_ENDPOINT_URL" not in os.environ,
    reason="GRAFY_TEST_S3_GATEWAY_URL and GRAFY_TEST_S3_ENDPOINT_URL are not configured",
)

# The gateway routes only this bucket.
BUCKET = "workbench-artifacts"
MAX_UPLOAD_BYTES = 64 * 1024 * 1024


def _credentials() -> tuple[str, str]:
    return (
        os.environ.get("GRAFY_TEST_S3_ACCESS_KEY_ID", "minioadmin"),
        os.environ.get("GRAFY_TEST_S3_SECRET_ACCESS_KEY", "minioadmin"),
    )


@pytest.fixture(scope="module")
def gateway_url() -> str:
    return os.environ["GRAFY_TEST_S3_GATEWAY_URL"].rstrip("/")


@pytest.fixture(scope="module")
def store(gateway_url: str) -> S3ObjectStore:
    access, secret = _credentials()
    endpoint = os.environ["GRAFY_TEST_S3_ENDPOINT_URL"]
    client = botocore.session.get_session().create_client(
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id=access,
        aws_secret_access_key=secret,
    )
    try:
        client.create_bucket(Bucket=BUCKET)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass
    return S3ObjectStore(
        endpoint_url=endpoint,
        signing_endpoint_url=gateway_url,
        region="us-east-1",
        access_key_id=access,
        secret_access_key=secret,
        force_path_style=True,
    )


@pytest_asyncio.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(timeout=60) as client:
        yield client


async def _signed_put_url(store: S3ObjectStore) -> tuple[str, str]:
    key = f"objects/{uuid4()}"
    target = await store.create_presigned_upload(
        BUCKET, key, expires_in=timedelta(minutes=5)
    )
    assert dict(target.required_headers) == {"If-None-Match": "*"}
    return key, target.url


@pytest.mark.asyncio
async def test_presigned_put_through_gateway_is_create_only(
    store: S3ObjectStore, gateway_url: str, http: httpx.AsyncClient
) -> None:
    key, url = await _signed_put_url(store)
    assert url.startswith(f"{gateway_url}/{BUCKET}/{key}?")

    # Content-Type is unsigned; the web client sends it with every upload.
    first = await http.put(
        url,
        content=b"first",
        headers={"If-None-Match": "*", "Content-Type": "application/octet-stream"},
    )
    assert first.status_code == 200, first.text
    info = await store.stat(BUCKET, key)
    assert info is not None
    assert info.byte_size == len(b"first")

    replay = await http.put(url, content=b"second", headers={"If-None-Match": "*"})
    assert replay.status_code == 412
    # MinIO rejects a request missing a signed header before evaluating it.
    unconditional = await http.put(url, content=b"third")
    assert unconditional.status_code in {400, 403}
    await store.delete(BUCKET, key)


@pytest.mark.asyncio
async def test_gateway_rejects_tampered_signed_path(
    store: S3ObjectStore, http: httpx.AsyncClient
) -> None:
    key, url = await _signed_put_url(store)
    tampered = url.replace(key, f"objects/{uuid4()}", 1)
    response = await http.put(tampered, content=b"x", headers={"If-None-Match": "*"})
    assert response.status_code == 403
    assert "SignatureDoesNotMatch" in response.text
    assert await store.stat(BUCKET, key) is None


@pytest.mark.asyncio
async def test_gateway_storage_location_allows_only_put(
    store: S3ObjectStore, http: httpx.AsyncClient
) -> None:
    _, url = await _signed_put_url(store)
    for method in ("GET", "HEAD", "POST", "DELETE"):
        response = await http.request(method, url)
        assert response.status_code == 403, method


@pytest.mark.asyncio
async def test_gateway_storage_location_exposes_only_the_artifact_bucket(
    gateway_url: str, http: httpx.AsyncClient
) -> None:
    origin = gateway_url.removesuffix(urlsplit(gateway_url).path)
    for path in (
        "/storage/other-bucket/objects/x?X-Amz-Signature=0",
        "/storage/minio/health/live?x=1",
        "/storage/minio/admin/v3/info?x=1",
        f"/storage/{BUCKET}?list-type=2",
        f"/storage/{BUCKET}/objects/unsigned",
    ):
        response = await http.put(f"{origin}{path}", content=b"x")
        assert response.status_code == 404, path


@pytest.mark.asyncio
async def test_gateway_rejects_bodies_above_staged_upload_limit(
    store: S3ObjectStore, http: httpx.AsyncClient
) -> None:
    key, url = await _signed_put_url(store)
    response = await http.put(
        url,
        content=b"\0" * (MAX_UPLOAD_BYTES + 1),
        headers={"If-None-Match": "*"},
    )
    assert response.status_code == 413
    assert await store.stat(BUCKET, key) is None
