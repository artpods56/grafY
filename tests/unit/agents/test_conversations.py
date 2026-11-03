"""Agent conversation domain rules and the in-memory adapter (ADR 0021, issue #202).

The in-memory adapter is checked against the same promises the SQL adapter has to keep,
so a green run here means the rules are rules and not one adapter's habits: an append
takes the sequence the conversation is waiting for, nothing edits an event, and a fork
records where it was cut.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from grafy_core.domain.agent_conversations import (
    MAX_AGENT_MESSAGE_CHARS,
    AgentConversation,
    AgentConversationEvent,
    AgentConversationTurnOutcome,
    AssistantMessagePayload,
    TurnOutcomePayload,
    UserMessagePayload,
)
from grafy_core.ports.agent_conversations import AgentConversationAppendError
from grafy_core.runtime.in_memory import InMemoryDataStore, InMemoryUnitOfWork

WORKSPACE = UUID(int=401)
PROJECT = UUID(int=402)
AUTHOR = UUID(int=403)
OTHER_AUTHOR = UUID(int=404)
OTHER_WORKSPACE = UUID(int=405)
TURN = UUID(int=406)
BASE_TIME = datetime(2026, 7, 16, 8, 0, tzinfo=UTC)


def conversation(**overrides: object) -> AgentConversation:
    values: dict[str, object] = {
        "workspace_id": WORKSPACE,
        "project_id": PROJECT,
        "graph_id": "main",
        "agent_id": "research",
        "author_user_id": AUTHOR,
        "at": BASE_TIME,
    }
    values.update(overrides)
    return AgentConversation.new(**values)


@pytest.mark.asyncio
async def test_append_takes_the_sequence_the_conversation_is_waiting_for() -> None:
    store = InMemoryDataStore()
    thread = conversation()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.agent_conversations.add(thread)
        first = await unit_of_work.agent_conversations.append(
            thread.event(turn_id=TURN, payload=UserMessagePayload(text="ask"))
        )
        assert first is None
        stored = await unit_of_work.agent_conversations.get(WORKSPACE, thread.id)
        assert stored is not None
        second = stored.event(
            turn_id=TURN, payload=AssistantMessagePayload(text="answer")
        )
        await unit_of_work.agent_conversations.append(second)
        await unit_of_work.commit()

    async with InMemoryUnitOfWork(store) as unit_of_work:
        stored = await unit_of_work.agent_conversations.get(WORKSPACE, thread.id)
        events = await unit_of_work.agent_conversations.list_events(WORKSPACE, thread.id)

    assert stored is not None
    assert stored.next_sequence == 3
    assert stored.updated_at == events[-1].created_at
    assert [event.sequence for event in events] == [1, 2]
    assert events[0].payload == UserMessagePayload(text="ask")
    assert events[1].payload == AssistantMessagePayload(text="answer")


@pytest.mark.asyncio
async def test_an_append_at_a_sequence_that_has_been_taken_is_refused() -> None:
    """Two turns that read the same conversation cannot both extend it."""

    store = InMemoryDataStore()
    thread = conversation()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.agent_conversations.add(thread)
        await unit_of_work.commit()

    stale = thread
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.agent_conversations.append(
            stale.event(turn_id=TURN, payload=UserMessagePayload(text="winner"))
        )
        await unit_of_work.commit()

    async with InMemoryUnitOfWork(store) as unit_of_work:
        with pytest.raises(AgentConversationAppendError):
            await unit_of_work.agent_conversations.append(
                stale.event(turn_id=uuid4(), payload=UserMessagePayload(text="loser"))
            )

    async with InMemoryUnitOfWork(store) as unit_of_work:
        events = await unit_of_work.agent_conversations.list_events(WORKSPACE, thread.id)
        stored = await unit_of_work.agent_conversations.get(WORKSPACE, thread.id)

    assert [event.payload.text for event in events] == ["winner"]  # type: ignore[attr-defined]
    assert stored is not None and stored.next_sequence == 2


@pytest.mark.asyncio
async def test_an_event_written_once_is_never_rewritten() -> None:
    """Frozen values, and no adapter path that takes an event and changes it.

    The port has no update method and the model refuses assignment, so "events are never
    edited" holds at the type as well as at the adapter.
    """

    store = InMemoryDataStore()
    thread = conversation()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.agent_conversations.add(thread)
        event = thread.event(turn_id=TURN, payload=UserMessagePayload(text="original"))
        await unit_of_work.agent_conversations.append(event)
        await unit_of_work.commit()

    with pytest.raises(ValidationError):
        event.payload = AssistantMessagePayload(text="edited")  # type: ignore[misc]

    async with InMemoryUnitOfWork(store) as unit_of_work:
        stored = await unit_of_work.agent_conversations.list_events(WORKSPACE, thread.id)
    assert stored[0].payload == UserMessagePayload(text="original")


@pytest.mark.asyncio
async def test_reads_are_scoped_to_the_workspace_that_wrote_them() -> None:
    store = InMemoryDataStore()
    thread = conversation()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.agent_conversations.add(thread)
        await unit_of_work.commit()

    async with InMemoryUnitOfWork(store) as unit_of_work:
        assert await unit_of_work.agent_conversations.get(OTHER_WORKSPACE, thread.id) is None
        assert (
            await unit_of_work.agent_conversations.list_for_agent(
                OTHER_WORKSPACE, PROJECT, "main", "research"
            )
            == []
        )
        assert (
            await unit_of_work.agent_conversations.list_events(
                OTHER_WORKSPACE, thread.id
            )
            == []
        )


@pytest.mark.asyncio
async def test_threads_of_one_agent_are_listed_newest_first_and_keep_their_authors() -> None:
    store = InMemoryDataStore()
    older = conversation(at=BASE_TIME)
    newer = conversation(at=BASE_TIME.replace(hour=9))
    other_agent = conversation(agent_id="other", at=BASE_TIME)
    async with InMemoryUnitOfWork(store) as unit_of_work:
        for thread in (older, newer, other_agent):
            await unit_of_work.agent_conversations.add(thread)
        await unit_of_work.commit()

    async with InMemoryUnitOfWork(store) as unit_of_work:
        listed = await unit_of_work.agent_conversations.list_for_agent(
            WORKSPACE, PROJECT, "main", "research"
        )
        assert listed is not None

    assert [thread.id for thread in listed] == [newer.id, older.id]
    assert {thread.author_user_id for thread in listed} == {AUTHOR}


@pytest.mark.asyncio
async def test_events_are_read_in_order_after_a_sequence_and_up_to_a_limit() -> None:
    store = InMemoryDataStore()
    thread = conversation()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.agent_conversations.add(thread)
        current = thread
        for text in ("one", "two", "three"):
            await unit_of_work.agent_conversations.append(
                current.event(turn_id=TURN, payload=UserMessagePayload(text=text))
            )
            current = current.appended(at=current.updated_at)
        await unit_of_work.commit()

    async with InMemoryUnitOfWork(store) as unit_of_work:
        tail = await unit_of_work.agent_conversations.list_events(
            WORKSPACE, thread.id, after_sequence=1
        )
        one = await unit_of_work.agent_conversations.list_events(
            WORKSPACE, thread.id, after_sequence=1, limit=1
        )
        assert tail is not None

    assert [event.sequence for event in tail] == [2, 3]
    assert [event.sequence for event in one] == [2]


def test_a_fork_records_the_conversation_and_sequence_it_was_cut_at() -> None:
    source = conversation()
    for _ in range(4):
        source = source.appended(at=BASE_TIME)
    fork = source.fork(at_sequence=4, author_user_id=OTHER_AUTHOR)

    assert fork.id != source.id
    assert fork.source_conversation_id == source.id
    assert fork.source_sequence == 4
    assert fork.next_sequence == 1
    assert fork.is_fork
    assert not source.is_fork
    # A continuation stays in the same place with the same Agent, and its own author.
    assert (fork.project_id, fork.graph_id, fork.agent_id) == (
        source.project_id,
        source.graph_id,
        source.agent_id,
    )
    assert fork.author_user_id == OTHER_AUTHOR


@pytest.mark.parametrize("at_sequence", [0, 5])
def test_only_a_sequence_the_source_holds_can_be_forked(at_sequence: int) -> None:
    source = conversation().appended(at=BASE_TIME).appended(at=BASE_TIME)
    assert source.last_sequence == 2

    with pytest.raises(ValueError, match="holds 2 event"):
        source.fork(at_sequence=at_sequence, author_user_id=AUTHOR)


def test_a_fork_that_names_a_source_but_no_sequence_is_not_a_fork() -> None:
    stored = conversation().model_dump()
    stored["source_conversation_id"] = uuid4()
    with pytest.raises(ValidationError, match="source and its source sequence"):
        AgentConversation.model_validate(stored)


def test_event_payloads_are_a_closed_vocabulary_with_a_bound_on_length() -> None:
    assert UserMessagePayload(text="x").kind == "user_message"
    assert AgentConversationTurnOutcome.INTERRUPTED == "interrupted"
    assert TurnOutcomePayload(outcome=AgentConversationTurnOutcome.CANCELLED).detail is None
    with pytest.raises(ValidationError):
        UserMessagePayload(text="")
    with pytest.raises(ValidationError):
        UserMessagePayload(text="x" * (MAX_AGENT_MESSAGE_CHARS + 1))
    with pytest.raises(ValidationError):
        AgentConversationEvent.model_validate(
            {
                "workspace_id": WORKSPACE,
                "conversation_id": uuid4(),
                "sequence": 0,
                "turn_id": TURN,
                "payload": {"kind": "system_prompt", "text": "not a Grafy event"},
                "created_at": BASE_TIME,
            }
        )


@pytest.mark.asyncio
async def test_a_rolled_back_append_leaves_no_event_and_no_moved_sequence() -> None:
    store = InMemoryDataStore()
    thread = conversation()
    async with InMemoryUnitOfWork(store) as unit_of_work:
        await unit_of_work.agent_conversations.add(thread)
        await unit_of_work.commit()

    with pytest.raises(RuntimeError, match="failed after it appended"):
        async with InMemoryUnitOfWork(store) as unit_of_work:
            await unit_of_work.agent_conversations.append(
                thread.event(turn_id=TURN, payload=UserMessagePayload(text="aborted"))
            )
            raise RuntimeError("the turn failed after it appended")

    async with InMemoryUnitOfWork(store) as unit_of_work:
        events = await unit_of_work.agent_conversations.list_events(WORKSPACE, thread.id)
        stored = await unit_of_work.agent_conversations.get(WORKSPACE, thread.id)

    assert events == []
    assert stored is not None and stored.next_sequence == 1


def test_a_stored_timestamp_without_a_zone_is_refused() -> None:
    stored = conversation().model_dump()
    stored["created_at"] = datetime(2026, 7, 16, 8, 0)  # naive
    with pytest.raises(ValidationError, match="timezone-aware"):
        AgentConversation.model_validate(stored)
