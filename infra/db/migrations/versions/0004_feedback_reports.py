"""Feedback reports people send from the app, triaged by deployment operators."""

import sqlalchemy as sa
from alembic import op
from grafy_persistence.column_types import UTCDateTime
from grafy_persistence.schema.feedback import (
    FeedbackClientType,
    FeedbackElementType,
    FeedbackKindType,
    FeedbackStatusType,
)

revision = "0004_feedback_reports"
down_revision = "0003_workspace_packs"


def upgrade() -> None:
    op.create_table(
        "feedback_reports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("reporter_user_id", sa.Uuid(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("kind", FeedbackKindType(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("page_path", sa.String(length=2048), nullable=False),
        sa.Column("element", FeedbackElementType(), nullable=True),
        sa.Column("client", FeedbackClientType(), nullable=False),
        sa.Column("screenshot_path", sa.String(length=255), nullable=True),
        sa.Column("screenshot_content_type", sa.String(length=32), nullable=True),
        sa.Column("screenshot_byte_size", sa.Integer(), nullable=True),
        sa.Column("status", FeedbackStatusType(), nullable=False),
        sa.Column("resolved_at", UTCDateTime(), nullable=True),
        sa.Column("resolved_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("github_issue_url", sa.String(length=500), nullable=True),
        sa.Column("created_at", UTCDateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["reporter_user_id"],
            ["users.id"],
            name=op.f("fk_feedback_reports_reporter_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_feedback_reports_workspace_id_workspaces"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_user_id"],
            ["users.id"],
            name=op.f("fk_feedback_reports_resolved_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_feedback_reports")),
    )
    op.create_index(
        "ix_feedback_reports_created_at_id",
        "feedback_reports",
        ["created_at", "id"],
        unique=False,
    )
    op.create_index(
        "ix_feedback_reports_reporter_created_at",
        "feedback_reports",
        ["reporter_user_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_feedback_reports_reporter_created_at", table_name="feedback_reports"
    )
    op.drop_index("ix_feedback_reports_created_at_id", table_name="feedback_reports")
    op.drop_table("feedback_reports")
