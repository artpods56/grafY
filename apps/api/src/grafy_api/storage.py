"""Construct the deployment's configured object-storage adapter."""

from grafy_core.ports.storage import FileStoragePort
from grafy_storage import LocalFileObjectStore, S3ObjectStore

from grafy_api.settings import Settings


def configured_file_storage(settings: Settings) -> FileStoragePort:
    s3_access_key_id: str | None = None
    if settings.s3_access_key_id is not None:
        configured_access_key_id = settings.s3_access_key_id.get_secret_value().strip()
        if configured_access_key_id != "":
            s3_access_key_id = configured_access_key_id
    s3_secret_access_key: str | None = None
    if settings.s3_secret_access_key is not None:
        configured_secret_access_key = settings.s3_secret_access_key.get_secret_value()
        if configured_secret_access_key != "":
            s3_secret_access_key = configured_secret_access_key
    s3_endpoint_url = settings.s3_endpoint_url
    if s3_endpoint_url == "":
        s3_endpoint_url = None
    if settings.storage_backend == "local":
        return LocalFileObjectStore(settings.workspace / "objects")
    return S3ObjectStore(
        endpoint_url=s3_endpoint_url,
        region=settings.s3_region,
        access_key_id=s3_access_key_id,
        secret_access_key=s3_secret_access_key,
        force_path_style=settings.s3_force_path_style,
    )


__all__ = ["configured_file_storage"]
