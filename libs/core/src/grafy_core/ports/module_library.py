from typing import Protocol
from uuid import UUID

from grafy_core.domain.module_library import Module, ModuleRelease
from grafy_core.ports.collaboration import CollaborationRepositoryPort
from grafy_core.ports.identity import IdentityRepositoryPort
from grafy_core.ports.saved_graphs import SavedGraphRepositoryPort
from grafy_core.ports.transactions import TransactionPort


class ModuleLibraryRepositoryPort(Protocol):
    async def add(self, module: Module) -> None: ...

    async def add_release(self, release: ModuleRelease) -> None: ...

    async def get(self, workspace_id: UUID, module_id: UUID) -> Module | None: ...

    async def get_by_source_graph(
        self,
        workspace_id: UUID,
        source_graph_id: UUID,
    ) -> Module | None: ...

    async def get_release(
        self,
        workspace_id: UUID,
        module_id: UUID,
        revision: int,
    ) -> ModuleRelease | None: ...

    async def list_modules(self, workspace_id: UUID) -> list[Module]: ...

    async def list_library(self, workspace_id: UUID) -> list[Module]: ...

    async def list_releases(
        self,
        workspace_id: UUID,
        module_id: UUID,
    ) -> list[ModuleRelease]: ...


class ModuleLibraryUnitOfWorkPort(TransactionPort, Protocol):
    @property
    def graphs(self) -> SavedGraphRepositoryPort: ...

    @property
    def modules(self) -> ModuleLibraryRepositoryPort: ...

    @property
    def collaboration(self) -> CollaborationRepositoryPort: ...

    @property
    def identity(self) -> IdentityRepositoryPort: ...


__all__ = [
    "ModuleLibraryRepositoryPort",
    "ModuleLibraryUnitOfWorkPort",
]
