"""The composed application configuration read by the API composition root.

Each section of :mod:`grafy_shared.config` is its own ``BaseSettings`` over the flat
``GRAFY_*`` namespace, so an operator-facing variable name never changes when a field
moves between sections. This parent is a plain ``BaseModel``: it reads no environment
itself, which is what keeps it out of the way of everything that needs one section.

This module is the only reader of the whole configuration object, and it never imports
``grafy_api.plugins.runtime``. Runtime policy objects are built by the runtime from an
``EgressConfig`` (``NetworkPolicy.from_config`` and
``PluginEgressBrokerPolicy.from_config``), so configuration configures the runtime
instead of importing it. See
``docs/adr/0011-shared-configuration-is-a-leaf-package.md``.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings

from grafy_shared.config import (
    STAGED_UPLOAD_HARD_MAX_BYTES,
    AppConfig,
    AuthConfig,
    EgressConfig,
    ExecutionConfig,
    KeysConfig,
    PluginsConfig,
    RealtimeConfig,
    StorageConfig,
    UploadConfig,
)
from grafy_shared.config.base import read_section

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
    auth: AuthConfig = Field(default_factory=AuthConfig)
    keys: KeysConfig = Field(default_factory=KeysConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    realtime: RealtimeConfig = Field(default_factory=RealtimeConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    uploads: UploadConfig = Field(default_factory=UploadConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    egress: EgressConfig = Field(default_factory=EgressConfig)

    def model_copy(
        self, *, update: Mapping[str, Any] | None = None, deep: bool = False
    ) -> "Settings":
        """Copy sections only.

        ``BaseModel.model_copy`` writes ``update`` keys straight into ``__dict__``
        without validation, so ``model_copy(update={"database_url": ...})`` would
        appear to work while every reader of ``app.database_url`` kept the old value.
        A section is copied instead: ``model_copy(update={"app": ...})``, and the
        message says which section owns the name that was passed.
        """

        unknown = set(update or {}) - set(Settings.model_fields)
        if unknown:
            owners: dict[str, str] = {}
            for section_name, section_field in Settings.model_fields.items():
                section_type = section_field.annotation
                if not isinstance(section_type, type) or not issubclass(
                    section_type, BaseSettings
                ):
                    continue
                for field_name in section_type.model_fields:
                    owners[field_name] = section_name
            details = ", ".join(
                f"{name} (copy the {owners[name]} section instead)"
                if name in owners
                else name
                for name in sorted(unknown)
            )
            raise TypeError(f"Settings has no field(s) {details}")
        return super().model_copy(update=update, deep=deep)

    @classmethod
    def from_environment(cls, *, env_file: str | Path | None = ".env") -> "Settings":
        """Read all sections, optionally suppressing the ``.env`` file entirely."""

        return cls(
            app=read_section(AppConfig, env_file=env_file),
            auth=read_section(AuthConfig, env_file=env_file),
            keys=read_section(KeysConfig, env_file=env_file),
            execution=read_section(ExecutionConfig, env_file=env_file),
            realtime=read_section(RealtimeConfig, env_file=env_file),
            storage=read_section(StorageConfig, env_file=env_file),
            uploads=read_section(UploadConfig, env_file=env_file),
            plugins=read_section(PluginsConfig, env_file=env_file),
            egress=read_section(EgressConfig, env_file=env_file),
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
