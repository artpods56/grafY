"""Add durable agent-authoring control-plane state.

Revision ID: 0013_agent_authoring
Revises: 0012_template_library
Create Date: 2026-08-16
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0013_agent_authoring"
down_revision: str | Sequence[str] | None = "0012_template_library"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_environments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("profile_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_environment_id", sa.String(length=1024), nullable=True),
        sa.Column("provisioning_owner", sa.String(length=255), nullable=True),
        sa.Column("provisioning_token", sa.Uuid(), nullable=True),
        sa.Column("provisioning_expires_at", sa.DateTime(), nullable=True),
        sa.Column("provisioning_fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("active_run_id", sa.Uuid(), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('provisioning', 'creating', 'ready', 'suspended', 'failed', "
            "'archived')",
            name="ck_agent_environments_status",
        ),
        sa.CheckConstraint(
            "provisioning_fencing_token >= 0",
            name="ck_agent_environments_provisioning_fencing_token",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_agent_environments_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_environments_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_environments")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_agent_environments_workspace_id_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "name",
            name="uq_agent_environments_workspace_name",
        ),
    )
    op.create_index(
        "ix_agent_environments_provision_queue",
        "agent_environments",
        ["status", "provisioning_expires_at", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_environments_workspace_updated",
        "agent_environments",
        ["workspace_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "agent_threads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("event_sequence", sa.BigInteger(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "event_sequence >= 0",
            name="ck_agent_threads_event_sequence",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_agent_threads_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "environment_id"],
            ["agent_environments.workspace_id", "agent_environments.id"],
            name="fk_agent_threads_environment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_threads_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_threads")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_agent_threads_workspace_id_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            "environment_id",
            name="uq_agent_threads_workspace_id_environment",
        ),
    )
    op.create_index(
        "ix_agent_threads_workspace_updated",
        "agent_threads",
        ["workspace_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "draft_nodes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.String(length=1000), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("anchor", sa.JSON(), nullable=False),
        sa.Column("build_attempt_number", sa.Integer(), nullable=False),
        sa.Column("published_revision", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "build_attempt_number >= 0",
            name="ck_draft_nodes_build_attempt_number",
        ),
        sa.CheckConstraint(
            "published_revision >= 0",
            name="ck_draft_nodes_published_revision",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'authoring', 'awaiting_approval', 'published', "
            "'failed', 'cancelled')",
            name="ck_draft_nodes_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_draft_nodes_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["saved_graphs.workspace_id", "saved_graphs.id"],
            name="fk_draft_nodes_graph",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "thread_id"],
            ["agent_threads.workspace_id", "agent_threads.id"],
            name="fk_draft_nodes_thread",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_draft_nodes_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_draft_nodes")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_draft_nodes_workspace_id_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            "thread_id",
            name="uq_draft_nodes_workspace_id_thread",
        ),
    )
    op.create_index(
        "ix_draft_nodes_workspace_graph",
        "draft_nodes",
        ["workspace_id", "graph_id"],
        unique=False,
    )
    op.create_index(
        "ix_draft_nodes_workspace_thread",
        "draft_nodes",
        ["workspace_id", "thread_id", "updated_at"],
        unique=False,
    )

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("target_draft_ids", sa.JSON(), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_digest", sa.String(length=64), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("continued_from_run_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("cancellation_requested_at", sa.DateTime(), nullable=True),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_token", sa.Uuid(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("lease_heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("terminal_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "fencing_token >= 0",
            name="ck_agent_runs_fencing_token",
        ),
        sa.CheckConstraint("attempt >= 0", name="ck_agent_runs_attempt"),
        sa.CheckConstraint(
            "status IN ('queued', 'claimed', 'running', 'awaiting_approval', "
            "'completed', 'failed', 'cancelling', 'cancelled', 'interrupting', "
            "'interrupted')",
            name="ck_agent_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_agent_runs_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "continued_from_run_id"],
            ["agent_runs.workspace_id", "agent_runs.id"],
            name="fk_agent_runs_continued_from_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "thread_id", "environment_id"],
            [
                "agent_threads.workspace_id",
                "agent_threads.id",
                "agent_threads.environment_id",
            ],
            name="fk_agent_runs_thread_environment",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_runs_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_agent_runs_workspace_id_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            "thread_id",
            name="uq_agent_runs_workspace_id_thread",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "idempotency_key",
            name="uq_agent_runs_workspace_idempotency",
        ),
    )
    active_run_predicate = sa.text(
        "status IN ('claimed', 'running', 'cancelling', 'interrupting')"
    )
    op.create_index(
        "uq_agent_runs_active_environment",
        "agent_runs",
        ["workspace_id", "environment_id"],
        unique=True,
        postgresql_where=active_run_predicate,
        sqlite_where=active_run_predicate,
    )
    op.create_index(
        "ix_agent_runs_claim_queue",
        "agent_runs",
        ["status", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_runs_expiring_lease",
        "agent_runs",
        ["status", "lease_expires_at"],
        unique=False,
    )

    op.create_table(
        "node_build_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("draft_node_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=True),
        sa.Column("capabilities", sa.JSON(), nullable=True),
        sa.Column("capability_digest", sa.String(length=64), nullable=True),
        sa.Column("artifacts", sa.JSON(), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "attempt_number >= 1",
            name="ck_node_build_attempts_attempt_number",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'preparing', 'coding', 'testing', "
            "'awaiting_approval', 'failed', 'cancelled', 'superseded', "
            "'published')",
            name="ck_node_build_attempts_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_node_id", "thread_id"],
            ["draft_nodes.workspace_id", "draft_nodes.id", "draft_nodes.thread_id"],
            name="fk_node_build_attempts_draft_thread",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id", "thread_id"],
            ["agent_runs.workspace_id", "agent_runs.id", "agent_runs.thread_id"],
            name="fk_node_build_attempts_run_thread",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_node_build_attempts_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_node_build_attempts")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_node_build_attempts_workspace_id_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            "draft_node_id",
            name="uq_node_build_attempts_identity_draft",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "draft_node_id",
            "attempt_number",
            name="uq_node_build_attempts_draft_attempt",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            "draft_node_id",
            "thread_id",
            name="uq_node_build_attempts_identity_context",
        ),
    )
    active_build_predicate = sa.text(
        "status IN ('queued', 'preparing', 'coding', 'testing', 'awaiting_approval')"
    )
    op.create_index(
        "uq_node_build_attempts_active_draft",
        "node_build_attempts",
        ["workspace_id", "draft_node_id"],
        unique=True,
        postgresql_where=active_build_predicate,
        sqlite_where=active_build_predicate,
    )
    op.create_index(
        "ix_node_build_attempts_run",
        "node_build_attempts",
        ["workspace_id", "run_id", "attempt_number"],
        unique=False,
    )

    op.create_table(
        "agent_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_agent_events_sequence"),
        sa.ForeignKeyConstraint(
            ["workspace_id", "run_id", "thread_id"],
            [
                "agent_runs.workspace_id",
                "agent_runs.id",
                "agent_runs.thread_id",
            ],
            name="fk_agent_events_run_thread",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "thread_id"],
            ["agent_threads.workspace_id", "agent_threads.id"],
            name="fk_agent_events_thread",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_agent_events_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_events")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_agent_events_workspace_id_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "thread_id",
            "sequence",
            name="uq_agent_events_thread_sequence",
        ),
    )
    op.create_index(
        "ix_agent_events_workspace_run",
        "agent_events",
        ["workspace_id", "run_id", "sequence"],
        unique=False,
    )

    op.create_table(
        "capability_approvals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("draft_node_id", sa.Uuid(), nullable=False),
        sa.Column("build_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("capability_digest", sa.String(length=64), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["users.id"],
            name=op.f("fk_capability_approvals_approved_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "build_attempt_id", "draft_node_id"],
            [
                "node_build_attempts.workspace_id",
                "node_build_attempts.id",
                "node_build_attempts.draft_node_id",
            ],
            name="fk_capability_approvals_build_draft",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_capability_approvals_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_capability_approvals")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name="uq_capability_approvals_workspace_id_id",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            "build_attempt_id",
            "draft_node_id",
            "approved_by_user_id",
            "capability_digest",
            name="uq_capability_approvals_identity_context",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "build_attempt_id",
            name="uq_capability_approvals_build_attempt",
        ),
    )

    op.create_table(
        "node_releases",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("draft_node_id", sa.Uuid(), nullable=False),
        sa.Column("build_attempt_id", sa.Uuid(), nullable=False),
        sa.Column("capability_approval_id", sa.Uuid(), nullable=False),
        sa.Column("thread_id", sa.Uuid(), nullable=False),
        sa.Column("environment_id", sa.Uuid(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("capability_digest", sa.String(length=64), nullable=False),
        sa.Column("artifacts", sa.JSON(), nullable=False),
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_node_releases_revision"),
        sa.CheckConstraint(
            "node_id = draft_node_id",
            name="ck_node_releases_node_is_draft",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["users.id"],
            name=op.f("fk_node_releases_approved_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_node_releases_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "build_attempt_id",
                "draft_node_id",
                "thread_id",
            ],
            [
                "node_build_attempts.workspace_id",
                "node_build_attempts.id",
                "node_build_attempts.draft_node_id",
                "node_build_attempts.thread_id",
            ],
            name="fk_node_releases_build_context",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "workspace_id",
                "capability_approval_id",
                "build_attempt_id",
                "draft_node_id",
                "approved_by_user_id",
                "capability_digest",
            ],
            [
                "capability_approvals.workspace_id",
                "capability_approvals.id",
                "capability_approvals.build_attempt_id",
                "capability_approvals.draft_node_id",
                "capability_approvals.approved_by_user_id",
                "capability_approvals.capability_digest",
            ],
            name="fk_node_releases_capability_approval_context",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "draft_node_id"],
            ["draft_nodes.workspace_id", "draft_nodes.id"],
            name="fk_node_releases_draft",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "thread_id", "environment_id"],
            [
                "agent_threads.workspace_id",
                "agent_threads.id",
                "agent_threads.environment_id",
            ],
            name="fk_node_releases_thread_environment",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_node_releases_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "node_id",
            "revision",
            name=op.f("pk_node_releases"),
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "build_attempt_id",
            name="uq_node_releases_build_attempt",
        ),
    )
    op.create_index(
        "ix_node_releases_workspace_node_revision",
        "node_releases",
        ["workspace_id", "node_id", "revision"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_node_releases_workspace_node_revision",
        table_name="node_releases",
    )
    op.drop_table("node_releases")
    op.drop_table("capability_approvals")
    op.drop_index("ix_agent_events_workspace_run", table_name="agent_events")
    op.drop_table("agent_events")
    op.drop_index(
        "ix_node_build_attempts_run",
        table_name="node_build_attempts",
    )
    op.drop_index(
        "uq_node_build_attempts_active_draft",
        table_name="node_build_attempts",
    )
    op.drop_table("node_build_attempts")
    op.drop_index("ix_agent_runs_expiring_lease", table_name="agent_runs")
    op.drop_index("ix_agent_runs_claim_queue", table_name="agent_runs")
    op.drop_index("uq_agent_runs_active_environment", table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_draft_nodes_workspace_thread", table_name="draft_nodes")
    op.drop_index("ix_draft_nodes_workspace_graph", table_name="draft_nodes")
    op.drop_table("draft_nodes")
    op.drop_index("ix_agent_threads_workspace_updated", table_name="agent_threads")
    op.drop_table("agent_threads")
    op.drop_index(
        "ix_agent_environments_workspace_updated",
        table_name="agent_environments",
    )
    op.drop_index(
        "ix_agent_environments_provision_queue",
        table_name="agent_environments",
    )
    op.drop_table("agent_environments")
