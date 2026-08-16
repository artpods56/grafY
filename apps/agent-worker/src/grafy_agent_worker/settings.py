import os
from pathlib import Path
import socket
from typing import ClassVar, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_worker_id() -> str:
    return f"agent-worker-{socket.gethostname()}-{os.getpid()}"


class AgentWorkerSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="GRAFY_AGENT_WORKER_",
        extra="ignore",
    )

    worker_id: str = Field(default_factory=_default_worker_id)
    workspace: Path = Path(".grafy-artifacts/workbench")
    database_url: SecretStr | None = None
    poll_interval_seconds: float = Field(default=1.0, ge=0.05, le=60.0)
    poll_batch_size: int = Field(default=8, ge=1, le=128)
    lease_seconds: int = Field(default=60, ge=15, le=3_600)
    heartbeat_seconds: float = Field(default=15.0, ge=1.0, le=1_200.0)
    storage_backend: Literal["local", "s3"] = "local"
    storage_bucket: str = "workbench-artifacts"
    s3_endpoint_url: str | None = None
    s3_region: str = "us-east-1"
    s3_access_key_id: SecretStr | None = None
    s3_secret_access_key: SecretStr | None = None
    s3_force_path_style: bool = False
    executor_host: str = "0.0.0.0"
    executor_port: int = Field(default=8091, ge=1, le=65_535)
    executor_hmac_secret: SecretStr | None = None
    executor_signature_skew_seconds: int = Field(default=30, ge=5, le=300)
    executor_replay_cache_entries: int = Field(default=10_000, ge=128, le=1_000_000)
    executor_max_request_bytes: int = Field(
        default=16_777_216,
        ge=1_024,
        le=16_777_216,
    )
    executor_max_response_bytes: int = Field(
        default=16_777_216,
        ge=1_024,
        le=16_777_216,
    )
    executor_max_concurrent_executions: int = Field(default=4, ge=1, le=128)
    executor_max_queued_executions: int = Field(default=16, ge=0, le=1_024)
    executor_admission_timeout_seconds: float = Field(
        default=2.0,
        ge=0.01,
        le=60.0,
    )

    @field_validator("worker_id", "storage_bucket", "executor_host")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Agent worker setting must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_lease_timing(self) -> "AgentWorkerSettings":
        if self.heartbeat_seconds >= self.lease_seconds / 2:
            raise ValueError(
                "Agent worker heartbeat must be less than half the lease duration"
            )
        return self

    @property
    def resolved_database_url(self) -> str:
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        database_path = (self.workspace / "grafy.sqlite3").resolve()
        return f"sqlite+aiosqlite:///{database_path}"

    def require_executor_hmac_secret(self) -> bytes:
        if self.executor_hmac_secret is None:
            raise ValueError("GRAFY_AGENT_WORKER_EXECUTOR_HMAC_SECRET is required")
        secret = self.executor_hmac_secret.get_secret_value().encode("utf-8")
        if len(secret) < 32:
            raise ValueError(
                "GRAFY_AGENT_WORKER_EXECUTOR_HMAC_SECRET must contain at least 32 bytes"
            )
        return secret


__all__ = ["AgentWorkerSettings"]
