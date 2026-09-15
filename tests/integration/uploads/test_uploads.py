import asyncio
from datetime import timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import cast, override
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from grafy_api.services.errors import WorkbenchOperationError
from grafy_api.settings import (
    STAGED_UPLOAD_HARD_MAX_BYTES,
    Settings,
)
from grafy_api.uploads import (
    FileFormatMismatchError,
    PresigningStorage,
    UploadNotFoundError,
    UploadService,
    UploadStateError,
    UploadTooLargeError,
    UploadTransportUnsupportedError,
)
from grafy_api.v1.routes.uploads.dependencies import upload_service
from grafy_api.v1.routes.uploads.models import SampleRequest
from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey
from grafy_core.domain.uploads import Upload, UploadStatus
from grafy_core.file_contracts import (
    BLOB_FILE,
    BUILTIN_FILE_FORMATS,
    build_extension_table,
)
from grafy_core.ports.storage import (
    FileStreamProtocol,
    SaveFileCommand,
    StoredFile,
    StoredObjectInfo,
)
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_storage import LocalFileObjectStore
from pydantic import ValidationError

from tests.support.clients import GrafyApi
from tests.support.identity import TEST_USER_ID, WORKSPACE_ID

PNG_BYTES = b"\x89PNG\r\n\x1a\nstaged payload"
BUCKET = "workbench-artifacts"
UPLOAD_FORMAT_TYPES = {
    (spec.key.id, spec.key.schema_version): spec for spec in BUILTIN_FILE_FORMATS
}
UPLOAD_EXTENSION_CLAIMS = build_extension_table(
    (spec.key, spec.extensions) for spec in BUILTIN_FILE_FORMATS
)


def _upload_service(
    tmp_path: Path,
    *,
    max_upload_bytes: int = STAGED_UPLOAD_HARD_MAX_BYTES,
    unit_of_work: InMemoryUnitOfWork | None = None,
    presigning: PresigningStorage | None = None,
) -> tuple[UploadService, InMemoryUnitOfWork, LocalFileObjectStore]:
    resolved_unit_of_work = unit_of_work or InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    service = UploadService(
        storage=storage,
        unit_of_work_factory=lambda: resolved_unit_of_work,
        artifact_types=UPLOAD_FORMAT_TYPES,
        extension_claims=UPLOAD_EXTENSION_CLAIMS,
        bucket=BUCKET,
        storage_backend="local",
        presigning=presigning,
        max_upload_bytes=max_upload_bytes,
    )
    return service, resolved_unit_of_work, storage


async def _complete_upload(
    service: UploadService,
    filename: str,
    content: bytes,
    *,
    content_type: str | None = None,
    workspace_id: UUID = WORKSPACE_ID,
) -> Upload:
    """Reserve, send, and complete one upload, returning its ready row."""

    target = await service.create_upload(
        workspace_id=workspace_id,
        created_by_user_id=TEST_USER_ID,
        filename=filename,
        byte_size=len(content),
        content_type=content_type,
    )
    await service.receive_content(
        workspace_id=workspace_id,
        upload_id=target.upload_id,
        stream=BytesIO(content),
    )
    result = await service.complete_upload(
        workspace_id=workspace_id,
        upload_id=target.upload_id,
    )
    return result.upload


async def _stored_files(root: Path) -> list[Path]:
    return [path for path in root.rglob("*") if path.is_file()]


async def _upload_row(
    unit_of_work: InMemoryUnitOfWork,
    upload_id: UUID,
    *,
    workspace_id: UUID = WORKSPACE_ID,
) -> Upload | None:
    async with unit_of_work as entered:
        return await entered.uploads.get(workspace_id, upload_id)


async def _uploads(
    unit_of_work: InMemoryUnitOfWork,
    workspace_id: UUID,
) -> list[Upload]:
    async with unit_of_work as entered:
        return await entered.uploads.list_for_workspace(workspace_id)


async def _artifacts(
    unit_of_work: InMemoryUnitOfWork,
    key: ArtifactTypeKey,
) -> list[ArtifactObject]:
    async with unit_of_work as entered:
        return await entered.artifacts.list_by_type(WORKSPACE_ID, key)


