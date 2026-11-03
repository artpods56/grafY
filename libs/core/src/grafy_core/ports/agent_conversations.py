"""Ports for Agent conversation history (ADR 0021, issue #202).

Both adapters behind these ports keep the same three promises:

* **Append takes the sequence the conversation is waiting for.** ``append`` stores an
  event whose ``sequence`` equals the stored conversation's ``next_sequence`` and moves
  the conversation on by one. A stored conversation that has already moved on raises
  :class:`AgentConversationAppendError` rather than writing a second event at the same
  sequence or leaving a hole.
* **History is immutable.** There is no update, delete or reorder of an event. A
  conversation only ever changes its ``next_sequence`` and ``updated_at``, and a fork
  copies events into a new conversation instead of trimming the source.
* **Workspace scoping.** Every read and write carries ``workspace_id``, so a row of
  another Workspace reads as absent.

``lock`` exists because "one turn runs at a time per conversation" is decided from the
stored history: the SQL adapter takes a row lock, and the in-memory adapter notes that
its unit of work's transaction lock is what actually serialises writers.
"""

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from grafy_core.domain.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
)
from grafy_core.ports.transactions import TransactionPort

if TYPE_CHECKING:
    from grafy_core.ports.collaboration import CollaborationRepositoryPort
    from grafy_core.ports.projects import ProjectRepositoryPort


class AgentConversationAppendError(RuntimeError):
    """The conversation is no longer at the sequence the appended event carries."""


class AgentConversationRepositoryPort(Protocol):
    async def add(self, conversation: AgentConversation) -> None: ...

    async def get(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> AgentConversation | None: ...

    async def lock(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> AgentConversation | None: ...

    async def list_for_agent(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> list[AgentConversation]: ...

    async def append(self, event: AgentConversationEvent) -> None: ...

    async def list_events(
        self,
        workspace_id: UUID,
        conversation_id: UUID,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[AgentConversationEvent]: ...


class AgentConversationUnitOfWorkPort(TransactionPort, Protocol):
    @property
    def projects(self) -> "ProjectRepositoryPort": ...

    @property
    def collaboration(self) -> "CollaborationRepositoryPort": ...

    @property
    def agent_conversations(self) -> AgentConversationRepositoryPort: ...


__all__ = [
    "AgentConversationAppendError",
    "AgentConversationRepositoryPort",
    "AgentConversationUnitOfWorkPort",
]
