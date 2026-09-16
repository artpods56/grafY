import pytest
from datetime import timedelta

from grafy_core.domain.errors import ValidationError as DomainValidationError
from pydantic import ValidationError
from starlette.requests import Request

from grafy_api.settings import STAGED_UPLOAD_HARD_MAX_BYTES
from grafy_api.uploads import UploadServiceConfig, UploadTooLargeError
from grafy_api.v1.routes.uploads.models import CreateUploadRequest
from grafy_api.v1.routes.uploads.validators import (
    ContentLengthValidator,
    CreateUploadSizeValidator,
)


def test_create_upload_request_strips_and_rejects_blank_filename() -> None:
    request = CreateUploadRequest(filename="  notes.bin  ", byte_size=1)
    assert request.filename == "notes.bin"

    with pytest.raises(ValidationError, match="Upload filename is required"):
        _ = CreateUploadRequest(filename="   ", byte_size=1)


def test_create_upload_request_rejects_size_above_hard_max() -> None:
    with pytest.raises(ValidationError):
        _ = CreateUploadRequest(
            filename="huge.bin",
            byte_size=STAGED_UPLOAD_HARD_MAX_BYTES + 1,
        )


async def test_create_upload_size_validator_rejects_over_deployment_limit() -> None:
    validator = CreateUploadSizeValidator(1024)
    request = CreateUploadRequest(filename="large.bin", byte_size=1025)

    with pytest.raises(UploadTooLargeError, match="exceeds the upload limit"):
        await validator.validate(request)


async def test_content_length_validator_rejects_bad_and_oversize_headers() -> None:
    validator = ContentLengthValidator(1024)

    bad = Request({"type": "http", "headers": [(b"content-length", b"nope")]})
    with pytest.raises(DomainValidationError, match="Content-Length must be an integer"):
        await validator.validate(bad)

    oversize = Request({"type": "http", "headers": [(b"content-length", b"2048")]})
    with pytest.raises(UploadTooLargeError, match="exceeds the upload limit"):
        await validator.validate(oversize)

    ok = Request({"type": "http", "headers": [(b"content-length", b"512")]})
    await validator.validate(ok)


def test_upload_service_config_rejects_lifetime_not_exceeding_target_ttl() -> None:
    with pytest.raises(ValidationError, match="lifetime must exceed"):
        _ = UploadServiceConfig(
            upload_lifetime=timedelta(minutes=10),
            upload_target_ttl=timedelta(minutes=15),
        )
