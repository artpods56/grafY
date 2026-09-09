from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy import Uuid as SaUuid

from grafy_persistence.column_types import ArtifactOutputsType, UTCDateTime

from .base import metadata

invocation_cache_entries = Table(
    "invocation_cache_entries",
    metadata,
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("key_sha256", String(64), primary_key=True),
    Column("generation", SaUuid(as_uuid=True), nullable=False),
    Column("outputs", ArtifactOutputsType(), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
)


materialized_node_outputs = Table(
    "materialized_node_outputs",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "graph_id",
        SaUuid(as_uuid=True),
        primary_key=True,
    ),
    Column("graph_revision", Integer, primary_key=True),
    Column("node_id", String(255), primary_key=True),
    Column("workflow_run_id", SaUuid(as_uuid=True), nullable=False),
    Column("outputs", ArtifactOutputsType(), nullable=False),
    Column("materialized_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id", "graph_revision"),
        (
            "saved_graph_revisions.workspace_id",
            "saved_graph_revisions.graph_id",
            "saved_graph_revisions.revision",
        ),
        ondelete="CASCADE",
    ),
    Index(
        "ix_materialized_node_outputs_graph_revision",
        "workspace_id",
        "graph_id",
        "graph_revision",
        "materialized_at",
    ),
)


graph_executions = Table(
    "graph_executions",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), nullable=False),
    Column("execution_id", SaUuid(as_uuid=True), primary_key=True),
    Column("graph_id", SaUuid(as_uuid=True), nullable=False),
    Column("graph_revision", Integer, nullable=False),
    Column("status", String(24), nullable=False),
    Column("scope", String(32), nullable=False),
    Column("submitted_request", JSON, nullable=True),
    Column("idempotency_key", String(255), nullable=True),
    Column("submitted_by_actor_id", SaUuid(as_uuid=True), nullable=True),
    Column("workflow_run_id", SaUuid(as_uuid=True), nullable=True),
    Column("error", Text, nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("started_at", UTCDateTime(), nullable=True),
    Column("finished_at", UTCDateTime(), nullable=True),
    ForeignKeyConstraint(
        ("workspace_id", "graph_id", "graph_revision"),
        (
            "saved_graph_revisions.workspace_id",
            "saved_graph_revisions.graph_id",
            "saved_graph_revisions.revision",
        ),
        ondelete="CASCADE",
    ),
    UniqueConstraint(
        "workspace_id",
        "execution_id",
        name="uq_graph_executions_workspace_id_execution_id",
    ),
    UniqueConstraint(
        "workspace_id",
        "idempotency_key",
        name="uq_graph_executions_workspace_idempotency_key",
    ),
    Index(
        "ix_graph_executions_graph_created",
        "workspace_id",
        "graph_id",
        "created_at",
        "execution_id",
    ),
    Index(
        "ix_graph_executions_graph_revision_created",
        "workspace_id",
        "graph_id",
        "graph_revision",
        "created_at",
        "execution_id",
    ),
    Index("ix_graph_executions_workspace_status", "workspace_id", "status"),
    Index(
        "ix_graph_executions_queue_order",
        "status",
        "created_at",
        "execution_id",
    ),
    Index(
        "uq_graph_executions_one_active_per_graph",
        "workspace_id",
        "graph_id",
        unique=True,
        sqlite_where=text("status IN ('queued', 'running', 'cancelling')"),
        postgresql_where=text("status IN ('queued', 'running', 'cancelling')"),
    ),
)


graph_execution_nodes = Table(
    "graph_execution_nodes",
    metadata,
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        primary_key=True,
    ),
    Column(
        "execution_id",
        SaUuid(as_uuid=True),
        primary_key=True,
    ),
    Column("node_id", String(255), primary_key=True),
    Column("position", Integer, nullable=False),
    Column("result_status", String(16), nullable=True),
    Column("result_position", Integer, nullable=True),
    Column("outputs", ArtifactOutputsType(), nullable=True),
    Column("artifact_count", Integer, nullable=True),
    Column("error", Text, nullable=True),
    Column("diagnostics", JSON, nullable=True),
    Column("completed_at", UTCDateTime(), nullable=True),
    ForeignKeyConstraint(
        ("workspace_id", "execution_id"),
        ("graph_executions.workspace_id", "graph_executions.execution_id"),
        name="fk_exec_nodes_workspace_execution",
        ondelete="CASCADE",
    ),
    CheckConstraint(
        "(result_status IS NULL AND result_position IS NULL AND outputs IS NULL "
        "AND artifact_count IS NULL AND diagnostics IS NULL "
        "AND completed_at IS NULL) OR "
        "(result_status IN ('succeeded', 'failed', 'skipped') "
        "AND result_position IS NOT NULL AND outputs IS NOT NULL "
        "AND artifact_count IS NOT NULL AND artifact_count >= 0 "
        "AND completed_at IS NOT NULL)",
        name="ck_graph_execution_nodes_result_shape",
    ),
    UniqueConstraint(
        "workspace_id",
        "execution_id",
        "position",
        name="uq_graph_execution_nodes_execution_position",
    ),
    Index(
        "uq_graph_execution_nodes_execution_result_position",
        "workspace_id",
        "execution_id",
        "result_position",
        unique=True,
        sqlite_where=text("result_position IS NOT NULL"),
        postgresql_where=text("result_position IS NOT NULL"),
    ),
    Index(
        "ix_graph_execution_nodes_node_execution",
        "workspace_id",
        "node_id",
        "execution_id",
    ),
)


transient_executions = Table(
    "transient_executions",
    metadata,
    Column("execution_id", SaUuid(as_uuid=True), primary_key=True),
    Column("workspace_id", SaUuid(as_uuid=True), nullable=False),
    Column("owner_id", SaUuid(as_uuid=True), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
)
