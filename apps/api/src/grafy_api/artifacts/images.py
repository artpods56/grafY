"""Workspace-scoped TIFF reads through the deployment's internal tiler."""

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_shared.config.tiler import TilerConfig

from grafy_api.artifacts.models import ImageInfoResponse

IMAGE_CACHE_CONTROL = "private, no-cache"

TileExtension = Literal["png", "jpg"]


class ImageProxyError(Exception):
    def __init__(
        self, status: int, detail: str, retry_after: str | None = None
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class ImageRead:
    body: bytes
    content_type: str
    etag: str
    not_modified: bool = False


@dataclass(frozen=True, slots=True)
class TiffSource:
    """One page of one stored TIFF the caller is already allowed to read."""

    bucket: str
    key: str
    sha256: str
    byte_size: int
    page: int


@dataclass(frozen=True, slots=True)
class TilerImage:
    body: bytes
    content_type: str


class TilerPort(Protocol):
    """Renders stored TIFFs. Failures are raised as ImageProxyError."""

    async def info(self, source: TiffSource) -> ImageInfoResponse: ...

    async def tile(
        self, source: TiffSource, *, z: int, x: int, y: int, extension: TileExtension
    ) -> TilerImage: ...

    async def thumbnail(self, source: TiffSource, *, edge: int) -> TilerImage: ...

    async def close(self) -> None: ...


class ArtifactImageService:
    def __init__(
        self, uow: UnitOfWorkPort, config: TilerConfig, tiler: TilerPort
    ) -> None:
        self._uow = uow
        self._config = config
        self._tiler = tiler

    async def close(self) -> None:
        await self._tiler.close()

    async def info(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        *,
        page: int,
        if_none_match: str | None,
    ) -> ImageRead:
        source = await self._source(workspace_id, artifact_id, page)
        etag = self._etag(source, "info", None)
        if _matches(if_none_match, etag):
            return ImageRead(b"", "", etag, not_modified=True)
        info = await self._tiler.info(source)
        return ImageRead(info.model_dump_json().encode(), "application/json", etag)

    async def tile(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        *,
        z: int,
        x: int,
        y: int,
        extension: TileExtension,
        page: int,
        if_none_match: str | None,
    ) -> ImageRead:
        source = await self._source(workspace_id, artifact_id, page)
        etag = self._etag(source, f"tiles/{z}/{x}/{y}.{extension}", None)
        if _matches(if_none_match, etag):
            return ImageRead(b"", "", etag, not_modified=True)
        image = await self._tiler.tile(source, z=z, x=x, y=y, extension=extension)
        return ImageRead(image.body, image.content_type, etag)

    async def thumbnail(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        *,
        edge: int,
        page: int,
        if_none_match: str | None,
    ) -> ImageRead:
        source = await self._source(workspace_id, artifact_id, page)
        etag = self._etag(source, "thumbnail", edge)
        if _matches(if_none_match, etag):
            return ImageRead(b"", "", etag, not_modified=True)
        image = await self._tiler.thumbnail(source, edge=edge)
        return ImageRead(image.body, image.content_type, etag)

    async def _source(
        self, workspace_id: UUID, artifact_id: UUID, page: int
    ) -> TiffSource:
        async with self._uow as uow:
            artifact = await uow.artifacts.get(workspace_id, artifact_id)
        if artifact is None:
            raise ImageProxyError(404, "Artifact not found")
        if artifact.content_type != "image/tiff":
            raise ImageProxyError(415, "Image tiles require a TIFF artifact")
        if self._config.tiler_url is None:
            raise ImageProxyError(501, "TIFF rendering is disabled")
        if (
            not artifact.bucket
            or not artifact.object_key
            or not artifact.sha256
            or artifact.byte_size is None
            or artifact.byte_size < 1
        ):
            raise ImageProxyError(422, "TIFF artifact has no stored source")
        return TiffSource(
            bucket=artifact.bucket,
            key=artifact.object_key,
            sha256=artifact.sha256,
            byte_size=artifact.byte_size,
            page=page,
        )

    def _etag(self, source: TiffSource, operation: str, edge: int | None) -> str:
        fingerprint = json.dumps(
            [
                source.sha256,
                source.byte_size,
                source.page,
                operation,
                edge,
                self._config.tiler_renderer_version,
            ],
            separators=(",", ":"),
        )
        return '"' + hashlib.sha256(fingerprint.encode()).hexdigest() + '"'


def _matches(if_none_match: str | None, etag: str) -> bool:
    return if_none_match is not None and any(
        candidate.strip().removeprefix("W/") in {etag, "*"}
        for candidate in if_none_match.split(",")
    )
