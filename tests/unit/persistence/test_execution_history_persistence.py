import asyncio
from dataclasses import replace
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID
from typing import Literal

import pytest
from sqlalchemy import event, select

from grafy_core.artifacts import ArtifactObject, ArtifactRefSequence
from grafy_core.domain.errors import (
    CollaborationActiveExecutionError,
    ObjectAlreadyExistsError,
)
from grafy_core.domain.execution_history import (
    GraphExecution,
    GraphExecutionNodeResult,
    GraphExecutionStatus,
)
from grafy_core.domain.saved_graphs import (
    SavedGraph,
    SavedGraphDocument,
    SavedGraphRevision,
)

from grafy_persistence import schema
from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork


WORKSPACE_ONE = UUID("00000000-0000-0000-0000-000000000001")
WORKSPACE_TWO = UUID("00000000-0000-0000-0000-000000000002")


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    created = create_database(
        f"sqlite+aiosqlite:///{tmp_path / 'execution-history.sqlite3'}"
    )
    async with created.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(
            schema.workspaces.insert(),
            [
                {
                    "id": WORKSPACE_ONE,
                    "slug": "one",
                    "name": "One",
                    "kind": "shared",
                    "created_at": datetime(2026, 7, 1, tzinfo=UTC),
                    "updated_at": datetime(2026, 7, 1, tzinfo=UTC),
                },
                {
                    "id": WORKSPACE_TWO,
                    "slug": "two",
                    "name": "Two",
                    "kind": "shared",
                    "created_at": datetime(2026, 7, 1, tzinfo=UTC),
                    "updated_at": datetime(2026, 7, 1, tzinfo=UTC),
                },
            ],
        )
    try:
        yield created
    finally:
        await created.dispose()


