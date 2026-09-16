from pathlib import Path
from typing import final
from uuid import UUID

from grafy_core.domain.uploads import Upload, UploadStatus
from grafy_core.ports.uploads import (
    UploadNotReadyError,
    UploadReaderPort,
    UploadUnitOfWorkPort,
)
from grafy_core.upload_paths import resolve_persisted_upload_path


class UploadBytesUnavailableError(RuntimeError):
    """An operator cannot read the bytes its configuration points at."""


async def read_confirmed_upload(
    uploads: UploadReaderPort,
    *,
    workspace_id: UUID,
    upload_key: str,
    byte_size: int,
    label: str,
) -> bytes:
    """Read one configured upload, failing with the declared identity.

    The declared byte size is the operator's own record of what it stored, so
    a mismatch means the bytes behind the key are not the configured file.
    """
    try:
        upload_id = UUID(upload_key)
    except ValueError as exc:
        raise UploadBytesUnavailableError(
            f"{label} {upload_key!r} is not a known upload identifier"
        ) from exc
    try:
        content = await uploads.read(workspace_id, upload_id)
    except (FileNotFoundError, UploadNotReadyError) as exc:
        raise UploadBytesUnavailableError(str(exc)) from exc
    if len(content) != byte_size:
        raise UploadBytesUnavailableError(
            f"{label} {upload_key!r} changed size: expected {byte_size}, "
            f"got {len(content)}"
        )
    return content


async def require_ready_upload(
    unit_of_work: UploadUnitOfWorkPort,
    workspace_id: UUID,
    upload_id: UUID,
) -> Upload:
    """Load one workspace-owned upload whose bytes were validated.

    Missing or foreign-workspace uploads fail closed, and an upload whose
    completion never succeeded is never readable.
    """
    async with unit_of_work as entered:
        record = await entered.uploads.get(workspace_id, upload_id)
    if record is None:
        raise FileNotFoundError(
            f"Upload {upload_id} was not found in workspace {workspace_id}"
        )
    if record.status is not UploadStatus.READY:
        raise UploadNotReadyError(
            f"Upload {upload_id} is {record.status.value} and has no usable bytes"
        )
    return record


@final
class BundleUploadReader:
    """Read an upload from the guest invocation bundle."""

    def __init__(
        self,
        uploads_dir: Path,
        unit_of_work: UploadUnitOfWorkPort,
    ) -> None:
        self._uploads_dir = uploads_dir.expanduser().resolve()
        self._unit_of_work = unit_of_work

    async def read(self, workspace_id: UUID, upload_id: UUID) -> bytes:
        record = await require_ready_upload(
            self._unit_of_work,
            workspace_id,
            upload_id,
        )
        path = await resolve_persisted_upload_path(
            self._uploads_dir,
            self._unit_of_work,
            workspace_id=record.workspace_id,
            upload_id=record.upload_id,
        )
        try:
            return path.read_bytes()
        except OSError as exc:
            raise FileNotFoundError(
                f"Bundle file for upload {upload_id} could not be read from {path}"
            ) from exc


__all__ = [
    "BundleUploadReader",
    "UploadBytesUnavailableError",
    "read_confirmed_upload",
    "require_ready_upload",
]
