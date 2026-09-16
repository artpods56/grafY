"""Seed confirmed uploads for operator-level tests."""

from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID, uuid4

from grafy_core.domain.uploads import Upload, UploadStatus
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.upload_reader import BundleUploadReader


async def seed_ready_upload(
    unit_of_work: InMemoryUnitOfWork,
    *,
    uploads_dir: Path,
    workspace_id: UUID,
    content: bytes,
    filename: str,
) -> UUID:
    """Store one confirmed upload in the bundle layout and return its identifier.

    The value an operator declares as ``upload_key`` is this identifier, so
    callers pass the result straight into node config.
    """
    upload_id = uuid4()
    workspace_uploads = uploads_dir / str(workspace_id)
    workspace_uploads.mkdir(parents=True, exist_ok=True)
    (workspace_uploads / str(upload_id)).write_bytes(content)
    async with unit_of_work as entered:
        await entered.uploads.add(
            Upload(
                workspace_id=workspace_id,
                upload_id=upload_id,
                original_filename=filename,
                bucket="guest-bundle",
                object_key=f"uploads/{workspace_id}/{upload_id}",
                expected_size=len(content),
                status=UploadStatus.READY,
                actual_size=len(content),
                sha256=sha256(content).hexdigest(),
                completed_at=datetime.now(UTC),
            )
        )
        await entered.commit()
    return upload_id


def bundle_upload_reader(
    unit_of_work: InMemoryUnitOfWork,
    *,
    uploads_dir: Path,
) -> BundleUploadReader:
    return BundleUploadReader(uploads_dir, unit_of_work)


__all__ = ["bundle_upload_reader", "seed_ready_upload"]
