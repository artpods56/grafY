"""The application's way into Agent history (ADR 0021, issue #202).

This is the only writer of conversation rows. It keeps three properties that a caller
must not have to remember:

* **One transaction per operation, sequence decided from stored state.** `append` reads
  the stored conversation under a lock and writes the event at the sequence that row is
  waiting for, so two turns racing on one conversation cannot both extend it — the loser
  gets `AgentConversationAppendError` and the winner's history stands.
* **A fork copies, it does not trim.** `fork` reads the first ``n`` events of the source
  and writes them, in order and with their own stamps, into a new conversation that
  records the source and the sequence it stopped at. The source keeps going untouched.
* **History outlives the canvas.** Only `start` checks that the Agent is on the Graph. An
  append does not: an Agent removed or renamed mid-turn must still be able to record the
  message it was writing, and that event stays readable in the conversation it belongs
  to.

Reading is deliberately unauthenticated here. Anyone with `view_project` may read a
conversation and anyone with `start_run` may send, so the route above decides which of
those a caller is holding and passes the check down as the right to call this at all.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from grafy_core.domain.agent_conversations import (
    AgentConversation,
    AgentConversationEvent,
    AgentConversationEventPayload,
)
from grafy_core.domain.collaboration import ProjectHead
from grafy_core.domain.errors import NotFoundError
from grafy_core.kernel.project import ProjectDocumentError
from grafy_core.ports.agent_conversations import AgentConversationUnitOfWorkPort


class AgentConversationService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], AgentConversationUnitOfWorkPort],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def start(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
        author_user_id: UUID,
        title: str = "",
        conversation_id: UUID | None = None,
    ) -> AgentConversation:
        """Open a new thread with one Agent that is on the canvas right now."""

        async with self._unit_of_work_factory() as unit_of_work:
            head = await self._head(unit_of_work, workspace_id, project_id)
            _agent_on_graph(head, graph_id, agent_id)
            conversation = AgentConversation.new(
                workspace_id=workspace_id,
                project_id=project_id,
                graph_id=graph_id,
                agent_id=agent_id,
                author_user_id=author_user_id,
                title=title,
                conversation_id=conversation_id,
            )
            await unit_of_work.agent_conversations.add(conversation)
            await unit_of_work.commit()
        return conversation

    async def fork(
        self,
        *,
        workspace_id: UUID,
        conversation_id: UUID,
        at_sequence: int,
        author_user_id: UUID,
        title: str | None = None,
        fork_id: UUID | None = None,
    ) -> AgentConversation:
        """Continue a conversation from one of its events, in a new conversation.

        The copy is sequential in one transaction: the source row is locked so the range
        being copied cannot grow underneath it. Copied events keep the stamps they were
        written with — the fork's history ends where the source's did, which is also what
        the new conversation's `updated_at` says — and a reader who wants to know where a
        thread came from asks the fork, which recorded it.
        """

        async with self._unit_of_work_factory() as unit_of_work:
            store = unit_of_work.agent_conversations
            source = await store.lock(workspace_id, conversation_id)
            if source is None:
                raise NotFoundError("Agent conversation", str(conversation_id))
            fork = source.fork(
                at_sequence=at_sequence,
                author_user_id=author_user_id,
                title=title,
                conversation_id=fork_id or uuid4(),
            )
            await store.add(fork)
            copied = await store.list_events(
                workspace_id, source.id, after_sequence=0, limit=at_sequence
            )
            for index, event in enumerate(copied, start=1):
                await store.append(
                    AgentConversationEvent(
                        workspace_id=event.workspace_id,
                        conversation_id=fork.id,
                        sequence=index,
                        turn_id=event.turn_id,
                        payload=event.payload,
                        created_at=event.created_at,
                    )
                )
                fork = fork.appended(at=event.created_at)
            await unit_of_work.commit()
        return fork

    async def append(
        self,
        *,
        workspace_id: UUID,
        conversation_id: UUID,
        turn_id: UUID,
        payload: AgentConversationEventPayload,
        at: datetime | None = None,
    ) -> AgentConversationEvent:
        """Extend one conversation by one event, at the sequence it is waiting for."""

        async with self._unit_of_work_factory() as unit_of_work:
            store = unit_of_work.agent_conversations
            conversation = await store.lock(workspace_id, conversation_id)
            if conversation is None:
                raise NotFoundError("Agent conversation", str(conversation_id))
            event = conversation.event(
                turn_id=turn_id, payload=payload, at=at or datetime.now(UTC)
            )
            await store.append(event)
            await unit_of_work.commit()
        return event

    async def get(
        self, *, workspace_id: UUID, conversation_id: UUID
    ) -> AgentConversation:
        async with self._unit_of_work_factory() as unit_of_work:
            conversation = await unit_of_work.agent_conversations.get(
                workspace_id, conversation_id
            )
        if conversation is None:
            raise NotFoundError("Agent conversation", str(conversation_id))
        return conversation

    async def list_for_agent(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        graph_id: str,
        agent_id: str,
    ) -> list[AgentConversation]:
        """Every thread with one Agent, newest first — whoever started them."""

        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.agent_conversations.list_for_agent(
                workspace_id, project_id, graph_id, agent_id
            )

    async def read_events(
        self,
        *,
        workspace_id: UUID,
        conversation_id: UUID,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[AgentConversationEvent]:
        """Events in order, after a sequence. `after_sequence` is what a resuming
        reader sends so it is not shown what it already has.

        A conversation that is not there is named rather than answered with an empty list:
        to a reader those two would be the same reply, and one of them means its thread id
        is wrong.
        """

        async with self._unit_of_work_factory() as unit_of_work:
            store = unit_of_work.agent_conversations
            if await store.get(workspace_id, conversation_id) is None:
                raise NotFoundError("Agent conversation", str(conversation_id))
            return await store.list_events(
                workspace_id,
                conversation_id,
                after_sequence=after_sequence,
                limit=limit,
            )

    @staticmethod
    async def _head(
        unit_of_work: AgentConversationUnitOfWorkPort,
        workspace_id: UUID,
        project_id: UUID,
    ) -> ProjectHead:
        head = await unit_of_work.collaboration.get_head(workspace_id, project_id)
        if head is None:
            raise NotFoundError("Project", str(project_id))
        return head


def _agent_on_graph(head: ProjectHead, graph_id: str, agent_id: str) -> None:
    try:
        graph = head.document.get_graph(graph_id)
    except ProjectDocumentError as exc:
        raise NotFoundError("Graph", graph_id) from exc
    if not any(agent.id == agent_id for agent in graph.document.agents):
        raise NotFoundError("Agent", agent_id)


__all__ = ["AgentConversationService"]
