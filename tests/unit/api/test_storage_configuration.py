from io import BytesIO
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from grafy_api.settings import Settings
from grafy_api.storage import configured_file_storage
from grafy_core.ports.storage import SaveFileCommand
from grafy_storage import S3ObjectStore


@pytest.mark.asyncio
async def test_configured_local_storage_uses_workspace_objects_root(
    tmp_path: Path,
) -> None:
    storage = configured_file_storage(
        Settings(workspace=tmp_path, storage_backend="local")
    )
    await storage.save(
        SaveFileCommand(
            bucket="test",
            path="value.txt",
            stream=BytesIO(b"value"),
            content_type="text/plain",
            metadata={},
        )
    )
    stream = await storage.load(bucket="test", path="value.txt")
    try:
        assert stream.read() == b"value"
    finally:
        stream.close()
    assert (tmp_path / "objects" / "test" / "value.txt").read_bytes() == b"value"


@pytest.mark.parametrize("blank", [False, True])
def test_configured_s3_storage_preserves_credential_normalization(blank: bool) -> None:
    settings = Settings(
        storage_backend="s3",
        s3_endpoint_url="" if blank else "http://minio:9000",
        s3_region="eu-central-1",
        s3_access_key_id=SecretStr("   " if blank else " access "),
        s3_secret_access_key=SecretStr("" if blank else " secret "),
        s3_force_path_style=True,
    )
    with patch("grafy_api.storage.S3ObjectStore", wraps=S3ObjectStore) as constructor:
        assert isinstance(configured_file_storage(settings), S3ObjectStore)
    constructor.assert_called_once_with(
        endpoint_url=None if blank else "http://minio:9000",
        region="eu-central-1",
        access_key_id=None if blank else "access",
        secret_access_key=None if blank else " secret ",
        force_path_style=True,
    )
