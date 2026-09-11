from fastapi import APIRouter, HTTPException
from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.services.errors import WorkbenchOperationError
from grafy_api.v1.routes.auth.dependencies import require_workspace_capability

from .dependencies import LibraryDependency
from .models import (
    LibraryItemResponse,
    LibraryListResponse,
    SaveRunArtifactRequest,
    SaveUploadedArtifactRequest,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/library", tags=["library"])


def _unavailable(exc: WorkbenchOperationError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/artifacts", response_model=LibraryListResponse)
async def list_library_artifacts(
    service: LibraryDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
) -> LibraryListResponse:
    return LibraryListResponse(items=await service.list_items(access.workspace_id))


@router.post("/artifacts/from-run", response_model=LibraryItemResponse)
async def save_library_artifact_from_run(
    body: SaveRunArtifactRequest,
    service: LibraryDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> LibraryItemResponse:
    try:
        return await service.save_from_run(
            workspace_id=access.workspace_id,
            artifact_id=body.artifact_id,
            execution_id=body.execution_id,
            node_id=body.node_id,
            node_title=body.node_title,
        )
    except WorkbenchOperationError as exc:
        raise _unavailable(exc) from exc


@router.post("/artifacts/from-upload", response_model=LibraryItemResponse)
async def save_library_artifact_from_upload(
    body: SaveUploadedArtifactRequest,
    service: LibraryDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> LibraryItemResponse:
    return await service.save_uploaded(
        workspace_id=access.workspace_id,
        artifact_id=body.artifact_id,
        original_filename=body.original_filename,
    )


__all__ = [
    "list_library_artifacts",
    "router",
    "save_library_artifact_from_run",
    "save_library_artifact_from_upload",
]
