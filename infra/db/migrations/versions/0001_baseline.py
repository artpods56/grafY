"""One baseline for the whole schema.

The rework in ADR 0020 keeps no rows, no clients and no stored shapes, so the
revision history that carried this schema up to here is gone. `upgrade` builds
the schema the ORM metadata in `grafy_persistence.schema` describes; `downgrade`
drops all of it.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from grafy_persistence.column_types import (
    ArtifactOutputsType,
    LibraryProvenanceType,
    SavedGraphDocumentType,
    UTCDateTime,
)
from grafy_persistence.schema.identity import (
    SecurityAuditActorKindType,
    SecurityAuditOutcomeType,
    WorkspaceCapabilityTupleType,
    WorkspaceInvitationStatusType,
    WorkspaceKindType,
    WorkspaceRoleType,
)
from grafy_persistence.schema.library import ModulePublicationStateType
from grafy_persistence.schema.uploads import UploadStatusType

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "oidc_login_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state_digest", sa.LargeBinary(length=64), nullable=False),
        sa.Column("nonce_digest", sa.LargeBinary(length=64), nullable=False),
        sa.Column("encrypted_pkce_verifier", sa.LargeBinary(), nullable=False),
        sa.Column("pkce_key_version", sa.Integer(), nullable=False),
        sa.Column("return_path", sa.String(length=2048), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("consumed_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "pkce_key_version >= 1",
            name=op.f(
                "ck_oidc_login_transactions_ck_oidc_login_transactions_pkce_key_version_positive"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oidc_login_transactions")),
    )
    op.create_index(
        "ix_oidc_login_transactions_expiry_consumed",
        "oidc_login_transactions",
        ["expires_at", "consumed_at"],
        unique=False,
    )
    op.create_table(
        "security_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", UTCDateTime(), nullable=False),
        sa.Column(
            "actor_kind",
            SecurityAuditActorKindType(length=24),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("credential_reference", sa.String(length=120), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("operation", sa.String(length=120), nullable=False),
        sa.Column(
            "outcome",
            SecurityAuditOutcomeType(length=16),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.CheckConstraint(
            "actor_kind IN ('authenticated', 'unauthenticated', 'system')",
            name=op.f(
                "ck_security_audit_events_ck_security_audit_events_actor_kind_choice"
            ),
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'failure')",
            name=op.f(
                "ck_security_audit_events_ck_security_audit_events_outcome_choice"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_security_audit_events")),
    )
    op.create_index(
        "ix_security_audit_events_actor_occurred_at",
        "security_audit_events",
        ["actor_kind", "user_id", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_security_audit_events_operation_occurred_at",
        "security_audit_events",
        ["operation", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_security_audit_events_retention",
        "security_audit_events",
        ["occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_security_audit_events_workspace_occurred_at",
        "security_audit_events",
        ["workspace_id", "occurred_at"],
        unique=False,
    )
    op.create_table(
        "transient_executions",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("execution_id", name=op.f("pk_transient_executions")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("normalized_email", sa.String(length=320), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(
        "ix_users_active_updated_at", "users", ["active", "updated_at"], unique=False
    )
    op.create_index(
        "ix_users_invitation_email",
        "users",
        ["normalized_email", "email_verified", "active"],
        unique=False,
    )
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("secret_digest", sa.LargeBinary(length=64), nullable=False),
        sa.Column("csrf_digest", sa.LargeBinary(length=64), nullable=False),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("last_used_at", UTCDateTime(), nullable=True),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_sessions")),
        sa.UniqueConstraint("secret_digest", name="uq_auth_sessions_secret_digest"),
    )
    op.create_index(
        "ix_auth_sessions_expiry_revoked",
        "auth_sessions",
        ["expires_at", "revoked_at"],
        unique=False,
    )
    op.create_index(
        "ix_auth_sessions_user_revoked",
        "auth_sessions",
        ["user_id", "revoked_at"],
        unique=False,
    )
    op.create_table(
        "oidc_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=2048), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oidc_identities_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oidc_identities")),
        sa.UniqueConstraint(
            "issuer", "subject", name="uq_oidc_identities_issuer_subject"
        ),
    )
    op.create_index(
        "ix_oidc_identities_user_id", "oidc_identities", ["user_id"], unique=False
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "kind",
            WorkspaceKindType(length=16),
            nullable=False,
        ),
        sa.Column("personal_owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "(kind = 'personal' AND personal_owner_user_id IS NOT NULL) OR (kind = 'shared' AND personal_owner_user_id IS NULL)",
            name=op.f("ck_workspaces_ck_workspaces_personal_owner_shape"),
        ),
        sa.CheckConstraint(
            "kind IN ('personal', 'shared')",
            name=op.f("ck_workspaces_ck_workspaces_kind_choice"),
        ),
        sa.CheckConstraint(
            "length(slug) BETWEEN 1 AND 80 AND slug = lower(trim(slug)) AND slug NOT LIKE '-%' AND slug NOT LIKE '%-'",
            name=op.f("ck_workspaces_ck_workspaces_slug_normalized"),
        ),
        sa.ForeignKeyConstraint(
            ["personal_owner_user_id"],
            ["users.id"],
            name=op.f("fk_workspaces_personal_owner_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint(
            "personal_owner_user_id", name="uq_workspaces_personal_owner_user_id"
        ),
        sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
    )
    op.create_index("ix_workspaces_kind", "workspaces", ["kind"], unique=False)
    op.create_table(
        "artifact_objects",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_type", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("storage_backend", sa.String(length=40), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=True),
        sa.Column("object_key", sa.String(length=2048), nullable=True),
        sa.Column("inline_payload", sa.JSON(), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column(
            "library_provenance",
            LibraryProvenanceType(none_as_null=True),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_artifact_objects_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_artifact_objects")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_artifact_objects_workspace_id_id"
        ),
    )
    op.create_index(
        "ix_artifact_objects_workspace_sha256",
        "artifact_objects",
        ["workspace_id", "sha256"],
        unique=False,
    )
    op.create_index(
        "ix_artifact_objects_workspace_type",
        "artifact_objects",
        ["workspace_id", "artifact_type", "schema_version"],
        unique=False,
    )
    op.create_table(
        "graph_folders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_graph_folders_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_graph_folders")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_graph_folders_workspace_id_id"
        ),
        sa.UniqueConstraint(
            "workspace_id", "name", name="uq_graph_folders_workspace_id_name"
        ),
    )
    op.create_index(
        "ix_graph_folders_workspace_name",
        "graph_folders",
        ["workspace_id", "name"],
        unique=False,
    )
    op.create_table(
        "invocation_cache_entries",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("key_sha256", sa.String(length=64), nullable=False),
        sa.Column("generation", sa.Uuid(), nullable=False),
        sa.Column(
            "outputs",
            ArtifactOutputsType(),
            nullable=False,
        ),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_invocation_cache_entries_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "key_sha256", name=op.f("pk_invocation_cache_entries")
        ),
    )
    op.create_table(
        "library_folders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("name_key", sa.String(length=480), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id",
            name=op.f("ck_library_folders_self_parent"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "parent_id"],
            ["library_folders.workspace_id", "library_folders.id"],
            name="fk_library_folders_parent_id_library_folders",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_library_folders_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_library_folders")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_library_folders_workspace_id_id"
        ),
    )
    op.create_index(
        "ix_library_folders_workspace_parent",
        "library_folders",
        ["workspace_id", "parent_id"],
        unique=False,
    )
    op.create_index(
        "uq_library_folders_child_name",
        "library_folders",
        ["workspace_id", "parent_id", "name_key"],
        unique=True,
        sqlite_where=sa.text("parent_id IS NOT NULL"),
        postgresql_where=sa.text("parent_id IS NOT NULL"),
    )
    op.create_index(
        "uq_library_folders_root_name",
        "library_folders",
        ["workspace_id", "name_key"],
        unique=True,
        sqlite_where=sa.text("parent_id IS NULL"),
        postgresql_where=sa.text("parent_id IS NULL"),
    )
    op.create_table(
        "personal_access_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("public_prefix", sa.String(length=32), nullable=False),
        sa.Column("secret_digest", sa.LargeBinary(length=64), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column(
            "scopes",
            WorkspaceCapabilityTupleType(),
            nullable=False,
        ),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("last_used_at", UTCDateTime(), nullable=True),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_personal_access_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_personal_access_tokens_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_personal_access_tokens")),
        sa.UniqueConstraint(
            "public_prefix", name="uq_personal_access_tokens_public_prefix"
        ),
        sa.UniqueConstraint(
            "secret_digest", name="uq_personal_access_tokens_secret_digest"
        ),
    )
    op.create_index(
        "ix_personal_access_tokens_expiry_revoked",
        "personal_access_tokens",
        ["expires_at", "revoked_at"],
        unique=False,
    )
    op.create_index(
        "ix_personal_access_tokens_workspace_revoked",
        "personal_access_tokens",
        ["workspace_id", "revoked_at"],
        unique=False,
    )
    op.create_table(
        "saved_graphs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "document",
            SavedGraphDocumentType(),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_saved_graphs_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_saved_graphs_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_saved_graphs")),
        sa.UniqueConstraint(
            "workspace_id", "id", name="uq_saved_graphs_workspace_id_id"
        ),
    )
    op.create_index(
        "ix_saved_graphs_workspace_id",
        "saved_graphs",
        ["workspace_id", "id"],
        unique=False,
    )
    op.create_index(
        "ix_saved_graphs_workspace_updated_at",
        "saved_graphs",
        ["workspace_id", "updated_at"],
        unique=False,
    )
    op.create_table(
        "uploads",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("expected_size", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            UploadStatusType(length=16),
            nullable=False,
        ),
        sa.Column("actual_size", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("artifact_type", sa.String(length=255), nullable=True),
        sa.Column("artifact_schema_version", sa.Integer(), nullable=True),
        sa.Column("artifact_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("completed_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "status <> 'ready' OR (artifact_type IS NOT NULL AND artifact_schema_version IS NOT NULL AND artifact_id IS NOT NULL AND sha256 IS NOT NULL)",
            name=op.f("ck_uploads_ck_uploads_ready_has_artifact"),
        ),
        sa.CheckConstraint(
            "status <> 'ready' OR (completed_at IS NOT NULL AND actual_size IS NOT NULL)",
            name=op.f("ck_uploads_ck_uploads_ready_is_complete"),
        ),
        sa.CheckConstraint(
            "actual_size IS NULL OR actual_size >= 0",
            name=op.f("ck_uploads_ck_uploads_actual_size_nonnegative"),
        ),
        sa.CheckConstraint(
            "artifact_schema_version IS NULL OR artifact_schema_version >= 1",
            name=op.f("ck_uploads_ck_uploads_artifact_schema_version_positive"),
        ),
        sa.CheckConstraint(
            "artifact_type IS NULL OR length(artifact_type) BETWEEN 1 AND 255",
            name=op.f("ck_uploads_ck_uploads_artifact_type_bounded"),
        ),
        sa.CheckConstraint(
            "expected_size >= 0",
            name=op.f("ck_uploads_ck_uploads_expected_size_nonnegative"),
        ),
        sa.CheckConstraint(
            "length(bucket) BETWEEN 1 AND 255",
            name=op.f("ck_uploads_ck_uploads_bucket_bounded"),
        ),
        sa.CheckConstraint(
            "length(object_key) BETWEEN 1 AND 1024",
            name=op.f("ck_uploads_ck_uploads_object_key_bounded"),
        ),
        sa.CheckConstraint(
            "length(original_filename) BETWEEN 1 AND 255",
            name=op.f("ck_uploads_ck_uploads_original_filename_bounded"),
        ),
        sa.CheckConstraint(
            "sha256 IS NULL OR length(sha256) = 64",
            name=op.f("ck_uploads_ck_uploads_sha256_length"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_uploads_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_uploads_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "upload_id", name=op.f("pk_uploads")),
    )
    op.create_index(
        "ix_uploads_status_created_at",
        "uploads",
        ["status", "created_at"],
        unique=False,
    )
    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("invitee_user_id", sa.Uuid(), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            WorkspaceRoleType(length=16),
            nullable=False,
        ),
        sa.Column(
            "status",
            WorkspaceInvitationStatusType(length=16),
            nullable=False,
        ),
        sa.Column("expires_at", UTCDateTime(), nullable=False),
        sa.Column("resolved_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "(status = 'pending' AND resolved_at IS NULL) OR (status != 'pending' AND resolved_at IS NOT NULL)",
            name=op.f(
                "ck_workspace_invitations_ck_workspace_invitations_resolution_shape"
            ),
        ),
        sa.CheckConstraint(
            "role IN ('viewer', 'editor', 'owner')",
            name=op.f("ck_workspace_invitations_ck_workspace_invitations_role_choice"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'cancelled', 'expired')",
            name=op.f(
                "ck_workspace_invitations_ck_workspace_invitations_status_choice"
            ),
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f(
                "ck_workspace_invitations_ck_workspace_invitations_expiry_after_creation"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            name=op.f("fk_workspace_invitations_invited_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["invitee_user_id"],
            ["users.id"],
            name=op.f("fk_workspace_invitations_invitee_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_invitations_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_invitations")),
    )
    op.create_index(
        "ix_workspace_invitations_invitee_status_expiry",
        "workspace_invitations",
        ["invitee_user_id", "status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_invitations_workspace_status_expiry",
        "workspace_invitations",
        ["workspace_id", "status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "uq_workspace_invitations_pending_recipient",
        "workspace_invitations",
        ["workspace_id", "invitee_user_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "workspace_memberships",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            WorkspaceRoleType(length=16),
            nullable=False,
        ),
        sa.Column("authorization_version", sa.BigInteger(), nullable=False),
        sa.Column("revoked_at", UTCDateTime(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "role IN ('viewer', 'editor', 'owner')",
            name=op.f("ck_workspace_memberships_ck_workspace_memberships_role_choice"),
        ),
        sa.CheckConstraint(
            "authorization_version >= 1",
            name=op.f(
                "ck_workspace_memberships_ck_workspace_memberships_authorization_version_positive"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_workspace_memberships_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_memberships_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "user_id", name=op.f("pk_workspace_memberships")
        ),
    )
    op.create_index(
        "ix_workspace_memberships_user_active",
        "workspace_memberships",
        ["user_id", "revoked_at"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_memberships_workspace_role_active",
        "workspace_memberships",
        ["workspace_id", "role", "revoked_at"],
        unique=False,
    )
    op.create_table(
        "collaborative_graph_heads",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("room_epoch", sa.Uuid(), nullable=False),
        sa.Column("collaboration_sequence", sa.Integer(), nullable=False),
        sa.Column("checkpoint_sequence", sa.Integer(), nullable=False),
        sa.Column("checkpoint_revision", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "document",
            SavedGraphDocumentType(),
            nullable=False,
        ),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "checkpoint_revision >= 1",
            name=op.f(
                "ck_collaborative_graph_heads_ck_collaborative_graph_heads_checkpoint_revision_positive"
            ),
        ),
        sa.CheckConstraint(
            "checkpoint_sequence <= collaboration_sequence",
            name=op.f(
                "ck_collaborative_graph_heads_ck_collaborative_graph_heads_checkpoint_lte_head"
            ),
        ),
        sa.CheckConstraint(
            "checkpoint_sequence >= 0",
            name=op.f(
                "ck_collaborative_graph_heads_ck_collaborative_graph_heads_checkpoint_sequence_nonneg"
            ),
        ),
        sa.CheckConstraint(
            "collaboration_sequence >= 0",
            name=op.f(
                "ck_collaborative_graph_heads_ck_collaborative_graph_heads_collaboration_sequence_nonneg"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["saved_graphs.workspace_id", "saved_graphs.id"],
            name=op.f("fk_collaborative_graph_heads_workspace_id_saved_graphs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "graph_id", name=op.f("pk_collaborative_graph_heads")
        ),
    )
    op.create_index(
        "ix_collaborative_graph_heads_workspace_updated_at",
        "collaborative_graph_heads",
        ["workspace_id", "updated_at"],
        unique=False,
    )
    op.create_table(
        "graph_organizations",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("folder_id", sa.Uuid(), nullable=True),
        sa.Column("archived_at", UTCDateTime(), nullable=True),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "folder_id"],
            ["graph_folders.workspace_id", "graph_folders.id"],
            name=op.f("fk_graph_organizations_workspace_id_graph_folders"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["saved_graphs.workspace_id", "saved_graphs.id"],
            name=op.f("fk_graph_organizations_workspace_id_saved_graphs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "graph_id", name=op.f("pk_graph_organizations")
        ),
    )
    op.create_index(
        "ix_graph_organizations_workspace_folder_archived",
        "graph_organizations",
        ["workspace_id", "folder_id", "archived_at"],
        unique=False,
    )
    op.create_table(
        "library_artifact_placements",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("folder_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "artifact_id"],
            ["artifact_objects.workspace_id", "artifact_objects.id"],
            name="fk_library_artifact_placements_artifact_object",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "folder_id"],
            ["library_folders.workspace_id", "library_folders.id"],
            name="fk_library_artifact_placements_library_folder",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_library_artifact_placements_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "artifact_id", name=op.f("pk_library_artifact_placements")
        ),
    )
    op.create_index(
        "ix_library_artifact_placements_workspace_folder",
        "library_artifact_placements",
        ["workspace_id", "folder_id"],
        unique=False,
    )
    op.create_table(
        "modules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("source_graph_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=True),
        sa.Column(
            "publication_state",
            ModulePublicationStateType(length=32),
            nullable=False,
        ),
        sa.Column("current_library_release", sa.Integer(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "publication_state IN ('published')",
            name=op.f("ck_modules_module_publication_state"),
        ),
        sa.CheckConstraint(
            "current_library_release IS NULL OR current_library_release >= 1",
            name=op.f("ck_modules_module_current_library_release"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_graph_id"],
            ["saved_graphs.workspace_id", "saved_graphs.id"],
            name="fk_modules_source_graph_id_saved_graphs",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_modules_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_modules")),
        sa.UniqueConstraint("workspace_id", "id", name="uq_modules_workspace_id_id"),
        sa.UniqueConstraint(
            "workspace_id", "source_graph_id", name="uq_modules_workspace_source_graph"
        ),
    )
    op.create_index(
        "ix_modules_workspace_updated_at",
        "modules",
        ["workspace_id", "updated_at"],
        unique=False,
    )
    op.create_table(
        "node_secrets",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("operator_id", sa.String(length=255), nullable=False),
        sa.Column("operator_version", sa.Integer(), nullable=False),
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("aad_version", sa.Integer(), nullable=False),
        sa.Column("dependency_sha256", sa.String(length=64), nullable=False),
        sa.Column("nonce", sa.LargeBinary(length=12), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "aad_version IN (1, 2)",
            name=op.f("ck_node_secrets_ck_node_secrets_aad_version"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["saved_graphs.workspace_id", "saved_graphs.id"],
            name=op.f("fk_node_secrets_workspace_id_saved_graphs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "graph_id", "node_id", "name", name=op.f("pk_node_secrets")
        ),
    )
    op.create_index(
        "ix_node_secrets_workspace_graph",
        "node_secrets",
        ["workspace_id", "graph_id"],
        unique=False,
    )
    op.create_table(
        "saved_graph_revisions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column(
            "document",
            SavedGraphDocumentType(),
            nullable=False,
        ),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["saved_graphs.workspace_id", "saved_graphs.id"],
            name=op.f("fk_saved_graph_revisions_workspace_id_saved_graphs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "graph_id",
            "revision",
            name=op.f("pk_saved_graph_revisions"),
        ),
    )
    op.create_index(
        "ix_saved_graph_revisions_workspace_graph_revision",
        "saved_graph_revisions",
        ["workspace_id", "graph_id", "revision"],
        unique=False,
    )
    op.create_table(
        "user_graph_states",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("starred", sa.Boolean(), nullable=False),
        sa.Column(
            "last_opened_at",
            UTCDateTime(),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_graph_states_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["saved_graphs.workspace_id", "saved_graphs.id"],
            name=op.f("fk_user_graph_states_workspace_id_saved_graphs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "graph_id", "user_id", name=op.f("pk_user_graph_states")
        ),
    )
    op.create_index(
        "ix_user_graph_states_user_last_opened",
        "user_graph_states",
        ["user_id", "last_opened_at"],
        unique=False,
    )
    op.create_index(
        "ix_user_graph_states_user_starred",
        "user_graph_states",
        ["user_id", "starred"],
        unique=False,
    )
    op.create_table(
        "graph_checkpoint_mappings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("room_epoch", sa.Uuid(), nullable=False),
        sa.Column("collaboration_sequence", sa.Integer(), nullable=False),
        sa.Column("saved_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "saved_revision"],
            [
                "saved_graph_revisions.workspace_id",
                "saved_graph_revisions.graph_id",
                "saved_graph_revisions.revision",
            ],
            name=op.f(
                "fk_graph_checkpoint_mappings_workspace_id_saved_graph_revisions"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            [
                "collaborative_graph_heads.workspace_id",
                "collaborative_graph_heads.graph_id",
            ],
            name=op.f(
                "fk_graph_checkpoint_mappings_workspace_id_collaborative_graph_heads"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "graph_id",
            "room_epoch",
            "collaboration_sequence",
            name=op.f("pk_graph_checkpoint_mappings"),
        ),
    )
    op.create_table(
        "graph_command_receipts",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("command_hmac", sa.LargeBinary(length=64), nullable=False),
        sa.Column("hmac_key_version", sa.Integer(), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("room_epoch", sa.Uuid(), nullable=False),
        sa.Column("accepted_sequence", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            [
                "collaborative_graph_heads.workspace_id",
                "collaborative_graph_heads.graph_id",
            ],
            name=op.f(
                "fk_graph_command_receipts_workspace_id_collaborative_graph_heads"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "graph_id",
            "command_id",
            name=op.f("pk_graph_command_receipts"),
        ),
    )
    op.create_table(
        "graph_executions",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("graph_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("submitted_request", sa.JSON(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("submitted_by_actor_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("started_at", UTCDateTime(), nullable=True),
        sa.Column("finished_at", UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "graph_revision"],
            [
                "saved_graph_revisions.workspace_id",
                "saved_graph_revisions.graph_id",
                "saved_graph_revisions.revision",
            ],
            name=op.f("fk_graph_executions_workspace_id_saved_graph_revisions"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("execution_id", name=op.f("pk_graph_executions")),
        sa.UniqueConstraint(
            "workspace_id",
            "execution_id",
            name="uq_graph_executions_workspace_id_execution_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_graph_executions_workspace_idempotency_key",
        ),
    )
    op.create_index(
        "ix_graph_executions_graph_created",
        "graph_executions",
        ["workspace_id", "graph_id", "created_at", "execution_id"],
        unique=False,
    )
    op.create_index(
        "ix_graph_executions_graph_revision_created",
        "graph_executions",
        ["workspace_id", "graph_id", "graph_revision", "created_at", "execution_id"],
        unique=False,
    )
    op.create_index(
        "ix_graph_executions_queue_order",
        "graph_executions",
        ["status", "created_at", "execution_id"],
        unique=False,
    )
    op.create_index(
        "ix_graph_executions_workspace_status",
        "graph_executions",
        ["workspace_id", "status"],
        unique=False,
    )
    op.create_index(
        "uq_graph_executions_one_active_per_graph",
        "graph_executions",
        ["workspace_id", "graph_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running', 'cancelling')"),
        postgresql_where=sa.text("status IN ('queued', 'running', 'cancelling')"),
    )
    op.create_table(
        "materialized_node_outputs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("graph_revision", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column(
            "outputs",
            ArtifactOutputsType(),
            nullable=False,
        ),
        sa.Column(
            "materialized_at",
            UTCDateTime(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "graph_revision"],
            [
                "saved_graph_revisions.workspace_id",
                "saved_graph_revisions.graph_id",
                "saved_graph_revisions.revision",
            ],
            name=op.f(
                "fk_materialized_node_outputs_workspace_id_saved_graph_revisions"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "graph_id",
            "graph_revision",
            "node_id",
            name=op.f("pk_materialized_node_outputs"),
        ),
    )
    op.create_index(
        "ix_materialized_node_outputs_graph_revision",
        "materialized_node_outputs",
        ["workspace_id", "graph_id", "graph_revision", "materialized_at"],
        unique=False,
    )
    op.create_table(
        "module_releases",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("module_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("source_graph_id", sa.Uuid(), nullable=False),
        sa.Column("published_at", UTCDateTime(), nullable=False),
        sa.Column("published_by_user_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "revision >= 1", name=op.f("ck_module_releases_module_release_revision")
        ),
        sa.ForeignKeyConstraint(
            ["published_by_user_id"],
            ["users.id"],
            name=op.f("fk_module_releases_published_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "module_id"],
            ["modules.workspace_id", "modules.id"],
            name=op.f("fk_module_releases_workspace_id_modules"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "source_graph_id", "revision"],
            [
                "saved_graph_revisions.workspace_id",
                "saved_graph_revisions.graph_id",
                "saved_graph_revisions.revision",
            ],
            name="fk_module_releases_saved_graph_revision",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id", "module_id", "revision", name=op.f("pk_module_releases")
        ),
    )
    op.create_index(
        "ix_module_releases_workspace_module_revision",
        "module_releases",
        ["workspace_id", "module_id", "revision"],
        unique=False,
    )
    op.create_table(
        "graph_execution_nodes",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("result_status", sa.String(length=16), nullable=True),
        sa.Column("result_position", sa.Integer(), nullable=True),
        sa.Column(
            "outputs",
            ArtifactOutputsType(),
            nullable=True,
        ),
        sa.Column("artifact_count", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("diagnostics", sa.JSON(), nullable=True),
        sa.Column("completed_at", UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "(result_status IS NULL AND result_position IS NULL AND outputs IS NULL AND artifact_count IS NULL AND diagnostics IS NULL AND completed_at IS NULL) OR (result_status IN ('succeeded', 'failed', 'skipped') AND result_position IS NOT NULL AND outputs IS NOT NULL AND artifact_count IS NOT NULL AND artifact_count >= 0 AND completed_at IS NOT NULL)",
            name=op.f("ck_graph_execution_nodes_ck_graph_execution_nodes_result_shape"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "execution_id"],
            ["graph_executions.workspace_id", "graph_executions.execution_id"],
            name="fk_exec_nodes_workspace_execution",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "execution_id",
            "node_id",
            name=op.f("pk_graph_execution_nodes"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "execution_id",
            "position",
            name="uq_graph_execution_nodes_execution_position",
        ),
    )
    op.create_index(
        "ix_graph_execution_nodes_node_execution",
        "graph_execution_nodes",
        ["workspace_id", "node_id", "execution_id"],
        unique=False,
    )
    op.create_index(
        "uq_graph_execution_nodes_execution_result_position",
        "graph_execution_nodes",
        ["workspace_id", "execution_id", "result_position"],
        unique=True,
        sqlite_where=sa.text("result_position IS NOT NULL"),
        postgresql_where=sa.text("result_position IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_graph_execution_nodes_execution_result_position",
        table_name="graph_execution_nodes",
        sqlite_where=sa.text("result_position IS NOT NULL"),
        postgresql_where=sa.text("result_position IS NOT NULL"),
    )
    op.drop_index(
        "ix_graph_execution_nodes_node_execution", table_name="graph_execution_nodes"
    )
    op.drop_table("graph_execution_nodes")
    op.drop_index(
        "ix_module_releases_workspace_module_revision", table_name="module_releases"
    )
    op.drop_table("module_releases")
    op.drop_index(
        "ix_materialized_node_outputs_graph_revision",
        table_name="materialized_node_outputs",
    )
    op.drop_table("materialized_node_outputs")
    op.drop_index(
        "uq_graph_executions_one_active_per_graph",
        table_name="graph_executions",
        sqlite_where=sa.text("status IN ('queued', 'running', 'cancelling')"),
        postgresql_where=sa.text("status IN ('queued', 'running', 'cancelling')"),
    )
    op.drop_index("ix_graph_executions_workspace_status", table_name="graph_executions")
    op.drop_index("ix_graph_executions_queue_order", table_name="graph_executions")
    op.drop_index(
        "ix_graph_executions_graph_revision_created", table_name="graph_executions"
    )
    op.drop_index("ix_graph_executions_graph_created", table_name="graph_executions")
    op.drop_table("graph_executions")
    op.drop_table("graph_command_receipts")
    op.drop_table("graph_checkpoint_mappings")
    op.drop_index("ix_user_graph_states_user_starred", table_name="user_graph_states")
    op.drop_index(
        "ix_user_graph_states_user_last_opened", table_name="user_graph_states"
    )
    op.drop_table("user_graph_states")
    op.drop_index(
        "ix_saved_graph_revisions_workspace_graph_revision",
        table_name="saved_graph_revisions",
    )
    op.drop_table("saved_graph_revisions")
    op.drop_index("ix_node_secrets_workspace_graph", table_name="node_secrets")
    op.drop_table("node_secrets")
    op.drop_index("ix_modules_workspace_updated_at", table_name="modules")
    op.drop_table("modules")
    op.drop_index(
        "ix_library_artifact_placements_workspace_folder",
        table_name="library_artifact_placements",
    )
    op.drop_table("library_artifact_placements")
    op.drop_index(
        "ix_graph_organizations_workspace_folder_archived",
        table_name="graph_organizations",
    )
    op.drop_table("graph_organizations")
    op.drop_index(
        "ix_collaborative_graph_heads_workspace_updated_at",
        table_name="collaborative_graph_heads",
    )
    op.drop_table("collaborative_graph_heads")
    op.drop_index(
        "ix_workspace_memberships_workspace_role_active",
        table_name="workspace_memberships",
    )
    op.drop_index(
        "ix_workspace_memberships_user_active", table_name="workspace_memberships"
    )
    op.drop_table("workspace_memberships")
    op.drop_index(
        "uq_workspace_invitations_pending_recipient",
        table_name="workspace_invitations",
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(
        "ix_workspace_invitations_workspace_status_expiry",
        table_name="workspace_invitations",
    )
    op.drop_index(
        "ix_workspace_invitations_invitee_status_expiry",
        table_name="workspace_invitations",
    )
    op.drop_table("workspace_invitations")
    op.drop_index("ix_uploads_status_created_at", table_name="uploads")
    op.drop_table("uploads")
    op.drop_index("ix_saved_graphs_workspace_updated_at", table_name="saved_graphs")
    op.drop_index("ix_saved_graphs_workspace_id", table_name="saved_graphs")
    op.drop_table("saved_graphs")
    op.drop_index(
        "ix_personal_access_tokens_workspace_revoked",
        table_name="personal_access_tokens",
    )
    op.drop_index(
        "ix_personal_access_tokens_expiry_revoked", table_name="personal_access_tokens"
    )
    op.drop_table("personal_access_tokens")
    op.drop_index(
        "uq_library_folders_root_name",
        table_name="library_folders",
        sqlite_where=sa.text("parent_id IS NULL"),
        postgresql_where=sa.text("parent_id IS NULL"),
    )
    op.drop_index(
        "uq_library_folders_child_name",
        table_name="library_folders",
        sqlite_where=sa.text("parent_id IS NOT NULL"),
        postgresql_where=sa.text("parent_id IS NOT NULL"),
    )
    op.drop_index("ix_library_folders_workspace_parent", table_name="library_folders")
    op.drop_table("library_folders")
    op.drop_table("invocation_cache_entries")
    op.drop_index("ix_graph_folders_workspace_name", table_name="graph_folders")
    op.drop_table("graph_folders")
    op.drop_index("ix_artifact_objects_workspace_type", table_name="artifact_objects")
    op.drop_index("ix_artifact_objects_workspace_sha256", table_name="artifact_objects")
    op.drop_table("artifact_objects")
    op.drop_index("ix_workspaces_kind", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_index("ix_oidc_identities_user_id", table_name="oidc_identities")
    op.drop_table("oidc_identities")
    op.drop_index("ix_auth_sessions_user_revoked", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_expiry_revoked", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index("ix_users_invitation_email", table_name="users")
    op.drop_index("ix_users_active_updated_at", table_name="users")
    op.drop_table("users")
    op.drop_table("transient_executions")
    op.drop_index(
        "ix_security_audit_events_workspace_occurred_at",
        table_name="security_audit_events",
    )
    op.drop_index(
        "ix_security_audit_events_retention", table_name="security_audit_events"
    )
    op.drop_index(
        "ix_security_audit_events_operation_occurred_at",
        table_name="security_audit_events",
    )
    op.drop_index(
        "ix_security_audit_events_actor_occurred_at", table_name="security_audit_events"
    )
    op.drop_table("security_audit_events")
    op.drop_index(
        "ix_oidc_login_transactions_expiry_consumed",
        table_name="oidc_login_transactions",
    )
    op.drop_table("oidc_login_transactions")
