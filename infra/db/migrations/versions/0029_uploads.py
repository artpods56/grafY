"""Replace local staged-upload rows with presigned upload records.

Staging used to be a local file plus an opaque ``upload_key`` row. An upload is
now a server-chosen identifier whose bytes live in object storage, so the old
rows cannot be carried across: their keys are not upload identifiers and their
bytes only ever existed under the deployment's local staging directory. The old
rows are also ephemeral by design, so the cutover requires an empty table
instead of inventing identifiers.

Revision ID: 0029_uploads
Revises: 0028_library_provenance
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029_uploads"
down_revision: str | Sequence[str] | None = "0028_library_provenance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _require_empty(connection: sa.Connection, table_names: tuple[str, ...]) -> None:
    populated = {
        table_name: connection.execute(
            sa.text(f"SELECT COUNT(*) FROM {table_name}")
        ).scalar_one()
        for table_name in table_names
    }
    populated = {name: count for name, count in populated.items() if count}
    if populated:
        detail = ", ".join(
            f"{table_name}={count}" for table_name, count in sorted(populated.items())
        )
        raise RuntimeError(
            f"The upload cutover requires empty staged-upload tables; found {detail}"
        )


def upgrade() -> None:
    _require_empty(op.get_bind(), ("staged_uploads",))
    op.create_table(
        "uploads",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("upload_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("bucket", sa.String(length=255), nullable=False),
        sa.Column("object_key", sa.String(length=1024), nullable=False),
        sa.Column("expected_size", sa.BigInteger(), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("actual_size", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("artifact_type", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "expected_size >= 0",
            name="ck_uploads_expected_size_nonnegative",
        ),
        sa.CheckConstraint(
            "actual_size IS NULL OR actual_size >= 0",
            name="ck_uploads_actual_size_nonnegative",
        ),
        sa.CheckConstraint(
            "length(original_filename) BETWEEN 1 AND 255",
            name="ck_uploads_original_filename_bounded",
        ),
        sa.CheckConstraint(
            "length(bucket) BETWEEN 1 AND 255",
            name="ck_uploads_bucket_bounded",
        ),
        sa.CheckConstraint(
            "length(object_key) BETWEEN 1 AND 1024",
            name="ck_uploads_object_key_bounded",
        ),
        sa.CheckConstraint(
            "sha256 IS NULL OR length(sha256) = 64",
            name="ck_uploads_sha256_length",
        ),
        sa.CheckConstraint(
            "artifact_type IS NULL OR length(artifact_type) BETWEEN 1 AND 255",
            name="ck_uploads_artifact_type_bounded",
        ),
        sa.CheckConstraint(
            "status <> 'ready' OR (completed_at IS NOT NULL AND actual_size IS NOT NULL)",
            name="ck_uploads_ready_is_complete",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_uploads_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_uploads_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "upload_id",
            name=op.f("pk_uploads"),
        ),
    )
    op.create_index(
        "ix_uploads_status_created_at",
        "uploads",
        ["status", "created_at"],
        unique=False,
    )
    op.drop_table("staged_uploads")


def downgrade() -> None:
    _require_empty(op.get_bind(), ("uploads",))
    op.create_table(
        "staged_uploads",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("upload_key", sa.String(length=1024), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "byte_size >= 0",
            name="ck_staged_uploads_byte_size_nonnegative",
        ),
        sa.CheckConstraint(
            "length(original_filename) BETWEEN 1 AND 255",
            name="ck_staged_uploads_original_filename_bounded",
        ),
        sa.CheckConstraint(
            "length(upload_key) BETWEEN 1 AND 1024",
            name="ck_staged_uploads_upload_key_bounded",
        ),
        sa.CheckConstraint(
            "upload_key NOT IN ('.', '..')",
            name="ck_staged_uploads_upload_key_not_dot_path",
        ),
        sa.CheckConstraint(
            "upload_key NOT LIKE '%/%'",
            name="ck_staged_uploads_upload_key_no_slash",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_staged_uploads_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_staged_uploads_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "upload_key",
            name=op.f("pk_staged_uploads"),
        ),
    )
    op.create_index(
        "ix_staged_uploads_workspace_created_at",
        "staged_uploads",
        ["workspace_id", "created_at"],
        unique=False,
    )
    op.drop_table("uploads")
