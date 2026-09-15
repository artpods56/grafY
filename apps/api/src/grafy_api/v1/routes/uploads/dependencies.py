from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_resources
from grafy_api.uploads import UploadService


def upload_service(request: Request) -> UploadService:
    return get_resources(request.app).workbench.uploads


UploadDependency = Annotated[
    UploadService,
    Depends(upload_service),
]


__all__ = ["UploadDependency", "upload_service"]
