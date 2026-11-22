from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
    Uuid,
)

from grafy_persistence.column_types import UTCDateTime

from .base import metadata

credentials = Table(
    "credentials",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column("scope", String(16), nullable=False),
    Column("owner_user_id", Uuid(), ForeignKey("users.id", ondelete="CASCADE")),
    Column("workspace_id", Uuid(), ForeignKey("workspaces.id", ondelete="CASCADE")),
    Column("provider_kind", String(128), nullable=False),
    Column("label", String(160), nullable=False),
    Column("key_hint", String(32)),
    Column("key_id", String(64), nullable=False),
    Column("aad_version", Integer, nullable=False),
    Column("nonce", LargeBinary(12), nullable=False),
    Column("ciphertext", LargeBinary(), nullable=False),
    Column(
        "verification_status", String(32), nullable=False, server_default="unverified"
    ),
    Column("verification_message", String(500)),
    Column("verification_hint", String(255)),
    Column("verified_at", UTCDateTime()),
    Column(
        "created_by_user_id",
        Uuid(),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    CheckConstraint("aad_version = 1", name="aad_version"),
    CheckConstraint(
        "(scope = 'personal' AND owner_user_id IS NOT NULL AND workspace_id IS NULL) OR "
        "(scope = 'shared' AND workspace_id IS NOT NULL AND owner_user_id IS NULL)",
        name="scope_owner",
    ),
    Index("ix_credentials_owner_provider", "owner_user_id", "provider_kind"),
    Index("ix_credentials_workspace_provider", "workspace_id", "provider_kind"),
)

node_shared_credential_bindings = Table(
    "node_shared_credential_bindings",
    metadata,
    Column("workspace_id", Uuid(), primary_key=True),
    Column("project_id", Uuid(), primary_key=True),
    Column("graph_id", String(255), primary_key=True),
    Column("node_id", String(255), primary_key=True),
    Column("name", String(255), primary_key=True),
    Column("mode", String(32), nullable=False),
    Column("credential_id", Uuid(), ForeignKey("credentials.id", ondelete="SET NULL")),
    Column("updated_by_user_id", Uuid(), ForeignKey("users.id", ondelete="SET NULL")),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    CheckConstraint(
        "mode IN ('credential', 'personal', 'deployment_default')", name="mode"
    ),
    CheckConstraint("mode = 'credential' OR credential_id IS NULL", name="selection"),
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("projects.workspace_id", "projects.id"),
        ondelete="CASCADE",
    ),
    Index(
        "ix_node_shared_credential_bindings_graph",
        "workspace_id",
        "project_id",
        "graph_id",
    ),
)

node_user_credential_overrides = Table(
    "node_user_credential_overrides",
    metadata,
    Column("workspace_id", Uuid(), primary_key=True),
    Column("project_id", Uuid(), primary_key=True),
    Column("graph_id", String(255), primary_key=True),
    Column("node_id", String(255), primary_key=True),
    Column("name", String(255), primary_key=True),
    Column(
        "user_id", Uuid(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    ),
    Column("mode", String(32), nullable=False),
    Column("credential_id", Uuid(), ForeignKey("credentials.id", ondelete="CASCADE")),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    CheckConstraint(
        "mode IN ('credential', 'shared', 'deployment_default')", name="mode"
    ),
    CheckConstraint(
        "(mode = 'credential') = (credential_id IS NOT NULL)", name="selection"
    ),
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("projects.workspace_id", "projects.id"),
        ondelete="CASCADE",
    ),
    Index(
        "ix_node_user_credential_overrides_graph_user",
        "workspace_id",
        "project_id",
        "graph_id",
        "user_id",
    ),
)
