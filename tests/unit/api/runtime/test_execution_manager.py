import asyncio
from datetime import UTC, datetime
import logging
from pathlib import Path
from typing import Annotated, cast, final, override
from uuid import UUID, uuid4

import pytest
from pydantic import StrictInt, ValidationError

from grafy_core.artifacts import NoConfig, NodeInput, NodeOutput
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.artifacts import JsonObject
from grafy_core.application.plugin_releases import PluginReleaseService
from grafy_core.domain.execution_history import (
    GraphExecution,
    GraphExecutionScope,
    GraphExecutionStatus,
)
from grafy_core.domain.errors import NotFoundError
from grafy_core.nodes import (
    MAX_NODE_PROGRESS_COUNTER,
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    UserFacingNodeError,
)
from grafy_core.artifact_contracts import INTEGER_VALUE
from grafy_core.plugins import Plugin

from grafy_api.execution.events import (
    ExecutionStatusEvent,
    NodeProgressEvent,
    NodeStatusEvent,
)
from grafy_api.execution.requests import (
    RunEdgeRequest,
    RunNodeRequest,
    RunRequest,
)
from tests.support.system_plugins import (
    TEST_SYSTEM_PLUGINS,
    build_selected_system_plugin_deployment,
)
from grafy_api.services.composition import build_workbench_components
from grafy_api.execution.control import RunExecutionControl
from grafy_api.execution.admission import (
    ExecutionAdmissionLimiter,
    RunExecutionCapacityError,
    RunExecutionQueueFullError,
)
from grafy_api.execution.manager import (
    RunExecutionIdempotencyConflictError,
    RunExecutionManager,
    RunExecutionSnapshot,
)
from grafy_api.execution.models import GraphExecutionResult
from grafy_api.execution.run_graph import RunGraph
from grafy_api.execution.history import ExecutionHistoryService


EXECUTION_TEST_PLUGIN = Plugin(
    slug="test.execution-control",
    title="Execution control test plugin",
)
EXECUTION_TEST_PLUGIN.register_artifact_type_dependency(INTEGER_VALUE)
_started: dict[str, asyncio.Event] = {}
_release: dict[str, asyncio.Event] = {}
_downstream_calls: list[str] = []
_progress_contexts: list[NodeExecutionContext] = []
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


async def _wait_at_gate(context: NodeExecutionContext) -> None:
    node_id = context.node_id
    assert node_id is not None
    _started[node_id].set()
    await _release[node_id].wait()


class FirstGateInput(NodeInput):
    pass


class FirstGateOutput(NodeOutput):
    value: Annotated[StrictInt, OutPort(INTEGER_VALUE)]


@EXECUTION_TEST_PLUGIN.node(
    operator_id="test.execution.first_gate",
    version=1,
    title="First gate",
)
@final
class FirstGateNode(Node[NoConfig, FirstGateInput, FirstGateOutput]):
    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        _inputs: FirstGateInput,
        /,
    ) -> FirstGateOutput:
        await _wait_at_gate(context)
        return FirstGateOutput(value=1)


class SecondGateInput(NodeInput):
    value: Annotated[StrictInt, InPort(INTEGER_VALUE)]


class SecondGateOutput(NodeOutput):
    value: Annotated[StrictInt, OutPort(INTEGER_VALUE)]


@EXECUTION_TEST_PLUGIN.node(
    operator_id="test.execution.second_gate",
    version=1,
    title="Second gate",
)
@final
class SecondGateNode(Node[NoConfig, SecondGateInput, SecondGateOutput]):
    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: SecondGateInput,
        /,
    ) -> SecondGateOutput:
        await _wait_at_gate(context)
        return SecondGateOutput(value=inputs.value + 1)


class RecordingInput(NodeInput):
    value: Annotated[StrictInt, InPort(INTEGER_VALUE)]


class RecordingOutput(NodeOutput):
    value: Annotated[StrictInt, OutPort(INTEGER_VALUE)]


@EXECUTION_TEST_PLUGIN.node(
    operator_id="test.execution.recording",
    version=1,
    title="Recording downstream",
)
@final
class RecordingNode(Node[NoConfig, RecordingInput, RecordingOutput]):
    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: RecordingInput,
        /,
    ) -> RecordingOutput:
        assert context.node_id is not None
        _downstream_calls.append(context.node_id)
        return RecordingOutput(value=inputs.value + 1)


class ProgressInput(NodeInput):
    value: Annotated[StrictInt, InPort(INTEGER_VALUE)]


class ProgressOutput(NodeOutput):
    value: Annotated[StrictInt, OutPort(INTEGER_VALUE)]


@EXECUTION_TEST_PLUGIN.function_node(
    operator_id="test.execution.progress",
    version=1,
    title="Progress reporter",
)
async def report_progress(
    context: NodeExecutionContext,
    _config: NoConfig,
    inputs: ProgressInput,
) -> ProgressOutput:
    _progress_contexts.append(context)
    invocation_index = context.invocation_index
    await context.progress(
        "Preparing mapped item",
        current=None if invocation_index is None else invocation_index + 1,
        total=3,
    )
    return ProgressOutput(value=inputs.value)


class FailingInput(NodeInput):
    pass


class FailingOutput(NodeOutput):
    value: Annotated[StrictInt, OutPort(INTEGER_VALUE)]


@EXECUTION_TEST_PLUGIN.node(
    operator_id="test.execution.failure",
    version=1,
    title="Failing node",
)
@final
class FailingNode(Node[NoConfig, FailingInput, FailingOutput]):
    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: NoConfig,
        _inputs: FailingInput,
        /,
    ) -> FailingOutput:
        raise UserFacingNodeError("controlled node failure")


SYSTEM_DEPLOYMENT = build_selected_system_plugin_deployment(
    (*TEST_SYSTEM_PLUGINS, EXECUTION_TEST_PLUGIN),
)


