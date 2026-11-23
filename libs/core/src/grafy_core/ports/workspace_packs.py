from datetime import datetime
from typing import Protocol
from uuid import UUID


class WorkspacePackRepositoryPort(Protocol):
    async def list_slugs(self, workspace_id: UUID) -> frozenset[str]: ...

    async def enable(
        self,
        workspace_id: UUID,
        pack_slug: str,
        *,
        enabled_at: datetime,
        enabled_by_user_id: UUID | None = None,
    ) -> None: ...

    async def disable(self, workspace_id: UUID, pack_slug: str) -> None: ...
