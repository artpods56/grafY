from typing import cast

from grafy_core.domain.identity import (
    PlatformTokenScope,
    WorkspaceCapability,
    WorkspaceInvitationStatus,
    WorkspaceKind,
    WorkspaceRole,
)
from grafy_core.domain.security_audit import (
    SecurityAuditActorKind,
    SecurityAuditOutcome,
)
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy import Uuid as SaUuid
from sqlalchemy.engine import Dialect
from sqlalchemy.types import TypeDecorator

from grafy_persistence.column_types import StringEnumType, UTCDateTime

from .base import metadata


class WorkspaceCapabilityTupleType(TypeDecorator[tuple[WorkspaceCapability, ...]]):
    impl = JSON
    cache_ok = True

    def process_bind_param(
        self,
        value: tuple[WorkspaceCapability, ...] | None,
        dialect: Dialect,
    ) -> list[str] | None:
        del dialect
        return None if value is None else [capability.value for capability in value]

    def process_result_value(
        self,
        value: object | None,
        dialect: Dialect,
    ) -> tuple[WorkspaceCapability, ...] | None:
        del dialect
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("Stored string tuple is not a JSON string list")
        items: list[str] = []
        for item in cast(list[object], value):
            if not isinstance(item, str):
                raise ValueError("Stored string tuple is not a JSON string list")
            items.append(item)
        try:
            return tuple(WorkspaceCapability(item) for item in items)
        except ValueError as exc:
            raise ValueError("Stored workspace capability is unknown") from exc


class PlatformTokenScopeTupleType(TypeDecorator[tuple[PlatformTokenScope, ...]]):
    impl = JSON
    cache_ok = True

    def process_bind_param(
        self,
        value: tuple[PlatformTokenScope, ...] | None,
        dialect: Dialect,
    ) -> list[str] | None:
        del dialect
        return None if value is None else [scope.value for scope in value]

    def process_result_value(
        self,
        value: object | None,
        dialect: Dialect,
    ) -> tuple[PlatformTokenScope, ...] | None:
        del dialect
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("Stored platform token scopes are not a JSON string list")
        items: list[str] = []
        for item in cast(list[object], value):
            if not isinstance(item, str):
                raise ValueError(
                    "Stored platform token scopes are not a JSON string list"
                )
            items.append(item)
        try:
            return tuple(PlatformTokenScope(item) for item in items)
        except ValueError as exc:
            raise ValueError("Stored platform token scope is unknown") from exc


class WorkspaceKindType(StringEnumType[WorkspaceKind]):
    impl = String(16)
    enum_type = WorkspaceKind
    cache_ok = True


class WorkspaceRoleType(StringEnumType[WorkspaceRole]):
    impl = String(16)
    enum_type = WorkspaceRole
    cache_ok = True


class WorkspaceInvitationStatusType(StringEnumType[WorkspaceInvitationStatus]):
    impl = String(16)
    enum_type = WorkspaceInvitationStatus
    cache_ok = True


class SecurityAuditActorKindType(StringEnumType[SecurityAuditActorKind]):
    impl = String(24)
    enum_type = SecurityAuditActorKind
    cache_ok = True


class SecurityAuditOutcomeType(StringEnumType[SecurityAuditOutcome]):
    impl = String(16)
    enum_type = SecurityAuditOutcome
    cache_ok = True


