"""Process, workspace and database configuration for the Grafy application."""

from pathlib import Path
from typing import ClassVar, Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS
from grafy_shared.config.origins import absolute_http_url


class AppConfig(BaseSettings):
    """Where the process runs, what it logs, and which database it owns."""

    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    workspace: Path = Path(".grafy-artifacts/workbench")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_renderer: Literal["console", "json"] = "console"
    environment: Literal["production", "development"] = "development"
    public_origin: str = "http://localhost:3000"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    database_url: SecretStr | None = None
    # Collaboration and shared execution assume one FastAPI process with one
    # HTTP worker. Startup acquires an exclusive lock under workspace when true.
    require_single_api_owner: bool = True

    @field_validator("public_origin")
    @classmethod
    def _validate_public_origin(cls, value: str) -> str:
        return absolute_http_url(value)

    @property
    def resolved_database_url(self) -> str:
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        database_path = (self.workspace / "grafy.sqlite3").resolve()
        return f"sqlite+aiosqlite:///{database_path}"

    @property
    def allowed_cors_origins(self) -> tuple[str, ...]:
        return tuple(
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        )
