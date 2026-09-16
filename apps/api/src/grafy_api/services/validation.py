import abc
import os
from pathlib import Path

from fastapi import UploadFile

from grafy_core.domain.errors import ValidationError
from grafy_core.ports.validator import Validator


class FileValidator(abc.ABC, Validator[UploadFile]):

    @abc.abstractmethod
    async def validate(self, data: UploadFile) -> None:
        """Validate the uploaded file, raising a domain exception on failure."""


class EmptyFileValidator(FileValidator):
    async def validate(self, data: UploadFile) -> None:
        _ = await data.seek(os.SEEK_END)
        if data.size == 0:
            raise ValidationError("Uploaded file is empty")
        _ = await data.seek(0)


class FileExtensionValidator(FileValidator):
    """Rejects uploads whose extension is not in the allowlist."""

    def __init__(self, allowed_extensions: set[str]):
        self._allowed = allowed_extensions

    async def validate(self, data: UploadFile) -> None:
        assert data.filename is not None
        ext = Path(data.filename).suffix.lower()
        if ext not in self._allowed:
            raise ValidationError(
                f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(self._allowed))}"
            )


class FileNameValidator(FileValidator):
    """Rejects uploads without a filename."""

    async def validate(self, data: UploadFile) -> None:
        if not data.filename:
            raise ValidationError("Filename is required.")


class FileMaxSizeValidator(FileValidator):
    """Rejects uploads that exceed *max_bytes*."""

    def __init__(self, max_bytes: int):
        self._max_bytes = max_bytes

    async def validate(self, data: UploadFile) -> None:
        _ = await data.seek(os.SEEK_END)
        if data.size is not None and data.size > self._max_bytes:
            raise ValidationError(
                f"File size {data.size} exceeds the limit of {self._max_bytes} bytes"
            )
        _ = await data.seek(0)


class FileContentTypeValidator(FileValidator):
    """Rejects uploads whose content-type is not in the allowlist."""

    def __init__(self, allowed_content_types: set[str]):
        self._allowed = allowed_content_types

    async def validate(self, data: UploadFile) -> None:
        if data.content_type and data.content_type not in self._allowed:
            raise ValidationError(
                f"Unsupported content type '{data.content_type}'. "
                f"Allowed: {', '.join(sorted(self._allowed))}"
            )
