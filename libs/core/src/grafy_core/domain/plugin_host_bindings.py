"""Historical System release-to-host binding contracts."""

from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from grafy_core.domain.plugin_installations import InstalledPluginRelease
from grafy_core.domain.plugin_releases import (
    PluginCatalogManifest,
    PluginReleaseScope,
    plugin_contract_digest,
)


class LoadedSystemPlugin(BaseModel):
    """Deployment manifest for the exact Plugin bytes loaded by this process."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    slug: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$", max_length=100)
    loader_target: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_.]*(?::[A-Za-z_][A-Za-z0-9_.]*)?$",
        max_length=512,
    )
    host_build_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class SystemHostPluginBinding(BaseModel):
    """Exact deployment identity allowed to execute through the host registry."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    scope: Literal[PluginReleaseScope.SYSTEM] = PluginReleaseScope.SYSTEM
    release_id: UUID
    slug: str = Field(pattern=r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$", max_length=100)
    revision: int = Field(ge=1, strict=True)
    selection_generation: int = Field(ge=1, strict=True)
    descriptor_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    contract_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_archive_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    loader_target: str = Field(
        pattern=r"^[A-Za-z_][A-Za-z0-9_.]*(?::[A-Za-z_][A-Za-z0-9_.]*)?$",
        max_length=512,
    )
    host_build_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    catalog: PluginCatalogManifest

    @model_validator(mode="after")
    def validate_catalog_identity(self) -> Self:
        if self.catalog.slug != self.slug:
            raise ValueError("System host binding slug must match its catalog")
        if plugin_contract_digest(self.catalog) != self.contract_digest:
            raise ValueError(
                "System host binding contract digest must match its catalog"
            )
        return self

    @classmethod
    def from_release(
        cls,
        release: InstalledPluginRelease,
        *,
        selection_generation: int,
        loader_target: str,
        host_build_digest: str,
    ) -> "SystemHostPluginBinding":
        if release.installation.scope is not PluginReleaseScope.SYSTEM:
            raise ValueError("Only System Plugin releases can bind to host code")
        if release.release.runtime_artifact is None:
            raise ValueError("System host bindings require a retained OCI artifact")
        return cls(
            release_id=release.release.id,
            slug=release.release.slug,
            revision=release.release.revision,
            selection_generation=selection_generation,
            descriptor_digest=release.release.descriptor.digest,
            contract_digest=release.release.contract_digest,
            source_digest=release.release.source_digest,
            runtime_archive_digest=release.release.runtime_artifact.archive_digest,
            loader_target=loader_target,
            host_build_digest=host_build_digest,
            catalog=release.release.catalog,
        )

    def release_mismatch(self, release: InstalledPluginRelease) -> str | None:
        """Return the first immutable identity mismatch, if one exists."""

        if (
            release.installation.scope is not self.scope
            or release.installation.workspace_id is not None
        ):
            return "scope"
        if release.release.id != self.release_id:
            return "release id"
        if release.release.slug != self.slug:
            return "slug"
        if release.release.revision != self.revision:
            return "revision"
        if release.release.descriptor.digest != self.descriptor_digest:
            return "descriptor digest"
        if release.release.contract_digest != self.contract_digest:
            return "contract digest"
        if release.release.source_digest != self.source_digest:
            return "source digest"
        if release.release.runtime_artifact is None:
            return "runtime artifact"
        if (
            release.release.runtime_artifact.archive_digest
            != self.runtime_archive_digest
        ):
            return "runtime archive digest"
        if release.release.catalog != self.catalog:
            return "catalog"
        return None