users = Table(
    "users",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("email", String(320), nullable=True),
    Column("normalized_email", String(320), nullable=True),
    Column("email_verified", Boolean, nullable=False, default=False),
    Column("display_name", String(160), nullable=True),
    Column("active", Boolean, nullable=False, default=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    Index("ix_users_active_updated_at", "active", "updated_at"),
    Index(
        "ix_users_invitation_email",
        "normalized_email",
        "email_verified",
        "active",
    ),
)


oidc_identities = Table(
    "oidc_identities",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("issuer", String(2048), nullable=False),
    Column("subject", String(512), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    UniqueConstraint("issuer", "subject", name="uq_oidc_identities_issuer_subject"),
    Index("ix_oidc_identities_user_id", "user_id"),
)


oidc_login_transactions = Table(
    "oidc_login_transactions",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("state_digest", LargeBinary(64), nullable=False),
    Column("nonce_digest", LargeBinary(64), nullable=False),
    Column("encrypted_pkce_verifier", LargeBinary(), nullable=False),
    Column("pkce_key_version", Integer, nullable=False),
    Column("return_path", String(2048), nullable=False),
    Column("expires_at", UTCDateTime(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("consumed_at", UTCDateTime(), nullable=True),
    CheckConstraint(
        "pkce_key_version >= 1",
        name="ck_oidc_login_transactions_pkce_key_version_positive",
    ),
    Index(
        "ix_oidc_login_transactions_expiry_consumed",
        "expires_at",
        "consumed_at",
    ),
)


workspaces = Table(
    "workspaces",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("slug", String(80), nullable=False),
    Column("name", String(160), nullable=False),
    Column("kind", WorkspaceKindType(), nullable=False),
    Column(
        "personal_owner_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    UniqueConstraint("slug", name="uq_workspaces_slug"),
    UniqueConstraint(
        "personal_owner_user_id",
        name="uq_workspaces_personal_owner_user_id",
    ),
    CheckConstraint(
        "length(slug) BETWEEN 1 AND 80 AND "
        "slug = lower(trim(slug)) AND "
        "slug NOT LIKE '-%' AND slug NOT LIKE '%-'",
        name="ck_workspaces_slug_normalized",
    ),
    CheckConstraint(
        "kind IN ('personal', 'shared')",
        name="ck_workspaces_kind_choice",
    ),
    CheckConstraint(
        "(kind = 'personal' AND personal_owner_user_id IS NOT NULL) OR "
        "(kind = 'shared' AND personal_owner_user_id IS NULL)",
        name="ck_workspaces_personal_owner_shape",
    ),
    Index("ix_workspaces_kind", "kind"),
)


workspace_memberships = Table(
    "workspace_memberships",
    metadata,
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("role", WorkspaceRoleType(), nullable=False),
    Column("authorization_version", BigInteger, nullable=False, default=1),
    Column("revoked_at", UTCDateTime(), nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    CheckConstraint(
        "role IN ('viewer', 'editor', 'owner')",
        name="ck_workspace_memberships_role_choice",
    ),
    CheckConstraint(
        "authorization_version >= 1",
        name="ck_workspace_memberships_authorization_version_positive",
    ),
    Index(
        "ix_workspace_memberships_user_active",
        "user_id",
        "revoked_at",
    ),
    Index(
        "ix_workspace_memberships_workspace_role_active",
        "workspace_id",
        "role",
        "revoked_at",
    ),
)


workspace_invitations = Table(
    "workspace_invitations",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "invitee_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "invited_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("role", WorkspaceRoleType(), nullable=False),
    Column("status", WorkspaceInvitationStatusType(), nullable=False),
    Column("expires_at", UTCDateTime(), nullable=False),
    Column("resolved_at", UTCDateTime(), nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    CheckConstraint(
        "role IN ('viewer', 'editor', 'owner')",
        name="ck_workspace_invitations_role_choice",
    ),
    CheckConstraint(
        "status IN ('pending', 'accepted', 'declined', 'cancelled', 'expired')",
        name="ck_workspace_invitations_status_choice",
    ),
    CheckConstraint(
        "(status = 'pending' AND resolved_at IS NULL) OR "
        "(status != 'pending' AND resolved_at IS NOT NULL)",
        name="ck_workspace_invitations_resolution_shape",
    ),
    CheckConstraint(
        "expires_at > created_at",
        name="ck_workspace_invitations_expiry_after_creation",
    ),
    Index(
        "ix_workspace_invitations_invitee_status_expiry",
        "invitee_user_id",
        "status",
        "expires_at",
    ),
    Index(
        "ix_workspace_invitations_workspace_status_expiry",
        "workspace_id",
        "status",
        "expires_at",
    ),
    Index(
        "uq_workspace_invitations_pending_recipient",
        "workspace_id",
        "invitee_user_id",
        unique=True,
        sqlite_where=text("status = 'pending'"),
        postgresql_where=text("status = 'pending'"),
    ),
)


auth_sessions = Table(
    "auth_sessions",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("secret_digest", LargeBinary(64), nullable=False),
    Column("csrf_digest", LargeBinary(64), nullable=False),
    Column("expires_at", UTCDateTime(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("last_used_at", UTCDateTime(), nullable=True),
    Column("revoked_at", UTCDateTime(), nullable=True),
    UniqueConstraint("secret_digest", name="uq_auth_sessions_secret_digest"),
    Index("ix_auth_sessions_user_revoked", "user_id", "revoked_at"),
    Index("ix_auth_sessions_expiry_revoked", "expires_at", "revoked_at"),
)


personal_access_tokens = Table(
    "personal_access_tokens",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("public_prefix", String(32), nullable=False),
    Column("secret_digest", LargeBinary(64), nullable=False),
    Column("label", String(160), nullable=False),
    Column("scopes", WorkspaceCapabilityTupleType(), nullable=False),
    Column("expires_at", UTCDateTime(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("last_used_at", UTCDateTime(), nullable=True),
    Column("revoked_at", UTCDateTime(), nullable=True),
    UniqueConstraint("public_prefix", name="uq_personal_access_tokens_public_prefix"),
    UniqueConstraint("secret_digest", name="uq_personal_access_tokens_secret_digest"),
    Index(
        "ix_personal_access_tokens_workspace_revoked",
        "workspace_id",
        "revoked_at",
    ),
    Index(
        "ix_personal_access_tokens_expiry_revoked",
        "expires_at",
        "revoked_at",
    ),
)


platform_access_tokens = Table(
    "platform_access_tokens",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("principal_reference", String(120), nullable=False),
    Column("public_prefix", String(32), nullable=False),
    Column("secret_digest", LargeBinary(64), nullable=False),
    Column("label", String(160), nullable=False),
    Column("scopes", PlatformTokenScopeTupleType(), nullable=False),
    Column("expires_at", UTCDateTime(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("last_used_at", UTCDateTime(), nullable=True),
    Column("revoked_at", UTCDateTime(), nullable=True),
    UniqueConstraint("public_prefix", name="uq_platform_access_tokens_public_prefix"),
    UniqueConstraint("secret_digest", name="uq_platform_access_tokens_secret_digest"),
    Index(
        "ix_platform_access_tokens_principal_revoked",
        "principal_reference",
        "revoked_at",
    ),
    Index(
        "ix_platform_access_tokens_expiry_revoked",
        "expires_at",
        "revoked_at",
    ),
)


security_audit_events = Table(
    "security_audit_events",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("occurred_at", UTCDateTime(), nullable=False),
    Column("actor_kind", SecurityAuditActorKindType(), nullable=False),
    Column("user_id", SaUuid(as_uuid=True), nullable=True),
    Column("credential_reference", String(120), nullable=True),
    Column("workspace_id", SaUuid(as_uuid=True), nullable=True),
    Column("resource_type", String(80), nullable=True),
    Column("resource_id", String(255), nullable=True),
    Column("operation", String(120), nullable=False),
    Column("outcome", SecurityAuditOutcomeType(), nullable=False),
    Column("error_code", String(80), nullable=True),
    CheckConstraint(
        "actor_kind IN ('authenticated', 'unauthenticated', 'system')",
        name="ck_security_audit_events_actor_kind_choice",
    ),
    CheckConstraint(
        "outcome IN ('success', 'failure')",
        name="ck_security_audit_events_outcome_choice",
    ),
    Index(
        "ix_security_audit_events_workspace_occurred_at",
        "workspace_id",
        "occurred_at",
    ),
    Index(
        "ix_security_audit_events_actor_occurred_at",
        "actor_kind",
        "user_id",
        "occurred_at",
    ),
    Index(
        "ix_security_audit_events_operation_occurred_at",
        "operation",
        "occurred_at",
    ),
    Index("ix_security_audit_events_retention", "occurred_at"),
)
