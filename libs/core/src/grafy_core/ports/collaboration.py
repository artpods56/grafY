from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from grafy_core.domain.collaboration import (
    CollaborativeGraphHead,
    GraphCheckpointMapping,
    GraphCommandReceipt,
)
from grafy_core.ports.transactions import TransactionPort

if TYPE_CHECKING:
    from grafy_core.ports.execution_history import GraphExecutionHistoryRepositoryPort
    from grafy_core.ports.identity import (
        IdentityRepositoryPort,
        SecurityAuditRepositoryPort,
    )
    from grafy_core.ports.materialized_outputs import (
        MaterializedNodeOutputsRepositoryPort,
    )
    from grafy_core.ports.node_secrets import NodeSecretRepositoryPort
    from grafy_core.ports.saved_graphs import SavedGraphRepositoryPort


class CollaborationRepositoryPort(Protocol):
    async def add_head(self, head: CollaborativeGraphHead) -> None: ...

    async def get_head(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> CollaborativeGraphHead | None: ...

    async def lock_head(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> CollaborativeGraphHead | None: ...

    async def save_head(self, head: CollaborativeGraphHead) -> None: ...

    async def remove_head(self, workspace_id: UUID, graph_id: UUID) -> None: ...

    async def list_graphs_missing_heads(self) -> list[tuple[UUID, UUID]]:
        """Return workspace/graph ids for saved graphs without a collaborative head."""
        ...

    async def get_receipt(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        command_id: UUID,
    ) -> GraphCommandReceipt | None: ...

    async def add_receipt(self, receipt: GraphCommandReceipt) -> None: ...

    async def get_checkpoint_mapping(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        *,
        room_epoch: UUID,
        collaboration_sequence: int,
    ) -> GraphCheckpointMapping | None: ...

    async def add_checkpoint_mapping(
        self,
        mapping: GraphCheckpointMapping,
    ) -> None: ...


class CollaborationUnitOfWorkPort(TransactionPort, Protocol):
    @property
    def materialized_outputs(self) -> "MaterializedNodeOutputsRepositoryPort": ...

    @property
    def collaboration(self) -> CollaborationRepositoryPort: ...

    @property
    def graphs(self) -> "SavedGraphRepositoryPort": ...

    @property
    def node_secrets(self) -> "NodeSecretRepositoryPort": ...

    @property
    def identity(self) -> "IdentityRepositoryPort": ...

    @property
    def security_audit(self) -> "SecurityAuditRepositoryPort": ...

    @property
    def execution_history(self) -> "GraphExecutionHistoryRepositoryPort": ...
