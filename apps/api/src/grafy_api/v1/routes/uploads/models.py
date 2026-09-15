from datetime import datetime
from typing import Self

from pydantic import BaseModel, Field

from grafy_core.file_contracts import BLOB_FILE

from grafy_api.uploads import UploadResult, UploadTarget
from grafy_api.v1.models import ApiResponse

BLOB_UPLOAD_NOTICE = "Format not recognized, stored as a blob."


class CreateUploadRequest(BaseModel):
    """Reserve one upload before the bytes leave the client."""

    filename: str = Field(min_length=1, max_length=255)
    byte_size: int = Field(ge=0)
    content_type: str | None = Field(default=None, max_length=255)


class UploadTargetResponse(ApiResponse):
    upload_id: str
    url: str
    method: str
    expires_at: datetime

    @classmethod
    def from_target(cls, target: UploadTarget) -> Self:
        return cls(
            upload_id=str(target.upload_id),
            url=target.url,
            method=target.method,
            expires_at=target.expires_at,
        )


class ImageUploadItemResponse(ApiResponse):
    upload_key: str
    filename: str
    byte_size: int
    artifact_type: str | None = None
    notice: str | None = None

    @classmethod
    def from_result(cls, result: UploadResult) -> Self:
        key = result.artifact_type
        upload = result.upload
        byte_size = upload.actual_size
        return cls(
            upload_key=str(upload.upload_id),
            filename=upload.original_filename,
            byte_size=byte_size if byte_size is not None else upload.expected_size,
            artifact_type=f"{key.id}@{key.schema_version}" if key is not None else None,
            notice=BLOB_UPLOAD_NOTICE
            if key is not None and key.id == BLOB_FILE.key.id
            else None,
        )


__all__ = [
    "BLOB_UPLOAD_NOTICE",
    "CreateUploadRequest",
    "ImageUploadItemResponse",
    "UploadTargetResponse",
]
