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

    async def list_library(self, workspace_id: UUID) -> list[ArtifactObject]: ...

    async def count_artifacts_sharing_object(
        self,
        workspace_id: UUID,
        *,
        bucket: str,
        object_key: str,
        except_artifact_id: UUID,
    ) -> int:
        """Count the workspace's other artifacts stored at the same object key.

        Stored content is addressed by digest, so two artifacts with identical
        bytes point at one object. The count is what says whether the object may
        be deleted with the artifact or has to stay for the others.
        """
        ...


class UnitOfWorkPort(TransactionPort, Protocol):
    @property
    def artifacts(self) -> ArtifactRepositoryPort: ...