def test_staged_upload_settings_enforce_release_bounds() -> None:
    settings = Settings.model_validate({})

    assert settings.staged_upload_max_bytes == 64 * 1024 * 1024
    with pytest.raises(ValidationError):
        Settings(staged_upload_max_bytes=1024 * 1024 - 1)
    with pytest.raises(ValidationError):
        Settings(
            staged_upload_max_bytes=STAGED_UPLOAD_HARD_MAX_BYTES + 1,
        )


def test_upload_service_rejects_limit_above_release_hard_max(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="64 MiB hard limit"):
        _upload_service(tmp_path, max_upload_bytes=STAGED_UPLOAD_HARD_MAX_BYTES + 1)


async def test_create_upload_rejects_a_declared_oversize_without_storing_bytes(
    tmp_path: Path,
) -> None:
    service, unit_of_work, _ = _upload_service(tmp_path, max_upload_bytes=1024)

    with pytest.raises(UploadTooLargeError, match="exceeds the upload limit"):
        await service.create_upload(
            workspace_id=WORKSPACE_ID,
            created_by_user_id=TEST_USER_ID,
            filename="large.bin",
            byte_size=1025,
        )

    assert await _uploads(unit_of_work, WORKSPACE_ID) == []
    assert await _stored_files(tmp_path / "objects") == []


async def test_upload_at_exact_byte_limit_is_promoted(tmp_path: Path) -> None:
    service, unit_of_work, _ = _upload_service(tmp_path, max_upload_bytes=4)

    upload = await _complete_upload(service, "exact.bin", b"1234")

    assert upload.status is UploadStatus.READY
    assert upload.actual_size == 4
    assert upload.workspace_id == WORKSPACE_ID
    assert upload.created_by_user_id == TEST_USER_ID
    assert upload.original_filename == "exact.bin"
    assert await _uploads(unit_of_work, WORKSPACE_ID) == [upload]


async def test_upload_rejects_bytes_that_outgrow_the_declared_size(
    tmp_path: Path,
) -> None:
    service, unit_of_work, _ = _upload_service(tmp_path)

    target = await service.create_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename="lied.bin",
        byte_size=2,
    )
    await service.receive_content(
        workspace_id=WORKSPACE_ID,
        upload_id=target.upload_id,
        stream=BytesIO(b"more than two bytes"),
    )

    with pytest.raises(UploadStateError, match="declared 2 bytes but"):
        await service.complete_upload(
            workspace_id=WORKSPACE_ID,
            upload_id=target.upload_id,
        )

    row = await _upload_row(unit_of_work, target.upload_id)
    assert row is not None
    assert row.status is UploadStatus.FAILED
    assert await _artifacts(unit_of_work, BLOB_FILE.key) == []


async def test_upload_resolves_a_known_extension_case_insensitively(
    tmp_path: Path,
) -> None:
    service, unit_of_work, storage = _upload_service(tmp_path)

    upload = await _complete_upload(service, "Scan.PNG", PNG_BYTES)

    assert upload.artifact_type == "file.png"
    artifacts = await _artifacts(unit_of_work, ArtifactTypeKey("file.png", 1))
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.content_type == "image/png"
    assert artifact.byte_size == len(PNG_BYTES)
    assert artifact.sha256 == sha256(PNG_BYTES).hexdigest()
    assert artifact.metadata == {"original_filename": "Scan.PNG"}
    assert artifact.workspace_id == WORKSPACE_ID
    assert artifact.storage_backend == "local"
    assert artifact.bucket == BUCKET
    assert artifact.object_key is not None
    stored = await storage.stat(BUCKET, artifact.object_key)
    assert stored is not None
    assert stored.byte_size == len(PNG_BYTES)


async def test_object_key_is_server_chosen_and_ignores_the_filename(
    tmp_path: Path,
) -> None:
    service, unit_of_work, _ = _upload_service(tmp_path)

    upload = await _complete_upload(service, "../../etc/passwd.png", PNG_BYTES)

    assert upload.object_key == f"objects/{upload.upload_id}"
    assert "passwd" not in upload.object_key
    assert await _uploads(unit_of_work, WORKSPACE_ID) == [upload]


