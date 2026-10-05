from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Path, Query
from fastapi.responses import Response, StreamingResponse

from .models import (
    GeoExactFeatureResponse,
    GeoFeatureQueryRequest,
    GeoFeatureQueryResponse,
    GeoRasterTileJsonResponse,
    GeoRenderResponse,
    TableCellResponse,
    TablePageResponse,
    TableQueryRequest,
    TableSchemaResponse,
    WorkbenchErrorResponse,
)
from grafy_api.services.errors import (
    ArtifactContentUnavailableError,
    WorkbenchOperationError,
)

from .dependencies import ArtifactDependency
from .services import (
    ArtifactContentRead,
    ArtifactResponseTooLargeError,
    GeoRangeNotSatisfiableError,
    IMMUTABLE_CACHE_CONTROL,
)
from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.v1.routes.auth.dependencies import require_workspace_capability


router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["workbench"])


def _artifact_streaming_response(
    content: ArtifactContentRead,
    *,
    media_type: str,
    headers: dict[str, str],
) -> StreamingResponse:
    if content.content_length is not None:
        headers["Content-Length"] = str(content.content_length)
    return StreamingResponse(
        content=content.chunks(),
        media_type=media_type,
        headers=headers,
    )


@router.get(
    "/artifacts/{artifact_id}/geo/render",
    response_model=GeoRenderResponse,
    responses={
        400: {"model": WorkbenchErrorResponse, "description": "Invalid geo request"},
        404: {"model": WorkbenchErrorResponse, "description": "Artifact not found"},
        500: {
            "model": WorkbenchErrorResponse,
            "description": "Artifact content is unavailable",
        },
    },
)
async def get_geo_render_descriptor(
    artifact_id: UUID,
    service: ArtifactDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
) -> GeoRenderResponse:
    artifact = await service.get(access.workspace_id, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        return await service.load_geo_render(artifact, workspace_id=access.workspace_id)
    except ArtifactContentUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/artifacts/{artifact_id}/geo/query",
    response_model=GeoFeatureQueryResponse,
    responses={
        400: {"model": WorkbenchErrorResponse, "description": "Invalid geo query"},
        404: {"model": WorkbenchErrorResponse, "description": "Artifact not found"},
        500: {
            "model": WorkbenchErrorResponse,
            "description": "Artifact content is unavailable",
        },
    },
)
async def query_geo_features(
    artifact_id: UUID,
    query: GeoFeatureQueryRequest,
    service: ArtifactDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
) -> GeoFeatureQueryResponse:
    artifact = await service.get(access.workspace_id, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        return await service.query_geo_features(
            artifact,
            query.rows,
            workspace_id=access.workspace_id,
        )
    except ArtifactContentUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/artifacts/{source_id}/geo/vector.pmtiles",
    responses={
        400: {"model": WorkbenchErrorResponse, "description": "Invalid vector source"},
        404: {"model": WorkbenchErrorResponse, "description": "Artifact not found"},
        413: {"model": WorkbenchErrorResponse, "description": "Response too large"},
        416: {"description": "Requested byte range is not satisfiable"},
        500: {
            "model": WorkbenchErrorResponse,
            "description": "Vector projection is unavailable",
        },
    },
)
async def get_geo_vector_pmtiles(
    source_id: UUID,
    service: ArtifactDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
    range_header: Annotated[str | None, Header(alias="Range")] = None,
) -> Response:
    artifact = await service.get(access.workspace_id, source_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        archive = await service.load_vector_archive(artifact, range_header)
    except GeoRangeNotSatisfiableError as exc:
        raise HTTPException(
            status_code=416,
            detail=str(exc),
            headers={
                "Accept-Ranges": "bytes",
                "Content-Range": f"bytes */{exc.total_size}",
                "ETag": exc.etag,
                "Cache-Control": IMMUTABLE_CACHE_CONTROL,
            },
        ) from exc
    except ArtifactResponseTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ArtifactContentUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(len(archive.content)),
        "ETag": archive.etag,
        "Cache-Control": IMMUTABLE_CACHE_CONTROL,
    }
    if archive.status_code == 206:
        headers["Content-Range"] = (
            f"bytes {archive.start}-{archive.end_exclusive - 1}/{archive.total_size}"
        )
    return Response(
        content=archive.content,
        status_code=archive.status_code,
        media_type=archive.content_type,
        headers=headers,
    )


