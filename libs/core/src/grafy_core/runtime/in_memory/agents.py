from datetime import datetime
from typing import override
from uuid import UUID

from grafy_core.domain.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
)
from grafy_core.domain.agent_turns import AgentTurn, AgentTurnStatus
from grafy_core.domain.errors import ConcurrentWriteError
from grafy_core.ports.agent_conversations import (
    AgentConversationAppendError,
    AgentConversationRepositoryPort,
)
from grafy_core.ports.agent_turns import (
    AgentTurnAlreadyAdmittedError,
    AgentTurnBusyError,
    AgentTurnRepositoryPort,
)

from grafy_core.runtime.in_memory.store import InMemoryDataStore, _newest_first


class InMemoryAgentConversationRepository(AgentConversationRepositoryPort):
    """Append-only Agent history over the cloned store.

    The conversation row is the sequence authority: an append only lands on the sequence
    the stored row is waiting for, and the row moves on with it. Frozen values are
    returned as stored - there is nothing for a caller to mutate behind the clone.
    """

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    @override
    async def add(self, conversation: AgentConversation) -> None:
        key = (conversation.workspace_id, conversation.id)
        if key in self._store.agent_conversations:
            raise ConcurrentWriteError(
                f"Agent conversation already exists: {conversation.id}"
            )
        self._store.agent_conversations[key] = conversation

    @override
    async def get(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> AgentConversation | None:
        return self._store.agent_conversations.get((workspace_id, conversation_id))

    @override
    async def lock(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> AgentConversation | None:
        # No row lock to imitate: the unit of work's transaction lock serialises writers.
        return await self.get(workspace_id, conversation_id)

    @override
    async def list_for_agent(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> list[AgentConversation]:
        rows = [
            conversation
            for conversation in self._store.agent_conversations.values()
            if conversation.workspace_id == workspace_id
            and conversation.project_id == project_id
            and conversation.graph_id == graph_id
            and conversation.agent_id == agent_id
        ]
        return _newest_first(
            rows,
            stamp=lambda conversation: conversation.created_at,
            ident=lambda conversation: conversation.id,
        )

    @override
    async def append(self, event: AgentConversationEvent) -> None:
        key = (event.workspace_id, event.conversation_id)
        conversation = self._store.agent_conversations.get(key)
        if conversation is None:
            raise AgentConversationAppendError(
                f"Agent conversation does not exist: {event.conversation_id}"
            )
        if conversation.next_sequence != event.sequence:
            raise AgentConversationAppendError(
                f"Agent conversation {event.conversation_id} is at sequence "
                f"{conversation.next_sequence}, not {event.sequence}"
            )
        event_key = (event.workspace_id, event.conversation_id, event.sequence)
        if event_key in self._store.agent_conversation_events:
            raise ConcurrentWriteError(
                f"Agent conversation event already stored: {event_key}"
            )
        self._store.agent_conversation_events[event_key] = event
        self._store.agent_conversations[key] = conversation.appended(
            at=event.created_at
        )

    @override
    async def list_events(
        self,
        workspace_id: UUID,
        conversation_id: UUID,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[AgentConversationEvent]:
        rows = [
            event
            for key, event in self._store.agent_conversation_events.items()
            if key[0] == workspace_id
            and key[1] == conversation_id
            and key[2] > after_sequence
        ]
        rows.sort(key=lambda event: event.sequence)
        return rows if limit is None else rows[:limit]


class InMemoryAgentTurnRepository(AgentTurnRepositoryPort):
    """Turn receipts over the shared store.

    The two admission rules are re-implemented here as the checks the SQL schema states as
    constraints, because an adapter that only *looks* like it refuses a second running turn
    would let the service believe it owns a conversation it does not: a duplicate receipt id
    and a conversation that already runs a turn are errors rather than silent overwrites.
    """

    def __init__(self, store: InMemoryDataStore) -> None:
        self._store = store

    @override
    async def add(self, turn: AgentTurn) -> None:
        if turn.id in self._store.agent_turns:
            raise ConcurrentWriteError(f"Agent turn already exists: {turn.id}")
        if (
            turn.workspace_id,
            turn.conversation_id,
            turn.client_turn_id,
        ) in {
            (other.workspace_id, other.conversation_id, other.client_turn_id)
            for other in self._store.agent_turns.values()
        }:
            raise AgentTurnAlreadyAdmittedError(
                f"Client turn {turn.client_turn_id} was already admitted for "
                f"conversation {turn.conversation_id}"
            )
        running = await self.running_for_conversation(
            turn.workspace_id, turn.conversation_id
        )
        if running is not None:
            raise AgentTurnBusyError(turn.conversation_id, running.id)
        self._store.agent_turns[turn.id] = turn

    @override
    async def get(self, workspace_id: UUID, turn_id: UUID) -> AgentTurn | None:
        turn = self._store.agent_turns.get(turn_id)
        if turn is None or turn.workspace_id != workspace_id:
            return None
        return turn

    @override
    async def get_by_client_turn_id(
        self, workspace_id: UUID, conversation_id: UUID, client_turn_id: str
    ) -> AgentTurn | None:
        return next(
            (
                turn
                for turn in self._store.agent_turns.values()
                if turn.workspace_id == workspace_id
                and turn.conversation_id == conversation_id
                and turn.client_turn_id == client_turn_id
            ),
            None,
        )

    @override
    async def running_for_conversation(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> AgentTurn | None:
        rows = [
            turn
            for turn in self._store.agent_turns.values()
            if turn.workspace_id == workspace_id
            and turn.conversation_id == conversation_id
        ]
        ordered = _newest_first(
            rows, stamp=lambda turn: turn.created_at, ident=lambda turn: turn.id
        )
        return next((turn for turn in ordered if turn.is_running), None)

    @override
    async def list_for_conversation(
        self, workspace_id: UUID, conversation_id: UUID, *, limit: int | None = None
    ) -> list[AgentTurn]:
        rows = [
            turn
            for turn in self._store.agent_turns.values()
            if turn.workspace_id == workspace_id
            and turn.conversation_id == conversation_id
        ]
        ordered = _newest_first(
            rows, stamp=lambda turn: turn.created_at, ident=lambda turn: turn.id
        )
        return ordered if limit is None else ordered[:limit]

    @override
    async def finish(
        self,
        workspace_id: UUID,
        turn_id: UUID,
        *,
        status: AgentTurnStatus,
        at: datetime,
        detail: str | None = None,
    ) -> AgentTurn | None:
        turn = await self.get(workspace_id, turn_id)
        if turn is None or not turn.is_running:
            # Already terminal, or never this Workspace's: the caller did not claim it.
            return None
        finished = turn.finished(status=status, at=at, detail=detail)
        self._store.agent_turns[turn_id] = finished
        return finished

    @override
    async def list_running(self) -> list[AgentTurn]:
        return sorted(
            (turn for turn in self._store.agent_turns.values() if turn.is_running),
            key=lambda turn: turn.created_at,
        )
