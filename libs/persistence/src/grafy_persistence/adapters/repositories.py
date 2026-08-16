from collections.abc import Collection
from datetime import UTC, datetime
from typing import cast, override
from uuid import UUID

from sqlalchemy import and_, delete, exists, func, insert, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRepositoryPort,
    ArtifactTypeKey,
)
from grafy_core.domain.agent_authoring import (
    AgentEnvironment,
    AgentEnvironmentStatus,
    AgentEvent,
    AgentRun,
    AgentRunStatus,
    AgentThread,
    CapabilityApproval,
    DraftNode,
    NodeBuildAttempt,
    NodeRelease,
)
from grafy_core.domain.invocation_cache import InvocationCacheEntry
from grafy_core.domain.identity import (
    AuthSession,
    OidcBootstrapOwnerMapping,
    OidcIdentity,
    OidcLoginTransaction,
    PersonalAccessToken,
    User,
    Workspace,
    WorkspaceKind,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_core.domain.errors import (
    GraphFolderNameConflictError,
    NotFoundError,
    ObjectAlreadyExistsError,
)
from grafy_core.domain.execution_history import (
    GraphExecution,
    GraphExecutionCursor,
    GraphExecutionDetail,
    GraphExecutionListItem,
    GraphExecutionNodeResult,
    GraphExecutionPage,
    GraphExecutionStatus,
)
from grafy_core.domain.materialized_outputs import MaterializedNodeOutputs
from grafy_core.domain.module_library import (
    Module,
    ModulePublicationState,
    ModuleRelease,
)
from grafy_core.domain.node_secrets import EncryptedNodeSecret
from grafy_core.domain.collaboration import (
    CollaborativeGraphHead,
    GraphActiveExecutionSlot,
    GraphCheckpointMapping,
    GraphCommandJournalEntry,
    GraphCommandReceipt,
    GraphExecutionIdempotencyRecord,
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
from grafy_core.domain.security_audit import SecurityAuditEvent
from grafy_core.domain.staged_uploads import StagedUpload
from grafy_core.domain.templates import Template, TemplateState
from grafy_core.ports.identity import (
    IdentityRepositoryPort,
    SecurityAuditRepositoryPort,
)
from grafy_core.ports.agent_authoring import AgentAuthoringRepositoryPort
from grafy_core.ports.invocation_cache import InvocationCacheRepositoryPort
from grafy_core.ports.execution_history import (
    GraphExecutionHistoryRepositoryPort,
)
from grafy_core.ports.materialized_outputs import (
    MaterializedNodeOutputsRepositoryPort,
)
from grafy_core.ports.module_library import ModuleLibraryRepositoryPort
from grafy_core.ports.node_secrets import NodeSecretRepositoryPort
from grafy_core.ports.saved_graphs import SavedGraphRepositoryPort
from grafy_core.ports.staged_uploads import StagedUploadRepositoryPort
from grafy_core.ports.templates import TemplateRepositoryPort

from grafy_persistence import schema
from grafy_persistence.orm import GraphExecutionRecord, SavedGraphRevisionRecord


class SqlIdentityRepository(IdentityRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add_user(self, user: User) -> None:
        self._session.add(user)

    @override
    async def get_user(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    @override
    async def get_oidc_identity(
        self,
        *,
        issuer: str,
        subject: str,
    ) -> OidcIdentity | None:
        return await self._session.scalar(
            select(OidcIdentity).where(
                schema.oidc_identities.c.issuer == issuer,
                schema.oidc_identities.c.subject == subject,
            )
        )

    @override
    async def add_oidc_identity(self, identity: OidcIdentity) -> None:
        await self._session.flush()
        self._session.add(identity)

    @override
    async def add_workspace(self, workspace: Workspace) -> None:
        await self._session.flush()
        self._session.add(workspace)

    @override
    async def get_workspace(self, workspace_id: UUID) -> Workspace | None:
        return await self._session.get(Workspace, workspace_id)

    @override
    async def get_workspace_by_slug(self, slug: str) -> Workspace | None:
        return await self._session.scalar(
            select(Workspace).where(schema.workspaces.c.slug == slug)
        )

    @override
    async def lock_workspace_for_membership_mutation(
        self,
        workspace_id: UUID,
    ) -> Workspace | None:
        statement = select(Workspace).where(
            schema.workspaces.c.id == workspace_id,
        )
        if self._session.get_bind().dialect.name == "sqlite":
            await self._session.execute(text("BEGIN IMMEDIATE"))
        else:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    @override
    async def lock_workspace_by_slug_for_membership_mutation(
        self,
        slug: str,
    ) -> Workspace | None:
        statement = select(Workspace).where(schema.workspaces.c.slug == slug)
        if self._session.get_bind().dialect.name == "sqlite":
            await self._session.execute(text("BEGIN IMMEDIATE"))
        else:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    @override
    async def get_personal_workspace(self, user_id: UUID) -> Workspace | None:
        return await self._session.scalar(
            select(Workspace).where(
                schema.workspaces.c.kind == WorkspaceKind.PERSONAL.value,
                schema.workspaces.c.personal_owner_user_id == user_id,
            )
        )

    @override
    async def list_workspaces_for_user(self, user_id: UUID) -> list[Workspace]:
        result = await self._session.scalars(
            select(Workspace)
            .join(
                schema.workspace_memberships,
                schema.workspace_memberships.c.workspace_id == schema.workspaces.c.id,
            )
            .where(
                schema.workspace_memberships.c.user_id == user_id,
                schema.workspace_memberships.c.revoked_at.is_(None),
            )
            .order_by(schema.workspaces.c.slug.asc())
        )
        return list(result)

    @override
    async def list_memberships_for_user(
        self,
        user_id: UUID,
    ) -> list[WorkspaceMembership]:
        result = await self._session.scalars(
            select(WorkspaceMembership)
            .where(schema.workspace_memberships.c.user_id == user_id)
            .order_by(schema.workspace_memberships.c.workspace_id.asc())
        )
        return list(result)

    @override
    async def add_membership(self, membership: WorkspaceMembership) -> None:
        await self._session.flush()
        self._session.add(membership)

    @override
    async def get_membership(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
    ) -> WorkspaceMembership | None:
        return await self._session.get(WorkspaceMembership, (workspace_id, user_id))

    @override
    async def list_memberships(self, workspace_id: UUID) -> list[WorkspaceMembership]:
        result = await self._session.scalars(
            select(WorkspaceMembership)
            .where(schema.workspace_memberships.c.workspace_id == workspace_id)
            .order_by(schema.workspace_memberships.c.user_id.asc())
        )
        return list(result)

    @override
    async def count_active_owners(self, workspace_id: UUID) -> int:
        count = await self._session.scalar(
            select(func.count())
            .select_from(schema.workspace_memberships)
            .where(
                schema.workspace_memberships.c.workspace_id == workspace_id,
                schema.workspace_memberships.c.role == "owner",
                schema.workspace_memberships.c.revoked_at.is_(None),
            )
        )
        return int(count or 0)

    @override
    async def get_unconsumed_bootstrap_mapping(
        self,
        workspace_id: UUID,
    ) -> OidcBootstrapOwnerMapping | None:
        return await self._session.scalar(
            select(OidcBootstrapOwnerMapping).where(
                schema.oidc_bootstrap_owner_mappings.c.workspace_id == workspace_id,
                schema.oidc_bootstrap_owner_mappings.c.consumed_at.is_(None),
            )
        )

    @override
    async def add_bootstrap_mapping(
        self,
        mapping: OidcBootstrapOwnerMapping,
    ) -> None:
        self._session.add(mapping)

    @override
    async def add_login_transaction(self, transaction: OidcLoginTransaction) -> None:
        self._session.add(transaction)

    @override
    async def get_login_transaction(
        self,
        transaction_id: UUID,
    ) -> OidcLoginTransaction | None:
        return await self._session.get(OidcLoginTransaction, transaction_id)

    @override
    async def lock_login_transaction(
        self,
        transaction_id: UUID,
    ) -> OidcLoginTransaction | None:
        statement = select(OidcLoginTransaction).where(
            schema.oidc_login_transactions.c.id == transaction_id,
        )
        if self._session.get_bind().dialect.name == "sqlite":
            await self._session.execute(text("BEGIN IMMEDIATE"))
        else:
            statement = statement.with_for_update()
        return await self._session.scalar(statement)

    @override
    async def add_auth_session(self, session: AuthSession) -> None:
        self._session.add(session)

    @override
    async def get_auth_session(self, session_id: UUID) -> AuthSession | None:
        return await self._session.get(AuthSession, session_id)

    @override
    async def list_auth_sessions_for_user(self, user_id: UUID) -> list[AuthSession]:
        result = await self._session.scalars(
            select(AuthSession).where(schema.auth_sessions.c.user_id == user_id)
        )
        return list(result)

    @override
    async def get_auth_session_for_user(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
    ) -> AuthSession | None:
        return await self._session.scalar(
            select(AuthSession).where(
                schema.auth_sessions.c.id == session_id,
                schema.auth_sessions.c.user_id == user_id,
            )
        )

    @override
    async def delete_expired_login_transactions(self, expired_before: datetime) -> int:
        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(
                delete(schema.oidc_login_transactions).where(
                    or_(
                        schema.oidc_login_transactions.c.expires_at < expired_before,
                        schema.oidc_login_transactions.c.consumed_at.is_not(None),
                    )
                )
            ),
        )
        return result.rowcount

    @override
    async def add_personal_access_token(self, token: PersonalAccessToken) -> None:
        self._session.add(token)

    @override
    async def get_personal_access_token_by_digest(
        self,
        secret_digest: bytes,
    ) -> PersonalAccessToken | None:
        return await self._session.scalar(
            select(PersonalAccessToken).where(
                schema.personal_access_tokens.c.secret_digest == secret_digest
            )
        )

    @override
    async def list_personal_access_tokens_for_user(
        self,
        user_id: UUID,
    ) -> list[PersonalAccessToken]:
        result = await self._session.scalars(
            select(PersonalAccessToken).where(
                schema.personal_access_tokens.c.user_id == user_id
            )
        )
        return list(result)

    @override
    async def list_personal_access_tokens_for_user_workspace(
        self,
        *,
        user_id: UUID,
        workspace_id: UUID,
    ) -> list[PersonalAccessToken]:
        result = await self._session.scalars(
            select(PersonalAccessToken)
            .where(
                schema.personal_access_tokens.c.user_id == user_id,
                schema.personal_access_tokens.c.workspace_id == workspace_id,
            )
            .order_by(schema.personal_access_tokens.c.created_at.desc())
        )
        return list(result)

    @override
    async def get_personal_access_token_for_user_workspace(
        self,
        *,
        token_id: UUID,
        user_id: UUID,
        workspace_id: UUID,
    ) -> PersonalAccessToken | None:
        return await self._session.scalar(
            select(PersonalAccessToken).where(
                schema.personal_access_tokens.c.id == token_id,
                schema.personal_access_tokens.c.user_id == user_id,
                schema.personal_access_tokens.c.workspace_id == workspace_id,
            )
        )

    @override
    async def delete_expired_sessions(self, expired_before: datetime) -> int:
        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(
                delete(schema.auth_sessions).where(
                    schema.auth_sessions.c.expires_at < expired_before
                )
            ),
        )
        return result.rowcount

    @override
    async def delete_expired_personal_access_tokens(
        self,
        expired_before: datetime,
    ) -> int:
        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(
                delete(schema.personal_access_tokens).where(
                    schema.personal_access_tokens.c.expires_at < expired_before
                )
            ),
        )
        return result.rowcount


class SqlSecurityAuditRepository(SecurityAuditRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, event: SecurityAuditEvent) -> None:
        self._session.add(event)

    @override
    async def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        limit: int,
    ) -> list[SecurityAuditEvent]:
        if limit < 1:
            raise ValueError("Security audit event limit must be positive")
        result = await self._session.scalars(
            select(SecurityAuditEvent)
            .where(schema.security_audit_events.c.workspace_id == workspace_id)
            .order_by(schema.security_audit_events.c.occurred_at.desc())
            .limit(limit)
        )
        return list(result)

    @override
    async def delete_before(self, occurred_before: datetime) -> int:
        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(
                delete(schema.security_audit_events).where(
                    schema.security_audit_events.c.occurred_at < occurred_before
                )
            ),
        )
        return result.rowcount


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
    async def list_accessible(self, user_id: UUID) -> list[GraphBrowserItem]:
        graphs = schema.saved_graphs
        memberships = schema.workspace_memberships
        workspaces = schema.workspaces
        folders = schema.graph_folders
        organizations = schema.graph_organizations
        states = schema.user_graph_states
        heads = schema.collaborative_graph_heads
        active_user = schema.users.alias("active_graph_browser_user")
        creator = schema.users.alias("graph_creator")
        rows = (
            await self._session.execute(
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
        ).mappings()
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


class SqlArtifactRepository(ArtifactRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, artifact: ArtifactObject) -> None:
        self._session.add(artifact)

    @override
    async def get(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactObject | None:
        return await self._session.scalar(
            select(ArtifactObject).where(
                schema.artifact_objects.c.workspace_id == workspace_id,
                schema.artifact_objects.c.id == artifact_id,
            )
        )

    @override
    async def get_many(
        self,
        workspace_id: UUID,
        artifact_ids: Collection[UUID],
    ) -> dict[UUID, ArtifactObject]:
        if not artifact_ids:
            return {}
        result = await self._session.scalars(
            select(ArtifactObject).where(
                schema.artifact_objects.c.id.in_(set(artifact_ids)),
                schema.artifact_objects.c.workspace_id == workspace_id,
            )
        )
        return {artifact.id: artifact for artifact in result}

    @override
    async def remove(self, workspace_id: UUID, artifact: ArtifactObject) -> None:
        await self._session.execute(
            delete(schema.artifact_objects).where(
                schema.artifact_objects.c.workspace_id == workspace_id,
                schema.artifact_objects.c.id == artifact.id,
            )
        )

    @override
    async def list_by_type(
        self,
        workspace_id: UUID,
        key: ArtifactTypeKey,
    ) -> list[ArtifactObject]:
        result = await self._session.scalars(
            select(ArtifactObject)
            .where(
                schema.artifact_objects.c.artifact_type == key.id,
                schema.artifact_objects.c.schema_version == key.schema_version,
                schema.artifact_objects.c.workspace_id == workspace_id,
            )
            .order_by(schema.artifact_objects.c.id.asc())
        )
        return list(result)


class SqlInvocationCacheRepository(InvocationCacheRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def get(
        self,
        workspace_id: UUID,
        key_sha256: str,
    ) -> InvocationCacheEntry | None:
        return await self._session.get(
            InvocationCacheEntry,
            (workspace_id, key_sha256),
        )

    @override
    async def put_if_absent(self, entry: InvocationCacheEntry) -> bool:
        table = schema.invocation_cache_entries
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name == "sqlite":
            insert_statement = sqlite_insert(table)
        elif dialect_name == "postgresql":
            insert_statement = postgresql_insert(table)
        else:
            raise NotImplementedError(
                "Invocation cache publication requires SQLite or PostgreSQL; "
                f"received dialect {dialect_name!r}"
            )

        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(
                insert_statement.values(
                    key_sha256=entry.key_sha256,
                    workspace_id=entry.workspace_id,
                    generation=entry.generation,
                    outputs=entry.outputs,
                    created_at=entry.created_at,
                ).on_conflict_do_nothing(
                    index_elements=(table.c.workspace_id, table.c.key_sha256),
                )
            ),
        )
        return result.rowcount == 1

    @override
    async def remove_if_current(
        self,
        workspace_id: UUID,
        key_sha256: str,
        generation: UUID,
    ) -> bool:
        table = schema.invocation_cache_entries
        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(
                delete(table).where(
                    table.c.workspace_id == workspace_id,
                    table.c.key_sha256 == key_sha256,
                    table.c.generation == generation,
                )
            ),
        )
        return result.rowcount == 1


class SqlMaterializedNodeOutputsRepository(
    MaterializedNodeOutputsRepositoryPort,
):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def upsert(self, value: MaterializedNodeOutputs) -> None:
        table = schema.materialized_node_outputs
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name == "sqlite":
            insert_statement = sqlite_insert(table)
        elif dialect_name == "postgresql":
            insert_statement = postgresql_insert(table)
        else:
            raise NotImplementedError(
                "Materialized output upsert requires SQLite or PostgreSQL; "
                f"received dialect {dialect_name!r}"
            )

        insert_statement = insert_statement.values(
            workspace_id=value.workspace_id,
            graph_id=value.graph_id,
            graph_revision=value.graph_revision,
            node_id=value.node_id,
            workflow_run_id=value.workflow_run_id,
            outputs=value.outputs,
            materialized_at=value.materialized_at,
        )
        await self._session.execute(
            insert_statement.on_conflict_do_update(
                index_elements=(
                    table.c.workspace_id,
                    table.c.graph_id,
                    table.c.graph_revision,
                    table.c.node_id,
                ),
                set_={
                    "workflow_run_id": insert_statement.excluded.workflow_run_id,
                    "outputs": insert_statement.excluded.outputs,
                    "materialized_at": insert_statement.excluded.materialized_at,
                },
            )
        )

    @override
    async def get(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
        node_id: str,
    ) -> MaterializedNodeOutputs | None:
        return await self._session.get(
            MaterializedNodeOutputs,
            (workspace_id, graph_id, graph_revision, node_id),
        )

    @override
    async def list_for_graph(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        graph_revision: int,
    ) -> list[MaterializedNodeOutputs]:
        result = await self._session.scalars(
            select(MaterializedNodeOutputs)
            .where(
                schema.materialized_node_outputs.c.graph_id == graph_id,
                schema.materialized_node_outputs.c.graph_revision == graph_revision,
                schema.materialized_node_outputs.c.workspace_id == workspace_id,
            )
            .order_by(schema.materialized_node_outputs.c.node_id.asc())
        )
        return list(result)


class SqlGraphExecutionHistoryRepository(
    GraphExecutionHistoryRepositoryPort,
):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, execution: GraphExecution) -> None:
        table = schema.graph_executions
        revision_exists = await self._session.scalar(
            select(schema.saved_graph_revisions.c.graph_id).where(
                schema.saved_graph_revisions.c.workspace_id == execution.workspace_id,
                schema.saved_graph_revisions.c.graph_id == execution.graph_id,
                schema.saved_graph_revisions.c.revision == execution.graph_revision,
            )
        )
        if revision_exists is None:
            raise NotFoundError(
                "Saved graph revision",
                f"{execution.graph_id}/r{execution.graph_revision}",
            )
        try:
            await self._session.execute(
                insert(table).values(
                    execution_id=execution.execution_id,
                    workspace_id=execution.workspace_id,
                    graph_id=execution.graph_id,
                    graph_revision=execution.graph_revision,
                    status=execution.status,
                    scope=execution.scope,
                    workflow_run_id=execution.workflow_run_id,
                    error=execution.error,
                    created_at=execution.created_at,
                    started_at=execution.started_at,
                    finished_at=execution.finished_at,
                )
            )
        except IntegrityError as exc:
            raise ObjectAlreadyExistsError(
                f"Graph execution already exists: {execution.execution_id}"
            ) from exc
        if execution.requested_node_ids:
            await self._session.execute(
                insert(schema.graph_execution_requested_nodes),
                [
                    {
                        "workspace_id": execution.workspace_id,
                        "execution_id": execution.execution_id,
                        "node_id": node_id,
                        "position": position,
                    }
                    for position, node_id in enumerate(execution.requested_node_ids)
                ],
            )

    @override
    async def update(self, execution: GraphExecution) -> None:
        current_record = await self._session.scalar(
            select(GraphExecutionRecord).where(
                schema.graph_executions.c.workspace_id == execution.workspace_id,
                schema.graph_executions.c.execution_id == execution.execution_id,
            )
        )
        if current_record is None:
            raise NotFoundError("Graph execution", str(execution.execution_id))
        requested_node_ids = await self._requested_node_ids(
            execution.workspace_id,
            execution.execution_id,
        )
        current = current_record.to_domain(requested_node_ids)
        if (
            current.graph_id != execution.graph_id
            or current.graph_revision != execution.graph_revision
            or current.scope != execution.scope
            or current.requested_node_ids != execution.requested_node_ids
            or current.created_at != execution.created_at
        ):
            raise ValueError(
                f"Graph execution {execution.execution_id} identity and request "
                "fields are immutable"
            )

        await self._session.execute(
            update(schema.graph_executions)
            .where(
                schema.graph_executions.c.workspace_id == execution.workspace_id,
                schema.graph_executions.c.execution_id == execution.execution_id,
            )
            .values(
                status=execution.status,
                workflow_run_id=execution.workflow_run_id,
                error=execution.error,
                started_at=execution.started_at,
                finished_at=execution.finished_at,
            )
        )

    @override
    async def add_node_result(self, result: GraphExecutionNodeResult) -> None:
        execution_exists = await self._session.scalar(
            select(schema.graph_executions.c.execution_id).where(
                schema.graph_executions.c.workspace_id == result.workspace_id,
                schema.graph_executions.c.execution_id == result.execution_id,
            )
        )
        if execution_exists is None:
            raise NotFoundError("Graph execution", str(result.execution_id))
        requested_node_exists = await self._session.scalar(
            select(schema.graph_execution_requested_nodes.c.execution_id).where(
                schema.graph_execution_requested_nodes.c.workspace_id
                == result.workspace_id,
                schema.graph_execution_requested_nodes.c.execution_id
                == result.execution_id,
                schema.graph_execution_requested_nodes.c.node_id == result.node_id,
            )
        )
        if requested_node_exists is None:
            raise ValueError(
                f"Graph execution {result.execution_id} did not request node "
                f"{result.node_id!r}"
            )

        table = schema.graph_execution_node_results
        try:
            await self._session.execute(
                insert(table).values(
                    workspace_id=result.workspace_id,
                    execution_id=result.execution_id,
                    node_id=result.node_id,
                    position=result.position,
                    status=result.status,
                    outputs=result.outputs,
                    artifact_count=result.artifact_count,
                    error=result.error,
                    completed_at=result.completed_at,
                )
            )
        except IntegrityError as exc:
            raise ObjectAlreadyExistsError(
                "Graph execution node result already exists: "
                f"{result.execution_id}/{result.node_id}"
            ) from exc

    @override
    async def get(
        self,
        workspace_id: UUID,
        execution_id: UUID,
    ) -> GraphExecutionDetail | None:
        record = await self._session.scalar(
            select(GraphExecutionRecord).where(
                schema.graph_executions.c.workspace_id == workspace_id,
                schema.graph_executions.c.execution_id == execution_id,
            )
        )
        if record is None:
            return None
        execution = record.to_domain(
            await self._requested_node_ids(workspace_id, execution_id)
        )
        results = await self._session.scalars(
            select(GraphExecutionNodeResult)
            .where(schema.graph_execution_node_results.c.execution_id == execution_id)
            .where(schema.graph_execution_node_results.c.workspace_id == workspace_id)
            .order_by(
                schema.graph_execution_node_results.c.position.asc(),
                schema.graph_execution_node_results.c.node_id.asc(),
            )
        )
        return GraphExecutionDetail(
            execution=execution,
            node_results=tuple(results),
        )

    @override
    async def list_for_graph(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        *,
        limit: int,
        cursor: GraphExecutionCursor | None = None,
        graph_revision: int | None = None,
        status: GraphExecutionStatus | None = None,
        node_id: str | None = None,
    ) -> GraphExecutionPage:
        if limit < 1:
            raise ValueError("Graph execution page limit must be at least 1")
        if graph_revision is not None and graph_revision < 1:
            raise ValueError("Graph execution revision filter must be at least 1")
        normalized_node_id = None
        if node_id is not None:
            normalized_node_id = node_id.strip()
            if normalized_node_id == "":
                raise ValueError("Graph execution node filter must not be blank")

        executions = schema.graph_executions
        requested_nodes = schema.graph_execution_requested_nodes
        node_results = schema.graph_execution_node_results
        counts = (
            select(
                node_results.c.workspace_id,
                node_results.c.execution_id,
                func.count(node_results.c.node_id).label("node_count"),
                func.coalesce(func.sum(node_results.c.artifact_count), 0).label(
                    "artifact_count"
                ),
            )
            .group_by(
                node_results.c.workspace_id,
                node_results.c.execution_id,
            )
            .subquery()
        )
        statement = (
            select(
                GraphExecutionRecord,
                func.coalesce(counts.c.node_count, 0),
                func.coalesce(counts.c.artifact_count, 0),
            )
            .outerjoin(
                counts,
                and_(
                    counts.c.workspace_id == executions.c.workspace_id,
                    counts.c.execution_id == executions.c.execution_id,
                ),
            )
            .where(
                executions.c.workspace_id == workspace_id,
                executions.c.graph_id == graph_id,
            )
        )
        if graph_revision is not None:
            statement = statement.where(executions.c.graph_revision == graph_revision)
        if status is not None:
            statement = statement.where(executions.c.status == status)
        if normalized_node_id is not None:
            statement = statement.where(
                select(1)
                .where(
                    requested_nodes.c.execution_id == executions.c.execution_id,
                    requested_nodes.c.workspace_id == workspace_id,
                    requested_nodes.c.node_id == normalized_node_id,
                )
                .exists()
            )
        if cursor is not None:
            statement = statement.where(
                or_(
                    executions.c.created_at < cursor.created_at,
                    (
                        (executions.c.created_at == cursor.created_at)
                        & (executions.c.execution_id < cursor.execution_id)
                    ),
                )
            )
        statement = statement.order_by(
            executions.c.created_at.desc(),
            executions.c.execution_id.desc(),
        ).limit(limit + 1)
        rows = list((await self._session.execute(statement)).all())
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        requested_by_execution: dict[UUID, list[tuple[int, str]]] = {}
        execution_ids = [row[0].execution_id for row in page_rows]
        if execution_ids:
            requested_rows = (
                await self._session.execute(
                    select(
                        requested_nodes.c.execution_id,
                        requested_nodes.c.position,
                        requested_nodes.c.node_id,
                    )
                    .where(requested_nodes.c.execution_id.in_(execution_ids))
                    .where(requested_nodes.c.workspace_id == workspace_id)
                    .order_by(
                        requested_nodes.c.execution_id.asc(),
                        requested_nodes.c.position.asc(),
                    )
                )
            ).all()
            for requested_execution_id, position, requested_node_id in requested_rows:
                requested_by_execution.setdefault(requested_execution_id, []).append(
                    (position, requested_node_id)
                )
        items = tuple(
            GraphExecutionListItem(
                execution=row[0].to_domain(
                    tuple(
                        node_id
                        for _, node_id in requested_by_execution.get(
                            row[0].execution_id,
                            [],
                        )
                    )
                ),
                node_count=int(row[1]),
                artifact_count=int(row[2]),
            )
            for row in page_rows
        )
        next_cursor = None
        if has_more and items:
            last = items[-1].execution
            next_cursor = GraphExecutionCursor(
                created_at=last.created_at,
                execution_id=last.execution_id,
            )
        return GraphExecutionPage(items=items, next_cursor=next_cursor)

    @override
    async def interrupt_all_active(
        self,
        *,
        finished_at: datetime,
        error: str,
    ) -> int:
        if finished_at.tzinfo is None:
            raise ValueError(
                "Graph execution interruption timestamp must be timezone-aware"
            )
        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(
                update(schema.graph_executions)
                .where(
                    schema.graph_executions.c.status.in_(
                        ("queued", "running", "cancelling")
                    )
                )
                .values(
                    status="failed",
                    finished_at=finished_at,
                    error=error,
                )
            ),
        )
        return result.rowcount

    async def _requested_node_ids(
        self,
        workspace_id: UUID,
        execution_id: UUID,
    ) -> tuple[str, ...]:
        requested_nodes = schema.graph_execution_requested_nodes
        result = await self._session.scalars(
            select(requested_nodes.c.node_id)
            .where(
                requested_nodes.c.workspace_id == workspace_id,
                requested_nodes.c.execution_id == execution_id,
            )
            .order_by(requested_nodes.c.position.asc())
        )
        return tuple(result)


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


