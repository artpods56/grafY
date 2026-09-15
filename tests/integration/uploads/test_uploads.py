import asyncio
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import cast, override
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from grafy_api.settings import (
    STAGED_UPLOAD_HARD_MAX_BYTES,
    Settings,
)
from grafy_api.v1.routes.uploads.dependencies import staged_upload_service
from grafy_api.staged_uploads import (
    FileFormatMismatchError,
    StagedUploadService,
)
from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey
from grafy_core.file_contracts import (
    BLOB_FILE,
    BUILTIN_FILE_FORMATS,
    build_extension_table,
)
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.domain.staged_uploads import StagedUpload
from grafy_storage import LocalFileObjectStore
from tests.support.clients import GrafyApi
from tests.support.identity import TEST_USER_ID, WORKSPACE_ID


PNG_BYTES = b"\x89PNG\r\n\x1a\nstaged payload"
UPLOAD_FORMAT_TYPES = {
    (spec.key.id, spec.key.schema_version): spec for spec in BUILTIN_FILE_FORMATS
}
UPLOAD_EXTENSION_CLAIMS = build_extension_table(
    (spec.key, spec.extensions) for spec in BUILTIN_FILE_FORMATS
)


def _artifact_upload_service(
    tmp_path: Path,
) -> tuple[StagedUploadService, InMemoryUnitOfWork, LocalFileObjectStore]:
    unit_of_work = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    service = StagedUploadService(
        tmp_path / "uploads",
        unit_of_work_factory=lambda: unit_of_work,
        artifact_unit_of_work=unit_of_work,
        storage=storage,
        artifact_types=UPLOAD_FORMAT_TYPES,
        extension_claims=UPLOAD_EXTENSION_CLAIMS,
        artifact_bucket="workbench-artifacts",
    )
    return service, unit_of_work, storage


async def _artifacts(
    unit_of_work: InMemoryUnitOfWork,
    key: ArtifactTypeKey,
) -> list[ArtifactObject]:
    async with unit_of_work as entered:
        return await entered.artifacts.list_by_type(WORKSPACE_ID, key)


async def _list_staged_uploads(
    unit_of_work: InMemoryUnitOfWork,
    workspace_id: UUID,
) -> list[StagedUpload]:
    async with unit_of_work as entered:
        return await entered.staged_uploads.list_for_workspace(workspace_id)


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
        StagedUploadService(
            tmp_path / "uploads",
            unit_of_work_factory=InMemoryUnitOfWork,
            max_upload_bytes=STAGED_UPLOAD_HARD_MAX_BYTES + 1,
        )


def test_upload_endpoint_rejects_oversize_file_and_removes_partial_stage(
    builtin_client: TestClient,
    tmp_path: Path,
) -> None:
    unit_of_work = InMemoryUnitOfWork()
    service = StagedUploadService(
        tmp_path / "limited-uploads",
        unit_of_work_factory=lambda: unit_of_work,
        max_upload_bytes=1024 * 1024,
    )
    application = cast(FastAPI, builtin_client.app)
    application.dependency_overrides[staged_upload_service] = lambda: service

    api = GrafyApi(builtin_client)
    uploads = api.workspace(WORKSPACE_ID).uploads
    response = uploads.upload(
        "large.bin",
        b"x" * (1024 * 1024 + 1),
        content_type="application/octet-stream",
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": (
            "Upload 'large.bin' exceeds the staged-upload limit of 1048576 bytes"
        )
    }
    workspace_dir = tmp_path / "limited-uploads" / str(WORKSPACE_ID)
    assert list(workspace_dir.iterdir()) == []
    assert asyncio.run(_list_staged_uploads(unit_of_work, WORKSPACE_ID)) == []


async def test_upload_at_exact_byte_limit_is_staged(tmp_path: Path) -> None:
    unit_of_work = InMemoryUnitOfWork()
    service = StagedUploadService(
        tmp_path / "uploads",
        unit_of_work_factory=lambda: unit_of_work,
        max_upload_bytes=4,
    )

    result = await service.save_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename="exact.bin",
        stream=BytesIO(b"1234"),
    )
    item = result.upload

    assert item.byte_size == 4
    assert item.workspace_id == WORKSPACE_ID
    assert item.created_by_user_id == TEST_USER_ID
    assert item.original_filename == "exact.bin"
    assert await _list_staged_uploads(unit_of_work, WORKSPACE_ID) == [item]


