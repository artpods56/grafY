from datetime import UTC, datetime
from uuid import UUID

import pytest

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.domain.execution_history import (
    GraphExecution,
    GraphExecutionNodeResult,
    GraphExecutionStatus,
)
from grafy_core.domain.errors import NotFoundError


WORKSPACE_ONE = UUID("00000000-0000-0000-0000-000000000101")
WORKSPACE_TWO = UUID("00000000-0000-0000-0000-000000000102")


def test_execution_history_models_validate_lifecycle_and_count_artifacts() -> None:
    with pytest.raises(ValueError, match="requires finished_at"):
        GraphExecution(
            workspace_id=WORKSPACE_ONE,
            execution_id=UUID("00000000-0000-0000-0000-000000000001"),
            graph_id=UUID("00000000-0000-0000-0000-000000000002"),
            graph_revision=1,
            status="failed",
        )

    first = ArtifactRef(
        artifact_id=UUID("00000000-0000-0000-0000-000000000010"),
        artifact_type="scalar.integer",
        schema_version=1,
    )
    sequence = ArtifactRefSequence(
        sequence_id=UUID("00000000-0000-0000-0000-000000000011"),
        artifact_type="scalar.integer",
        schema_version=1,
        item_refs=[
            first,
            first.model_copy(
                update={"artifact_id": UUID("00000000-0000-0000-0000-000000000012")}
            ),
        ],
    )
    result = GraphExecutionNodeResult(
        execution_id=UUID("00000000-0000-0000-0000-000000000001"),
        workspace_id=WORKSPACE_ONE,
        node_id="  extract  ",
        position=0,
        status="succeeded",
        outputs={"single": first, "many": sequence},
    )

    assert result.node_id == "extract"
    assert result.artifact_count == 3
    assert (
        GraphExecutionNodeResult.outputs_from_storage(result.storage_envelopes())
        == result.outputs
    )


@pytest.mark.asyncio
async def test_in_memory_execution_history_obeys_commit_and_node_filter_semantics() -> (
    None
):
    unit_of_work = InMemoryUnitOfWork()
    execution = GraphExecution(
        execution_id=UUID("00000000-0000-0000-0000-000000000021"),
        workspace_id=WORKSPACE_ONE,
        graph_id=UUID("00000000-0000-0000-0000-000000000022"),
        graph_revision=3,
        status="queued",
        scope="selected-with-dependencies",
        requested_node_ids=("source", "target"),
        created_at=datetime(2026, 7, 18, 8, 0, tzinfo=UTC),
    )

    async with unit_of_work as entered:
        await entered.execution_history.add(execution)
        await entered.commit()
    async with unit_of_work as entered:
        page = await entered.execution_history.list_for_graph(
            WORKSPACE_ONE,
            execution.graph_id,
            limit=10,
            node_id="target",
        )
        missing = await entered.execution_history.list_for_graph(
            WORKSPACE_ONE,
            execution.graph_id,
            limit=10,
            node_id="not-requested",
        )

    assert [item.execution.execution_id for item in page.items] == [
        execution.execution_id
    ]
    assert page.items[0].node_count == 0
    assert missing.items == ()


@pytest.mark.asyncio
async def test_in_memory_queued_order_uses_execution_id_as_stable_time_tie_breaker() -> (
    None
):
    unit_of_work = InMemoryUnitOfWork()
    created_at = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
    execution_ids = (
        UUID("00000000-0000-0000-0000-000000000071"),
        UUID("00000000-0000-0000-0000-000000000072"),
    )
    graph_ids = (
        UUID("00000000-0000-0000-0000-000000000171"),
        UUID("00000000-0000-0000-0000-000000000172"),
    )
    async with unit_of_work as entered:
        for execution_id, graph_id in reversed(
            tuple(zip(execution_ids, graph_ids, strict=True))
        ):
            await entered.execution_history.add(
                GraphExecution(
                    workspace_id=WORKSPACE_ONE,
                    execution_id=execution_id,
                    graph_id=graph_id,
                    graph_revision=1,
                    status="queued",
                    created_at=created_at,
                    submitted_request={"nodes": []},
                )
            )
        await entered.commit()
    async with unit_of_work as entered:
        queued = await entered.execution_history.list_queued()

    assert tuple(execution.execution_id for execution in queued) == execution_ids


