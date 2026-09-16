"""The staged-upload reader keeps failing closed on identity mismatches.

No in-repo node reads a staged upload any more, but plugins outside this
repository declare ``staged_upload_inputs`` and call this reader, so its guards
stay under test even while the retired upload operators are gone.
"""

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.upload_reader import (
    UploadBytesUnavailableError,
    read_confirmed_upload,
)

from tests.support.uploads import bundle_upload_reader, seed_ready_upload

TEST_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")
FOREIGN_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000902")


@pytest.mark.asyncio
async def test_read_confirmed_upload_returns_the_confirmed_bytes(
    tmp_path: Path,
) -> None:
    uow = InMemoryUnitOfWork()
    upload_id = await seed_ready_upload(
        uow,
        uploads_dir=tmp_path / "uploads",
        workspace_id=TEST_WORKSPACE_ID,
        content=b"page-bytes",
        filename="page.png",
    )

    content = await read_confirmed_upload(
        bundle_upload_reader(uow, uploads_dir=tmp_path / "uploads"),
        workspace_id=TEST_WORKSPACE_ID,
        upload_key=str(upload_id),
        byte_size=len(b"page-bytes"),
        label="Staged image upload",
    )

    assert content == b"page-bytes"


@pytest.mark.asyncio
async def test_read_confirmed_upload_rejects_a_key_that_is_not_an_identifier(
    tmp_path: Path,
) -> None:
    with pytest.raises(
        UploadBytesUnavailableError, match="not a known upload identifier"
    ):
        await read_confirmed_upload(
            bundle_upload_reader(
                InMemoryUnitOfWork(),
                uploads_dir=tmp_path / "uploads",
            ),
            workspace_id=TEST_WORKSPACE_ID,
            upload_key="../outside.png",
            byte_size=1,
            label="Staged image upload",
        )


@pytest.mark.asyncio
async def test_read_confirmed_upload_rejects_an_unknown_upload(tmp_path: Path) -> None:
    with pytest.raises(UploadBytesUnavailableError, match="was not found in workspace"):
        await read_confirmed_upload(
            bundle_upload_reader(
                InMemoryUnitOfWork(),
                uploads_dir=tmp_path / "uploads",
            ),
            workspace_id=TEST_WORKSPACE_ID,
            upload_key=str(uuid4()),
            byte_size=10,
            label="Staged table upload",
        )


@pytest.mark.asyncio
async def test_read_confirmed_upload_rejects_bytes_from_another_workspace(
    tmp_path: Path,
) -> None:
    uow = InMemoryUnitOfWork()
    upload_id = await seed_ready_upload(
        uow,
        uploads_dir=tmp_path / "uploads",
        workspace_id=FOREIGN_WORKSPACE_ID,
        content=b"foreign-bytes",
        filename="foreign.png",
    )

    with pytest.raises(UploadBytesUnavailableError, match="was not found in workspace"):
        await read_confirmed_upload(
            bundle_upload_reader(uow, uploads_dir=tmp_path / "uploads"),
            workspace_id=TEST_WORKSPACE_ID,
            upload_key=str(upload_id),
            byte_size=len(b"foreign-bytes"),
            label="Staged image upload",
        )


@pytest.mark.asyncio
async def test_read_confirmed_upload_rejects_a_size_the_operator_did_not_store(
    tmp_path: Path,
) -> None:
    uow = InMemoryUnitOfWork()
    upload_id = await seed_ready_upload(
        uow,
        uploads_dir=tmp_path / "uploads",
        workspace_id=TEST_WORKSPACE_ID,
        content=b"page-bytes",
        filename="page.png",
    )

    with pytest.raises(UploadBytesUnavailableError, match="changed size"):
        await read_confirmed_upload(
            bundle_upload_reader(uow, uploads_dir=tmp_path / "uploads"),
            workspace_id=TEST_WORKSPACE_ID,
            upload_key=str(upload_id),
            byte_size=99,
            label="Staged image upload",
        )
