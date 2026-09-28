from typing import Protocol
from uuid import UUID

from grafy_core.domain.library import LibraryFolder


class LibraryFolderRepositoryPort(Protocol):
    """The Library folder tree, and which folder each Library artifact sits in.

    An artifact with no placement row is at the root, so "unfiled" needs no
    sentinel folder and placements disappear with the artifact they point at.
    """

    async def add(self, folder: LibraryFolder) -> None:
        """Insert one folder.

        Raises ``LibraryFolderNameConflictError`` when a sibling already holds
        the name.
        """

        ...

    async def get(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> LibraryFolder | None: ...

    async def get_by_name(
        self,
        workspace_id: UUID,
        parent_id: UUID | None,
        name_key: str,
    ) -> LibraryFolder | None: ...

    async def list(self, workspace_id: UUID) -> list[LibraryFolder]:
        """Every folder in the workspace; the panel assembles the tree."""

        ...

    async def save(self, folder: LibraryFolder) -> None:
        """Persist a renamed or moved folder.

        Raises ``LibraryFolderNameConflictError`` when a sibling already holds
        the name.
        """

        ...

    async def remove(self, folder: LibraryFolder) -> None: ...

    async def count_children(self, workspace_id: UUID, folder_id: UUID) -> int: ...

    async def placements(self, workspace_id: UUID) -> dict[UUID, UUID]:
        """``artifact_id → folder_id`` for every filed Library artifact."""

        ...

    async def count_placements(self, workspace_id: UUID, folder_id: UUID) -> int: ...

    async def place(
        self,
        workspace_id: UUID,
        artifact_ids: list[UUID],
        folder_id: UUID | None,
    ) -> None:
        """File the artifacts in ``folder_id``, or unfile them when it is ``None``."""

        ...
