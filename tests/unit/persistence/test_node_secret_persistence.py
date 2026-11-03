from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from grafy_core.domain.node_secrets import EncryptedNodeSecret
from grafy_core.domain.graph_documents import SavedGraph, GraphDocument
from grafy_core.domain.identity import Workspace

from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000007")


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database_path = tmp_path / "node-secrets.sqlite3"
    created = create_database(f"sqlite+aiosqlite:///{database_path}")
    async with created.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    async with SqlAlchemyUnitOfWork(created.sessions) as unit_of_work:
        await unit_of_work.identity.add_workspace(
            Workspace(
                id=WORKSPACE_ID,
                slug="team",
                name="Team",
                kind="shared",
            )
        )
        await unit_of_work.commit()
    try:
        yield created
    finally:
        await created.dispose()


def _encrypted_secret(
    graph_id: UUID,
    *,
    workspace_id: UUID,
    ciphertext: bytes = b"ciphertext-with-authentication-tag",
    at: datetime | None = None,
) -> EncryptedNodeSecret:
    timestamp = at or datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    return EncryptedNodeSecret(
        workspace_id=workspace_id,
        graph_id=graph_id,
        node_id="llm-node",
        name="api_key",
        operator_id="llm.openai.chat-completion",
        operator_version=1,
        key_id="0123456789abcdef",
        aad_version=2,
        dependency_sha256="a" * 64,
        nonce=b"0123456789ab",
        ciphertext=ciphertext,
        created_at=timestamp,
        updated_at=timestamp,
    )


@pytest.mark.asyncio
async def test_node_secret_round_trips_and_upserts_without_replacing_created_at(
    database: Database,
) -> None:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        name="Encrypted graph",
        document=GraphDocument(),
    )
    original = _encrypted_secret(graph.id, workspace_id=graph.workspace_id)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.node_secrets.upsert(original)
        await unit_of_work.commit()

    replacement_time = original.updated_at + timedelta(hours=1)
    replacement = _encrypted_secret(
        graph.id,
        workspace_id=graph.workspace_id,
        ciphertext=b"replacement-ciphertext-with-tag",
        at=replacement_time,
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.node_secrets.upsert(replacement)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        loaded = await unit_of_work.node_secrets.get(
            graph.workspace_id,
            graph.id,
            "llm-node",
            "api_key",
        )
        listed = await unit_of_work.node_secrets.list_for_graph(
            graph.workspace_id, graph.id
        )

    assert loaded is not None
    assert loaded.ciphertext == replacement.ciphertext
    assert loaded.created_at == original.created_at
    assert loaded.updated_at == replacement.updated_at
    assert listed == [loaded]


@pytest.mark.asyncio
async def test_deleting_saved_graph_cascades_to_node_secrets(
    database: Database,
) -> None:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        name="Disposable secret",
        document=GraphDocument(),
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.node_secrets.upsert(
            _encrypted_secret(graph.id, workspace_id=graph.workspace_id)
        )
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        loaded_graph = await unit_of_work.graphs.get(graph.workspace_id, graph.id)
        assert loaded_graph is not None
        await unit_of_work.graphs.remove(graph.workspace_id, loaded_graph)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert (
            await unit_of_work.node_secrets.get(
                graph.workspace_id, graph.id, "llm-node", "api_key"
            )
            is None
        )


@pytest.mark.asyncio
async def test_node_secret_can_be_removed_without_reading_ciphertext(
    database: Database,
) -> None:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        name="Clear secret",
        document=GraphDocument(),
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.node_secrets.upsert(
            _encrypted_secret(graph.id, workspace_id=graph.workspace_id)
        )
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.node_secrets.remove(
            graph.workspace_id, graph.id, "llm-node", "api_key"
        )
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert (
            await unit_of_work.node_secrets.list_for_graph(graph.workspace_id, graph.id)
            == []
        )


@pytest.mark.asyncio
async def test_saved_graph_revision_lock_is_a_no_op_for_the_graph_row(
    database: Database,
) -> None:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        name="Lock target",
        document=GraphDocument(),
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.lock_revision(
            graph.workspace_id, graph.id, graph.revision
        )
        locked = await unit_of_work.graphs.get(graph.workspace_id, graph.id)
        await unit_of_work.commit()

    assert locked is not None
    assert locked.revision == 1