@pytest.mark.asyncio
async def test_in_memory_execution_history_rejects_unrequested_node_results() -> None:
    unit_of_work = InMemoryUnitOfWork()
    execution = GraphExecution(
        execution_id=UUID("00000000-0000-0000-0000-000000000031"),
        workspace_id=WORKSPACE_ONE,
        graph_id=UUID("00000000-0000-0000-0000-000000000032"),
        graph_revision=1,
        status="queued",
        requested_node_ids=("requested",),
    )
    async with unit_of_work as entered:
        await entered.execution_history.add(execution)
        with pytest.raises(ValueError, match="did not request node 'unexpected'"):
            await entered.execution_history.add_node_result(
                GraphExecutionNodeResult(
                    workspace_id=WORKSPACE_ONE,
                    execution_id=execution.execution_id,
                    node_id="unexpected",
                    position=0,
                    status="skipped",
                    outputs={},
                )
            )


@pytest.mark.asyncio
async def test_in_memory_execution_identity_is_global_but_reads_are_workspace_scoped() -> (
    None
):
    unit_of_work = InMemoryUnitOfWork()
    execution = GraphExecution(
        workspace_id=WORKSPACE_ONE,
        execution_id=UUID("00000000-0000-0000-0000-000000000041"),
        graph_id=UUID("00000000-0000-0000-0000-000000000042"),
        graph_revision=1,
        status="queued",
    )

    async with unit_of_work as entered:
        await entered.execution_history.add(execution)
        assert (
            await entered.execution_history.get(
                WORKSPACE_TWO,
                execution.execution_id,
            )
            is None
        )
        await entered.commit()

    async with unit_of_work as entered:
        with pytest.raises(NotFoundError, match="Graph execution"):
            await entered.execution_history.update(
                GraphExecution(
                    workspace_id=WORKSPACE_TWO,
                    execution_id=execution.execution_id,
                    graph_id=execution.graph_id,
                    graph_revision=1,
                    status="queued",
                )
            )


@pytest.mark.asyncio
async def test_in_memory_restart_preserves_queued_and_interrupts_started() -> None:
    unit_of_work = InMemoryUnitOfWork()
    created_at = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    execution_cases: tuple[tuple[UUID, GraphExecutionStatus], ...] = (
        (WORKSPACE_ONE, "queued"),
        (WORKSPACE_TWO, "running"),
        (WORKSPACE_ONE, "cancelling"),
        (WORKSPACE_TWO, "succeeded"),
    )
    executions = tuple(
        GraphExecution(
            workspace_id=workspace_id,
            execution_id=UUID(f"00000000-0000-0000-0000-{index:012d}"),
            graph_id=UUID(f"00000000-0000-0000-0000-{index + 100:012d}"),
            graph_revision=1,
            status=status,
            created_at=created_at,
            started_at=(created_at if status != "queued" else None),
            finished_at=(created_at if status == "succeeded" else None),
        )
        for index, (workspace_id, status) in enumerate(
            execution_cases,
            start=1,
        )
    )
    async with unit_of_work as entered:
        for execution in executions:
            await entered.execution_history.add(execution)
        interrupted = await entered.execution_history.interrupt_started(
            finished_at=created_at.replace(hour=13),
            error="startup recovery",
        )
        await entered.commit()

    assert [execution.status for execution in interrupted] == [
        "running",
        "cancelling",
    ]
    async with unit_of_work as entered:
        details = [
            await entered.execution_history.get(
                execution.workspace_id,
                execution.execution_id,
            )
            for execution in executions
        ]
    assert [detail.execution.status for detail in details if detail is not None] == [
        "queued",
        "failed",
        "failed",
        "succeeded",
    ]