def _pin_system_plugins(request: RunRequest) -> RunRequest:
    return request.model_copy(
        update={"nodes": [SYSTEM_DEPLOYMENT.pin_node(node) for node in request.nodes]}
    )


class CancellationWrappingRunGraph(RunGraph):
    def __init__(self) -> None:
        self.started = asyncio.Event()

    @override
    async def run(
        self,
        workspace_id: UUID,
        request: RunRequest,
        control: RunExecutionControl | None = None,
    ) -> GraphExecutionResult:
        del workspace_id, request, control
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as exc:
            raise RuntimeError("wrapped execution cancellation") from exc
        raise AssertionError("unreachable")


class ControlledRunGraph(RunGraph):
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    @override
    async def run(
        self,
        workspace_id: UUID,
        request: RunRequest,
        control: RunExecutionControl | None = None,
    ) -> GraphExecutionResult:
        del workspace_id, request, control
        self.started.set()
        await self.release.wait()
        return GraphExecutionResult(
            workflow_run_id=uuid4(),
            status="succeeded",
            node_results=(),
            outputs={},
        )


class SequencedRunGraph(RunGraph):
    def __init__(self) -> None:
        self.started_order: list[UUID] = []
        self.started: dict[UUID, asyncio.Event] = {}
        self.release: dict[UUID, asyncio.Event] = {}

    def add(self, graph_id: UUID) -> None:
        self.started[graph_id] = asyncio.Event()
        self.release[graph_id] = asyncio.Event()

    @override
    async def run(
        self,
        workspace_id: UUID,
        request: RunRequest,
        control: RunExecutionControl | None = None,
    ) -> GraphExecutionResult:
        del workspace_id, control
        graph_id = request.graph_id
        assert graph_id is not None
        self.started_order.append(graph_id)
        self.started[graph_id].set()
        await self.release[graph_id].wait()
        return GraphExecutionResult(
            workflow_run_id=uuid4(),
            status="succeeded",
            node_results=(),
            outputs={},
        )


class ControlledExecutionHistory(ExecutionHistoryService):
    def __init__(self) -> None:
        super().__init__(InMemoryUnitOfWork(), None)
        self.transitions: list[str] = []
        self.cancelling_entered = asyncio.Event()
        self.allow_cancelling = asyncio.Event()
        self.allow_cancelling.set()
        self.complete_entered = asyncio.Event()
        self.allow_complete = asyncio.Event()
        self.allow_complete.set()
        self.complete_failures_remaining = 0
        self.complete_calls = 0
        self.executions_by_idempotency_key: dict[str, GraphExecution] = {}
        self.recovered_authorized = True

    @override
    async def create_queued(
        self,
        *,
        workspace_id: UUID,
        execution_id: UUID,
        graph_id: UUID,
        graph_revision: int,
        scope: GraphExecutionScope,
        requested_node_ids: tuple[str, ...],
        submitted_request: JsonObject,
        idempotency_key: str | None,
        submitted_by_actor_id: UUID | None,
    ) -> GraphExecution:
        self.transitions.append("queued")
        execution = GraphExecution(
            workspace_id=workspace_id,
            execution_id=execution_id,
            graph_id=graph_id,
            graph_revision=graph_revision,
            scope=scope,
            status="queued",
            requested_node_ids=requested_node_ids,
            submitted_request=submitted_request,
            idempotency_key=idempotency_key,
            submitted_by_actor_id=submitted_by_actor_id,
        )
        if idempotency_key is not None:
            self.executions_by_idempotency_key[idempotency_key] = execution
        return execution

    @override
    async def get_by_idempotency_key(
        self,
        workspace_id: UUID,
        idempotency_key: str,
    ) -> GraphExecution | None:
        execution = self.executions_by_idempotency_key.get(idempotency_key)
        if execution is None or execution.workspace_id != workspace_id:
            return None
        return execution

    @override
    async def mark_running(
        self,
        workspace_id: UUID,
        execution: GraphExecution,
    ) -> bool:
        del workspace_id
        execution.status = "running"
        execution.started_at = datetime.now(UTC)
        self.transitions.append("running")
        return True

    @override
    async def mark_cancelling(
        self,
        workspace_id: UUID,
        execution: GraphExecution,
    ) -> None:
        del workspace_id
        self.cancelling_entered.set()
        await self.allow_cancelling.wait()
        execution.status = "cancelling"
        self.transitions.append("cancelling")

    @override
    async def complete(
        self,
        workspace_id: UUID,
        execution: GraphExecution,
        *,
        status: GraphExecutionStatus,
        result: GraphExecutionResult | None,
        error: str | None,
    ) -> None:
        del workspace_id, result
        self.complete_calls += 1
        self.complete_entered.set()
        await self.allow_complete.wait()
        if self.complete_failures_remaining > 0:
            self.complete_failures_remaining -= 1
            raise RuntimeError("transient execution history failure")
        execution.status = status
        execution.finished_at = datetime.now(UTC)
        execution.error = error
        self.transitions.append(status)

    @override
    async def list_queued(self) -> tuple[GraphExecution, ...]:
        return ()

    @override
    async def can_dispatch_recovered(self, execution: GraphExecution) -> bool:
        del execution
        return self.recovered_authorized


class RecoveringExecutionHistory(ControlledExecutionHistory):
    def __init__(self, queued: tuple[GraphExecution, ...]) -> None:
        super().__init__()
        self.queued = queued

    @override
    async def list_queued(self) -> tuple[GraphExecution, ...]:
        return self.queued


def _manager(
    workspace: Path,
    *,
    terminal_retention: int = 100,
    event_capacity: int = 256,
    max_active_executions: int = 2,
) -> RunExecutionManager:
    components = build_workbench_components(
        plugin_registry=SYSTEM_DEPLOYMENT.registry,
        workspace=workspace,
        plugin_releases=cast(
            PluginReleaseService,
            SYSTEM_DEPLOYMENT.release_lookup,
        ),
        system_host_bindings=SYSTEM_DEPLOYMENT.host_bindings,
        loaded_system_plugins=SYSTEM_DEPLOYMENT.loaded_plugins,
    )
    return RunExecutionManager(
        components.run_graph,
        terminal_retention=terminal_retention,
        event_capacity=event_capacity,
        admission_limiter=ExecutionAdmissionLimiter(max_active_executions),
    )