async def test_upload_resolves_a_known_extension_case_insensitively(
    tmp_path: Path,
) -> None:
    service, unit_of_work, storage = _artifact_upload_service(tmp_path)

    result = await service.save_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename="Scan.PNG",
        stream=BytesIO(PNG_BYTES),
    )

    assert result.artifact_type == ArtifactTypeKey("file.png", 1)
    artifacts = await _artifacts(unit_of_work, ArtifactTypeKey("file.png", 1))
    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.content_type == "image/png"
    assert artifact.byte_size == len(PNG_BYTES)
    assert artifact.sha256 == sha256(PNG_BYTES).hexdigest()
    assert artifact.metadata == {"original_filename": "Scan.PNG"}
    assert artifact.workspace_id == WORKSPACE_ID
    assert artifact.storage_backend == "local"
    assert artifact.bucket == "workbench-artifacts"
    assert artifact.object_key is not None
    stored = await storage.stat("workbench-artifacts", artifact.object_key)
    assert stored is not None
    assert stored.byte_size == len(PNG_BYTES)


async def test_upload_rejects_a_known_extension_whose_bytes_disagree(
    tmp_path: Path,
) -> None:
    service, unit_of_work, _ = _artifact_upload_service(tmp_path)

    with pytest.raises(FileFormatMismatchError) as raised:
        await service.save_upload(
            workspace_id=WORKSPACE_ID,
            created_by_user_id=TEST_USER_ID,
            filename="scan.png",
            stream=BytesIO(b"not a png"),
        )

    assert str(raised.value) == (
        "'scan.png' does not look like a PNG file. "
        "Rename it or convert it, then try again."
    )
    assert await _artifacts(unit_of_work, ArtifactTypeKey("file.png", 1)) == []
    assert await _list_staged_uploads(unit_of_work, WORKSPACE_ID) == []
    assert [path for path in (tmp_path / "uploads").rglob("*") if path.is_file()] == []
    assert [path for path in (tmp_path / "objects").rglob("*") if path.is_file()] == []


@pytest.mark.parametrize("filename", ["notes.xyz", "README", ".gitignore"])
async def test_upload_stores_an_unclaimed_or_missing_extension_as_a_blob(
    tmp_path: Path,
    filename: str,
) -> None:
    service, unit_of_work, _ = _artifact_upload_service(tmp_path)

    result = await service.save_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename=filename,
        stream=BytesIO(b"opaque bytes"),
    )

    assert result.artifact_type == BLOB_FILE.key
    artifacts = await _artifacts(unit_of_work, BLOB_FILE.key)
    assert [artifact.metadata for artifact in artifacts] == [
        {"original_filename": filename}
    ]


async def test_upload_confirms_a_json_extension_with_its_declared_rule(
    tmp_path: Path,
) -> None:
    service, unit_of_work, _ = _artifact_upload_service(tmp_path)
    key = ArtifactTypeKey("file.json", 1)

    accepted = await service.save_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename="rows.json",
        stream=BytesIO(b'[{"a": 1}]'),
    )
    assert accepted.artifact_type == key

    with pytest.raises(FileFormatMismatchError, match="does not look like a JSON"):
        await service.save_upload(
            workspace_id=WORKSPACE_ID,
            created_by_user_id=TEST_USER_ID,
            filename="value.json",
            stream=BytesIO(b"17"),
        )
    assert len(await _artifacts(unit_of_work, key)) == 1


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


class FailingCommitUnitOfWork(InMemoryUnitOfWork):
    @override
    async def commit(self) -> None:
        raise RuntimeError("staging commit failed")


@pytest.mark.parametrize("samples", [False, True])
async def test_failed_staging_commit_removes_all_files_and_rows(
    tmp_path: Path,
    samples: bool,
) -> None:
    unit_of_work = FailingCommitUnitOfWork()
    upload_root = tmp_path / "uploads"
    service = StagedUploadService(upload_root, lambda: unit_of_work)
    with pytest.raises(RuntimeError, match="staging commit failed"):
        if samples:
            await service.create_sample_images(
                workspace_id=WORKSPACE_ID,
                created_by_user_id=TEST_USER_ID,
                count=3,
            )
        else:
            await service.save_upload(
                workspace_id=WORKSPACE_ID,
                created_by_user_id=TEST_USER_ID,
                filename="data.bin",
                stream=BytesIO(b"contents"),
            )
    assert [path for path in upload_root.rglob("*") if path.is_file()] == []
    assert await _list_staged_uploads(unit_of_work, WORKSPACE_ID) == []


async def test_domain_validation_failure_removes_staged_file(tmp_path: Path) -> None:
    unit_of_work = InMemoryUnitOfWork()
    upload_root = tmp_path / "uploads"
    service = StagedUploadService(upload_root, lambda: unit_of_work)
    with pytest.raises(ValueError, match="original filename must not be blank"):
        await service.save_upload(
            workspace_id=WORKSPACE_ID,
            created_by_user_id=TEST_USER_ID,
            filename="   ",
            stream=BytesIO(b"contents"),
        )
    assert [path for path in upload_root.rglob("*") if path.is_file()] == []
    assert await _list_staged_uploads(unit_of_work, WORKSPACE_ID) == []
