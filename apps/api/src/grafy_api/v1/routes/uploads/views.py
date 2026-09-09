from uuid import UUID

from fastapi import APIRouter, File, HTTPException, UploadFile

from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.services.errors import WorkbenchOperationError
from grafy_api.v1.routes.auth.dependencies import require_workspace_capability

from .dependencies import StagedUploadDependency
from .models import ImageUploadItemResponse, SampleRequest
from grafy_api.staged_uploads import StagedUploadTooLargeError


router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["workbench"])


@router.post("/uploads", response_model=ImageUploadItemResponse)
async def upload_file(
    workspace_id: UUID,
    service: StagedUploadDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
    file: UploadFile = File(),
) -> ImageUploadItemResponse:
    if not file.filename:
        raise HTTPException(status_code=422, detail="Upload filename is required")
    try:
        item = await service.save_upload(
            workspace_id=workspace_id,
            created_by_user_id=access.actor.user_id,
            filename=file.filename,
            stream=file.file,
        )
        return ImageUploadItemResponse.from_item(item)
    except StagedUploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/samples", response_model=list[ImageUploadItemResponse])
async def create_samples(
    workspace_id: UUID,
    request: SampleRequest,
    service: StagedUploadDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> list[ImageUploadItemResponse]:
    items = await service.create_sample_images(
        workspace_id=workspace_id,
        created_by_user_id=access.actor.user_id,
        count=request.count,
    )
    return [ImageUploadItemResponse.from_item(item) for item in items]


__all__ = ["router"]