async def test_upload_rejects_a_known_extension_whose_bytes_disagree(
    tmp_path: Path,
) -> None:
    service, unit_of_work, _ = _upload_service(tmp_path)

    target = await service.create_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename="scan.png",
        byte_size=len(b"not a png"),
    )
    await service.receive_content(
        workspace_id=WORKSPACE_ID,
        upload_id=target.upload_id,
        stream=BytesIO(b"not a png"),
    )
    with pytest.raises(FileFormatMismatchError) as raised:
        await service.complete_upload(
            workspace_id=WORKSPACE_ID,
            upload_id=target.upload_id,
        )

    assert str(raised.value) == (
        "'scan.png' does not look like a PNG file. "
        "Rename it or convert it, then try again."
    )
    assert await _artifacts(unit_of_work, ArtifactTypeKey("file.png", 1)) == []
    row = await _upload_row(unit_of_work, target.upload_id)
    assert row is not None
    assert row.status is UploadStatus.FAILED


@pytest.mark.parametrize("filename", ["notes.xyz", "README", ".gitignore"])
async def test_upload_stores_an_unclaimed_or_missing_extension_as_a_blob(
    tmp_path: Path,
    filename: str,
) -> None:
    service, unit_of_work, _ = _upload_service(tmp_path)

    upload = await _complete_upload(service, filename, b"opaque bytes")

    assert upload.artifact_type == BLOB_FILE.key.id
    artifacts = await _artifacts(unit_of_work, BLOB_FILE.key)
    assert [artifact.metadata for artifact in artifacts] == [
        {"original_filename": filename}
    ]


async def test_upload_confirms_a_json_extension_with_its_declared_rule(
    tmp_path: Path,
) -> None:
    service, unit_of_work, _ = _upload_service(tmp_path)
    key = ArtifactTypeKey("file.json", 1)

    accepted = await _complete_upload(service, "rows.json", b'[{"a": 1}]')
    assert accepted.artifact_type == key.id

    with pytest.raises(FileFormatMismatchError, match="does not look like a JSON"):
        await _complete_upload(service, "value.json", b"17")
    assert len(await _artifacts(unit_of_work, key)) == 1


async def test_complete_requires_the_bytes_to_have_arrived(tmp_path: Path) -> None:
    service, unit_of_work, _ = _upload_service(tmp_path)

    target = await service.create_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename="page.png",
        byte_size=len(PNG_BYTES),
    )

    with pytest.raises(UploadStateError, match="has no stored bytes"):
        await service.complete_upload(
            workspace_id=WORKSPACE_ID,
            upload_id=target.upload_id,
        )

    row = await _upload_row(unit_of_work, target.upload_id)
    assert row is not None
    assert row.status is UploadStatus.FAILED


async def test_complete_is_rejected_once_the_upload_is_ready(
    tmp_path: Path,
) -> None:
    service, _, _ = _upload_service(tmp_path)

    upload = await _complete_upload(service, "page.png", PNG_BYTES)

    with pytest.raises(UploadStateError, match="already complete"):
        await service.complete_upload(
            workspace_id=WORKSPACE_ID,
            upload_id=upload.upload_id,
        )


async def test_uploads_are_confined_to_their_workspace(tmp_path: Path) -> None:
    service, _, _ = _upload_service(tmp_path)
    other_workspace = uuid4()

    upload = await _complete_upload(service, "page.png", PNG_BYTES)

    with pytest.raises(UploadNotFoundError):
        await service.complete_upload(
            workspace_id=other_workspace,
            upload_id=upload.upload_id,
        )
    with pytest.raises(UploadNotFoundError):
        await service.receive_content(
            workspace_id=other_workspace,
            upload_id=upload.upload_id,
            stream=BytesIO(PNG_BYTES),
        )