def _gate(node_id: str) -> None:
    _started[node_id] = asyncio.Event()
    _release[node_id] = asyncio.Event()


async def _terminal(
    manager: RunExecutionManager,
    execution_id: UUID,
) -> RunExecutionSnapshot:
    async with asyncio.timeout(3):
        while True:
            execution = await manager.get(WORKSPACE_ID, execution_id)
            if execution.status in {"cancelled", "succeeded", "failed"}:
                return execution
            await asyncio.sleep(0)


def _saved_request(graph_id: UUID) -> RunRequest:
    return RunRequest(nodes=[], graph_id=graph_id, graph_revision=1)


@pytest.fixture(autouse=True)
def reset_execution_test_state() -> None:
    _started.clear()
    _release.clear()
    _downstream_calls.clear()
    _progress_contexts.clear()


@pytest.mark.asyncio
async def test_manager_reports_exact_node_and_cancellation_stops_downstream(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path / "workbench")
    _gate("first")
    _gate("second")
    request = _pin_system_plugins(
        RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="first",
                    operator_id="test.execution.first_gate",
                    operator_version=1,
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="second",
                    operator_id="test.execution.second_gate",
                    operator_version=1,
                ),
                RunNodeRequest(
                    kind="builtin",
                    id="third",
                    operator_id="test.execution.recording",
                    operator_version=1,
                ),
            ],
            edges=[
                RunEdgeRequest(
                    from_node="first",
                    from_port="value",
                    to_node="second",
                    to_port="value",
                ),
                RunEdgeRequest(
                    from_node="second",
                    from_port="value",
                    to_node="third",
                    to_port="value",
                ),
            ],
        )
    )

    execution = await manager.start(WORKSPACE_ID, request)
    await asyncio.wait_for(_started["first"].wait(), timeout=3)
    assert (
        await manager.get(WORKSPACE_ID, execution.execution_id)
    ).active_node_id == "first"
    subscription = await manager.subscribe_events(WORKSPACE_ID, execution.execution_id)
    observed = await subscription.wait(
        after_sequence=0,
        timeout=0,
    )
    quiet = await subscription.wait(
        after_sequence=observed.events[-1].sequence,
        timeout=0,
    )
    assert quiet.events == ()
    assert quiet.terminal is False

    _release["first"].set()
    await asyncio.wait_for(_started["second"].wait(), timeout=3)
    assert (
        await manager.get(WORKSPACE_ID, execution.execution_id)
    ).active_node_id == "second"

    cancelling = await manager.cancel(WORKSPACE_ID, execution.execution_id)
    assert cancelling.status == "cancelling"
    cancelled = await _terminal(manager, execution.execution_id)
    assert cancelled.status == "cancelled"
    assert cancelled.active_node_id is None
    assert cancelled.result is None
    assert cancelled.error is None
    assert _downstream_calls == []
    terminal_events = await subscription.wait(
        after_sequence=0,
        timeout=0,
    )
    lifecycle = [
        event.status
        for event in terminal_events.events
        if isinstance(event, ExecutionStatusEvent)
    ]
    assert "cancelling" in lifecycle
    assert lifecycle[-1] == "cancelled"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_cancel_is_idempotent_and_handles_cancel_before_task_start(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path / "workbench")
    execution = await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))

    first = await manager.cancel(WORKSPACE_ID, execution.execution_id)
    second = await manager.cancel(WORKSPACE_ID, execution.execution_id)
    assert first.status == "cancelling"
    assert second.status == "cancelling"
    terminal = await _terminal(manager, execution.execution_id)
    assert terminal.status == "cancelled"
    assert (
        await manager.cancel(WORKSPACE_ID, execution.execution_id)
    ).status == "cancelled"

    other_workspace_id = UUID("00000000-0000-0000-0000-000000000902")
    with pytest.raises(NotFoundError, match="Run execution"):
        await manager.subscribe_events(other_workspace_id, execution.execution_id)
    missing_id = uuid4()
    with pytest.raises(NotFoundError, match=str(missing_id)):
        await manager.get(WORKSPACE_ID, missing_id)
    with pytest.raises(NotFoundError, match=str(missing_id)):
        await manager.cancel(WORKSPACE_ID, missing_id)
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_isolates_concurrent_execution_progress(tmp_path: Path) -> None:
    manager = _manager(tmp_path / "workbench")
    _gate("run-a")
    _gate("run-b")
    first = await manager.start(
        WORKSPACE_ID,
        _pin_system_plugins(
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id="run-a",
                        operator_id="test.execution.first_gate",
                        operator_version=1,
                    )
                ]
            )
        ),
    )
    second = await manager.start(
        WORKSPACE_ID,
        _pin_system_plugins(
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id="run-b",
                        operator_id="test.execution.first_gate",
                        operator_version=1,
                    )
                ]
            )
        ),
    )

    await asyncio.gather(_started["run-a"].wait(), _started["run-b"].wait())
    assert (
        await manager.get(WORKSPACE_ID, first.execution_id)
    ).active_node_id == "run-a"
    assert (
        await manager.get(WORKSPACE_ID, second.execution_id)
    ).active_node_id == "run-b"

    _release["run-a"].set()
    assert (await _terminal(manager, first.execution_id)).status == "succeeded"
    still_running = await manager.get(WORKSPACE_ID, second.execution_id)
    assert still_running.status == "running"
    assert still_running.active_node_id == "run-b"
    await manager.cancel(WORKSPACE_ID, second.execution_id)
    assert (await _terminal(manager, second.execution_id)).status == "cancelled"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_shutdown_cancels_and_awaits_active_tasks(tmp_path: Path) -> None:
    manager = _manager(tmp_path / "workbench")
    _gate("run-a")
    _gate("run-b")
    first = await manager.start(
        WORKSPACE_ID,
        _pin_system_plugins(
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id="run-a",
                        operator_id="test.execution.first_gate",
                        operator_version=1,
                    )
                ]
            )
        ),
    )
    second = await manager.start(
        WORKSPACE_ID,
        _pin_system_plugins(
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id="run-b",
                        operator_id="test.execution.first_gate",
                        operator_version=1,
                    )
                ]
            )
        ),
    )
    await asyncio.gather(_started["run-a"].wait(), _started["run-b"].wait())

    await manager.shutdown()

    assert (await manager.get(WORKSPACE_ID, first.execution_id)).status == "cancelled"
    assert (await manager.get(WORKSPACE_ID, second.execution_id)).status == "cancelled"
    with pytest.raises(RuntimeError, match="shutting down"):
        await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))


