"""Admission limits for graph execution and Plugin invocation."""

from typing import ClassVar

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS


class ExecutionConfig(BaseSettings):
    """How much graph work one API process admits at once."""

    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    map_max_concurrency: int = Field(default=4, ge=1)
    max_active_executions: int = Field(default=2, ge=1, le=32)
    max_pending_graphs: int = Field(default=20, ge=1, le=1_000)
