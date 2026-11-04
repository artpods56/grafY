"""SQL adapters for Agent conversations and their ordered events (ADR 0021, issue #202).

Both repositories speak Core SQL and carry ``workspace_id`` in every ``WHERE``, so a
conversation of another Workspace is indistinguishable from one that was never there.

``append`` is the whole write path for history and it is deliberately narrow. It moves
the conversation's ``next_sequence`` with a conditional ``UPDATE`` — the row lock that
takes is what makes "one turn at a time per conversation" a property of the database
rather than of whoever got to the scheduler first — and only then inserts the event at
the sequence that update just claimed. An event row is never updated and never deleted;
a conversation row changes only its counter and its ``updated_at``.
"""

from typing import override
from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.engine import RowMapping
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from grafy_core.domain.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
    event_payload_from_storage,
    event_payload_to_storage,
)
from grafy_core.domain.errors import ConcurrentWriteError
from grafy_core.ports.agent_conversations import (
    AgentConversationAppendError,
    AgentConversationRepositoryPort,
)
from grafy_persistence import schema


def _conversation_from_row(row: RowMapping) -> AgentConversation:
    return AgentConversation.model_validate(dict(row))


def _event_from_row(row: RowMapping) -> AgentConversationEvent:
    values = dict(row)
    # ``kind`` is a copy of the payload discriminator kept for readers that narrow a
    # range of history without parsing it. A disagreement is a corrupted row, not a
    # payload to guess at.
    stored_kind = values.pop("kind")
    payload = event_payload_from_storage(values["payload"])
    if stored_kind != payload.kind:
        raise ValueError(
            f"Agent conversation event {values['conversation_id']}/"
            f"{values['sequence']} is stored as {stored_kind!r}, not {payload.kind!r}"
        )
    values["payload"] = payload
    return AgentConversationEvent.model_validate(values)


class SqlAgentConversationRepository(AgentConversationRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def add(self, conversation: AgentConversation) -> None:
        table = schema.agent_conversations
        try:
            await self._session.execute(
                insert(table).values(
                    id=conversation.id,
                    workspace_id=conversation.workspace_id,
                    project_id=conversation.project_id,
                    graph_id=conversation.graph_id,
                    agent_id=conversation.agent_id,
                    author_user_id=conversation.author_user_id,
                    title=conversation.title,
                    source_conversation_id=conversation.source_conversation_id,
                    source_sequence=conversation.source_sequence,
                    next_sequence=conversation.next_sequence,
                    created_at=conversation.created_at,
                    updated_at=conversation.updated_at,
                )
            )
        except IntegrityError as exc:
            raise ConcurrentWriteError(
                f"Agent conversation already exists: {conversation.id}"
            ) from exc

    @override
    async def get(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> AgentConversation | None:
        return await self._read(workspace_id, conversation_id, for_update=False)

    @override
    async def lock(
        self, workspace_id: UUID, conversation_id: UUID
    ) -> AgentConversation | None:
        return await self._read(workspace_id, conversation_id, for_update=True)

    async def _read(
        self, workspace_id: UUID, conversation_id: UUID, *, for_update: bool
    ) -> AgentConversation | None:
        table = schema.agent_conversations
        statement = select(table).where(
            table.c.workspace_id == workspace_id,
            table.c.id == conversation_id,
        )
        if for_update:
            # SELECT ... FOR UPDATE: on SQLite the dialect elides the lock and the
            # serialised write is the conditional counter update in ``append``.
            statement = statement.with_for_update()
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else _conversation_from_row(row)

    @override
    async def list_for_agent(
        self,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> list[AgentConversation]:
        table = schema.agent_conversations
        rows = (
            await self._session.execute(
                select(table)
                .where(
                    table.c.workspace_id == workspace_id,
                    table.c.project_id == project_id,
                    table.c.graph_id == graph_id,
                    table.c.agent_id == agent_id,
                )
                .order_by(table.c.created_at.desc(), table.c.id.asc())
            )
        ).mappings().all()
        return [_conversation_from_row(row) for row in rows]

    @override
    async def append(self, event: AgentConversationEvent) -> None:
        conversations = schema.agent_conversations
        claimed = await self._session.execute(
            update(conversations)
            .where(
                conversations.c.workspace_id == event.workspace_id,
                conversations.c.id == event.conversation_id,
                conversations.c.next_sequence == event.sequence,
            )
            .values(
                next_sequence=event.sequence + 1, updated_at=event.created_at
            )
        )
        if claimed.rowcount != 1:
            stored = await self.get(event.workspace_id, event.conversation_id)
            if stored is None:
                raise AgentConversationAppendError(
                    f"Agent conversation does not exist: {event.conversation_id}"
                )
            raise AgentConversationAppendError(
                f"Agent conversation {event.conversation_id} is at sequence "
                f"{stored.next_sequence}, not {event.sequence}"
            )
        events = schema.agent_conversation_events
        try:
            await self._session.execute(
                insert(events).values(
                    workspace_id=event.workspace_id,
                    conversation_id=event.conversation_id,
                    sequence=event.sequence,
                    turn_id=event.turn_id,
                    kind=event.payload.kind,
                    payload=event_payload_to_storage(event.payload),
                    created_at=event.created_at,
                )
            )
        except IntegrityError as exc:
            raise ConcurrentWriteError(
                f"Agent conversation event already stored: "
                f"{event.conversation_id}/{event.sequence}"
            ) from exc

    @override
    async def list_events(
        self,
        workspace_id: UUID,
        conversation_id: UUID,
        *,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[AgentConversationEvent]:
        events = schema.agent_conversation_events
        statement = (
            select(events)
            .where(
                events.c.workspace_id == workspace_id,
                events.c.conversation_id == conversation_id,
                events.c.sequence > after_sequence,
            )
            .order_by(events.c.sequence.asc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        rows = (await self._session.execute(statement)).mappings().all()
        return [_event_from_row(row) for row in rows]
