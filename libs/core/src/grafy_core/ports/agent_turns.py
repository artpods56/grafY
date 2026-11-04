"""Ports for durable Agent turn receipts (ADR 0021, issue #202).

Both adapters behind this port keep the same two admission rules, because both are the
rule rather than a cache of it:

* **A client turn id is admitted once per conversation.** ``add`` writes the receipt the
  send was accepted with; a second ``add`` under the same
  ``(workspace_id, conversation_id, client_turn_id)`` is refused with
  :class:`AgentTurnAlreadyAdmittedError` rather than writing a second row. The service
  turns that refusal into an idempotent replay or a conflict by reading the receipt back.
* **One turn runs per conversation.** ``add`` is refused with
  :class:`AgentTurnBusyError` while another receipt for the same conversation is
  ``running``, whichever transaction got there first.

``finish`` moves a receipt out of ``running`` only if it is still there, so a cancel, a
model failure and startup recovery cannot each write a terminal state for one turn: the
first caller's answer stands and the others are told they did not claim it. That is the
same "claim by conditional update" the conversation append uses, and it is what makes
"marked interrupted exactly once" a property rather than a hope.

Every read and write carries ``workspace_id``, so a receipt of another Workspace reads as
absent. ``list_running`` is the one unscoped read, and it is scoped by role instead: it is
what the API owner runs at startup, before any request has a Workspace to narrow by.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from grafy_core.domain.agent_turns import AgentTurn, AgentTurnStatus
from grafy_core.ports.transactions import TransactionPort

if TYPE_CHECKING:
    from grafy_core.ports.agent_conversations import AgentConversationRepositoryPort
    from grafy_core.ports.collaboration import CollaborationRepositoryPort
    from grafy_core.ports.projects import ProjectRepositoryPort


class AgentTurnAlreadyAdmittedError(RuntimeError):
    """This client turn id has already been admitted for this conversation."""


class AgentTurnBusyError(RuntimeError):
    """Another turn of this conversation is still running."""

    def __init__(
        self, conversation_id: UUID, running_turn_id: UUID | None = None
    ) -> None:
        super().__init__(
            f"Agent conversation {conversation_id} is running turn {running_turn_id}"
            if running_turn_id is not None
            else f"Agent conversation {conversation_id} is running a turn"
        )
        self.conversation_id = conversation_id
        self.running_turn_id = running_turn_id


class AgentTurnRepositoryPort(Protocol):
    async def add(self, turn: AgentTurn) -> None:
        """Admit a turn. Raises if its id is taken or its conversation is busy."""

        ...

    async def get(self, workspace_id: UUID, turn_id: UUID) -> AgentTurn | None: ...

    async def get_by_client_turn_id(
        self, workspace_id: UUID, conversation_id: UUID, client_turn_id: str
    ) -> AgentTurn | None: ...

    async def running_for_conversation(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> AgentTurn | None: ...

    async def list_for_conversation(
        self, workspace_id: UUID, conversation_id: UUID, *, limit: int | None = None
    ) -> list[AgentTurn]: ...

    async def finish(
        self,
        workspace_id: UUID,
        turn_id: UUID,
        *,
        status: AgentTurnStatus,
        at: datetime,
        detail: str | None = None,
    ) -> AgentTurn | None:
        """Claim a running turn's terminal state, or answer ``None`` if it was claimed."""

        ...

    async def list_running(self) -> list[AgentTurn]:
        """Every turn this database still believes is running, whatever its Workspace."""

        ...


class AgentTurnUnitOfWorkPort(TransactionPort, Protocol):
    """The unit of work the turn runtime needs: turns, and the history they write.

    Admission is one transaction because a turn and its user message are one fact: a
    receipt with no message, or a message with no receipt, is a send that cannot be
    answered idempotently.
    """

    @property
    def projects(self) -> "ProjectRepositoryPort": ...

    @property
    def collaboration(self) -> "CollaborationRepositoryPort": ...

    @property
    def agent_conversations(self) -> "AgentConversationRepositoryPort": ...

    @property
    def agent_turns(self) -> AgentTurnRepositoryPort: ...


__all__ = [
    "AgentTurnAlreadyAdmittedError",
    "AgentTurnBusyError",
    "AgentTurnRepositoryPort",
    "AgentTurnUnitOfWorkPort",
]
