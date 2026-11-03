from asyncio import Lock
from collections.abc import Collection
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Self,
    final,
    override,
)
from uuid import UUID

if TYPE_CHECKING:
    from grafy_core.domain.uploads import Upload
    from grafy_core.ports.uploads import UploadRepositoryPort

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactTypeKey,
)
from grafy_core.domain.errors import (
    LibraryFolderNameConflictError,
    ObjectAlreadyExistsError,
)
from grafy_core.domain.library import LibraryFolder
from grafy_core.domain.uploads import UploadStatus
from grafy_core.ports.artifacts import ArtifactRepositoryPort, UnitOfWorkPort
from grafy_core.ports.library_folders import LibraryFolderRepositoryPort


def _clone[T](value: T) -> T:
    return deepcopy(value)


@dataclass(slots=True)
class InMemoryDataStore:
    artifacts: dict[UUID, ArtifactObject] = field(
        default_factory=dict[UUID, ArtifactObject]
    )
    uploads: dict[tuple[UUID, UUID], "Upload"] = field(
        default_factory=dict[tuple[UUID, UUID], "Upload"]
    )
    library_folders: dict[UUID, LibraryFolder] = field(
        default_factory=dict[UUID, LibraryFolder]
    )
    # (workspace_id, artifact_id) → folder_id. An artifact with no key sits at
    # the Library root, exactly like the SQL placement table.
    library_placements: dict[tuple[UUID, UUID], UUID] = field(
        default_factory=dict[tuple[UUID, UUID], UUID]
    )

    def clone(self) -> Self:
        return _clone(self)

    def replace_with(self, other: Self) -> None:
        self.artifacts = _clone(other.artifacts)
        self.uploads = _clone(other.uploads)
        self.library_folders = _clone(other.library_folders)
        self.library_placements = _clone(other.library_placements)