def _execution(
    status: str,
    *,
    finished_at: datetime | None = None,
) -> GraphExecution:
    return GraphExecution(
        workspace_id=WORKSPACE_ONE,
        execution_id=UUID("00000000-0000-0000-0000-000000000001"),
        graph_id=UUID("00000000-0000-0000-0000-000000000002"),
        graph_revision=1,
        status=status,  # type: ignore[arg-type]
        finished_at=finished_at,
    )


def test_durable_transition_table_enforces_legal_lifecycle() -> None:
    """Explicit transitions keep status, timestamps, workflow id, and error
    correlated; illegal sequences are rejected."""

    # queued -> running stamps the start time.
    running = _execution("queued")
    running.transition_to_running()
    assert running.status == "running"
    assert running.started_at is not None
    assert running.finished_at is None
    assert running.error is None

    # running -> terminal succeeded carries workflow id and finish time.
    succeeded = _execution("running")
    succeeded.transition_to_terminal(
        "succeeded",
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000099"),
        error=None,
    )
    assert succeeded.status == "succeeded"
    assert succeeded.finished_at is not None
    assert succeeded.workflow_run_id == UUID("00000000-0000-0000-0000-000000000099")

    # running -> failed terminal carries error and finish time together.
    failed = _execution("running")
    failed.transition_to_terminal(
        "failed",
        workflow_run_id=None,
        error="boom",
    )
    assert failed.status == "failed"
    assert failed.finished_at is not None
    assert failed.error == "boom"

    # queued -> cancelling -> cancelled.
    cancelling = _execution("queued")
    cancelling.transition_to_cancelling()
    assert cancelling.status == "cancelling"
    cancelling.transition_to_terminal(
        "cancelled",
        workflow_run_id=None,
        error=None,
    )
    assert cancelling.status == "cancelled"
    assert cancelling.finished_at is not None

    # Illegal: starting from running, cancel from terminal, cancelling to success.
    with pytest.raises(ValueError, match="cannot start from"):
        _execution("running").transition_to_running()
    with pytest.raises(ValueError, match="cannot cancel from"):
        GraphExecution(
            workspace_id=WORKSPACE_ONE,
            execution_id=UUID("00000000-0000-0000-0000-000000000001"),
            graph_id=UUID("00000000-0000-0000-0000-000000000002"),
            graph_revision=1,
            status="succeeded",
            created_at=datetime(2026, 7, 18, 11, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 18, 13, 0, tzinfo=UTC),
        ).transition_to_cancelling()
    with pytest.raises(ValueError, match="only complete as cancelled"):
        _execution("cancelling").transition_to_terminal(
            "succeeded",
            workflow_run_id=None,
            error=None,
        )


def test_terminal_transition_carries_one_complete_outcome() -> None:
    """A terminal record always carries finish time plus workflow identity and
    error together (exactly one typed outcome)."""

    terminal = _execution("running")
    terminal.transition_to_terminal(
        "failed",
        workflow_run_id=UUID("00000000-0000-0000-0000-000000000101"),
        error="boom",
    )
    assert terminal.status == "failed"
    assert terminal.finished_at is not None
    assert terminal.workflow_run_id is not None
    assert terminal.error == "boom"

    # A non-terminal execution cannot be constructed as finished (post_init).
    with pytest.raises(ValueError, match="cannot have finished_at"):
        GraphExecution(
            workspace_id=WORKSPACE_ONE,
            execution_id=UUID("00000000-0000-0000-0000-000000000002"),
            graph_id=UUID("00000000-0000-0000-0000-000000000003"),
            graph_revision=1,
            status="queued",
            created_at=datetime(2026, 7, 18, 11, 0, tzinfo=UTC),
            finished_at=datetime(2026, 7, 18, 12, 0, tzinfo=UTC),
        )
