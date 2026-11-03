"""The conversation owner over the in-memory adapters (ADR 0021, issue #202).

These are the rules a caller of the next unit (the AgentService turn loop) is entitled to
rely on without reading an adapter: what may start a thread, what an append does to the
sequence, what a fork leaves behind, and what happens to history when the Agent it belongs
to is taken off the canvas.
"""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from grafy_api.agents.conversations import AgentConversationService
from grafy_core.domain.agent_conversations import (
    AgentConversationTurnOutcome,
    AssistantMessagePayload,
    TurnOutcomePayload,
    UserMessagePayload,
)
from grafy_core.domain.collaboration import (
    ProjectHead,
    RemoveAgentCommand,
    apply_graph_command,
)
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.graph_documents import GraphAgent, GraphDocument
from grafy_core.kernel.project import GraphDefinition, ProjectDocument
from grafy_core.runtime.in_memory import InMemoryDataStore, InMemoryUnitOfWork

WORKSPACE = UUID(int=701)
PROJECT = UUID(int=702)
EPOCH = UUID(int=703)
AUTHOR = UUID(int=704)
OTHER_AUTHOR = UUID(int=705)
GRAPH_ID = "main"
AGENT_ID = "research"
T1 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def head_with_agents(*agent_ids: str) -> ProjectHead:
    return ProjectHead(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        room_epoch=EPOCH,
        collaboration_sequence=3,
        checkpoint_sequence=0,
        checkpoint_revision=1,
        name="Agents",
        document=ProjectDocument(
            graphs=(
                GraphDefinition(
                    id=GRAPH_ID,
                    name="Main",
                    document=GraphDocument(
                        agents=tuple(
                            GraphAgent(id=agent_id, name=agent_id.title())
                            for agent_id in agent_ids
                        )
                    ),
                ),
            )
        ),
    )


async def store_with(head: ProjectHead) -> InMemoryDataStore:
    store = InMemoryDataStore()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.collaboration.add_head(head)
        await unit_of_work.commit()
    return store


def service(store: InMemoryDataStore) -> AgentConversationService:
    return AgentConversationService(
        unit_of_work_factory=lambda: InMemoryUnitOfWork(store)
    )


async def run_one_turn(
    service: AgentConversationService, conversation_id: UUID, turn_id: UUID, text: str
) -> None:
    """What the next unit will do for one turn, minus the model."""

    await service.append(
        workspace_id=WORKSPACE,
        conversation_id=conversation_id,
        turn_id=turn_id,
        payload=UserMessagePayload(text=text),
    )
    await service.append(
        workspace_id=WORKSPACE,
        conversation_id=conversation_id,
        turn_id=turn_id,
        payload=AssistantMessagePayload(text="the ledger says two lastings"),
    )
    await service.append(
        workspace_id=WORKSPACE,
        conversation_id=conversation_id,
        turn_id=turn_id,
        payload=TurnOutcomePayload(outcome=AgentConversationTurnOutcome.COMPLETED),
    )


async def test_a_thread_starts_on_an_agent_that_is_on_the_canvas() -> None:
    store = await store_with(head_with_agents(AGENT_ID, "other"))
    owner = service(store)

    thread = await owner.start(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
        author_user_id=AUTHOR,
        title="1667 flood",
    )
    listed = await owner.list_for_agent(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
    )

    assert thread.author_user_id == AUTHOR
    assert thread.title == "1667 flood"
    assert thread.next_sequence == 1
    assert [item.id for item in listed] == [thread.id]

    with pytest.raises(NotFoundError, match="Agent not found"):
        await owner.start(
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            graph_id=GRAPH_ID,
            agent_id="not-placed",
            author_user_id=AUTHOR,
        )
    with pytest.raises(NotFoundError, match="Graph not found"):
        await owner.start(
            workspace_id=WORKSPACE,
            project_id=PROJECT,
            graph_id="second-graph",
            agent_id=AGENT_ID,
            author_user_id=AUTHOR,
        )
    with pytest.raises(NotFoundError, match="Project not found"):
        await owner.start(
            workspace_id=WORKSPACE,
            project_id=uuid4(),
            graph_id=GRAPH_ID,
            agent_id=AGENT_ID,
            author_user_id=AUTHOR,
        )


