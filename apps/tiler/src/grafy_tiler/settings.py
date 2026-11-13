"""Tiler configuration, read once from ``TILER_*`` environment variables."""

import os
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SIGNING_KEY_LENGTH = 32
# Longest side of the lazily built overview; see `overview_min_pixels`.
OVERVIEW_EDGE = 2048


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TILER_", extra="ignore", frozen=True, env_ignore_empty=True
    )

    docs_enabled: bool = False

    # Comma-separated HMAC keys that may have signed a grant. The API signs with
    # one of them; listing two lets an operator rotate without downtime.
    signing_keys: SecretStr
    # The only bucket this service reads. A grant naming another bucket is
    # refused before storage is touched.
    bucket: str = Field(min_length=1)

    storage: Literal["s3", "local"] = "s3"
    # `local` mode reads `<local_root>/<bucket>/<key>` and exists for native
    # development against the local file store; deployments use `s3`.
    local_root: Path | None = None
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_force_path_style: bool = True

    cache_dir: Path = Path("/cache")
    cache_max_bytes: int = Field(default=2 * 1024**3, ge=1024**2)

    tile_size: Literal[256, 512] = 512
    jpeg_quality: int = Field(default=85, ge=1, le=100)
    # Hard caps on what one grant may ask the renderer to open.
    max_source_bytes: int = Field(default=1024**3, ge=1)
    max_pixels: int = Field(default=2_000_000_000, ge=1)
    max_pages: int = Field(default=1024, ge=1)
    # A source without overviews that is larger than this on its longest side
    # gets one lazily built overview, so low-zoom tiles do not decode it whole.
    overview_min_pixels: int = Field(default=4096, ge=OVERVIEW_EDGE)

    # Renders run in worker threads; this bounds how many run at once. Work
    # beyond `queue_depth` waiting requests is refused with 503 so a burst
    # cannot pile up unbounded memory.
    render_concurrency: int = Field(default=2, ge=1, le=32)
    queue_depth: int = Field(default=32, ge=0)
    render_timeout_seconds: float = Field(default=30.0, gt=0)
    gdal_cache_mb: int = Field(default=128, ge=16)

    grant_clock_skew_seconds: int = Field(default=5, ge=0, le=60)

    host: str = "0.0.0.0"
    port: int = Field(default=8100, ge=1, le=65535)
    workers: int = Field(default=1, ge=1, le=16)

    @model_validator(mode="after")
    def _validate_storage(self) -> Self:
        if any(len(key) < MIN_SIGNING_KEY_LENGTH for key in self.signing_key_values):
            raise ValueError(
                f"every TILER_SIGNING_KEYS entry must have at least "
                f"{MIN_SIGNING_KEY_LENGTH} characters"
            )
        if self.storage == "local" and self.local_root is None:
            raise ValueError("TILER_LOCAL_ROOT is required when TILER_STORAGE=local")
        if self.storage == "s3" and (
            (self.s3_access_key_id is None) != (self.s3_secret_access_key is None)
        ):
            raise ValueError(
                "TILER_S3_ACCESS_KEY_ID and TILER_S3_SECRET_ACCESS_KEY go together"
            )
        return self

    @property
    def signing_key_values(self) -> tuple[bytes, ...]:
        raw = self.signing_keys.get_secret_value()
        return tuple(
            part.strip().encode() for part in raw.split(",") if part.strip() != ""
        )

    def apply_gdal_environment(self) -> None:
        """Export GDAL's configuration as process environment variables.

        GDAL reads these natively on every thread. rasterio's own `Env` is
        thread-local and would have to be re-entered in each render thread.
        """
        # Do not set GDAL_DISABLE_READDIR_ON_OPEN: with it, opening a later page
        # of a multipage TIFF (`GTIFF_DIR:n:/vsis3/...`) hangs inside GDAL.
        options = {
            "GDAL_CACHEMAX": str(self.gdal_cache_mb),
            "GDAL_NUM_THREADS": "1",
            "GDAL_PAM_ENABLED": "NO",
            "GDAL_HTTP_TIMEOUT": "20",
            "GDAL_HTTP_CONNECTTIMEOUT": "5",
            "GDAL_HTTP_MAX_RETRY": "2",
            "GDAL_HTTP_RETRY_DELAY": "1",
            "VSI_CACHE": "TRUE",
            "VSI_CACHE_SIZE": str(32 * 1024 * 1024),
            "CPL_VSIL_CURL_CHUNK_SIZE": str(512 * 1024),
            "CPL_VSIL_CURL_CACHE_SIZE": str(64 * 1024 * 1024),
            "PROJ_NETWORK": "OFF",
            "AWS_REGION": self.s3_region,
            "AWS_VIRTUAL_HOSTING": "FALSE" if self.s3_force_path_style else "TRUE",
        }
        if self.s3_endpoint_url is not None:
            scheme, _, host = self.s3_endpoint_url.partition("://")
            options["AWS_S3_ENDPOINT"] = host.rstrip("/")
            options["AWS_HTTPS"] = "NO" if scheme == "http" else "YES"
        if self.s3_access_key_id is not None and self.s3_secret_access_key is not None:
            options["AWS_ACCESS_KEY_ID"] = self.s3_access_key_id.get_secret_value()
            options["AWS_SECRET_ACCESS_KEY"] = (
                self.s3_secret_access_key.get_secret_value()
            )
        os.environ.update(options)