async def test_create_upload_rejects_a_blank_filename(tmp_path: Path) -> None:
    service, unit_of_work, _ = _upload_service(tmp_path)

    with pytest.raises(WorkbenchOperationError, match="filename is required"):
        await service.create_upload(
            workspace_id=WORKSPACE_ID,
            created_by_user_id=TEST_USER_ID,
            filename="   ",
            byte_size=3,
        )

    assert await _uploads(unit_of_work, WORKSPACE_ID) == []


async def test_cleanup_reclaims_abandoned_uploads_and_spares_promoted_ones(
    tmp_path: Path,
) -> None:
    service, unit_of_work, storage = _upload_service(tmp_path)

    promoted = await _complete_upload(service, "page.png", PNG_BYTES)
    abandon = await service.create_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename="abandoned.bin",
        byte_size=4,
    )
    await service.receive_content(
        workspace_id=WORKSPACE_ID,
        upload_id=abandon.upload_id,
        stream=BytesIO(b"data"),
    )

    discarded = await service.cleanup_abandoned(older_than=timedelta(0))

    assert discarded == 1
    assert await _upload_row(unit_of_work, abandon.upload_id) is None
    assert await storage.stat(BUCKET, f"objects/{abandon.upload_id}") is None
    remaining = await _stored_files(tmp_path / "objects")
    assert len(remaining) == 1
    assert promoted.object_key in str(remaining[0])
    surviving = await _upload_row(unit_of_work, promoted.upload_id)
    assert surviving is not None
    assert surviving.status is UploadStatus.READY


class FailingCompletionUnitOfWork(InMemoryUnitOfWork):
    """Fail the completion commit, then behave normally again."""

    def __init__(self) -> None:
        super().__init__()
        self._commits = 0

    @override
    async def commit(self) -> None:
        self._commits += 1
        if self._commits == 2:
            raise RuntimeError("completion commit failed")
        await super().commit()


async def test_a_failed_completion_leaves_the_upload_for_the_cleanup_sweep(
    tmp_path: Path,
) -> None:
    unit_of_work = FailingCompletionUnitOfWork()
    service, _, storage = _upload_service(tmp_path, unit_of_work=unit_of_work)

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
    with pytest.raises(RuntimeError, match="completion commit failed"):
        await service.complete_upload(
            workspace_id=WORKSPACE_ID,
            upload_id=target.upload_id,
        )

    row = await _upload_row(unit_of_work, target.upload_id)
    assert row is not None
    assert row.status is UploadStatus.PENDING
    assert await _artifacts(unit_of_work, ArtifactTypeKey("file.png", 1)) == []

    assert await service.cleanup_abandoned(older_than=timedelta(0)) == 1
    assert await _upload_row(unit_of_work, target.upload_id) is None
    assert await storage.stat(BUCKET, f"objects/{target.upload_id}") is None


def test_upload_endpoint_reserves_then_completes(
    builtin_client: TestClient,
) -> None:
    uploads = GrafyApi(builtin_client).workspace(WORKSPACE_ID).uploads

    target = uploads.create_ok("page.png", len(PNG_BYTES), content_type="image/png")
    assert target.method == "PUT"
    assert target.url == (
        f"/v1/workspaces/{WORKSPACE_ID}/uploads/{target.upload_id}/content"
    )

    assert uploads.put_content(target, PNG_BYTES).status_code == 204

    body = uploads.complete_ok(target.upload_id)
    assert body.upload_key == target.upload_id
    assert body.filename == "page.png"
    assert body.byte_size == len(PNG_BYTES)
    assert body.artifact_type == "file.png@1"
    assert body.notice is None