class SqlStagedUploadRepository(StagedUploadRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, upload: StagedUpload) -> None:
        self._session.add(upload)

    @override
    async def get(
        self,
        workspace_id: UUID,
        upload_key: str,
    ) -> StagedUpload | None:
        return await self._session.get(StagedUpload, (workspace_id, upload_key))

    @override
    async def list_for_workspace(self, workspace_id: UUID) -> list[StagedUpload]:
        result = await self._session.scalars(
            select(StagedUpload)
            .where(schema.staged_uploads.c.workspace_id == workspace_id)
            .order_by(
                schema.staged_uploads.c.created_at.asc(),
                schema.staged_uploads.c.upload_key.asc(),
            )
        )
        return list(result)

    @override
    async def remove(self, workspace_id: UUID, upload_key: str) -> None:
        await self._session.execute(
            delete(schema.staged_uploads).where(
                schema.staged_uploads.c.workspace_id == workspace_id,
                schema.staged_uploads.c.upload_key == upload_key,
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

    async def add_journal_entry(self, entry: GraphCommandJournalEntry) -> None:
        # Core inserts must see pending ORM parents (heads) in the same unit.
        await self._session.flush()
        await self._session.execute(
            insert(schema.graph_command_journal).values(
                workspace_id=entry.workspace_id,
                graph_id=entry.graph_id,
                accepted_sequence=entry.accepted_sequence,
                room_epoch=entry.room_epoch,
                command_id=entry.command_id,
                command_hmac=entry.command_hmac,
                hmac_key_version=entry.hmac_key_version,
                actor_kind=entry.actor_kind.value,
                actor_user_id=entry.actor_user_id,
                graph_room_session_id=entry.graph_room_session_id,
                authorization_version=entry.authorization_version,
                command_kind=entry.command_kind.value,
                command_payload=entry.command_payload,
                accepted_at=entry.accepted_at,
            )
        )

    async def clear_journal(self, workspace_id: UUID, graph_id: UUID) -> None:
        await self._session.execute(
            delete(schema.graph_command_journal).where(
                schema.graph_command_journal.c.workspace_id == workspace_id,
                schema.graph_command_journal.c.graph_id == graph_id,
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

    async def get_execution_idempotency(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        client_request_id: UUID,
    ) -> GraphExecutionIdempotencyRecord | None:
        row = (
            (
                await self._session.execute(
                    select(schema.graph_execution_idempotency).where(
                        schema.graph_execution_idempotency.c.workspace_id
                        == workspace_id,
                        schema.graph_execution_idempotency.c.graph_id == graph_id,
                        schema.graph_execution_idempotency.c.client_request_id
                        == client_request_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return GraphExecutionIdempotencyRecord.model_validate(dict(row))

    async def add_execution_idempotency(
        self,
        record: GraphExecutionIdempotencyRecord,
    ) -> None:
        await self._session.execute(
            insert(schema.graph_execution_idempotency).values(
                workspace_id=record.workspace_id,
                graph_id=record.graph_id,
                client_request_id=record.client_request_id,
                request_hmac=record.request_hmac,
                hmac_key_version=record.hmac_key_version,
                actor_user_id=record.actor_user_id,
                room_epoch=record.room_epoch,
                head_sequence=record.head_sequence,
                execution_id=record.execution_id,
                created_at=record.created_at,
            )
        )

    async def get_active_execution_slot(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> GraphActiveExecutionSlot | None:
        row = (
            (
                await self._session.execute(
                    select(schema.graph_active_execution_slots).where(
                        schema.graph_active_execution_slots.c.workspace_id
                        == workspace_id,
                        schema.graph_active_execution_slots.c.graph_id == graph_id,
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return GraphActiveExecutionSlot.model_validate(dict(row))

    async def acquire_active_execution_slot(
        self,
        slot: GraphActiveExecutionSlot,
    ) -> bool:
        values = {
            "workspace_id": slot.workspace_id,
            "graph_id": slot.graph_id,
            "execution_id": slot.execution_id,
            "updated_at": slot.updated_at,
        }
        dialect = (
            self._session.bind.dialect.name if self._session.bind is not None else ""
        )
        if dialect == "postgresql":
            statement = (
                postgresql_insert(schema.graph_active_execution_slots)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["workspace_id", "graph_id"])
            )
        elif dialect == "sqlite":
            statement = (
                sqlite_insert(schema.graph_active_execution_slots)
                .values(**values)
                .on_conflict_do_nothing(index_elements=["workspace_id", "graph_id"])
            )
        else:
            existing = await self.get_active_execution_slot(
                slot.workspace_id,
                slot.graph_id,
            )
            if existing is not None:
                return False
            statement = insert(schema.graph_active_execution_slots).values(**values)
        result = await self._session.execute(statement)
        return bool(result.rowcount)

    async def clear_active_execution_slot(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        *,
        execution_id: UUID | None = None,
    ) -> None:
        clause = [
            schema.graph_active_execution_slots.c.workspace_id == workspace_id,
            schema.graph_active_execution_slots.c.graph_id == graph_id,
        ]
        if execution_id is not None:
            clause.append(
                schema.graph_active_execution_slots.c.execution_id == execution_id
            )
        await self._session.execute(
            delete(schema.graph_active_execution_slots).where(*clause)
        )

    async def clear_all_active_execution_slots(self) -> int:
        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(delete(schema.graph_active_execution_slots)),
        )
        return int(result.rowcount or 0)


class SqlModuleLibraryRepository(ModuleLibraryRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, module: Module) -> None:
        self._session.add(module)
        await self._session.flush()

    @override
    async def add_release(self, release: ModuleRelease) -> None:
        self._session.add(release)
        await self._session.flush()

    @override
    async def get(self, workspace_id: UUID, module_id: UUID) -> Module | None:
        return await self._session.scalar(
            select(Module).where(
                schema.modules.c.workspace_id == workspace_id,
                schema.modules.c.id == module_id,
            )
        )

    @override
    async def get_by_source_graph(
        self,
        workspace_id: UUID,
        source_graph_id: UUID,
    ) -> Module | None:
        return await self._session.scalar(
            select(Module).where(
                schema.modules.c.workspace_id == workspace_id,
                schema.modules.c.source_graph_id == source_graph_id,
            )
        )

    @override
    async def get_release(
        self,
        workspace_id: UUID,
        module_id: UUID,
        revision: int,
    ) -> ModuleRelease | None:
        return await self._session.get(
            ModuleRelease,
            (workspace_id, module_id, revision),
        )

    @override
    async def list_modules(self, workspace_id: UUID) -> list[Module]:
        result = await self._session.scalars(
            select(Module)
            .where(schema.modules.c.workspace_id == workspace_id)
            .order_by(
                schema.modules.c.updated_at.desc(),
                schema.modules.c.id.asc(),
            )
        )
        return list(result)

    @override
    async def list_library(self, workspace_id: UUID) -> list[Module]:
        result = await self._session.scalars(
            select(Module)
            .where(
                schema.modules.c.workspace_id == workspace_id,
                schema.modules.c.publication_state.in_(
                    (
                        ModulePublicationState.PUBLISHED,
                        ModulePublicationState.DEPRECATED,
                    )
                ),
            )
            .order_by(
                schema.modules.c.name.asc(),
                schema.modules.c.id.asc(),
            )
        )
        return list(result)

    @override
    async def list_releases(
        self,
        workspace_id: UUID,
        module_id: UUID,
    ) -> list[ModuleRelease]:
        result = await self._session.scalars(
            select(ModuleRelease)
            .where(
                schema.module_releases.c.workspace_id == workspace_id,
                schema.module_releases.c.module_id == module_id,
            )
            .order_by(schema.module_releases.c.revision.desc())
        )
        return list(result)


class SqlTemplateRepository(TemplateRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, template: Template) -> None:
        self._session.add(template)
        await self._session.flush()

    @override
    async def get(
        self,
        workspace_id: UUID,
        template_id: UUID,
    ) -> Template | None:
        return await self._session.scalar(
            select(Template).where(
                schema.templates.c.workspace_id == workspace_id,
                schema.templates.c.id == template_id,
            )
        )

    @override
    async def list(
        self,
        workspace_id: UUID,
        *,
        query: str | None,
        include_archived: bool,
    ) -> list[Template]:
        statement = select(Template).where(
            schema.templates.c.workspace_id == workspace_id
        )
        if not include_archived:
            statement = statement.where(
                schema.templates.c.state == TemplateState.ACTIVE
            )
        if query is not None:
            pattern = f"%{query.lower()}%"
            statement = statement.where(
                or_(
                    func.lower(schema.templates.c.name).like(pattern),
                    func.lower(schema.templates.c.description).like(pattern),
                    func.lower(schema.templates.c.source_graph_name).like(pattern),
                )
            )
        result = await self._session.scalars(
            statement.order_by(
                schema.templates.c.name.asc(),
                schema.templates.c.id.asc(),
            )
        )
        return list(result)


class SqlAgentAuthoringRepository(AgentAuthoringRepositoryPort):
    """SQL adapter for durable authoring state and database-leased work.

    Provisioning, run-claim, and expired-run fencing hold candidate rows until
    the enclosing transaction commits. Claims and fencing always lock the run
    before its environment, with ``SKIP LOCKED`` on both rows. SQLite
    intentionally supports only the single-worker development runtime.
    Provider termination happens after commit and is idempotently retried from
    the interrupting/cancelling discovery queries.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add_environment(self, environment: AgentEnvironment) -> None:
        self._session.add(environment)
        await self._session.flush()

    @override
    async def get_environment(
        self,
        workspace_id: UUID,
        environment_id: UUID,
    ) -> AgentEnvironment | None:
        return await self._session.scalar(
            select(AgentEnvironment).where(
                schema.agent_environments.c.workspace_id == workspace_id,
                schema.agent_environments.c.id == environment_id,
            )
        )

    @override
    async def lock_environment(
        self,
        workspace_id: UUID,
        environment_id: UUID,
    ) -> AgentEnvironment | None:
        return await self._session.scalar(
            select(AgentEnvironment)
            .where(
                schema.agent_environments.c.workspace_id == workspace_id,
                schema.agent_environments.c.id == environment_id,
            )
            .with_for_update()
        )

    @override
    async def save_environment(self, environment: AgentEnvironment) -> None:
        del environment
        await self._session.flush()

    @override
    async def list_environments(
        self,
        workspace_id: UUID,
    ) -> list[AgentEnvironment]:
        result = await self._session.scalars(
            select(AgentEnvironment)
            .where(schema.agent_environments.c.workspace_id == workspace_id)
            .order_by(
                schema.agent_environments.c.updated_at.desc(),
                schema.agent_environments.c.id.asc(),
            )
        )
        return list(result)

    @override
    async def list_provisionable_environment_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        statement = (
            select(
                schema.agent_environments.c.workspace_id,
                schema.agent_environments.c.id,
            )
            .where(
                or_(
                    schema.agent_environments.c.status
                    == AgentEnvironmentStatus.PROVISIONING,
                    and_(
                        schema.agent_environments.c.status
                        == AgentEnvironmentStatus.CREATING,
                        schema.agent_environments.c.provisioning_expires_at <= when,
                    ),
                )
            )
            .order_by(
                schema.agent_environments.c.created_at.asc(),
                schema.agent_environments.c.id.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(statement)
        return [(row.workspace_id, row.id) for row in result]

    @override
    async def lock_provisionable_environment(
        self,
        workspace_id: UUID,
        environment_id: UUID,
        *,
        when: datetime,
    ) -> AgentEnvironment | None:
        return await self._session.scalar(
            select(AgentEnvironment)
            .where(
                schema.agent_environments.c.workspace_id == workspace_id,
                schema.agent_environments.c.id == environment_id,
                or_(
                    schema.agent_environments.c.status
                    == AgentEnvironmentStatus.PROVISIONING,
                    and_(
                        schema.agent_environments.c.status
                        == AgentEnvironmentStatus.CREATING,
                        schema.agent_environments.c.provisioning_expires_at <= when,
                    ),
                ),
            )
            .with_for_update(skip_locked=True)
        )

    @override
    async def add_thread(self, thread: AgentThread) -> None:
        self._session.add(thread)
        await self._session.flush()

    @override
    async def get_thread(
        self,
        workspace_id: UUID,
        thread_id: UUID,
    ) -> AgentThread | None:
        return await self._session.scalar(
            select(AgentThread).where(
                schema.agent_threads.c.workspace_id == workspace_id,
                schema.agent_threads.c.id == thread_id,
            )
        )

    @override
    async def lock_thread(
        self,
        workspace_id: UUID,
        thread_id: UUID,
    ) -> AgentThread | None:
        return await self._session.scalar(
            select(AgentThread)
            .where(
                schema.agent_threads.c.workspace_id == workspace_id,
                schema.agent_threads.c.id == thread_id,
            )
            .with_for_update()
        )

    @override
    async def save_thread(self, thread: AgentThread) -> None:
        del thread
        await self._session.flush()

    @override
    async def add_draft(self, draft: DraftNode) -> None:
        self._session.add(draft)
        await self._session.flush()

    @override
    async def get_draft(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> DraftNode | None:
        return await self._session.scalar(
            select(DraftNode).where(
                schema.draft_nodes.c.workspace_id == workspace_id,
                schema.draft_nodes.c.id == draft_node_id,
            )
        )

    @override
    async def lock_draft(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> DraftNode | None:
        return await self._session.scalar(
            select(DraftNode)
            .where(
                schema.draft_nodes.c.workspace_id == workspace_id,
                schema.draft_nodes.c.id == draft_node_id,
            )
            .with_for_update()
        )

    @override
    async def save_draft(self, draft: DraftNode) -> None:
        del draft
        await self._session.flush()

    @override
    async def list_drafts(
        self,
        workspace_id: UUID,
        *,
        thread_id: UUID | None = None,
    ) -> list[DraftNode]:
        statement = select(DraftNode).where(
            schema.draft_nodes.c.workspace_id == workspace_id
        )
        if thread_id is not None:
            statement = statement.where(schema.draft_nodes.c.thread_id == thread_id)
        result = await self._session.scalars(
            statement.order_by(
                schema.draft_nodes.c.updated_at.desc(),
                schema.draft_nodes.c.id.asc(),
            )
        )
        return list(result)

    @override
    async def add_run(self, run: AgentRun) -> None:
        self._session.add(run)
        await self._session.flush()

    @override
    async def get_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> AgentRun | None:
        return await self._session.scalar(
            select(AgentRun).where(
                schema.agent_runs.c.workspace_id == workspace_id,
                schema.agent_runs.c.id == run_id,
            )
        )

    @override
    async def lock_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> AgentRun | None:
        return await self._session.scalar(
            select(AgentRun)
            .where(
                schema.agent_runs.c.workspace_id == workspace_id,
                schema.agent_runs.c.id == run_id,
            )
            .with_for_update()
        )

    @override
    async def lock_claimable_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        when: datetime,
    ) -> AgentRun | None:
        run = await self._session.scalar(
            select(AgentRun)
            .where(
                schema.agent_runs.c.workspace_id == workspace_id,
                schema.agent_runs.c.id == run_id,
                or_(
                    schema.agent_runs.c.status == AgentRunStatus.QUEUED,
                    and_(
                        schema.agent_runs.c.status == AgentRunStatus.CLAIMED,
                        schema.agent_runs.c.lease_expires_at <= when,
                    ),
                ),
            )
            .with_for_update(skip_locked=True)
        )
        if run is None:
            return None

        if run.status is AgentRunStatus.QUEUED:
            writer_condition = schema.agent_environments.c.active_run_id.is_(None)
        else:
            writer_condition = schema.agent_environments.c.active_run_id == run.id
        environment = await self._session.scalar(
            select(AgentEnvironment)
            .where(
                schema.agent_environments.c.workspace_id == workspace_id,
                schema.agent_environments.c.id == run.environment_id,
                schema.agent_environments.c.status == AgentEnvironmentStatus.READY,
                writer_condition,
            )
            .with_for_update(skip_locked=True)
        )
        if environment is None:
            return None
        return run

    @override
    async def lock_expired_running_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        when: datetime,
    ) -> AgentRun | None:
        run = await self._session.scalar(
            select(AgentRun)
            .where(
                schema.agent_runs.c.workspace_id == workspace_id,
                schema.agent_runs.c.id == run_id,
                schema.agent_runs.c.status == AgentRunStatus.RUNNING,
                schema.agent_runs.c.lease_expires_at <= when,
            )
            .with_for_update(skip_locked=True)
        )
        if run is None:
            return None

        environment = await self._session.scalar(
            select(AgentEnvironment)
            .where(
                schema.agent_environments.c.workspace_id == workspace_id,
                schema.agent_environments.c.id == run.environment_id,
                schema.agent_environments.c.active_run_id == run.id,
            )
            .with_for_update(skip_locked=True)
        )
        if environment is None:
            return None
        return run

    @override
    async def save_run(self, run: AgentRun) -> None:
        del run
        await self._session.flush()

    @override
    async def get_run_by_idempotency(
        self,
        workspace_id: UUID,
        idempotency_key: str,
    ) -> AgentRun | None:
        return await self._session.scalar(
            select(AgentRun).where(
                schema.agent_runs.c.workspace_id == workspace_id,
                schema.agent_runs.c.idempotency_key == idempotency_key,
            )
        )

    @override
    async def list_runs_for_thread(
        self,
        workspace_id: UUID,
        thread_id: UUID,
    ) -> list[AgentRun]:
        result = await self._session.scalars(
            select(AgentRun)
            .where(
                schema.agent_runs.c.workspace_id == workspace_id,
                schema.agent_runs.c.thread_id == thread_id,
            )
            .order_by(
                schema.agent_runs.c.created_at.asc(),
                schema.agent_runs.c.id.asc(),
            )
        )
        return list(result)

    @override
    async def list_claimable_run_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        earlier_run = schema.agent_runs.alias("earlier_agent_run")
        earlier_queued_run_exists = exists(
            select(1).where(
                earlier_run.c.workspace_id == schema.agent_runs.c.workspace_id,
                earlier_run.c.environment_id == schema.agent_runs.c.environment_id,
                earlier_run.c.status == AgentRunStatus.QUEUED,
                or_(
                    earlier_run.c.created_at < schema.agent_runs.c.created_at,
                    and_(
                        earlier_run.c.created_at == schema.agent_runs.c.created_at,
                        earlier_run.c.id < schema.agent_runs.c.id,
                    ),
                ),
            )
        )
        statement = (
            select(
                schema.agent_runs.c.workspace_id,
                schema.agent_runs.c.id,
            )
            .join(
                schema.agent_environments,
                and_(
                    schema.agent_environments.c.workspace_id
                    == schema.agent_runs.c.workspace_id,
                    schema.agent_environments.c.id
                    == schema.agent_runs.c.environment_id,
                ),
            )
            .where(
                schema.agent_environments.c.status == AgentEnvironmentStatus.READY,
                or_(
                    and_(
                        schema.agent_runs.c.status == AgentRunStatus.QUEUED,
                        schema.agent_environments.c.active_run_id.is_(None),
                        ~earlier_queued_run_exists,
                    ),
                    and_(
                        schema.agent_runs.c.status == AgentRunStatus.CLAIMED,
                        schema.agent_runs.c.lease_expires_at <= when,
                        schema.agent_environments.c.active_run_id
                        == schema.agent_runs.c.id,
                    ),
                ),
            )
            .order_by(
                schema.agent_runs.c.created_at.asc(),
                schema.agent_runs.c.id.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(statement)
        return [(row.workspace_id, row.id) for row in result]

    @override
    async def list_expired_running_run_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        statement = (
            select(
                schema.agent_runs.c.workspace_id,
                schema.agent_runs.c.id,
            )
            .join(
                schema.agent_environments,
                and_(
                    schema.agent_environments.c.workspace_id
                    == schema.agent_runs.c.workspace_id,
                    schema.agent_environments.c.id
                    == schema.agent_runs.c.environment_id,
                ),
            )
            .where(
                schema.agent_runs.c.status == AgentRunStatus.RUNNING,
                schema.agent_runs.c.lease_expires_at <= when,
                schema.agent_environments.c.active_run_id == schema.agent_runs.c.id,
            )
            .order_by(
                schema.agent_runs.c.lease_expires_at.asc(),
                schema.agent_runs.c.id.asc(),
            )
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(statement)
        return [(row.workspace_id, row.id) for row in result]

    @override
    async def list_interrupting_run_keys(
        self,
        *,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        statement = (
            select(
                schema.agent_runs.c.workspace_id,
                schema.agent_runs.c.id,
            )
            .join(
                schema.agent_environments,
                and_(
                    schema.agent_environments.c.workspace_id
                    == schema.agent_runs.c.workspace_id,
                    schema.agent_environments.c.id
                    == schema.agent_runs.c.environment_id,
                ),
            )
            .where(
                schema.agent_runs.c.status == AgentRunStatus.INTERRUPTING,
                schema.agent_environments.c.active_run_id == schema.agent_runs.c.id,
            )
            .order_by(
                schema.agent_runs.c.updated_at.asc(),
                schema.agent_runs.c.id.asc(),
            )
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [(row.workspace_id, row.id) for row in result]

    @override
    async def list_cancelling_run_keys(
        self,
        *,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        statement = (
            select(
                schema.agent_runs.c.workspace_id,
                schema.agent_runs.c.id,
            )
            .join(
                schema.agent_environments,
                and_(
                    schema.agent_environments.c.workspace_id
                    == schema.agent_runs.c.workspace_id,
                    schema.agent_environments.c.id
                    == schema.agent_runs.c.environment_id,
                ),
            )
            .where(
                schema.agent_runs.c.status == AgentRunStatus.CANCELLING,
                schema.agent_environments.c.active_run_id == schema.agent_runs.c.id,
            )
            .order_by(
                schema.agent_runs.c.updated_at.asc(),
                schema.agent_runs.c.id.asc(),
            )
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [(row.workspace_id, row.id) for row in result]

    @override
    async def add_build_attempt(self, build: NodeBuildAttempt) -> None:
        self._session.add(build)
        await self._session.flush()

    @override
    async def get_build_attempt(
        self,
        workspace_id: UUID,
        build_attempt_id: UUID,
    ) -> NodeBuildAttempt | None:
        return await self._session.scalar(
            select(NodeBuildAttempt).where(
                schema.node_build_attempts.c.workspace_id == workspace_id,
                schema.node_build_attempts.c.id == build_attempt_id,
            )
        )

    @override
    async def lock_build_attempt(
        self,
        workspace_id: UUID,
        build_attempt_id: UUID,
    ) -> NodeBuildAttempt | None:
        return await self._session.scalar(
            select(NodeBuildAttempt)
            .where(
                schema.node_build_attempts.c.workspace_id == workspace_id,
                schema.node_build_attempts.c.id == build_attempt_id,
            )
            .with_for_update()
        )

    @override
    async def save_build_attempt(self, build: NodeBuildAttempt) -> None:
        del build
        await self._session.flush()

    @override
    async def list_build_attempts_for_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> list[NodeBuildAttempt]:
        result = await self._session.scalars(
            select(NodeBuildAttempt)
            .where(
                schema.node_build_attempts.c.workspace_id == workspace_id,
                schema.node_build_attempts.c.run_id == run_id,
            )
            .order_by(
                schema.node_build_attempts.c.attempt_number.asc(),
                schema.node_build_attempts.c.id.asc(),
            )
        )
        return list(result)

    @override
    async def list_build_attempts_for_draft(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> list[NodeBuildAttempt]:
        result = await self._session.scalars(
            select(NodeBuildAttempt)
            .where(
                schema.node_build_attempts.c.workspace_id == workspace_id,
                schema.node_build_attempts.c.draft_node_id == draft_node_id,
            )
            .order_by(
                schema.node_build_attempts.c.attempt_number.asc(),
                schema.node_build_attempts.c.id.asc(),
            )
        )
        return list(result)

    @override
    async def get_latest_build_attempt_for_draft(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> NodeBuildAttempt | None:
        return await self._session.scalar(
            select(NodeBuildAttempt)
            .where(
                schema.node_build_attempts.c.workspace_id == workspace_id,
                schema.node_build_attempts.c.draft_node_id == draft_node_id,
            )
            .order_by(
                schema.node_build_attempts.c.attempt_number.desc(),
                schema.node_build_attempts.c.id.desc(),
            )
            .limit(1)
        )

    @override
    async def add_event(self, event: AgentEvent) -> None:
        self._session.add(event)
        await self._session.flush()

    @override
    async def list_events(
        self,
        workspace_id: UUID,
        thread_id: UUID,
        *,
        after_sequence: int,
        limit: int,
    ) -> list[AgentEvent]:
        result = await self._session.scalars(
            select(AgentEvent)
            .where(
                schema.agent_events.c.workspace_id == workspace_id,
                schema.agent_events.c.thread_id == thread_id,
                schema.agent_events.c.sequence > after_sequence,
            )
            .order_by(schema.agent_events.c.sequence.asc())
            .limit(limit)
        )
        return list(result)

    @override
    async def add_capability_approval(
        self,
        approval: CapabilityApproval,
    ) -> None:
        self._session.add(approval)
        await self._session.flush()

    @override
    async def get_capability_approval(
        self,
        workspace_id: UUID,
        build_attempt_id: UUID,
    ) -> CapabilityApproval | None:
        return await self._session.scalar(
            select(CapabilityApproval).where(
                schema.capability_approvals.c.workspace_id == workspace_id,
                schema.capability_approvals.c.build_attempt_id == build_attempt_id,
            )
        )

    @override
    async def add_release(self, release: NodeRelease) -> None:
        self._session.add(release)
        await self._session.flush()

    @override
    async def get_release(
        self,
        workspace_id: UUID,
        node_id: UUID,
        revision: int,
    ) -> NodeRelease | None:
        return await self._session.get(
            NodeRelease,
            (workspace_id, node_id, revision),
        )

    @override
    async def list_releases(
        self,
        workspace_id: UUID,
    ) -> list[NodeRelease]:
        result = await self._session.scalars(
            select(NodeRelease)
            .where(schema.node_releases.c.workspace_id == workspace_id)
            .order_by(
                schema.node_releases.c.node_id.asc(),
                schema.node_releases.c.revision.desc(),
            )
        )
        return list(result)
