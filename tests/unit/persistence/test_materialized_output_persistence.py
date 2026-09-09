import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import event

from grafy_core.artifacts import ArtifactObject, ArtifactRefSequence, ArtifactTypeKey
from grafy_core.runtime.in_memory import InMemoryDataStore, InMemoryUnitOfWork
from grafy_core.domain.materialized_outputs import MaterializedNodeOutputs
from grafy_core.domain.saved_graphs import (
    SavedGraph,
    SavedGraphDocument,
    SavedGraphRevision,
)

from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_persistence import schema


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    database_path = tmp_path / "materialized-outputs.sqlite3"
    created = create_database(f"sqlite+aiosqlite:///{database_path}")
    async with created.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            schema.workspaces.insert(),
            {
                "id": WORKSPACE_ID,
                "slug": "team",
                "name": "Local",
                "kind": "shared",
                "created_at": datetime(2026, 7, 1, tzinfo=UTC),
                "updated_at": datetime(2026, 7, 1, tzinfo=UTC),
            },
        )
    try:
        yield created
    finally:
        await created.dispose()


async def _persist_graph(
    unit_of_work: SqlAlchemyUnitOfWork,
    graph_id: UUID,
) -> None:
    async with unit_of_work as entered:
        await entered.graphs.add(
            SavedGraph(
                workspace_id=WORKSPACE_ID,
                id=graph_id,
                name="Materialized graph",
                document=SavedGraphDocument(),
            )
        )
        await entered.graphs.add_revision(
            SavedGraphRevision(
                workspace_id=WORKSPACE_ID,
                graph_id=graph_id,
                revision=1,
                name="Materialized graph",
                document=SavedGraphDocument(),
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )
        await entered.graphs.add_revision(
            SavedGraphRevision(
                workspace_id=WORKSPACE_ID,
                graph_id=graph_id,
                revision=2,
                name="Materialized graph",
                document=SavedGraphDocument(),
                created_at=datetime(2026, 7, 1, tzinfo=UTC),
            )
        )
        await entered.commit()


@pytest.mark.asyncio
async def test_in_memory_materializations_follow_unit_of_work_commit_boundaries() -> (
    None
):
    store = InMemoryDataStore()
    unit_of_work = InMemoryUnitOfWork(store)
    graph_id = UUID("00000000-0000-0000-0000-000000000001")
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="scalar.integer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 1},
    )
    committed = MaterializedNodeOutputs(
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        graph_revision=1,
        node_id="committed",
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000002"),
        outputs={"value": artifact.ref()},
    )
    discarded = MaterializedNodeOutputs(
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        graph_revision=1,
        node_id="discarded",
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000003"),
        outputs={"value": artifact.ref()},
    )

    async with unit_of_work as entered:
        await entered.materialized_outputs.upsert(committed)
        await entered.commit()
    async with unit_of_work as entered:
        await entered.materialized_outputs.upsert(discarded)
    async with unit_of_work as entered:
        listed = await entered.materialized_outputs.list_for_graph(
            WORKSPACE_ID, graph_id, 1
        )

    assert [value.node_id for value in listed] == ["committed"]


@pytest.mark.asyncio
async def test_artifact_metadata_round_trips_in_a_fresh_session(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    inline = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        id=UUID("00000000-0000-0000-0000-000000000101"),
        artifact_type="scalar.integer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 13},
        byte_size=12,
        sha256="1" * 64,
        metadata={"producer_node_id": "addition"},
    )
    stored = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        id=UUID("00000000-0000-0000-0000-000000000102"),
        artifact_type="image.raster",
        schema_version=1,
        content_type="image/png",
        storage_backend="local",
        bucket="workbench-artifacts",
        object_key="image.raster/v1/page.png",
        byte_size=4096,
        sha256="2" * 64,
        metadata={"original_filename": "page.png"},
    )

    async with unit_of_work as entered:
        await entered.artifacts.add(inline)
        await entered.artifacts.add(stored)
        await entered.commit()

    async with unit_of_work as entered:
        loaded_inline = await entered.artifacts.get(WORKSPACE_ID, inline.id)
        loaded_stored = await entered.artifacts.get(WORKSPACE_ID, stored.id)
        integer_artifacts = await entered.artifacts.list_by_type(
            WORKSPACE_ID, ArtifactTypeKey("scalar.integer", 1)
        )

    assert loaded_inline is not None
    assert loaded_inline is not inline
    assert loaded_inline.ref() == inline.ref()
    assert loaded_inline.inline_payload == {"value": 13}
    assert loaded_inline.metadata == {"producer_node_id": "addition"}
    assert loaded_stored is not None
    assert loaded_stored.bucket == "workbench-artifacts"
    assert loaded_stored.object_key == "image.raster/v1/page.png"
    assert [artifact.id for artifact in integer_artifacts] == [inline.id]


