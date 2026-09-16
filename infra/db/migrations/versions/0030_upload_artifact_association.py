"""Associate completed uploads with the artifact they finalized.

Completion must return the same artifact on retry without re-resolving format
against a changed registration set. The association is recorded on the upload
row in the same transaction as the ``PENDING → READY`` transition. The link is
application-owned rather than a database foreign key so artifact insertion and
the conditional status update can share one transaction on SQLite.

Revision ID: 0030_upload_artifact_association
Revises: 0029_uploads
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030_upload_artifact_association"
down_revision: str | Sequence[str] | None = "0029_uploads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("uploads") as batch:
        batch.add_column(sa.Column("artifact_schema_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("artifact_id", sa.Uuid(), nullable=True))
        batch.create_check_constraint(
            "ck_uploads_artifact_schema_version_positive",
            "artifact_schema_version IS NULL OR artifact_schema_version >= 1",
        )
        batch.create_check_constraint(
            "ck_uploads_ready_has_artifact",
            (
                "status <> 'ready' OR ("
                "artifact_type IS NOT NULL AND "
                "artifact_schema_version IS NOT NULL AND "
                "artifact_id IS NOT NULL AND "
                "sha256 IS NOT NULL"
                ")"
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("uploads") as batch:
        batch.drop_constraint("ck_uploads_ready_has_artifact", type_="check")
        batch.drop_constraint(
            "ck_uploads_artifact_schema_version_positive",
            type_="check",
        )
        batch.drop_column("artifact_id")
        batch.drop_column("artifact_schema_version")
