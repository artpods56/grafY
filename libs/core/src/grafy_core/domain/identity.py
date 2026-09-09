from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
import re
from uuid import UUID, uuid4

from grafy_core.domain.errors import (
    CapabilityDeniedError,
    IdentityInvariantError,
    LastWorkspaceOwnerError,
)


class WorkspaceKind(StrEnum):
    PERSONAL = "personal"
    SHARED = "shared"


class WorkspaceRole(StrEnum):
    VIEWER = "viewer"
    EDITOR = "editor"
    OWNER = "owner"


class WorkspaceInvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class WorkspaceCapability(StrEnum):
    VIEW_GRAPH = "view_graph"
    VIEW_ARTIFACTS = "view_artifacts"
    VIEW_MATERIALIZATIONS = "view_materializations"
    VIEW_HISTORY = "view_history"
    VIEW_EXECUTION = "view_execution"
    JOIN_GRAPH_ROOM = "join_graph_room"
    PUBLISH_PRESENCE = "publish_presence"
    CREATE_GRAPH = "create_graph"
    EDIT_GRAPH = "edit_graph"
    CHECKPOINT_GRAPH = "checkpoint_graph"
    EXECUTE_GRAPH = "execute_graph"
    CANCEL_EXECUTION = "cancel_execution"
    PUBLISH_PLUGIN = "publish_plugin"
    PUBLISH_MODULE = "publish_module"
    MANAGE_MODULE_LIBRARY = "manage_module_library"
    CREATE_TEMPLATE = "create_template"
    MANAGE_TEMPLATE_LIBRARY = "manage_template_library"
    MANAGE_SECRETS = "manage_secrets"
    DELETE_GRAPH = "delete_graph"
    MANAGE_MEMBERS = "manage_members"
    RENAME_WORKSPACE = "rename_workspace"


class PlatformTokenScope(StrEnum):
    PUBLISH_GLOBAL = "plugin.publish_global"
    PROMOTE_GLOBAL = "plugin.promote_global"
    REVOKE_GLOBAL = "plugin.revoke_global"