@pytest.mark.asyncio
async def test_latest_node_outputs_preserve_exact_single_and_sequence_envelopes(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    graph_id = UUID("00000000-0000-0000-0000-000000000201")
    await _persist_graph(unit_of_work, graph_id)
    first = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        id=UUID("00000000-0000-0000-0000-000000000211"),
        artifact_type="scalar.integer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 3},
        sha256="3" * 64,
    )
    second = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        id=UUID("00000000-0000-0000-0000-000000000212"),
        artifact_type="scalar.integer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 7},
        sha256="4" * 64,
    )
    sequence = ArtifactRefSequence(
        sequence_id=UUID("00000000-0000-0000-0000-000000000220"),
        artifact_type="scalar.integer",
        schema_version=1,
        item_refs=[first.ref(), second.ref()],
        ordered=True,
        index_key="source_order",
        metadata={"source_sequence_id": "upstream-sequence"},
    )
    materialized_at = datetime(2026, 7, 15, 8, 30, tzinfo=UTC)
    materialization = MaterializedNodeOutputs(
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        graph_revision=1,
        node_id="source",
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000230"),
        outputs={"single": first.ref(), "sequence": sequence},
        materialized_at=materialized_at,
    )

    async with unit_of_work as entered:
        await entered.artifacts.add(first)
        await entered.artifacts.add(second)
        await entered.commit()
    async with unit_of_work as entered:
        await entered.materialized_outputs.upsert(materialization)
        await entered.commit()

    async with unit_of_work as entered:
        loaded = await entered.materialized_outputs.get(
            WORKSPACE_ID, graph_id, 1, "source"
        )
        listed = await entered.materialized_outputs.list_for_graph(
            WORKSPACE_ID, graph_id, 1
        )

    assert loaded is not None
    assert loaded is not materialization
    assert loaded.graph_id == graph_id
    assert loaded.graph_revision == 1
    assert loaded.node_id == "source"
    assert loaded.workflow_run_id == materialization.workflow_run_id
    assert loaded.materialized_at == materialized_at
    assert loaded.outputs["single"] == first.ref()
    loaded_sequence = loaded.outputs["sequence"]
    assert isinstance(loaded_sequence, ArtifactRefSequence)
    assert loaded_sequence == sequence
    assert [value.node_id for value in listed] == ["source"]


@pytest.mark.asyncio
async def test_upsert_replaces_only_the_same_graph_revision_and_node(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    graph_id = UUID("00000000-0000-0000-0000-000000000301")
    await _persist_graph(unit_of_work, graph_id)
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="scalar.integer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 9},
    )
    first = MaterializedNodeOutputs(
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        graph_revision=1,
        node_id="number",
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000310"),
        outputs={"old": artifact.ref()},
        materialized_at=datetime(2026, 7, 15, 9, 0, tzinfo=UTC),
    )
    replacement = MaterializedNodeOutputs(
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        graph_revision=1,
        node_id="number",
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000311"),
        outputs={"value": artifact.ref()},
        materialized_at=datetime(2026, 7, 15, 9, 5, tzinfo=UTC),
    )
    next_revision = MaterializedNodeOutputs(
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        graph_revision=2,
        node_id="number",
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000312"),
        outputs={"value": artifact.ref()},
        materialized_at=datetime(2026, 7, 15, 9, 10, tzinfo=UTC),
    )

    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    async with unit_of_work as entered:
        await entered.materialized_outputs.upsert(first)
        await entered.commit()
    async with unit_of_work as entered:
        await entered.materialized_outputs.upsert(replacement)
        await entered.materialized_outputs.upsert(next_revision)
        await entered.commit()

    async with unit_of_work as entered:
        revision_one = await entered.materialized_outputs.get(
            WORKSPACE_ID, graph_id, 1, "number"
        )
        revision_two = await entered.materialized_outputs.get(
            WORKSPACE_ID, graph_id, 2, "number"
        )

    assert revision_one is not None
    assert revision_one.workflow_run_id == replacement.workflow_run_id
    assert set(revision_one.outputs) == {"value"}
    assert revision_two is not None
    assert revision_two.workflow_run_id == next_revision.workflow_run_id


