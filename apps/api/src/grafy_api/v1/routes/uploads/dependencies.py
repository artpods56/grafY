from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_resources

from grafy_api.staged_uploads import StagedUploadService


def staged_upload_service(request: Request) -> StagedUploadService:
    return get_resources(request.app).uploads


StagedUploadDependency = Annotated[
    StagedUploadService,
    Depends(staged_upload_service),
]


__all__ = ["StagedUploadDependency", "staged_upload_service"]