_SLUG_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$")
_ROLE_CAPABILITIES: dict[WorkspaceRole, frozenset[WorkspaceCapability]] = {
    WorkspaceRole.VIEWER: frozenset(
        {
            WorkspaceCapability.VIEW_GRAPH,
            WorkspaceCapability.VIEW_ARTIFACTS,
            WorkspaceCapability.VIEW_MATERIALIZATIONS,
            WorkspaceCapability.VIEW_HISTORY,
            WorkspaceCapability.VIEW_EXECUTION,
            WorkspaceCapability.JOIN_GRAPH_ROOM,
            WorkspaceCapability.PUBLISH_PRESENCE,
        }
    ),
    WorkspaceRole.EDITOR: frozenset(
        {
            WorkspaceCapability.VIEW_GRAPH,
            WorkspaceCapability.VIEW_ARTIFACTS,
            WorkspaceCapability.VIEW_MATERIALIZATIONS,
            WorkspaceCapability.VIEW_HISTORY,
            WorkspaceCapability.VIEW_EXECUTION,
            WorkspaceCapability.JOIN_GRAPH_ROOM,
            WorkspaceCapability.PUBLISH_PRESENCE,
            WorkspaceCapability.CREATE_GRAPH,
            WorkspaceCapability.EDIT_GRAPH,
            WorkspaceCapability.CHECKPOINT_GRAPH,
            WorkspaceCapability.EXECUTE_GRAPH,
            WorkspaceCapability.CANCEL_EXECUTION,
            WorkspaceCapability.PUBLISH_MODULE,
            WorkspaceCapability.CREATE_TEMPLATE,
        }
    ),
    WorkspaceRole.OWNER: frozenset(WorkspaceCapability),
}
PAT_ALLOWED_CAPABILITIES = frozenset(
    {
        WorkspaceCapability.VIEW_GRAPH,
        WorkspaceCapability.VIEW_ARTIFACTS,
        WorkspaceCapability.VIEW_MATERIALIZATIONS,
        WorkspaceCapability.VIEW_HISTORY,
        WorkspaceCapability.VIEW_EXECUTION,
        WorkspaceCapability.CREATE_GRAPH,
        WorkspaceCapability.EDIT_GRAPH,
        WorkspaceCapability.CHECKPOINT_GRAPH,
        WorkspaceCapability.EXECUTE_GRAPH,
        WorkspaceCapability.CANCEL_EXECUTION,
        WorkspaceCapability.PUBLISH_PLUGIN,
        WorkspaceCapability.PUBLISH_MODULE,
        WorkspaceCapability.CREATE_TEMPLATE,
        WorkspaceCapability.MANAGE_SECRETS,
    }
)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_aware(value: datetime, label: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")


def _require_nonempty(value: str, label: str, maximum: int) -> str:
    if value == "" or value.strip() == "":
        raise ValueError(f"{label} must not be blank")
    if len(value) > maximum:
        raise ValueError(f"{label} must be at most {maximum} characters")
    return value


def normalize_workspace_slug(value: str) -> str:
    slug = value.strip().lower()
    if not _SLUG_PATTERN.fullmatch(slug):
        raise ValueError(
            "Workspace slug must contain 1-80 lowercase letters, numbers, or "
            "internal hyphens"
        )
    return slug


def capabilities_for_role(role: WorkspaceRole) -> frozenset[WorkspaceCapability]:
    return _ROLE_CAPABILITIES[role]


def normalize_user_email(value: str) -> str:
    return _require_nonempty(value.strip(), "User email", 320).lower()


@dataclass
class User:
    id: UUID = field(default_factory=uuid4)
    email: str | None = None
    normalized_email: str | None = None
    email_verified: bool = False
    display_name: str | None = None
    active: bool = True
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if self.email is not None:
            self.email = _require_nonempty(self.email.strip(), "User email", 320)
            self.normalized_email = normalize_user_email(self.email)
        else:
            self.normalized_email = None
            self.email_verified = False
        if self.display_name is not None:
            self.display_name = _require_nonempty(
                self.display_name.strip(), "User display name", 160
            )
        _require_aware(self.created_at, "User creation timestamp")
        _require_aware(self.updated_at, "User update timestamp")

    @property
    def is_active(self) -> bool:
        return self.active

    def update_profile(
        self,
        *,
        email: str | None,
        email_verified: bool,
        display_name: str | None,
        updated_at: datetime | None = None,
    ) -> None:
        self.email = (
            None
            if email is None
            else _require_nonempty(email.strip(), "User email", 320)
        )
        self.normalized_email = (
            None if self.email is None else normalize_user_email(self.email)
        )
        self.email_verified = email_verified if self.email is not None else False
        self.display_name = (
            None
            if display_name is None
            else _require_nonempty(display_name.strip(), "User display name", 160)
        )
        self.updated_at = updated_at or _utc_now()
        _require_aware(self.updated_at, "User update timestamp")


@dataclass
class OidcIdentity:
    user_id: UUID
    issuer: str
    subject: str
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        _require_nonempty(self.issuer, "OIDC issuer", 2048)
        _require_nonempty(self.subject, "OIDC subject", 512)
        _require_aware(self.created_at, "OIDC identity creation timestamp")
        _require_aware(self.updated_at, "OIDC identity update timestamp")


@dataclass
class Workspace:
    slug: str
    name: str
    kind: WorkspaceKind
    id: UUID = field(default_factory=uuid4)
    personal_owner_user_id: UUID | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.kind = WorkspaceKind(self.kind)
        self.slug = normalize_workspace_slug(self.slug)
        self.name = _require_nonempty(self.name.strip(), "Workspace name", 160)
        if self.kind is WorkspaceKind.PERSONAL and self.personal_owner_user_id is None:
            raise IdentityInvariantError(
                "Personal workspace must have a personal owner"
            )
        if (
            self.kind is WorkspaceKind.SHARED
            and self.personal_owner_user_id is not None
        ):
            raise IdentityInvariantError(
                "Shared workspace cannot have a personal owner"
            )
        _require_aware(self.created_at, "Workspace creation timestamp")
        _require_aware(self.updated_at, "Workspace update timestamp")

    @classmethod
    def personal(cls, *, owner_user_id: UUID, name: str = "Personal") -> "Workspace":
        return cls(
            slug=owner_user_id.hex,
            name=name,
            kind=WorkspaceKind.PERSONAL,
            personal_owner_user_id=owner_user_id,
        )

    @classmethod
    def shared(cls, *, slug: str, name: str) -> "Workspace":
        return cls(slug=slug, name=name, kind=WorkspaceKind.SHARED)


@dataclass(frozen=True)
class OidcDomainWorkspaceGrant:
    """Deployment grant: a verified email domain joins one shared Workspace."""

    email_domain: str
    workspace_slug: str
    workspace_name: str

    def __post_init__(self) -> None:
        domain = self.email_domain.strip().lower()
        if (
            not domain
            or "@" in domain
            or "." not in domain
            or any(part == "" for part in domain.split("."))
        ):
            raise ValueError("OIDC domain workspace grant needs a DNS email domain")
        object.__setattr__(self, "email_domain", domain)
        object.__setattr__(
            self, "workspace_slug", normalize_workspace_slug(self.workspace_slug)
        )
        name = self.workspace_name.strip() or self.workspace_slug
        object.__setattr__(
            self,
            "workspace_name",
            _require_nonempty(name, "Workspace name", 160),
        )

    def matches_normalized_email(self, normalized_email: str) -> bool:
        _, separator, domain = normalized_email.rpartition("@")
        return bool(separator) and domain == self.email_domain


def parse_oidc_domain_workspace_grants(
    value: str | Sequence[str],
) -> tuple[OidcDomainWorkspaceGrant, ...]:
    """Parse `domain:slug` or `domain:slug:name` grants from deployment config."""

    if isinstance(value, str):
        items = [item.strip() for item in value.split(",") if item.strip()]
    else:
        items = [str(item).strip() for item in value if str(item).strip()]
    grants: list[OidcDomainWorkspaceGrant] = []
    seen_domains: set[str] = set()
    for item in items:
        fields = item.split(":")
        if len(fields) not in {2, 3}:
            raise ValueError(
                "OIDC domain workspace grant must be domain:slug or domain:slug:name"
            )
        domain, slug, *rest = fields
        grant = OidcDomainWorkspaceGrant(
            email_domain=domain,
            workspace_slug=slug,
            workspace_name=rest[0] if rest else slug,
        )
        if grant.email_domain in seen_domains:
            raise ValueError(
                f"duplicate OIDC domain workspace grant for {grant.email_domain}"
            )
        seen_domains.add(grant.email_domain)
        grants.append(grant)
    return tuple(grants)


@dataclass
class WorkspaceMembership:
    workspace_id: UUID
    user_id: UUID
    role: WorkspaceRole
    authorization_version: int = 1
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.role = WorkspaceRole(self.role)
        if self.authorization_version < 1:
            raise ValueError("Membership authorization version must be positive")
        _require_aware(self.created_at, "Membership creation timestamp")
        _require_aware(self.updated_at, "Membership update timestamp")
        if self.revoked_at is not None:
            _require_aware(self.revoked_at, "Membership revocation timestamp")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    @property
    def capabilities(self) -> frozenset[WorkspaceCapability]:
        if not self.is_active:
            return frozenset()
        return capabilities_for_role(self.role)

    def grants(self, capability: WorkspaceCapability) -> bool:
        return capability in self.capabilities

    def change_role(
        self,
        role: WorkspaceRole,
        *,
        updated_at: datetime | None = None,
    ) -> None:
        if self.role is not role:
            self.role = role
            self.authorization_version += 1
        self.updated_at = updated_at or _utc_now()

    def revoke(self, *, revoked_at: datetime | None = None) -> None:
        if self.revoked_at is None:
            self.revoked_at = revoked_at or _utc_now()
            self.authorization_version += 1
        self.updated_at = revoked_at or _utc_now()

    def reactivate(
        self,
        *,
        role: WorkspaceRole,
        updated_at: datetime | None = None,
    ) -> None:
        self.role = role
        self.revoked_at = None
        self.authorization_version += 1
        self.updated_at = updated_at or _utc_now()


@dataclass
class WorkspaceInvitation:
    workspace_id: UUID
    invitee_user_id: UUID
    invited_by_user_id: UUID
    role: WorkspaceRole
    expires_at: datetime
    id: UUID = field(default_factory=uuid4)
    status: WorkspaceInvitationStatus = WorkspaceInvitationStatus.PENDING
    resolved_at: datetime | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.role = WorkspaceRole(self.role)
        self.status = WorkspaceInvitationStatus(self.status)
        _require_aware(self.expires_at, "Workspace invitation expiry timestamp")
        _require_aware(self.created_at, "Workspace invitation creation timestamp")
        _require_aware(self.updated_at, "Workspace invitation update timestamp")
        if self.resolved_at is not None:
            _require_aware(
                self.resolved_at,
                "Workspace invitation resolution timestamp",
            )
        if self.expires_at <= self.created_at:
            raise ValueError("Workspace invitation expiry must follow creation")
        if (
            self.status is WorkspaceInvitationStatus.PENDING
            and self.resolved_at is not None
        ):
            raise ValueError("Pending workspace invitation cannot be resolved")
        if (
            self.status is not WorkspaceInvitationStatus.PENDING
            and self.resolved_at is None
        ):
            raise ValueError("Resolved workspace invitation needs a timestamp")

    def expire_if_due(self, *, now: datetime) -> bool:
        _require_aware(now, "Workspace invitation expiry check timestamp")
        if (
            self.status is not WorkspaceInvitationStatus.PENDING
            or now < self.expires_at
        ):
            return False
        self.status = WorkspaceInvitationStatus.EXPIRED
        self.resolved_at = now
        self.updated_at = now
        return True

    def accept(self, *, accepted_at: datetime | None = None) -> None:
        self._resolve(WorkspaceInvitationStatus.ACCEPTED, accepted_at or _utc_now())

    def decline(self, *, declined_at: datetime | None = None) -> None:
        self._resolve(WorkspaceInvitationStatus.DECLINED, declined_at or _utc_now())

    def cancel(self, *, cancelled_at: datetime | None = None) -> None:
        self._resolve(WorkspaceInvitationStatus.CANCELLED, cancelled_at or _utc_now())

    def _resolve(
        self, status: WorkspaceInvitationStatus, resolved_at: datetime
    ) -> None:
        _require_aware(resolved_at, "Workspace invitation resolution timestamp")
        if self.status is not WorkspaceInvitationStatus.PENDING:
            raise IdentityInvariantError("Workspace invitation is no longer pending")
        if resolved_at >= self.expires_at:
            self.expire_if_due(now=resolved_at)
            raise IdentityInvariantError("Workspace invitation has expired")
        self.status = status
        self.resolved_at = resolved_at
        self.updated_at = resolved_at


@dataclass
class OidcLoginTransaction:
    state_digest: bytes = field(repr=False)
    nonce_digest: bytes = field(repr=False)
    encrypted_pkce_verifier: bytes = field(repr=False)
    pkce_key_version: int
    return_path: str = field(repr=False)
    expires_at: datetime
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utc_now)
    consumed_at: datetime | None = None

    def __post_init__(self) -> None:
        if len(self.state_digest) == 0 or len(self.nonce_digest) == 0:
            raise ValueError("OIDC transaction digests must not be empty")
        if len(self.encrypted_pkce_verifier) == 0:
            raise ValueError("OIDC transaction verifier must not be empty")
        if self.pkce_key_version < 1:
            raise ValueError("OIDC transaction PKCE key version must be positive")
        _require_nonempty(self.return_path, "OIDC transaction return path", 2048)
        _require_aware(self.created_at, "OIDC transaction creation timestamp")
        _require_aware(self.expires_at, "OIDC transaction expiry timestamp")
        if self.consumed_at is not None:
            _require_aware(self.consumed_at, "OIDC transaction consumption timestamp")

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    def consume(self, *, consumed_at: datetime | None = None) -> None:
        if self.is_consumed:
            raise IdentityInvariantError("OIDC login transaction was already consumed")
        self.consumed_at = consumed_at or _utc_now()