@router.get(
    "/artifacts/{source_id}/geo/features/{feature_index}",
    response_model=GeoExactFeatureResponse,
    responses={
        400: {"model": WorkbenchErrorResponse, "description": "Invalid vector source"},
        404: {"model": WorkbenchErrorResponse, "description": "Feature not found"},
        500: {
            "model": WorkbenchErrorResponse,
            "description": "Feature content is unavailable",
        },
    },
)
async def get_geo_exact_feature(
    source_id: UUID,
    service: ArtifactDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
    feature_index: Annotated[int, Path(ge=0)],
) -> GeoExactFeatureResponse:
    artifact = await service.get(access.workspace_id, source_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        feature = await service.load_exact_feature(artifact, feature_index)
    except ArtifactContentUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if feature is None:
        raise HTTPException(status_code=404, detail="Feature not found")
    return feature


@router.get(
    "/artifacts/{source_id}/geo/raster/tilejson.json",
    response_model=GeoRasterTileJsonResponse,
    responses={
        400: {"model": WorkbenchErrorResponse, "description": "Invalid raster source"},
        404: {"model": WorkbenchErrorResponse, "description": "Artifact not found"},
        500: {
            "model": WorkbenchErrorResponse,
            "description": "Raster projection is unavailable",
        },
    },
)
async def get_geo_raster_tilejson(
    source_id: UUID,
    service: ArtifactDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
) -> GeoRasterTileJsonResponse:
    artifact = await service.get(access.workspace_id, source_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        tilejson = await service.load_raster_tilejson(
            artifact,
            workspace_id=access.workspace_id,
        )
        return tilejson.model_copy(
            update={
                "tiles": [
                    (
                        f"/api/v1/workspaces/{access.workspace_id}/artifacts/"
                        f"{source_id}/geo/raster/{{z}}/{{x}}/{{y}}.png"
                    )
                ]
            }
        )
    except ArtifactContentUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Could not load raster TileJSON for artifact {source_id}",
        ) from exc


@router.get(
    "/artifacts/{source_id}/geo/raster/{z}/{x}/{y}.png",
    responses={
        400: {"model": WorkbenchErrorResponse, "description": "Invalid raster source"},
        404: {"model": WorkbenchErrorResponse, "description": "Raster tile not found"},
        500: {
            "model": WorkbenchErrorResponse,
            "description": "Raster tile is unavailable",
        },
    },
)
async def get_geo_raster_tile(
    source_id: UUID,
    service: ArtifactDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
    z: Annotated[int, Path(ge=0, le=24)],
    x: Annotated[int, Path(ge=0)],
    y: Annotated[int, Path(ge=0)],
) -> Response:
    artifact = await service.get(access.workspace_id, source_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        tile = await service.load_raster_tile(
            artifact,
            workspace_id=access.workspace_id,
            z=z,
            x=x,
            y=y,
        )
    except ArtifactContentUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if tile is None:
        raise HTTPException(status_code=404, detail="Raster tile not found")
    headers = {
        "Content-Length": str(len(tile.content)),
        "Cache-Control": "private, max-age=300",
    }
    if tile.etag is not None:
        headers["ETag"] = tile.etag
        headers["Cache-Control"] = IMMUTABLE_CACHE_CONTROL
    return Response(
        content=tile.content,
        media_type=tile.content_type,
        headers=headers,
    )


@router.get(
    "/artifacts/{artifact_id}/table/page",
    response_model=TablePageResponse,
    responses={
        400: {"model": WorkbenchErrorResponse, "description": "Invalid table request"},
        404: {"model": WorkbenchErrorResponse, "description": "Artifact not found"},
        500: {
            "model": WorkbenchErrorResponse,
            "description": "Artifact content is unavailable",
        },
    },
)
async def get_table_artifact_page(
    artifact_id: UUID,
    service: ArtifactDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    column_offset: Annotated[int, Query(ge=0)] = 0,
    column_limit: Annotated[int, Query(ge=1, le=100)] = 25,
    column_ids: Annotated[
        list[str] | None,
        Query(min_length=1, max_length=100),
    ] = None,
    max_cell_characters: Annotated[int, Query(ge=32, le=2_000)] = 256,
) -> TablePageResponse:
    requested_column_count = len(column_ids) if column_ids is not None else column_limit
    if limit * requested_column_count * max_cell_characters > 2_000_000:
        raise HTTPException(
            status_code=400,
            detail=(
                "Requested table preview exceeds the 2,000,000-character "
                "response budget; reduce limit, column_limit, or "
                "max_cell_characters"
            ),
        )
    artifact = await service.get(access.workspace_id, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        page = await service.load_table_page(
            artifact,
            offset=offset,
            limit=limit,
        )
        return TablePageResponse.from_page(
            page,
            limit=limit,
            column_offset=column_offset,
            column_limit=column_limit,
            column_ids=column_ids,
            max_cell_characters=max_cell_characters,
        )
    except ArtifactContentUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/artifacts/{artifact_id}/table/schema",
    response_model=TableSchemaResponse,
    responses={
        400: {"model": WorkbenchErrorResponse, "description": "Invalid table request"},
        404: {"model": WorkbenchErrorResponse, "description": "Artifact not found"},
        500: {
            "model": WorkbenchErrorResponse,
            "description": "Artifact content is unavailable",
        },
    },
)
async def get_table_artifact_schema(
    artifact_id: UUID,
    service: ArtifactDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
) -> TableSchemaResponse:
    artifact = await service.get(access.workspace_id, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        page = await service.load_table_page(artifact, offset=0, limit=1)
    except ArtifactContentUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TableSchemaResponse.from_page(page)


@router.post(
    "/artifacts/{artifact_id}/table/query",
    response_model=TablePageResponse,
    responses={
        400: {"model": WorkbenchErrorResponse, "description": "Invalid table query"},
        404: {"model": WorkbenchErrorResponse, "description": "Artifact not found"},
        500: {
            "model": WorkbenchErrorResponse,
            "description": "Artifact content is unavailable",
        },
    },
)
async def query_table_artifact_page(
    artifact_id: UUID,
    query: TableQueryRequest,
    service: ArtifactDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
) -> TablePageResponse:
    requested_column_count = (
        len(query.column_ids) if query.column_ids is not None else query.column_limit
    )
    if query.limit * requested_column_count * query.max_cell_characters > 2_000_000:
        raise HTTPException(
            status_code=400,
            detail=(
                "Requested table preview exceeds the 2,000,000-character "
                "response budget; reduce limit, column_limit, or "
                "max_cell_characters"
            ),
        )
    artifact = await service.get(access.workspace_id, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        result = await service.load_table_query_page(
            artifact,
            filter_groups=query.filter_groups,
            highlight_groups=query.highlight_groups,
            offset=query.offset,
            limit=query.limit,
        )
        return TablePageResponse.from_page(
            result.page,
            limit=query.limit,
            column_offset=query.column_offset,
            column_limit=query.column_limit,
            column_ids=query.column_ids,
            max_cell_characters=query.max_cell_characters,
            row_indices=result.row_indices,
            highlighted_row_indices=result.highlighted_row_indices,
        )
    except ArtifactContentUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/artifacts/{artifact_id}/table/cell",
    response_model=TableCellResponse,
    responses={
        400: {"model": WorkbenchErrorResponse, "description": "Invalid cell request"},
        404: {"model": WorkbenchErrorResponse, "description": "Artifact not found"},
        500: {
            "model": WorkbenchErrorResponse,
            "description": "Artifact content is unavailable",
        },
    },
)
async def get_table_artifact_cell(
    artifact_id: UUID,
    service: ArtifactDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
    row_index: Annotated[int, Query(ge=0)],
    column_id: Annotated[str, Query(min_length=1)],
) -> TableCellResponse:
    artifact = await service.get(access.workspace_id, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        value = await service.load_table_cell(
            artifact,
            row_index=row_index,
            column_id=column_id,
        )
    except ArtifactContentUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TableCellResponse.from_value(
        row_index=row_index,
        column_id=column_id,
        value=value,
    )


@router.get(
    "/artifacts/{artifact_id}/content",
    responses={
        404: {"model": WorkbenchErrorResponse, "description": "Artifact not found"},
        413: {"model": WorkbenchErrorResponse, "description": "Response too large"},
        500: {
            "model": WorkbenchErrorResponse,
            "description": "Artifact content is unavailable",
        },
    },
)
async def get_artifact_content(
    artifact_id: UUID,
    service: ArtifactDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
) -> StreamingResponse:
    artifact = await service.get(access.workspace_id, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        content = await service.open_content(artifact)
    except ArtifactResponseTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    headers: dict[str, str] = {}
    download_name = artifact.metadata.get("download_name")
    if isinstance(download_name, str) and download_name != "":
        headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
    return _artifact_streaming_response(
        content,
        media_type=artifact.content_type,
        headers=headers,
    )


@router.get(
    "/artifacts/{artifact_id}/download",
    responses={
        400: {"model": WorkbenchErrorResponse, "description": "Unsupported format"},
        404: {"model": WorkbenchErrorResponse, "description": "Artifact not found"},
        413: {"model": WorkbenchErrorResponse, "description": "Response too large"},
        500: {
            "model": WorkbenchErrorResponse,
            "description": "Artifact content is unavailable",
        },
    },
)
async def get_artifact_download(
    artifact_id: UUID,
    service: ArtifactDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
    format: Annotated[
        str,
        Query(min_length=1, max_length=32, pattern=r"^[a-z0-9_.-]+$"),
    ] = "json",
) -> StreamingResponse:
    artifact = await service.get(access.workspace_id, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")
    try:
        content, content_type = await service.load_download(artifact, format)
    except ArtifactContentUnavailableError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except ArtifactResponseTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Deterministic, unique, safe filename: never user-supplied metadata (which
    # may contain path separators). Prefer the format's declared filename
    # suffixed with the short artifact id, falling back to an id-suffixed slug.
    declared = next(
        (
            entry.filename
            for entry in service.export_formats(artifact)
            if entry.format == format
        ),
        None,
    )
    stem = declared.rsplit(".", 1)[0] if declared else format
    filename = f"{stem}-{artifact.id.hex[:8]}"
    if declared and "." in declared:
        filename = f"{filename}.{declared.rsplit('.', 1)[1]}"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return _artifact_streaming_response(
        content,
        media_type=content_type,
        headers=headers,
    )


__all__ = [
    "get_artifact_content",
    "get_artifact_download",
    "get_geo_exact_feature",
    "get_geo_raster_tile",
    "get_geo_raster_tilejson",
    "get_geo_render_descriptor",
    "get_geo_vector_pmtiles",
    "query_geo_features",
    "get_table_artifact_cell",
    "get_table_artifact_page",
    "get_table_artifact_schema",
    "query_table_artifact_page",
    "router",
]
