from datetime import datetime
from typing import Protocol
from uuid import UUID

from grafy_core.domain.uploads import Upload
from grafy_core.ports.artifacts import ArtifactRepositoryPort
from grafy_core.ports.transactions import TransactionPort


class UploadNotReadyError(RuntimeError):
    """An upload has no confirmed bytes yet and cannot be read."""


class UploadRepositoryPort(Protocol):
    """Lifecycle rows for client uploads.

    ``get`` returns the row owned by the current transaction rather than a
    detached copy, so callers advance an upload by mutating it and committing.
    Both adapters honour that, keeping completion and failure marking on one
    code path.
    """

    async def add(self, upload: Upload) -> None: ...

    async def get(self, workspace_id: UUID, upload_id: UUID) -> Upload | None: ...

    async def list_for_workspace(self, workspace_id: UUID) -> list[Upload]: ...

    async def list_abandoned_before(
        self,
        before: datetime,
        *,
        limit: int = 500,
    ) -> list[Upload]: ...

    async def discard(self, workspace_id: UUID, upload_id: UUID) -> bool:
        """Delete one upload only while it is still unpromoted.

        Returns whether the row was removed. Cleanup uses this to decide
        whether the stored bytes are safe to delete: a concurrent completion
        that promoted the upload wins the race, and its bytes survive.
        """

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
