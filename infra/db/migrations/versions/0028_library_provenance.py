"""Record how a Library artifact came to be.

Only the Library provenance snapshot is added here. The Library placement
columns from #25 (folder tree, saved-by) do not exist yet, so a non-null
``library_provenance`` is the whole marker that an artifact is in the Library.

Revision ID: 0028_library_provenance
Revises: 0027_transient_executions
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0028_library_provenance"
down_revision: str | Sequence[str] | None = "0027_transient_executions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "artifact_objects",
        sa.Column("library_provenance", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("artifact_objects", "library_provenance")
