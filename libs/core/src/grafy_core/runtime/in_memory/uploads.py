from datetime import datetime
from typing import TYPE_CHECKING, final
from uuid import UUID

if TYPE_CHECKING:
    from grafy_core.domain.uploads import Upload

from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.domain.uploads import UploadStatus

from grafy_core.runtime.in_memory.store import InMemoryDataStore, _clone


@final
class InMemoryUploadRepository:
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    async def add(self, upload: "Upload") -> None:
        key = (upload.workspace_id, upload.upload_id)
        if key in self._store.uploads:
            raise ObjectAlreadyExistsError(
                f"Upload already exists: {upload.workspace_id}/{upload.upload_id}"
            )
        self._store.uploads[key] = _clone(upload)

    async def get(self, workspace_id: UUID, upload_id: UUID) -> "Upload | None":
        upload = self._store.uploads.get((workspace_id, upload_id))
        return None if upload is None else _clone(upload)

    async def list_for_workspace(self, workspace_id: UUID) -> list["Upload"]:
        uploads = [
            _clone(upload)
            for (stored_workspace_id, _), upload in self._store.uploads.items()
            if stored_workspace_id == workspace_id
        ]
        uploads.sort(key=lambda upload: (upload.created_at, str(upload.upload_id)))
        return uploads

    async def finalize_if_pending(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        *,
        actual_size: int,
        sha256: str,
        artifact_type: str,
        artifact_schema_version: int,
        artifact_id: UUID,
        completed_at: datetime,
        not_older_than: datetime,
    ) -> "Upload | None":
        upload = self._store.uploads.get((workspace_id, upload_id))
        if (
            upload is None
            or upload.status is not UploadStatus.PENDING
            or upload.created_at < not_older_than
        ):
            return None
        upload.status = UploadStatus.READY
        upload.actual_size = actual_size
        upload.sha256 = sha256
        upload.artifact_type = artifact_type
        upload.artifact_schema_version = artifact_schema_version
        upload.artifact_id = artifact_id
        upload.completed_at = completed_at
        return _clone(upload)

    async def mark_terminal_if_pending(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        *,
        status: UploadStatus,
    ) -> "Upload | None":
        if status not in {UploadStatus.FAILED, UploadStatus.EXPIRED}:
            raise ValueError(
                f"Upload terminal transition requires failed or expired; got {status}"
            )
        upload = self._store.uploads.get((workspace_id, upload_id))
        if upload is None or upload.status is not UploadStatus.PENDING:
            return None
        upload.status = status
        return _clone(upload)

    async def list_cleanup_candidates(
        self,
        *,
        pending_before: datetime,
        terminal_before: datetime,
        limit: int = 500,
    ) -> list["Upload"]:
        candidates: list[Upload] = []
        for upload in self._store.uploads.values():
            if (
                upload.status is UploadStatus.PENDING
                and upload.created_at < pending_before
            ):
                candidates.append(_clone(upload))
            elif (
                upload.status in {UploadStatus.FAILED, UploadStatus.EXPIRED}
                and upload.created_at < terminal_before
            ):
                candidates.append(_clone(upload))
        candidates.sort(key=lambda item: (item.created_at, str(item.upload_id)))
        return candidates[:limit]

    async def delete_terminal(self, workspace_id: UUID, upload_id: UUID) -> bool:
        upload = self._store.uploads.get((workspace_id, upload_id))
        if upload is None or upload.status not in {
            UploadStatus.FAILED,
            UploadStatus.EXPIRED,
        }:
            return False
        del self._store.uploads[(workspace_id, upload_id)]
        return True
