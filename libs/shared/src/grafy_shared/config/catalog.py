"""Deployment configuration for catalog discovery."""

import tomllib
from pathlib import Path
from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS


class CatalogDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    workspace_packs: list[str] | None = None


class CatalogOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    defaults: CatalogDefaults = Field(default_factory=CatalogDefaults)
    packs: dict[str, bool] = Field(default_factory=dict)
    operators: dict[str, bool] = Field(default_factory=dict)


class CatalogConfig(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = {
        **SECTION_SETTINGS,
        "env_ignore_empty": True,
    }

    catalog_config: Path | None = None

    def load_overrides(self) -> CatalogOverrides:
        path = self.catalog_config
        if path is None:
            return CatalogOverrides()
        try:
            with path.open("rb") as source:
                return CatalogOverrides.model_validate(tomllib.load(source))
        except (OSError, ValueError) as exc:
            raise ValueError(f"GRAFY_CATALOG_CONFIG ({path}): {exc}") from exc
