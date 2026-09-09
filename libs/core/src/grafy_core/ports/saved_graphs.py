from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from grafy_core.domain.saved_graphs import (
    GraphBrowserItem,
    GraphFolder,
    GraphOrganization,
    SavedGraph,
    SavedGraphRevision,
    UserGraphState,
)
from grafy_core.ports.transactions import TransactionPort

if TYPE_CHECKING:
    from grafy_core.ports.identity import (
        IdentityRepositoryPort,
        SecurityAuditRepositoryPort,
    )
    from grafy_core.ports.materialized_outputs import (
        MaterializedNodeOutputsRepositoryPort,
    )
    from grafy_core.ports.node_secrets import NodeSecretRepositoryPort


class SavedGraphRepositoryPort(Protocol):
    async def add(self, graph: SavedGraph) -> None: ...

    async def add_revision(self, revision: SavedGraphRevision) -> None: ...

    async def lock_revision(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        expected_revision: int,
    ) -> None: ...

    async def get(self, workspace_id: UUID, graph_id: UUID) -> SavedGraph | None: ...

    async def get_revision(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        revision: int,
    ) -> SavedGraphRevision | None: ...

    async def list_revisions(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> list[SavedGraphRevision]: ...

    async def list_accessible(self, user_id: UUID) -> list[GraphBrowserItem]: ...

    async def add_folder(self, folder: GraphFolder) -> None: ...

    async def get_folder(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> GraphFolder | None: ...

    async def get_folder_by_name(
        self,
        workspace_id: UUID,
        name: str,
    ) -> GraphFolder | None: ...

    async def list_folders(self, workspace_id: UUID) -> list[GraphFolder]: ...

    async def list(self, workspace_id: UUID) -> list[SavedGraph]: ...

    async def save_folder(self, folder: GraphFolder) -> None: ...

    async def unfile_graphs_in_folder(
        self,
        workspace_id: UUID,
        folder_id: UUID,
    ) -> None: ...

    async def remove_folder(self, folder: GraphFolder) -> None: ...

    async def get_organization(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> GraphOrganization | None: ...

    async def save_organization(self, organization: GraphOrganization) -> None: ...

    async def get_user_state(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        user_id: UUID,
    ) -> UserGraphState | None: ...

    async def save_user_state(self, state: UserGraphState) -> None: ...

    async def remove(self, workspace_id: UUID, graph: SavedGraph) -> None: ...


class SavedGraphUnitOfWorkPort(TransactionPort, Protocol):
    @property
    def materialized_outputs(self) -> "MaterializedNodeOutputsRepositoryPort": ...

    @property
    def graphs(self) -> SavedGraphRepositoryPort: ...

    @property
    def node_secrets(self) -> "NodeSecretRepositoryPort": ...

    @property
    def identity(self) -> "IdentityRepositoryPort": ...

    @property
    def security_audit(self) -> "SecurityAuditRepositoryPort": ...
