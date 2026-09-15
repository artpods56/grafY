from sqlalchemy import (
    JSON,
    BigInteger,
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
    LibraryProvenanceType,
    UTCDateTime,
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


staged_uploads = Table(
    "staged_uploads",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("upload_key", String(1024), primary_key=True),
    Column(
        "created_by_user_id",
        SaUuid(as_uuid=True),
        nullable=True,
    ),
    Column("original_filename", String(255), nullable=False),
    Column("byte_size", BigInteger, nullable=False),
    Column("created_at", UTCDateTime(), nullable=False),
    ForeignKeyConstraint(
        ("workspace_id",),
        ("workspaces.id",),
        ondelete="CASCADE",
    ),
    ForeignKeyConstraint(
        ("created_by_user_id",),
        ("users.id",),
        ondelete="SET NULL",
    ),
    CheckConstraint("byte_size >= 0", name="ck_staged_uploads_byte_size_nonnegative"),
    CheckConstraint(
        "length(original_filename) BETWEEN 1 AND 255",
        name="ck_staged_uploads_original_filename_bounded",
    ),
    CheckConstraint(
        "length(upload_key) BETWEEN 1 AND 1024",
        name="ck_staged_uploads_upload_key_bounded",
    ),
    CheckConstraint(
        "upload_key NOT IN ('.', '..')",
        name="ck_staged_uploads_upload_key_not_dot_path",
    ),
    CheckConstraint(
        "upload_key NOT LIKE '%/%'",
        name="ck_staged_uploads_upload_key_no_slash",
    ),
    CheckConstraint(
        "instr(upload_key, char(92)) = 0",
        name="ck_staged_uploads_upload_key_no_backslash",
    ).ddl_if(dialect="sqlite"),
    CheckConstraint(
        "position(chr(92) in upload_key) = 0",
        name="ck_staged_uploads_upload_key_no_backslash",
    ).ddl_if(dialect="postgresql"),
    CheckConstraint(
        "instr(upload_key, char(0)) = 0",
        name="ck_staged_uploads_upload_key_no_nul",
    ).ddl_if(dialect="sqlite"),
    Index("ix_staged_uploads_workspace_created_at", "workspace_id", "created_at"),
)
