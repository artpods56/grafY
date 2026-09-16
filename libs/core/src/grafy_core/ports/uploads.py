from datetime import datetime
from typing import Protocol
from uuid import UUID

from grafy_core.domain.uploads import Upload, UploadStatus
from grafy_core.ports.artifacts import ArtifactRepositoryPort
from grafy_core.ports.transactions import TransactionPort


class UploadNotReadyError(RuntimeError):
    """An upload has no confirmed bytes yet and cannot be read."""


class UploadFinalizeFields(Protocol):
    actual_size: int
    sha256: str
    artifact_type: str
    artifact_schema_version: int
    artifact_id: UUID
    completed_at: datetime


class UploadRepositoryPort(Protocol):
    """Lifecycle rows for client uploads.

    Callers advance state through conditional transitions rather than loading a
    mutable row and committing. Each transition reports whether it won.
    """

    async def add(self, upload: Upload) -> None: ...

    async def get(self, workspace_id: UUID, upload_id: UUID) -> Upload | None: ...

    async def list_for_workspace(self, workspace_id: UUID) -> list[Upload]: ...

    async def finalize_if_pending(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        *,
        actual_size: int,
        sha256: str,
        artifact_type: str,
        artifact_schema_version: int,
        artifact_id: UUID,
        completed_at: datetime,
        not_older_than: datetime,
    ) -> Upload | None:
        """``PENDING → READY`` only when still pending and unexpired.

        Returns the finalized row when this caller wins, otherwise ``None``.
        """

        ...

    async def mark_terminal_if_pending(
        self,
        workspace_id: UUID,
        upload_id: UUID,
        *,
        status: UploadStatus,
    ) -> Upload | None:
        """``PENDING → FAILED|EXPIRED`` only when still pending.

        Returns the updated row when this caller wins, otherwise ``None``.
        """

        ...

    async def list_cleanup_candidates(
        self,
        *,
        pending_before: datetime,
        terminal_before: datetime,
        limit: int = 500,
    ) -> list[Upload]:
        """Pending rows past ``pending_before`` plus terminal rows past grace."""

        ...

    async def delete_terminal(self, workspace_id: UUID, upload_id: UUID) -> bool:
        """Delete one ``FAILED`` or ``EXPIRED`` tracking row after object cleanup."""

        ...


class UploadUnitOfWorkPort(TransactionPort, Protocol):
    @property
    def uploads(self) -> UploadRepositoryPort: ...

    @property
    def artifacts(self) -> ArtifactRepositoryPort: ...


class UploadReaderPort(Protocol):
    """Read the confirmed bytes of one upload.

    Hosts implement this from object storage; the Plugin guest implements it
    from the invocation bundle so one operator class serves both planes.
    """

    async def read(self, workspace_id: UUID, upload_id: UUID) -> bytes: ...
