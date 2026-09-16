from typing import Annotated

from fastapi import Depends, Request

from grafy_api.app_state import get_resources
from grafy_api.uploads import UploadService, UploadServiceConfig
from grafy_api.v1.routes.uploads.models import CreateUploadRequest
from grafy_api.v1.routes.uploads.validators import (
    ContentLengthValidator,
    CreateUploadSizeValidator,
)
from grafy_core.ports.validator import Validator


def upload_service(request: Request) -> UploadService:
    return get_resources(request.app).workbench.uploads


def upload_config(request: Request) -> UploadServiceConfig:
    return get_resources(request.app).workbench.upload_config


def create_upload_size_validator(
    config: Annotated[UploadServiceConfig, Depends(upload_config)],
) -> Validator[CreateUploadRequest]:
    return CreateUploadSizeValidator(config.max_upload_bytes)


def content_length_validator(
    config: Annotated[UploadServiceConfig, Depends(upload_config)],
) -> Validator[Request]:
    return ContentLengthValidator(config.max_upload_bytes)


UploadDependency = Annotated[
    UploadService,
    Depends(upload_service),
]

UploadConfigDependency = Annotated[
    UploadServiceConfig,
    Depends(upload_config),
]

CreateUploadSizeDependency = Annotated[
    Validator[CreateUploadRequest],
    Depends(create_upload_size_validator),
]

ContentLengthDependency = Annotated[
    Validator[Request],
    Depends(content_length_validator),
]


__all__ = [
    "ContentLengthDependency",
    "CreateUploadSizeDependency",
    "UploadConfigDependency",
    "UploadDependency",
    "upload_config",
    "upload_service",
]
