import pytest
from datetime import timedelta

from pydantic import ValidationError

from grafy_api.settings import STAGED_UPLOAD_HARD_MAX_BYTES
from grafy_api.uploads import UploadServiceConfig
from grafy_api.v1.routes.uploads.models import CreateUploadRequest


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


def test_upload_service_config_rejects_lifetime_not_exceeding_target_ttl() -> None:
    with pytest.raises(ValidationError, match="lifetime must exceed"):
        _ = UploadServiceConfig(
            upload_lifetime=timedelta(minutes=10),
            upload_target_ttl=timedelta(minutes=15),
        )
