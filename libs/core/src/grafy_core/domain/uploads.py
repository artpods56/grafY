from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID


def _utc_now() -> datetime:
    return datetime.now(UTC)


class UploadStatus(StrEnum):
    """Lifecycle state of one upload.

    ``PENDING`` uploads have a row and a target object key but no confirmed
    bytes. ``READY`` uploads passed completion validation and own a stored
    object. ``FAILED`` and ``EXPIRED`` uploads are terminal and only await
    cleanup. Transitions are terminal except ``PENDING`` advancing to one of
    the other states.
    """

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class Upload:
    """One client upload of a single file, promoted to an artifact on completion.

    ``upload_id`` is the client-facing opaque identifier. ``object_key`` is
    chosen by the server and is never derived from ``original_filename``; the
    filename is display metadata. A ``READY`` upload records the artifact it
    created so retrying completion can return the same result without
    re-inspecting bytes against a changed registration set.
    """

    workspace_id: UUID
    upload_id: UUID
    original_filename: str
    bucket: str
    object_key: str
    expected_size: int
    content_type: str | None = None
    created_by_user_id: UUID | None = None
    status: UploadStatus = UploadStatus.PENDING
    actual_size: int | None = None
    sha256: str | None = None
    artifact_type: str | None = None
    artifact_schema_version: int | None = None
    artifact_id: UUID | None = None
    created_at: datetime = field(default_factory=_utc_now)
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.original_filename.strip() == "":
            raise ValueError("Upload original filename must not be blank")
        if len(self.original_filename) > 255:
            raise ValueError("Upload original filename must be at most 255 characters")
        if self.bucket.strip() == "":
            raise ValueError("Upload bucket must not be blank")
        if len(self.bucket) > 255:
            raise ValueError("Upload bucket must be at most 255 characters")
        if self.object_key.strip() == "":
            raise ValueError("Upload object key must not be blank")
        if len(self.object_key) > 1024:
            raise ValueError("Upload object key must be at most 1024 characters")
        if self.expected_size < 0:
            raise ValueError("Upload expected size must not be negative")
        if self.actual_size is not None and self.actual_size < 0:
            raise ValueError("Upload actual size must not be negative")
        if self.sha256 is not None and len(self.sha256) != 64:
            raise ValueError("Upload digest must be 64 characters")
        if self.artifact_schema_version is not None and self.artifact_schema_version < 1:
            raise ValueError("Upload artifact schema version must be positive")
        if self.created_at.tzinfo is None:
            raise ValueError("Upload timestamp must be timezone-aware")
        if self.completed_at is not None and self.completed_at.tzinfo is None:
            raise ValueError("Upload completion timestamp must be timezone-aware")
        if self.status is UploadStatus.READY:
            if self.completed_at is None:
                raise ValueError("A ready upload requires a completion timestamp")
            if self.actual_size is None:
                raise ValueError("A ready upload requires an actual size")
            if self.sha256 is None:
                raise ValueError("A ready upload requires a digest")
            # Ingest completion records the resulting artifact so retries can
            # return the same response. Guest-bundle staging may omit those
            # fields because it never creates an ArtifactObject.
            if self.artifact_id is not None:
                if self.artifact_type is None:
                    raise ValueError("A ready upload with an artifact id requires an artifact type")
                if self.artifact_schema_version is None:
                    raise ValueError(
                        "A ready upload with an artifact id requires an artifact schema version"
                    )
