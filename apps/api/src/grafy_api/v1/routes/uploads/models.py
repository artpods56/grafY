from typing import Self

from grafy_core.domain.staged_uploads import StagedUpload
from grafy_core.file_contracts import BLOB_FILE
from pydantic import BaseModel, Field

from grafy_api.staged_uploads import StagedUploadResult
from grafy_api.v1.models import ApiResponse

BLOB_UPLOAD_NOTICE = "Format not recognized, stored as a blob."


class SampleRequest(BaseModel):
    count: int = Field(default=2, ge=1, le=8)


class ImageUploadItemResponse(ApiResponse):
    upload_key: str
    filename: str
    byte_size: int
    artifact_type: str | None = None
    notice: str | None = None

    @classmethod
    def from_result(cls, result: StagedUploadResult) -> Self:
        key = result.artifact_type
        return cls(
            upload_key=result.upload.upload_key,
            filename=result.upload.original_filename,
            byte_size=result.upload.byte_size,
            artifact_type=f"{key.id}@{key.schema_version}" if key is not None else None,
            notice=BLOB_UPLOAD_NOTICE if key == BLOB_FILE.key else None,
        )

    @classmethod
    def from_item(cls, item: StagedUpload) -> Self:
        return cls(
            upload_key=item.upload_key,
            filename=item.original_filename,
            byte_size=item.byte_size,
        )


__all__ = ["ImageUploadItemResponse", "SampleRequest"]
