from dataclasses import asdict, replace
from datetime import datetime
from typing import override
from uuid import UUID

from grafy_core.domain.credentials import (
    CredentialScope,
    CredentialVerificationStatus,
    EncryptedCredential,
    NodeSharedCredentialBinding,
    NodeUserCredentialOverride,
    SharedCredentialBindingMode,
    UserCredentialOverrideMode,
)
from grafy_core.ports.credentials import (
    CredentialRepositoryPort,
    NodeCredentialSelectionRepositoryPort,
)
from sqlalchemy import Table, delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from grafy_persistence import schema


class SqlCredentialRepository(CredentialRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def insert(self, record: EncryptedCredential) -> None:
        await self._session.execute(insert(schema.credentials).values(**asdict(record)))

    @override
    async def get_by_id(self, credential_id: UUID) -> EncryptedCredential | None:
        record = await self._session.get(EncryptedCredential, credential_id)
        return self._typed(record) if record is not None else None

    @override
    async def list_personal(
        self, owner_user_id: UUID, provider_kind: str | None = None
    ) -> list[EncryptedCredential]:
        return await self._list(
            owner_user_id=owner_user_id, provider_kind=provider_kind
        )

    @override
    async def list_shared(
        self, workspace_id: UUID, provider_kind: str | None = None
    ) -> list[EncryptedCredential]:
        return await self._list(workspace_id=workspace_id, provider_kind=provider_kind)

    async def _list(self, **filters: UUID | str | None) -> list[EncryptedCredential]:
        query = (
            select(EncryptedCredential)
            .filter_by(
                **{key: value for key, value in filters.items() if value is not None}
            )
            .order_by(schema.credentials.c.label, schema.credentials.c.id)
        )
        return [self._typed(record) for record in await self._session.scalars(query)]

    @staticmethod
    def _typed(record: EncryptedCredential) -> EncryptedCredential:
        return replace(
            record,
            scope=CredentialScope(record.scope),
            verification_status=CredentialVerificationStatus(
                record.verification_status
            ),
        )

    @override
    async def update(
        self, record: EncryptedCredential, *, expected_updated_at: datetime
    ) -> bool:
        values = asdict(record)
        del values["id"]
        result = await self._session.execute(
            update(schema.credentials)
            .where(
                schema.credentials.c.id == record.id,
                schema.credentials.c.updated_at == expected_updated_at,
            )
            .values(**values)
            .returning(schema.credentials.c.id)
        )
        return result.scalar_one_or_none() is not None

    @override
    async def delete(self, credential_id: UUID) -> None:
        await self._session.execute(
            delete(schema.credentials).where(schema.credentials.c.id == credential_id)
        )


class SqlNodeCredentialSelectionRepository(NodeCredentialSelectionRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def get_shared_binding(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
    ) -> NodeSharedCredentialBinding | None:
        row = await self._session.get(
            NodeSharedCredentialBinding,
            (workspace_id, project_id, graph_id, node_id, name),
        )
        return replace(row, mode=SharedCredentialBindingMode(row.mode)) if row else None

    @override
    async def list_shared_bindings_for_graph(
        self, workspace_id: UUID, project_id: UUID, graph_id: str
    ) -> list[NodeSharedCredentialBinding]:
        rows = await self._session.scalars(
            select(NodeSharedCredentialBinding).filter_by(
                workspace_id=workspace_id,
                project_id=project_id,
                graph_id=graph_id,
            )
        )
        return [
            replace(row, mode=SharedCredentialBindingMode(row.mode)) for row in rows
        ]

    @override
    async def upsert_shared_binding(self, binding: NodeSharedCredentialBinding) -> None:
        await self._upsert(schema.node_shared_credential_bindings, binding)

    @override
    async def delete_shared_binding(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
    ) -> None:
        await self._session.execute(
            delete(schema.node_shared_credential_bindings).filter_by(
                workspace_id=workspace_id,
                project_id=project_id,
                graph_id=graph_id,
                node_id=node_id,
                name=name,
            )
        )

    @override
    async def get_user_override(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        user_id: UUID,
    ) -> NodeUserCredentialOverride | None:
        row = await self._session.get(
            NodeUserCredentialOverride,
            (workspace_id, project_id, graph_id, node_id, name, user_id),
        )
        return replace(row, mode=UserCredentialOverrideMode(row.mode)) if row else None

    @override
    async def list_user_overrides_for_graph(
        self, workspace_id: UUID, project_id: UUID, graph_id: str, user_id: UUID
    ) -> list[NodeUserCredentialOverride]:
        rows = await self._session.scalars(
            select(NodeUserCredentialOverride).filter_by(
                workspace_id=workspace_id,
                project_id=project_id,
                graph_id=graph_id,
                user_id=user_id,
            )
        )
        return [replace(row, mode=UserCredentialOverrideMode(row.mode)) for row in rows]

    @override
    async def upsert_user_override(self, override: NodeUserCredentialOverride) -> None:
        await self._upsert(schema.node_user_credential_overrides, override)

    @override
    async def delete_user_override(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        node_id: str,
        name: str,
        user_id: UUID,
    ) -> None:
        await self._session.execute(
            delete(schema.node_user_credential_overrides).filter_by(
                workspace_id=workspace_id,
                project_id=project_id,
                graph_id=graph_id,
                node_id=node_id,
                name=name,
                user_id=user_id,
            )
        )

    async def _upsert(
        self,
        table: Table,
        selection: NodeSharedCredentialBinding | NodeUserCredentialOverride,
    ) -> None:
        dialect = self._session.get_bind().dialect.name
        if dialect == "sqlite":
            statement = sqlite_insert(table).values(**asdict(selection))
        elif dialect == "postgresql":
            statement = postgresql_insert(table).values(**asdict(selection))
        else:
            raise NotImplementedError(
                f"Credential selection upsert does not support {dialect!r}"
            )
        await self._session.execute(
            statement.on_conflict_do_update(
                index_elements=tuple(table.primary_key.columns),
                set_={
                    column.name: statement.excluded[column.name]
                    for column in table.columns
                    if not column.primary_key and column.name != "created_at"
                },
            )
        )
