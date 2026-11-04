"""Agent turn receipt persistence (ADR 0021, issue #202).

Runs on the shared ``database`` fixture: SQLite always, and PostgreSQL as well when
``GRAFY_TEST_POSTGRES_URL`` names an empty disposable database. The point of running these
here rather than only against the in-memory port is that the two admission rules are
*constraints*. A second running turn of one conversation is refused by the schema, in a
second transaction, over a connection that never saw the first. An application check would
pass here and lose in production, which is the difference these tests exist to make.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from grafy_core.domain.agent_conversations import AgentConversation
from grafy_core.domain.agent_turns import AgentTurn, AgentTurnStatus
from grafy_core.domain.projects import Project
from grafy_core.ports.agent_turns import (
    AgentTurnAlreadyAdmittedError,
    AgentTurnBusyError,
)
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.support.persistence import WORKSPACE_ONE, WORKSPACE_TWO
from tests.support.persistence import database as _base_database_fixture

base_database = _base_database_fixture

GRAPH_ID = "main"
AGENT_ID = "research"
USER = UUID("00000000-0000-0000-0000-0000000000d1")
T1 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)

# A receipt is a row under a conversation, which is a row under a project, so a test asks
# for a conversation and gets the scope that makes one exist. Naming bare UUIDs instead is
# how a foreign key ends up explaining the test to the reader.
CONVERSATION = uuid4()
OTHER_CONVERSATION = uuid4()
THIRD_CONVERSATION = uuid4()


@pytest.fixture
async def database(base_database: Database) -> AsyncIterator[Database]:
    """The shared SQLite/PostgreSQL fixture, under the name these tests read."""

    yield base_database


async def conversation(
    database: Database,
    conversation_id: UUID,
    *,
    workspace_id: UUID = WORKSPACE_ONE,
    project_id: UUID | None = None,
) -> UUID:
    """Make one conversation exist, and answer with the project row it belongs to."""

    scope = project_id or uuid4()
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        if await unit_of_work.projects.get(workspace_id, scope) is None:
            await unit_of_work.projects.add(
                Project(id=scope, workspace_id=workspace_id, name="Agents")
            )
        await unit_of_work.commit()
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        if (
            await unit_of_work.agent_conversations.get(workspace_id, conversation_id)
            is None
        ):
            await unit_of_work.agent_conversations.add(
                AgentConversation.new(
                    workspace_id=workspace_id,
                    project_id=scope,
                    graph_id=GRAPH_ID,
                    agent_id=AGENT_ID,
                    author_user_id=USER,
                    title="Sources on the 1667 flood",
                    at=T1,
                ).model_copy(update={"id": conversation_id})
            )
        await unit_of_work.commit()
    return scope


def receipt(
    project_id: UUID,
    *,
    conversation_id: UUID = CONVERSATION,
    workspace_id: UUID = WORKSPACE_ONE,
    client_turn_id: str = "client-1",
    text: str = "what did the ledger say?",
    turn_id: UUID | None = None,
    at: datetime = T1,
) -> AgentTurn:
    return AgentTurn.admit(
        workspace_id=workspace_id,
        project_id=project_id,
        graph_id=GRAPH_ID,
        agent_id=AGENT_ID,
        conversation_id=conversation_id,
        client_turn_id=client_turn_id,
        requested_by_user_id=USER,
        user_text=text,
        user_message_sequence=1,
        instructions="Answer from the sources.",
        model_source="deployment",
        model_name="llama-4",
        turn_id=turn_id,
        at=at,
    )


async def add(database: Database, *turns: AgentTurn) -> None:
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        for turn in turns:
            await unit_of_work.agent_turns.add(turn)
        await unit_of_work.commit()


async def finish(
    database: Database,
    turn: AgentTurn,
    *,
    status: AgentTurnStatus,
    at: datetime,
    detail: str | None = None,
) -> AgentTurn | None:
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        claimed = await unit_of_work.agent_turns.finish(
            turn.workspace_id, turn.id, status=status, at=at, detail=detail
        )
        await unit_of_work.commit()
    return claimed


async def test_a_receipt_round_trips_with_the_snapshot_it_was_accepted_with(
    database: Database,
) -> None:
    scope = await conversation(database, CONVERSATION)
    turn = receipt(scope, client_turn_id="client-9")
    await add(database, turn)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        stored = await unit_of_work.agent_turns.get(WORKSPACE_ONE, turn.id)

    assert stored == turn
    assert stored is not None
    assert stored.status is AgentTurnStatus.RUNNING
    assert stored.finished_at is None
    assert stored.instructions == "Answer from the sources."
    assert stored.model_source == "deployment" and stored.model_name == "llama-4"
    assert stored.user_message_sequence == 1
    # The digest is what a retry is compared against, so it has to survive the trip.
    assert stored.request_digest == turn.request_digest
    assert stored.created_at.tzinfo is not None


async def test_a_finished_receipt_keeps_the_text_of_its_own_ending(
    database: Database,
) -> None:
    scope = await conversation(database, CONVERSATION)
    turn = receipt(scope)
    await add(database, turn)

    finished = await finish(
        database,
        turn,
        status=AgentTurnStatus.FAILED,
        at=T1 + timedelta(minutes=1),
        detail="APITimeout: the gateway gave up",
    )

    assert finished is not None
    assert finished.status is AgentTurnStatus.FAILED
    assert finished.finished_at == T1 + timedelta(minutes=1)
    assert finished.outcome_detail == "APITimeout: the gateway gave up"
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        stored = await unit_of_work.agent_turns.get(WORKSPACE_ONE, turn.id)
    assert stored == finished


async def test_the_busy_rule_holds_in_a_transaction_that_never_saw_the_first_turn(
    database: Database,
) -> None:
    """The busy rule is a partial unique index, not a check the service remembers to do."""

    scope = await conversation(database, CONVERSATION)
    first = receipt(scope, client_turn_id="client-1")
    await add(database, first)

    following = receipt(
        scope,
        client_turn_id="client-2",
        turn_id=uuid4(),
        at=T1 + timedelta(seconds=1),
    )
    with pytest.raises(AgentTurnBusyError) as busy:
        await add(database, following)
    # The refusal names the conversation and not the winner's content: the service reads the
    # running turn itself when it wants to say who is ahead of this send.
    assert busy.value.running_turn_id is None

    # The refused admission left no row behind, which is what the service needs: a receipt
    # and its user message are one transaction, so a refused send cannot leave a question in
    # the thread with no turn ever answering it.
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        receipts = await unit_of_work.agent_turns.list_for_conversation(
            WORKSPACE_ONE, CONVERSATION
        )
    assert [item.id for item in receipts] == [first.id]


async def test_finishing_a_turn_frees_the_conversation_for_the_next_one(
    database: Database,
) -> None:
    scope = await conversation(database, CONVERSATION)
    turn = receipt(scope, client_turn_id="client-1")
    await add(database, turn)
    assert (
        await finish(
            database,
            turn,
            status=AgentTurnStatus.CANCELLED,
            at=T1 + timedelta(minutes=1),
            detail="the person reading stopped it",
        )
    ) is not None

    # The way out is the whole point of a *partial* index: once nothing runs, the next
    # question is admissible, and its receipt is a fresh row rather than the old one moved.
    next_turn = receipt(
        scope, client_turn_id="client-2", turn_id=uuid4(), at=T1 + timedelta(minutes=2)
    )
    await add(database, next_turn)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        store = unit_of_work.agent_turns
        assert (
            await store.running_for_conversation(WORKSPACE_ONE, CONVERSATION)
        ) == next_turn
        assert [
            item.id
            for item in await store.list_for_conversation(WORKSPACE_ONE, CONVERSATION)
        ] == [next_turn.id, turn.id]


async def test_the_same_client_turn_id_is_admitted_once_even_after_the_turn_ends(
    database: Database,
) -> None:
    """The client-id rule outlives the turn. The busy rule cannot catch a finished one."""

    scope = await conversation(database, CONVERSATION)
    turn = receipt(scope, client_turn_id="client-1")
    await add(database, turn)
    await finish(
        database, turn, status=AgentTurnStatus.COMPLETED, at=T1 + timedelta(minutes=1)
    )

    again = receipt(
        scope, client_turn_id="client-1", turn_id=uuid4(), at=T1 + timedelta(minutes=2)
    )
    with pytest.raises(AgentTurnAlreadyAdmittedError):
        await add(database, again)

    # A different conversation of the same Agent has never seen that client id, and the
    # lookup is scoped to the pair rather than to the id alone.
    other_scope = await conversation(database, OTHER_CONVERSATION)
    elsewhere = receipt(
        other_scope,
        conversation_id=OTHER_CONVERSATION,
        client_turn_id="client-1",
        at=T1 + timedelta(minutes=2),
    )
    await add(database, elsewhere)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        store = unit_of_work.agent_turns
        assert (
            await store.get_by_client_turn_id(
                WORKSPACE_ONE, OTHER_CONVERSATION, "client-1"
            )
        ) == elsewhere
        assert (
            await store.get_by_client_turn_id(WORKSPACE_ONE, CONVERSATION, "client-2")
        ) is None


async def test_a_receipt_is_not_readable_through_another_workspace(
    database: Database,
) -> None:
    scope = await conversation(database, CONVERSATION)
    turn = receipt(scope)
    await add(database, turn)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        store = unit_of_work.agent_turns
        assert await store.get(WORKSPACE_TWO, turn.id) is None
        assert (
            await store.get_by_client_turn_id(WORKSPACE_TWO, CONVERSATION, "client-1")
        ) is None
        assert await store.running_for_conversation(WORKSPACE_TWO, CONVERSATION) is None
        assert await store.list_for_conversation(WORKSPACE_TWO, CONVERSATION) == []
        # Recovery is the exception, and the only read without a Workspace in it.
        assert [item.id for item in await store.list_running()] == [turn.id]


async def test_the_terminal_state_is_claimed_once_and_the_first_account_stands(
    database: Database,
) -> None:
    scope = await conversation(database, CONVERSATION)
    turn = receipt(scope)
    await add(database, turn)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        claimed = await unit_of_work.agent_turns.finish(
            WORKSPACE_ONE,
            turn.id,
            status=AgentTurnStatus.CANCELLED,
            at=T1 + timedelta(minutes=1),
        )
        # Second attempt, same transaction: whoever else believed this turn was theirs to
        # end is told it already was, and the first account of how it ended is what stays.
        again = await unit_of_work.agent_turns.finish(
            WORKSPACE_ONE,
            turn.id,
            status=AgentTurnStatus.INTERRUPTED,
            at=T1 + timedelta(minutes=2),
            detail="the API owner restarted while this turn was running",
        )
        await unit_of_work.commit()

    assert claimed is not None and claimed.status is AgentTurnStatus.CANCELLED
    assert again is None
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        stored = await unit_of_work.agent_turns.get(WORKSPACE_ONE, turn.id)
    assert stored is not None
    assert stored.status is AgentTurnStatus.CANCELLED
    assert stored.outcome_detail is None


async def test_only_a_terminal_status_ends_a_turn(database: Database) -> None:
    scope = await conversation(database, CONVERSATION)
    turn = receipt(scope)
    await add(database, turn)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        with pytest.raises(ValueError, match="not a terminal"):
            await unit_of_work.agent_turns.finish(
                WORKSPACE_ONE,
                turn.id,
                status=AgentTurnStatus.RUNNING,
                at=T1 + timedelta(minutes=1),
            )
        await unit_of_work.rollback()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        stored = await unit_of_work.agent_turns.get(WORKSPACE_ONE, turn.id)
    assert stored is not None and stored.status is AgentTurnStatus.RUNNING


async def test_recovery_reads_running_turns_whatever_workspace_they_belong_to(
    database: Database,
) -> None:
    """``list_running`` is the startup read: it has no request, so it has no Workspace."""

    one_scope = await conversation(database, CONVERSATION)
    two_scope = await conversation(
        database, OTHER_CONVERSATION, workspace_id=WORKSPACE_TWO
    )
    three_scope = await conversation(database, THIRD_CONVERSATION)
    one = receipt(one_scope, client_turn_id="client-1")
    two = receipt(
        two_scope,
        workspace_id=WORKSPACE_TWO,
        conversation_id=OTHER_CONVERSATION,
        client_turn_id="client-1",
        at=T1 + timedelta(seconds=1),
    )
    finished_first = receipt(
        three_scope,
        conversation_id=THIRD_CONVERSATION,
        client_turn_id="client-1",
        at=T1 + timedelta(seconds=2),
    )
    await add(database, one, two, finished_first)
    await finish(
        database,
        finished_first,
        status=AgentTurnStatus.COMPLETED,
        at=T1 + timedelta(minutes=1),
    )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        running = await unit_of_work.agent_turns.list_running()
    assert [turn.id for turn in running] == [one.id, two.id]
    assert all(turn.status is AgentTurnStatus.RUNNING for turn in running)

    # Recovery is what empties it, and an empty read is the ordinary case after that.
    for turn in running:
        await finish(
            database,
            turn,
            status=AgentTurnStatus.INTERRUPTED,
            at=T1 + timedelta(minutes=2),
        )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.agent_turns.list_running() == []


async def test_a_conversation_lists_its_turns_newest_first_and_a_limit_takes_the_first(
    database: Database,
) -> None:
    scope = await conversation(database, CONVERSATION)
    turns = [
        receipt(
            scope, client_turn_id=f"client-{index}", at=T1 + timedelta(minutes=index)
        )
        for index in range(3)
    ]
    # One turn at a time per conversation, so each is admitted after the one before it ends.
    for turn in turns:
        await add(database, turn)
        await finish(
            database,
            turn,
            status=AgentTurnStatus.COMPLETED,
            at=turn.created_at + timedelta(seconds=1),
        )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        store = unit_of_work.agent_turns
        assert [
            item.id
            for item in await store.list_for_conversation(WORKSPACE_ONE, CONVERSATION)
        ] == [turns[2].id, turns[1].id, turns[0].id]
        assert [
            item.id
            for item in await store.list_for_conversation(
                WORKSPACE_ONE, CONVERSATION, limit=1
            )
        ] == [turns[2].id]


async def test_two_conversations_of_one_agent_each_run_their_own_turn(
    database: Database,
) -> None:
    """One turn per *conversation*, which is not one turn per Agent or per Project."""

    scope = await conversation(database, CONVERSATION)
    other_scope = await conversation(database, OTHER_CONVERSATION, project_id=scope)
    first = receipt(scope, client_turn_id="client-1")
    second = receipt(
        other_scope,
        conversation_id=OTHER_CONVERSATION,
        client_turn_id="client-1",
        at=T1 + timedelta(seconds=1),
    )
    await add(database, first, second)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        store = unit_of_work.agent_turns
        assert (
            await store.running_for_conversation(WORKSPACE_ONE, CONVERSATION)
        ) == first
        assert (
            await store.running_for_conversation(WORKSPACE_ONE, OTHER_CONVERSATION)
        ) == second
        assert len(await store.list_running()) == 2
