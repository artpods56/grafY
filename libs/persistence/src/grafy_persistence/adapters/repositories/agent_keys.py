"""SQL adapter for the encrypted per-Agent model key (ADR 0021, issue #202).

The row is read and written as an ``EncryptedAgentKey``: sealed material and the
coordinates it is bound to, with no path that yields plaintext. ``remove`` clears an
Agent's own key without reading the ciphertext it held, which is what makes clearing a
key an operation a reviewer can trust.
"""

from typing import override
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from grafy_core.domain.agent_keys import EncryptedAgentKey
from grafy_core.ports.agent_keys import AgentKeyRepositoryPort
from grafy_persistence import schema


class SqlAgentKeyRepository(AgentKeyRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def upsert(self, key: EncryptedAgentKey) -> None:
        await self._session.flush()
        table = schema.agent_keys
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name == "sqlite":
            insert_statement = sqlite_insert(table)
        elif dialect_name == "postgresql":
            insert_statement = postgresql_insert(table)
        else:
            raise NotImplementedError(
                "Agent key upsert requires SQLite or PostgreSQL; "
                f"received dialect {dialect_name!r}"
            )
        insert_statement = insert_statement.values(
            workspace_id=key.workspace_id,
            project_id=key.project_id,
            graph_id=key.graph_id,
            agent_id=key.agent_id,
            key_id=key.key_id,
            aad_version=key.aad_version,
            nonce=key.nonce,
            ciphertext=key.ciphertext,
            set_by_user_id=key.set_by_user_id,
            created_at=key.created_at,
            updated_at=key.updated_at,
        )
        await self._session.execute(
            insert_statement.on_conflict_do_update(
                index_elements=(
                    table.c.workspace_id,
                    table.c.project_id,
                    table.c.graph_id,
                    table.c.agent_id,
                ),
                set_={
                    "key_id": insert_statement.excluded.key_id,
                    "aad_version": insert_statement.excluded.aad_version,
                    "nonce": insert_statement.excluded.nonce,
                    "ciphertext": insert_statement.excluded.ciphertext,
                    "set_by_user_id": insert_statement.excluded.set_by_user_id,
                    "updated_at": insert_statement.excluded.updated_at,
                },
            )
        )

    @override
    async def get(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> EncryptedAgentKey | None:
        return await self._session.get(
            EncryptedAgentKey,
            (workspace_id, project_id, graph_id, agent_id),
        )

    @override
    async def list_for_graph(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
    ) -> list[EncryptedAgentKey]:
        result = await self._session.scalars(
            select(EncryptedAgentKey)
            .where(schema.agent_keys.c.workspace_id == workspace_id)
            .where(schema.agent_keys.c.project_id == project_id)
            .where(schema.agent_keys.c.graph_id == graph_id)
            .order_by(schema.agent_keys.c.agent_id.asc())
        )
        return list(result)

    @override
    async def remove(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> None:
        await self._session.execute(
            delete(EncryptedAgentKey).where(
                schema.agent_keys.c.workspace_id == workspace_id,
                schema.agent_keys.c.project_id == project_id,
                schema.agent_keys.c.graph_id == graph_id,
                schema.agent_keys.c.agent_id == agent_id,
            )
        )
