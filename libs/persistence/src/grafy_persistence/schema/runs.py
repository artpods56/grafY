"""Run and result-store SQL schema (ADR 0020, issue #195).

Three tables, three lifetimes. ``node_results`` is append-only and belongs to the
Workspace, not to any Project: a stored result stays reusable until the Workspace
itself goes away. ``instance_pointers`` and ``project_runs`` are mutable bookkeeping
about Projects and cascade with them, so deleting a Project drops its Run history
and its instance pointers while the results those Runs produced remain addressable
by fingerprint.

Every table is keyed by ``workspace_id``, and everything that belongs to a Project
joins through the ``(workspace_id, project_id)`` pair on ``projects``, so a row of
another Workspace is a foreign key miss rather than a row to filter out. Results
are never shared across Workspaces: the same fingerprint in two Workspaces is two
rows.

An instance pointer is keyed by ``instance_digest``, the SHA-256 of the canonical
JSON of the *full* ``InstanceKey`` (project, graph, call path, node id, map index).
The JSON itself cannot be a portable primary key, so the digest is the key and the
key's coordinates are stored beside it and round-trip exactly.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    JSON,
    String,
    Table,
    Text,
)
from sqlalchemy import Uuid as SaUuid

from grafy_persistence.column_types import ArtifactOutputsType, UTCDateTime

from .base import metadata

_RUN_STATUSES = ("running", "succeeded", "failed", "cancelled", "interrupted")

node_results = Table(
    "node_results",
    metadata,
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("fingerprint", String(64), primary_key=True),
    # Immutable artifact refs and sequences; the row is never updated in place.
    Column("outputs", ArtifactOutputsType(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
)

instance_pointers = Table(
    "instance_pointers",
    metadata,
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("instance_digest", String(64), primary_key=True),
    # The full InstanceKey, so a pointer reads back as the exact key it was
    # written with. The digest cannot be reversed, these columns can.
    Column("project_id", SaUuid(as_uuid=True), nullable=False),
    Column("graph_id", String(255), nullable=False),
    Column("call_path", JSON, nullable=False),
    Column("node_id", String(255), nullable=False),
    Column("map_index", Integer, nullable=True),
    CheckConstraint(
        "map_index IS NULL OR map_index >= 0",
        name="ck_instance_pointers_map_index_nonneg",
    ),
    # Last result and last failure live side by side: a failed instance keeps
    # showing what it last produced.
    Column("last_result_fingerprint", String(64), nullable=True),
    Column("failure_fingerprint", String(64), nullable=True),
    Column("failure_message", Text, nullable=True),
    Column("failed_at", UTCDateTime(), nullable=True),
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("projects.workspace_id", "projects.id"),
        ondelete="CASCADE",
    ),
    # Pointing at a result requires that result to exist, and deleting a result
    # out from under a pointer is refused. The pointer is the mutable half; the
    # result row it names never changes.
    ForeignKeyConstraint(
        ("workspace_id", "last_result_fingerprint"),
        ("node_results.workspace_id", "node_results.fingerprint"),
        ondelete="RESTRICT",
    ),
    Index(
        "ix_instance_pointers_workspace_project",
        "workspace_id",
        "project_id",
    ),
)

project_runs = Table(
    "project_runs",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column("workspace_id", SaUuid(as_uuid=True), nullable=False),
    Column("project_id", SaUuid(as_uuid=True), nullable=False),
    Column("graph_id", String(255), nullable=False),
    # The JSON array of RunTarget objects; empty means the whole root Graph.
    Column("targets", JSON, nullable=False),
    Column(
        "started_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("status", String(32), nullable=False),
    CheckConstraint(
        f"status IN ({', '.join(repr(status) for status in _RUN_STATUSES)})",
        name="ck_project_runs_status_known",
    ),
    # A Run is running exactly while it has no finish stamp, mirroring the
    # RunStatus invariants the domain enforces in memory.
    CheckConstraint(
        "(status = 'running') = (finished_at IS NULL)",
        name="ck_project_runs_running_iff_unfinished",
    ),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("finished_at", UTCDateTime(), nullable=True),
    Column("error", Text, nullable=True),
    ForeignKeyConstraint(
        ("workspace_id", "project_id"),
        ("projects.workspace_id", "projects.id"),
        ondelete="CASCADE",
    ),
    Index(
        "ix_project_runs_workspace_project_created",
        "workspace_id",
        "project_id",
        "created_at",
    ),
    Index("ix_project_runs_status", "status"),
)
