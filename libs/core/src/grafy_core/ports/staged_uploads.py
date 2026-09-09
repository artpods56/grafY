from typing import Protocol
from uuid import UUID

from grafy_core.domain.staged_uploads import StagedUpload
from grafy_core.ports.transactions import TransactionPort


class StagedUploadRepositoryPort(Protocol):
    async def add(self, upload: StagedUpload) -> None: ...

    async def get(
        self,
        workspace_id: UUID,
        upload_key: str,
    ) -> StagedUpload | None: ...

    async def list_for_workspace(self, workspace_id: UUID) -> list[StagedUpload]: ...

    async def remove(self, workspace_id: UUID, upload_key: str) -> None: ...


class StagedUploadUnitOfWorkPort(TransactionPort, Protocol):
    @property
    def staged_uploads(self) -> StagedUploadRepositoryPort: ...
