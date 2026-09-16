from pathlib import Path
from uuid import UUID


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


__all__ = [
    "resolve_upload_path",
]
