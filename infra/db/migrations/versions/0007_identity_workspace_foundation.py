"""Add identity, workspace, credential, and security-audit foundation.

Revision ID: 0007_identity_workspace_foundation
Revises: 0006_execution_history
Create Date: 2026-08-07
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from alembic import op
import sqlalchemy as sa


revision: str = "0007_identity_workspace_foundation"
down_revision: str | Sequence[str] | None = "0006_execution_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LOCAL_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")
# UTCDateTime persists UTC timestamps in timezone-naive database columns.
LOCAL_WORKSPACE_CREATED_AT = datetime(2026, 8, 7)


def upgrade() -> None:
    connection = op.get_bind()
    if connection.dialect.name == "postgresql":
        op.alter_column(
            "alembic_version",
            "version_num",
            existing_type=sa.String(length=32),
            type_=sa.String(length=64),
            existing_nullable=False,
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=160), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_index(
        "ix_users_active_updated_at",
        "users",
        ["active", "updated_at"],
        unique=False,
    )

    op.create_table(
        "oidc_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=2048), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_oidc_identities_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_oidc_identities"),
        sa.UniqueConstraint(
            "issuer",
            "subject",
            name="uq_oidc_identities_issuer_subject",
        ),
    )
    op.create_index(
        "ix_oidc_identities_user_id",
        "oidc_identities",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "oidc_login_transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("state_digest", sa.LargeBinary(length=64), nullable=False),
        sa.Column("nonce_digest", sa.LargeBinary(length=64), nullable=False),
        sa.Column("encrypted_pkce_verifier", sa.LargeBinary(), nullable=False),
        sa.Column("pkce_key_version", sa.Integer(), nullable=False),
        sa.Column("return_path", sa.String(length=2048), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "pkce_key_version >= 1",
            name="ck_oidc_login_transactions_pkce_key_version_positive",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_oidc_login_transactions"),
    )
    op.create_index(
        "ix_oidc_login_transactions_expiry_consumed",
        "oidc_login_transactions",
        ["expires_at", "consumed_at"],
        unique=False,
    )

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("personal_owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('personal', 'shared')",
            name="ck_workspaces_kind_choice",
        ),
        sa.CheckConstraint(
            "length(slug) BETWEEN 1 AND 80 AND "
            "slug = lower(trim(slug)) AND "
            "slug NOT LIKE '-%' AND slug NOT LIKE '%-'",
            name="ck_workspaces_slug_normalized",
        ),
        sa.CheckConstraint(
            "(kind = 'personal' AND personal_owner_user_id IS NOT NULL) OR "
            "(kind = 'shared' AND personal_owner_user_id IS NULL)",
            name="ck_workspaces_personal_owner_shape",
        ),
        sa.ForeignKeyConstraint(
            ["personal_owner_user_id"],
            ["users.id"],
            name="fk_workspaces_personal_owner_user_id_users",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_workspaces"),
        sa.UniqueConstraint(
            "personal_owner_user_id", name="uq_workspaces_personal_owner_user_id"
        ),
        sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
    )
    op.create_index("ix_workspaces_kind", "workspaces", ["kind"], unique=False)

    op.create_table(
        "workspace_memberships",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("authorization_version", sa.BigInteger(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "role IN ('viewer', 'editor', 'owner')",
            name="ck_workspace_memberships_role_choice",
        ),
        sa.CheckConstraint(
            "authorization_version >= 1",
            name="ck_workspace_memberships_authorization_version_positive",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_workspace_memberships_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_workspace_memberships_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "user_id",
            name="pk_workspace_memberships",
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
        "oidc_bootstrap_owner_mappings",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("issuer", sa.String(length=2048), nullable=False),
        sa.Column("subject", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_oidc_bootstrap_owner_mappings_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_oidc_bootstrap_owner_mappings"),
        sa.UniqueConstraint(
            "workspace_id",
            name="uq_oidc_bootstrap_owner_mappings_workspace_id",
        ),
    )
    op.create_index(
        "ix_oidc_bootstrap_owner_mappings_unconsumed",
        "oidc_bootstrap_owner_mappings",
        ["workspace_id", "consumed_at"],
        unique=False,
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("secret_digest", sa.LargeBinary(length=64), nullable=False),
        sa.Column("csrf_digest", sa.LargeBinary(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_auth_sessions_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("secret_digest", name="uq_auth_sessions_secret_digest"),
    )
    op.create_index(
        "ix_auth_sessions_user_revoked",
        "auth_sessions",
        ["user_id", "revoked_at"],
        unique=False,
    )
    op.create_index(
        "ix_auth_sessions_expiry_revoked",
        "auth_sessions",
        ["expires_at", "revoked_at"],
        unique=False,
    )

    op.create_table(
        "personal_access_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("public_prefix", sa.String(length=32), nullable=False),
        sa.Column("secret_digest", sa.LargeBinary(length=64), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_personal_access_tokens_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_personal_access_tokens_workspace_id_workspaces",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_personal_access_tokens"),
        sa.UniqueConstraint(
            "public_prefix",
            name="uq_personal_access_tokens_public_prefix",
        ),
        sa.UniqueConstraint(
            "secret_digest",
            name="uq_personal_access_tokens_secret_digest",
        ),
    )
    op.create_index(
        "ix_personal_access_tokens_workspace_revoked",
        "personal_access_tokens",
        ["workspace_id", "revoked_at"],
        unique=False,
    )
    op.create_index(
        "ix_personal_access_tokens_expiry_revoked",
        "personal_access_tokens",
        ["expires_at", "revoked_at"],
        unique=False,
    )

    op.create_table(
        "security_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("actor_kind", sa.String(length=24), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("credential_reference", sa.String(length=120), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("resource_type", sa.String(length=80), nullable=True),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("operation", sa.String(length=120), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.CheckConstraint(
            "actor_kind IN ('authenticated', 'unauthenticated', 'system')",
            name="ck_security_audit_events_actor_kind_choice",
        ),
        sa.CheckConstraint(
            "outcome IN ('success', 'failure')",
            name="ck_security_audit_events_outcome_choice",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_security_audit_events"),
    )
    op.create_index(
        "ix_security_audit_events_workspace_occurred_at",
        "security_audit_events",
        ["workspace_id", "occurred_at"],
        unique=False,
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

    op.bulk_insert(
        sa.table(
            "workspaces",
            sa.column("id", sa.Uuid()),
            sa.column("slug", sa.String()),
            sa.column("name", sa.String()),
            sa.column("kind", sa.String()),
            sa.column("personal_owner_user_id", sa.Uuid()),
            sa.column("created_at", sa.DateTime()),
            sa.column("updated_at", sa.DateTime()),
        ),
        [
            {
                "id": LOCAL_WORKSPACE_ID,
                "slug": "local",
                "name": "Local workspace",
                "kind": "shared",
                "personal_owner_user_id": None,
                "created_at": LOCAL_WORKSPACE_CREATED_AT,
                "updated_at": LOCAL_WORKSPACE_CREATED_AT,
            }
        ],
    )


def downgrade() -> None:
    connection = op.get_bind()
    local_workspace = (
        connection.execute(
            _local_workspace_guard_query(),
            {"local_id": LOCAL_WORKSPACE_ID},
        )
        .mappings()
        .all()
    )
    workspace_count = connection.scalar(sa.text("SELECT COUNT(*) FROM workspaces"))
    if workspace_count != 1 or local_workspace != [
        {
            "slug": "local",
            "kind": "shared",
            "personal_owner_user_id": None,
        }
    ]:
        raise RuntimeError(
            "Cannot downgrade identity foundation: users or workspaces would "
            "be discarded or merged"
        )
    identity_tables = (
        "users",
        "oidc_identities",
        "oidc_login_transactions",
        "oidc_bootstrap_owner_mappings",
        "workspace_memberships",
        "auth_sessions",
        "personal_access_tokens",
        "security_audit_events",
    )
    populated = {
        table_name: int(
            connection.scalar(sa.text(f"SELECT COUNT(*) FROM {table_name}")) or 0
        )
        for table_name in identity_tables
    }
    populated = {table_name: count for table_name, count in populated.items() if count}
    if populated:
        raise RuntimeError(
            "Cannot downgrade identity foundation: identity/security data would "
            f"be discarded ({populated})"
        )
    op.drop_index(
        "ix_security_audit_events_retention", table_name="security_audit_events"
    )
    op.drop_index(
        "ix_security_audit_events_operation_occurred_at",
        table_name="security_audit_events",
    )
    op.drop_index(
        "ix_security_audit_events_actor_occurred_at",
        table_name="security_audit_events",
    )
    op.drop_index(
        "ix_security_audit_events_workspace_occurred_at",
        table_name="security_audit_events",
    )
    op.drop_table("security_audit_events")
    op.drop_index(
        "ix_personal_access_tokens_expiry_revoked",
        table_name="personal_access_tokens",
    )
    op.drop_index(
        "ix_personal_access_tokens_workspace_revoked",
        table_name="personal_access_tokens",
    )
    op.drop_table("personal_access_tokens")
    op.drop_index("ix_auth_sessions_expiry_revoked", table_name="auth_sessions")
    op.drop_index("ix_auth_sessions_user_revoked", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_index(
        "ix_oidc_bootstrap_owner_mappings_unconsumed",
        table_name="oidc_bootstrap_owner_mappings",
    )
    op.drop_table("oidc_bootstrap_owner_mappings")
    op.drop_index(
        "ix_workspace_memberships_workspace_role_active",
        table_name="workspace_memberships",
    )
    op.drop_index(
        "ix_workspace_memberships_user_active",
        table_name="workspace_memberships",
    )
    op.drop_table("workspace_memberships")
    op.drop_index("ix_workspaces_kind", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_index(
        "ix_oidc_login_transactions_expiry_consumed",
        table_name="oidc_login_transactions",
    )
    op.drop_table("oidc_login_transactions")
    op.drop_index("ix_oidc_identities_user_id", table_name="oidc_identities")
    op.drop_table("oidc_identities")
    op.drop_index("ix_users_active_updated_at", table_name="users")
    op.drop_table("users")


def _local_workspace_guard_query() -> sa.TextClause:
    return sa.text(
        "SELECT slug, kind, personal_owner_user_id FROM workspaces WHERE id = :local_id"
    ).bindparams(sa.bindparam("local_id", type_=sa.Uuid()))
