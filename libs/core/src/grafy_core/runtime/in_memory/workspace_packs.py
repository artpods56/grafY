from datetime import datetime
from typing import override
from uuid import UUID

from grafy_core.ports.workspace_packs import WorkspacePackRepositoryPort
from grafy_core.runtime.in_memory.store import InMemoryDataStore


class InMemoryWorkspacePackRepository(WorkspacePackRepositoryPort):
    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    @override
    async def list_slugs(self, workspace_id: UUID) -> frozenset[str]:
        return frozenset(
            slug for owner, slug in self._store.workspace_packs if owner == workspace_id
        )

    @override
    async def enable(
        self,
        workspace_id: UUID,
        pack_slug: str,
        *,
        enabled_at: datetime,
        enabled_by_user_id: UUID | None = None,
    ) -> None:
        self._store.workspace_packs.setdefault(
            (workspace_id, pack_slug), (enabled_at, enabled_by_user_id)
        )

    @override
    async def disable(self, workspace_id: UUID, pack_slug: str) -> None:
        self._store.workspace_packs.pop((workspace_id, pack_slug), None)
