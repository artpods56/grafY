"""Persist permanent exact Plugin release revocations.

Revision ID: 0021_plugin_release_revocations
Revises: 0020_plugin_release_selections
Create Date: 2026-08-24
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0021_plugin_release_revocations"
down_revision: str | Sequence[str] | None = "0020_plugin_release_selections"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SCOPED_IDENTITY_INDEX = "ix_plugin_release_revocations_scoped_identity"


def upgrade() -> None:
    op.create_table(
        "plugin_release_revocations",
        sa.Column("release_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=16), nullable=False),
        sa.Column("revoked_by_user_id", sa.Uuid(), nullable=True),
        sa.Column(
            "revoked_by_platform_actor",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column("revoked_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "scope IN ('system', 'workspace')",
            name="ck_plugin_release_revocations_revocation_scope",
        ),
        sa.CheckConstraint(
            "(scope = 'system' AND workspace_id IS NULL) OR "
            "(scope = 'workspace' AND workspace_id IS NOT NULL)",
            name="ck_plugin_release_revocations_revocation_scope_workspace",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_plugin_release_revocations_revocation_revision",
        ),
        sa.CheckConstraint(
            "reason IN ('security', 'integrity', 'policy', 'operational')",
            name="ck_plugin_release_revocations_revocation_reason",
        ),
        sa.CheckConstraint(
            "(scope = 'system' AND revoked_by_user_id IS NULL "
            "AND revoked_by_platform_actor IS NOT NULL "
            "AND length(trim(revoked_by_platform_actor)) BETWEEN 1 AND 255) OR "
            "(scope = 'workspace' AND revoked_by_user_id IS NOT NULL "
            "AND revoked_by_platform_actor IS NULL)",
            name="ck_plugin_release_revocations_revocation_actor",
        ),
        sa.ForeignKeyConstraint(
            ["release_id"],
            ["plugin_releases.id"],
            name=op.f(
                "fk_plugin_release_revocations_release_id_plugin_releases"
            ),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_plugin_release_revocations_workspace_id_workspaces"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["revoked_by_user_id"],
            ["users.id"],
            name=op.f("fk_plugin_release_revocations_revoked_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "release_id",
            name=op.f("pk_plugin_release_revocations"),
        ),
    )
    op.create_index(
        _SCOPED_IDENTITY_INDEX,
        "plugin_release_revocations",
        ["scope", "workspace_id", "slug", "revision"],
        unique=False,
    )


def downgrade() -> None:
    connection = op.get_bind()
    revocation_count = connection.execute(
        sa.text("SELECT COUNT(*) FROM plugin_release_revocations")
    ).scalar_one()
    if revocation_count:
        raise RuntimeError(
            "Cannot downgrade 0021: exact Plugin release revocations would be lost"
        )
    op.drop_index(
        _SCOPED_IDENTITY_INDEX,
        table_name="plugin_release_revocations",
    )
    op.drop_table("plugin_release_revocations")
