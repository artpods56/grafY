"""Object-storage backend selection and S3 connection details."""

from typing import ClassVar, Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS


class StorageConfig(BaseSettings):
    """Which object store holds artifact bytes and how to reach it."""

    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    storage_backend: Literal["local", "s3"] = "local"
    storage_bucket: str = Field(default="workbench-artifacts", min_length=1)
    s3_endpoint_url: str | None = None
    # Browser-facing S3/MinIO hostname used only when signing upload targets.
    # Internal object IO keeps ``s3_endpoint_url`` so signatures do not need
    # post-hoc hostname rewriting.
    s3_signing_endpoint_url: str | None = None
    s3_region: str = Field(default="us-east-1", min_length=1)
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_force_path_style: bool = False