async def test_one_turn_writes_its_events_in_order_under_its_turn_id() -> None:
    store = await store_with(head_with_agents(AGENT_ID))
    owner = service(store)
    thread = await owner.start(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
        author_user_id=AUTHOR,
    )
    turn = uuid4()

    await run_one_turn(owner, thread.id, turn, "what did the ledger say?")
    second_turn = uuid4()
    await run_one_turn(owner, thread.id, second_turn, "and the second entry?")

    events = await owner.read_events(workspace_id=WORKSPACE, conversation_id=thread.id)
    current = await owner.get(workspace_id=WORKSPACE, conversation_id=thread.id)

    assert [event.sequence for event in events] == [1, 2, 3, 4, 5, 6]
    assert [event.turn_id for event in events] == [turn] * 3 + [second_turn] * 3
    assert [event.payload.kind for event in events] == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ] * 2
    assert current.next_sequence == 7


async def test_history_outlives_the_agent_it_began_with() -> None:
    """A removed Agent still gets to finish recording the turn it was on.

    Removing an Agent is a canvas edit through the ordinary document command; the
    conversation is Project history. Refusing the append would throw away a reply that was
    already paid for, and would leave a turn with a question and no answer.
    """

    head = head_with_agents(AGENT_ID)
    store = await store_with(head)
    owner = service(store)
    thread = await owner.start(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
        author_user_id=AUTHOR,
    )

    graph = head.document.get_graph(GRAPH_ID)
    without_agent = apply_graph_command(
        document=graph.document, command=RemoveAgentCommand(agent_id=AGENT_ID)
    )
    assert without_agent.agents == ()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.collaboration.save_head(
            replace(
                head,
                collaboration_sequence=head.collaboration_sequence + 1,
                document=ProjectDocument(
                    graphs=(graph.model_copy(update={"document": without_agent}),)
                ),
            )
        )
        await unit_of_work.commit()

    turn = uuid4()
    await run_one_turn(owner, thread.id, turn, "ask")

    events = await owner.read_events(workspace_id=WORKSPACE, conversation_id=thread.id)
    assert [event.payload.kind for event in events] == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]


async def test_forking_continues_without_touching_the_source() -> None:
    store = await store_with(head_with_agents(AGENT_ID))
    owner = service(store)
    thread = await owner.start(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
        author_user_id=AUTHOR,
    )
    first_turn, second_turn = uuid4(), uuid4()
    await run_one_turn(owner, thread.id, first_turn, "first question")
    await run_one_turn(owner, thread.id, second_turn, "second question")

    fork = await owner.fork(
        workspace_id=WORKSPACE,
        conversation_id=thread.id,
        at_sequence=3,
        author_user_id=OTHER_AUTHOR,
    )
    await run_one_turn(owner, fork.id, uuid4(), "a different direction")

    copied = await owner.read_events(workspace_id=WORKSPACE, conversation_id=fork.id)
    source = await owner.read_events(workspace_id=WORKSPACE, conversation_id=thread.id)
    threads = await owner.list_for_agent(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
    )

    assert fork.source_conversation_id == thread.id
    assert fork.source_sequence == 3
    assert fork.author_user_id == OTHER_AUTHOR
    assert [event.sequence for event in copied] == [1, 2, 3, 4, 5, 6]
    assert copied[3].payload == UserMessagePayload(text="a different direction")
    assert [event.sequence for event in source] == list(range(1, 7))
    assert {item.id for item in threads} == {thread.id, fork.id}

    with pytest.raises(ValueError, match="holds 6 event"):
        await owner.fork(
            workspace_id=WORKSPACE,
            conversation_id=thread.id,
            at_sequence=7,
            author_user_id=OTHER_AUTHOR,
        )


async def test_a_resuming_reader_asks_for_what_it_does_not_have() -> None:
    store = await store_with(head_with_agents(AGENT_ID))
    owner = service(store)
    thread = await owner.start(
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
        author_user_id=AUTHOR,
    )
    await run_one_turn(owner, thread.id, uuid4(), "ask")

    tail = await owner.read_events(
        workspace_id=WORKSPACE, conversation_id=thread.id, after_sequence=2
    )
    page = await owner.read_events(
        workspace_id=WORKSPACE, conversation_id=thread.id, limit=1
    )

    assert [event.sequence for event in tail] == [3]
    assert [event.sequence for event in page] == [1]

    with pytest.raises(NotFoundError, match="Agent conversation not found"):
        await owner.read_events(workspace_id=WORKSPACE, conversation_id=uuid4())


async def test_an_append_the_conversation_cannot_see_is_refused_before_it_writes(
    ) -> None:
    store = await store_with(head_with_agents(AGENT_ID))
    owner = service(store)

    with pytest.raises(NotFoundError, match="Agent conversation not found"):
        await owner.append(
            workspace_id=WORKSPACE,
            conversation_id=uuid4(),
            turn_id=uuid4(),
            payload=UserMessagePayload(text="nowhere"),
        )