@dataclass
class AuthSession:
    user_id: UUID
    secret_digest: bytes = field(repr=False)
    csrf_digest: bytes = field(repr=False)
    expires_at: datetime
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utc_now)
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if len(self.secret_digest) == 0 or len(self.csrf_digest) == 0:
            raise ValueError("Auth session digests must not be empty")
        _require_aware(self.created_at, "Auth session creation timestamp")
        _require_aware(self.expires_at, "Auth session expiry timestamp")
        if self.last_used_at is not None:
            _require_aware(self.last_used_at, "Auth session last-used timestamp")
        if self.revoked_at is not None:
            _require_aware(self.revoked_at, "Auth session revocation timestamp")

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def revoke(self, *, revoked_at: datetime | None = None) -> None:
        self.revoked_at = revoked_at or _utc_now()


@dataclass
class PersonalAccessToken:
    user_id: UUID
    workspace_id: UUID
    public_prefix: str
    secret_digest: bytes = field(repr=False)
    label: str
    scopes: tuple[WorkspaceCapability, ...]
    expires_at: datetime
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utc_now)
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        self.scopes = tuple(WorkspaceCapability(scope) for scope in self.scopes)
        _require_nonempty(self.public_prefix, "Personal access token prefix", 32)
        if len(self.secret_digest) == 0:
            raise ValueError("Personal access token digest must not be empty")
        _require_nonempty(self.label.strip(), "Personal access token label", 160)
        if not set(self.scopes).issubset(PAT_ALLOWED_CAPABILITIES):
            raise ValueError("Personal access token scope is not available")
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("Personal access token scopes must be unique")
        for scope in self.scopes:
            _require_nonempty(scope, "Personal access token scope", 64)
        _require_aware(self.created_at, "Personal access token creation timestamp")
        _require_aware(self.expires_at, "Personal access token expiry timestamp")
        if self.last_used_at is not None:
            _require_aware(
                self.last_used_at, "Personal access token last-used timestamp"
            )
        if self.revoked_at is not None:
            _require_aware(
                self.revoked_at, "Personal access token revocation timestamp"
            )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def revoke(self, *, revoked_at: datetime | None = None) -> None:
        self.revoked_at = revoked_at or _utc_now()


