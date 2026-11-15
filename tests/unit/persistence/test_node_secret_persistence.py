from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from grafy_core.domain.node_secrets import EncryptedNodeSecret
from grafy_core.domain.projects import Project
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
    async with SqlAlchemyUnitOfWork(created.sessions) as uow:
        await uow.identity.add_workspace(
            Workspace(
                id=WORKSPACE_ID,
                slug="team",
                name="Team",
                kind="shared",
            )
        )
        await uow.commit()
    try:
        yield created
    finally:
        await created.dispose()


def _encrypted_secret(
    project_id: UUID,
    *,
    workspace_id: UUID,
    ciphertext: bytes = b"ciphertext-with-authentication-tag",
    at: datetime | None = None,
) -> EncryptedNodeSecret:
    timestamp = at or datetime(2026, 7, 16, 8, 0, tzinfo=UTC)
    return EncryptedNodeSecret(
        workspace_id=workspace_id,
        project_id=project_id,
        graph_id="main",
        node_id="llm-node",
        name="api_key",
        operator_id="llm.openai.chat-completion",
        operator_version=1,
        key_id="0123456789abcdef",
        aad_version=3,
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
    graph = Project(
        workspace_id=WORKSPACE_ID,
        name="Encrypted graph",
    )
    original = _encrypted_secret(graph.id, workspace_id=graph.workspace_id)
    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        await uow.projects.add(graph)
        await uow.node_secrets.upsert(original)
        await uow.commit()

    replacement_time = original.updated_at + timedelta(hours=1)
    replacement = _encrypted_secret(
        graph.id,
        workspace_id=graph.workspace_id,
        ciphertext=b"replacement-ciphertext-with-tag",
        at=replacement_time,
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        await uow.node_secrets.upsert(replacement)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        loaded = await uow.node_secrets.get(
            graph.workspace_id,
            graph.id,
            "main",
            "llm-node",
            "api_key",
        )
        listed = await uow.node_secrets.list_for_graph(
            graph.workspace_id, graph.id, "main"
        )

    assert loaded is not None
    assert loaded.ciphertext == replacement.ciphertext
    assert loaded.created_at == original.created_at
    assert loaded.updated_at == replacement.updated_at
    assert listed == [loaded]


@pytest.mark.asyncio
async def test_deleting_project_cascades_to_node_secrets(
    database: Database,
) -> None:
    graph = Project(
        workspace_id=WORKSPACE_ID,
        name="Disposable secret",
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        await uow.projects.add(graph)
        await uow.node_secrets.upsert(
            _encrypted_secret(graph.id, workspace_id=graph.workspace_id)
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        loaded_graph = await uow.projects.get(graph.workspace_id, graph.id)
        assert loaded_graph is not None
        await uow.projects.remove(graph.workspace_id, loaded_graph)
        await uow.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        assert (
            await uow.node_secrets.get(
                graph.workspace_id, graph.id, "main", "llm-node", "api_key"
            )
            is None
        )


@pytest.mark.asyncio
async def test_node_secret_can_be_removed_without_reading_ciphertext(
    database: Database,
) -> None:
    graph = Project(
        workspace_id=WORKSPACE_ID,
        name="Clear secret",
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        await uow.projects.add(graph)
        await uow.node_secrets.upsert(
            _encrypted_secret(graph.id, workspace_id=graph.workspace_id)
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        await uow.node_secrets.remove(
            graph.workspace_id, graph.id, "main", "llm-node", "api_key"
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as uow:
        assert (
            await uow.node_secrets.list_for_graph(graph.workspace_id, graph.id, "main")
            == []
        )
