"""Add credentials for authenticated platform publication operations.

Revision ID: 0025_platform_access_tokens
Revises: 0024_plugin_installations
Create Date: 2026-08-27
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0025_platform_access_tokens"
down_revision: str | Sequence[str] | None = "0024_plugin_installations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "platform_access_tokens",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("principal_reference", sa.String(length=120), nullable=False),
        sa.Column("public_prefix", sa.String(length=32), nullable=False),
        sa.Column("secret_digest", sa.LargeBinary(length=64), nullable=False),
        sa.Column("label", sa.String(length=160), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_platform_access_tokens")),
        sa.UniqueConstraint(
            "public_prefix", name="uq_platform_access_tokens_public_prefix"
        ),
        sa.UniqueConstraint(
            "secret_digest", name="uq_platform_access_tokens_secret_digest"
        ),
    )
    op.create_index(
        "ix_platform_access_tokens_principal_revoked",
        "platform_access_tokens",
        ["principal_reference", "revoked_at"],
        unique=False,
    )
    op.create_index(
        "ix_platform_access_tokens_expiry_revoked",
        "platform_access_tokens",
        ["expires_at", "revoked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_platform_access_tokens_expiry_revoked",
        table_name="platform_access_tokens",
    )
    op.drop_index(
        "ix_platform_access_tokens_principal_revoked",
        table_name="platform_access_tokens",
    )
    op.drop_table("platform_access_tokens")
