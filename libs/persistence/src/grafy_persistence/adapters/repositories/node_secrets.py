from typing import override
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from grafy_core.domain.node_secrets import EncryptedNodeSecret
from grafy_core.ports.node_secrets import NodeSecretRepositoryPort
from grafy_persistence import schema


class SqlNodeSecretRepository(NodeSecretRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def upsert(self, secret: EncryptedNodeSecret) -> None:
        await self._session.flush()
        table = schema.node_secrets
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name == "sqlite":
            insert_statement = sqlite_insert(table)
        elif dialect_name == "postgresql":
            insert_statement = postgresql_insert(table)
        else:
            raise NotImplementedError(
                "Node secret upsert requires SQLite or PostgreSQL; "
                f"received dialect {dialect_name!r}"
            )
        insert_statement = insert_statement.values(
            workspace_id=secret.workspace_id,
            project_id=secret.project_id,
            graph_id=secret.graph_id,
            node_id=secret.node_id,
            name=secret.name,
            operator_id=secret.operator_id,
            operator_version=secret.operator_version,
            key_id=secret.key_id,
            aad_version=secret.aad_version,
            dependency_sha256=secret.dependency_sha256,
            nonce=secret.nonce,
            ciphertext=secret.ciphertext,
            created_at=secret.created_at,
            updated_at=secret.updated_at,
        )
        await self._session.execute(
            insert_statement.on_conflict_do_update(
                index_elements=(
                    table.c.workspace_id,
                    table.c.project_id,
                    table.c.graph_id,
                    table.c.node_id,
                    table.c.name,
                ),
                set_={
                    "operator_id": insert_statement.excluded.operator_id,
                    "operator_version": insert_statement.excluded.operator_version,
                    "key_id": insert_statement.excluded.key_id,
                    "aad_version": insert_statement.excluded.aad_version,
                    "dependency_sha256": (insert_statement.excluded.dependency_sha256),
                    "nonce": insert_statement.excluded.nonce,
                    "ciphertext": insert_statement.excluded.ciphertext,
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
        node_id: str,
        name: str,
    ) -> EncryptedNodeSecret | None:
        return await self._session.get(
            EncryptedNodeSecret,
            (workspace_id, project_id, graph_id, node_id, name),
        )

    @override
    async def list_for_graph(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
    ) -> list[EncryptedNodeSecret]:
        result = await self._session.scalars(
            select(EncryptedNodeSecret)
            .where(schema.node_secrets.c.project_id == project_id)
            .where(schema.node_secrets.c.graph_id == graph_id)
            .where(schema.node_secrets.c.workspace_id == workspace_id)
            .order_by(
                schema.node_secrets.c.node_id.asc(),
                schema.node_secrets.c.name.asc(),
            )
        )
        return list(result)

    @override
    async def remove(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
    ) -> None:
        await self._session.execute(
            delete(EncryptedNodeSecret).where(
                schema.node_secrets.c.workspace_id == workspace_id,
                schema.node_secrets.c.project_id == project_id,
                schema.node_secrets.c.graph_id == graph_id,
                schema.node_secrets.c.node_id == node_id,
                schema.node_secrets.c.name == name,
            )
        )