@pytest.mark.asyncio
async def test_concurrent_first_upserts_share_one_valid_materialization(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    graph_id = UUID("00000000-0000-0000-0000-000000000321")
    await _persist_graph(unit_of_work, graph_id)
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        id=UUID("00000000-0000-0000-0000-000000000324"),
        artifact_type="scalar.integer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 9},
    )
    first = MaterializedNodeOutputs(
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        graph_revision=1,
        node_id="number",
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000322"),
        outputs={"first": artifact.ref()},
        materialized_at=datetime(2026, 7, 15, 9, 20, tzinfo=UTC),
    )
    second = MaterializedNodeOutputs(
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        graph_revision=1,
        node_id="number",
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000323"),
        outputs={"second": artifact.ref()},
        materialized_at=datetime(2026, 7, 15, 9, 21, tzinfo=UTC),
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    first_statement_finished = asyncio.Event()
    second_statement_started = asyncio.Event()
    release_first_commit = asyncio.Event()
    insert_count = 0

    def observe_materialized_insert(
        connection: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        del connection, cursor, parameters, context, executemany
        nonlocal insert_count
        if statement.lstrip().startswith("INSERT INTO materialized_node_outputs"):
            insert_count += 1
            if insert_count == 2:
                second_statement_started.set()

    async def write_first() -> None:
        async with unit_of_work as entered:
            await entered.materialized_outputs.upsert(first)
            first_statement_finished.set()
            await asyncio.wait_for(release_first_commit.wait(), timeout=5)
            await entered.commit()

    async def write_second() -> None:
        await asyncio.wait_for(first_statement_finished.wait(), timeout=5)
        async with unit_of_work as entered:
            await entered.materialized_outputs.upsert(second)
            await entered.commit()

    event.listen(
        database.engine.sync_engine,
        "before_cursor_execute",
        observe_materialized_insert,
    )
    try:
        async with asyncio.TaskGroup() as task_group:
            task_group.create_task(write_first())
            second_task = task_group.create_task(write_second())
            await asyncio.wait_for(second_statement_started.wait(), timeout=5)
            assert not second_task.done()
            release_first_commit.set()
    finally:
        event.remove(
            database.engine.sync_engine,
            "before_cursor_execute",
            observe_materialized_insert,
        )

    async with unit_of_work as entered:
        loaded = await entered.materialized_outputs.get(
            WORKSPACE_ID, graph_id, 1, "number"
        )
        listed = await entered.materialized_outputs.list_for_graph(
            WORKSPACE_ID, graph_id, 1
        )

    assert insert_count == 2
    assert loaded is not None
    assert loaded.workflow_run_id == second.workflow_run_id
    assert loaded.outputs == second.outputs
    assert loaded.materialized_at == second.materialized_at
    assert [value.node_id for value in listed] == ["number"]


@pytest.mark.asyncio
async def test_deleting_graph_cascades_materializations_but_keeps_artifacts(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    graph_id = UUID("00000000-0000-0000-0000-000000000401")
    await _persist_graph(unit_of_work, graph_id)
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ID,
        artifact_type="scalar.integer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 4},
    )
    materialization = MaterializedNodeOutputs(
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        graph_revision=1,
        node_id="number",
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000410"),
        outputs={"value": artifact.ref()},
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.commit()
    async with unit_of_work as entered:
        await entered.materialized_outputs.upsert(materialization)
        await entered.commit()
    async with unit_of_work as entered:
        graph = await entered.graphs.get(WORKSPACE_ID, graph_id)
        assert graph is not None
        await entered.graphs.remove(WORKSPACE_ID, graph)
        await entered.commit()

    async with unit_of_work as entered:
        assert (
            await entered.materialized_outputs.list_for_graph(WORKSPACE_ID, graph_id, 1)
            == []
        )
        assert await entered.artifacts.get(WORKSPACE_ID, artifact.id) is not None


@pytest.mark.asyncio
async def test_reusable_unit_of_work_is_isolated_per_async_task(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    both_entered = asyncio.Event()
    entered_count = 0

    async def enter_and_wait() -> int:
        nonlocal entered_count
        async with unit_of_work as entered:
            entered_count += 1
            if entered_count == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), timeout=1)
            return len(
                await entered.artifacts.list_by_type(
                    WORKSPACE_ID, ArtifactTypeKey("scalar.integer", 1)
                )
            )

    assert await asyncio.gather(enter_and_wait(), enter_and_wait()) == [0, 0]

    async with unit_of_work:
        with pytest.raises(RuntimeError, match="already entered in this task"):
            async with unit_of_work:
                pass
