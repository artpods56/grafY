from datetime import UTC, datetime
from typing import cast, override
from uuid import UUID
from sqlalchemy import (
    and_,
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from grafy_core.domain.identity import (
    WorkspaceKind,
    WorkspaceRole,
)
from grafy_core.domain.errors import (
    GraphFolderNameConflictError,
)
from grafy_core.domain.node_secrets import EncryptedNodeSecret
from grafy_core.domain.collaboration import (
    CollaborativeGraphHead,
    GraphCheckpointMapping,
    GraphCommandReceipt,
)
from grafy_core.domain.saved_graphs import (
    GraphBrowserCreator,
    GraphBrowserDraft,
    GraphBrowserFolder,
    GraphBrowserItem,
    GraphBrowserLocation,
    GraphFolder,
    GraphOrganization,
    SavedGraph,
    SavedGraphDocument,
    SavedGraphRevision,
    UserGraphState,
)
from grafy_core.ports.node_secrets import NodeSecretRepositoryPort
from grafy_core.ports.saved_graphs import SavedGraphRepositoryPort
from grafy_persistence import schema
from grafy_persistence.orm import SavedGraphRevisionRecord


class SqlSavedGraphRepository(SavedGraphRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, graph: SavedGraph) -> None:
        self._session.add(graph)
        # Collaborative heads FK to saved_graphs; flush so later head inserts see the row.
        await self._session.flush()

    @override
    async def add_revision(self, revision: SavedGraphRevision) -> None:
        self._session.add(
            SavedGraphRevisionRecord(
                workspace_id=revision.workspace_id,
                graph_id=revision.graph_id,
                revision=revision.revision,
                name=revision.name,
                document=revision.document,
                created_at=revision.created_at,
            ),
        )
        # Checkpoint mappings FK to revisions; flush before collaboration Core inserts.
        await self._session.flush()

    @override
    async def lock_revision(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        expected_revision: int,
    ) -> None:
        table = schema.saved_graphs
        await self._session.execute(
            update(table)
            .where(
                table.c.id == graph_id,
                table.c.workspace_id == workspace_id,
                table.c.revision == expected_revision,
            )
            .values(revision=table.c.revision)
        )

    @override
    async def get(self, workspace_id: UUID, graph_id: UUID) -> SavedGraph | None:
        return await self._session.scalar(
            select(SavedGraph).where(
                schema.saved_graphs.c.workspace_id == workspace_id,
                schema.saved_graphs.c.id == graph_id,
            )
        )

    @override
    async def get_revision(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        revision: int,
    ) -> SavedGraphRevision | None:
        record = await self._session.get(
            SavedGraphRevisionRecord,
            (workspace_id, graph_id, revision),
        )
        if record is None:
            return None
        return SavedGraphRevision(
            graph_id=record.graph_id,
            workspace_id=record.workspace_id,
            revision=record.revision,
            name=record.name,
            document=record.document,
            created_at=record.created_at,
        )

    @override
    async def list_revisions(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> list[SavedGraphRevision]:
        result = await self._session.scalars(
            select(SavedGraphRevisionRecord)
            .where(schema.saved_graph_revisions.c.graph_id == graph_id)
            .where(schema.saved_graph_revisions.c.workspace_id == workspace_id)
            .order_by(schema.saved_graph_revisions.c.revision.desc())
        )
        return [
            SavedGraphRevision(
                graph_id=record.graph_id,
                workspace_id=record.workspace_id,
                revision=record.revision,
                name=record.name,
                document=record.document,
                created_at=record.created_at,
            )
            for record in result
        ]

    @override
    async def list_accessible(
        self,
        user_id: UUID,
        *,
        workspace_id: UUID | None = None,
    ) -> list[GraphBrowserItem]:
        graphs = schema.saved_graphs
        memberships = schema.workspace_memberships
        workspaces = schema.workspaces
        folders = schema.graph_folders
        organizations = schema.graph_organizations
        states = schema.user_graph_states
        heads = schema.collaborative_graph_heads
        active_user = schema.users.alias("active_graph_browser_user")
        creator = schema.users.alias("graph_creator")
        query = (
            select(
                graphs.c.id,
                organizations.c.archived_at,
                organizations.c.updated_at.label("organization_updated_at"),
                heads.c.name.label("head_name"),
                heads.c.document.label("head_document"),
                heads.c.collaboration_sequence,
                heads.c.checkpoint_sequence,
                heads.c.checkpoint_revision,
                heads.c.updated_at.label("head_updated_at"),
                workspaces.c.id.label("workspace_id"),
                workspaces.c.slug.label("workspace_slug"),
                workspaces.c.name.label("workspace_name"),
                workspaces.c.kind.label("workspace_kind"),
                folders.c.id.label("folder_id"),
                folders.c.name.label("folder_name"),
                states.c.starred,
                states.c.last_opened_at,
                creator.c.id.label("creator_id"),
                creator.c.display_name.label("creator_display_name"),
            )
            .select_from(
                    graphs.join(
                        memberships,
                        and_(
                            memberships.c.workspace_id == graphs.c.workspace_id,
                            memberships.c.user_id == user_id,
                            memberships.c.revoked_at.is_(None),
                            memberships.c.role.in_(
                                (
                                    WorkspaceRole.VIEWER.value,
                                    WorkspaceRole.EDITOR.value,
                                    WorkspaceRole.OWNER.value,
                                )
                            ),
                        ),
                    )
                    .join(
                        active_user,
                        and_(
                            active_user.c.id == user_id,
                            active_user.c.active.is_(True),
                        ),
                    )
                    .join(workspaces, workspaces.c.id == graphs.c.workspace_id)
                    .join(
                        heads,
                        and_(
                            heads.c.workspace_id == graphs.c.workspace_id,
                            heads.c.graph_id == graphs.c.id,
                        ),
                    )
                    .outerjoin(
                        organizations,
                        and_(
                            organizations.c.workspace_id == graphs.c.workspace_id,
                            organizations.c.graph_id == graphs.c.id,
                        ),
                    )
                    .outerjoin(
                        folders,
                        and_(
                            folders.c.workspace_id == graphs.c.workspace_id,
                            folders.c.id == organizations.c.folder_id,
                        ),
                    )
                    .outerjoin(
                        states,
                        and_(
                            states.c.workspace_id == graphs.c.workspace_id,
                            states.c.graph_id == graphs.c.id,
                            states.c.user_id == user_id,
                        ),
                    )
                .outerjoin(creator, creator.c.id == graphs.c.created_by_user_id)
            )
            .order_by(
                heads.c.updated_at.desc(),
                graphs.c.id.asc(),
            )
        )
        if workspace_id is not None:
            query = query.where(graphs.c.workspace_id == workspace_id)
        rows = (await self._session.execute(query)).mappings()
        items: list[GraphBrowserItem] = []
        for row in rows:
            document = cast(SavedGraphDocument, row["head_document"])
            folder_id = cast(UUID | None, row["folder_id"])
            creator_id = cast(UUID | None, row["creator_id"])
            items.append(
                GraphBrowserItem(
                    id=cast(UUID, row["id"]),
                    draft=GraphBrowserDraft(
                        name=cast(str, row["head_name"]),
                        head_sequence=cast(int, row["collaboration_sequence"]),
                        checkpoint_sequence=cast(int, row["checkpoint_sequence"]),
                        checkpoint_revision=cast(int, row["checkpoint_revision"]),
                        updated_at=cast(datetime, row["head_updated_at"]),
                        node_count=len(document.nodes),
                        edge_count=len(document.edges),
                    ),
                    location=GraphBrowserLocation(
                        id=cast(UUID, row["workspace_id"]),
                        slug=cast(str, row["workspace_slug"]),
                        name=cast(str, row["workspace_name"]),
                        kind=WorkspaceKind(cast(str, row["workspace_kind"])),
                    ),
                    folder=(
                        None
                        if folder_id is None
                        else GraphBrowserFolder(
                            id=folder_id,
                            name=cast(str, row["folder_name"]),
                        )
                    ),
                    archived_at=cast(datetime | None, row["archived_at"]),
                    starred=bool(row["starred"]),
                    last_opened_at=cast(
                        datetime | None,
                        row["last_opened_at"],
                    ),
                    organization_updated_at=cast(
                        datetime | None,
                        row["organization_updated_at"],
                    ),
                    creator=(
                        None
                        if creator_id is None
                        else GraphBrowserCreator(
                            id=creator_id,
                            display_name=cast(
                                str | None,
                                row["creator_display_name"],
                            ),
                        )
                    ),
                )
            )
        return items

    @override
    async def add_folder(self, folder: GraphFolder) -> None:
        self._session.add(folder)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise GraphFolderNameConflictError(
                workspace_id=folder.workspace_id,
                name=folder.name,
            ) from exc

    @override
    async def get_folder(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> GraphFolder | None:
        return await self._session.scalar(
            select(GraphFolder).where(
                schema.graph_folders.c.workspace_id == workspace_id,
                schema.graph_folders.c.id == folder_id,
            )
        )

    @override
    async def get_folder_by_name(
        self,
        workspace_id: UUID,
        name: str,
    ) -> GraphFolder | None:
        return await self._session.scalar(
            select(GraphFolder).where(
                schema.graph_folders.c.workspace_id == workspace_id,
                schema.graph_folders.c.name == name,
            )
        )

    @override
    async def list_folders(self, workspace_id: UUID) -> list[GraphFolder]:
        result = await self._session.scalars(
            select(GraphFolder)
            .where(schema.graph_folders.c.workspace_id == workspace_id)
            .order_by(
                schema.graph_folders.c.name.asc(),
                schema.graph_folders.c.id.asc(),
            )
        )
        return list(result)

    @override
    async def list(self, workspace_id: UUID) -> list[SavedGraph]:
        result = await self._session.scalars(
            select(SavedGraph)
            .order_by(
                schema.saved_graphs.c.updated_at.desc(),
                schema.saved_graphs.c.id.asc(),
            )
            .where(schema.saved_graphs.c.workspace_id == workspace_id)
        )
        return list(result)

    @override
    async def save_folder(self, folder: GraphFolder) -> None:
        self._session.add(folder)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise GraphFolderNameConflictError(
                workspace_id=folder.workspace_id,
                name=folder.name,
            ) from exc

    @override
    async def unfile_graphs_in_folder(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> None:
        await self._session.execute(
            update(schema.graph_organizations)
            .where(
                schema.graph_organizations.c.workspace_id == workspace_id,
                schema.graph_organizations.c.folder_id == folder_id,
            )
            .values(folder_id=None, updated_at=datetime.now(UTC))
        )

    @override
    async def remove_folder(self, folder: GraphFolder) -> None:
        await self._session.execute(
            delete(schema.graph_folders).where(
                schema.graph_folders.c.workspace_id == folder.workspace_id,
                schema.graph_folders.c.id == folder.id,
            )
        )

    @override
    async def get_organization(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> GraphOrganization | None:
        return await self._session.get(
            GraphOrganization,
            (workspace_id, graph_id),
        )

    @override
    async def save_organization(self, organization: GraphOrganization) -> None:
        self._session.add(organization)

    @override
    async def get_user_state(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        user_id: UUID,
    ) -> UserGraphState | None:
        return await self._session.get(
            UserGraphState,
            (workspace_id, graph_id, user_id),
        )

    @override
    async def save_user_state(self, state: UserGraphState) -> None:
        self._session.add(state)

    @override
    async def remove(self, workspace_id: UUID, graph: SavedGraph) -> None:
        await self._session.execute(
            delete(schema.saved_graphs).where(
                schema.saved_graphs.c.workspace_id == workspace_id,
                schema.saved_graphs.c.id == graph.id,
            )
        )


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
        graph_id: UUID,
        node_id: str,
        name: str,
    ) -> EncryptedNodeSecret | None:
        return await self._session.get(
            EncryptedNodeSecret,
            (workspace_id, graph_id, node_id, name),
        )

    @override
    async def list_for_graph(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> list[EncryptedNodeSecret]:
        result = await self._session.scalars(
            select(EncryptedNodeSecret)
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
        graph_id: UUID,
        node_id: str,
        name: str,
    ) -> None:
        await self._session.execute(
            delete(EncryptedNodeSecret).where(
                schema.node_secrets.c.workspace_id == workspace_id,
                schema.node_secrets.c.graph_id == graph_id,
                schema.node_secrets.c.node_id == node_id,
                schema.node_secrets.c.name == name,
            )
        )


class SqlCollaborationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_head(self, head: CollaborativeGraphHead) -> None:
        self._session.add(head)

    async def get_head(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> CollaborativeGraphHead | None:
        return await self._session.scalar(
            select(CollaborativeGraphHead).where(
                schema.collaborative_graph_heads.c.workspace_id == workspace_id,
                schema.collaborative_graph_heads.c.graph_id == graph_id,
            )
        )

    async def lock_head(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> CollaborativeGraphHead | None:
        table = schema.collaborative_graph_heads
        await self._session.execute(
            update(table)
            .where(
                table.c.workspace_id == workspace_id,
                table.c.graph_id == graph_id,
            )
            .values(updated_at=table.c.updated_at)
        )
        return await self.get_head(workspace_id, graph_id)

    async def save_head(self, head: CollaborativeGraphHead) -> None:
        self._session.add(head)

    async def remove_head(self, workspace_id: UUID, graph_id: UUID) -> None:
        await self._session.execute(
            delete(schema.collaborative_graph_heads).where(
                schema.collaborative_graph_heads.c.workspace_id == workspace_id,
                schema.collaborative_graph_heads.c.graph_id == graph_id,
            )
        )

    async def list_graphs_missing_heads(self) -> list[tuple[UUID, UUID]]:
        heads = schema.collaborative_graph_heads
        graphs = schema.saved_graphs
        rows = (
            await self._session.execute(
                select(graphs.c.workspace_id, graphs.c.id)
                .select_from(
                    graphs.outerjoin(
                        heads,
                        and_(
                            heads.c.workspace_id == graphs.c.workspace_id,
                            heads.c.graph_id == graphs.c.id,
                        ),
                    )
                )
                .where(heads.c.graph_id.is_(None))
                .order_by(graphs.c.workspace_id.asc(), graphs.c.id.asc())
            )
        ).all()
        return [(workspace_id, graph_id) for workspace_id, graph_id in rows]

    async def add_receipt(self, receipt: GraphCommandReceipt) -> None:
        await self._session.flush()
        await self._session.execute(
            insert(schema.graph_command_receipts).values(
                workspace_id=receipt.workspace_id,
                graph_id=receipt.graph_id,
                command_id=receipt.command_id,
                command_hmac=receipt.command_hmac,
                hmac_key_version=receipt.hmac_key_version,
                actor_kind=receipt.actor_kind.value,
                actor_user_id=receipt.actor_user_id,
                room_epoch=receipt.room_epoch,
                accepted_sequence=receipt.accepted_sequence,
                outcome=receipt.outcome.value,
                created_at=receipt.created_at,
            )
        )

    async def add_checkpoint_mapping(
        self,
        mapping: GraphCheckpointMapping,
    ) -> None:
        # Mapping FKs target heads and revisions that may still be pending ORM adds.
        await self._session.flush()
        await self._session.execute(
            insert(schema.graph_checkpoint_mappings).values(
                workspace_id=mapping.workspace_id,
                graph_id=mapping.graph_id,
                room_epoch=mapping.room_epoch,
                collaboration_sequence=mapping.collaboration_sequence,
                saved_revision=mapping.saved_revision,
                created_at=mapping.created_at,
            )
        )

    async def get_receipt(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        command_id: UUID,
    ) -> GraphCommandReceipt | None:
        row = (
            (
                await self._session.execute(
                    select(schema.graph_command_receipts).where(
                        schema.graph_command_receipts.c.workspace_id == workspace_id,
                        schema.graph_command_receipts.c.graph_id == graph_id,
                        schema.graph_command_receipts.c.command_id == command_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return GraphCommandReceipt.model_validate(dict(row))

    async def get_checkpoint_mapping(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        *,
        room_epoch: UUID,
        collaboration_sequence: int,
    ) -> GraphCheckpointMapping | None:
        row = (
            (
                await self._session.execute(
                    select(schema.graph_checkpoint_mappings).where(
                        schema.graph_checkpoint_mappings.c.workspace_id == workspace_id,
                        schema.graph_checkpoint_mappings.c.graph_id == graph_id,
                        schema.graph_checkpoint_mappings.c.room_epoch == room_epoch,
                        schema.graph_checkpoint_mappings.c.collaboration_sequence
                        == collaboration_sequence,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return GraphCheckpointMapping.model_validate(dict(row))
