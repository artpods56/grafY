from datetime import datetime
from typing import cast, override
from uuid import UUID
from sqlalchemy import (
    delete,
    func,
    or_,
    select,
    text,
)
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession
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
)
from grafy_core.domain.security_audit import SecurityAuditEvent
from grafy_core.ports.identity import (
    IdentityRepositoryPort,
    SecurityAuditRepositoryPort,
)
from grafy_persistence import schema


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
