from uuid import UUID

from grafy_core.domain.errors import (
    LibraryFolderCycleError,
    LibraryFolderNameConflictError,
    LibraryFolderNotEmptyError,
    NotFoundError,
)
from grafy_core.domain.library import LibraryFolder, is_descendant_folder
from grafy_core.ports.workbench import WorkbenchUnitOfWorkPort

from grafy_api.library.models import LibraryFolderResponse


class LibraryFoldersService:
    """The Library tree the workspace owns, and where its artifacts are filed.

    The rules are the ones ADR 0010 handed the server: folders nest to any depth,
    a folder never moves inside itself, sibling names are unique without regard to
    case, and a folder deletes only when empty. An artifact with no placement row
    sits at the root, so "unfile" is a delete rather than a sentinel folder.
    """

    def __init__(self, uow: WorkbenchUnitOfWorkPort) -> None:
        self._uow = uow

    async def list_folders(self, workspace_id: UUID) -> list[LibraryFolderResponse]:
        async with self._uow as uow:
            folders = await uow.library_folders.list(workspace_id)
        return [LibraryFolderResponse.from_folder(folder) for folder in folders]

    async def create_folder(
        self,
        *,
        workspace_id: UUID,
        name: str,
        parent_id: UUID | None,
    ) -> LibraryFolderResponse:
        folder = LibraryFolder(
            workspace_id=workspace_id, name=name, parent_id=parent_id
        )
        async with self._uow as uow:
            await self._require_folder_when_set(uow, workspace_id, parent_id)
            await self._require_name_free(
                uow,
                workspace_id=workspace_id,
                parent_id=parent_id,
                name_key=folder.name_key,
            )
            await uow.library_folders.add(folder)
            await uow.commit()
        return LibraryFolderResponse.from_folder(folder)

    async def rename_folder(
        self,
        *,
        workspace_id: UUID,
        folder_id: UUID,
        name: str,
    ) -> LibraryFolderResponse:
        async with self._uow as uow:
            folder = await self._require_folder(uow, workspace_id, folder_id)
            candidate = LibraryFolder(
                workspace_id=workspace_id,
                name=name,
                parent_id=folder.parent_id,
            )
            await self._require_name_free(
                uow,
                workspace_id=workspace_id,
                parent_id=folder.parent_id,
                name_key=candidate.name_key,
                except_folder_id=folder_id,
            )
            folder.rename(candidate.name)
            await uow.library_folders.save(folder)
            await uow.commit()
        return LibraryFolderResponse.from_folder(folder)

    async def delete_folder(self, *, workspace_id: UUID, folder_id: UUID) -> None:
        """Delete one empty folder. Contents are the caller's problem first."""
        async with self._uow as uow:
            folder = await self._require_folder(uow, workspace_id, folder_id)
            artifact_count = await uow.library_folders.count_placements(
                workspace_id,
                folder_id,
            )
            child_count = await uow.library_folders.count_children(
                workspace_id,
                folder_id,
            )
            if artifact_count or child_count:
                raise LibraryFolderNotEmptyError(
                    folder_id=folder_id,
                    artifact_count=artifact_count,
                    child_count=child_count,
                )
            await uow.library_folders.remove(folder)
            await uow.commit()

    async def move_folder(
        self,
        *,
        workspace_id: UUID,
        folder_id: UUID,
        parent_id: UUID | None,
    ) -> LibraryFolderResponse:
        async with self._uow as uow:
            folder = await self._require_folder(uow, workspace_id, folder_id)
            await self._require_folder_when_set(uow, workspace_id, parent_id)
            if parent_id is not None:
                folders = await uow.library_folders.list(workspace_id)
                if is_descendant_folder(
                    folders,
                    candidate_id=parent_id,
                    ancestor_id=folder_id,
                ):
                    raise LibraryFolderCycleError(
                        folder_id=folder_id,
                        parent_id=parent_id,
                    )
            await self._require_name_free(
                uow,
                workspace_id=workspace_id,
                parent_id=parent_id,
                name_key=folder.name_key,
                except_folder_id=folder_id,
            )
            folder.move_to(parent_id)
            await uow.library_folders.save(folder)
            await uow.commit()
        return LibraryFolderResponse.from_folder(folder)

    async def place_artifacts(
        self,
        *,
        workspace_id: UUID,
        artifact_ids: list[UUID],
        folder_id: UUID | None,
    ) -> None:
        """File the artifacts in one folder, or unfile them when it is ``None``.

        An artifact the workspace does not have is an error naming it: silently
        filing half of a drop would leave the panel showing a placement that
        never happened.
        """
        unique_ids = list(dict.fromkeys(artifact_ids))
        async with self._uow as uow:
            await self._require_folder_when_set(uow, workspace_id, folder_id)
            found = await uow.artifacts.get_many(workspace_id, unique_ids)
            for artifact_id in unique_ids:
                artifact = found.get(artifact_id)
                if artifact is None:
                    raise NotFoundError("Artifact", str(artifact_id))
                if artifact.library_provenance is None:
                    # A placement row describes where a Library artifact is filed.
                    # Filing something that is not in the Library would leave a row
                    # no listing ever shows, and an artifact that lands in the
                    # Library later would arrive already filed somewhere.
                    raise NotFoundError("Library artifact", str(artifact_id))
            await uow.library_folders.place(
                workspace_id,
                unique_ids,
                folder_id,
            )
            await uow.commit()

    async def _require_folder(
        self,
        uow: WorkbenchUnitOfWorkPort,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> LibraryFolder:
        folder = await uow.library_folders.get(workspace_id, folder_id)
        if folder is None:
            raise NotFoundError("Library folder", str(folder_id))
        return folder

    async def _require_folder_when_set(
        self,
        uow: WorkbenchUnitOfWorkPort,
        workspace_id: UUID,
        folder_id: UUID | None,
    ) -> None:
        """Require a folder only when one was named; ``None`` is the root."""
        if folder_id is None:
            return
        await self._require_folder(uow, workspace_id, folder_id)

    async def _require_name_free(
        self,
        uow: WorkbenchUnitOfWorkPort,
        *,
        workspace_id: UUID,
        parent_id: UUID | None,
        name_key: str,
        except_folder_id: UUID | None = None,
    ) -> None:
        """Reject a name one sibling already answers to.

        The unique indexes are the backstop under concurrent writers; this check
        is what turns their violation into a name the panel can repeat to the
        user.
        """
        taken = await uow.library_folders.get_by_name(
            workspace_id,
            parent_id,
            name_key,
        )
        if taken is not None and taken.id != except_folder_id:
            raise LibraryFolderNameConflictError(
                workspace_id=workspace_id,
                parent_id=parent_id,
                name=taken.name,
            )


__all__ = ["LibraryFoldersService"]
