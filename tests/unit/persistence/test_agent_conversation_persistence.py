"""Agent conversation persistence (ADR 0021, issue #202).

Runs on the shared ``database`` fixture: every test executes against SQLite and, when
``GRAFY_TEST_POSTGRES_URL`` names an empty disposable database, against PostgreSQL in a
per-test schema. That matters here more than it does elsewhere in this directory: the
append's serialisation point is a conditional ``UPDATE`` of the conversation's sequence,
and only PostgreSQL can show that two appends do not both land.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete

from grafy_api.agents.conversations import AgentConversationService
from grafy_core.domain.agent_conversations import (
    AgentConversation,
    AgentConversationTurnOutcome,
    AssistantMessagePayload,
    TurnOutcomePayload,
    UserMessagePayload,
)
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.projects import Project
from grafy_core.ports.agent_conversations import AgentConversationAppendError
from grafy_persistence import schema
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.support.persistence import WORKSPACE_ONE, WORKSPACE_TWO
from tests.support.persistence import database as _base_database_fixture

base_database = _base_database_fixture

GRAPH_ID = "main"
AGENT_ID = "research"
AUTHOR = UUID("00000000-0000-0000-0000-0000000000d1")
TURN = UUID("00000000-0000-0000-0000-0000000000d2")
T1 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


@pytest.fixture
async def database(base_database: Database) -> AsyncIterator[Database]:
    """The shared SQLite/PostgreSQL fixture, under the name these tests read."""

    yield base_database


def project(workspace_id: UUID = WORKSPACE_ONE) -> Project:
    return Project(workspace_id=workspace_id, name="Agents")


async def add_project(database: Database, row: Project) -> Project:
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.projects.add(row)
        await unit_of_work.commit()
    return row


async def add_conversation(
    database: Database, row: AgentConversation
) -> AgentConversation:
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.agent_conversations.add(row)
        await unit_of_work.commit()
    return row


def thread(row: Project, **overrides: object) -> AgentConversation:
    values: dict[str, object] = {
        "workspace_id": row.workspace_id,
        "project_id": row.id,
        "graph_id": GRAPH_ID,
        "agent_id": AGENT_ID,
        "author_user_id": AUTHOR,
        "title": "Sources on the 1667 flood",
        "at": T1,
    }
    values.update(overrides)
    return AgentConversation.new(**values)


@pytest.mark.asyncio
async def test_a_thread_and_every_kind_of_event_round_trip(database: Database) -> None:
    row = await add_project(database, project())
    stored = await add_conversation(database, thread(row))

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        store = unit_of_work.agent_conversations
        current = stored
        for payload in (
            UserMessagePayload(text="what did the ledger say?"),
            AssistantMessagePayload(text="it said: two lastings."),
            TurnOutcomePayload(outcome=AgentConversationTurnOutcome.COMPLETED),
        ):
            await store.append(current.event(turn_id=TURN, payload=payload))
            current = current.appended(at=T1 + timedelta(minutes=1))
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        read = await unit_of_work.agent_conversations.get(WORKSPACE_ONE, stored.id)
        events = await unit_of_work.agent_conversations.list_events(
            WORKSPACE_ONE, stored.id
        )

    assert read is not None
    assert read.title == "Sources on the 1667 flood"
    assert read.next_sequence == 4
    assert read.created_at == T1
    assert [event.sequence for event in events] == [1, 2, 3]
    assert [event.payload.kind for event in events] == [
        "user_message",
        "assistant_message",
        "turn_outcome",
    ]
    assert events[0].payload == UserMessagePayload(text="what did the ledger say?")
    assert events[2].payload == TurnOutcomePayload(
        outcome=AgentConversationTurnOutcome.COMPLETED
    )
    assert all(event.turn_id == TURN for event in events)
    assert all(event.created_at.tzinfo is not None for event in events)


@pytest.mark.asyncio
async def test_a_fork_is_recorded_as_a_fork_and_survives_reread(
    database: Database,
) -> None:
    row = await add_project(database, project())
    source = await add_conversation(database, thread(row))
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.agent_conversations.append(
            source.event(turn_id=TURN, payload=UserMessagePayload(text="first"))
        )
        await unit_of_work.commit()

    forked = AgentConversation.new(
        workspace_id=WORKSPACE_ONE,
        project_id=row.id,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
        author_user_id=AUTHOR,
        at=T1,
    ).model_copy(
        update={
            "source_conversation_id": source.id,
            "source_sequence": 1,
            "next_sequence": 2,
        }
    )
    await add_conversation(database, forked)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        read = await unit_of_work.agent_conversations.get(WORKSPACE_ONE, forked.id)
        listed = await unit_of_work.agent_conversations.list_for_agent(
            WORKSPACE_ONE, row.id, GRAPH_ID, AGENT_ID
        )

    assert read is not None
    assert read.source_conversation_id == source.id
    assert read.source_sequence == 1
    assert {item.id for item in listed} == {source.id, forked.id}


@pytest.mark.asyncio
async def test_an_append_after_the_stored_sequence_is_refused_and_leaves_nothing_behind(
    database: Database,
) -> None:
    row = await add_project(database, project())
    stored = await add_conversation(database, thread(row))
    stale = stored

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.agent_conversations.append(
            stale.event(turn_id=TURN, payload=UserMessagePayload(text="first"))
        )
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        with pytest.raises(AgentConversationAppendError, match="at sequence 2, not 1"):
            await unit_of_work.agent_conversations.append(
                stale.event(turn_id=uuid4(), payload=UserMessagePayload(text="dupe"))
            )
        await unit_of_work.rollback()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        read = await unit_of_work.agent_conversations.get(WORKSPACE_ONE, stored.id)
        events = await unit_of_work.agent_conversations.list_events(
            WORKSPACE_ONE, stored.id
        )

    assert read is not None and read.next_sequence == 2
    assert [event.sequence for event in events] == [1]


@pytest.mark.asyncio
async def test_an_append_to_a_conversation_that_is_not_there_is_refused(
    database: Database,
) -> None:
    stored = thread(await add_project(database, project()))

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        with pytest.raises(AgentConversationAppendError, match="does not exist"):
            await unit_of_work.agent_conversations.append(
                stored.event(turn_id=TURN, payload=UserMessagePayload(text="orphan"))
            )


@pytest.mark.asyncio
async def test_events_are_read_after_a_sequence_and_up_to_a_limit(
    database: Database,
) -> None:
    row = await add_project(database, project())
    stored = await add_conversation(database, thread(row))
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        current = stored
        for text in ("one", "two", "three"):
            await unit_of_work.agent_conversations.append(
                current.event(turn_id=TURN, payload=UserMessagePayload(text=text))
            )
            current = current.appended(at=T1)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        tail = await unit_of_work.agent_conversations.list_events(
            WORKSPACE_ONE, stored.id, after_sequence=1
        )
        page = await unit_of_work.agent_conversations.list_events(
            WORKSPACE_ONE, stored.id, limit=2
        )

    assert [event.sequence for event in tail] == [2, 3]
    assert [event.sequence for event in page] == [1, 2]


@pytest.mark.asyncio
async def test_a_thread_is_scoped_to_its_workspace_and_project(
    database: Database,
) -> None:
    row = await add_project(database, project())
    stored = await add_conversation(database, thread(row))

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.agent_conversations.get(WORKSPACE_TWO, stored.id) is None
        assert (
            await unit_of_work.agent_conversations.list_for_agent(
                WORKSPACE_TWO, row.id, GRAPH_ID, AGENT_ID
            )
            == []
        )
        assert (
            await unit_of_work.agent_conversations.list_events(WORKSPACE_TWO, stored.id)
            == []
        )


@pytest.mark.asyncio
async def test_deleting_the_project_takes_threads_and_events_with_it(
    database: Database,
) -> None:
    row = await add_project(database, project())
    stored = await add_conversation(database, thread(row))
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.agent_conversations.append(
            stored.event(turn_id=TURN, payload=UserMessagePayload(text="one"))
        )
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        loaded = await unit_of_work.projects.get(row.workspace_id, row.id)
        assert loaded is not None
        await unit_of_work.projects.remove(row.workspace_id, loaded)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.agent_conversations.get(WORKSPACE_ONE, stored.id) is None
        assert (
            await unit_of_work.agent_conversations.list_events(WORKSPACE_ONE, stored.id)
            == []
        )


@pytest.mark.asyncio
async def test_forking_copies_the_range_in_order_through_sql(
    database: Database,
) -> None:
    """The service's fork against the SQL adapter: one transaction, copied history."""

    row = await add_project(database, project())
    source = await add_conversation(database, thread(row))
    service = AgentConversationService(
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions)
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        current = source
        for text in ("one", "two", "three"):
            await unit_of_work.agent_conversations.append(
                current.event(turn_id=TURN, payload=UserMessagePayload(text=text))
            )
            current = current.appended(at=T1)
        await unit_of_work.commit()

    fork = await service.fork(
        workspace_id=WORKSPACE_ONE,
        conversation_id=source.id,
        at_sequence=2,
        author_user_id=AUTHOR,
    )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        copied = await unit_of_work.agent_conversations.list_events(
            WORKSPACE_ONE, fork.id
        )
        untouched = await unit_of_work.agent_conversations.list_events(
            WORKSPACE_ONE, source.id
        )
        listed = await unit_of_work.agent_conversations.list_for_agent(
            WORKSPACE_ONE, row.id, GRAPH_ID, AGENT_ID
        )

    assert [event.payload.text for event in copied] == ["one", "two"]  # type: ignore[attr-defined]
    assert [event.sequence for event in copied] == [1, 2]
    assert [event.payload.text for event in untouched] == [  # type: ignore[attr-defined]
        "one",
        "two",
        "three",
    ]
    assert fork.source_conversation_id == source.id
    assert fork.source_sequence == 2
    assert {item.id for item in listed} == {source.id, fork.id}