@pytest.mark.asyncio
async def test_manager_preserves_failed_graph_result(tmp_path: Path) -> None:
    manager = _manager(tmp_path / "workbench")
    execution = await manager.start(
        WORKSPACE_ID,
        _pin_system_plugins(
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id="failure",
                        operator_id="test.execution.failure",
                        operator_version=1,
                    ),
                    RunNodeRequest(
                        kind="builtin",
                        id="skipped",
                        operator_id="test.execution.recording",
                        operator_version=1,
                    ),
                ],
                edges=[
                    RunEdgeRequest(
                        from_node="failure",
                        from_port="value",
                        to_node="skipped",
                        to_port="value",
                    )
                ],
            )
        ),
    )

    failed = await _terminal(manager, execution.execution_id)

    assert failed.status == "failed"
    assert failed.result is not None
    assert failed.result.status == "failed"
    assert "controlled node failure" in (failed.result.node_results[0].error or "")
    subscription = await manager.subscribe_events(WORKSPACE_ID, execution.execution_id)
    batch = await subscription.wait(
        after_sequence=0,
        timeout=0,
    )
    node_transitions = [
        (event.node_id, event.status)
        for event in batch.events
        if isinstance(event, NodeStatusEvent)
    ]
    assert node_transitions == [
        ("failure", "running"),
        ("failure", "failed"),
        ("skipped", "skipped"),
    ]
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_replays_lifecycle_and_mapped_progress_events(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path / "workbench")
    execution = await manager.start(
        WORKSPACE_ID,
        _pin_system_plugins(
            RunRequest(
                nodes=[
                    RunNodeRequest(
                        kind="builtin",
                        id="sequence",
                        operator_id="arithmetic.integer_sequence",
                        operator_version=1,
                        config={"start": 1, "count": 3, "step": 1},
                    ),
                    RunNodeRequest(
                        kind="builtin",
                        id="progress",
                        operator_id="test.execution.progress",
                        operator_version=1,
                    ),
                ],
                edges=[
                    RunEdgeRequest(
                        from_node="sequence",
                        from_port="values",
                        to_node="progress",
                        to_port="value",
                        collection_mode="map",
                    )
                ],
            )
        ),
    )
    assert (await _terminal(manager, execution.execution_id)).status == "succeeded"

    subscription = await manager.subscribe_events(WORKSPACE_ID, execution.execution_id)
    batch = await subscription.wait(
        after_sequence=0,
        timeout=0,
    )
    progress_events = [
        event for event in batch.events if isinstance(event, NodeProgressEvent)
    ]
    status_events = [
        event for event in batch.events if isinstance(event, ExecutionStatusEvent)
    ]

    assert batch.terminal is True
    assert [event.sequence for event in batch.events] == list(
        range(1, len(batch.events) + 1)
    )
    assert [event.status for event in status_events[:2]] == ["queued", "running"]
    assert status_events[-1].status == "succeeded"
    assert [event.invocation_index for event in progress_events] == [0, 1, 2]
    assert [event.invocation_path for event in progress_events] == [[0], [1], [2]]
    assert [event.current for event in progress_events] == [1, 2, 3]
    assert all(event.total == 3 for event in progress_events)
    assert all(event.node_path == ["progress"] for event in progress_events)
    assert all(event.node_run_id is not None for event in progress_events)

    terminal_sequence = batch.events[-1].sequence
    await _progress_contexts[0].progress("Too late")
    after_terminal = await subscription.wait(
        after_sequence=terminal_sequence,
        timeout=0,
    )
    assert after_terminal.events == ()
    assert after_terminal.terminal is True
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_bounds_event_replay_and_detects_terminal_delivery(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path / "workbench", event_capacity=2)
    execution = await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
    assert (await _terminal(manager, execution.execution_id)).status == "succeeded"

    subscription = await manager.subscribe_events(WORKSPACE_ID, execution.execution_id)
    replay = await subscription.wait(
        after_sequence=0,
        timeout=0,
    )
    after_terminal = await subscription.wait(
        after_sequence=replay.events[-1].sequence,
        timeout=0,
    )

    assert [event.sequence for event in replay.events] == [2, 3]
    assert [event.kind for event in replay.events] == [
        "execution.status",
        "execution.status",
    ]
    assert replay.terminal is True
    assert after_terminal.events == ()
    assert after_terminal.terminal is True
    await manager.shutdown()


