from collections.abc import Sequence
from datetime import datetime
from typing import Protocol
from uuid import UUID

from grafy_core.domain.identity import (
    AuthSession,
    OidcIdentity,
    OidcLoginTransaction,
    PersonalAccessToken,
    PlatformAccessToken,
    User,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMembership,
)
from grafy_core.domain.security_audit import SecurityAuditEvent
from grafy_core.ports.transactions import TransactionPort


class IdentityRepositoryPort(Protocol):
    async def add_user(self, user: User) -> None: ...

    async def get_user(self, user_id: UUID) -> User | None: ...

    async def find_active_users_by_verified_email(
        self,
        normalized_email: str,
    ) -> list[User]: ...

    async def get_oidc_identity(
        self,
        *,
        issuer: str,
        subject: str,
    ) -> OidcIdentity | None: ...

    async def add_oidc_identity(self, identity: OidcIdentity) -> None: ...

    async def add_workspace(self, workspace: Workspace) -> None: ...

    async def get_workspace(self, workspace_id: UUID) -> Workspace | None: ...

    async def get_workspace_by_slug(self, slug: str) -> Workspace | None: ...

    async def lock_workspace_for_membership_mutation(
        self,
        workspace_id: UUID,
    ) -> Workspace | None: ...

    async def lock_workspace_by_slug_for_membership_mutation(
        self,
        slug: str,
    ) -> Workspace | None: ...

    async def get_personal_workspace(self, user_id: UUID) -> Workspace | None: ...

    async def list_workspaces_for_user(self, user_id: UUID) -> list[Workspace]: ...

    async def list_memberships_for_user(
        self, user_id: UUID
    ) -> list[WorkspaceMembership]: ...

    async def add_membership(self, membership: WorkspaceMembership) -> None: ...

    async def get_membership(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
    ) -> WorkspaceMembership | None: ...

    async def list_memberships(
        self, workspace_id: UUID
    ) -> list[WorkspaceMembership]: ...

    async def count_active_owners(self, workspace_id: UUID) -> int: ...

    async def add_workspace_invitation(
        self,
        invitation: WorkspaceInvitation,
    ) -> None: ...

    async def get_workspace_invitation(
        self,
        invitation_id: UUID,
    ) -> WorkspaceInvitation | None: ...

    async def list_workspace_invitations(
        self,
        workspace_id: UUID,
    ) -> list[WorkspaceInvitation]: ...

    async def list_workspace_invitations_for_user(
        self,
        user_id: UUID,
    ) -> list[WorkspaceInvitation]: ...

    async def add_login_transaction(
        self, transaction: OidcLoginTransaction
    ) -> None: ...

    async def get_login_transaction(
        self,
        transaction_id: UUID,
    ) -> OidcLoginTransaction | None: ...

    async def lock_login_transaction(
        self,
        transaction_id: UUID,
    ) -> OidcLoginTransaction | None: ...

    async def add_auth_session(self, session: AuthSession) -> None: ...

    async def get_auth_session(self, session_id: UUID) -> AuthSession | None: ...

    async def list_auth_sessions_for_user(self, user_id: UUID) -> list[AuthSession]: ...

    async def get_auth_session_for_user(
        self,
        *,
        session_id: UUID,
        user_id: UUID,
    ) -> AuthSession | None: ...

    async def delete_expired_login_transactions(
        self, expired_before: datetime
    ) -> int: ...

    async def add_personal_access_token(self, token: PersonalAccessToken) -> None: ...

    async def get_personal_access_token_by_digest(
        self,
        secret_digest: bytes,
    ) -> PersonalAccessToken | None: ...

    async def get_personal_access_token_by_prefix(
        self,
        public_prefix: str,
    ) -> PersonalAccessToken | None: ...

    async def add_platform_access_token(self, token: PlatformAccessToken) -> None: ...

    async def get_platform_access_token(
        self,
        token_id: UUID,
    ) -> PlatformAccessToken | None: ...

    async def get_platform_access_token_by_prefix(
        self,
        public_prefix: str,
    ) -> PlatformAccessToken | None: ...

    async def list_platform_access_tokens(self) -> list[PlatformAccessToken]: ...

    async def list_personal_access_tokens_for_user(
        self,
        user_id: UUID,
    ) -> list[PersonalAccessToken]: ...

    async def list_personal_access_tokens_for_user_workspace(
        self,
        *,
        user_id: UUID,
        workspace_id: UUID,
    ) -> list[PersonalAccessToken]: ...

    async def get_personal_access_token_for_user_workspace(
        self,
        *,
        token_id: UUID,
        user_id: UUID,
        workspace_id: UUID,
    ) -> PersonalAccessToken | None: ...

    async def delete_expired_sessions(self, expired_before: datetime) -> int: ...

    async def delete_expired_personal_access_tokens(
        self,
        expired_before: datetime,
    ) -> int: ...


class SecurityAuditRepositoryPort(Protocol):
    async def add(self, event: SecurityAuditEvent) -> None: ...

    async def list_for_workspace(
        self,
        workspace_id: UUID,
        *,
        limit: int,
    ) -> Sequence[SecurityAuditEvent]: ...

    async def delete_before(self, occurred_before: datetime) -> int: ...


class IdentityUnitOfWorkPort(TransactionPort, Protocol):
    @property
    def identity(self) -> IdentityRepositoryPort: ...

    @property
    def security_audit(self) -> SecurityAuditRepositoryPort: ...


__all__ = [
    "IdentityRepositoryPort",
    "IdentityUnitOfWorkPort",
    "SecurityAuditRepositoryPort",
]
