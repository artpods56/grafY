"""Connection to the deployment-owned internal TIFF renderer."""

from typing import ClassVar, Self

from pydantic import Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS


class TilerConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = {
        **SECTION_SETTINGS,
        "env_ignore_empty": True,
    }

    tiler_url: HttpUrl | None = None
    tiler_shared_key: SecretStr | None = None
    tiler_renderer_version: str = Field(default="1", min_length=1)
    tiler_timeout_seconds: float = Field(default=10, gt=0)

    tiler_info_timeout_seconds: float = Field(default=30, gt=0)

    @model_validator(mode="after")
    def validate_connection(self) -> Self:
        if self.tiler_url is not None:
            if (
                self.tiler_url.username
                or self.tiler_url.password
                or self.tiler_url.query
                or self.tiler_url.fragment
            ):
                raise ValueError(
                    "Tiler URL cannot contain credentials, a query or a fragment"
                )
            if (
                self.tiler_shared_key is None
                or not 1
                <= len(self.tiler_shared_key.get_secret_value().split(","))
                <= 2
                or any(
                    len(key.strip()) < 32
                    for key in self.tiler_shared_key.get_secret_value().split(",")
                )
            ):
                raise ValueError(
                    "An enabled tiler requires a shared key of at least 32 characters"
                )
        return self
