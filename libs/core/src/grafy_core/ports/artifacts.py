from collections.abc import Collection
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey


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


class UnitOfWorkPort(Protocol):
    @property
    def artifacts(self) -> ArtifactRepositoryPort: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
