from collections.abc import Collection
from typing import override
from uuid import UUID
from sqlalchemy import (
    delete,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey
from grafy_core.ports.artifacts import ArtifactRepositoryPort
from grafy_core.domain.staged_uploads import StagedUpload
from grafy_core.ports.staged_uploads import StagedUploadRepositoryPort
from grafy_persistence import schema


class SqlArtifactRepository(ArtifactRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, artifact: ArtifactObject) -> None:
        self._session.add(artifact)

    @override
    async def get(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
    ) -> ArtifactObject | None:
        return await self._session.scalar(
            select(ArtifactObject).where(
                schema.artifact_objects.c.workspace_id == workspace_id,
                schema.artifact_objects.c.id == artifact_id,
            )
        )

    @override
    async def get_many(
        self,
        workspace_id: UUID,
        artifact_ids: Collection[UUID],
    ) -> dict[UUID, ArtifactObject]:
        if not artifact_ids:
            return {}
        result = await self._session.scalars(
            select(ArtifactObject).where(
                schema.artifact_objects.c.id.in_(set(artifact_ids)),
                schema.artifact_objects.c.workspace_id == workspace_id,
            )
        )
        return {artifact.id: artifact for artifact in result}

    @override
    async def remove(self, workspace_id: UUID, artifact: ArtifactObject) -> None:
        await self._session.execute(
            delete(schema.artifact_objects).where(
                schema.artifact_objects.c.workspace_id == workspace_id,
                schema.artifact_objects.c.id == artifact.id,
            )
        )

    @override
    async def list_by_type(
        self,
        workspace_id: UUID,
        key: ArtifactTypeKey,
    ) -> list[ArtifactObject]:
        result = await self._session.scalars(
            select(ArtifactObject)
            .where(
                schema.artifact_objects.c.artifact_type == key.id,
                schema.artifact_objects.c.schema_version == key.schema_version,
                schema.artifact_objects.c.workspace_id == workspace_id,
            )
            .order_by(schema.artifact_objects.c.id.asc())
        )
        return list(result)


class SqlStagedUploadRepository(StagedUploadRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, upload: StagedUpload) -> None:
        self._session.add(upload)

    @override
    async def get(
        self,
        workspace_id: UUID,
        upload_key: str,
    ) -> StagedUpload | None:
        return await self._session.get(StagedUpload, (workspace_id, upload_key))

    @override
    async def list_for_workspace(self, workspace_id: UUID) -> list[StagedUpload]:
        result = await self._session.scalars(
            select(StagedUpload)
            .where(schema.staged_uploads.c.workspace_id == workspace_id)
            .order_by(
                schema.staged_uploads.c.created_at.asc(),
                schema.staged_uploads.c.upload_key.asc(),
            )
        )
        return list(result)

    @override
    async def remove(self, workspace_id: UUID, upload_key: str) -> None:
        await self._session.execute(
            delete(schema.staged_uploads).where(
                schema.staged_uploads.c.workspace_id == workspace_id,
                schema.staged_uploads.c.upload_key == upload_key,
            )
        )