@dataclass
class PlatformAccessToken:
    principal_reference: str
    public_prefix: str
    secret_digest: bytes = field(repr=False)
    label: str
    scopes: tuple[PlatformTokenScope, ...]
    expires_at: datetime
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utc_now)
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        self.scopes = tuple(PlatformTokenScope(scope) for scope in self.scopes)
        self.principal_reference = _require_nonempty(
            self.principal_reference.strip(), "Platform principal reference", 120
        )
        _require_nonempty(self.public_prefix, "Platform access token prefix", 32)
        if len(self.secret_digest) == 0:
            raise ValueError("Platform access token digest must not be empty")
        self.label = _require_nonempty(
            self.label.strip(), "Platform access token label", 160
        )
        if len(self.scopes) == 0:
            raise ValueError("Platform access token must have at least one scope")
        if len(set(self.scopes)) != len(self.scopes):
            raise ValueError("Platform access token scopes must be unique")
        _require_aware(self.created_at, "Platform access token creation timestamp")
        _require_aware(self.expires_at, "Platform access token expiry timestamp")
        if self.expires_at <= self.created_at:
            raise ValueError(
                "Platform access token expiry must be after its creation timestamp"
            )
        if self.last_used_at is not None:
            _require_aware(
                self.last_used_at, "Platform access token last-used timestamp"
            )
        if self.revoked_at is not None:
            _require_aware(
                self.revoked_at, "Platform access token revocation timestamp"
            )

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def revoke(self, *, revoked_at: datetime | None = None) -> None:
        self.revoked_at = revoked_at or _utc_now()


