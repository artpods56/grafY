import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Protocol, Self
from uuid import UUID

from grafy_core.artifacts import ArtifactObject
from grafy_core.node_context import UserFacingNodeError
from grafy_core.domain.identity import WorkspaceAccess, WorkspaceCapability
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.text_regions import TiffPage
from grafy_shared.config.tiler import TilerConfig
from pydantic import BaseModel, ConfigDict, Field, model_validator

from grafy_api.artifacts.models import ImageInfoResponse

IMAGE_CACHE_CONTROL = "private, max-age=300"

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

    def get_etag(
        self, *, operation: str, edge: int | None, tiler_renderer_version: str
    ) -> str:
        fingerprint = json.dumps(
            [
                self.sha256,
                self.byte_size,
                self.page,
                operation,
                edge,
                tiler_renderer_version,
            ],
            separators=(",", ":"),
        )
        return '"' + hashlib.sha256(fingerprint.encode()).hexdigest() + '"'


@dataclass(frozen=True, slots=True)
class TilerImage:
    body: bytes
    content_type: str


class WindowCoordinates(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)

    col: int = Field(ge=0)
    row: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class WindowPlacement(WindowCoordinates):
    """Source window and optional crop-local pixel-corner to CRS affine."""

    model_config = ConfigDict(allow_inf_nan=False)

    affine: tuple[float, float, float, float, float, float] | None
    crs: str | None = Field(min_length=1)

    @model_validator(mode="after")
    def _check_georeference(self) -> Self:
        if (self.affine is None) != (self.crs is None):
            raise ValueError("affine and CRS must be present together")
        return self


@dataclass(frozen=True, slots=True)
class TilerWindow:
    body: bytes  # image/png
    placement: WindowPlacement


class TilerPort(Protocol):
    """Renders stored TIFFs. Failures are raised as ImageProxyError."""

    async def info(self, source: TiffSource) -> ImageInfoResponse: ...

    async def tile(
        self, source: TiffSource, *, z: int, x: int, y: int, extension: TileExtension
    ) -> TilerImage: ...

    async def thumbnail(self, source: TiffSource, *, edge: int) -> TilerImage: ...

    async def read_window(
        self, source: TiffSource, *, col: int, row: int, width: int, height: int
    ) -> TilerWindow: ...

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

    async def read_window(
        self,
        access: WorkspaceAccess,
        artifact_id: UUID,
        *,
        col: int,
        row: int,
        width: int,
        height: int,
        page: int = 0,
    ) -> TilerWindow:
        """Read a native window. Acquire access via VIEW_ARTIFACTS authorization."""
        access.require(WorkspaceCapability.VIEW_ARTIFACTS)
        return await self._read_window(
            access.workspace_id,
            artifact_id,
            page=page,
            col=col,
            row=row,
            width=width,
            height=height,
        )

    async def open_run_tiff_page(
        self, workspace_id: UUID, artifact_id: UUID, *, page: int
    ) -> TiffPage:
        """Resolve a Run input once before issuing concurrent native reads."""
        try:
            source = await self._window_source(workspace_id, artifact_id, page=page)
            info = await self._tiler.info(source)
            # A window's affine is local to its corner, so the one at (0, 0)
            # is the page's own pixel-to-CRS transform.
            origin = await self._tiler.read_window(
                source, col=0, row=0, width=1, height=1
            )
        except ImageProxyError as exc:
            raise UserFacingNodeError(f"Could not open the TIFF page: {exc}") from exc

        async def read(*, col: int, row: int, width: int, height: int) -> bytes:
            try:
                window = await self._tiler.read_window(
                    source, col=col, row=row, width=width, height=height
                )
            except ImageProxyError as exc:
                raise UserFacingNodeError(
                    f"Could not read the TIFF window at ({col}, {row}): {exc}"
                ) from exc
            return window.body

        return TiffPage(
            info.width,
            info.height,
            read,
            source_sha256=source.sha256,
            page=page,
            affine=origin.placement.affine,
            crs=origin.placement.crs,
        )

    async def _window_source(
        self, workspace_id: UUID, artifact_id: UUID, *, page: int
    ) -> TiffSource:
        async with self._uow as uow:
            artifact = await uow.artifacts.get(workspace_id, artifact_id)
            if artifact is None:
                raise ImageProxyError(404, "Artifact not found")
            if artifact.content_type.partition(";")[0].strip().lower() != "image/tiff":
                raise ImageProxyError(415, "Pixel windows require a TIFF artifact")
            source = _stored_tiff_source(artifact, page=page)

        if self._config.tiler_url is None:
            raise ImageProxyError(501, "TIFF rendering is disabled")
        return source

    async def _read_window(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        *,
        page: int,
        col: int,
        row: int,
        width: int,
        height: int,
    ) -> TilerWindow:
        source = await self._window_source(workspace_id, artifact_id, page=page)
        return await self._tiler.read_window(
            source, col=col, row=row, width=width, height=height
        )

    async def info(
        self,
        workspace_id: UUID,
        artifact_id: UUID,
        *,
        page: int,
        if_none_match: str | None,
    ) -> ImageRead:
        async with self._uow as uow:
            source = _tiff_from_artifact(
                await uow.artifacts.get(workspace_id, artifact_id), page=page
            )

        if self._config.tiler_url is None:
            raise ImageProxyError(501, "TIFF rendering is disabled")

        etag = source.get_etag(
            operation="info",
            edge=None,
            tiler_renderer_version=self._config.tiler_renderer_version,
        )

        if _matches_current_etag(if_none_match, etag):
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
        async with self._uow as uow:
            source = _tiff_from_artifact(
                await uow.artifacts.get(workspace_id, artifact_id), page=page
            )

        if self._config.tiler_url is None:
            raise ImageProxyError(501, "TIFF rendering is disabled")

        etag = source.get_etag(
            operation=f"tiles/{z}/{x}/{y}.{extension}",
            edge=None,
            tiler_renderer_version=self._config.tiler_renderer_version,
        )

        if _matches_current_etag(if_none_match, etag):
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
        async with self._uow as uow:
            source = _tiff_from_artifact(
                await uow.artifacts.get(workspace_id, artifact_id), page=page
            )

        if self._config.tiler_url is None:
            raise ImageProxyError(501, "TIFF rendering is disabled")

        etag = source.get_etag(
            operation="thumbnail",
            edge=edge,
            tiler_renderer_version=self._config.tiler_renderer_version,
        )

        if _matches_current_etag(if_none_match, etag):
            return ImageRead(b"", "", etag, not_modified=True)

        image = await self._tiler.thumbnail(source, edge=edge)

        return ImageRead(image.body, image.content_type, etag)


def _matches_current_etag(if_none_match: str | None, etag: str) -> bool:
    # check if have this resource
    if if_none_match is None:
        return False

    for candidate in if_none_match.split(","):
        if candidate.strip().removeprefix("W/") in {etag, "*"}:
            return True

    return False


def _tiff_from_artifact(artifact: ArtifactObject | None, *, page: int) -> TiffSource:
    if artifact is None:
        raise ImageProxyError(404, "Artifact not found")
    if artifact.content_type != "image/tiff":
        raise ImageProxyError(415, "Image tiles require a TIFF artifact")
    return _stored_tiff_source(artifact, page=page)


def _stored_tiff_source(artifact: ArtifactObject, *, page: int) -> TiffSource:
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
