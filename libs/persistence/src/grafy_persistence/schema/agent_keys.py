"""Encrypted per-Agent model key SQL schema (ADR 0021, issue #202).

One row per Agent, keyed by where the Agent sits. The columns are seal material and
binding only — there is no column a key could be read out of. See
``grafy_core.domain.agent_keys`` for why the binding is the Agent's coordinates and not
an operator contract, which is what separates this from ``node_secrets``.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    Integer,
    String,
    Table,
)
from sqlalchemy import Uuid as SaUuid

from grafy_persistence.column_types import UTCDateTime

from .base import metadata

agent_keys = Table(
    "agent_keys",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("project_id", SaUuid(as_uuid=True), primary_key=True),
    Column("graph_id", String(255), primary_key=True),
    Column("agent_id", String(255), primary_key=True),
    Column("key_id", String(64), nullable=False),
    Column("aad_version", Integer, nullable=False),
    Column("nonce", LargeBinary(12), nullable=False),
    Column("ciphertext", LargeBinary, nullable=False),
    # Who sealed it, kept as a bare id like a command receipt's actor: an account going
    # away must not silently take an Agent's credential with it, and must not strand a
    # row whose author cannot be named.
    Column("set_by_user_id", SaUuid(as_uuid=True), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    CheckConstraint("aad_version = 1", name="ck_agent_keys_aad_version"),
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("projects.workspace_id", "projects.id"),
        ondelete="CASCADE",
    ),
    Index(
        "ix_agent_keys_workspace_project_graph",
        "workspace_id",
        "project_id",
        "graph_id",
    ),
)
