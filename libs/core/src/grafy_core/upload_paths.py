from pathlib import Path
from uuid import UUID

from grafy_core.ports.uploads import UploadUnitOfWorkPort


def resolve_upload_path(
    uploads_dir: Path,
    *,
    workspace_id: UUID,
    upload_id: UUID,
) -> Path:
    """Resolve one upload inside ``uploads_dir/{workspace_id}/{upload_id}``.

    The caller supplies the server-chosen upload identity, so a path outside
    the workspace directory fails closed.
    """
    workspace_dir = (uploads_dir / str(workspace_id)).resolve()
    path = (workspace_dir / str(upload_id)).resolve()
    if path.parent != workspace_dir:
        raise ValueError(
            f"Upload {upload_id} resolves outside workspace "
            f"{workspace_id} uploads directory"
        )
    return path


async def resolve_persisted_upload_path(
    uploads_dir: Path,
    unit_of_work: UploadUnitOfWorkPort,
    *,
    workspace_id: UUID,
    upload_id: UUID,
) -> Path:
    """Resolve a staged upload that has a live workspace ``Upload`` row.

    A file on disk is not authorization. Missing or foreign-workspace rows
    fail closed even when a file exists at the derived path.
    """
    _ = resolve_upload_path(
        uploads_dir,
        workspace_id=workspace_id,
        upload_id=upload_id,
    )
    async with unit_of_work as entered:
        record = await entered.uploads.get(workspace_id, upload_id)
    if record is None:
        raise FileNotFoundError(
            f"Upload {upload_id} was not found in workspace {workspace_id}"
        )
    return resolve_upload_path(
        uploads_dir,
        workspace_id=record.workspace_id,
        upload_id=record.upload_id,
    )


__all__ = [
    "resolve_persisted_upload_path",
    "resolve_upload_path",
]
