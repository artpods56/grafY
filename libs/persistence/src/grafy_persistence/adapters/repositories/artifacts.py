from collections.abc import Collection
from datetime import datetime
from typing import cast, override
from uuid import UUID

from grafy_core.artifacts import ArtifactObject, ArtifactTypeKey
from grafy_core.domain.uploads import Upload, UploadStatus
from grafy_core.ports.artifacts import ArtifactRepositoryPort
from grafy_core.ports.uploads import UploadRepositoryPort
from sqlalchemy import (
    CursorResult,
    delete,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession

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

    @override
    async def list_library(self, workspace_id: UUID) -> list[ArtifactObject]:
        result = await self._session.scalars(
            select(ArtifactObject)
            .where(
                schema.artifact_objects.c.workspace_id == workspace_id,
                schema.artifact_objects.c.library_provenance.is_not(None),
            )
            .order_by(schema.artifact_objects.c.id.asc())
        )
        return list(result)


class SqlUploadRepository(UploadRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, upload: Upload) -> None:
        self._session.add(upload)

    @override
    async def get(
        self,
        workspace_id: UUID,
        upload_id: UUID,
    ) -> Upload | None:
        return await self._session.get(Upload, (workspace_id, upload_id))

    @override
    async def list_for_workspace(self, workspace_id: UUID) -> list[Upload]:
        result = await self._session.scalars(
            select(Upload)
            .where(schema.uploads.c.workspace_id == workspace_id)
            .order_by(
                schema.uploads.c.created_at.asc(),
                schema.uploads.c.upload_id.asc(),
            )
        )
        return list(result)

    @override
    async def list_abandoned_before(
        self,
        before: datetime,
        *,
        limit: int = 500,
    ) -> list[Upload]:
        result = await self._session.scalars(
            select(Upload)
            .where(
                schema.uploads.c.created_at < before,
                schema.uploads.c.status.in_(
                    (UploadStatus.PENDING, UploadStatus.FAILED, UploadStatus.EXPIRED)
                ),
            )
            .order_by(schema.uploads.c.created_at.asc())
            .limit(limit)
        )
        return list(result)

    @override
    async def discard(self, workspace_id: UUID, upload_id: UUID) -> bool:
        result = cast(
            CursorResult[tuple[object, ...]],
            await self._session.execute(
                delete(schema.uploads).where(
                    schema.uploads.c.workspace_id == workspace_id,
                    schema.uploads.c.upload_id == upload_id,
                    schema.uploads.c.status != UploadStatus.READY,
                )
            ),
        )
        return result.rowcount > 0
