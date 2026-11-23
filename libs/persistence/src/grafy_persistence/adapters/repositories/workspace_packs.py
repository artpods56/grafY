from datetime import datetime
from typing import override
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from grafy_core.ports.workspace_packs import WorkspacePackRepositoryPort
from grafy_persistence.schema import workspace_packs


class SqlWorkspacePackRepository(WorkspacePackRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def list_slugs(self, workspace_id: UUID) -> frozenset[str]:
        slugs = await self._session.scalars(
            select(workspace_packs.c.pack_slug).where(
                workspace_packs.c.workspace_id == workspace_id
            )
        )
        return frozenset(slugs)

    @override
    async def enable(
        self,
        workspace_id: UUID,
        pack_slug: str,
        *,
        enabled_at: datetime,
        enabled_by_user_id: UUID | None = None,
    ) -> None:
        # Workspace creation can seed subscriptions within the same transaction.
        await self._session.flush()
        insert = (
            sqlite_insert
            if self._session.get_bind().dialect.name == "sqlite"
            else postgresql_insert
        )
        await self._session.execute(
            insert(workspace_packs)
            .values(
                workspace_id=workspace_id,
                pack_slug=pack_slug,
                enabled_at=enabled_at,
                enabled_by_user_id=enabled_by_user_id,
            )
            .on_conflict_do_nothing(index_elements=["workspace_id", "pack_slug"])
        )

    @override
    async def disable(self, workspace_id: UUID, pack_slug: str) -> None:
        await self._session.execute(
            delete(workspace_packs).where(
                workspace_packs.c.workspace_id == workspace_id,
                workspace_packs.c.pack_slug == pack_slug,
            )
        )
