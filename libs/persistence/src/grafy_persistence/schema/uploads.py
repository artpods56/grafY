from grafy_core.domain.uploads import UploadStatus
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
)
from sqlalchemy import Uuid as SaUuid

from grafy_persistence.column_types import (
    StringEnumType,
    UTCDateTime,
)

from .base import metadata


class UploadStatusType(StringEnumType[UploadStatus]):
    impl = String(16)
    enum_type = UploadStatus
    cache_ok = True


uploads = Table(
    "uploads",
    metadata,
    Column("workspace_id", SaUuid(as_uuid=True), primary_key=True),
    Column("upload_id", SaUuid(as_uuid=True), primary_key=True),
    Column("original_filename", String(255), nullable=False),
    Column("bucket", String(255), nullable=False),
    Column("object_key", String(1024), nullable=False),
    Column("expected_size", BigInteger, nullable=False),
    Column("content_type", String(255), nullable=True),
    Column(
        "created_by_user_id",
        SaUuid(as_uuid=True),
        nullable=True,
    ),
    Column("status", UploadStatusType(), nullable=False),
    Column("actual_size", BigInteger, nullable=True),
    Column("sha256", String(64), nullable=True),
    Column("artifact_type", String(255), nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Column("completed_at", UTCDateTime(), nullable=True),
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
    CheckConstraint("expected_size >= 0", name="ck_uploads_expected_size_nonnegative"),
    CheckConstraint(
        "actual_size IS NULL OR actual_size >= 0",
        name="ck_uploads_actual_size_nonnegative",
    ),
    CheckConstraint(
        "length(original_filename) BETWEEN 1 AND 255",
        name="ck_uploads_original_filename_bounded",
    ),
    CheckConstraint(
        "length(bucket) BETWEEN 1 AND 255",
        name="ck_uploads_bucket_bounded",
    ),
    CheckConstraint(
        "length(object_key) BETWEEN 1 AND 1024",
        name="ck_uploads_object_key_bounded",
    ),
    CheckConstraint(
        "sha256 IS NULL OR length(sha256) = 64",
        name="ck_uploads_sha256_length",
    ),
    CheckConstraint(
        "artifact_type IS NULL OR length(artifact_type) BETWEEN 1 AND 255",
        name="ck_uploads_artifact_type_bounded",
    ),
    CheckConstraint(
        "status <> 'ready' OR (completed_at IS NOT NULL AND actual_size IS NOT NULL)",
        name="ck_uploads_ready_is_complete",
    ),
    Index("ix_uploads_status_created_at", "status", "created_at"),
)
