"""Secret key material the API wraps, signs, and stamps commands with."""

from typing import ClassVar

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS


class KeysConfig(BaseSettings):
    """Deployment keys. Values are secret and must never gain a dump path."""

    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    credential_encryption_key: SecretStr | None = None
    command_hmac_key: SecretStr | None = None
    command_hmac_key_version: int = Field(default=1, ge=1)

    def resolved_command_hmac_key(self) -> bytes:
        """Return the deployment HMAC key, failing closed when unset or empty."""
        configured = self.command_hmac_key
        value = configured.get_secret_value() if configured is not None else ""
        if not value:
            raise ValueError(
                "API startup failed: GRAFY_COMMAND_HMAC_KEY is missing or empty. "
                "Set it in the repository-root .env file or export it before "
                "starting the API. Generate one with: "
                'export GRAFY_COMMAND_HMAC_KEY="$(openssl rand -hex 32)"'
            )
        return value.encode("utf-8")
