from tempfile import SpooledTemporaryFile
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.services.errors import WorkbenchOperationError
from grafy_api.uploads import (
    FileFormatMismatchError,
    UploadNotFoundError,
    UploadTooLargeError,
    UploadTransportUnsupportedError,
)
from grafy_api.v1.routes.auth.dependencies import require_workspace_capability

from .dependencies import UploadDependency
from .models import (
    CreateUploadRequest,
    ImageUploadItemResponse,
    UploadTargetResponse,
)

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["workbench"])

_STREAM_BUFFER_BYTES = 8 * 1024 * 1024


@router.post(
    "/uploads",
    response_model=UploadTargetResponse,
    status_code=201,
)
async def create_upload(
    workspace_id: UUID,
    request: CreateUploadRequest,
    service: UploadDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> UploadTargetResponse:
    try:
        target = await service.create_upload(
            workspace_id=workspace_id,
            created_by_user_id=access.actor.user_id,
            filename=request.filename,
            byte_size=request.byte_size,
            content_type=request.content_type,
        )
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return UploadTargetResponse.from_target(target)


@router.put(
    "/uploads/{upload_id}/content",
    status_code=204,
    response_class=Response,
)
async def receive_upload_content(
    workspace_id: UUID,
    upload_id: UUID,
    request: Request,
    service: UploadDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> Response:
    if not service.accepts_direct_upload:
        raise HTTPException(
            status_code=404,
            detail="Upload content is accepted only through signed URLs",
        )
    with SpooledTemporaryFile(max_size=_STREAM_BUFFER_BYTES) as buffer:
        async for chunk in request.stream():
            _ = buffer.write(chunk)
        _ = buffer.seek(0)
        try:
            await service.receive_content(
                workspace_id=workspace_id,
                upload_id=upload_id,
                stream=buffer,
            )
        except UploadTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except UploadNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except UploadTransportUnsupportedError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except WorkbenchOperationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post(
    "/uploads/{upload_id}/complete",
    response_model=ImageUploadItemResponse,
    response_model_exclude_none=True,
)
async def complete_upload(
    workspace_id: UUID,
    upload_id: UUID,
    service: UploadDependency,
    access: require_workspace_capability(WorkspaceCapability.EDIT_GRAPH),
) -> ImageUploadItemResponse:
    try:
        result = await service.complete_upload(
            workspace_id=workspace_id,
            upload_id=upload_id,
        )
    except FileFormatMismatchError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "file_format_mismatch", "message": str(exc)},
        ) from exc
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except UploadNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except WorkbenchOperationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ImageUploadItemResponse.from_result(result)


__all__ = ["router"]
