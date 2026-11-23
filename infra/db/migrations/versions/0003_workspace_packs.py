"""Workspace pack subscriptions and defaults for existing Workspaces."""

import sqlalchemy as sa
from alembic import op

revision = "0003_workspace_packs"
down_revision = "0002_credentials_and_selections"


def upgrade() -> None:
    op.create_table(
        "workspace_packs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("pack_slug", sa.String(80), nullable=False),
        sa.Column("enabled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("enabled_by_user_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["enabled_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("workspace_id", "pack_slug"),
    )
    op.execute(
        """
        INSERT INTO workspace_packs (workspace_id, pack_slug, enabled_at)
        SELECT id, defaults.pack_slug, CURRENT_TIMESTAMP
        FROM workspaces
        CROSS JOIN (
            SELECT 'essentials' AS pack_slug
            UNION ALL SELECT 'document_ocr'
        ) AS defaults
        """
    )


def downgrade() -> None:
    op.drop_table("workspace_packs")
