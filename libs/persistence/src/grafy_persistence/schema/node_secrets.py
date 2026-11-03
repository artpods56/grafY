from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Table,
)
from sqlalchemy import Uuid as SaUuid

from grafy_persistence.column_types import UTCDateTime
from .base import metadata

node_secrets = Table(
    "node_secrets",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("project_id", SaUuid(as_uuid=True), primary_key=True),
    Column("graph_id", String(255), primary_key=True),
    Column("node_id", String(255), primary_key=True),
    Column("name", String(255), primary_key=True),
    Column("operator_id", String(255), nullable=False),
    Column("operator_version", Integer, nullable=False),
    Column("key_id", String(64), nullable=False),
    Column("aad_version", Integer, nullable=False),
    Column("dependency_sha256", String(64), nullable=False),
    Column("nonce", LargeBinary(12), nullable=False),
    Column("ciphertext", LargeBinary(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("projects.workspace_id", "projects.id"),
        ondelete="CASCADE",
    ),
    CheckConstraint("aad_version = 3", name="ck_node_secrets_aad_version"),
    Index(
        "ix_node_secrets_workspace_project_graph",
        "workspace_id",
        "project_id",
        "graph_id",
    ),
)
