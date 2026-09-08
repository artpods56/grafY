from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from grafy_core.domain.execution_history import ActiveGraphExecution
from grafy_core.domain.plugin_releases import (
    PluginCatalogManifest,
    PluginRelease,
    PluginReleaseNamespace,
    PluginRuntimeArtifact,
)
from grafy_core.domain.plugin_installations import (
    InstalledPluginRelease,
    PluginInstallation,
)
from grafy_core.domain.plugin_revocations import PluginReleaseRevocation
from grafy_core.domain.plugin_selection import PluginReleaseSelection
from grafy_core.ports.identity import IdentityRepositoryPort


class PluginReleaseRepositoryPort(Protocol):
    async def lock_system_revocation(self) -> tuple[ActiveGraphExecution, ...]:
        """Fence durable execution admission and report active executions.

        Call before any reads in a fresh transaction. Hold the fence until the
        transaction commits or rolls back, including when no executions exist.
        """
        ...

    async def add(self, release: PluginRelease) -> None: ...

    async def add_installation(self, installation: PluginInstallation) -> None: ...

    async def get_by_source_digest(
        self,
        slug: str,
        source_digest: str,
    ) -> PluginRelease | None: ...

    async def get_by_descriptor_digest(
        self,
        slug: str,
        descriptor_digest: str,
    ) -> PluginRelease | None: ...

    async def get_by_revision(
        self,
        namespace: PluginReleaseNamespace,
        slug: str,
        revision: int,
    ) -> InstalledPluginRelease | None: ...

    async def get_revocation_by_installation_id(
        self,
        installation_id: UUID,
    ) -> PluginReleaseRevocation | None: ...

    async def add_revocation(
        self,
        revocation: PluginReleaseRevocation,
    ) -> PluginReleaseRevocation: ...

    async def next_revision(
        self,
        slug: str,
    ) -> int: ...

    async def family_exists(
        self,
        namespace: PluginReleaseNamespace,
        slug: str,
    ) -> bool: ...

    async def workspace_family_exists(self, slug: str) -> bool: ...

    async def list_workspace_catalogs(self) -> list[PluginCatalogManifest]: ...

    async def list_catalogs(
        self,
        namespace: PluginReleaseNamespace,
    ) -> list[PluginCatalogManifest]: ...

    async def list_current(
        self,
        namespace: PluginReleaseNamespace,
    ) -> list[InstalledPluginRelease]: ...

    async def get_selection(
        self,
        namespace: PluginReleaseNamespace,
        slug: str,
    ) -> PluginReleaseSelection | None: ...

    async def add_selection(
        self,
        selection: PluginReleaseSelection,
    ) -> None: ...

    async def update_selection(
        self,
        selection: PluginReleaseSelection,
        *,
        expected_generation: int,
    ) -> None: ...

    async def list_runtime_artifacts(self) -> list[PluginRuntimeArtifact]: ...


class PluginReleaseUnitOfWorkPort(Protocol):
    @property
    def plugin_releases(self) -> PluginReleaseRepositoryPort: ...

    @property
    def identity(self) -> IdentityRepositoryPort: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


__all__ = ["PluginReleaseRepositoryPort", "PluginReleaseUnitOfWorkPort"]
