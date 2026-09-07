"""Add verified-email workspace invitations.

Revision ID: 0022_workspace_invitations
Revises: 0021_plugin_release_revocations
Create Date: 2026-08-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0022_workspace_invitations"
down_revision: str | Sequence[str] | None = "0021_plugin_release_revocations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("normalized_email", sa.String(length=320), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        sa.text(
            "UPDATE users SET normalized_email = lower(trim(email)) "
            "WHERE email IS NOT NULL"
        )
    )
    op.create_index(
        "ix_users_invitation_email",
        "users",
        ["normalized_email", "email_verified", "active"],
        unique=False,
    )

    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("invitee_user_id", sa.Uuid(), nullable=False),
        sa.Column("invited_by_user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "role IN ('viewer', 'editor', 'owner')",
            name=op.f("ck_workspace_invitations_role_choice"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'declined', 'cancelled', 'expired')",
            name=op.f("ck_workspace_invitations_status_choice"),
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND resolved_at IS NULL) OR "
            "(status != 'pending' AND resolved_at IS NOT NULL)",
            name=op.f("ck_workspace_invitations_resolution_shape"),
        ),
        sa.CheckConstraint(
            "expires_at > created_at",
            name=op.f("ck_workspace_invitations_expiry_after_creation"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_workspace_invitations_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invitee_user_id"],
            ["users.id"],
            name=op.f("fk_workspace_invitations_invitee_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by_user_id"],
            ["users.id"],
            name=op.f("fk_workspace_invitations_invited_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_workspace_invitations")),
    )
    op.create_index(
        "ix_workspace_invitations_invitee_status_expiry",
        "workspace_invitations",
        ["invitee_user_id", "status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_workspace_invitations_workspace_status_expiry",
        "workspace_invitations",
        ["workspace_id", "status", "expires_at"],
        unique=False,
    )
    op.create_index(
        "uq_workspace_invitations_pending_recipient",
        "workspace_invitations",
        ["workspace_id", "invitee_user_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    invitation_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM workspace_invitations")
    ).scalar_one()
    if invitation_count:
        raise RuntimeError(
            "Cannot downgrade 0022: workspace invitation history would be lost"
        )
    op.drop_index(
        "uq_workspace_invitations_pending_recipient",
        table_name="workspace_invitations",
    )
    op.drop_index(
        "ix_workspace_invitations_workspace_status_expiry",
        table_name="workspace_invitations",
    )
    op.drop_index(
        "ix_workspace_invitations_invitee_status_expiry",
        table_name="workspace_invitations",
    )
    op.drop_table("workspace_invitations")
    op.drop_index("ix_users_invitation_email", table_name="users")
    op.drop_column("users", "email_verified")
    op.drop_column("users", "normalized_email")
