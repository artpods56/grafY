from fastapi import Request

from grafy_api.uploads import UploadTooLargeError
from grafy_api.v1.routes.uploads.models import CreateUploadRequest
from grafy_core.domain.errors import ValidationError
from grafy_core.ports.validator import Validator


class CreateUploadSizeValidator(Validator[CreateUploadRequest]):
    """Rejects create requests whose declared size exceeds the deployment limit."""

    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes

    async def validate(self, data: CreateUploadRequest) -> None:
        if data.byte_size > self._max_bytes:
            raise UploadTooLargeError(
                f"Upload {data.filename!r} exceeds the upload limit of "
                f"{self._max_bytes} bytes"
            )


class ContentLengthValidator(Validator[Request]):
    """Rejects content PUTs whose Content-Length exceeds the deployment limit."""

    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes

    async def validate(self, data: Request) -> None:
        content_length = data.headers.get("content-length")
        if content_length is None:
            return
        try:
            declared = int(content_length)
        except ValueError as exc:
            raise ValidationError("Content-Length must be an integer") from exc
        if declared > self._max_bytes:
            raise UploadTooLargeError(
                f"Upload exceeds the upload limit of {self._max_bytes} bytes"
            )
