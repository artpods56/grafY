from collections.abc import Collection
from datetime import UTC, datetime
from typing import cast, override
from uuid import UUID

from sqlalchemy import and_, case, delete, func, insert, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.schema import Table

from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRepositoryPort,
    ArtifactTypeKey,
)
from grafy_core.domain.plugin_catalog import PluginCatalogRelease
from grafy_core.domain.plugin_releases import PluginReleaseScope
from grafy_core.domain.invocation_cache import InvocationCacheEntry
from grafy_core.domain.identity import (
    AuthSession,
    OidcIdentity,
    OidcLoginTransaction,
    PlatformAccessToken,
    PersonalAccessToken,
    User,
    Workspace,
    WorkspaceInvitation,
    WorkspaceKind,
    WorkspaceMembership,
    WorkspaceRole,
)
from grafy_core.domain.errors import (
    CollaborationActiveExecutionError,
    ConcurrentWriteError,
    GraphFolderNameConflictError,
    NotFoundError,
    ObjectAlreadyExistsError,
)
from grafy_core.domain.execution_history import (
    ActiveGraphExecution,
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
from grafy_core.domain.plugin_releases import (
    PluginCatalogManifest,
    PluginRelease,
    PluginReleaseError,
    PluginReleaseNamespace,
    PluginRuntimeArtifact,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_revocations import (
    PluginReleaseRevocation,
    PluginReleaseRevocationError,
)
from grafy_core.domain.plugin_selection import (
    PluginReleaseSelection,
    PluginReleaseSelectionError,
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
from grafy_core.domain.security_audit import SecurityAuditEvent
from grafy_core.domain.staged_uploads import StagedUpload
from grafy_core.domain.templates import Template, TemplateState
from grafy_core.ports.identity import (
    IdentityRepositoryPort,
    SecurityAuditRepositoryPort,
)
from grafy_core.ports.invocation_cache import InvocationCacheRepositoryPort
from grafy_core.ports.execution_history import (
    GraphExecutionHistoryRepositoryPort,
)
from grafy_core.ports.materialized_outputs import (
    MaterializedNodeOutputsRepositoryPort,
)
from grafy_core.ports.module_library import ModuleLibraryRepositoryPort
from grafy_core.ports.plugin_releases import PluginReleaseRepositoryPort
from grafy_core.ports.node_secrets import NodeSecretRepositoryPort
from grafy_core.ports.saved_graphs import SavedGraphRepositoryPort
from grafy_core.ports.staged_uploads import StagedUploadRepositoryPort
from grafy_core.ports.templates import TemplateRepositoryPort

from grafy_persistence import schema
from grafy_persistence.orm import GraphExecutionRecord, SavedGraphRevisionRecord

_ACTIVE_EXECUTION_STATUSES = ("queued", "running", "cancelling")


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
    async def find_active_users_by_verified_email(
        self,
        normalized_email: str,
    ) -> list[User]:
        result = await self._session.scalars(
            select(User)
            .where(
                schema.users.c.normalized_email == normalized_email,
                schema.users.c.email_verified.is_(True),
                schema.users.c.active.is_(True),
            )
            .order_by(schema.users.c.id.asc())
        )
        return list(result)

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
            if not self._session.in_transaction():
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
            if not self._session.in_transaction():
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
    async def add_workspace_invitation(
        self,
        invitation: WorkspaceInvitation,
    ) -> None:
        self._session.add(invitation)

    @override
    async def get_workspace_invitation(
        self,
        invitation_id: UUID,
    ) -> WorkspaceInvitation | None:
        return await self._session.get(WorkspaceInvitation, invitation_id)

    @override
    async def list_workspace_invitations(
        self,
        workspace_id: UUID,
    ) -> list[WorkspaceInvitation]:
        result = await self._session.scalars(
            select(WorkspaceInvitation)
            .where(schema.workspace_invitations.c.workspace_id == workspace_id)
            .order_by(schema.workspace_invitations.c.created_at.desc())
        )
        return list(result)

    @override
    async def list_workspace_invitations_for_user(
        self,
        user_id: UUID,
    ) -> list[WorkspaceInvitation]:
        result = await self._session.scalars(
            select(WorkspaceInvitation)
            .where(schema.workspace_invitations.c.invitee_user_id == user_id)
            .order_by(schema.workspace_invitations.c.created_at.desc())
        )
        return list(result)

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
    async def get_personal_access_token_by_prefix(
        self,
        public_prefix: str,
    ) -> PersonalAccessToken | None:
        return await self._session.scalar(
            select(PersonalAccessToken).where(
                schema.personal_access_tokens.c.public_prefix == public_prefix
            )
        )

    @override
    async def add_platform_access_token(self, token: PlatformAccessToken) -> None:
        self._session.add(token)

    @override
    async def get_platform_access_token(
        self,
        token_id: UUID,
    ) -> PlatformAccessToken | None:
        return await self._session.get(PlatformAccessToken, token_id)

    @override
    async def get_platform_access_token_by_prefix(
        self,
        public_prefix: str,
    ) -> PlatformAccessToken | None:
        return await self._session.scalar(
            select(PlatformAccessToken).where(
                schema.platform_access_tokens.c.public_prefix == public_prefix
            )
        )

    @override
    async def list_platform_access_tokens(self) -> list[PlatformAccessToken]:
        result = await self._session.scalars(
            select(PlatformAccessToken).order_by(
                schema.platform_access_tokens.c.created_at.desc()
            )
        )
        return list(result)

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
            async with self._session.begin_nested():
                await self._session.execute(
                    insert(table).values(
                        execution_id=execution.execution_id,
                        workspace_id=execution.workspace_id,
                        graph_id=execution.graph_id,
                        graph_revision=execution.graph_revision,
                        status=execution.status,
                        scope=execution.scope,
                        submitted_request=execution.submitted_request,
                        idempotency_key=execution.idempotency_key,
                        submitted_by_actor_id=execution.submitted_by_actor_id,
                        workflow_run_id=execution.workflow_run_id,
                        error=execution.error,
                        created_at=execution.created_at,
                        started_at=execution.started_at,
                        finished_at=execution.finished_at,
                    )
                )
                if execution.requested_node_ids:
                    await self._session.execute(
                        insert(schema.graph_execution_nodes),
                        [
                            {
                                "workspace_id": execution.workspace_id,
                                "execution_id": execution.execution_id,
                                "node_id": node_id,
                                "position": position,
                            }
                            for position, node_id in enumerate(
                                execution.requested_node_ids
                            )
                        ],
                    )
        except IntegrityError as exc:
            await self._session.rollback()
            active_execution_id = await self.find_active_execution_id(
                execution.workspace_id,
                execution.graph_id,
            )
            if active_execution_id is not None:
                raise CollaborationActiveExecutionError(
                    workspace_id=execution.workspace_id,
                    graph_id=execution.graph_id,
                    execution_id=active_execution_id,
                ) from exc
            raise ObjectAlreadyExistsError(
                f"Graph execution already exists: {execution.execution_id}"
            ) from exc

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
            or current.submitted_request != execution.submitted_request
            or current.idempotency_key != execution.idempotency_key
            or current.submitted_by_actor_id != execution.submitted_by_actor_id
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
        nodes = schema.graph_execution_nodes
        requested = await self._session.execute(
            select(nodes.c.result_status).where(
                nodes.c.workspace_id == result.workspace_id,
                nodes.c.execution_id == result.execution_id,
                nodes.c.node_id == result.node_id,
            )
        )
        requested_row = requested.one_or_none()
        if requested_row is None:
            raise ValueError(
                f"Graph execution {result.execution_id} did not request node "
                f"{result.node_id!r}"
            )
        if requested_row.result_status is not None:
            raise ObjectAlreadyExistsError(
                "Graph execution node result already exists: "
                f"{result.execution_id}/{result.node_id}"
            )
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    update(nodes)
                    .where(
                        nodes.c.workspace_id == result.workspace_id,
                        nodes.c.execution_id == result.execution_id,
                        nodes.c.node_id == result.node_id,
                    )
                    .values(
                        result_status=result.status,
                        result_position=result.position,
                        outputs=result.outputs,
                        artifact_count=result.artifact_count,
                        error=result.error,
                        diagnostics=result.diagnostics,
                        completed_at=result.completed_at,
                    )
                )
        except IntegrityError as exc:
            await self._session.rollback()
            raise ObjectAlreadyExistsError(
                "Graph execution node result position already exists: "
                f"{result.execution_id}/{result.position}"
            ) from exc

    @override
    async def find_active_execution_id(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> UUID | None:
        return await self._session.scalar(
            select(schema.graph_executions.c.execution_id)
            .where(
                schema.graph_executions.c.workspace_id == workspace_id,
                schema.graph_executions.c.graph_id == graph_id,
                schema.graph_executions.c.status.in_(_ACTIVE_EXECUTION_STATUSES),
            )
            .order_by(
                schema.graph_executions.c.created_at.asc(),
                schema.graph_executions.c.execution_id.asc(),
            )
            .limit(1)
        )

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
        nodes = schema.graph_execution_nodes
        result_rows = (
            await self._session.execute(
                select(
                    nodes.c.node_id,
                    nodes.c.result_position,
                    nodes.c.result_status,
                    nodes.c.outputs,
                    nodes.c.error,
                    nodes.c.diagnostics,
                    nodes.c.completed_at,
                )
                .where(
                    nodes.c.workspace_id == workspace_id,
                    nodes.c.execution_id == execution_id,
                    nodes.c.result_status.is_not(None),
                )
                .order_by(nodes.c.result_position.asc(), nodes.c.node_id.asc())
            )
        ).all()
        results = tuple(
            GraphExecutionNodeResult(
                workspace_id=workspace_id,
                execution_id=execution_id,
                node_id=row.node_id,
                position=row.result_position,
                status=row.result_status,
                outputs=row.outputs,
                error=row.error,
                diagnostics=row.diagnostics,
                completed_at=row.completed_at.replace(tzinfo=UTC),
            )
            for row in result_rows
        )
        return GraphExecutionDetail(
            execution=execution,
            node_results=results,
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
        nodes = schema.graph_execution_nodes
        counts = (
            select(
                nodes.c.workspace_id,
                nodes.c.execution_id,
                func.sum(
                    case(
                        (nodes.c.result_status.is_not(None), 1),
                        else_=0,
                    )
                ).label("node_count"),
                func.coalesce(func.sum(nodes.c.artifact_count), 0).label(
                    "artifact_count"
                ),
            )
            .group_by(
                nodes.c.workspace_id,
                nodes.c.execution_id,
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
                    nodes.c.execution_id == executions.c.execution_id,
                    nodes.c.workspace_id == workspace_id,
                    nodes.c.node_id == normalized_node_id,
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
            node_rows = (
                await self._session.execute(
                    select(
                        nodes.c.execution_id,
                        nodes.c.position,
                        nodes.c.node_id,
                    )
                    .where(nodes.c.execution_id.in_(execution_ids))
                    .where(nodes.c.workspace_id == workspace_id)
                    .order_by(
                        nodes.c.execution_id.asc(),
                        nodes.c.position.asc(),
                    )
                )
            ).all()
            for requested_execution_id, position, requested_node_id in node_rows:
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
    async def list_queued(self) -> tuple[GraphExecution, ...]:
        records = tuple(
            await self._session.scalars(
                select(GraphExecutionRecord)
                .where(schema.graph_executions.c.status == "queued")
                .order_by(
                    schema.graph_executions.c.created_at.asc(),
                    schema.graph_executions.c.execution_id.asc(),
                )
            )
        )
        queued: list[GraphExecution] = []
        for record in records:
            requested_node_ids = await self._requested_node_ids(
                record.workspace_id,
                record.execution_id,
            )
            queued.append(record.to_domain(requested_node_ids))
        return tuple(queued)

    @override
    async def get_by_idempotency_key(
        self,
        workspace_id: UUID,
        idempotency_key: str,
    ) -> GraphExecution | None:
        record = await self._session.scalar(
            select(GraphExecutionRecord).where(
                schema.graph_executions.c.workspace_id == workspace_id,
                schema.graph_executions.c.idempotency_key == idempotency_key,
            )
        )
        if record is None:
            return None
        requested_node_ids = await self._requested_node_ids(
            workspace_id,
            record.execution_id,
        )
        return record.to_domain(requested_node_ids)

    @override
    async def claim_queued(
        self,
        workspace_id: UUID,
        execution_id: UUID,
        *,
        started_at: datetime,
    ) -> bool:
        if started_at.tzinfo is None:
            raise ValueError("Graph execution start timestamp must be timezone-aware")
        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(
                update(schema.graph_executions)
                .where(
                    schema.graph_executions.c.workspace_id == workspace_id,
                    schema.graph_executions.c.execution_id == execution_id,
                    schema.graph_executions.c.status == "queued",
                )
                .values(status="running", started_at=started_at)
            ),
        )
        return result.rowcount == 1

    @override
    async def interrupt_started(
        self,
        *,
        finished_at: datetime,
        error: str,
    ) -> tuple[GraphExecution, ...]:
        if finished_at.tzinfo is None:
            raise ValueError(
                "Graph execution interruption timestamp must be timezone-aware"
            )
        records = tuple(
            await self._session.scalars(
                select(GraphExecutionRecord).where(
                    schema.graph_executions.c.status.in_(("running", "cancelling"))
                )
            )
        )
        interrupted_values: list[GraphExecution] = []
        for record in records:
            requested_node_ids = await self._requested_node_ids(
                record.workspace_id,
                record.execution_id,
            )
            interrupted_values.append(record.to_domain(requested_node_ids))
        interrupted = tuple(interrupted_values)
        if interrupted:
            await self._session.execute(
                update(schema.graph_executions)
                .where(
                    schema.graph_executions.c.execution_id.in_(
                        execution.execution_id for execution in interrupted
                    )
                )
                .values(
                    status="failed",
                    finished_at=finished_at,
                    error=error,
                )
            )
        return interrupted

    async def _requested_node_ids(
        self,
        workspace_id: UUID,
        execution_id: UUID,
    ) -> tuple[str, ...]:
        nodes = schema.graph_execution_nodes
        result = await self._session.scalars(
            select(nodes.c.node_id)
            .where(
                nodes.c.workspace_id == workspace_id,
                nodes.c.execution_id == execution_id,
            )
            .order_by(nodes.c.position.asc())
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


class SqlPluginReleaseRepository(PluginReleaseRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def lock_system_revocation(self) -> tuple[ActiveGraphExecution, ...]:
        dialect_name = self._session.get_bind().dialect.name
        if dialect_name == "postgresql":
            # Match cutover lock order. Execution inserts and status updates take
            # conflicting row-exclusive table locks automatically.
            await self._session.execute(
                text(
                    "LOCK TABLE plugin_release_revocations IN SHARE ROW EXCLUSIVE MODE"
                )
            )
            await self._session.execute(
                text("LOCK TABLE graph_executions IN SHARE ROW EXCLUSIVE MODE")
            )
        elif dialect_name == "sqlite":
            if self._session.in_transaction():
                raise PluginReleaseRevocationError(
                    "System Plugin revocation fence requires a fresh transaction"
                )
            await self._session.execute(text("BEGIN IMMEDIATE"))
        else:
            raise PluginReleaseRevocationError(
                "System Plugin revocation requires an execution admission fence; "
                f"database dialect {dialect_name!r} is unsupported"
            )
        executions = schema.graph_executions
        rows = await self._session.execute(
            select(executions.c.execution_id, executions.c.status)
            .where(executions.c.status.in_(("queued", "running", "cancelling")))
            .order_by(executions.c.created_at.asc(), executions.c.execution_id.asc())
        )
        return tuple(
            ActiveGraphExecution(execution_id=execution_id, status=status)
            for execution_id, status in rows
        )

    @override
    async def add(self, release: PluginRelease) -> None:
        self._session.add(release)
        await self._session.flush()

    @override
    async def add_installation(self, installation: PluginInstallation) -> None:
        await self._require_installation_release(installation)
        self._session.add(installation)
        await self._session.flush()

    @override
    async def get_by_source_digest(
        self,
        slug: str,
        source_digest: str,
    ) -> PluginRelease | None:
        return await self._session.scalar(
            select(PluginRelease)
            .where(
                schema.plugin_releases.c.slug == slug,
                schema.plugin_releases.c.source_digest == source_digest,
            )
            .order_by(schema.plugin_releases.c.revision.desc())
        )

    @override
    async def get_by_descriptor_digest(
        self,
        slug: str,
        descriptor_digest: str,
    ) -> PluginRelease | None:
        return await self._session.scalar(
            select(PluginRelease).where(
                schema.plugin_releases.c.slug == slug,
                schema.plugin_releases.c.descriptor_digest == descriptor_digest,
            )
        )

    @override
    async def get_by_revision(
        self,
        namespace: PluginReleaseNamespace,
        slug: str,
        revision: int,
    ) -> InstalledPluginRelease | None:
        row = (
            await self._session.execute(
                select(PluginRelease, PluginInstallation)
                .join(
                    PluginInstallation,
                    schema.plugin_installations.c.release_id
                    == schema.plugin_releases.c.id,
                )
                .where(
                    *self._namespace_conditions(
                        schema.plugin_installations,
                        namespace,
                    ),
                    schema.plugin_releases.c.slug == slug,
                    schema.plugin_releases.c.revision == revision,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        return InstalledPluginRelease(release=row[0], installation=row[1])

    @override
    async def get_revocation_by_installation_id(
        self,
        installation_id: UUID,
    ) -> PluginReleaseRevocation | None:
        return await self._session.get(PluginReleaseRevocation, installation_id)

    @override
    async def add_revocation(
        self,
        revocation: PluginReleaseRevocation,
    ) -> PluginReleaseRevocation:
        await self._require_revoked_release(revocation)
        existing = await self.get_revocation_by_installation_id(
            revocation.installation_id
        )
        if existing is not None:
            if existing.has_same_intent(revocation):
                return existing
            raise PluginReleaseRevocationError(
                "Plugin release revocation already exists with different immutable "
                f"intent for {revocation.scope.value}:"
                f"{revocation.workspace_id}:{revocation.slug}@"
                f"{revocation.revision} ({revocation.installation_id})"
            )
        self._session.add(revocation)
        await self._session.flush()
        return revocation

    @override
    async def next_revision(
        self,
        slug: str,
    ) -> int:
        await self._session.execute(
            select(schema.plugin_releases.c.id)
            .where(schema.plugin_releases.c.slug == slug)
            .with_for_update()
        )
        latest = await self._session.scalar(
            select(func.max(schema.plugin_releases.c.revision)).where(
                schema.plugin_releases.c.slug == slug,
            )
        )
        return 1 if latest is None else int(latest) + 1

    @override
    async def family_exists(
        self,
        namespace: PluginReleaseNamespace,
        slug: str,
    ) -> bool:
        release_id = await self._session.scalar(
            select(schema.plugin_installations.c.id)
            .where(
                *self._namespace_conditions(schema.plugin_installations, namespace),
                schema.plugin_installations.c.slug == slug,
            )
            .limit(1)
        )
        return release_id is not None

    @override
    async def workspace_family_exists(self, slug: str) -> bool:
        release_id = await self._session.scalar(
            select(schema.plugin_installations.c.id)
            .where(
                schema.plugin_installations.c.scope == "workspace",
                schema.plugin_installations.c.slug == slug,
            )
            .limit(1)
        )
        return release_id is not None

    @override
    async def list_workspace_catalogs(self) -> list[PluginCatalogManifest]:
        result = await self._session.scalars(
            select(schema.plugin_releases.c.catalog)
            .join(
                schema.plugin_installations,
                schema.plugin_installations.c.release_id == schema.plugin_releases.c.id,
            )
            .where(schema.plugin_installations.c.scope == "workspace")
            .order_by(
                schema.plugin_installations.c.workspace_id.asc(),
                schema.plugin_releases.c.slug.asc(),
                schema.plugin_releases.c.revision.asc(),
            )
        )
        return list(result)

    @override
    async def list_catalogs(
        self,
        namespace: PluginReleaseNamespace,
    ) -> list[PluginCatalogManifest]:
        result = await self._session.scalars(
            select(schema.plugin_releases.c.catalog)
            .join(
                schema.plugin_installations,
                schema.plugin_installations.c.release_id == schema.plugin_releases.c.id,
            )
            .where(*self._namespace_conditions(schema.plugin_installations, namespace))
            .order_by(
                schema.plugin_releases.c.slug.asc(),
                schema.plugin_releases.c.revision.asc(),
            )
        )
        return list(result)

    @override
    async def list_catalog(self, workspace_id: UUID) -> list[PluginCatalogRelease]:
        releases = schema.plugin_releases
        selections = schema.plugin_release_selections
        installations = schema.plugin_installations
        rows = await self._session.execute(
            select(
                PluginRelease,
                PluginInstallation,
                PluginReleaseSelection,
                PluginReleaseRevocation,
            )
            .select_from(PluginReleaseSelection)
            .join(PluginRelease, selections.c.selected_release_id == releases.c.id)
            .join(
                PluginInstallation,
                and_(
                    installations.c.release_id == releases.c.id,
                    installations.c.scope == selections.c.scope,
                    installations.c.workspace_id.is_not_distinct_from(
                        selections.c.workspace_id
                    ),
                ),
            )
            .outerjoin(
                PluginReleaseRevocation,
                schema.plugin_release_revocations.c.installation_id
                == installations.c.id,
            )
            .where(
                or_(
                    and_(
                        selections.c.scope == PluginReleaseScope.SYSTEM,
                        selections.c.workspace_id.is_(None),
                    ),
                    and_(
                        selections.c.scope == PluginReleaseScope.WORKSPACE,
                        selections.c.workspace_id == workspace_id,
                    ),
                )
            )
            .order_by(selections.c.scope.asc(), releases.c.slug.asc())
        )
        return [
            PluginCatalogRelease(
                release=InstalledPluginRelease(
                    release=release, installation=installation
                ),
                selection=selection,
                revocation=revocation,
            )
            for release, installation, selection, revocation in rows
        ]

    @override
    async def list_current(
        self,
        namespace: PluginReleaseNamespace,
    ) -> list[InstalledPluginRelease]:
        releases = schema.plugin_releases
        selections = schema.plugin_release_selections
        rows = await self._session.execute(
            select(PluginRelease, PluginInstallation)
            .join(
                selections,
                selections.c.selected_release_id == releases.c.id,
            )
            .join(
                PluginInstallation,
                and_(
                    schema.plugin_installations.c.release_id == releases.c.id,
                    schema.plugin_installations.c.scope == selections.c.scope,
                    schema.plugin_installations.c.workspace_id.is_not_distinct_from(
                        selections.c.workspace_id
                    ),
                ),
            )
            .where(*self._namespace_conditions(selections, namespace))
            .order_by(releases.c.slug.asc())
        )
        return [
            InstalledPluginRelease(release=release, installation=installation)
            for release, installation in rows
        ]

    @override
    async def get_selection(
        self,
        namespace: PluginReleaseNamespace,
        slug: str,
    ) -> PluginReleaseSelection | None:
        return await self._session.scalar(
            select(PluginReleaseSelection).where(
                *self._namespace_conditions(
                    schema.plugin_release_selections,
                    namespace,
                ),
                schema.plugin_release_selections.c.slug == slug,
            )
        )

    @override
    async def add_selection(
        self,
        selection: PluginReleaseSelection,
    ) -> None:
        await self._require_selected_release(selection)
        self._session.add(selection)
        await self._session.flush()

    @override
    async def update_selection(
        self,
        selection: PluginReleaseSelection,
        *,
        expected_generation: int,
    ) -> None:
        if isinstance(expected_generation, bool) or expected_generation < 1:
            raise ValueError("Expected Plugin selection generation must be positive")
        if selection.generation <= expected_generation:
            raise ValueError(
                "Updated Plugin selection generation must exceed the expected "
                "generation"
            )
        await self._require_selected_release(selection)
        table = schema.plugin_release_selections
        with self._session.no_autoflush:
            result = cast(
                CursorResult[tuple[object, ...]],
                await self._session.execute(
                    update(table)
                    .where(
                        table.c.id == selection.id,
                        *self._namespace_conditions(table, selection.namespace),
                        table.c.slug == selection.slug,
                        table.c.generation == expected_generation,
                    )
                    .values(
                        selected_release_id=selection.selected_release_id,
                        selected_revision=selection.selected_revision,
                        lifecycle=selection.lifecycle,
                        generation=selection.generation,
                        updated_at=selection.updated_at,
                        updated_by_actor=selection.updated_by_actor,
                    )
                ),
            )
        if result.rowcount != 1:
            raise ConcurrentWriteError(
                "Plugin release selection changed concurrently for "
                f"{selection.namespace.scope.value} family {selection.slug!r}; "
                f"expected generation {expected_generation}"
            )
        if selection in self._session.sync_session:
            await self._session.refresh(selection)

    @override
    async def list_runtime_artifacts(self) -> list[PluginRuntimeArtifact]:
        result = await self._session.scalars(
            select(PluginRelease).where(
                schema.plugin_releases.c.runtime_artifact.is_not(None)
            )
        )
        artifacts: list[PluginRuntimeArtifact] = []
        for release in result:
            if release.runtime_artifact is not None:
                artifacts.append(release.runtime_artifact)
        return artifacts

    @staticmethod
    def _namespace_conditions(
        table: Table,
        namespace: PluginReleaseNamespace,
    ) -> tuple[ColumnElement[bool], ColumnElement[bool]]:
        owner_condition = (
            table.c.workspace_id.is_(None)
            if namespace.workspace_id is None
            else table.c.workspace_id == namespace.workspace_id
        )
        return table.c.scope == namespace.scope, owner_condition

    async def _require_selected_release(
        self,
        selection: PluginReleaseSelection,
    ) -> None:
        with self._session.no_autoflush:
            row = (
                await self._session.execute(
                    select(PluginRelease, PluginInstallation)
                    .join(
                        PluginInstallation,
                        schema.plugin_installations.c.release_id
                        == schema.plugin_releases.c.id,
                    )
                    .where(
                        schema.plugin_releases.c.id == selection.selected_release_id,
                        *self._namespace_conditions(
                            schema.plugin_installations,
                            selection.namespace,
                        ),
                    )
                )
            ).one_or_none()
        if row is None:
            raise PluginReleaseSelectionError(
                f"Selected Plugin release {selection.selected_release_id} is not "
                "installed in the selection namespace"
            )
        release = InstalledPluginRelease(release=row[0], installation=row[1])
        if (
            release.namespace != selection.namespace
            or release.slug != selection.slug
            or release.revision != selection.selected_revision
        ):
            raise PluginReleaseSelectionError(
                "Selected Plugin release identity does not match selection family "
                f"{selection.namespace.scope.value}:{selection.slug}:"
                f"{selection.selected_revision}"
            )

    async def _require_revoked_release(
        self,
        revocation: PluginReleaseRevocation,
    ) -> None:
        with self._session.no_autoflush:
            row = (
                await self._session.execute(
                    select(PluginRelease, PluginInstallation)
                    .join(
                        PluginInstallation,
                        schema.plugin_installations.c.release_id
                        == schema.plugin_releases.c.id,
                    )
                    .where(
                        schema.plugin_installations.c.id == revocation.installation_id
                    )
                )
            ).one_or_none()
        if row is None:
            raise PluginReleaseRevocationError(
                f"Revoked Plugin installation {revocation.installation_id} does not exist"
            )
        release = InstalledPluginRelease(release=row[0], installation=row[1])
        if (
            release.namespace != revocation.namespace
            or release.slug != revocation.slug
            or release.revision != revocation.revision
        ):
            raise PluginReleaseRevocationError(
                "Revoked Plugin release identity does not match exact release "
                f"{revocation.scope.value}:{revocation.workspace_id}:"
                f"{revocation.slug}@{revocation.revision} "
                f"({revocation.installation_id})"
            )

    async def _require_installation_release(
        self,
        installation: PluginInstallation,
    ) -> None:
        with self._session.no_autoflush:
            release = await self._session.get(PluginRelease, installation.release_id)
        if release is None:
            raise PluginReleaseError(
                f"Installed Plugin release {installation.release_id} does not exist"
            )
        InstalledPluginRelease(release=release, installation=installation)


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