@pytest.mark.asyncio
async def test_cancellation_intent_wins_when_executor_wraps_cancelled_error() -> None:
    run_graph = CancellationWrappingRunGraph()
    manager = RunExecutionManager(run_graph)
    execution = await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
    await run_graph.started.wait()

    await manager.cancel(WORKSPACE_ID, execution.execution_id)
    terminal = await _terminal(manager, execution.execution_id)

    assert terminal.status == "cancelled"
    assert terminal.error is None
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_atomically_rejects_execution_above_process_capacity() -> None:
    run_graph = ControlledRunGraph()
    admission_limiter = ExecutionAdmissionLimiter(1)
    manager = RunExecutionManager(
        run_graph,
        admission_limiter=admission_limiter,
    )

    starts = await asyncio.gather(
        manager.start(WORKSPACE_ID, RunRequest(nodes=[])),
        manager.start(WORKSPACE_ID, RunRequest(nodes=[])),
        return_exceptions=True,
    )

    accepted = [result for result in starts if isinstance(result, RunExecutionSnapshot)]
    rejected = [result for result in starts if isinstance(result, Exception)]
    assert len(accepted) == 1
    assert len(rejected) == 1
    capacity_error = rejected[0]
    assert isinstance(capacity_error, RunExecutionCapacityError)
    assert capacity_error.error_code == "execution_capacity_exceeded"
    assert capacity_error.max_active_executions == 1
    assert admission_limiter.diagnostics().active_executions == 1
    assert admission_limiter.diagnostics().rejected_acquisitions == 1

    run_graph.release.set()
    assert (await _terminal(manager, accepted[0].execution_id)).status == "succeeded"
    replacement = await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
    assert (await _terminal(manager, replacement.execution_id)).status == "succeeded"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_saved_graph_executions_wait_in_bounded_fifo() -> None:
    run_graph = SequencedRunGraph()
    history = ControlledExecutionHistory()
    graph_ids = tuple(uuid4() for _ in range(4))
    for graph_id in graph_ids:
        run_graph.add(graph_id)
    manager = RunExecutionManager(
        run_graph,
        execution_history=history,
        admission_limiter=ExecutionAdmissionLimiter(1),
        max_pending_graphs=2,
    )

    first = await manager.start(WORKSPACE_ID, _saved_request(graph_ids[0]))
    await run_graph.started[graph_ids[0]].wait()
    second = await manager.start(WORKSPACE_ID, _saved_request(graph_ids[1]))
    third = await manager.start(WORKSPACE_ID, _saved_request(graph_ids[2]))

    assert (await manager.get(WORKSPACE_ID, first.execution_id)).status == "running"
    assert second.status == "queued"
    assert second.queue_position == 1
    assert third.status == "queued"
    assert third.queue_position == 2
    with pytest.raises(RunExecutionQueueFullError) as exc_info:
        await manager.start(WORKSPACE_ID, _saved_request(graph_ids[3]))
    assert exc_info.value.max_pending_graphs == 2
    assert history.transitions.count("queued") == 3
    queue_diagnostics = await manager.diagnostics()
    assert queue_diagnostics.pending_graphs == 2
    assert queue_diagnostics.max_pending_graphs == 2
    assert queue_diagnostics.queue_full_outcomes == 1
    assert queue_diagnostics.oldest_pending_wait_seconds >= 0

    run_graph.release[graph_ids[0]].set()
    await run_graph.started[graph_ids[1]].wait()
    assert (await manager.get(WORKSPACE_ID, third.execution_id)).queue_position == 1
    run_graph.release[graph_ids[1]].set()
    await run_graph.started[graph_ids[2]].wait()
    run_graph.release[graph_ids[2]].set()

    assert (await _terminal(manager, first.execution_id)).status == "succeeded"
    assert (await _terminal(manager, second.execution_id)).status == "succeeded"
    assert (await _terminal(manager, third.execution_id)).status == "succeeded"
    assert run_graph.started_order == list(graph_ids[:3])
    terminal_diagnostics = await manager.diagnostics()
    assert terminal_diagnostics.pending_graphs == 0
    assert terminal_diagnostics.dispatched_graphs == 3
    assert terminal_diagnostics.average_dispatch_wait_seconds >= 0
    assert terminal_diagnostics.maximum_dispatch_wait_seconds >= 0
    await manager.shutdown()


@pytest.mark.asyncio
async def test_third_saved_graph_waits_while_two_graph_slots_are_occupied() -> None:
    run_graph = SequencedRunGraph()
    history = ControlledExecutionHistory()
    graph_ids = tuple(uuid4() for _ in range(3))
    for graph_id in graph_ids:
        run_graph.add(graph_id)
    manager = RunExecutionManager(
        run_graph,
        execution_history=history,
        admission_limiter=ExecutionAdmissionLimiter(2),
    )

    first = await manager.start(WORKSPACE_ID, _saved_request(graph_ids[0]))
    second = await manager.start(WORKSPACE_ID, _saved_request(graph_ids[1]))
    await asyncio.gather(
        run_graph.started[graph_ids[0]].wait(),
        run_graph.started[graph_ids[1]].wait(),
    )
    third = await manager.start(WORKSPACE_ID, _saved_request(graph_ids[2]))

    assert third.status == "queued"
    assert third.queue_position == 1
    run_graph.release[graph_ids[0]].set()
    await run_graph.started[graph_ids[2]].wait()

    run_graph.release[graph_ids[1]].set()
    run_graph.release[graph_ids[2]].set()
    assert (await _terminal(manager, first.execution_id)).status == "succeeded"
    assert (await _terminal(manager, second.execution_id)).status == "succeeded"
    assert (await _terminal(manager, third.execution_id)).status == "succeeded"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_queued_cancellation_never_invokes_graph_code() -> None:
    run_graph = SequencedRunGraph()
    history = ControlledExecutionHistory()
    first_graph_id = uuid4()
    queued_graph_id = uuid4()
    run_graph.add(first_graph_id)
    run_graph.add(queued_graph_id)
    manager = RunExecutionManager(
        run_graph,
        execution_history=history,
        admission_limiter=ExecutionAdmissionLimiter(1),
    )

    first = await manager.start(WORKSPACE_ID, _saved_request(first_graph_id))
    await run_graph.started[first_graph_id].wait()
    queued = await manager.start(WORKSPACE_ID, _saved_request(queued_graph_id))

    cancelled = await manager.cancel(WORKSPACE_ID, queued.execution_id)

    assert cancelled.status == "cancelled"
    assert cancelled.queue_position is None
    assert queued_graph_id not in run_graph.started_order
    run_graph.release[first_graph_id].set()
    assert (await _terminal(manager, first.execution_id)).status == "succeeded"
    await asyncio.sleep(0)
    assert queued_graph_id not in run_graph.started_order
    await manager.shutdown()