async def _persist_graph_revisions(
    unit_of_work: SqlAlchemyUnitOfWork,
    graph_id: UUID,
    workspace_id: UUID,
) -> None:
    document = SavedGraphDocument()
    created_at = datetime(2026, 7, 18, 7, 0, tzinfo=UTC)
    async with unit_of_work as entered:
        await entered.graphs.add(
            SavedGraph(
                workspace_id=workspace_id,
                id=graph_id,
                name="Execution history graph",
                document=document,
                revision=2,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        await entered.commit()
    async with unit_of_work as entered:
        for revision in (1, 2):
            await entered.graphs.add_revision(
                SavedGraphRevision(
                    workspace_id=workspace_id,
                    graph_id=graph_id,
                    revision=revision,
                    name="Execution history graph",
                    document=document,
                    created_at=created_at,
                )
            )
        await entered.commit()


@pytest.mark.asyncio
async def test_execution_lifecycle_and_node_outputs_round_trip_without_replacing_head(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    graph_id = UUID("00000000-0000-0000-0000-000000000101")
    execution_id = UUID("00000000-0000-0000-0000-000000000102")
    await _persist_graph_revisions(unit_of_work, graph_id, WORKSPACE_ONE)
    created_at = datetime(2026, 7, 18, 8, 0, tzinfo=UTC)
    started_at = created_at + timedelta(seconds=1)
    finished_at = started_at + timedelta(seconds=2)
    execution = GraphExecution(
        workspace_id=WORKSPACE_ONE,
        execution_id=execution_id,
        graph_id=graph_id,
        graph_revision=2,
        status="queued",
        scope="selected-with-dependencies",
        requested_node_ids=("upload", "extract"),
        submitted_request={
            "nodes": [],
            "graph_id": str(graph_id),
            "graph_revision": 2,
        },
        idempotency_key="api-retry-101",
        created_at=created_at,
    )
    image = ArtifactObject(
        workspace_id=WORKSPACE_ONE,
        id=UUID("00000000-0000-0000-0000-000000000103"),
        artifact_type="image.raster",
        schema_version=1,
        content_type="image/png",
        storage_backend="local",
        object_key="images/page.png",
    )
    second_image = ArtifactObject(
        workspace_id=WORKSPACE_ONE,
        id=UUID("00000000-0000-0000-0000-000000000104"),
        artifact_type="image.raster",
        schema_version=1,
        content_type="image/png",
        storage_backend="local",
        object_key="images/page-2.png",
    )
    sequence = ArtifactRefSequence(
        sequence_id=UUID("00000000-0000-0000-0000-000000000105"),
        artifact_type="image.raster",
        schema_version=1,
        item_refs=[image.ref(), second_image.ref()],
    )

    async with unit_of_work as entered:
        await entered.execution_history.add(execution)
        await entered.commit()
    running = replace(execution, status="running", started_at=started_at)
    async with unit_of_work as entered:
        await entered.execution_history.update(running)
        await entered.commit()
    succeeded = replace(
        running,
        status="succeeded",
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000106"),
        finished_at=finished_at,
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(image)
        await entered.artifacts.add(second_image)
        await entered.execution_history.add_node_result(
            GraphExecutionNodeResult(
                workspace_id=WORKSPACE_ONE,
                execution_id=execution_id,
                node_id="upload",
                position=0,
                status="succeeded",
                outputs={"images": sequence},
                completed_at=started_at + timedelta(seconds=1),
            )
        )
        await entered.execution_history.add_node_result(
            GraphExecutionNodeResult(
                workspace_id=WORKSPACE_ONE,
                execution_id=execution_id,
                node_id="extract",
                position=1,
                status="failed",
                outputs={},
                error="provider timed out",
                completed_at=finished_at,
            )
        )
        await entered.execution_history.update(succeeded)
        await entered.commit()

    async with unit_of_work as entered:
        detail = await entered.execution_history.get(WORKSPACE_ONE, execution_id)
        page = await entered.execution_history.list_for_graph(
            WORKSPACE_ONE, graph_id, limit=20
        )
        materialized = await entered.materialized_outputs.list_for_graph(
            WORKSPACE_ONE, graph_id, 2
        )
        by_idempotency_key = await entered.execution_history.get_by_idempotency_key(
            WORKSPACE_ONE,
            "api-retry-101",
        )

    assert detail is not None
    assert detail.execution == succeeded
    assert detail.execution.requested_node_ids == ("upload", "extract")
    assert by_idempotency_key == succeeded
    assert [result.node_id for result in detail.node_results] == ["upload", "extract"]
    assert detail.node_results[0].outputs == {"images": sequence}
    assert detail.node_results[1].error == "provider timed out"
    assert page.items[0].node_count == 2
    assert page.items[0].artifact_count == 2
    assert materialized == []


@pytest.mark.asyncio
async def test_cursor_paging_is_stable_when_execution_timestamps_tie(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    graph_id = UUID("00000000-0000-0000-0000-000000000201")
    await _persist_graph_revisions(unit_of_work, graph_id, WORKSPACE_ONE)
    created_at = datetime(2026, 7, 18, 9, 0, tzinfo=UTC)
    execution_ids = [
        UUID("00000000-0000-0000-0000-000000000201"),
        UUID("00000000-0000-0000-0000-000000000202"),
        UUID("00000000-0000-0000-0000-000000000203"),
    ]
    async with unit_of_work as entered:
        for index, execution_id in enumerate(execution_ids):
            # Only the newest execution may stay active: the partial unique
            # index permits one queued/running/cancelling row per graph.
            active = index == len(execution_ids) - 1
            await entered.execution_history.add(
                GraphExecution(
                    workspace_id=WORKSPACE_ONE,
                    execution_id=execution_id,
                    graph_id=graph_id,
                    graph_revision=1,
                    status="queued" if active else "succeeded",
                    requested_node_ids=("extract",),
                    created_at=created_at,
                    started_at=None if active else created_at,
                    finished_at=None if active else created_at,
                )
            )
        await entered.commit()

    async with unit_of_work as entered:
        first = await entered.execution_history.list_for_graph(
            WORKSPACE_ONE, graph_id, limit=2
        )
        assert first.next_cursor is not None
        second = await entered.execution_history.list_for_graph(
            WORKSPACE_ONE,
            graph_id,
            limit=2,
            cursor=first.next_cursor,
        )

    assert [item.execution.execution_id for item in first.items] == [
        execution_ids[2],
        execution_ids[1],
    ]
    assert [item.execution.execution_id for item in second.items] == [execution_ids[0]]
    assert second.next_cursor is None


@pytest.mark.asyncio
async def test_durable_queue_claim_is_oldest_first_and_conditional(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    graph_ids = (
        UUID("00000000-0000-0000-0000-000000000211"),
        UUID("00000000-0000-0000-0000-000000000212"),
    )
    for graph_id in graph_ids:
        await _persist_graph_revisions(unit_of_work, graph_id, WORKSPACE_ONE)
    created_at = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
    execution_ids = (
        UUID("00000000-0000-7000-8000-000000000211"),
        UUID("00000000-0000-7000-8000-000000000212"),
    )
    execution_pairs = tuple(zip(execution_ids, graph_ids, strict=True))
    async with unit_of_work as entered:
        for execution_id, graph_id in reversed(execution_pairs):
            await entered.execution_history.add(
                GraphExecution(
                    workspace_id=WORKSPACE_ONE,
                    execution_id=execution_id,
                    graph_id=graph_id,
                    graph_revision=1,
                    status="queued",
                    submitted_request={"nodes": []},
                    created_at=created_at,
                )
            )
        await entered.commit()

    started_at = created_at + timedelta(seconds=5)
    async with unit_of_work as entered:
        queued = await entered.execution_history.list_queued()
        claimed = await entered.execution_history.claim_queued(
            WORKSPACE_ONE,
            execution_ids[0],
            started_at=started_at,
        )
        duplicate_claim = await entered.execution_history.claim_queued(
            WORKSPACE_ONE,
            execution_ids[0],
            started_at=started_at,
        )
        await entered.commit()

    assert tuple(execution.execution_id for execution in queued) == execution_ids
    assert claimed is True
    assert duplicate_claim is False
    async with unit_of_work as entered:
        detail = await entered.execution_history.get(
            WORKSPACE_ONE,
            execution_ids[0],
        )
    assert detail is not None
    assert detail.execution.status == "running"
    assert detail.execution.started_at == started_at


@pytest.mark.asyncio
async def test_filters_select_executions_without_filtering_detail_node_rows(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    graph_id = UUID("00000000-0000-0000-0000-000000000301")
    await _persist_graph_revisions(unit_of_work, graph_id, WORKSPACE_ONE)
    base_time = datetime(2026, 7, 18, 10, 0, tzinfo=UTC)
    completed_id = UUID("00000000-0000-0000-0000-000000000302")
    queued_id = UUID("00000000-0000-0000-0000-000000000303")
    unrelated_id = UUID("00000000-0000-0000-0000-000000000304")
    cancelled_id = UUID("00000000-0000-0000-0000-000000000305")
    completed = GraphExecution(
        workspace_id=WORKSPACE_ONE,
        execution_id=completed_id,
        graph_id=graph_id,
        graph_revision=1,
        status="succeeded",
        scope="selected",
        requested_node_ids=("target", "other"),
        created_at=base_time,
        started_at=base_time,
        finished_at=base_time + timedelta(seconds=1),
    )
    queued = GraphExecution(
        workspace_id=WORKSPACE_ONE,
        execution_id=queued_id,
        graph_id=graph_id,
        graph_revision=2,
        status="queued",
        scope="selected",
        requested_node_ids=("target",),
        created_at=base_time + timedelta(minutes=1),
    )
    unrelated = GraphExecution(
        workspace_id=WORKSPACE_ONE,
        execution_id=unrelated_id,
        graph_id=graph_id,
        graph_revision=1,
        status="failed",
        scope="selected",
        requested_node_ids=("other",),
        created_at=base_time + timedelta(minutes=2),
        started_at=base_time + timedelta(minutes=2),
        finished_at=base_time + timedelta(minutes=2, seconds=30),
    )
    cancelled = GraphExecution(
        workspace_id=WORKSPACE_ONE,
        execution_id=cancelled_id,
        graph_id=graph_id,
        graph_revision=1,
        status="cancelled",
        scope="selected",
        requested_node_ids=("target",),
        created_at=base_time + timedelta(minutes=3),
        finished_at=base_time + timedelta(minutes=3, seconds=1),
    )
    async with unit_of_work as entered:
        for execution in (completed, queued, unrelated, cancelled):
            await entered.execution_history.add(execution)
        with pytest.raises(ValueError, match="did not request node 'unexpected'"):
            await entered.execution_history.add_node_result(
                GraphExecutionNodeResult(
                    workspace_id=WORKSPACE_ONE,
                    execution_id=completed_id,
                    node_id="unexpected",
                    position=2,
                    status="skipped",
                    outputs={},
                    completed_at=base_time + timedelta(seconds=1),
                )
            )
        for position, node_id in enumerate(("target", "other")):
            await entered.execution_history.add_node_result(
                GraphExecutionNodeResult(
                    workspace_id=WORKSPACE_ONE,
                    execution_id=completed_id,
                    node_id=node_id,
                    position=position,
                    status="succeeded",
                    outputs={},
                    completed_at=base_time + timedelta(seconds=1),
                )
            )
        await entered.commit()

    async with unit_of_work as entered:
        target_page = await entered.execution_history.list_for_graph(
            WORKSPACE_ONE,
            graph_id,
            limit=10,
            node_id="target",
        )
        revision_page = await entered.execution_history.list_for_graph(
            WORKSPACE_ONE,
            graph_id,
            limit=10,
            graph_revision=2,
        )
        succeeded_page = await entered.execution_history.list_for_graph(
            WORKSPACE_ONE,
            graph_id,
            limit=10,
            status="succeeded",
        )
        detail = await entered.execution_history.get(WORKSPACE_ONE, completed_id)

    assert [item.execution.execution_id for item in target_page.items] == [
        cancelled_id,
        queued_id,
        completed_id,
    ]
    assert [item.execution.execution_id for item in revision_page.items] == [queued_id]
    assert [item.execution.execution_id for item in succeeded_page.items] == [
        completed_id
    ]
    assert detail is not None
    assert [result.node_id for result in detail.node_results] == ["target", "other"]


@pytest.mark.asyncio
async def test_restart_recovery_fails_only_active_executions(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    statuses: tuple[GraphExecutionStatus, ...] = (
        "queued",
        "running",
        "cancelling",
        "succeeded",
    )
    # One graph per execution: each workspace-owned graph admits at most one
    # active (queued/running/cancelling) execution at a time.
    first_workspace_graph_ids = [
        UUID(f"00000000-0000-0000-0000-{index:012d}") for index in range(401, 405)
    ]
    second_workspace_graph_ids = [
        UUID(f"00000000-0000-0000-0000-{index:012d}") for index in range(411, 415)
    ]
    for graph_id in first_workspace_graph_ids:
        await _persist_graph_revisions(unit_of_work, graph_id, WORKSPACE_ONE)
    for graph_id in second_workspace_graph_ids:
        await _persist_graph_revisions(unit_of_work, graph_id, WORKSPACE_TWO)
    created_at = datetime(2026, 7, 18, 11, 0, tzinfo=UTC)
    execution_ids = [
        UUID(f"00000000-0000-0000-0000-{index:012d}") for index in range(410, 414)
    ]
    second_workspace_execution_ids = [
        UUID(f"00000000-0000-0000-0000-{index:012d}") for index in range(420, 424)
    ]
    async with unit_of_work as entered:
        for graph_id, execution_id, status in zip(
            first_workspace_graph_ids, execution_ids, statuses, strict=True
        ):
            terminal = status == "succeeded"
            await entered.execution_history.add(
                GraphExecution(
                    workspace_id=WORKSPACE_ONE,
                    execution_id=execution_id,
                    graph_id=graph_id,
                    graph_revision=2,
                    status=status,
                    created_at=created_at,
                    started_at=(created_at if status != "queued" else None),
                    finished_at=(created_at if terminal else None),
                )
            )
        for graph_id, execution_id, status in zip(
            second_workspace_graph_ids,
            second_workspace_execution_ids,
            statuses,
            strict=True,
        ):
            terminal = status == "succeeded"
            await entered.execution_history.add(
                GraphExecution(
                    workspace_id=WORKSPACE_TWO,
                    execution_id=execution_id,
                    graph_id=graph_id,
                    graph_revision=2,
                    status=status,
                    created_at=created_at,
                    started_at=(created_at if status != "queued" else None),
                    finished_at=(created_at if terminal else None),
                )
            )
        await entered.commit()

    recovered_at = created_at + timedelta(minutes=5)
    async with unit_of_work as entered:
        interrupted = await entered.execution_history.interrupt_started(
            finished_at=recovered_at,
            error="API restarted before execution completed",
        )
        await entered.commit()

    async with unit_of_work as entered:
        details = [
            await entered.execution_history.get(WORKSPACE_ONE, execution_id)
            for execution_id in execution_ids
        ]
        second_workspace_details = [
            await entered.execution_history.get(WORKSPACE_TWO, execution_id)
            for execution_id in second_workspace_execution_ids
        ]

    assert len(interrupted) == 4
    assert all(detail is not None for detail in details)
    assert [detail.execution.status for detail in details if detail is not None] == [
        "queued",
        "failed",
        "failed",
        "succeeded",
    ]
    assert details[1] is not None
    assert details[1].execution.finished_at == recovered_at
    assert details[1].execution.error == "API restarted before execution completed"
    assert [
        detail.execution.status
        for detail in second_workspace_details
        if detail is not None
    ] == ["queued", "failed", "failed", "succeeded"]


@pytest.mark.asyncio
async def test_deleting_graph_cascades_history_and_preserves_artifacts(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    graph_id = UUID("00000000-0000-0000-0000-000000000501")
    execution_id = UUID("00000000-0000-0000-0000-000000000502")
    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ONE,
        id=UUID("00000000-0000-0000-0000-000000000503"),
        artifact_type="scalar.integer",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": 5},
    )
    await _persist_graph_revisions(unit_of_work, graph_id, WORKSPACE_ONE)
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.execution_history.add(
            GraphExecution(
                workspace_id=WORKSPACE_ONE,
                execution_id=execution_id,
                graph_id=graph_id,
                graph_revision=1,
                status="queued",
            )
        )
        await entered.commit()
    async with unit_of_work as entered:
        graph = await entered.graphs.get(WORKSPACE_ONE, graph_id)
        assert graph is not None
        await entered.graphs.remove(WORKSPACE_ONE, graph)
        await entered.commit()

    async with unit_of_work as entered:
        assert await entered.execution_history.get(WORKSPACE_ONE, execution_id) is None
        assert await entered.artifacts.get(WORKSPACE_ONE, artifact.id) is not None
    async with database.sessions() as session:
        assert (
            await session.scalar(select(schema.graph_execution_nodes.c.execution_id))
            is None
        )
        assert (
            await session.scalar(select(schema.graph_executions.c.execution_id)) is None
        )


@pytest.mark.asyncio
async def test_one_active_execution_per_graph_is_database_enforced(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    graph_id = UUID("00000000-0000-0000-0000-000000000601")
    second_workspace_same_graph_id = UUID("00000000-0000-0000-0000-000000000602")
    await _persist_graph_revisions(unit_of_work, graph_id, WORKSPACE_ONE)
    await _persist_graph_revisions(
        unit_of_work, second_workspace_same_graph_id, WORKSPACE_TWO
    )

    async def _start(
        workspace_id: UUID,
        target_graph_id: UUID,
        execution_id: UUID,
    ) -> None:
        async with unit_of_work as entered:
            await entered.execution_history.add(
                GraphExecution(
                    workspace_id=workspace_id,
                    execution_id=execution_id,
                    graph_id=target_graph_id,
                    graph_revision=2,
                    status="queued",
                    created_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
                )
            )
            await entered.commit()

    # No active execution: a queued start is accepted.
    first_execution_id = UUID("00000000-0000-0000-0000-000000000603")
    await _start(WORKSPACE_ONE, graph_id, first_execution_id)

    # A second queued/running/cancelling start for the same workspace graph is
    # rejected by the partial unique index, reporting the existing execution.
    for status in ("queued", "running", "cancelling"):
        conflicting_id = UUID("00000000-0000-0000-0000-000000000604")
        with pytest.raises(CollaborationActiveExecutionError) as exc:
            async with unit_of_work as entered:
                await entered.execution_history.add(
                    GraphExecution(
                        workspace_id=WORKSPACE_ONE,
                        execution_id=conflicting_id,
                        graph_id=graph_id,
                        graph_revision=2,
                        status=status,  # type: ignore[arg-type]
                        started_at=(
                            datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
                            if status != "queued"
                            else None
                        ),
                        created_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
                    )
                )
                await entered.commit()
        assert exc.value.execution_id == first_execution_id

    # Different graphs in the same workspace run concurrently.
    other_graph_id = UUID("00000000-0000-0000-0000-000000000605")
    await _persist_graph_revisions(unit_of_work, other_graph_id, WORKSPACE_ONE)
    await _start(
        WORKSPACE_ONE,
        other_graph_id,
        UUID("00000000-0000-0000-0000-000000000606"),
    )

    # The same graph id in a different workspace does not collide.
    await _start(
        WORKSPACE_TWO,
        second_workspace_same_graph_id,
        UUID("00000000-0000-0000-0000-000000000607"),
    )

    # A terminal transition releases the constraint; a new execution starts.
    async with unit_of_work as entered:
        execution = await entered.execution_history.get(
            WORKSPACE_ONE, first_execution_id
        )
        assert execution is not None
        terminal = replace(
            execution.execution,
            status="succeeded",
            finished_at=datetime(2026, 7, 18, 12, 1, tzinfo=UTC),
        )
        await entered.execution_history.update(terminal)
        await entered.commit()
    released_execution_id = UUID("00000000-0000-0000-0000-000000000608")
    await _start(WORKSPACE_ONE, graph_id, released_execution_id)


@pytest.mark.asyncio
async def test_concurrent_starts_race_on_the_database_constraint(
    database: Database,
) -> None:
    graph_id = UUID("00000000-0000-0000-0000-000000000651")
    first_unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    await _persist_graph_revisions(first_unit_of_work, graph_id, WORKSPACE_ONE)
    created_at = datetime(2026, 7, 18, 13, 0, tzinfo=UTC)

    async def _race(execution_id: UUID) -> str:
        unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
        try:
            async with unit_of_work as entered:
                await entered.execution_history.add(
                    GraphExecution(
                        workspace_id=WORKSPACE_ONE,
                        execution_id=execution_id,
                        graph_id=graph_id,
                        graph_revision=2,
                        status="queued",
                        created_at=created_at,
                    )
                )
                await entered.commit()
            return "accepted"
        except CollaborationActiveExecutionError:
            return "conflict"

    outcomes = await asyncio.gather(
        _race(UUID("00000000-0000-0000-0000-000000000652")),
        _race(UUID("00000000-0000-0000-0000-000000000653")),
    )

    assert sorted(outcomes) == ["accepted", "conflict"]


@pytest.mark.asyncio
async def test_unified_node_rows_round_trip_partial_executions(
    database: Database,
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    graph_id = UUID("00000000-0000-0000-0000-000000000701")
    execution_id = UUID("00000000-0000-0000-0000-000000000702")
    await _persist_graph_revisions(unit_of_work, graph_id, WORKSPACE_ONE)
    base_time = datetime(2026, 7, 18, 14, 0, tzinfo=UTC)
    execution = GraphExecution(
        workspace_id=WORKSPACE_ONE,
        execution_id=execution_id,
        graph_id=graph_id,
        graph_revision=2,
        status="running",
        requested_node_ids=("alpha", "beta", "gamma"),
        created_at=base_time,
        started_at=base_time,
    )
    async with unit_of_work as entered:
        await entered.execution_history.add(execution)
        await entered.commit()

    # The execution is readable before any node result exists.
    async with unit_of_work as entered:
        detail = await entered.execution_history.get(WORKSPACE_ONE, execution_id)
        page = await entered.execution_history.list_for_graph(
            WORKSPACE_ONE, graph_id, limit=10
        )
    assert detail is not None
    assert detail.execution.requested_node_ids == ("alpha", "beta", "gamma")
    assert detail.node_results == ()
    assert page.items[0].node_count == 0
    assert page.items[0].artifact_count == 0

    artifact = ArtifactObject(
        workspace_id=WORKSPACE_ONE,
        id=UUID("00000000-0000-0000-0000-000000000703"),
        artifact_type="scalar.text",
        schema_version=1,
        content_type="application/json",
        storage_backend="inline",
        inline_payload={"value": "out"},
    )
    skipped_result = GraphExecutionNodeResult(
        workspace_id=WORKSPACE_ONE,
        execution_id=execution_id,
        node_id="gamma",
        position=0,
        status="skipped",
        outputs={},
        completed_at=base_time + timedelta(seconds=1),
    )
    async with unit_of_work as entered:
        await entered.artifacts.add(artifact)
        await entered.execution_history.add_node_result(
            GraphExecutionNodeResult(
                workspace_id=WORKSPACE_ONE,
                execution_id=execution_id,
                node_id="alpha",
                position=1,
                status="succeeded",
                outputs={"text": artifact.ref()},
                completed_at=base_time + timedelta(seconds=2),
            )
        )
        await entered.execution_history.add_node_result(skipped_result)
        await entered.commit()

    # A result can be recorded only once per requested node.
    with pytest.raises(ObjectAlreadyExistsError):
        async with unit_of_work as entered:
            await entered.execution_history.add_node_result(skipped_result)
            await entered.commit()

    async with unit_of_work as entered:
        detail = await entered.execution_history.get(WORKSPACE_ONE, execution_id)
        page = await entered.execution_history.list_for_graph(
            WORKSPACE_ONE, graph_id, limit=10
        )
    async with database.sessions() as session:
        pending_rows = (
            (
                await session.execute(
                    select(schema.graph_execution_nodes.c.node_id)
                    .where(schema.graph_execution_nodes.c.result_status.is_(None))
                    .order_by(schema.graph_execution_nodes.c.position.asc())
                )
            )
            .scalars()
            .all()
        )

    assert detail is not None
    assert detail.execution.requested_node_ids == ("alpha", "beta", "gamma")
    # Result order follows the terminal-result position (completion order),
    # not the request position.
    assert [result.node_id for result in detail.node_results] == ["gamma", "alpha"]
    assert detail.node_results[1].position == 1
    assert detail.node_results[1].outputs["text"].artifact_id == artifact.id
    assert page.items[0].node_count == 2
    assert page.items[0].artifact_count == 1
    # Partially completed executions retain pending requested nodes.
    assert list(pending_rows) == ["beta"]

    # Workspace isolation: the same ids are invisible from another workspace.
    async with unit_of_work as entered:
        foreign_detail = await entered.execution_history.get(
            WORKSPACE_TWO, execution_id
        )
        foreign_page = await entered.execution_history.list_for_graph(
            WORKSPACE_TWO, graph_id, limit=10
        )
    assert foreign_detail is None
    assert foreign_page.items == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("execution_count", [0, 1, 5, 401])
@pytest.mark.parametrize("operation", ["queue", "interrupt"])
async def test_recovery_batches_nodes_and_preserves_execution_contracts(
    database: Database,
    execution_count: int,
    operation: Literal["queue", "interrupt"],
) -> None:
    unit_of_work = SqlAlchemyUnitOfWork(database.sessions)
    created_at = datetime(2026, 9, 1, tzinfo=UTC)
    expected: list[GraphExecution] = []
    for index in range(execution_count):
        workspace_id = WORKSPACE_ONE if index % 2 == 0 else WORKSPACE_TWO
        graph_id = UUID(int=10000 + index)
        await _persist_graph_revisions(unit_of_work, graph_id, workspace_id)
        status: GraphExecutionStatus = "queued"
        if operation == "interrupt":
            status = "running" if index % 2 == 0 else "cancelling"
        expected.append(
            GraphExecution(
                workspace_id=workspace_id,
                execution_id=UUID(int=20000 + index),
                graph_id=graph_id,
                graph_revision=2,
                status=status,
                requested_node_ids=()
                if index % 3 == 0
                else (f"z-{index}", f"a-{index}"),
                submitted_request={"marker": index},
                created_at=created_at + timedelta(seconds=index // 2),
                started_at=None
                if status == "queued"
                else created_at + timedelta(seconds=index // 2),
            )
        )
    async with unit_of_work as entered:
        for execution in reversed(expected):
            await entered.execution_history.add(execution)
        await entered.commit()

    statements: list[str] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(database.engine.sync_engine, "before_cursor_execute", record_statement)
    finished_at = created_at + timedelta(hours=1)
    try:
        async with unit_of_work as entered:
            if operation == "queue":
                actual = await entered.execution_history.list_queued()
            else:
                actual = await entered.execution_history.interrupt_started(
                    finished_at=finished_at,
                    error="Restarted",
                )
            await entered.commit()
    finally:
        event.remove(
            database.engine.sync_engine, "before_cursor_execute", record_statement
        )

    assert len(statements) == 1 + (execution_count + 399) // 400
    if operation == "queue":
        assert actual == tuple(expected)
    else:
        assert sorted(actual, key=lambda execution: execution.execution_id) == expected
        async with unit_of_work as entered:
            for original in expected:
                detail = await entered.execution_history.get(
                    original.workspace_id,
                    original.execution_id,
                )
                assert detail is not None
                assert detail.execution == replace(
                    original,
                    status="failed",
                    finished_at=finished_at,
                    error="Restarted",
                )
