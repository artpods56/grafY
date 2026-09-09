import hmac
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from grafy_core.domain.errors import (
    CapabilityDeniedError,
    CredentialAuthenticationError,
    IdentityInvariantError,
    NotFoundError,
    UserDisabledError,
)
from grafy_core.domain.identity import (
    PAT_ALLOWED_CAPABILITIES,
    ActorContext,
    IdentityProvisioningResult,
    OidcDomainWorkspaceGrant,
    OidcIdentity,
    PersonalAccessToken,
    PlatformAccessToken,
    PlatformTokenPrincipal,
    PlatformTokenScope,
    User,
    Workspace,
    WorkspaceAccess,
    WorkspaceCapability,
    WorkspaceInvitation,
    WorkspaceInvitationStatus,
    WorkspaceKind,
    WorkspaceMembership,
    WorkspacePatPrincipal,
    WorkspaceRole,
    ensure_last_owner_can_change,
    normalize_user_email,
    normalize_workspace_slug,
)
from grafy_core.domain.security_audit import (
    SecurityAuditActorKind,
    SecurityAuditEvent,
    SecurityAuditOutcome,
)
from grafy_core.ports.identity import IdentityRepositoryPort, IdentityUnitOfWorkPort


async def authorize_workspace(
    identity: IdentityRepositoryPort,
    *,
    actor: ActorContext,
    workspace_id: UUID,
    capability: WorkspaceCapability,
) -> WorkspaceAccess:
    """Authorize workspace access through the caller's active transaction."""

    if (
        actor.credential_workspace_id is not None
        and actor.credential_workspace_id != workspace_id
    ):
        raise NotFoundError("Workspace", str(workspace_id))
    workspace = await identity.lock_workspace_for_membership_mutation(workspace_id)
    if workspace is None:
        raise NotFoundError("Workspace", str(workspace_id))
    user = await identity.get_user(actor.user_id)
    if user is None or not user.active:
        raise UserDisabledError(f"User {actor.user_id} is disabled")
    membership = await identity.get_membership(
        workspace_id=workspace_id,
        user_id=actor.user_id,
    )
    if membership is None or not membership.is_active:
        raise NotFoundError("Workspace", str(workspace_id))
    access = WorkspaceAccess(
        actor=actor,
        workspace_id=workspace_id,
        membership=membership,
    )
    access.require(capability)
    return access