@pytest.mark.asyncio
async def test_recovery_reloads_durable_queue_before_dispatch() -> None:
    run_graph = SequencedRunGraph()
    graph_ids = (uuid4(), uuid4())
    for graph_id in graph_ids:
        run_graph.add(graph_id)
    created_at = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)
    execution_ids = (
        UUID("00000000-0000-7000-8000-000000000001"),
        UUID("00000000-0000-7000-8000-000000000002"),
    )
    queued = tuple(
        GraphExecution(
            workspace_id=WORKSPACE_ID,
            execution_id=execution_id,
            graph_id=graph_id,
            graph_revision=1,
            status="queued",
            created_at=created_at,
            submitted_request=_saved_request(graph_id).model_dump(mode="json"),
        )
        for execution_id, graph_id in zip(execution_ids, graph_ids, strict=True)
    )
    history = RecoveringExecutionHistory(queued)
    admission_limiter = ExecutionAdmissionLimiter(1)
    occupied_lease = admission_limiter.acquire()
    manager = RunExecutionManager(
        run_graph,
        execution_history=history,
        admission_limiter=admission_limiter,
    )

    assert await manager.recover_queued() == 2
    assert (await manager.get(WORKSPACE_ID, execution_ids[0])).queue_position == 1
    assert (await manager.get(WORKSPACE_ID, execution_ids[1])).queue_position == 2

    occupied_lease.release()
    await run_graph.started[graph_ids[0]].wait()
    run_graph.release[graph_ids[0]].set()
    await run_graph.started[graph_ids[1]].wait()
    run_graph.release[graph_ids[1]].set()

    assert (await _terminal(manager, execution_ids[0])).status == "succeeded"
    assert (await _terminal(manager, execution_ids[1])).status == "succeeded"
    assert run_graph.started_order == list(graph_ids)
    await manager.shutdown()


@pytest.mark.asyncio
async def test_recovered_queue_revalidates_submitter_access_before_graph_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.ERROR,
        logger="grafy_api.execution.manager",
    )
    run_graph = SequencedRunGraph()
    graph_id = uuid4()
    run_graph.add(graph_id)
    execution_id = UUID("00000000-0000-7000-8000-000000000010")
    queued = GraphExecution(
        workspace_id=WORKSPACE_ID,
        execution_id=execution_id,
        graph_id=graph_id,
        graph_revision=1,
        status="queued",
        submitted_request=_saved_request(graph_id).model_dump(mode="json"),
        submitted_by_actor_id=uuid4(),
    )
    history = RecoveringExecutionHistory((queued,))
    history.recovered_authorized = False
    manager = RunExecutionManager(
        run_graph,
        execution_history=history,
        admission_limiter=ExecutionAdmissionLimiter(1),
    )

    assert await manager.recover_queued() == 1
    failed = await _terminal(manager, execution_id)

    assert failed.status == "failed"
    assert "no longer has execute access" in (failed.error or "")
    assert run_graph.started_order == []
    failure_record = next(
        record
        for record in caplog.records
        if record.message == "graph_execution_failed"
    )
    assert cast(str, failure_record.__dict__["workspace_id"]) == str(WORKSPACE_ID)
    assert cast(str, failure_record.__dict__["execution_id"]) == str(execution_id)
    assert cast(str, failure_record.__dict__["graph_id"]) == str(graph_id)
    assert cast(int, failure_record.__dict__["graph_revision"]) == 1
    assert failure_record.exc_info is not None or hasattr(
        failure_record,
        "exception",
    )
    await manager.shutdown()


@pytest.mark.asyncio
async def test_exact_idempotent_retry_returns_original_before_queue_full_check() -> (
    None
):
    run_graph = SequencedRunGraph()
    graph_id = uuid4()
    run_graph.add(graph_id)
    history = ControlledExecutionHistory()
    admission_limiter = ExecutionAdmissionLimiter(1)
    occupied_lease = admission_limiter.acquire()
    manager = RunExecutionManager(
        run_graph,
        execution_history=history,
        admission_limiter=admission_limiter,
        max_pending_graphs=1,
    )
    request = _saved_request(graph_id)

    original = await manager.start(
        WORKSPACE_ID,
        request,
        idempotency_key="schedule:weekly:2026-08-24T10:00:00Z",
    )
    retry = await manager.start(
        WORKSPACE_ID,
        request.model_copy(deep=True),
        idempotency_key="schedule:weekly:2026-08-24T10:00:00Z",
    )

    assert retry.execution_id == original.execution_id
    assert retry.queue_position == 1
    assert history.transitions.count("queued") == 1

    occupied_lease.release()
    await run_graph.started[graph_id].wait()
    run_graph.release[graph_id].set()
    assert (await _terminal(manager, original.execution_id)).status == "succeeded"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_exact_idempotent_retry_after_manager_restart_returns_original() -> None:
    graph_id = uuid4()
    request = _saved_request(graph_id)
    history = ControlledExecutionHistory()
    first_admission = ExecutionAdmissionLimiter(1)
    occupied_lease = first_admission.acquire()
    first_manager = RunExecutionManager(
        SequencedRunGraph(),
        execution_history=history,
        admission_limiter=first_admission,
    )
    original = await first_manager.start(
        WORKSPACE_ID,
        request,
        idempotency_key="api-retry-across-restart",
    )
    assert original.status == "queued"
    await first_manager.shutdown()

    restarted_manager = RunExecutionManager(
        SequencedRunGraph(),
        execution_history=history,
        admission_limiter=ExecutionAdmissionLimiter(1),
    )
    retry = await restarted_manager.start(
        WORKSPACE_ID,
        request.model_copy(deep=True),
        idempotency_key="api-retry-across-restart",
    )

    assert retry.execution_id == original.execution_id
    assert retry.status == "queued"
    assert history.transitions.count("queued") == 1
    occupied_lease.release()
    await restarted_manager.shutdown()


