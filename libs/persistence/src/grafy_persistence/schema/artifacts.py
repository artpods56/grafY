from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
)
from sqlalchemy import Uuid as SaUuid

from grafy_persistence.column_types import (
    LibraryProvenanceType,
)

from .base import metadata

artifact_objects = Table(
    "artifact_objects",
    metadata,
    Column("id", SaUuid(as_uuid=True), primary_key=True),
    Column(
        "workspace_id",
        SaUuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("artifact_type", String(255), nullable=False),
    Column("schema_version", Integer, nullable=False),
    Column("content_type", String(255), nullable=False),
    Column("storage_backend", String(40), nullable=False),
    Column("bucket", String(255), nullable=True),
    Column("object_key", String(2048), nullable=True),
    Column("inline_payload", JSON, nullable=True),
    Column("byte_size", BigInteger, nullable=True),
    Column("sha256", String(64), nullable=True),
    Column("metadata", JSON, nullable=False),
    Column("library_provenance", LibraryProvenanceType(), nullable=True),
    UniqueConstraint("workspace_id", "id", name="uq_artifact_objects_workspace_id_id"),
    Index(
        "ix_artifact_objects_workspace_type",
        "workspace_id",
        "artifact_type",
        "schema_version",
    ),
    Index("ix_artifact_objects_workspace_sha256", "workspace_id", "sha256"),
)
