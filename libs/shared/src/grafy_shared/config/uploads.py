"""Staged upload sizing and lifetime bounds."""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS

# What a deployment accepts per file unless its operator says otherwise.
STAGED_UPLOAD_DEFAULT_MAX_BYTES = 64 * 1024 * 1024
# The highest per-file limit an operator may configure, and the bound the reserve
# contract publishes. It is a protocol ceiling, not what a deployment accepts: the
# configured `staged_upload_max_bytes` is enforced at reserve, receive and complete.
STAGED_UPLOAD_HARD_MAX_BYTES = 2 * 1024 * 1024 * 1024


class UploadConfig(BaseSettings):
    """How large an upload may be and how long its target stays valid."""

    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    staged_upload_max_bytes: int = Field(
        default=STAGED_UPLOAD_DEFAULT_MAX_BYTES,
        ge=1024 * 1024,
        le=STAGED_UPLOAD_HARD_MAX_BYTES,
    )
    # Longest time a reserved upload may remain pending before expiration.
    upload_lifetime_seconds: int = Field(
        default=24 * 60 * 60, ge=60, le=7 * 24 * 60 * 60
    )
    # Lifetime of one signed or API-owned upload target. A PUT must start inside it;
    # the receive timeout below bounds how long its body may then take.
    upload_target_ttl_seconds: int = Field(default=15 * 60, ge=30, le=60 * 60)
    # Bound on receiving one upload body (local route and MinIO/proxy path).
    # Cleanup retains terminal rows until this window after target expiry so a
    # late in-flight PUT cannot recreate bytes after tracking is gone.
    upload_receive_timeout_seconds: int = Field(default=30 * 60, ge=30, le=6 * 60 * 60)
