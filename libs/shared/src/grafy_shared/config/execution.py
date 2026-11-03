"""Per-Project computation and MAP concurrency."""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS


class ExecutionConfig(BaseSettings):
    """The computation budget of each Project scheduler."""

    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    map_max_concurrency: int = Field(default=4, ge=1)
    project_computation_concurrency: int = Field(default=2, ge=1, le=32)
