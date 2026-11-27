from sqlalchemy import (
    JSON,
    Column,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    Text,
    Uuid,
)

from grafy_core.domain.feedback import (
    FeedbackClient,
    FeedbackElement,
    FeedbackKind,
    FeedbackStatus,
)
from grafy_persistence.column_types import (
    PydanticJSONType,
    StringEnumType,
    UTCDateTime,
)

from .base import metadata


class FeedbackKindType(StringEnumType[FeedbackKind]):
    impl = String(16)
    enum_type = FeedbackKind
    cache_ok = True


class FeedbackStatusType(StringEnumType[FeedbackStatus]):
    impl = String(16)
    enum_type = FeedbackStatus
    cache_ok = True


class FeedbackElementType(PydanticJSONType[FeedbackElement]):
    # A report without a picked element stores SQL NULL, not the JSON literal null.
    impl = JSON(none_as_null=True)
    model_type = FeedbackElement
    cache_ok = True


class FeedbackClientType(PydanticJSONType[FeedbackClient]):
    model_type = FeedbackClient
    cache_ok = True


feedback_reports = Table(
    "feedback_reports",
    metadata,
    Column("id", Uuid(), primary_key=True),
    Column(
        "reporter_user_id",
        Uuid(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column(
        "workspace_id",
        Uuid(),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("kind", FeedbackKindType(), nullable=False),
    Column("message", Text(), nullable=False),
    Column("page_path", String(2048), nullable=False),
    Column("element", FeedbackElementType(), nullable=True),
    Column("client", FeedbackClientType(), nullable=False),
    Column("screenshot_path", String(255), nullable=True),
    Column("screenshot_content_type", String(32), nullable=True),
    Column("screenshot_byte_size", Integer(), nullable=True),
    Column("status", FeedbackStatusType(), nullable=False),
    Column("resolved_at", UTCDateTime(), nullable=True),
    Column(
        "resolved_by_user_id",
        Uuid(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("github_issue_url", String(500), nullable=True),
    Column("created_at", UTCDateTime(), nullable=False),
    Index("ix_feedback_reports_created_at_id", "created_at", "id"),
    Index("ix_feedback_reports_reporter_created_at", "reporter_user_id", "created_at"),
)
