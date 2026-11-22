"""Reusable provider credentials and per-node selections."""

import sqlalchemy as sa
from alembic import op
from grafy_persistence.column_types import UTCDateTime

revision = "0002_credentials_and_selections"
down_revision = "0001_baseline"


def upgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("provider_kind", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("key_hint", sa.String(length=32), nullable=True),
        sa.Column("key_id", sa.String(length=64), nullable=False),
        sa.Column("aad_version", sa.Integer(), nullable=False),
        sa.Column("nonce", sa.LargeBinary(length=12), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column(
            "verification_status",
            sa.String(length=32),
            server_default="unverified",
            nullable=False,
        ),
        sa.Column("verification_message", sa.String(length=500), nullable=True),
        sa.Column("verification_hint", sa.String(length=255), nullable=True),
        sa.Column("verified_at", UTCDateTime(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "(scope = 'personal' AND owner_user_id IS NOT NULL AND workspace_id IS NULL) OR (scope = 'shared' AND workspace_id IS NOT NULL AND owner_user_id IS NULL)",
            name=op.f("ck_credentials_scope_owner"),
        ),
        sa.CheckConstraint("aad_version = 1", name=op.f("ck_credentials_aad_version")),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_credentials_created_by_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            name=op.f("fk_credentials_owner_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_credentials_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_credentials")),
    )
    op.create_index(
        "ix_credentials_owner_provider",
        "credentials",
        ["owner_user_id", "provider_kind"],
        unique=False,
    )
    op.create_index(
        "ix_credentials_workspace_provider",
        "credentials",
        ["workspace_id", "provider_kind"],
        unique=False,
    )
    op.create_table(
        "node_shared_credential_bindings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.String(length=255), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "mode = 'credential' OR credential_id IS NULL",
            name=op.f("ck_node_shared_credential_bindings_selection"),
        ),
        sa.CheckConstraint(
            "mode IN ('credential', 'personal', 'deployment_default')",
            name=op.f("ck_node_shared_credential_bindings_mode"),
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credentials.id"],
            name=op.f("fk_node_shared_credential_bindings_credential_id_credentials"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            name=op.f("fk_node_shared_credential_bindings_updated_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name=op.f("fk_node_shared_credential_bindings_workspace_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "project_id",
            "graph_id",
            "node_id",
            "name",
            name=op.f("pk_node_shared_credential_bindings"),
        ),
    )
    op.create_index(
        "ix_node_shared_credential_bindings_graph",
        "node_shared_credential_bindings",
        ["workspace_id", "project_id", "graph_id"],
        unique=False,
    )
    op.create_table(
        "node_user_credential_overrides",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.String(length=255), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("credential_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.Column("updated_at", UTCDateTime(), nullable=False),
        sa.CheckConstraint(
            "(mode = 'credential') = (credential_id IS NOT NULL)",
            name=op.f("ck_node_user_credential_overrides_selection"),
        ),
        sa.CheckConstraint(
            "mode IN ('credential', 'shared', 'deployment_default')",
            name=op.f("ck_node_user_credential_overrides_mode"),
        ),
        sa.ForeignKeyConstraint(
            ["credential_id"],
            ["credentials.id"],
            name=op.f("fk_node_user_credential_overrides_credential_id_credentials"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_node_user_credential_overrides_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "project_id"],
            ["projects.workspace_id", "projects.id"],
            name=op.f("fk_node_user_credential_overrides_workspace_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "project_id",
            "graph_id",
            "node_id",
            "name",
            "user_id",
            name=op.f("pk_node_user_credential_overrides"),
        ),
    )
    op.create_index(
        "ix_node_user_credential_overrides_graph_user",
        "node_user_credential_overrides",
        ["workspace_id", "project_id", "graph_id", "user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("node_user_credential_overrides")
    op.drop_table("node_shared_credential_bindings")
    op.drop_table("credentials")