@dataclass(frozen=True, slots=True)
class ActorContext:
    user_id: UUID
    credential_reference: str | None = None
    credential_workspace_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class WorkspacePatPrincipal:
    actor: ActorContext
    workspace_id: UUID
    capabilities: frozenset[WorkspaceCapability]
    token_id: UUID

    def require(self, capability: WorkspaceCapability) -> None:
        if capability not in self.capabilities:
            raise CapabilityDeniedError(
                capability=capability.value,
                workspace_id=self.workspace_id,
                user_id=self.actor.user_id,
            )


@dataclass(frozen=True, slots=True)
class PlatformTokenPrincipal:
    principal_reference: str
    credential_reference: str
    scopes: frozenset[PlatformTokenScope]
    token_id: UUID

    def require(self, scope: PlatformTokenScope) -> None:
        if scope not in self.scopes:
            raise IdentityInvariantError(
                f"Platform principal {self.principal_reference!r} is not authorized "
                f"for scope {scope.value!r}"
            )


@dataclass(frozen=True, slots=True)
class WorkspaceAccess:
    actor: ActorContext
    workspace_id: UUID
    membership: WorkspaceMembership

    @property
    def capabilities(self) -> frozenset[WorkspaceCapability]:
        return self.membership.capabilities

    def require(self, capability: WorkspaceCapability) -> None:
        if not self.membership.grants(capability):
            raise CapabilityDeniedError(
                capability=capability.value,
                workspace_id=self.workspace_id,
                user_id=self.actor.user_id,
            )


