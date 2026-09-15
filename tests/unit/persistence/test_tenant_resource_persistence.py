from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from grafy_core.artifacts import ArtifactObject
from grafy_core.domain.errors import NotFoundError
from grafy_core.domain.execution_history import GraphExecution
from grafy_core.domain.invocation_cache import InvocationCacheEntry
from grafy_core.domain.materialized_outputs import MaterializedNodeOutputs
from grafy_core.domain.node_secrets import EncryptedNodeSecret
from grafy_core.domain.saved_graphs import SavedGraph, SavedGraphDocument
from grafy_core.domain.uploads import Upload
from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

WORKSPACE_ONE = UUID("00000000-0000-0000-0000-000000000201")
WORKSPACE_TWO = UUID("00000000-0000-0000-0000-000000000202")


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database = create_database(f"sqlite+aiosqlite:///{tmp_path / 'tenant.sqlite3'}")
    async with database.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            text(
                "INSERT INTO workspaces "
                "(id, slug, name, kind, created_at, updated_at) VALUES "
                "(:one, 'one', 'One', 'shared', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP), "
                "(:two, 'two', 'Two', 'shared', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"one": WORKSPACE_ONE.hex, "two": WORKSPACE_TWO.hex},
        )
    try:
        yield database
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_sql_repositories_require_workspace_for_artifact_cache_and_upload(
    database: Database,
) -> None:
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ONE,
        id=UUID("00000000-0000-0000-0000-000000000203"),
        artifact_type="test.value",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 1},
        metadata={},
    )
    artifact_two = ArtifactObject(
        workspace_id=WORKSPACE_TWO,
        id=UUID("00000000-0000-0000-0000-000000000207"),
        artifact_type="test.value",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 2},
        metadata={},
    )
    cache_one = InvocationCacheEntry(
        workspace_id=WORKSPACE_ONE,
        key_sha256="c" * 64,
        generation=UUID("00000000-0000-0000-0000-000000000208"),
        outputs={"value": artifact.ref()},
    )
    cache_two = InvocationCacheEntry(
        workspace_id=WORKSPACE_TWO,
        key_sha256=cache_one.key_sha256,
        generation=UUID("00000000-0000-0000-0000-000000000209"),
        outputs={"value": artifact_two.ref()},
    )
    upload = Upload(
        workspace_id=WORKSPACE_ONE,
        upload_id=UUID("00000000-0000-0000-0000-00000000020a"),
        original_filename="source.csv",
        bucket="artifacts",
        object_key="objects/source",
        expected_size=4,
    )
    graph = SavedGraph(
        workspace_id=WORKSPACE_ONE,
        id=UUID("00000000-0000-0000-0000-000000000204"),
        name="Tenant graph",
        document=SavedGraphDocument(),
    )
    revision = graph.snapshot()
    secret = EncryptedNodeSecret(
        workspace_id=WORKSPACE_ONE,
        graph_id=graph.id,
        node_id="node",
        name="secret",
        operator_id="test.operator",
        operator_version=1,
        key_id="key",
        aad_version=2,
        dependency_sha256="d" * 64,
        nonce=b"0" * 12,
        ciphertext=b"ciphertext",
        created_at=graph.created_at,
        updated_at=graph.updated_at,
    )
    materialized = MaterializedNodeOutputs(
        workspace_id=WORKSPACE_ONE,
        graph_id=graph.id,
        graph_revision=graph.revision,
        node_id="node",
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000205"),
        outputs={},
    )
    execution = GraphExecution(
        workspace_id=WORKSPACE_ONE,
        execution_id=UUID("00000000-0000-0000-0000-000000000206"),
        graph_id=graph.id,
        graph_revision=graph.revision,
        requested_node_ids=("node",),
        status="queued",
    )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.graphs.add_revision(revision)
        await unit_of_work.artifacts.add(artifact)
        await unit_of_work.artifacts.add(artifact_two)
        assert await unit_of_work.invocation_cache.put_if_absent(cache_one)
        assert await unit_of_work.invocation_cache.put_if_absent(cache_two)
        await unit_of_work.uploads.add(upload)
        await unit_of_work.node_secrets.upsert(secret)
        await unit_of_work.materialized_outputs.upsert(materialized)
        await unit_of_work.execution_history.add(execution)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.artifacts.get(WORKSPACE_ONE, artifact.id) is not None
        assert await unit_of_work.artifacts.get(WORKSPACE_TWO, artifact.id) is None
        assert await unit_of_work.graphs.get(WORKSPACE_TWO, graph.id) is None
        assert (
            await unit_of_work.graphs.get_revision(
                WORKSPACE_TWO,
                graph.id,
                graph.revision,
            )
            is None
        )
        assert (
            await unit_of_work.node_secrets.get(
                WORKSPACE_TWO,
                graph.id,
                secret.node_id,
                secret.name,
            )
            is None
        )
        assert (
            await unit_of_work.materialized_outputs.get(
                WORKSPACE_TWO,
                graph.id,
                graph.revision,
                materialized.node_id,
            )
            is None
        )
        assert (
            await unit_of_work.execution_history.get(
                WORKSPACE_TWO,
                execution.execution_id,
            )
            is None
        )
        assert (
            await unit_of_work.execution_history.list_for_graph(
                WORKSPACE_TWO,
                graph.id,
                limit=10,
            )
        ).items == ()
        with pytest.raises(NotFoundError):
            await unit_of_work.execution_history.update(
                replace(execution, workspace_id=WORKSPACE_TWO)
            )
        stored_cache_one = await unit_of_work.invocation_cache.get(
            WORKSPACE_ONE,
            cache_one.key_sha256,
        )
        stored_cache_two = await unit_of_work.invocation_cache.get(
            WORKSPACE_TWO,
            cache_two.key_sha256,
        )
        assert stored_cache_one is not None
        assert stored_cache_two is not None
        assert stored_cache_one.generation == cache_one.generation
        assert stored_cache_one.outputs == cache_one.outputs
        assert stored_cache_two.generation == cache_two.generation
        assert stored_cache_two.outputs == cache_two.outputs
        assert stored_cache_one != stored_cache_two
        assert (
            await unit_of_work.uploads.get(
                WORKSPACE_TWO,
                upload.upload_id,
            )
            is None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("object_key", "expected_size", "status", "actual_size", "completed_at"),
    [
        ("", 0, "pending", None, None),
        ("objects/" + "x" * 1025, 0, "pending", None, None),
        ("objects/source", -1, "pending", None, None),
        ("objects/source", 0, "ready", None, datetime.now(UTC)),
        ("objects/source", 0, "ready", 4, None),
    ],
)
async def test_sql_uploads_reject_unbounded_or_unconfirmed_rows(
    database: Database,
    object_key: str,
    expected_size: int,
    status: str,
    actual_size: int | None,
    completed_at: datetime | None,
) -> None:
    with pytest.raises(IntegrityError):
        async with database.engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO uploads "
                    "(workspace_id, upload_id, original_filename, bucket, "
                    "object_key, expected_size, status, actual_size, completed_at, "
                    "created_at) "
                    "VALUES (:workspace_id, :upload_id, 'input.csv', 'artifacts', "
                    ":object_key, :expected_size, :status, :actual_size, "
                    ":completed_at, CURRENT_TIMESTAMP)"
                ),
                {
                    "workspace_id": WORKSPACE_ONE.hex,
                    "upload_id": UUID(int=1).hex,
                    "object_key": object_key,
                    "expected_size": expected_size,
                    "status": status,
                    "actual_size": actual_size,
                    "completed_at": completed_at,
                },
            )
