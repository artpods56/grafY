from grafy_core.domain.module_library import ModulePublicationState
from grafy_core.domain.templates import TemplateState
from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SaUuid

from grafy_persistence.column_types import (
    SavedGraphDocumentType,
    StringEnumType,
    UTCDateTime,
)

from .base import metadata


class ModulePublicationStateType(StringEnumType[ModulePublicationState]):
    impl = String(32)
    enum_type = ModulePublicationState
    cache_ok = True


class TemplateStateType(StringEnumType[TemplateState]):
    impl = String(16)
    enum_type = TemplateState
    cache_ok = True


modules = Table(
    "modules",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("source_graph_id", SaUuid(as_uuid=True), nullable=False),
    Column("name", String(160), nullable=False),
    Column("description", String(1000), nullable=True),
    Column("publication_state", ModulePublicationStateType(), nullable=False),
    Column("current_library_release", Integer, nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    UniqueConstraint("workspace_id", "id", name="uq_modules_workspace_id_id"),
    UniqueConstraint(
        "workspace_id",
        "source_graph_id",
        name="uq_modules_workspace_source_graph",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "source_graph_id"),
        ("saved_graphs.workspace_id", "saved_graphs.id"),
        name="fk_modules_source_graph_id_saved_graphs",
    ),
    CheckConstraint(
        "publication_state IN ('published', 'deprecated', 'withdrawn')",
        name="module_publication_state",
    ),
    CheckConstraint(
        "current_library_release IS NULL OR current_library_release >= 1",
        name="module_current_library_release",
    ),
    Index("ix_modules_workspace_updated_at", "workspace_id", "updated_at"),
)


module_releases = Table(
    "module_releases",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("module_id", SaUuid(as_uuid=True), primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("source_graph_id", SaUuid(as_uuid=True), nullable=False),
    Column("published_at", UTCDateTime(), nullable=False),
    Column(
        "published_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    ForeignKeyConstraint(
        ("workspace_id", "module_id"),
        ("modules.workspace_id", "modules.id"),
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ("workspace_id", "source_graph_id", "revision"),
        (
            "saved_graph_revisions.workspace_id",
            "saved_graph_revisions.graph_id",
            "saved_graph_revisions.revision",
        ),
        ondelete="RESTRICT",
        name="fk_module_releases_saved_graph_revision",
    ),
    CheckConstraint("revision >= 1", name="module_release_revision"),
    Index(
        "ix_module_releases_workspace_module_revision",
        "workspace_id",
        "module_id",
        "revision",
    ),
)


templates = Table(
    "templates",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("source_graph_id", SaUuid(as_uuid=True), nullable=False),
    Column("source_revision", Integer, nullable=False),
    Column("source_graph_name", String(160), nullable=False),
    Column("snapshot_document", SavedGraphDocumentType(), nullable=False),
    Column("name", String(160), nullable=False),
    Column("description", String(1000), nullable=True),
    Column("state", TemplateStateType(), nullable=False),
    Column(
        "created_by_user_id",
        SaUuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("updated_at", UTCDateTime(), nullable=False),
    UniqueConstraint("workspace_id", "id", name="uq_templates_workspace_id_id"),
    CheckConstraint("source_revision >= 1", name="template_source_revision"),
    CheckConstraint(
        "state IN ('active', 'archived')",
        name="template_state",
    ),
    Index("ix_templates_workspace_name", "workspace_id", "name"),
    Index("ix_templates_workspace_updated_at", "workspace_id", "updated_at"),
)