@final
class InMemoryArtifactRepository(ArtifactRepositoryPort):
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    @override
    async def add(self, artifact: ArtifactObject) -> None:
        if artifact.id in self._store.artifacts:
            raise ObjectAlreadyExistsError(f"Artifact already exists: {artifact.id}")
        self._store.artifacts[artifact.id] = artifact

    @override
    async def get(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactObject | None:
        artifact = self._store.artifacts.get(artifact_id)
        if artifact is None or artifact.workspace_id != workspace_id:
            return None
        return artifact

    @override
    async def get_many(
        self,
        workspace_id: UUID,
        artifact_ids: Collection[UUID],
    ) -> dict[UUID, ArtifactObject]:
        return {
            artifact_id: artifact
            for artifact_id in artifact_ids
            if (artifact := self._store.artifacts.get(artifact_id)) is not None
            and artifact.workspace_id == workspace_id
        }

    @override
    async def remove(self, workspace_id: UUID, artifact: ArtifactObject) -> None:
        if artifact.workspace_id != workspace_id:
            return
        stored = self._store.artifacts.get(artifact.id)
        if stored is not None and stored.workspace_id == workspace_id:
            self._store.artifacts.pop(artifact.id, None)

    @override
    async def list_by_type(
        self,
        workspace_id: UUID,
        key: ArtifactTypeKey,
    ) -> list[ArtifactObject]:
        return [
            artifact
            for artifact in self._store.artifacts.values()
            if artifact.workspace_id == workspace_id
            and artifact.artifact_type == key.id
            and artifact.schema_version == key.schema_version
        ]

    @override
    async def list_library(self, workspace_id: UUID) -> list[ArtifactObject]:
        return [
            artifact
            for artifact in self._store.artifacts.values()
            if artifact.workspace_id == workspace_id
            and artifact.library_provenance is not None
        ]

    @override
    async def count_artifacts_sharing_object(
        self,
        workspace_id: UUID,
        *,
        bucket: str,
        object_key: str,
        except_artifact_id: UUID,
    ) -> int:
        return sum(
            1
            for artifact in self._store.artifacts.values()
            if artifact.workspace_id == workspace_id
            and artifact.id != except_artifact_id
            and artifact.bucket == bucket
            and artifact.object_key == object_key
        )


@final
class InMemoryLibraryFolderRepository(LibraryFolderRepositoryPort):
    """The Library folder tree held in the shared in-memory store.

    Folders are handed out as copies and written back whole, which is what the
    SQL repository does with its detached dataclass. Placement rows cascade away
    with their artifact in SQL through a foreign key; nothing here reaches into
    the artifact repository to imitate that.
    """

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    def _find_sibling(
        self,
        workspace_id: UUID,
        parent_id: UUID | None,
        name_key: str,
        *,
        except_folder_id: UUID | None = None,
    ) -> LibraryFolder | None:
        for folder in self._store.library_folders.values():
            if folder.workspace_id != workspace_id:
                continue
            if folder.parent_id != parent_id or folder.name_key != name_key:
                continue
            if except_folder_id is not None and folder.id == except_folder_id:
                continue
            return folder
        return None

    @override
    async def add(self, folder: LibraryFolder) -> None:
        if (
            self._find_sibling(
                folder.workspace_id,
                folder.parent_id,
                folder.name_key,
            )
            is not None
        ):
            raise LibraryFolderNameConflictError(
                workspace_id=folder.workspace_id,
                parent_id=folder.parent_id,
                name=folder.name,
            )
        self._store.library_folders[folder.id] = replace(folder)

    @override
    async def get(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> LibraryFolder | None:
        folder = self._store.library_folders.get(folder_id)
        if folder is None or folder.workspace_id != workspace_id:
            return None
        return replace(folder)

    @override
    async def get_by_name(
        self,
        workspace_id: UUID,
        parent_id: UUID | None,
        name_key: str,
    ) -> LibraryFolder | None:
        folder = self._find_sibling(workspace_id, parent_id, name_key)
        return None if folder is None else replace(folder)

    @override
    async def list(self, workspace_id: UUID) -> list[LibraryFolder]:
        folders = [
            replace(folder)
            for folder in self._store.library_folders.values()
            if folder.workspace_id == workspace_id
        ]
        folders.sort(key=lambda folder: (folder.name_key, str(folder.id)))
        return folders

    @override
    async def save(self, folder: LibraryFolder) -> None:
        if (
            self._find_sibling(
                folder.workspace_id,
                folder.parent_id,
                folder.name_key,
                except_folder_id=folder.id,
            )
            is not None
        ):
            raise LibraryFolderNameConflictError(
                workspace_id=folder.workspace_id,
                parent_id=folder.parent_id,
                name=folder.name,
            )
        self._store.library_folders[folder.id] = replace(folder)

    @override
    async def remove(self, folder: LibraryFolder) -> None:
        _ = self._store.library_folders.pop(folder.id, None)

    @override
    async def count_children(self, workspace_id: UUID, folder_id: UUID) -> int:
        return sum(
            1
            for folder in self._store.library_folders.values()
            if folder.workspace_id == workspace_id and folder.parent_id == folder_id
        )

    @override
    async def placements(self, workspace_id: UUID) -> dict[UUID, UUID]:
        return {
            artifact_id: folder_id
            for (placement_workspace, artifact_id), folder_id in (
                self._store.library_placements.items()
            )
            if placement_workspace == workspace_id
        }

    @override
    async def count_placements(self, workspace_id: UUID, folder_id: UUID) -> int:
        return sum(
            1
            for (placement_workspace, _), placed_folder in (
                self._store.library_placements.items()
            )
            if placement_workspace == workspace_id and placed_folder == folder_id
        )

    @override
    async def place(
        self,
        workspace_id: UUID,
        artifact_ids: list[UUID],
        folder_id: UUID | None,
    ) -> None:
        for artifact_id in artifact_ids:
            key = (workspace_id, artifact_id)
            _ = self._store.library_placements.pop(key, None)
            if folder_id is not None:
                self._store.library_placements[key] = folder_id


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


@dataclass(frozen=True, slots=True)
class _InMemoryUnitOfWorkState:
    working_store: InMemoryDataStore
    artifacts: ArtifactRepositoryPort
    uploads: "UploadRepositoryPort"
    library_folders: "LibraryFolderRepositoryPort"


class InMemoryUnitOfWork(UnitOfWorkPort):
    def __init__(self, store: InMemoryDataStore | None = None) -> None:
        self._store = store or InMemoryDataStore()
        self._transaction_lock = Lock()
        self._state: ContextVar[_InMemoryUnitOfWorkState | None] = ContextVar(
            "grafy_in_memory_unit_of_work_state",
            default=None,
        )
        self.commit_count = 0
        self.rollback_count = 0

    @property
    @override
    def artifacts(self) -> ArtifactRepositoryPort:
        return self._entered_state().artifacts

    @property
    def uploads(self) -> "UploadRepositoryPort":
        return self._entered_state().uploads

    @property
    def library_folders(self) -> "LibraryFolderRepositoryPort":
        return self._entered_state().library_folders

    @override
    async def __aenter__(self) -> Self:
        if self._state.get() is not None:
            raise RuntimeError("Unit of work is already entered in this task")

        await self._transaction_lock.acquire()
        try:
            working_store = self._store.clone()
            self._state.set(
                _InMemoryUnitOfWorkState(
                    working_store=working_store,
                    artifacts=InMemoryArtifactRepository(working_store),
                    uploads=InMemoryUploadRepository(working_store),
                    library_folders=InMemoryLibraryFolderRepository(working_store),
                )
            )
        except BaseException:
            self._transaction_lock.release()
            raise
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc, traceback
        state = self._state.get()
        if state is None:
            return
        try:
            if exc_type is not None:
                await self.rollback()
        finally:
            self._state.set(None)
            self._transaction_lock.release()

    @override
    async def commit(self) -> None:
        state = self._entered_state()
        self._store.replace_with(state.working_store)
        self.commit_count += 1

    @override
    async def rollback(self) -> None:
        state = self._entered_state()
        state.working_store.replace_with(self._store)
        self.rollback_count += 1

    def _entered_state(self) -> _InMemoryUnitOfWorkState:
        state = self._state.get()
        if state is None:
            raise RuntimeError("Unit of work is not entered")
        return state