def test_upload_endpoint_rejects_an_oversize_reservation(
    builtin_client: TestClient,
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    service, _, _ = _upload_service(
        tmp_path,
        max_upload_bytes=1024 * 1024,
        unit_of_work=unit_of_work,
    )
    application = cast(FastAPI, builtin_client.app)
    application.dependency_overrides[upload_service] = lambda: service

    uploads = GrafyApi(builtin_client).workspace(WORKSPACE_ID).uploads
    response = uploads.create(
        "large.bin",
        1024 * 1024 + 1,
        content_type="application/octet-stream",
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": ("Upload 'large.bin' exceeds the upload limit of 1048576 bytes")
    }
    assert asyncio.run(_uploads(unit_of_work, WORKSPACE_ID)) == []
    assert asyncio.run(_stored_files(tmp_path / "objects")) == []


def test_upload_endpoint_reports_a_file_format_mismatch(
    builtin_client: TestClient,
) -> None:
    uploads = GrafyApi(builtin_client).workspace(WORKSPACE_ID).uploads

    response = uploads.upload("scan.png", b"not a png")

    assert response.status_code == 422
    assert response.json() == {
        "detail": {
            "code": "file_format_mismatch",
            "message": (
                "'scan.png' does not look like a PNG file. "
                "Rename it or convert it, then try again."
            ),
        }
    }


def test_upload_endpoint_carries_the_resolved_artifact_type(
    builtin_client: TestClient,
) -> None:
    uploads = GrafyApi(builtin_client).workspace(WORKSPACE_ID).uploads

    body = uploads.upload_ok("Scan.PNG", PNG_BYTES, content_type="image/png")

    assert body.artifact_type == "file.png@1"
    assert body.notice is None


def test_upload_endpoint_shows_the_blob_informational_line(
    builtin_client: TestClient,
) -> None:
    uploads = GrafyApi(builtin_client).workspace(WORKSPACE_ID).uploads

    body = uploads.upload_ok("notes.xyz", b"opaque bytes")

    assert body.artifact_type == "file.blob@1"
    assert body.notice == "Format not recognized, stored as a blob."


def test_image_upload_materializes_sample_images(
    builtin_client: TestClient,
) -> None:
    uploads = GrafyApi(builtin_client).workspace(WORKSPACE_ID).uploads

    items = uploads.create_samples_ok(SampleRequest(count=2))

    assert [item.artifact_type for item in items] == ["file.png@1", "file.png@1"]
    assert [item.filename for item in items] == [
        "sample-page-1.png",
        "sample-page-2.png",
    ]
    assert all(item.byte_size > 0 for item in items)


def test_upload_endpoint_requires_content_only_on_the_local_backend(
    builtin_client: TestClient,
) -> None:
    uploads = GrafyApi(builtin_client).workspace(WORKSPACE_ID).uploads

    target = uploads.create_ok("page.png", len(PNG_BYTES))

    assert uploads.put_content(target, PNG_BYTES).status_code == 204


class _PresigningStore:
    """A deployment whose storage signs its own upload targets."""

    def __init__(self, inner: LocalFileObjectStore) -> None:
        self._inner = inner

    async def create_presigned_upload(
        self,
        bucket: str,
        path: str,
        *,
        expires_in: timedelta,
    ) -> str:
        del expires_in
        return f"https://storage.example.test/{bucket}/{path}"

    async def save(self, command: SaveFileCommand) -> StoredFile:
        return await self._inner.save(command)

    async def move(self, bucket: str, source_path: str, destination_path: str) -> None:
        await self._inner.move(bucket, source_path, destination_path)

    async def load(self, bucket: str, path: str) -> FileStreamProtocol:
        return await self._inner.load(bucket, path)

    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        return await self._inner.stat(bucket, path)

    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes:
        return await self._inner.load_range(bucket, path, start, end_exclusive)

    async def delete(self, bucket: str, path: str) -> None:
        await self._inner.delete(bucket, path)


async def test_a_presigning_deployment_hands_out_signed_targets_only(
    tmp_path: Path,
) -> None:
    presigning = _PresigningStore(LocalFileObjectStore(tmp_path / "objects"))
    service, _, _ = _upload_service(tmp_path, presigning=presigning)

    assert service.accepts_direct_upload is False

    target = await service.create_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename="page.png",
        byte_size=len(PNG_BYTES),
    )
    assert target.url == (
        f"https://storage.example.test/{BUCKET}/objects/{target.upload_id}"
    )

    with pytest.raises(UploadTransportUnsupportedError, match="signed URLs"):
        await service.receive_content(
            workspace_id=WORKSPACE_ID,
            upload_id=target.upload_id,
            stream=BytesIO(PNG_BYTES),
        )
