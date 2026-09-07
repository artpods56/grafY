"""Add workspace-qualified collaborative heads and command journals.

Revision ID: 0009_collaborative_graph_heads
Revises: 0008_tenant_existing_resources
Create Date: 2026-08-07
"""

from collections.abc import Sequence
import json
from uuid import UUID, uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "0009_collaborative_graph_heads"
down_revision: str | Sequence[str] | None = "0008_tenant_existing_resources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLLAB_TABLES = (
    "collaborative_graph_heads",
    "graph_command_journal",
    "graph_command_receipts",
    "graph_checkpoint_mappings",
    "graph_execution_idempotency",
    "graph_active_execution_slots",
)


def _table_exists(connection: sa.Connection, table_name: str) -> bool:
    return table_name in sa.inspect(connection).get_table_names()


def upgrade() -> None:
    connection = op.get_bind()
    if _table_exists(connection, "collaborative_graph_heads"):
        raise RuntimeError(
            "Cannot apply 0009: collaborative_graph_heads already exists"
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
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "collaboration_sequence >= 0",
            name="ck_collaborative_graph_heads_collaboration_sequence_nonneg",
        ),
        sa.CheckConstraint(
            "checkpoint_sequence >= 0",
            name="ck_collaborative_graph_heads_checkpoint_sequence_nonneg",
        ),
        sa.CheckConstraint(
            "checkpoint_sequence <= collaboration_sequence",
            name="ck_collaborative_graph_heads_checkpoint_lte_head",
        ),
        sa.CheckConstraint(
            "checkpoint_revision >= 1",
            name="ck_collaborative_graph_heads_checkpoint_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            ["saved_graphs.workspace_id", "saved_graphs.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "graph_id"),
    )
    op.create_index(
        "ix_collaborative_graph_heads_workspace_updated_at",
        "collaborative_graph_heads",
        ["workspace_id", "updated_at"],
    )

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
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "graph_id",
            "accepted_sequence",
        ),
        sa.UniqueConstraint(
            "workspace_id",
            "graph_id",
            "command_id",
            name="uq_graph_command_journal_command_id",
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
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "actor_kind IN ('user', 'system')",
            name="ck_graph_command_receipts_actor_kind",
        ),
        sa.CheckConstraint(
            "outcome IN ('accepted', 'idempotent_replay')",
            name="ck_graph_command_receipts_outcome",
        ),
        sa.CheckConstraint(
            "hmac_key_version >= 1",
            name="ck_graph_command_receipts_hmac_key_version",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            [
                "collaborative_graph_heads.workspace_id",
                "collaborative_graph_heads.graph_id",
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("workspace_id", "graph_id", "command_id"),
    )

    op.create_table(
        "graph_checkpoint_mappings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("graph_id", sa.Uuid(), nullable=False),
        sa.Column("room_epoch", sa.Uuid(), nullable=False),
        sa.Column("collaboration_sequence", sa.Integer(), nullable=False),
        sa.Column("saved_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "collaboration_sequence >= 0",
            name="ck_graph_checkpoint_mappings_sequence_nonneg",
        ),
        sa.CheckConstraint(
            "saved_revision >= 1",
            name="ck_graph_checkpoint_mappings_revision_positive",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id"],
            [
                "collaborative_graph_heads.workspace_id",
                "collaborative_graph_heads.graph_id",
            ],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "graph_id", "saved_revision"],
            [
                "saved_graph_revisions.workspace_id",
                "saved_graph_revisions.graph_id",
                "saved_graph_revisions.revision",
            ],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "graph_id",
            "room_epoch",
            "collaboration_sequence",
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
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "graph_id",
            "client_request_id",
        ),
    )

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

    graphs = connection.execute(
        sa.text(
            "SELECT workspace_id, id, name, document, revision, updated_at "
            "FROM saved_graphs"
        )
    ).mappings()
    insert_head = sa.text(
        "INSERT INTO collaborative_graph_heads ("
        "workspace_id, graph_id, room_epoch, collaboration_sequence, "
        "checkpoint_sequence, checkpoint_revision, name, document, updated_at"
        ") VALUES ("
        ":workspace_id, :graph_id, :room_epoch, 0, 0, :checkpoint_revision, "
        ":name, :document, :updated_at"
        ")"
    ).bindparams(
        sa.bindparam("workspace_id", type_=sa.Uuid()),
        sa.bindparam("graph_id", type_=sa.Uuid()),
        sa.bindparam("room_epoch", type_=sa.Uuid()),
    )
    for graph in graphs:
        document = graph["document"]
        if isinstance(document, str):
            document = json.loads(document)
        workspace_id = graph["workspace_id"]
        graph_id = graph["id"]
        if not isinstance(workspace_id, UUID):
            workspace_id = UUID(str(workspace_id))
        if not isinstance(graph_id, UUID):
            graph_id = UUID(str(graph_id))
        connection.execute(
            insert_head,
            {
                "workspace_id": workspace_id,
                "graph_id": graph_id,
                "room_epoch": uuid4(),
                "checkpoint_revision": graph["revision"],
                "name": graph["name"],
                "document": json.dumps(document),
                "updated_at": graph["updated_at"],
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    if _table_exists(connection, "graph_command_journal"):
        journal_count = connection.execute(
            sa.text("SELECT COUNT(*) FROM graph_command_journal")
        ).scalar_one()
        if journal_count:
            raise RuntimeError(
                "Cannot downgrade 0009 while graph_command_journal rows exist"
            )
    if _table_exists(connection, "collaborative_graph_heads"):
        uncheckpointed = connection.execute(
            sa.text(
                "SELECT COUNT(*) FROM collaborative_graph_heads "
                "WHERE collaboration_sequence != checkpoint_sequence"
            )
        ).scalar_one()
        if uncheckpointed:
            raise RuntimeError(
                "Cannot downgrade 0009 while uncheckpointed collaborative heads exist"
            )

    for table_name in reversed(_COLLAB_TABLES):
        if _table_exists(connection, table_name):
            op.drop_table(table_name)
