"""Plugin discovery, authoring, and isolated sandbox runtime configuration."""

import re
from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from grafy_shared.config.base import SECTION_SETTINGS


class PluginsConfig(BaseSettings):
    """Where Plugins come from and what their sandboxes are allowed to cost."""

    model_config: ClassVar[SettingsConfigDict] = SECTION_SETTINGS

    plugin_roots: tuple[Path, ...] = (
        Path("examples"),
        Path("plugins"),
        Path(".grafy-artifacts/workspace-plugins"),
    )
    # Coding-agent authoring is assigned deterministically beneath this
    # deployment-owned Plugin root. It never chooses an arbitrary host path.
    plugin_authoring_root: Path = Path(".grafy-artifacts/workspace-plugins")
    # Source used to build the versioned SDK wheel vendored into a generated
    # working copy. The resulting Plugin has no monorepo-relative dependency.
    plugin_sdk_project: Path = Path("libs/core")
    # Deployment-owned default runtime profile for published Plugin releases.
    plugin_runtime_profile: Literal[
        "python-uv",
        "python-uv-gdal",
        "python-uv-tesseract",
        "python-uv-gdal-tesseract",
    ] = "python-uv"
    plugin_runtime_native_base_image: str | None = None
    plugin_runtime_native_base_image_digest: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    # Workspace Plugin execution is fail-closed unless the local Docker
    # sandbox owner is explicitly enabled for this single API process.
    plugin_runtime_enabled: bool = False
    # Development only. System Plugin slugs from plugins/system-plugins.toml, or
    # exact "module:attribute" loader targets, installed in-process beside the
    # builtin families. They run unsandboxed and bypass release publication.
    dev_plugins: tuple[str, ...] = ()
    plugin_docker_binary: str = Field(default="docker", min_length=1, max_length=1_024)
    # The Docker daemon must be able to bind this host path into one-shot
    # publisher containers. The local default stays beneath the repository.
    plugin_publisher_scratch_root: Path = Path(".grafy-artifacts/plugin-publisher")
    plugin_runtime_seccomp_profile: Path | None = None
    # Deployment-owned directory of versioned Grafy Plugin SDK wheels (e.g. a
    # built grapy-core wheel) exposed to Plugin dependency resolution via
    # UV_FIND_LINKS. Plugins never depend on monorepo paths.
    plugin_wheelhouse: Path | None = None
    max_active_plugin_invocations: int = Field(default=4, ge=1, le=128)
    plugin_invocation_wall_time_seconds_by_slug: dict[str, int] = Field(
        default_factory=dict,
    )
    max_live_plugin_sandboxes: int = Field(default=4, ge=1, le=64)
    max_distinct_plugin_releases_per_graph: int = Field(default=4, ge=1, le=64)
    # Origin-keyed sandboxes turn one release into multiple variants. This
    # bound must never exceed global live-sandbox capacity.
    max_plugin_sandbox_variants_per_execution: int = Field(default=4, ge=1, le=64)

    @model_validator(mode="after")
    def validate_plugin_capacity(self) -> "PluginsConfig":
        if self.max_distinct_plugin_releases_per_graph > self.max_live_plugin_sandboxes:
            raise ValueError(
                "max_distinct_plugin_releases_per_graph cannot exceed "
                "max_live_plugin_sandboxes"
            )
        if (
            self.max_plugin_sandbox_variants_per_execution
            > self.max_live_plugin_sandboxes
        ):
            raise ValueError(
                "max_plugin_sandbox_variants_per_execution cannot exceed "
                "max_live_plugin_sandboxes"
            )
        return self

    @field_validator("plugin_invocation_wall_time_seconds_by_slug")
    @classmethod
    def validate_plugin_invocation_wall_times(
        cls,
        value: dict[str, int],
    ) -> dict[str, int]:
        for slug, seconds in value.items():
            if re.fullmatch(r"[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*", slug) is None:
                raise ValueError(f"Invalid Plugin slug {slug!r}")
            if seconds < 1 or seconds > 3_600:
                raise ValueError(
                    f"Plugin invocation wall time for {slug!r} must be between "
                    "1 and 3600 seconds"
                )
        return value

    @property
    def resolved_plugin_roots(self) -> tuple[Path, ...]:
        return tuple(root.expanduser().resolve() for root in self.plugin_roots)

    @property
    def resolved_plugin_wheelhouse(self) -> Path | None:
        if self.plugin_wheelhouse is None:
            return None
        return self.plugin_wheelhouse.expanduser().resolve()

    @property
    def resolved_plugin_authoring_root(self) -> Path:
        return self.plugin_authoring_root.expanduser().resolve()

    @property
    def resolved_plugin_publisher_scratch_root(self) -> Path:
        return self.plugin_publisher_scratch_root.expanduser().resolve()

    @property
    def resolved_plugin_sdk_project(self) -> Path:
        return self.plugin_sdk_project.expanduser().resolve()

    @property
    def resolved_seccomp_profile(self) -> Path | None:
        if self.plugin_runtime_seccomp_profile is None:
            return None
        return self.plugin_runtime_seccomp_profile.expanduser().resolve()
