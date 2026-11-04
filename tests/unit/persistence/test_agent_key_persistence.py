"""Encrypted per-Agent key persistence (ADR 0021, issue #202).

Runs against SQLite and, when ``GRAFY_TEST_POSTGRES_URL`` names an empty disposable
database, against PostgreSQL in a per-test schema.

What is being proved here is narrow on purpose: the row holds seal material and its
coordinates, a replacement keeps the row's origin, clearing needs no plaintext, and the
Project owns the row's life. Whether the seal *opens* is the application owner's business
and is covered in ``tests/unit/api/agents/test_agent_keys.py``.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from grafy_core.domain.agent_keys import AGENT_KEY_AAD_VERSION, EncryptedAgentKey
from grafy_core.domain.projects import Project
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.support.persistence import WORKSPACE_ONE, WORKSPACE_TWO
from tests.support.persistence import database as _base_database_fixture

base_database = _base_database_fixture

GRAPH_ID = "main"
AGENT_ID = "research"
SET_BY = UUID("00000000-0000-0000-0000-0000000000e1")
T1 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


@pytest.fixture
async def database(base_database: Database) -> AsyncIterator[Database]:
    yield base_database


def sealed(
    project_id: UUID,
    *,
    workspace_id: UUID = WORKSPACE_ONE,
    agent_id: str = AGENT_ID,
    ciphertext: bytes = b"ciphertext-with-authentication-tag",
    key_id: str = "0123456789abcdef",
    at: datetime | None = None,
) -> EncryptedAgentKey:
    stamp = at or T1
    return EncryptedAgentKey(
        workspace_id=workspace_id,
        project_id=project_id,
        graph_id=GRAPH_ID,
        agent_id=agent_id,
        key_id=key_id,
        aad_version=AGENT_KEY_AAD_VERSION,
        nonce=b"0123456789ab",
        ciphertext=ciphertext,
        set_by_user_id=SET_BY,
        created_at=stamp,
        updated_at=stamp,
    )


async def add_project(
    database: Database, name: str = "Agents", workspace_id: UUID = WORKSPACE_ONE
) -> Project:
    row = Project(workspace_id=workspace_id, name=name)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.projects.add(row)
        await unit_of_work.commit()
    return row


@pytest.mark.asyncio
async def test_a_sealed_key_round_trips_and_a_replacement_keeps_its_origin(
    database: Database,
) -> None:
    project = await add_project(database)
    original = sealed(project.id)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.agent_keys.upsert(original)
        await unit_of_work.commit()

    replacement = sealed(
        project.id,
        ciphertext=b"replacement-ciphertext-with-tag",
        key_id="fedcba9876543210",
        at=T1 + timedelta(hours=1),
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.agent_keys.upsert(replacement)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        loaded = await unit_of_work.agent_keys.get(
            WORKSPACE_ONE, project.id, GRAPH_ID, AGENT_ID
        )
        listed = await unit_of_work.agent_keys.list_for_graph(
            WORKSPACE_ONE, project.id, GRAPH_ID
        )

    assert loaded is not None
    assert loaded.ciphertext == replacement.ciphertext
    assert loaded.nonce == replacement.nonce
    assert loaded.key_id == "fedcba9876543210"
    assert loaded.set_by_user_id == SET_BY
    assert loaded.created_at == original.created_at
    assert loaded.updated_at == replacement.updated_at
    assert listed == [loaded]


@pytest.mark.asyncio
async def test_keys_of_one_graph_are_listed_by_agent_and_scoped_to_the_workspace(
    database: Database,
) -> None:
    project = await add_project(database)
    # A key belongs to a Project of its own Workspace: the composite foreign key makes a
    # Project of another Workspace a miss rather than a row to filter out, so the other
    # Workspace gets its own Project here and its key must stay on that side.
    theirs = await add_project(database, name="Theirs", workspace_id=WORKSPACE_TWO)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        for agent_id in ("zeta", "alpha"):
            await unit_of_work.agent_keys.upsert(sealed(project.id, agent_id=agent_id))
        await unit_of_work.agent_keys.upsert(
            sealed(theirs.id, workspace_id=WORKSPACE_TWO, agent_id="other")
        )
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        mine = await unit_of_work.agent_keys.list_for_graph(
            WORKSPACE_ONE, project.id, GRAPH_ID
        )
        others = await unit_of_work.agent_keys.list_for_graph(
            WORKSPACE_TWO, theirs.id, GRAPH_ID
        )
        # Reading another Workspace's coordinates, or our own coordinates through them.
        assert (
            await unit_of_work.agent_keys.get(WORKSPACE_TWO, project.id, GRAPH_ID, AGENT_ID)
        ) is None
        assert (
            await unit_of_work.agent_keys.list_for_graph(WORKSPACE_TWO, project.id, GRAPH_ID)
            == []
        )

    assert [key.agent_id for key in mine] == ["alpha", "zeta"]
    assert [key.agent_id for key in others] == ["other"]


@pytest.mark.asyncio
async def test_clearing_a_key_needs_nothing_it_could_only_have_read(
    database: Database,
) -> None:
    project = await add_project(database)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.agent_keys.upsert(sealed(project.id))
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.agent_keys.remove(WORKSPACE_ONE, project.id, GRAPH_ID, AGENT_ID)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert (
            await unit_of_work.agent_keys.get(WORKSPACE_ONE, project.id, GRAPH_ID, AGENT_ID)
        ) is None
        assert (
            await unit_of_work.agent_keys.list_for_graph(WORKSPACE_ONE, project.id, GRAPH_ID)
            == []
        )

    # Clearing what was never there is not an error: the state the caller wanted holds.
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.agent_keys.remove(WORKSPACE_ONE, project.id, GRAPH_ID, AGENT_ID)
        await unit_of_work.commit()


@pytest.mark.asyncio
async def test_deleting_the_project_takes_the_sealed_key_with_it(
    database: Database,
) -> None:
    project = await add_project(database, name="Disposable key")
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.agent_keys.upsert(sealed(project.id))
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        loaded = await unit_of_work.projects.get(WORKSPACE_ONE, project.id)
        assert loaded is not None
        await unit_of_work.projects.remove(WORKSPACE_ONE, loaded)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert (
            await unit_of_work.agent_keys.list_for_graph(WORKSPACE_ONE, project.id, GRAPH_ID)
            == []
        )
