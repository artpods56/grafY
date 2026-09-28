"""Give the Workspace Library a folder tree the user owns.

ADR 0010 made the Library browser a tree the workspace owns, and the web app has
been filing it in `localStorage` behind ``NEXT_PUBLIC_LIBRARY_FOLDERS_API``.
Two tables: ``library_folders`` is the tree (``parent_id`` of ``NULL`` is the
root), and ``library_artifact_placements`` records which folder an artifact sits
in. A missing placement row is the root, and the placement cascade-deletes with
the artifact, so a deleted artifact never leaves a dangling filing.

Sibling names are unique case-insensitively through ``name_key``, written by the
domain. A single unique constraint over the nullable ``parent_id`` would let
Postgres file two root folders under one name, so the root level and the child
level each get their own partial unique index.

Revision ID: 0031_library_folders
Revises: 0030_upload_artifact_association
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031_library_folders"
down_revision: str | Sequence[str] | None = "0030_upload_artifact_association"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "library_folders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        # A valid 160-character name can casefold to 480 characters, so `name_key`
        # is that wide in schema/library.py and here.
        sa.Column("name_key", sa.String(length=480), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_library_folders_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "parent_id"],
            ["library_folders.workspace_id", "library_folders.id"],
            name="fk_library_folders_parent_id_library_folders",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id",
            name="self_parent",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_library_folders")),
        sa.UniqueConstraint(
            "workspace_id",
            "id",
            name=op.f("uq_library_folders_workspace_id_id"),
        ),
    )
    op.create_index(
        "uq_library_folders_root_name",
        "library_folders",
        ["workspace_id", "name_key"],
        unique=True,
        sqlite_where=sa.text("parent_id IS NULL"),
        postgresql_where=sa.text("parent_id IS NULL"),
    )
    op.create_index(
        "uq_library_folders_child_name",
        "library_folders",
        ["workspace_id", "parent_id", "name_key"],
        unique=True,
        sqlite_where=sa.text("parent_id IS NOT NULL"),
        postgresql_where=sa.text("parent_id IS NOT NULL"),
    )
    op.create_index(
        op.f("ix_library_folders_workspace_parent"),
        "library_folders",
        ["workspace_id", "parent_id"],
        unique=False,
    )
    op.create_table(
        "library_artifact_placements",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("artifact_id", sa.Uuid(), nullable=False),
        sa.Column("folder_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f(
                "fk_library_artifact_placements_workspace_id_workspaces"
            ),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "artifact_id"],
            ["artifact_objects.workspace_id", "artifact_objects.id"],
            name="fk_library_artifact_placements_artifact_object",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "folder_id"],
            ["library_folders.workspace_id", "library_folders.id"],
            name="fk_library_artifact_placements_library_folder",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "workspace_id",
            "artifact_id",
            name=op.f("pk_library_artifact_placements"),
        ),
    )
    op.create_index(
        op.f("ix_library_artifact_placements_workspace_folder"),
        "library_artifact_placements",
        ["workspace_id", "folder_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_library_artifact_placements_workspace_folder"),
        table_name="library_artifact_placements",
    )
    op.drop_table("library_artifact_placements")
    op.drop_index(
        op.f("ix_library_folders_workspace_parent"),
        table_name="library_folders",
    )
    op.drop_index("uq_library_folders_child_name", table_name="library_folders")
    op.drop_index("uq_library_folders_root_name", table_name="library_folders")
    op.drop_table("library_folders")