@dataclass(frozen=True, slots=True)
class IdentityProvisioningResult:
    user: User
    oidc_identity: OidcIdentity
    personal_workspace: Workspace


def ensure_last_owner_can_change(
    *,
    workspace: Workspace,
    memberships: tuple[WorkspaceMembership, ...] | list[WorkspaceMembership],
    target: WorkspaceMembership,
    replacement_role: WorkspaceRole | None = None,
    removing: bool = False,
) -> None:
    if workspace.kind is WorkspaceKind.PERSONAL:
        if target.user_id != workspace.personal_owner_user_id:
            raise IdentityInvariantError(
                "Personal workspace cannot accept another membership"
            )
        if removing or replacement_role is not WorkspaceRole.OWNER:
            raise IdentityInvariantError(
                "Personal workspace owner membership cannot be removed or changed"
            )
        return

    if not target.is_active or target.role is not WorkspaceRole.OWNER:
        return
    becomes_owner = replacement_role is WorkspaceRole.OWNER and not removing
    active_owner_count = sum(
        membership.is_active and membership.role is WorkspaceRole.OWNER
        for membership in memberships
    )
    if active_owner_count <= 1 and not becomes_owner:
        raise LastWorkspaceOwnerError(
            f"Workspace {workspace.id} must retain an active owner"
        )


__all__ = [
    "ActorContext",
    "AuthSession",
    "IdentityProvisioningResult",
    "OidcIdentity",
    "OidcLoginTransaction",
    "PAT_ALLOWED_CAPABILITIES",
    "PlatformAccessToken",
    "PlatformTokenPrincipal",
    "PlatformTokenScope",
    "PersonalAccessToken",
    "User",
    "Workspace",
    "WorkspaceAccess",
    "WorkspaceCapability",
    "WorkspaceKind",
    "WorkspaceMembership",
    "WorkspacePatPrincipal",
    "WorkspaceRole",
    "capabilities_for_role",
    "ensure_last_owner_can_change",
    "normalize_workspace_slug",
]
