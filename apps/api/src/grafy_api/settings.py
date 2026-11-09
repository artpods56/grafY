"""The composed application configuration read by the API composition root.

Each section of :mod:`grafy_shared.config` is its own ``BaseSettings`` over the flat
``GRAFY_*`` namespace, so an operator-facing variable name never changes when a field
moves between sections. This parent is a plain ``BaseModel``: it reads no environment
itself, which is what keeps it out of the way of everything that needs one section.

This module is the only reader of the whole configuration object. The one runtime
policy it composes is the egress authority: ``grafy_core.egress`` decides, from
``EgressConfig.egress_trusted_destinations``, whether the API may dial a destination a
node named. Configuration stays a leaf and never imports the application. See
``docs/adr/0011-shared-configuration-is-a-leaf-package.md``.
"""

from functools import lru_cache

from pydantic import BaseModel, ConfigDict, Field

from grafy_shared.config import (
    STAGED_UPLOAD_HARD_MAX_BYTES,
    AgentsConfig,
    AppConfig,
    AuthConfig,
    EgressConfig,
    ExecutionConfig,
    KeysConfig,
    RealtimeConfig,
    StorageConfig,
    UploadConfig,
)

__all__ = [
    "STAGED_UPLOAD_HARD_MAX_BYTES",
    "Settings",
    "get_settings",
]


class Settings(BaseModel):
    """Every configuration section, composed by reading the environment once each.

    A caller narrows one section by passing it: ``Settings(app=AppConfig(...))``.
    Each section is a ``BaseSettings`` and honours ``_env_file=None`` itself, so the
    parent has no environment behaviour of its own to forward.

    ``extra="forbid"`` is what makes that forwarding rule loud. A leftover
    ``Settings(workspace=...)`` used to build a valid object that silently kept the
    default ``AppConfig``, so the app ran against the wrong workspace and database
    while every assertion about them still passed.
    """

    model_config = ConfigDict(extra="forbid")

    app: AppConfig = Field(default_factory=AppConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    keys: KeysConfig = Field(default_factory=KeysConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    realtime: RealtimeConfig = Field(default_factory=RealtimeConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    uploads: UploadConfig = Field(default_factory=UploadConfig)
    egress: EgressConfig = Field(default_factory=EgressConfig)


@lru_cache
def get_settings() -> Settings:
    return Settings()
