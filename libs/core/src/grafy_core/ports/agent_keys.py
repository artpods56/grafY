"""Ports for the encrypted per-Agent model key (ADR 0021, issue #202).

The row is indexed by where the Agent sits — Workspace, Project, Graph, Agent — and holds
sealed material only. Nothing here can produce plaintext: decryption belongs to the
application owner that holds the deployment key, exactly as node secrets do.
"""

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from grafy_core.domain.agent_keys import EncryptedAgentKey
from grafy_core.ports.transactions import TransactionPort

if TYPE_CHECKING:
    from grafy_core.ports.collaboration import CollaborationRepositoryPort
    from grafy_core.ports.projects import ProjectRepositoryPort


class AgentKeyRepositoryPort(Protocol):
    async def upsert(self, key: EncryptedAgentKey) -> None: ...

    async def get(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> EncryptedAgentKey | None: ...

    async def list_for_graph(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
    ) -> list[EncryptedAgentKey]: ...

    async def remove(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> None: ...


class AgentKeyUnitOfWorkPort(TransactionPort, Protocol):
    @property
    def projects(self) -> "ProjectRepositoryPort": ...

    @property
    def collaboration(self) -> "CollaborationRepositoryPort": ...

    @property
    def agent_keys(self) -> AgentKeyRepositoryPort: ...


__all__ = ["AgentKeyRepositoryPort", "AgentKeyUnitOfWorkPort"]
