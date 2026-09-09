"""Public storage-package factory retained for supported caller imports."""

from pathlib import Path
from typing import Literal

from grafy_core.ports.storage import FileStoragePort
from grafy_storage.adapters.local import LocalFileObjectStore
from grafy_storage.adapters.s3 import S3ObjectStore

StorageBackend = Literal["local", "s3"]


def create_file_storage(
    *,
    backend: StorageBackend,
    local_root: Path,
    s3_endpoint_url: str | None = None,
    s3_region: str = "us-east-1",
    s3_access_key_id: str | None = None,
    s3_secret_access_key: str | None = None,
    s3_force_path_style: bool = False,
) -> FileStoragePort:
    if backend == "local":
        return LocalFileObjectStore(local_root)
    return S3ObjectStore(
        endpoint_url=s3_endpoint_url,
        region=s3_region,
        access_key_id=s3_access_key_id,
        secret_access_key=s3_secret_access_key,
        force_path_style=s3_force_path_style,
    )