async def authorize_workspaces(
    identity: IdentityRepositoryPort,
    *,
    actor: ActorContext,
    requirements: Sequence[tuple[UUID, WorkspaceCapability]],
) -> None:
    """Authorize and lock multiple workspaces in deterministic order."""

    for workspace_id, capability in sorted(
        requirements,
        key=lambda requirement: str(requirement[0]),
    ):
        await authorize_workspace(
            identity,
            actor=actor,
            workspace_id=workspace_id,
            capability=capability,
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class WorkspaceInvitationAcceptance:
    invitation: WorkspaceInvitation
    workspace: Workspace
    membership: WorkspaceMembership


@dataclass(frozen=True, slots=True)
class WorkspaceMemberResult:
    user: User
    membership: WorkspaceMembership


class IdentityService:
    """Application-owned identity, workspace, and membership workflows."""

    def __init__(
        self,
        unit_of_work_factory: Callable[[], IdentityUnitOfWorkPort],
        domain_workspace_grants: Sequence[OidcDomainWorkspaceGrant] = (),
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._domain_workspace_grants = tuple(domain_workspace_grants)

    async def authenticate_personal_access_token(
        self,
        *,
        public_prefix: str,
        secret_digest: bytes,
        required_capability: WorkspaceCapability | None = None,
    ) -> WorkspacePatPrincipal:
        now = _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            token = await unit_of_work.identity.get_personal_access_token_by_prefix(
                public_prefix
            )
            if (
                token is None
                or not hmac.compare_digest(token.secret_digest, secret_digest)
                or token.is_revoked
                or token.expires_at <= now
            ):
                raise CredentialAuthenticationError()
            user = await unit_of_work.identity.get_user(token.user_id)
            membership = await unit_of_work.identity.get_membership(
                workspace_id=token.workspace_id,
                user_id=token.user_id,
            )
            if (
                user is None
                or not user.active
                or membership is None
                or not membership.is_active
            ):
                raise CredentialAuthenticationError()
            capabilities = frozenset(token.scopes).intersection(membership.capabilities)
            principal = WorkspacePatPrincipal(
                actor=ActorContext(
                    user_id=token.user_id,
                    credential_reference=f"pat:{token.id}",
                    credential_workspace_id=token.workspace_id,
                ),
                workspace_id=token.workspace_id,
                capabilities=frozenset(capabilities),
                token_id=token.id,
            )
            if required_capability is not None:
                principal.require(required_capability)
            token.last_used_at = now
            await unit_of_work.commit()
            return principal

    async def authenticate_platform_access_token(
        self,
        *,
        public_prefix: str,
        secret_digest: bytes,
        required_scope: PlatformTokenScope | None = None,
    ) -> PlatformTokenPrincipal:
        now = _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            token = await unit_of_work.identity.get_platform_access_token_by_prefix(
                public_prefix
            )
            if (
                token is None
                or not hmac.compare_digest(token.secret_digest, secret_digest)
                or token.is_revoked
                or token.expires_at <= now
            ):
                raise CredentialAuthenticationError()
            principal = PlatformTokenPrincipal(
                principal_reference=token.principal_reference,
                credential_reference=f"platform-token:{token.id}",
                scopes=frozenset(token.scopes),
                token_id=token.id,
            )
            if required_scope is not None:
                principal.require(required_scope)
            token.last_used_at = now
            await unit_of_work.commit()
            return principal

    async def create_platform_access_token(
        self,
        *,
        token: PlatformAccessToken,
    ) -> PlatformAccessToken:
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.identity.add_platform_access_token(token)
            await unit_of_work.commit()
            return token

    async def list_platform_access_tokens(self) -> list[PlatformAccessToken]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.identity.list_platform_access_tokens()

    async def revoke_platform_access_token(
        self,
        *,
        token_id: UUID,
    ) -> PlatformAccessToken:
        async with self._unit_of_work_factory() as unit_of_work:
            token = await unit_of_work.identity.get_platform_access_token(token_id)
            if token is None:
                raise NotFoundError("Platform access token", str(token_id))
            token.revoke()
            await unit_of_work.commit()
            return token

    async def list_workspaces(
        self, *, actor: ActorContext
    ) -> list[tuple[Workspace, WorkspaceMembership]]:
        async with self._unit_of_work_factory() as unit_of_work:
            await self._require_active_user(unit_of_work, actor.user_id)
            memberships = await unit_of_work.identity.list_memberships_for_user(
                actor.user_id
            )
            workspaces: list[tuple[Workspace, WorkspaceMembership]] = []
            for membership in memberships:
                if not membership.is_active:
                    continue
                workspace = await unit_of_work.identity.get_workspace(
                    membership.workspace_id
                )
                if workspace is not None:
                    workspaces.append((workspace, membership))
            return workspaces

    async def list_members(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
    ) -> list[tuple[User, WorkspaceMembership]]:
        async with self._unit_of_work_factory() as unit_of_work:
            await self._require_workspace_owner(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
            )
            members: list[tuple[User, WorkspaceMembership]] = []
            for membership in await unit_of_work.identity.list_memberships(
                workspace_id
            ):
                user = await unit_of_work.identity.get_user(membership.user_id)
                if user is not None:
                    members.append((user, membership))
            return members

    async def resolve_workspace_invitation_candidate(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        email: str,
    ) -> User:
        async with self._unit_of_work_factory() as unit_of_work:
            workspace = await self._require_shared_workspace_for_invitation(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
            )
            del workspace
            return await self._resolve_invitation_candidate(
                unit_of_work,
                workspace_id=workspace_id,
                email=email,
            )

    async def create_workspace_invitation(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        email: str,
        role: WorkspaceRole,
    ) -> tuple[WorkspaceInvitation, User]:
        now = _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            workspace = await self._require_shared_workspace_for_invitation(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
            )
            del workspace
            await self._expire_due_invitations(
                unit_of_work,
                await unit_of_work.identity.list_workspace_invitations(workspace_id),
                now=now,
            )
            invitee = await self._resolve_invitation_candidate(
                unit_of_work,
                workspace_id=workspace_id,
                email=email,
            )
            invitations = await unit_of_work.identity.list_workspace_invitations(
                workspace_id
            )
            if any(
                invitation.invitee_user_id == invitee.id
                and invitation.status is WorkspaceInvitationStatus.PENDING
                for invitation in invitations
            ):
                raise IdentityInvariantError(
                    "A pending invitation already exists for this recipient"
                )
            invitation = WorkspaceInvitation(
                workspace_id=workspace_id,
                invitee_user_id=invitee.id,
                invited_by_user_id=actor.user_id,
                role=WorkspaceRole(role),
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(days=7),
            )
            await unit_of_work.identity.add_workspace_invitation(invitation)
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    operation="workspace.invitation.create",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    workspace_id=workspace_id,
                    resource_type="workspace_invitation",
                    resource_id=str(invitation.id),
                )
            )
            await unit_of_work.commit()
            return invitation, invitee

    async def list_workspace_invitations(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
    ) -> list[tuple[WorkspaceInvitation, User]]:
        now = _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            await self._require_workspace_owner(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
            )
            invitations = await unit_of_work.identity.list_workspace_invitations(
                workspace_id
            )
            expired = await self._expire_due_invitations(
                unit_of_work,
                invitations,
                now=now,
            )
            if expired:
                await unit_of_work.commit()
            rows: list[tuple[WorkspaceInvitation, User]] = []
            for invitation in invitations:
                if invitation.status is not WorkspaceInvitationStatus.PENDING:
                    continue
                invitee = await unit_of_work.identity.get_user(
                    invitation.invitee_user_id
                )
                if invitee is not None:
                    rows.append((invitation, invitee))
            return rows

    async def list_my_workspace_invitations(
        self,
        *,
        actor: ActorContext,
    ) -> list[tuple[WorkspaceInvitation, Workspace, User]]:
        now = _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            await self._require_active_user(unit_of_work, actor.user_id)
            invitations = (
                await unit_of_work.identity.list_workspace_invitations_for_user(
                    actor.user_id
                )
            )
            expired = await self._expire_due_invitations(
                unit_of_work,
                invitations,
                now=now,
            )
            if expired:
                await unit_of_work.commit()
            rows: list[tuple[WorkspaceInvitation, Workspace, User]] = []
            for invitation in invitations:
                if invitation.status is not WorkspaceInvitationStatus.PENDING:
                    continue
                workspace = await unit_of_work.identity.get_workspace(
                    invitation.workspace_id
                )
                inviter = await unit_of_work.identity.get_user(
                    invitation.invited_by_user_id
                )
                if workspace is not None and inviter is not None:
                    rows.append((invitation, workspace, inviter))
            return rows

    async def accept_workspace_invitation(
        self,
        *,
        actor: ActorContext,
        invitation_id: UUID,
    ) -> WorkspaceInvitationAcceptance:
        now = _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            await self._require_active_user(unit_of_work, actor.user_id)
            invitation = await unit_of_work.identity.get_workspace_invitation(
                invitation_id
            )
            if invitation is None or invitation.invitee_user_id != actor.user_id:
                raise NotFoundError("Workspace invitation", str(invitation_id))
            workspace = (
                await unit_of_work.identity.lock_workspace_for_membership_mutation(
                    invitation.workspace_id
                )
            )
            if workspace is None:
                raise NotFoundError("Workspace", str(invitation.workspace_id))
            if invitation.expire_if_due(now=now):
                await self._audit_invitation_expiry(unit_of_work, invitation)
                await unit_of_work.commit()
                raise IdentityInvariantError("Workspace invitation has expired")
            if invitation.status is not WorkspaceInvitationStatus.PENDING:
                raise IdentityInvariantError(
                    "Workspace invitation is no longer pending"
                )
            membership = await unit_of_work.identity.get_membership(
                workspace_id=invitation.workspace_id,
                user_id=actor.user_id,
            )
            if membership is None:
                membership = WorkspaceMembership(
                    workspace_id=invitation.workspace_id,
                    user_id=actor.user_id,
                    role=invitation.role,
                )
                await unit_of_work.identity.add_membership(membership)
            elif membership.is_active:
                raise IdentityInvariantError("User is already a workspace member")
            else:
                membership.reactivate(role=invitation.role, updated_at=now)
            invitation.accept(accepted_at=now)
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    operation="workspace.invitation.accept",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    workspace_id=invitation.workspace_id,
                    resource_type="workspace_invitation",
                    resource_id=str(invitation.id),
                )
            )
            await unit_of_work.commit()
            return WorkspaceInvitationAcceptance(invitation, workspace, membership)

    async def decline_workspace_invitation(
        self,
        *,
        actor: ActorContext,
        invitation_id: UUID,
    ) -> WorkspaceInvitation:
        now = _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            await self._require_active_user(unit_of_work, actor.user_id)
            invitation = await unit_of_work.identity.get_workspace_invitation(
                invitation_id
            )
            if invitation is None or invitation.invitee_user_id != actor.user_id:
                raise NotFoundError("Workspace invitation", str(invitation_id))
            await unit_of_work.identity.lock_workspace_for_membership_mutation(
                invitation.workspace_id
            )
            if invitation.expire_if_due(now=now):
                await self._audit_invitation_expiry(unit_of_work, invitation)
                await unit_of_work.commit()
                raise IdentityInvariantError("Workspace invitation has expired")
            invitation.decline(declined_at=now)
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    operation="workspace.invitation.decline",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    workspace_id=invitation.workspace_id,
                    resource_type="workspace_invitation",
                    resource_id=str(invitation.id),
                )
            )
            await unit_of_work.commit()
            return invitation

    async def cancel_workspace_invitation(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        invitation_id: UUID,
    ) -> WorkspaceInvitation:
        now = _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            await self._require_workspace_owner(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
            )
            invitation = await unit_of_work.identity.get_workspace_invitation(
                invitation_id
            )
            if invitation is None or invitation.workspace_id != workspace_id:
                raise NotFoundError("Workspace invitation", str(invitation_id))
            if invitation.expire_if_due(now=now):
                await self._audit_invitation_expiry(unit_of_work, invitation)
                await unit_of_work.commit()
                raise IdentityInvariantError("Workspace invitation has expired")
            invitation.cancel(cancelled_at=now)
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    operation="workspace.invitation.cancel",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    workspace_id=workspace_id,
                    resource_type="workspace_invitation",
                    resource_id=str(invitation.id),
                )
            )
            await unit_of_work.commit()
            return invitation

    async def create_personal_access_token(
        self,
        *,
        actor: ActorContext,
        token: PersonalAccessToken,
    ) -> PersonalAccessToken:
        async with self._unit_of_work_factory() as unit_of_work:
            await self._require_active_user(unit_of_work, actor.user_id)
            if token.user_id != actor.user_id:
                raise IdentityInvariantError(
                    "PAT owner must match the authenticated user"
                )
            if not set(token.scopes).issubset(PAT_ALLOWED_CAPABILITIES):
                raise IdentityInvariantError(
                    "Personal access token scope is not available"
                )
            membership = await self._require_membership(
                unit_of_work,
                workspace_id=token.workspace_id,
                user_id=actor.user_id,
            )
            if not set(token.scopes).issubset(membership.capabilities):
                raise CapabilityDeniedError(
                    capability="personal_access_token_scope",
                    workspace_id=token.workspace_id,
                    user_id=actor.user_id,
                )
            await unit_of_work.identity.add_personal_access_token(token)
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    operation="credential.pat.create",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    workspace_id=token.workspace_id,
                    resource_type="personal_access_token",
                    resource_id=str(token.id),
                )
            )
            await unit_of_work.commit()
            return token

    async def list_personal_access_tokens(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
    ) -> list[PersonalAccessToken]:
        async with self._unit_of_work_factory() as unit_of_work:
            await self._require_active_user(unit_of_work, actor.user_id)
            membership = await self._require_membership(
                unit_of_work,
                workspace_id=workspace_id,
                user_id=actor.user_id,
            )
            if not membership.grants(WorkspaceCapability.VIEW_GRAPH):
                raise CapabilityDeniedError(
                    capability=WorkspaceCapability.VIEW_GRAPH.value,
                    workspace_id=workspace_id,
                    user_id=actor.user_id,
                )
            return await unit_of_work.identity.list_personal_access_tokens_for_user_workspace(
                user_id=actor.user_id,
                workspace_id=workspace_id,
            )

    async def revoke_personal_access_token(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        token_id: UUID,
    ) -> PersonalAccessToken:
        async with self._unit_of_work_factory() as unit_of_work:
            await self._require_active_user(unit_of_work, actor.user_id)
            membership = await self._require_membership(
                unit_of_work,
                workspace_id=workspace_id,
                user_id=actor.user_id,
            )
            if not membership.grants(WorkspaceCapability.VIEW_GRAPH):
                raise CapabilityDeniedError(
                    capability=WorkspaceCapability.VIEW_GRAPH.value,
                    workspace_id=workspace_id,
                    user_id=actor.user_id,
                )
            token = await unit_of_work.identity.get_personal_access_token_for_user_workspace(
                token_id=token_id,
                user_id=actor.user_id,
                workspace_id=workspace_id,
            )
            if token is None:
                raise NotFoundError("Personal access token", str(token_id))
            token.revoke()
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    workspace_id=workspace_id,
                    resource_type="personal_access_token",
                    resource_id=str(token.id),
                    operation="credential.pat.revoke",
                    outcome=SecurityAuditOutcome.SUCCESS,
                )
            )
            await unit_of_work.commit()
            return token

    async def provision_oidc_identity(
        self,
        *,
        issuer: str,
        subject: str,
        email: str | None,
        display_name: str | None,
        email_verified: bool = False,
    ) -> IdentityProvisioningResult:
        """Provision or refresh one validated OIDC identity atomically."""
        async with self._unit_of_work_factory() as unit_of_work:
            identity = await unit_of_work.identity.get_oidc_identity(
                issuer=issuer,
                subject=subject,
            )
            if identity is not None:
                user = await unit_of_work.identity.get_user(identity.user_id)
                if user is None:
                    raise IdentityInvariantError(
                        f"OIDC identity {identity.id} references a missing user"
                    )
                if not user.active:
                    raise UserDisabledError(f"User {user.id} is disabled")
                user.update_profile(
                    email=email,
                    email_verified=email_verified,
                    display_name=display_name,
                )
                personal_workspace = await unit_of_work.identity.get_personal_workspace(
                    user.id
                )
                if personal_workspace is None:
                    personal_workspace = Workspace.personal(owner_user_id=user.id)
                    await unit_of_work.identity.add_workspace(personal_workspace)
                    await unit_of_work.identity.add_membership(
                        WorkspaceMembership(
                            workspace_id=personal_workspace.id,
                            user_id=user.id,
                            role=WorkspaceRole.OWNER,
                        )
                    )
                await self._ensure_domain_workspace_memberships(unit_of_work, user)
                await unit_of_work.commit()
                return IdentityProvisioningResult(
                    user=user,
                    oidc_identity=identity,
                    personal_workspace=personal_workspace,
                )

            user = User(
                email=email,
                email_verified=email_verified,
                display_name=display_name,
            )
            identity = OidcIdentity(
                user_id=user.id,
                issuer=issuer,
                subject=subject,
            )
            personal_workspace = Workspace.personal(owner_user_id=user.id)
            personal_membership = WorkspaceMembership(
                workspace_id=personal_workspace.id,
                user_id=user.id,
                role=WorkspaceRole.OWNER,
            )
            await unit_of_work.identity.add_user(user)
            await unit_of_work.identity.add_oidc_identity(identity)
            await unit_of_work.identity.add_workspace(personal_workspace)
            await unit_of_work.identity.add_membership(personal_membership)

            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.UNAUTHENTICATED,
                    operation="oidc.identity.provision",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    workspace_id=personal_workspace.id,
                    resource_type="user",
                    resource_id=str(user.id),
                )
            )
            await self._ensure_domain_workspace_memberships(unit_of_work, user)
            await unit_of_work.commit()
        return IdentityProvisioningResult(
            user=user,
            oidc_identity=identity,
            personal_workspace=personal_workspace,
        )

    async def create_shared_workspace(
        self,
        *,
        actor: ActorContext,
        slug: str,
        name: str,
    ) -> Workspace:
        normalized_slug = normalize_workspace_slug(slug)
        async with self._unit_of_work_factory() as unit_of_work:
            existing = await unit_of_work.identity.lock_workspace_by_slug_for_membership_mutation(
                normalized_slug
            )
            if existing is not None:
                raise IdentityInvariantError("Workspace slug is already in use")
            await self._require_active_user(unit_of_work, actor.user_id)
            workspace = Workspace.shared(slug=normalized_slug, name=name)
            await unit_of_work.identity.add_workspace(workspace)
            await unit_of_work.identity.add_membership(
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=actor.user_id,
                    role=WorkspaceRole.OWNER,
                )
            )
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    operation="workspace.create",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    workspace_id=workspace.id,
                )
            )
            await unit_of_work.commit()
        return workspace

    async def authorize(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        capability: WorkspaceCapability,
    ) -> WorkspaceAccess:
        async with self._unit_of_work_factory() as unit_of_work:
            return await authorize_workspace(
                unit_of_work.identity,
                actor=actor,
                workspace_id=workspace_id,
                capability=capability,
            )

    async def add_or_reactivate_member(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        user_id: UUID,
        role: WorkspaceRole,
    ) -> WorkspaceMembership:
        role = WorkspaceRole(role)
        async with self._unit_of_work_factory() as unit_of_work:
            workspace = (
                await unit_of_work.identity.lock_workspace_for_membership_mutation(
                    workspace_id
                )
            )
            if workspace is None:
                raise NotFoundError("Workspace", str(workspace_id))
            await self._require_workspace_owner(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
            )
            if (
                workspace.kind is WorkspaceKind.PERSONAL
                and user_id != workspace.personal_owner_user_id
            ):
                raise IdentityInvariantError(
                    "Personal workspace cannot accept another membership"
                )
            if (
                workspace.kind is WorkspaceKind.PERSONAL
                and role is not WorkspaceRole.OWNER
            ):
                raise IdentityInvariantError(
                    "Personal workspace membership must remain owner-authorized"
                )
            target_user = await self._require_active_user(unit_of_work, user_id)
            del target_user
            membership = await unit_of_work.identity.get_membership(
                workspace_id=workspace_id,
                user_id=user_id,
            )
            if membership is None:
                membership = WorkspaceMembership(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    role=role,
                )
                await unit_of_work.identity.add_membership(membership)
            elif membership.is_active:
                memberships = await unit_of_work.identity.list_memberships(workspace_id)
                ensure_last_owner_can_change(
                    workspace=workspace,
                    memberships=memberships,
                    target=membership,
                    replacement_role=role,
                )
                membership.change_role(role)
                await self._revoke_workspace_pats_exceeding_capabilities(
                    unit_of_work,
                    actor=actor,
                    user_id=user_id,
                    workspace_id=workspace_id,
                    remaining_capabilities=membership.capabilities,
                )
            else:
                membership.reactivate(role=role)
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    operation="workspace.membership.upsert",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    workspace_id=workspace_id,
                    resource_type="user",
                    resource_id=str(user_id),
                )
            )
            await unit_of_work.commit()
        return membership

    async def change_member_role(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        user_id: UUID,
        role: WorkspaceRole,
    ) -> WorkspaceMemberResult:
        role = WorkspaceRole(role)
        async with self._unit_of_work_factory() as unit_of_work:
            workspace = (
                await unit_of_work.identity.lock_workspace_for_membership_mutation(
                    workspace_id
                )
            )
            if workspace is None:
                raise NotFoundError("Workspace", str(workspace_id))
            await self._require_workspace_owner(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
            )
            membership = await self._require_membership(
                unit_of_work,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            user = await unit_of_work.identity.get_user(user_id)
            if user is None:
                raise NotFoundError("User", str(user_id))
            memberships = await unit_of_work.identity.list_memberships(workspace_id)
            ensure_last_owner_can_change(
                workspace=workspace,
                memberships=memberships,
                target=membership,
                replacement_role=role,
            )
            membership.change_role(role)
            await self._revoke_workspace_pats_exceeding_capabilities(
                unit_of_work,
                actor=actor,
                user_id=user_id,
                workspace_id=workspace_id,
                remaining_capabilities=membership.capabilities,
            )
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    operation="workspace.membership.role_change",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    workspace_id=workspace_id,
                    resource_type="user",
                    resource_id=str(user_id),
                )
            )
            await unit_of_work.commit()
        return WorkspaceMemberResult(user, membership)

    async def remove_member(
        self,
        *,
        actor: ActorContext,
        workspace_id: UUID,
        user_id: UUID,
    ) -> WorkspaceMembership:
        async with self._unit_of_work_factory() as unit_of_work:
            workspace = (
                await unit_of_work.identity.lock_workspace_for_membership_mutation(
                    workspace_id
                )
            )
            if workspace is None:
                raise NotFoundError("Workspace", str(workspace_id))
            await self._require_workspace_owner(
                unit_of_work,
                actor=actor,
                workspace_id=workspace_id,
            )
            membership = await self._require_membership(
                unit_of_work,
                workspace_id=workspace_id,
                user_id=user_id,
            )
            memberships = await unit_of_work.identity.list_memberships(workspace_id)
            ensure_last_owner_can_change(
                workspace=workspace,
                memberships=memberships,
                target=membership,
                removing=True,
            )
            membership.revoke()
            await self._revoke_workspace_pats_exceeding_capabilities(
                unit_of_work,
                actor=actor,
                user_id=user_id,
                workspace_id=workspace_id,
                remaining_capabilities=membership.capabilities,
            )
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                    user_id=actor.user_id,
                    credential_reference=actor.credential_reference,
                    operation="workspace.membership.remove",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    workspace_id=workspace_id,
                    resource_type="user",
                    resource_id=str(user_id),
                )
            )
            await unit_of_work.commit()
        return membership

    async def disable_user(self, *, user_id: UUID) -> User:
        async with self._unit_of_work_factory() as unit_of_work:
            user = await self._require_user(unit_of_work, user_id)
            user.active = False
            user.updated_at = _utc_now()
            for session in await unit_of_work.identity.list_auth_sessions_for_user(
                user_id
            ):
                if session.is_revoked:
                    continue
                session.revoke()
                await unit_of_work.security_audit.add(
                    SecurityAuditEvent(
                        actor_kind=SecurityAuditActorKind.SYSTEM,
                        operation="credential.session.revoke",
                        outcome=SecurityAuditOutcome.SUCCESS,
                        resource_type="auth_session",
                        resource_id=str(session.id),
                    )
                )
            for (
                token
            ) in await unit_of_work.identity.list_personal_access_tokens_for_user(
                user_id
            ):
                await self._revoke_personal_access_token(
                    unit_of_work,
                    token,
                    actor_kind=SecurityAuditActorKind.SYSTEM,
                )
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.SYSTEM,
                    operation="user.disable",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    resource_type="user",
                    resource_id=str(user_id),
                )
            )
            await unit_of_work.commit()
        return user

    async def _revoke_personal_access_token(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        token: PersonalAccessToken,
        *,
        actor_kind: SecurityAuditActorKind,
        actor: ActorContext | None = None,
    ) -> None:
        if token.is_revoked:
            return
        token.revoke()
        await unit_of_work.security_audit.add(
            SecurityAuditEvent(
                actor_kind=actor_kind,
                user_id=None if actor is None else actor.user_id,
                credential_reference=(
                    None if actor is None else actor.credential_reference
                ),
                workspace_id=token.workspace_id,
                resource_type="personal_access_token",
                resource_id=str(token.id),
                operation="credential.pat.revoke",
                outcome=SecurityAuditOutcome.SUCCESS,
            )
        )

    async def _revoke_workspace_pats_exceeding_capabilities(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        *,
        actor: ActorContext,
        user_id: UUID,
        workspace_id: UUID,
        remaining_capabilities: frozenset[WorkspaceCapability],
    ) -> None:
        tokens = (
            await unit_of_work.identity.list_personal_access_tokens_for_user_workspace(
                user_id=user_id,
                workspace_id=workspace_id,
            )
        )
        for token in tokens:
            if set(token.scopes).issubset(remaining_capabilities):
                continue
            await self._revoke_personal_access_token(
                unit_of_work,
                token,
                actor_kind=SecurityAuditActorKind.AUTHENTICATED,
                actor=actor,
            )

    async def _ensure_domain_workspace_memberships(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        user: User,
    ) -> None:
        if (
            not self._domain_workspace_grants
            or not user.email_verified
            or user.normalized_email is None
        ):
            return
        for grant in self._domain_workspace_grants:
            if not grant.matches_normalized_email(user.normalized_email):
                continue
            workspace = (
                await unit_of_work.identity.lock_workspace_by_slug_for_membership_mutation(
                    grant.workspace_slug
                )
            )
            if workspace is None:
                workspace = Workspace.shared(
                    slug=grant.workspace_slug,
                    name=grant.workspace_name,
                )
                await unit_of_work.identity.add_workspace(workspace)
            elif workspace.kind is not WorkspaceKind.SHARED:
                raise IdentityInvariantError(
                    f"OIDC domain workspace slug {grant.workspace_slug!r} is not shared"
                )
            membership = await unit_of_work.identity.get_membership(
                workspace_id=workspace.id,
                user_id=user.id,
            )
            if membership is not None:
                continue
            owner_count = await unit_of_work.identity.count_active_owners(workspace.id)
            role = (
                WorkspaceRole.OWNER if owner_count == 0 else WorkspaceRole.EDITOR
            )
            await unit_of_work.identity.add_membership(
                WorkspaceMembership(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role=role,
                )
            )
            await unit_of_work.security_audit.add(
                SecurityAuditEvent(
                    actor_kind=SecurityAuditActorKind.UNAUTHENTICATED,
                    operation="oidc.domain_workspace.grant",
                    outcome=SecurityAuditOutcome.SUCCESS,
                    workspace_id=workspace.id,
                    resource_type="user",
                    resource_id=str(user.id),
                )
            )

    async def _require_shared_workspace_for_invitation(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        *,
        actor: ActorContext,
        workspace_id: UUID,
    ) -> Workspace:
        workspace = await unit_of_work.identity.lock_workspace_for_membership_mutation(
            workspace_id
        )
        if workspace is None:
            raise NotFoundError("Workspace", str(workspace_id))
        await self._require_workspace_owner(
            unit_of_work,
            actor=actor,
            workspace_id=workspace_id,
        )
        if workspace.kind is not WorkspaceKind.SHARED:
            raise IdentityInvariantError("Personal workspace cannot accept invitations")
        return workspace

    async def _resolve_invitation_candidate(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        *,
        workspace_id: UUID,
        email: str,
    ) -> User:
        candidates = await unit_of_work.identity.find_active_users_by_verified_email(
            normalize_user_email(email)
        )
        if len(candidates) != 1:
            raise NotFoundError("Invitation recipient", "eligible")
        invitee = candidates[0]
        membership = await unit_of_work.identity.get_membership(
            workspace_id=workspace_id,
            user_id=invitee.id,
        )
        if membership is not None and membership.is_active:
            raise IdentityInvariantError("User is already a workspace member")
        return invitee

    async def _expire_due_invitations(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        invitations: Sequence[WorkspaceInvitation],
        *,
        now: datetime,
    ) -> int:
        expired = 0
        for invitation in invitations:
            if not invitation.expire_if_due(now=now):
                continue
            expired += 1
            await self._audit_invitation_expiry(unit_of_work, invitation)
        return expired

    async def _audit_invitation_expiry(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        invitation: WorkspaceInvitation,
    ) -> None:
        await unit_of_work.security_audit.add(
            SecurityAuditEvent(
                actor_kind=SecurityAuditActorKind.SYSTEM,
                operation="workspace.invitation.expire",
                outcome=SecurityAuditOutcome.SUCCESS,
                workspace_id=invitation.workspace_id,
                resource_type="workspace_invitation",
                resource_id=str(invitation.id),
            )
        )

    async def _require_active_user(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        user_id: UUID,
    ) -> User:
        user = await self._require_user(unit_of_work, user_id)
        if not user.active:
            raise UserDisabledError(f"User {user.id} is disabled")
        return user

    async def _require_user(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        user_id: UUID,
    ) -> User:
        user = await unit_of_work.identity.get_user(user_id)
        if user is None:
            raise NotFoundError("User", str(user_id))
        return user

    async def _require_workspace(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        workspace_id: UUID,
    ) -> Workspace:
        workspace = await unit_of_work.identity.get_workspace(workspace_id)
        if workspace is None:
            raise NotFoundError("Workspace", str(workspace_id))
        return workspace

    async def _require_membership(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        *,
        workspace_id: UUID,
        user_id: UUID,
    ) -> WorkspaceMembership:
        membership = await unit_of_work.identity.get_membership(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if membership is None or not membership.is_active:
            raise NotFoundError("Workspace membership", f"{workspace_id}/{user_id}")
        return membership

    async def _require_workspace_owner(
        self,
        unit_of_work: IdentityUnitOfWorkPort,
        *,
        actor: ActorContext,
        workspace_id: UUID,
    ) -> WorkspaceMembership:
        await self._require_active_user(unit_of_work, actor.user_id)
        membership = await self._require_membership(
            unit_of_work,
            workspace_id=workspace_id,
            user_id=actor.user_id,
        )
        if not membership.grants(WorkspaceCapability.MANAGE_MEMBERS):
            raise CapabilityDeniedError(
                capability=WorkspaceCapability.MANAGE_MEMBERS.value,
                workspace_id=workspace_id,
                user_id=actor.user_id,
            )
        return membership


__all__ = ["IdentityService", "authorize_workspace", "authorize_workspaces"]
