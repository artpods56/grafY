from collections.abc import Collection
from dataclasses import replace
from typing import final, override
from uuid import UUID

from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey
from grafy_core.domain.errors import (
    LibraryFolderNameConflictError,
    ObjectAlreadyExistsError,
)
from grafy_core.domain.library import LibraryFolder
from grafy_core.ports.artifacts import ArtifactRepositoryPort
from grafy_core.ports.library_folders import LibraryFolderRepositoryPort

from grafy_core.runtime.in_memory.store import InMemoryDataStore


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
