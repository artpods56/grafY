from collections.abc import Collection
from typing import Protocol
from uuid import UUID

from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey
from grafy_core.ports.transactions import TransactionPort


class ArtifactRepositoryPort(Protocol):
    async def add(self, artifact: ArtifactObject) -> None: ...

    async def get(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactObject | None: ...

    async def get_many(
        self,
        workspace_id: UUID,
        artifact_ids: Collection[UUID],
    ) -> dict[UUID, ArtifactObject]: ...

    async def remove(self, workspace_id: UUID, artifact: ArtifactObject) -> None: ...

    async def list_by_type(
        self,
        workspace_id: UUID,
        key: ArtifactTypeKey,
    ) -> list[ArtifactObject]: ...


class UnitOfWorkPort(TransactionPort, Protocol):
    @property
    def artifacts(self) -> ArtifactRepositoryPort: ...
