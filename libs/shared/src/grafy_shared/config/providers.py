"""Deployment defaults for provider-backed node secrets."""

from typing import ClassVar

from pydantic import AnyHttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS


class ProviderSecretsConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    reducto_api_key: SecretStr | None = None
    mistral_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_base_url: AnyHttpUrl | None = None

    @field_validator("openai_base_url")
    @classmethod
    def validate_base_url(cls, value: AnyHttpUrl | None) -> AnyHttpUrl | None:
        if value is None:
            return value
        if value.username is not None or value.password is not None:
            raise ValueError(
                "GRAFY_OPENAI_BASE_URL must not carry embedded credentials"
            )
        if value.query or value.fragment:
            raise ValueError(
                "GRAFY_OPENAI_BASE_URL must be a query-free service endpoint"
            )
        if value.scheme not in ("http", "https"):
            raise ValueError("GRAFY_OPENAI_BASE_URL must be an http or https endpoint")
        return value
