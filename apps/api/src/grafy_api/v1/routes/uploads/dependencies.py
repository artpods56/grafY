from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_resources
from grafy_api.uploads import UploadService, UploadServiceConfig


def upload_service(request: Request) -> UploadService:
    return get_resources(request.app).workbench.uploads


def upload_config(request: Request) -> UploadServiceConfig:
    return get_resources(request.app).workbench.upload_config


UploadDependency = Annotated[
    UploadService,
    Depends(upload_service),
]

UploadConfigDependency = Annotated[
    UploadServiceConfig,
    Depends(upload_config),
]


__all__ = [
    "UploadConfigDependency",
    "UploadDependency",
    "upload_config",
    "upload_service",
]
