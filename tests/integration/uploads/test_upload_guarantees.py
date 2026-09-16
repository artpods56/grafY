"""Adversarial upload guarantee tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from grafy_api.upload_inspection import FileFormatMismatchError, inspect_upload_async
from grafy_api.uploads import UploadService, UploadServiceConfig, UploadTooLargeError
from grafy_core.artifacts import ArtifactTypeKey
from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.domain.uploads import UploadStatus
from grafy_core.file_contracts import BUILTIN_FILE_FORMATS, build_extension_table
from grafy_core.ports.storage import SaveFileCommand
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_storage import LocalFileObjectStore
from grafy_storage.adapters.s3 import S3ObjectStore

from tests.support.identity import TEST_USER_ID, WORKSPACE_ID

PNG_BYTES = b"\x89PNG\r\n\x1a\nstaged payload"
BUCKET = "workbench-artifacts"
UPLOAD_FORMAT_TYPES = {
    (spec.key.id, spec.key.schema_version): spec for spec in BUILTIN_FILE_FORMATS
}
UPLOAD_EXTENSION_CLAIMS = build_extension_table(
    (spec.key, spec.extensions) for spec in BUILTIN_FILE_FORMATS
)


def _service(tmp_path: Path, **kwargs) -> tuple[UploadService, InMemoryUnitOfWork, LocalFileObjectStore]:
    unit_of_work = kwargs.pop("unit_of_work", None) or InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    max_upload_bytes = kwargs.pop("max_upload_bytes", 1024 * 1024)
    service = UploadService.from_config(
        UploadServiceConfig(max_upload_bytes=max_upload_bytes),
        storage=storage,
        unit_of_work_factory=lambda: unit_of_work,
        artifact_types=UPLOAD_FORMAT_TYPES,
        extension_claims=UPLOAD_EXTENSION_CLAIMS,
        bucket=BUCKET,
        storage_backend="local",
        **kwargs,
    )
    return service, unit_of_work, storage


async def test_local_create_only_writes_cannot_replace_each_other(tmp_path: Path) -> None:
    storage = LocalFileObjectStore(tmp_path)
    first = await storage.save(
        SaveFileCommand(
            bucket="artifacts",
            path="objects/one.bin",
            stream=BytesIO(b"first-writer"),
            content_type="application/octet-stream",
            metadata={},
        )
    )
    with pytest.raises(ObjectAlreadyExistsError):
        await storage.save(
            SaveFileCommand(
                bucket="artifacts",
                path="objects/one.bin",
                stream=BytesIO(b"second-writer-longer"),
                content_type="application/octet-stream",
                metadata={},
            )
        )
    loaded = await storage.open_chunks("artifacts", "objects/one.bin")
    try:
        assert loaded.read() == b"first-writer"
    finally:
        loaded.close()
    assert first.byte_size == len(b"first-writer")


async def test_local_overflow_leaves_no_ordinary_temporary_file(tmp_path: Path) -> None:
    service, _, storage = _service(tmp_path, max_upload_bytes=4)
    target = await service.create_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename="too-big.bin",
        byte_size=4,
    )
    with pytest.raises(UploadTooLargeError):
        await service.receive_content(
            workspace_id=WORKSPACE_ID,
            upload_id=target.upload_id,
            stream=BytesIO(b"12345"),
        )
    root = tmp_path / "objects"
    leftover = [path for path in root.rglob("*") if path.is_file()]
    assert leftover == []
    assert await storage.stat(BUCKET, f"objects/{target.upload_id}") is None


async def test_concurrent_completions_create_exactly_one_artifact(tmp_path: Path) -> None:
    service, unit_of_work, _ = _service(tmp_path)
    target = await service.create_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename="page.png",
        byte_size=len(PNG_BYTES),
    )
    await service.receive_content(
        workspace_id=WORKSPACE_ID,
        upload_id=target.upload_id,
        stream=BytesIO(PNG_BYTES),
    )

    first, second = await asyncio.gather(
        service.complete_upload(workspace_id=WORKSPACE_ID, upload_id=target.upload_id),
        service.complete_upload(workspace_id=WORKSPACE_ID, upload_id=target.upload_id),
    )

    assert first.upload.artifact_id == second.upload.artifact_id
    assert first.upload.sha256 == second.upload.sha256
    async with unit_of_work as entered:
        artifacts = await entered.artifacts.list_by_type(
            WORKSPACE_ID,
            ArtifactTypeKey("file.png", 1),
        )
    assert len(artifacts) == 1


async def test_failure_marking_cannot_downgrade_ready(tmp_path: Path) -> None:
    service, unit_of_work, _ = _service(tmp_path)
    target = await service.create_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename="page.png",
        byte_size=len(PNG_BYTES),
    )
    await service.receive_content(
        workspace_id=WORKSPACE_ID,
        upload_id=target.upload_id,
        stream=BytesIO(PNG_BYTES),
    )
    ready = await service.complete_upload(
        workspace_id=WORKSPACE_ID,
        upload_id=target.upload_id,
    )
    async with unit_of_work as entered:
        marked = await entered.uploads.mark_terminal_if_pending(
            WORKSPACE_ID,
            target.upload_id,
            status=UploadStatus.FAILED,
        )
        await entered.commit()
    assert marked is None
    async with unit_of_work as entered:
        current = await entered.uploads.get(WORKSPACE_ID, target.upload_id)
    assert current is not None
    assert current.status is UploadStatus.READY
    assert current.artifact_id == ready.upload.artifact_id


async def test_cleanup_keeps_tracking_when_storage_delete_fails(tmp_path: Path) -> None:
    service, unit_of_work, storage = _service(tmp_path)
    target = await service.create_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename="abandoned.bin",
        byte_size=4,
    )
    await service.receive_content(
        workspace_id=WORKSPACE_ID,
        upload_id=target.upload_id,
        stream=BytesIO(b"data"),
    )

    async def boom(bucket: str, path: str) -> None:
        raise OSError("simulated delete failure")

    storage.delete = boom  # type: ignore[method-assign]
    assert await service.cleanup_abandoned(older_than=timedelta(0)) == 0
    async with unit_of_work as entered:
        row = await entered.uploads.get(WORKSPACE_ID, target.upload_id)
    assert row is not None
    assert row.status is UploadStatus.EXPIRED

    async def ok_delete(bucket: str, path: str) -> None:
        file_path = storage._path_for(bucket, path)
        if file_path.exists():
            file_path.unlink()

    storage.delete = ok_delete  # type: ignore[method-assign]
    assert await service.cleanup_abandoned(older_than=timedelta(0)) == 1
    async with unit_of_work as entered:
        assert await entered.uploads.get(WORKSPACE_ID, target.upload_id) is None


async def test_upload_target_repr_redacts_signed_capability() -> None:
    from grafy_api.uploads import UploadTarget

    target = UploadTarget(
        upload_id=uuid4(),
        url="https://bucket.example/object?X-Amz-Signature=secret",
        method="PUT",
        expires_at=datetime.now(UTC),
        kind="storage",
        headers={"If-None-Match": "*"},
    )
    rendered = repr(target)
    assert "X-Amz-Signature" not in rendered
    assert "secret" not in rendered
    assert "<redacted>" in rendered


async def test_inspection_rejects_truncated_json(tmp_path: Path) -> None:
    storage = LocalFileObjectStore(tmp_path)
    await storage.save(
        SaveFileCommand(
            bucket=BUCKET,
            path="objects/broken.json",
            stream=BytesIO(b'{"a":'),
            content_type="application/json",
            metadata={},
        )
    )
    with pytest.raises(FileFormatMismatchError):
        await inspect_upload_async(
            storage=storage,
            bucket=BUCKET,
            object_key="objects/broken.json",
            original_filename="broken.json",
            expected_size=5,
            max_upload_bytes=1024,
            artifact_types=UPLOAD_FORMAT_TYPES,
            extension_claims=UPLOAD_EXTENSION_CLAIMS,
            declared_byte_size=5,
        )


def test_conditional_presign_includes_if_none_match_in_signed_headers() -> None:
    store = S3ObjectStore(
        endpoint_url="http://minio.internal:9000",
        signing_endpoint_url="https://uploads.example.test",
        region="us-east-1",
        access_key_id="minioadmin",
        secret_access_key="minioadmin",
        force_path_style=True,
    )
    url = store._sign_conditional_put("artifacts", "objects/one.bin", 60)
    query = parse_qs(urlparse(url).query)
    assert urlparse(url).hostname == "uploads.example.test"
    signed_headers = query["X-Amz-SignedHeaders"][0]
    assert "if-none-match" in signed_headers.split(";")


@pytest.mark.skipif(
    "GRAFY_TEST_S3_ENDPOINT_URL" not in __import__("os").environ,
    reason="GRAFY_TEST_S3_ENDPOINT_URL is not configured",
)
@pytest.mark.asyncio
async def test_minio_conditional_put_rejects_replay() -> None:
    import os

    import httpx

    endpoint = os.environ["GRAFY_TEST_S3_ENDPOINT_URL"]
    access = os.environ.get("GRAFY_TEST_S3_ACCESS_KEY_ID", "minioadmin")
    secret = os.environ.get("GRAFY_TEST_S3_SECRET_ACCESS_KEY", "minioadmin")
    bucket = os.environ.get("GRAFY_TEST_S3_BUCKET", "grafy-upload-tests")
    store = S3ObjectStore(
        endpoint_url=endpoint,
        signing_endpoint_url=endpoint,
        region=os.environ.get("GRAFY_TEST_S3_REGION", "us-east-1"),
        access_key_id=access,
        secret_access_key=secret,
        force_path_style=True,
    )
    key = f"objects/{uuid4()}"
    target = await store.create_presigned_upload(
        bucket,
        key,
        expires_in=timedelta(minutes=5),
    )
    async with httpx.AsyncClient() as client:
        first = await client.put(
            target.url,
            content=b"first",
            headers=dict(target.required_headers),
        )
        assert first.status_code in {200, 204}
        replay = await client.put(
            target.url,
            content=b"second",
            headers=dict(target.required_headers),
        )
        assert replay.status_code in {412, 409, 403}
        missing = await client.put(target.url, content=b"third")
        assert missing.status_code in {403, 400, 412}
    await store.delete(bucket, key)