@pytest.mark.asyncio
async def test_saved_graph_replay_probe_requires_the_original_graph_identity() -> None:
    graph_id = uuid4()
    request = _saved_request(graph_id)
    history = ControlledExecutionHistory()
    admission_limiter = ExecutionAdmissionLimiter(1)
    occupied_lease = admission_limiter.acquire()
    manager = RunExecutionManager(
        SequencedRunGraph(),
        execution_history=history,
        admission_limiter=admission_limiter,
    )
    original = await manager.start(
        WORKSPACE_ID,
        request,
        idempotency_key="saved-graph-probe",
    )

    replay = await manager.replay_saved_graph_execution(
        WORKSPACE_ID,
        "saved-graph-probe",
        graph_id=graph_id,
        graph_revision=1,
    )

    assert replay is not None
    assert replay.execution_id == original.execution_id
    assert (
        await manager.replay_saved_graph_execution(
            WORKSPACE_ID,
            "unused-key",
            graph_id=graph_id,
            graph_revision=1,
        )
        is None
    )
    for conflicting_graph_id, conflicting_revision in (
        (graph_id, 2),
        (uuid4(), 1),
    ):
        with pytest.raises(RunExecutionIdempotencyConflictError):
            await manager.replay_saved_graph_execution(
                WORKSPACE_ID,
                "saved-graph-probe",
                graph_id=conflicting_graph_id,
                graph_revision=conflicting_revision,
            )

    await manager.cancel(WORKSPACE_ID, original.execution_id)
    occupied_lease.release()
    await manager.shutdown()


@pytest.mark.asyncio
async def test_idempotency_key_rejects_a_different_submitted_request() -> None:
    run_graph = SequencedRunGraph()
    graph_id = uuid4()
    run_graph.add(graph_id)
    history = ControlledExecutionHistory()
    admission_limiter = ExecutionAdmissionLimiter(1)
    occupied_lease = admission_limiter.acquire()
    manager = RunExecutionManager(
        run_graph,
        execution_history=history,
        admission_limiter=admission_limiter,
    )
    original = _saved_request(graph_id)
    await manager.start(
        WORKSPACE_ID,
        original,
        idempotency_key="api-retry-1",
    )

    with pytest.raises(RunExecutionIdempotencyConflictError) as exc_info:
        await manager.start(
            WORKSPACE_ID,
            original.model_copy(update={"scope": "selected"}),
            idempotency_key="api-retry-1",
        )

    assert exc_info.value.idempotency_key == "api-retry-1"
    assert history.transitions.count("queued") == 1
    cancelled = next(iter(history.executions_by_idempotency_key.values()))
    await manager.cancel(WORKSPACE_ID, cancelled.execution_id)
    occupied_lease.release()
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_uses_shared_process_admission_budget() -> None:
    run_graph = ControlledRunGraph()
    admission_limiter = ExecutionAdmissionLimiter(1)
    manager = RunExecutionManager(
        run_graph,
        admission_limiter=admission_limiter,
    )
    diagnostic_run_lease = admission_limiter.acquire()

    with pytest.raises(RunExecutionCapacityError):
        await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))

    diagnostic_run_lease.release()
    execution = await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
    run_graph.release.set()
    assert (await _terminal(manager, execution.execution_id)).status == "succeeded"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_releases_admission_after_start_setup_failure() -> None:
    run_graph = ControlledRunGraph()
    admission_limiter = ExecutionAdmissionLimiter(1)
    manager = RunExecutionManager(
        run_graph,
        admission_limiter=admission_limiter,
    )

    with pytest.raises(RuntimeError, match="history is not configured"):
        await manager.start(
            WORKSPACE_ID,
            RunRequest(nodes=[], graph_id=uuid4(), graph_revision=1),
        )

    execution = await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
    run_graph.release.set()
    assert (await _terminal(manager, execution.execution_id)).status == "succeeded"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_cancelled_execution_releases_process_capacity() -> None:
    run_graph = ControlledRunGraph()
    history = ControlledExecutionHistory()
    history.allow_complete.clear()
    manager = RunExecutionManager(
        run_graph,
        execution_history=history,
        admission_limiter=ExecutionAdmissionLimiter(1),
    )
    execution = await manager.start(
        WORKSPACE_ID,
        RunRequest(nodes=[], graph_id=uuid4(), graph_revision=1),
    )
    await run_graph.started.wait()

    cancelling = await manager.cancel(WORKSPACE_ID, execution.execution_id)
    assert cancelling.status == "cancelling"
    await history.complete_entered.wait()
    with pytest.raises(RunExecutionCapacityError):
        await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
    history.allow_complete.set()
    assert (await _terminal(manager, execution.execution_id)).status == "cancelled"

    replacement = await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
    run_graph.release.set()
    assert (await _terminal(manager, replacement.execution_id)).status == "succeeded"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_failed_execution_releases_process_capacity(tmp_path: Path) -> None:
    manager = _manager(
        tmp_path / "workbench",
        max_active_executions=1,
    )
    failing_request = _pin_system_plugins(
        RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="failure",
                    operator_id="test.execution.failure",
                    operator_version=1,
                )
            ]
        )
    )
    first = await manager.start(WORKSPACE_ID, failing_request)
    assert (await _terminal(manager, first.execution_id)).status == "failed"

    second = await manager.start(WORKSPACE_ID, failing_request)
    assert (await _terminal(manager, second.execution_id)).status == "failed"
    await manager.shutdown()


