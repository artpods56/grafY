"""Track transient execution activity for maintenance fences.

Revision ID: 0027_transient_executions
Revises: 0026_drop_plugin_distribution
"""

from alembic import op
import sqlalchemy as sa

revision = "0027_transient_executions"
down_revision = "0026_drop_plugin_distribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "transient_executions",
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("execution_id", name=op.f("pk_transient_executions")),
    )


def downgrade() -> None:
    op.drop_table("transient_executions")
