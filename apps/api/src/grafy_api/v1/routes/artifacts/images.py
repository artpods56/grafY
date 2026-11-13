from collections.abc import Awaitable
from typing import Annotated, Literal, get_args
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Path, Query
from fastapi.responses import Response

from grafy_core.domain.identity import WorkspaceAccess, WorkspaceCapability

from grafy_api.artifacts.images import IMAGE_CACHE_CONTROL, ImageProxyError, ImageRead
from grafy_api.artifacts.models import ImageInfoResponse
from grafy_api.v1.routes.artifacts.dependencies import ArtifactImageDependency
from grafy_api.v1.routes.auth.dependencies import require_workspace_capability

router = APIRouter(
    prefix="/workspaces/{workspace_id}/artifacts/{artifact_id}/image",
    tags=["workbench"],
    responses={
        304: {"description": "Image has not changed"},
        401: {"description": "Authentication required"},
        403: {"description": "View artifacts capability required"},
        404: {"description": "Artifact, page or tile not found"},
        409: {"description": "Stored source does not match the artifact"},
        413: {"description": "Source exceeds rendering limits"},
        415: {"description": "Artifact is not a TIFF"},
        422: {"description": "Invalid parameters or unreadable TIFF"},
        501: {"description": "TIFF rendering is disabled"},
        502: {"description": "Invalid response from the tiler"},
        503: {"description": "Tiler unavailable or busy; retry later"},
    },
)
ViewArtifacts = Annotated[
    WorkspaceAccess,
    get_args(require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS))[1],
]
Page = Annotated[int, Query(ge=0, le=1023)]
Conditional = Annotated[str | None, Header(alias="If-None-Match")]


async def image_response(read: Awaitable[ImageRead]) -> Response:
    try:
        result = await read
    except ImageProxyError as exc:
        raise HTTPException(
            exc.status,
            str(exc),
            headers={"Retry-After": exc.retry_after} if exc.retry_after else None,
        ) from exc
    return Response(
        result.body,
        status_code=304 if result.not_modified else 200,
        media_type=result.content_type or None,
        headers={"ETag": result.etag, "Cache-Control": IMAGE_CACHE_CONTROL},
    )


@router.get("/info", response_model=ImageInfoResponse)
async def image_info(
    artifact_id: UUID,
    service: ArtifactImageDependency,
    access: ViewArtifacts,
    page: Page = 0,
    if_none_match: Conditional = None,
) -> Response:
    return await image_response(
        service.info(
            access.workspace_id,
            artifact_id,
            page=page,
            if_none_match=if_none_match,
        )
    )


@router.get(
    "/tiles/{z}/{x}/{y}.{extension}",
    response_class=Response,
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}},
)
async def image_tile(
    artifact_id: UUID,
    z: Annotated[int, Path(ge=0, le=31)],
    x: Annotated[int, Path(ge=0)],
    y: Annotated[int, Path(ge=0)],
    extension: Literal["png", "jpg"],
    service: ArtifactImageDependency,
    access: ViewArtifacts,
    page: Page = 0,
    if_none_match: Conditional = None,
) -> Response:
    return await image_response(
        service.tile(
            access.workspace_id,
            artifact_id,
            z=z,
            x=x,
            y=y,
            extension=extension,
            page=page,
            if_none_match=if_none_match,
        )
    )


@router.get(
    "/thumbnail",
    response_class=Response,
    responses={200: {"content": {"image/png": {}, "image/jpeg": {}}}},
)
async def image_thumbnail(
    artifact_id: UUID,
    service: ArtifactImageDependency,
    access: ViewArtifacts,
    page: Page = 0,
    edge: Annotated[
        int, Query(json_schema_extra={"enum": [128, 256, 512, 1024]})
    ] = 256,
    if_none_match: Conditional = None,
) -> Response:
    if edge not in {128, 256, 512, 1024}:
        raise HTTPException(422, "Thumbnail edge must be 128, 256, 512 or 1024")
    return await image_response(
        service.thumbnail(
            access.workspace_id,
            artifact_id,
            edge=edge,
            page=page,
            if_none_match=if_none_match,
        )
    )
