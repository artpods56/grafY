from pathlib import Path
from uuid import UUID

import pytest

from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.domain.staged_uploads import StagedUpload
from grafy_core.staged_upload_paths import (
    resolve_persisted_staged_upload_path,
    resolve_staged_upload_path,
)


WORKSPACE_ONE = UUID("00000000-0000-0000-0000-000000000901")
WORKSPACE_TWO = UUID("00000000-0000-0000-0000-000000000902")


async def seed_staged_upload(
    unit_of_work: InMemoryUnitOfWork,
    *,
    workspace_id: UUID,
    upload_key: str,
    filename: str = "page.png",
    byte_size: int = 1,
) -> None:
    async with unit_of_work as entered:
        await entered.staged_uploads.add(
            StagedUpload(
                workspace_id=workspace_id,
                upload_key=upload_key,
                original_filename=filename,
                byte_size=byte_size,
            )
        )
        await entered.commit()


def test_resolve_staged_upload_path_rejects_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="opaque relative name"):
        resolve_staged_upload_path(
            tmp_path / "uploads",
            workspace_id=WORKSPACE_ONE,
            upload_key="../escape.png",
        )


@pytest.mark.asyncio
async def test_persisted_resolve_requires_live_row_even_when_file_exists(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    path = uploads_dir / str(WORKSPACE_ONE) / "orphan.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")

    with pytest.raises(FileNotFoundError, match="was not found in workspace"):
        await resolve_persisted_staged_upload_path(
            uploads_dir,
            InMemoryUnitOfWork(),
            workspace_id=WORKSPACE_ONE,
            upload_key="orphan.png",
        )


@pytest.mark.asyncio
async def test_persisted_resolve_fails_closed_for_foreign_workspace_row(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    path = uploads_dir / str(WORKSPACE_ONE) / "page.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    uow = InMemoryUnitOfWork()
    await seed_staged_upload(
        uow,
        workspace_id=WORKSPACE_TWO,
        upload_key="page.png",
    )

    with pytest.raises(FileNotFoundError, match="was not found in workspace"):
        await resolve_persisted_staged_upload_path(
            uploads_dir,
            uow,
            workspace_id=WORKSPACE_ONE,
            upload_key="page.png",
        )


@pytest.mark.asyncio
async def test_persisted_resolve_opens_path_for_live_workspace_row(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    path = uploads_dir / str(WORKSPACE_ONE) / "page.png"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    uow = InMemoryUnitOfWork()
    await seed_staged_upload(
        uow,
        workspace_id=WORKSPACE_ONE,
        upload_key="page.png",
    )

    resolved = await resolve_persisted_staged_upload_path(
        uploads_dir,
        uow,
        workspace_id=WORKSPACE_ONE,
        upload_key="page.png",
    )
    assert resolved == path.resolve()
    assert resolved.read_bytes() == b"x"
