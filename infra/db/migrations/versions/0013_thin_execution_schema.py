"""Thin the execution and collaboration schema to 27 tables.

Revision ID: 0013_thin_execution_schema
Revises: 0012_template_library
Create Date: 2026-08-23

Deletes the unused ``graph_execution_idempotency`` table, replaces the
``graph_active_execution_slots`` mutex with a partial unique index on
``graph_executions.status``, deletes the write-only ``graph_command_journal``
(the complete collaborative head remains the recovery representation), and
merges ``graph_execution_requested_nodes`` plus ``graph_execution_node_results``
into one monotonic ``graph_execution_nodes`` table.
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0013_thin_execution_schema"
down_revision: str | Sequence[str] | None = "0012_template_library"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ACTIVE_STATUSES_SQL = "status IN ('queued', 'running', 'cancelling')"


def upgrade() -> None:
    connection = op.get_bind()

    duplicate_actives = (
        connection.execute(
            sa.text(
                "SELECT workspace_id, graph_id, COUNT(*) AS n "
                "FROM graph_executions "
                f"WHERE {_ACTIVE_STATUSES_SQL} "
                "GROUP BY workspace_id, graph_id HAVING COUNT(*) > 1"
            )
        )
        .mappings()
        .all()
    )
    if duplicate_actives:
        details = ", ".join(
            f"workspace={row['workspace_id']} graph={row['graph_id']} "
            f"active_executions={row['n']}"
            for row in duplicate_actives
        )
        raise RuntimeError(
            "Cannot apply 0013: these workspace graphs already have multiple "
            f"queued/running/cancelling executions: {details}. Resolve the "
            "conflicting executions before migrating; none is chosen "
            "automatically."
        )

    orphan_results = (
        connection.execute(
            sa.text(
                "SELECT r.workspace_id, r.execution_id, r.node_id "
                "FROM graph_execution_node_results r "
                "WHERE NOT EXISTS ("
                "  SELECT 1 FROM graph_execution_requested_nodes q"
                "  WHERE q.workspace_id = r.workspace_id"
                "    AND q.execution_id = r.execution_id"
                "    AND q.node_id = r.node_id)"
            )
        )
        .mappings()
        .all()
    )
    if orphan_results:
        details = ", ".join(
            f"execution={row['execution_id']} node={row['node_id']!r}"
            for row in orphan_results[:10]
        )
        raise RuntimeError(
            "Cannot apply 0013: node results exist without a matching "
            f"requested node: {details}"
        )

    op.create_table(
        "graph_execution_nodes",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("result_status", sa.String(length=16), nullable=True),
        sa.Column("result_position", sa.Integer(), nullable=True),
        sa.Column("outputs", sa.JSON(), nullable=True),
        sa.Column("artifact_count", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "(result_status IS NULL AND result_position IS NULL AND outputs IS NULL "
            "AND artifact_count IS NULL AND completed_at IS NULL) OR "
            "(result_status IN ('succeeded', 'failed', 'skipped') "
            "AND result_position IS NOT NULL AND outputs IS NOT NULL "
            "AND artifact_count IS NOT NULL AND artifact_count >= 0 "
            "AND completed_at IS NOT NULL)",
            name="ck_graph_execution_nodes_result_shape",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "execution_id"],
            ["graph_executions.workspace_id", "graph_executions.execution_id"],
            name="fk_exec_nodes_workspace_execution",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "execution_id", "node_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "execution_id",
            "position",
            name="uq_graph_execution_nodes_execution_position",
        ),
    )
    # Request position keeps the stable request order; result_position keeps
    # the terminal-result ordering previously stored by
    # graph_execution_node_results.position (compiled-plan visit order).
    connection.execute(
        sa.text(
            "INSERT INTO graph_execution_nodes ("
            "workspace_id, execution_id, node_id, position, result_status, "
            "result_position, outputs, artifact_count, error, completed_at) "
            "SELECT q.workspace_id, q.execution_id, q.node_id, q.position, "
            "r.status, r.position, r.outputs, r.artifact_count, r.error, "
            "r.completed_at "
            "FROM graph_execution_requested_nodes q "
            "LEFT JOIN graph_execution_node_results r "
            "ON r.workspace_id = q.workspace_id "
            "AND r.execution_id = q.execution_id "
            "AND r.node_id = q.node_id"
        )
    )

    requested_total = connection.execute(
        sa.text("SELECT COUNT(*) FROM graph_execution_requested_nodes")
    ).scalar_one()
    unified_total = connection.execute(
        sa.text("SELECT COUNT(*) FROM graph_execution_nodes")
    ).scalar_one()
    if unified_total != requested_total:
        raise RuntimeError(
            "Cannot apply 0013: requested-node copy lost rows "
            f"({requested_total} source rows became {unified_total})"
        )
    result_total = connection.execute(
        sa.text("SELECT COUNT(*) FROM graph_execution_node_results")
    ).scalar_one()
    unified_terminal = connection.execute(
        sa.text(
            "SELECT COUNT(*) FROM graph_execution_nodes WHERE result_status IS NOT NULL"
        )
    ).scalar_one()
    if unified_terminal != result_total:
        raise RuntimeError(
            "Cannot apply 0013: terminal-result copy lost rows "
            f"({result_total} source rows became {unified_terminal})"
        )

    op.drop_table("graph_execution_requested_nodes")
    op.drop_table("graph_execution_node_results")
    op.create_index(
        "uq_graph_execution_nodes_execution_result_position",
        "graph_execution_nodes",
        ["workspace_id", "execution_id", "result_position"],
        unique=True,
        sqlite_where=sa.text("result_position IS NOT NULL"),
        postgresql_where=sa.text("result_position IS NOT NULL"),
    )
    op.create_index(
        "ix_graph_execution_nodes_node_execution",
        "graph_execution_nodes",
        ["workspace_id", "node_id", "execution_id"],
    )

    op.create_index(
        "uq_graph_executions_one_active_per_graph",
        "graph_executions",
        ["workspace_id", "graph_id"],
        unique=True,
        sqlite_where=sa.text(_ACTIVE_STATUSES_SQL),
        postgresql_where=sa.text(_ACTIVE_STATUSES_SQL),
    )
    op.drop_table("graph_active_execution_slots")

    # Journal and execution-idempotency history is intentionally destroyed:
    # journal replay was never a supported capability and the idempotency
    # store had no application callers.
    op.drop_table("graph_execution_idempotency")
    op.drop_table("graph_command_journal")


def downgrade() -> None:
    op.drop_index(
        "ix_graph_execution_nodes_node_execution",
        table_name="graph_execution_nodes",
    )
    op.drop_index(
        "uq_graph_execution_nodes_execution_result_position",
        table_name="graph_execution_nodes",
    )

    # Journal and execution-idempotency history was destroyed by the upgrade:
    # this downgrade recreates both shapes empty and cannot recover rows.
    op.create_table(
        "graph_command_journal",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("accepted_sequence", sa.Integer(), nullable=False),
        sa.Column("room_epoch", sa.Uuid(), nullable=False),
        sa.Column("command_id", sa.Uuid(), nullable=False),
        sa.Column("command_hmac", sa.LargeBinary(length=64), nullable=False),
        sa.Column("hmac_key_version", sa.Integer(), nullable=False),
        sa.Column("actor_kind", sa.String(length=32), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("graph_room_session_id", sa.Uuid(), nullable=True),
        sa.Column("authorization_version", sa.Integer(), nullable=True),
        sa.Column("command_kind", sa.String(length=80), nullable=False),
        sa.Column("command_payload", sa.JSON(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "actor_kind IN ('user', 'system')",
            name="ck_graph_command_journal_actor_kind",
        ),
        sa.CheckConstraint(
            "hmac_key_version >= 1",
            name="ck_graph_command_journal_hmac_key_version",
        ),
        sa.CheckConstraint(
            "accepted_sequence >= 1",
            name="ck_graph_command_journal_accepted_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            [
                "collaborative_graph_heads.workspace_id",
                "collaborative_graph_heads.graph_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "graph_id", "accepted_sequence"),
        sa.UniqueConstraint(
            "workspace_id",
            "graph_id",
            "command_id",
            name="uq_graph_command_journal_command_id",
        ),
    )
    op.create_table(
        "graph_execution_idempotency",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("client_request_id", sa.Uuid(), nullable=False),
        sa.Column("request_hmac", sa.LargeBinary(length=64), nullable=False),
        sa.Column("hmac_key_version", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("room_epoch", sa.Uuid(), nullable=False),
        sa.Column("head_sequence", sa.Integer(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "hmac_key_version >= 1",
            name="ck_graph_execution_idempotency_hmac_key_version",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            [
                "collaborative_graph_heads.workspace_id",
                "collaborative_graph_heads.graph_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "graph_id", "client_request_id"),
    )

    _recreate_split_tables()

    op.create_table(
        "graph_active_execution_slots",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            [
                "collaborative_graph_heads.workspace_id",
                "collaborative_graph_heads.graph_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "graph_id"),
    )

    op.drop_index(
        "uq_graph_executions_one_active_per_graph",
        table_name="graph_executions",
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "INSERT INTO graph_execution_requested_nodes "
            "(workspace_id, execution_id, node_id, position) "
            "SELECT workspace_id, execution_id, node_id, position "
            "FROM graph_execution_nodes"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO graph_execution_node_results "
            "(workspace_id, execution_id, node_id, position, status, outputs, "
            "artifact_count, error, completed_at) "
            "SELECT workspace_id, execution_id, node_id, result_position, "
            "result_status, outputs, artifact_count, error, completed_at "
            "FROM graph_execution_nodes WHERE result_status IS NOT NULL"
        )
    )
    connection.execute(
        sa.text(
            "INSERT INTO graph_active_execution_slots "
            "(workspace_id, graph_id, execution_id, updated_at) "
            "SELECT workspace_id, graph_id, execution_id, "
            "COALESCE(started_at, created_at) "
            f"FROM graph_executions WHERE {_ACTIVE_STATUSES_SQL}"
        )
    )
    op.drop_table("graph_execution_nodes")

    op.create_index(
        "ix_graph_execution_requested_nodes_node_execution",
        "graph_execution_requested_nodes",
        ["workspace_id", "node_id", "execution_id"],
    )
    op.create_index(
        "ix_graph_execution_node_results_node_execution",
        "graph_execution_node_results",
        ["workspace_id", "node_id", "execution_id"],
    )


def _recreate_split_tables() -> None:
    """Recreate the pre-0013 requested-node and node-result table shapes."""
    op.create_table(
        "graph_execution_requested_nodes",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "execution_id"],
            ["graph_executions.workspace_id", "graph_executions.execution_id"],
            name="fk_exec_req_nodes_workspace_execution",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "execution_id", "node_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "execution_id",
            "position",
            name="uq_graph_execution_requested_nodes_execution_position",
        ),
    )
    op.create_table(
        "graph_execution_node_results",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.String(length=255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("outputs", sa.JSON(), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id", "execution_id"],
            ["graph_executions.workspace_id", "graph_executions.execution_id"],
            name="fk_exec_result_nodes_workspace_execution",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "execution_id", "node_id"),
        sa.UniqueConstraint(
            "workspace_id",
            "execution_id",
            "position",
            name="uq_graph_execution_node_results_execution_position",
        ),
    )
