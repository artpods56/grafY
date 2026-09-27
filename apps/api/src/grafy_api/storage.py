"""Construct the deployment's configured object-storage adapter."""

from pathlib import Path

from grafy_core.ports.storage import FileStoragePort
from grafy_shared.config import StorageConfig
from grafy_storage import LocalFileObjectStore, S3ObjectStore


def configured_file_storage(cfg: StorageConfig, workspace: Path) -> FileStoragePort:
    s3_access_key_id: str | None = None
    if cfg.s3_access_key_id is not None:
        configured_access_key_id = cfg.s3_access_key_id.get_secret_value().strip()
        if configured_access_key_id != "":
            s3_access_key_id = configured_access_key_id
    s3_secret_access_key: str | None = None
    if cfg.s3_secret_access_key is not None:
        configured_secret_access_key = cfg.s3_secret_access_key.get_secret_value()
        if configured_secret_access_key != "":
            s3_secret_access_key = configured_secret_access_key
    s3_endpoint_url = cfg.s3_endpoint_url
    if s3_endpoint_url == "":
        s3_endpoint_url = None
    s3_signing_endpoint_url = cfg.s3_signing_endpoint_url
    if s3_signing_endpoint_url == "":
        s3_signing_endpoint_url = None
    if cfg.storage_backend == "local":
        return LocalFileObjectStore(workspace / "objects")
    return S3ObjectStore(
        endpoint_url=s3_endpoint_url,
        region=cfg.s3_region,
        access_key_id=s3_access_key_id,
        secret_access_key=s3_secret_access_key,
        force_path_style=cfg.s3_force_path_style,
        signing_endpoint_url=s3_signing_endpoint_url,
    )


__all__ = ["configured_file_storage"]