@pytest.mark.asyncio
async def test_manager_bounds_terminal_execution_retention(tmp_path: Path) -> None:
    manager = _manager(tmp_path / "workbench", terminal_retention=2)
    execution_ids: list[UUID] = []
    first_subscription = None
    for _ in range(3):
        execution = await manager.start(WORKSPACE_ID, RunRequest(nodes=[]))
        execution_ids.append(execution.execution_id)
        assert (await _terminal(manager, execution.execution_id)).status == "succeeded"
        if first_subscription is None:
            first_subscription = await manager.subscribe_events(
                WORKSPACE_ID, execution.execution_id
            )

    with pytest.raises(NotFoundError, match=str(execution_ids[0])):
        await manager.get(WORKSPACE_ID, execution_ids[0])
    assert (await manager.get(WORKSPACE_ID, execution_ids[1])).status == "succeeded"
    assert (await manager.get(WORKSPACE_ID, execution_ids[2])).status == "succeeded"
    assert first_subscription is not None
    retained_events = await first_subscription.wait(after_sequence=0, timeout=0)
    assert retained_events.terminal is True
    assert retained_events.events
    assert all(
        event.execution_id == execution_ids[0] for event in retained_events.events
    )
    await manager.shutdown()


def test_node_execution_event_identity_is_bounded() -> None:
    event_fields = {
        "sequence": 1,
        "execution_id": uuid4(),
        "occurred_at": datetime.now(UTC),
        "node_id": "node",
        "node_path": ["node"],
        "node_run_id": uuid4(),
        "message": "Working",
    }

    normalized = NodeProgressEvent.model_validate(
        {
            **event_fields,
            "node_id": " node ",
            "node_path": [" parent ", " node "],
        }
    )
    assert normalized.node_id == "node"
    assert normalized.node_path == ["parent", "node"]

    boundary = NodeProgressEvent.model_validate(
        {
            **event_fields,
            "current": MAX_NODE_PROGRESS_COUNTER,
            "total": MAX_NODE_PROGRESS_COUNTER,
        }
    )
    assert boundary.current == MAX_NODE_PROGRESS_COUNTER
    assert boundary.total == MAX_NODE_PROGRESS_COUNTER

    with pytest.raises(ValidationError):
        NodeProgressEvent.model_validate({**event_fields, "node_id": "x" * 256})
    with pytest.raises(ValidationError):
        NodeProgressEvent.model_validate({**event_fields, "node_path": ["x" * 256]})
    with pytest.raises(ValidationError):
        NodeProgressEvent.model_validate({**event_fields, "node_path": ["  "]})
    with pytest.raises(ValidationError):
        NodeProgressEvent.model_validate({**event_fields, "node_path": ["node"] * 65})
    with pytest.raises(ValidationError):
        NodeProgressEvent.model_validate(
            {**event_fields, "invocation_path": list(range(65))}
        )
    with pytest.raises(ValidationError):
        ExecutionStatusEvent(
            sequence=1,
            execution_id=uuid4(),
            occurred_at=datetime.now(UTC),
            status="running",
            active_node_id="x" * 256,
        )
    with pytest.raises(ValidationError):
        NodeProgressEvent.model_validate(
            {**event_fields, "current": MAX_NODE_PROGRESS_COUNTER + 1}
        )
    with pytest.raises(ValidationError):
        NodeProgressEvent.model_validate(
            {**event_fields, "total": MAX_NODE_PROGRESS_COUNTER + 1}
        )


@pytest.mark.asyncio
async def test_natural_completion_wins_cancel_race_without_durable_downgrade() -> None:
    run_graph = ControlledRunGraph()
    history = ControlledExecutionHistory()
    history.allow_complete.clear()
    manager = RunExecutionManager(run_graph, execution_history=history)
    execution = await manager.start(
        WORKSPACE_ID,
        RunRequest(
            nodes=[],
            graph_id=uuid4(),
            graph_revision=1,
        ),
    )
    await run_graph.started.wait()
    run_graph.release.set()
    await history.complete_entered.wait()

    cancelling = asyncio.create_task(
        manager.cancel(WORKSPACE_ID, execution.execution_id)
    )
    await asyncio.sleep(0)
    assert not cancelling.done()
    history.allow_complete.set()

    cancel_result = await cancelling
    terminal = await _terminal(manager, execution.execution_id)
    assert cancel_result.status == "succeeded"
    assert terminal.status == "succeeded"
    assert history.transitions == ["queued", "running", "succeeded"]
    await manager.shutdown()


@pytest.mark.asyncio
async def test_cancel_transition_wins_race_and_persists_one_terminal_result() -> None:
    run_graph = ControlledRunGraph()
    history = ControlledExecutionHistory()
    history.allow_cancelling.clear()
    manager = RunExecutionManager(run_graph, execution_history=history)
    execution = await manager.start(
        WORKSPACE_ID,
        RunRequest(
            nodes=[],
            graph_id=uuid4(),
            graph_revision=1,
        ),
    )
    await run_graph.started.wait()

    cancelling = asyncio.create_task(
        manager.cancel(WORKSPACE_ID, execution.execution_id)
    )
    await history.cancelling_entered.wait()
    run_graph.release.set()
    await asyncio.sleep(0)
    history.allow_cancelling.set()

    assert (await cancelling).status == "cancelling"
    terminal = await _terminal(manager, execution.execution_id)
    assert terminal.status == "cancelled"
    assert history.transitions == ["queued", "running", "cancelling", "cancelled"]
    await manager.shutdown()


@pytest.mark.asyncio
async def test_terminal_history_write_retries_before_exposing_terminal() -> None:
    run_graph = ControlledRunGraph()
    history = ControlledExecutionHistory()
    history.complete_failures_remaining = 1
    manager = RunExecutionManager(run_graph, execution_history=history)
    execution = await manager.start(
        WORKSPACE_ID,
        RunRequest(
            nodes=[],
            graph_id=uuid4(),
            graph_revision=1,
        ),
    )
    await run_graph.started.wait()

    run_graph.release.set()
    terminal = await _terminal(manager, execution.execution_id)

    assert terminal.status == "succeeded"
    assert terminal.error is None
    assert history.complete_calls == 2
    assert history.transitions == ["queued", "running", "succeeded"]
    await manager.shutdown()
