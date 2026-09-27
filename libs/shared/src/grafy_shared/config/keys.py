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
        if configured is None:
            raise ValueError(
                "GRAFY_COMMAND_HMAC_KEY must be configured for collaboration"
            )
        value = configured.get_secret_value()
        if value == "":
            raise ValueError("GRAFY_COMMAND_HMAC_KEY must not be empty")
        return value.encode("utf-8")