@pytest.mark.asyncio
async def test_a_thread_still_has_the_agent_it_began_with_until_its_project_goes(
    database: Database,
) -> None:
    """Removing a source out from under a fork takes the fork with it.

    The alternative is a conversation whose beginning is a row that is not there, so the
    schema refuses to keep the copy rather than keep an unexplainable one.
    """

    row = await add_project(database, project())
    source = await add_conversation(database, thread(row))
    service = AgentConversationService(
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions)
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.agent_conversations.append(
            source.event(turn_id=TURN, payload=UserMessagePayload(text="one"))
        )
        await unit_of_work.commit()
    fork = await service.fork(
        workspace_id=WORKSPACE_ONE,
        conversation_id=source.id,
        at_sequence=1,
        author_user_id=AUTHOR,
    )

    async with database.sessions() as session:
        await session.execute(
            delete(schema.agent_conversations).where(
                schema.agent_conversations.c.id == source.id
            )
        )
        await session.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.agent_conversations.get(WORKSPACE_ONE, fork.id) is None
        assert (
            await unit_of_work.agent_conversations.list_events(WORKSPACE_ONE, fork.id)
            == []
        )


@pytest.mark.asyncio
async def test_the_service_names_a_conversation_that_was_never_there(
    database: Database,
) -> None:
    service = AgentConversationService(
        unit_of_work_factory=lambda: SqlAlchemyUnitOfWork(database.sessions)
    )

    with pytest.raises(NotFoundError, match="Agent conversation not found"):
        await service.get(workspace_id=WORKSPACE_ONE, conversation_id=uuid4())
