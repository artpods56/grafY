from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.services.errors import WorkbenchOperationError
from grafy_api.v1.routes.auth.dependencies import require_workspace_capability

from .dependencies import LibraryDependency, LibraryFoldersDependency
from .models import (
    CreateLibraryFolderRequest,
    LibraryFolderListResponse,
    LibraryFolderResponse,
    LibraryItemResponse,
    LibraryListResponse,
    MoveLibraryArtifactsRequest,
    MoveLibraryFolderRequest,
    RenameLibraryFolderRequest,
    SaveRunArtifactRequest,
    SaveUploadedArtifactRequest,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/library", tags=["library"])
folders_router = APIRouter(
    prefix="/workspaces/{workspace_id}/library/folders",
    tags=["library folders"],
)


#[TODO] we should probably check what are these services throwing and ensure that we handle these errors correctly


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
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.put(
    "/placements",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def move_library_artifacts(
    body: MoveLibraryArtifactsRequest,
    service: LibraryFoldersDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> Response:
    """File artifacts in one folder, or unfile them when ``folder_id`` is null."""
    await service.place_artifacts(
        workspace_id=access.workspace_id,
        artifact_ids=body.artifact_ids,
        folder_id=body.folder_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@folders_router.get("", response_model=LibraryFolderListResponse)
async def list_library_folders(
    service: LibraryFoldersDependency,
    access: require_workspace_capability(WorkspaceCapability.VIEW_ARTIFACTS),
) -> LibraryFolderListResponse:
    return LibraryFolderListResponse(
        folders=await service.list_folders(access.workspace_id),
    )


@folders_router.post(
    "",
    response_model=LibraryFolderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_library_folder(
    body: CreateLibraryFolderRequest,
    service: LibraryFoldersDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> LibraryFolderResponse:
    return await service.create_folder(
        workspace_id=access.workspace_id,
        name=body.name,
        parent_id=body.parent_id,
    )


@folders_router.patch("/{folder_id}", response_model=LibraryFolderResponse)
async def rename_library_folder(
    folder_id: UUID,
    body: RenameLibraryFolderRequest,
    service: LibraryFoldersDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> LibraryFolderResponse:
    return await service.rename_folder(
        workspace_id=access.workspace_id,
        folder_id=folder_id,
        name=body.name,
    )


@folders_router.delete(
    "/{folder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_library_folder(
    folder_id: UUID,
    service: LibraryFoldersDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> Response:
    """Delete one folder. A folder that still holds anything is refused."""
    await service.delete_folder(
        workspace_id=access.workspace_id,
        folder_id=folder_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@folders_router.put("/{folder_id}/parent", response_model=LibraryFolderResponse)
async def move_library_folder(
    folder_id: UUID,
    body: MoveLibraryFolderRequest,
    service: LibraryFoldersDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> LibraryFolderResponse:
    return await service.move_folder(
        workspace_id=access.workspace_id,
        folder_id=folder_id,
        parent_id=body.parent_id,
    )


__all__ = [
    "folders_router",
    "list_library_artifacts",
    "router",
    "save_library_artifact_from_run",
    "save_library_artifact_from_upload",
]
