from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from grafy_core.domain.collaboration import (
    ProjectCheckpointMapping,
    ProjectCommandReceipt,
    ProjectHead,
)
from grafy_core.ports.transactions import TransactionPort

if TYPE_CHECKING:
    from grafy_core.ports.identity import (
        IdentityRepositoryPort,
        SecurityAuditRepositoryPort,
    )
    from grafy_core.ports.node_secrets import NodeSecretRepositoryPort
    from grafy_core.ports.projects import ProjectRepositoryPort


class CollaborationRepositoryPort(Protocol):
    async def add_head(self, head: ProjectHead) -> None: ...

    async def get_head(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectHead | None: ...

    async def lock_head(
        self,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectHead | None:
        """Read the head for update inside the current transaction."""
        ...

    async def save_head(self, head: ProjectHead) -> None: ...

    async def remove_head(self, workspace_id: UUID, project_id: UUID) -> None: ...

    async def get_receipt(
        self,
        workspace_id: UUID,
        project_id: UUID,
        command_id: UUID,
    ) -> ProjectCommandReceipt | None: ...

    async def add_receipt(self, receipt: ProjectCommandReceipt) -> None: ...

    async def get_checkpoint_mapping(
        self,
        workspace_id: UUID,
        project_id: UUID,
        *,
        room_epoch: UUID,
        collaboration_sequence: int,
    ) -> ProjectCheckpointMapping | None: ...

    async def add_checkpoint_mapping(
        self,
        mapping: ProjectCheckpointMapping,
    ) -> None: ...


class CollaborationUnitOfWorkPort(TransactionPort, Protocol):
    @property
    def collaboration(self) -> CollaborationRepositoryPort: ...

    @property
    def projects(self) -> "ProjectRepositoryPort": ...

    @property
    def node_secrets(self) -> "NodeSecretRepositoryPort": ...

    @property
    def identity(self) -> "IdentityRepositoryPort": ...

    @property
    def security_audit(self) -> "SecurityAuditRepositoryPort": ...
