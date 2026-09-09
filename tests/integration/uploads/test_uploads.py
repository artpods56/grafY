import asyncio
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
from grafy_api.staged_uploads import StagedUploadService
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.domain.staged_uploads import StagedUpload
from tests.support.clients import GrafyApi
from tests.support.identity import TEST_USER_ID, WORKSPACE_ID


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

    item = await service.save_upload(
        workspace_id=WORKSPACE_ID,
        created_by_user_id=TEST_USER_ID,
        filename="exact.bin",
        stream=BytesIO(b"1234"),
    )

    assert item.byte_size == 4
    assert item.workspace_id == WORKSPACE_ID
    assert item.created_by_user_id == TEST_USER_ID
    assert item.original_filename == "exact.bin"
    assert await _list_staged_uploads(unit_of_work, WORKSPACE_ID) == [item]


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
