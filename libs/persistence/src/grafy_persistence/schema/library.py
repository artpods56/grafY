from grafy_core.domain.library import MAX_FOLDER_NAME_KEY_LENGTH
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    UniqueConstraint,
    text,
)
from sqlalchemy import Uuid as SaUuid

from grafy_persistence.column_types import UTCDateTime

from .base import metadata


library_folders = Table(
    "library_folders",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("parent_id", SaUuid(as_uuid=True), nullable=True),
    Column("name", String(160), nullable=False),
    # The domain folds the name before it stores the key, so the column has to
    # hold the widest folding a valid name can expand to, not the name's length.
    Column("name_key", String(MAX_FOLDER_NAME_KEY_LENGTH), nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    UniqueConstraint("workspace_id", "id", name="uq_library_folders_workspace_id_id"),
    ForeignKeyConstraint(
        ("workspace_id", "parent_id"),
        ("library_folders.workspace_id", "library_folders.id"),
        ondelete="RESTRICT",
        name="fk_library_folders_parent_id_library_folders",
    ),
    CheckConstraint(
        "parent_id IS NULL OR parent_id <> id",
        name="self_parent",
    ),
    # Sibling names are unique case-insensitively. One constraint over a
    # nullable parent_id would let Postgres file two root folders with one
    # name, so the root level and the child level get their own partial index.
    Index(
        "uq_library_folders_root_name",
        "workspace_id",
        "name_key",
        unique=True,
        sqlite_where=text("parent_id IS NULL"),
        postgresql_where=text("parent_id IS NULL"),
    ),
    Index(
        "uq_library_folders_child_name",
        "workspace_id",
        "parent_id",
        "name_key",
        unique=True,
        sqlite_where=text("parent_id IS NOT NULL"),
        postgresql_where=text("parent_id IS NOT NULL"),
    ),
    Index("ix_library_folders_workspace_parent", "workspace_id", "parent_id"),
)


library_artifact_placements = Table(
    "library_artifact_placements",
    metadata,
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("artifact_id", SaUuid(as_uuid=True), primary_key=True),
    Column("folder_id", SaUuid(as_uuid=True), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id", "artifact_id"),
        ("artifact_objects.workspace_id", "artifact_objects.id"),
        ondelete="CASCADE",
        name="fk_library_artifact_placements_artifact_object",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "folder_id"),
        ("library_folders.workspace_id", "library_folders.id"),
        ondelete="RESTRICT",
        name="fk_library_artifact_placements_library_folder",
    ),
    Index(
        "ix_library_artifact_placements_workspace_folder",
        "workspace_id",
        "folder_id",
    ),
)
