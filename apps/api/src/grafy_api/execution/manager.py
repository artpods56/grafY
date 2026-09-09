"""Execution activity ownership and observation of background graph executions."""

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid7

from grafy_core.domain.execution_history import GraphExecution
from grafy_core.domain.errors import NotFoundError
from grafy_core.nodes import NodeExecutionContext

from grafy_api.realtime.hub import GraphRoomHub
from grafy_api.realtime.protocol import (
    ActiveExecutionLifecycleStatus,
    ActiveExecutionSummary,
    ActorPresentation,
    ExecutionActiveMessage,
    ExecutionClearedMessage,
)

from grafy_api.execution.events import (
    ExecutionStatusEvent,
    NodeExecutionEventStatus,
    NodeProgressEvent,
    NodeStatusEvent,
    RunExecutionEvent,
    RunExecutionStatus,
)
from grafy_api.execution.requests import RunRequest
from grafy_api.execution.history import ExecutionHistoryService
from grafy_api.execution.admission import (
    ExecutionAdmissionLease,
    ExecutionAdmissionLimiter,
    RunExecutionCapacityError,
    RunExecutionQueueFullError,
)
from grafy_api.execution.control import RunExecutionControl
from grafy_api.execution.errors import render_execution_error
from grafy_api.execution.models import GraphExecutionResult
from grafy_api.execution.run_graph import RunGraph
from grafy_api.plugins.runtime.sandbox import PluginSandboxCleanupError


logger = logging.getLogger(__name__)

_TERMINAL_STATUSES = frozenset({"cancelled", "succeeded", "failed"})
_ACTIVE_STATUSES = frozenset({"queued", "running", "cancelling"})


@dataclass(frozen=True, slots=True)
class RunExecutionSnapshot:
    workspace_id: UUID
    execution_id: UUID
    status: RunExecutionStatus
    active_node_id: str | None
    result: GraphExecutionResult | None
    error: str | None
    queue_position: int | None


@dataclass(frozen=True, slots=True)
class RunExecutionEventBatch:
    events: tuple[RunExecutionEvent, ...]
    terminal: bool


@dataclass(frozen=True, slots=True)
class RunExecutionQueueDiagnostics:
    max_pending_graphs: int
    pending_graphs: int
    queue_full_outcomes: int
    dispatched_graphs: int
    average_dispatch_wait_seconds: float
    maximum_dispatch_wait_seconds: float
    oldest_pending_wait_seconds: float


class _RunExecutionEventJournal:
    """Bounded replay journal that never waits for stream subscribers."""

    def __init__(self, execution_id: UUID, capacity: int) -> None:
        self._execution_id = execution_id
        self._events: deque[RunExecutionEvent] = deque(maxlen=capacity)
        self._next_sequence = 1
        self._terminal_sequence: int | None = None
        self._sealed = False
        self._changed = asyncio.Event()

    def publish_execution_status(
        self,
        status: RunExecutionStatus,
        active_node_id: str | None,
        /,
    ) -> None:
        if self._sealed:
            return
        event = ExecutionStatusEvent(
            sequence=self._next_sequence,
            execution_id=self._execution_id,
            occurred_at=datetime.now(UTC),
            status=status,
            active_node_id=active_node_id,
        )
        self._append(event)
        if status in _TERMINAL_STATUSES:
            self._terminal_sequence = event.sequence
            self._sealed = True

    def publish_node_status(
        self,
        *,
        status: NodeExecutionEventStatus,
        node_path: tuple[str, ...],
        node_id: str,
        node_run_id: UUID | None,
        invocation_index: int | None,
        invocation_path: tuple[int, ...],
    ) -> None:
        if self._sealed:
            return
        self._append(
            NodeStatusEvent(
                sequence=self._next_sequence,
                execution_id=self._execution_id,
                occurred_at=datetime.now(UTC),
                status=status,
                node_path=list(node_path),
                node_id=node_id,
                node_run_id=node_run_id,
                invocation_index=invocation_index,
                invocation_path=list(invocation_path),
            )
        )

    async def report_progress(
        self,
        context: NodeExecutionContext,
        message: str,
        *,
        current: int | None,
        total: int | None,
    ) -> None:
        if self._sealed:
            return
        node_id = context.node_id
        if node_id is None:
            raise RuntimeError("Managed node progress requires a node ID")
        node_path = context.node_path
        if not node_path:
            node_path = (node_id,)
        self._append(
            NodeProgressEvent(
                sequence=self._next_sequence,
                execution_id=self._execution_id,
                occurred_at=datetime.now(UTC),
                node_path=list(node_path),
                node_id=node_id,
                node_run_id=context.node_run_id,
                invocation_index=context.invocation_index,
                invocation_path=list(context.invocation_path),
                message=message,
                current=current,
                total=total,
            )
        )

    async def wait_after(
        self,
        sequence: int,
        timeout: float,
        /,
    ) -> RunExecutionEventBatch:
        while True:
            events = tuple(event for event in self._events if event.sequence > sequence)
            delivered_sequence = events[-1].sequence if events else sequence
            terminal = (
                self._terminal_sequence is not None
                and self._terminal_sequence <= delivered_sequence
            )
            if events or terminal:
                return RunExecutionEventBatch(events=events, terminal=terminal)

            changed = self._changed
            try:
                async with asyncio.timeout(timeout):
                    await changed.wait()
            except TimeoutError:
                return RunExecutionEventBatch(events=(), terminal=False)

    def _append(self, event: RunExecutionEvent) -> None:
        self._events.append(event)
        self._next_sequence += 1
        changed = self._changed
        self._changed = asyncio.Event()
        changed.set()


@dataclass(frozen=True, slots=True)
class RunExecutionEventSubscription:
    """Stable event-journal handle retained independently of manager eviction."""

    _journal: _RunExecutionEventJournal = field(repr=False)

    async def wait(
        self,
        *,
        after_sequence: int = 0,
        timeout: float = 15,
    ) -> RunExecutionEventBatch:
        if after_sequence < 0:
            raise ValueError("Execution event sequence must not be negative")
        if timeout < 0:
            raise ValueError("Execution event wait timeout must not be negative")
        return await self._journal.wait_after(after_sequence, timeout)


@dataclass(frozen=True, slots=True)
class _TerminalOutcome:
    """One typed terminal outcome: status, result, and error move together."""

    status: Literal["cancelled", "succeeded", "failed"]
    result: GraphExecutionResult | None
    error: str | None


class RunExecutionIdempotencyConflictError(RuntimeError):
    """One retry key was reused for a different submitted execution."""

    error_code: Literal["execution_idempotency_conflict"] = (
        "execution_idempotency_conflict"
    )

    def __init__(self, idempotency_key: str, execution_id: UUID) -> None:
        self.idempotency_key = idempotency_key
        self.execution_id = execution_id
        super().__init__(
            f"Idempotency key {idempotency_key!r} already belongs to execution "
            f"{execution_id} with a different submitted request"
        )


@dataclass(slots=True)
class _RunExecutionRecord:
    workspace_id: UUID
    execution_id: UUID
    control: RunExecutionControl
    journal: _RunExecutionEventJournal
    request: RunRequest
    admission_lease: ExecutionAdmissionLease | None = None
    history_execution: GraphExecution | None = None
    starter: ActorPresentation | None = None
    overlays_compatible: bool = True
    recovered: bool = False
    transition_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    status: RunExecutionStatus = "queued"
    task: asyncio.Task[None] | None = None
    error: str | None = None
    terminal: _TerminalOutcome | None = None
    cleanup_confirmed: bool = True
    activity_registration_attempted: bool = False

    def snapshot(self, queue_position: int | None) -> RunExecutionSnapshot:
        terminal = self.terminal
        if terminal is not None:
            return RunExecutionSnapshot(
                workspace_id=self.workspace_id,
                execution_id=self.execution_id,
                status=terminal.status,
                active_node_id=self.control.active_node_id,
                result=terminal.result,
                error=terminal.error,
                queue_position=None,
            )
        return RunExecutionSnapshot(
            workspace_id=self.workspace_id,
            execution_id=self.execution_id,
            status=self.status,
            active_node_id=self.control.active_node_id,
            result=None,
            error=self.error,
            queue_position=queue_position,
        )

    def active_summary(self) -> ActiveExecutionSummary | None:
        if (
            self.history_execution is None
            or self.starter is None
            or self.status not in _ACTIVE_STATUSES
        ):
            return None
        status: ActiveExecutionLifecycleStatus
        if self.status == "queued":
            status = "queued"
        elif self.status == "running":
            status = "running"
        else:
            status = "cancelling"
        return ActiveExecutionSummary(
            execution_id=self.execution_id,
            graph_revision=self.history_execution.graph_revision,
            status=status,
            scope=self.history_execution.scope,
            requested_node_ids=list(self.history_execution.requested_node_ids),
            starter=self.starter,
            active_node_id=self.control.active_node_id,
            overlays_compatible=self.overlays_compatible,
            cancellable=self.status in {"queued", "running"},
        )


class RunExecutionManager:
    """Own background graph tasks and retain a bounded set of terminal results."""

    def __init__(
        self,
        run_graph: RunGraph,
        *,
        execution_history: ExecutionHistoryService | None = None,
        terminal_retention: int = 100,
        event_capacity: int = 256,
        admission_limiter: ExecutionAdmissionLimiter | None = None,
        max_pending_graphs: int = 20,
        graph_room_hub: GraphRoomHub | None = None,
    ) -> None:
        if terminal_retention < 1:
            raise ValueError("Execution terminal retention must be at least one")
        if event_capacity < 1:
            raise ValueError("Execution event capacity must be at least one")
        if max_pending_graphs < 1:
            raise ValueError("Maximum pending graph executions must be at least one")
        self._run_graph = run_graph
        self._execution_history = execution_history
        self._transient_owner_id = uuid7()
        self._terminal_retention = terminal_retention
        self._event_capacity = event_capacity
        self._admission_limiter = admission_limiter or ExecutionAdmissionLimiter(2)
        self._max_pending_graphs = max_pending_graphs
        self._queue_full_outcomes = 0
        self._dispatched_graphs = 0
        self._total_dispatch_wait_seconds = 0.0
        self._maximum_dispatch_wait_seconds = 0.0
        self._executions: dict[UUID, _RunExecutionRecord] = {}
        self._pending_execution_ids: list[UUID] = []
        self._terminal_order: deque[UUID] = deque()
        self._lock = asyncio.Lock()
        self._dispatch_wake = asyncio.Event()
        self._dispatcher_task: asyncio.Task[None] | None = None
        self._shutting_down = False
        self._graph_room_hub = graph_room_hub
        self._admission_limiter.bind_capacity_listener(self._dispatch_wake.set)

    async def run_inline(
        self, workspace_id: UUID, request: RunRequest
    ) -> GraphExecutionResult:
        """Run in the caller task; the caller retains its admission lease.

        Unlike background execution, errors and cancellation propagate directly.
        Activity covers preflight through sandbox cleanup without creating saved
        graph history or a pollable background execution.
        """
        if self._shutting_down:
            raise RuntimeError("Run execution manager is shutting down")
        if self._execution_history is None:
            raise RuntimeError("Transient execution activity is not configured")
        execution_id = uuid7()
        execution_failed = False
        cleanup_confirmed = True
        try:
            await self._execution_history.register_transient(
                workspace_id, execution_id, self._transient_owner_id
            )
            return await self._run_graph.run(workspace_id, request)
        except PluginSandboxCleanupError:
            cleanup_confirmed = False
            logger.exception(
                "Retaining transient activity after unconfirmed sandbox cleanup "
                "execution_id=%s",
                execution_id,
            )
            raise
        except BaseException:
            execution_failed = True
            raise
        finally:
            if cleanup_confirmed:
                # Registration may have committed even if its acknowledgement failed.
                for attempt in range(2):
                    try:
                        await self._execution_history.release_transient(
                            execution_id, self._transient_owner_id
                        )
                    except Exception as exc:
                        if attempt == 0:
                            await asyncio.sleep(0)
                            continue
                        message = (
                            f"Could not release transient execution {execution_id}; "
                            "activity marker retained for maintenance"
                        )
                        logger.exception(message)
                        if not execution_failed:
                            raise RuntimeError(message) from exc
                    break

    async def active_execution_summary(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> ActiveExecutionSummary | None:
        async with self._lock:
            for record in self._executions.values():
                if record.workspace_id != workspace_id:
                    continue
                history = record.history_execution
                if history is None or history.graph_id != graph_id:
                    continue
                summary = record.active_summary()
                if summary is not None:
                    return summary
            return None

    async def replay_saved_graph_execution(
        self,
        workspace_id: UUID,
        idempotency_key: str,
        *,
        graph_id: UUID,
        graph_revision: int,
    ) -> RunExecutionSnapshot | None:
        """Return the durable execution for one key and saved graph revision."""

        async with self._lock:
            if self._shutting_down:
                raise RuntimeError("Run execution manager is shutting down")
            if self._execution_history is None:
                raise RuntimeError("Saved graph execution history is not configured")
            normalized_idempotency_key = self._normalize_idempotency_key(
                idempotency_key
            )
            existing = await self._execution_history.get_by_idempotency_key(
                workspace_id,
                normalized_idempotency_key,
            )
            if existing is None:
                return None
            if (
                existing.graph_id != graph_id
                or existing.graph_revision != graph_revision
            ):
                raise RunExecutionIdempotencyConflictError(
                    normalized_idempotency_key,
                    existing.execution_id,
                )
            return self._existing_execution_snapshot_locked(existing)

    async def start(
        self,
        workspace_id: UUID,
        request: RunRequest,
        *,
        starter: ActorPresentation | None = None,
        overlays_compatible: bool = True,
        idempotency_key: str | None = None,
    ) -> RunExecutionSnapshot:
        async with self._lock:
            if self._shutting_down:
                raise RuntimeError("Run execution manager is shutting down")
            saved_graph_execution = (
                request.graph_id is not None and request.graph_revision is not None
            )
            normalized_idempotency_key = None
            if idempotency_key is not None:
                normalized_idempotency_key = self._normalize_idempotency_key(
                    idempotency_key
                )
                if not saved_graph_execution:
                    raise ValueError(
                        "Execution idempotency requires a saved graph context"
                    )
                if self._execution_history is None:
                    raise RuntimeError(
                        "Saved graph execution history is not configured"
                    )
                submitted_request = request.model_dump(mode="json")
                existing = await self._execution_history.get_by_idempotency_key(
                    workspace_id,
                    normalized_idempotency_key,
                )
                if existing is not None:
                    if existing.submitted_request != submitted_request:
                        raise RunExecutionIdempotencyConflictError(
                            normalized_idempotency_key,
                            existing.execution_id,
                        )
                    return self._existing_execution_snapshot_locked(existing)
            if (
                saved_graph_execution
                and self._pending_count_locked() >= self._max_pending_graphs
            ):
                self._queue_full_outcomes += 1
                logger.warning(
                    "execution_queue_full pending_graphs=%s max_pending_graphs=%s "
                    "queue_full_outcomes=%s",
                    self._pending_count_locked(),
                    self._max_pending_graphs,
                    self._queue_full_outcomes,
                )
                raise RunExecutionQueueFullError(self._max_pending_graphs)
            admission_lease = (
                None if saved_graph_execution else self._admission_limiter.acquire()
            )
            execution_id = uuid7()
            transient_registration_attempted = False
            try:
                history_execution: GraphExecution | None = None
                if saved_graph_execution:
                    graph_id = request.graph_id
                    graph_revision = request.graph_revision
                    if graph_id is None or graph_revision is None:
                        raise RuntimeError(
                            "Saved graph execution is missing its graph identity"
                        )
                    if self._execution_history is None:
                        raise RuntimeError(
                            "Saved graph execution history is not configured"
                        )
                    requested_node_ids: list[str] = []
                    seen_node_ids: set[str] = set()
                    for node in request.nodes:
                        if node.id in seen_node_ids:
                            continue
                        seen_node_ids.add(node.id)
                        requested_node_ids.append(node.id)
                    history_execution = await self._execution_history.create_queued(
                        workspace_id=workspace_id,
                        execution_id=execution_id,
                        graph_id=graph_id,
                        graph_revision=graph_revision,
                        scope=request.scope,
                        requested_node_ids=tuple(requested_node_ids),
                        submitted_request=request.model_dump(mode="json"),
                        idempotency_key=normalized_idempotency_key,
                        submitted_by_actor_id=(
                            starter.actor_id if starter is not None else None
                        ),
                    )
                elif self._execution_history is not None:
                    transient_registration_attempted = True
                    await self._execution_history.register_transient(
                        workspace_id, execution_id, self._transient_owner_id
                    )
                journal = _RunExecutionEventJournal(execution_id, self._event_capacity)
                control = RunExecutionControl(journal)
                record = _RunExecutionRecord(
                    workspace_id=workspace_id,
                    execution_id=execution_id,
                    control=control,
                    journal=journal,
                    request=request.model_copy(deep=True),
                    admission_lease=admission_lease,
                    history_execution=history_execution,
                    activity_registration_attempted=transient_registration_attempted,
                    starter=starter,
                    overlays_compatible=overlays_compatible,
                )
                self._executions[execution_id] = record
                control.publish_execution_status("queued", None)
                if saved_graph_execution:
                    self._insert_pending_locked(record)
                    self._ensure_dispatcher_locked()
                    self._dispatch_wake.set()
                else:
                    self._create_run_task_locked(record)
            except BaseException:
                self._executions.pop(execution_id, None)
                if admission_lease is not None:
                    admission_lease.release()
                if (
                    transient_registration_attempted
                    and self._execution_history is not None
                ):
                    try:
                        await self._execution_history.release_transient(
                            execution_id, self._transient_owner_id
                        )
                    except BaseException:
                        logger.exception(
                            "Could not clear failed transient admission execution_id=%s",
                            execution_id,
                        )
                raise
            snapshot = self._snapshot_locked(record)
            await self._publish_active(record)
            return snapshot

    async def recover_queued(self) -> int:
        if self._execution_history is None:
            return 0
        queued = await self._execution_history.list_queued()
        recovered: list[_RunExecutionRecord] = []
        invalid: list[tuple[GraphExecution, str]] = []
        for history_execution in queued:
            submitted_request = history_execution.submitted_request
            if submitted_request is None:
                invalid.append(
                    (history_execution, "Queued execution has no submitted request")
                )
                continue
            try:
                request = RunRequest.model_validate(submitted_request)
            except Exception as exc:
                invalid.append(
                    (
                        history_execution,
                        "Queued execution request is invalid: "
                        f"{render_execution_error(exc)}",
                    )
                )
                continue
            if (
                request.graph_id != history_execution.graph_id
                or request.graph_revision != history_execution.graph_revision
                or request.scope != history_execution.scope
            ):
                invalid.append(
                    (
                        history_execution,
                        "Queued execution request does not match its durable identity",
                    )
                )
                continue
            journal = _RunExecutionEventJournal(
                history_execution.execution_id,
                self._event_capacity,
            )
            control = RunExecutionControl(journal)
            record = _RunExecutionRecord(
                workspace_id=history_execution.workspace_id,
                execution_id=history_execution.execution_id,
                control=control,
                journal=journal,
                request=request,
                history_execution=history_execution,
                recovered=True,
            )
            control.publish_execution_status("queued", None)
            recovered.append(record)

        for history_execution, error in invalid:
            await self._execution_history.complete(
                history_execution.workspace_id,
                history_execution,
                status="failed",
                result=None,
                error=error,
            )

        async with self._lock:
            if self._shutting_down:
                raise RuntimeError("Run execution manager is shutting down")
            for record in recovered:
                if record.execution_id in self._executions:
                    continue
                self._executions[record.execution_id] = record
                self._insert_pending_locked(record)
            self._ensure_dispatcher_locked()
            self._dispatch_wake.set()
        return len(recovered)

    async def get(
        self,
        workspace_id: UUID,
        execution_id: UUID,
    ) -> RunExecutionSnapshot:
        async with self._lock:
            record = self._executions.get(execution_id)
            if record is None or record.workspace_id != workspace_id:
                raise NotFoundError("Run execution", str(execution_id))
            return self._snapshot_locked(record)

    async def diagnostics(self) -> RunExecutionQueueDiagnostics:
        async with self._lock:
            pending_records = [
                self._executions[execution_id]
                for execution_id in self._pending_execution_ids
                if execution_id in self._executions
                and self._executions[execution_id].status == "queued"
                and self._executions[execution_id].task is None
            ]
            now = datetime.now(UTC)
            pending_waits = [
                max(0.0, (now - history.created_at).total_seconds())
                for record in pending_records
                if (history := record.history_execution) is not None
            ]
            average_wait = (
                self._total_dispatch_wait_seconds / self._dispatched_graphs
                if self._dispatched_graphs
                else 0.0
            )
            return RunExecutionQueueDiagnostics(
                max_pending_graphs=self._max_pending_graphs,
                pending_graphs=len(pending_records),
                queue_full_outcomes=self._queue_full_outcomes,
                dispatched_graphs=self._dispatched_graphs,
                average_dispatch_wait_seconds=average_wait,
                maximum_dispatch_wait_seconds=self._maximum_dispatch_wait_seconds,
                oldest_pending_wait_seconds=max(pending_waits, default=0.0),
            )

    async def subscribe_events(
        self,
        workspace_id: UUID,
        execution_id: UUID,
        /,
    ) -> RunExecutionEventSubscription:
        async with self._lock:
            record = self._executions.get(execution_id)
            if record is None or record.workspace_id != workspace_id:
                raise NotFoundError("Run execution", str(execution_id))
            return RunExecutionEventSubscription(record.journal)

    async def cancel(
        self,
        workspace_id: UUID,
        execution_id: UUID,
    ) -> RunExecutionSnapshot:
        async with self._lock:
            record = self._executions.get(execution_id)
            if record is None or record.workspace_id != workspace_id:
                raise NotFoundError("Run execution", str(execution_id))
            if record.status in _TERMINAL_STATUSES:
                return self._snapshot_locked(record)
            if record.status == "cancelling":
                return self._snapshot_locked(record)
            record.control.request_cancel()
            if record.status == "queued" and record.task is None:
                self._remove_pending_locked(record.execution_id)
                await self._complete(record, status="cancelled")
                self._dispatch_wake.set()
                return self._snapshot_locked(record)
            async with record.transition_lock:
                if record.status in _TERMINAL_STATUSES:
                    return self._snapshot_locked(record)
                if (
                    record.history_execution is not None
                    and self._execution_history is not None
                ):
                    try:
                        await self._execution_history.mark_cancelling(
                            workspace_id, record.history_execution
                        )
                    except Exception as exc:
                        record.error = (
                            "Execution history could not record cancellation: "
                            f"{render_execution_error(exc)}"
                        )
                record.status = "cancelling"
                record.control.publish_execution_status(
                    "cancelling",
                    record.control.active_node_id,
                )
                task = record.task
                snapshot = self._snapshot_locked(record)
                await self._publish_active(record)
            if task is not None:
                task.cancel()
            return snapshot

    async def shutdown(self) -> None:
        async with self._lock:
            self._shutting_down = True
            dispatcher_task = self._dispatcher_task
            self._dispatcher_task = None
            if dispatcher_task is not None:
                dispatcher_task.cancel()
            active_records = [
                record
                for record in self._executions.values()
                if record.task is not None and record.status not in _TERMINAL_STATUSES
            ]
            tasks = [
                record.task for record in active_records if record.task is not None
            ]
            for record in active_records:
                record.control.request_cancel()
                if record.status != "cancelling":
                    record.status = "cancelling"
                    record.control.publish_execution_status(
                        "cancelling",
                        record.control.active_node_id,
                    )
            for task in tasks:
                task.cancel()

        owned_tasks: list[asyncio.Task[None]] = list(tasks)
        if dispatcher_task is not None:
            owned_tasks.append(dispatcher_task)
        if owned_tasks:
            await asyncio.gather(*owned_tasks, return_exceptions=True)
        for record in active_records:
            if record.status not in _TERMINAL_STATUSES:
                await self._complete(record, status="cancelled")

    async def _run(self, execution_id: UUID) -> None:
        record = self._executions[execution_id]
        try:
            record.control.check_cancelled()
            if (
                record.recovered
                and record.history_execution is not None
                and self._execution_history is not None
                and not await self._execution_history.can_dispatch_recovered(
                    record.history_execution
                )
            ):
                raise RuntimeError(
                    "Recovered execution submitter no longer has execute access"
                )
            async with record.transition_lock:
                record.control.check_cancelled()
                record.status = "running"
                if (
                    record.history_execution is not None
                    and self._execution_history is not None
                ):
                    claimed = await self._execution_history.mark_running(
                        record.workspace_id,
                        record.history_execution,
                    )
                    if not claimed:
                        raise RuntimeError(
                            "Queued execution could not be claimed from durable state"
                        )
                    record.activity_registration_attempted = True
                    await self._execution_history.register_transient(
                        record.workspace_id,
                        record.execution_id,
                        self._transient_owner_id,
                    )
                record.control.publish_execution_status(
                    "running",
                    record.control.active_node_id,
                )
                await self._publish_active(record)
            result = await self._run_graph.run(
                record.workspace_id,
                record.request,
                control=record.control,
            )
        except PluginSandboxCleanupError as exc:
            record.cleanup_confirmed = False
            logger.exception(
                "Retaining execution activity after unconfirmed sandbox cleanup "
                "execution_id=%s",
                record.execution_id,
            )
            await self._complete(
                record, status="failed", error=render_execution_error(exc)
            )
        except asyncio.CancelledError:
            await self._complete(record, status="cancelled")
        except Exception as exc:
            if record.control.cancel_requested or _contains_cancellation(exc):
                await self._complete(record, status="cancelled")
            else:
                logger.error(
                    "graph_execution_failed",
                    extra={
                        "workspace_id": str(record.workspace_id),
                        "execution_id": str(record.execution_id),
                        "graph_id": (
                            None
                            if record.request.graph_id is None
                            else str(record.request.graph_id)
                        ),
                        "graph_revision": record.request.graph_revision,
                        "actor_id": (
                            None
                            if record.starter is None
                            else str(record.starter.actor_id)
                        ),
                    },
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
                await self._complete(
                    record,
                    status="failed",
                    error=render_execution_error(exc),
                )
        else:
            if record.control.cancel_requested:
                await self._complete(record, status="cancelled", result=result)
            elif result.status == "failed":
                await self._complete(record, status="failed", result=result)
            else:
                await self._complete(record, status="succeeded", result=result)

    def _task_done(self, execution_id: UUID, task: asyncio.Task[None]) -> None:
        record = self._executions.get(execution_id)
        if record is None or record.status in _TERMINAL_STATUSES:
            return
        if record.control.cancel_requested or task.cancelled():
            asyncio.create_task(self._complete(record, status="cancelled"))
            return
        exception = task.exception()
        if exception is None:
            asyncio.create_task(
                self._complete(
                    record,
                    status="failed",
                    error="Run execution ended without a terminal result",
                )
            )
            return
        asyncio.create_task(
            self._complete(
                record,
                status="failed",
                error=render_execution_error(exception),
            )
        )

    async def _complete(
        self,
        record: _RunExecutionRecord,
        *,
        status: Literal["cancelled", "succeeded", "failed"],
        result: GraphExecutionResult | None = None,
        error: str | None = None,
    ) -> None:
        async with record.transition_lock:
            if record.status in _TERMINAL_STATUSES or record.terminal is not None:
                return
            history_error: str | None = None
            if (
                record.cleanup_confirmed
                and record.history_execution is not None
                and self._execution_history is not None
            ):
                history_failure: Exception | None = None
                for attempt in range(2):
                    try:
                        await self._execution_history.complete(
                            record.workspace_id,
                            record.history_execution,
                            status=status,
                            result=result,
                            error=error,
                        )
                    except Exception as exc:
                        history_failure = exc
                        try:
                            persisted = await self._execution_history.get_for_graph(
                                record.workspace_id,
                                record.history_execution.graph_id,
                                record.execution_id,
                            )
                        except Exception as reconciliation_exc:
                            history_failure = reconciliation_exc
                        else:
                            expected_workflow_run_id = (
                                result.workflow_run_id if result is not None else None
                            )
                            if (
                                persisted is not None
                                and persisted.execution.status == status
                                and persisted.execution.workflow_run_id
                                == expected_workflow_run_id
                                and persisted.execution.error == error
                            ):
                                history_failure = None
                                break
                        if attempt == 0:
                            await asyncio.sleep(0)
                    else:
                        history_failure = None
                        break
                if history_failure is not None:
                    history_error = (
                        "Execution history could not record the terminal result: "
                        f"{render_execution_error(history_failure)}"
                    )
            if (
                record.cleanup_confirmed
                and record.activity_registration_attempted
                and self._execution_history is not None
            ):
                for attempt in range(2):
                    try:
                        await self._execution_history.release_transient(
                            record.execution_id, self._transient_owner_id
                        )
                    except Exception as exc:
                        history_error = (
                            f"Could not release transient execution {record.execution_id}: "
                            f"{render_execution_error(exc)}"
                        )
                        if attempt == 0:
                            await asyncio.sleep(0)
                    else:
                        history_error = None
                        break
                if history_error is not None:
                    logger.error(
                        "%s; activity marker retained for maintenance", history_error
                    )
            if not record.cleanup_confirmed:
                history_error = (
                    f"Execution {record.execution_id} remains active for maintenance "
                    "until sandbox cleanup is confirmed"
                )
            active_node_id = record.control.active_node_id
            if active_node_id is not None:
                record.control.finish_outer_node(active_node_id)
            final_error = error
            if history_error is not None:
                if final_error is None:
                    final_error = history_error
                else:
                    final_error = f"{final_error} <- caused by {history_error}"
            record.status = status
            record.task = None
            admission_lease = record.admission_lease
            record.admission_lease = None
            if admission_lease is not None:
                admission_lease.release()
            record.terminal = _TerminalOutcome(
                status=status,
                result=result,
                error=final_error,
            )
            record.control.publish_execution_status(status, None)
            await self._publish_cleared(record, status=status)
            self._terminal_order.append(record.execution_id)
            while len(self._terminal_order) > self._terminal_retention:
                expired_id = self._terminal_order.popleft()
                self._executions.pop(expired_id, None)
            self._dispatch_wake.set()

    def _snapshot_locked(self, record: _RunExecutionRecord) -> RunExecutionSnapshot:
        queue_position = None
        if record.status == "queued" and record.task is None:
            try:
                queue_position = (
                    self._pending_execution_ids.index(record.execution_id) + 1
                )
            except ValueError:
                queue_position = None
        return record.snapshot(queue_position)

    def _existing_execution_snapshot_locked(
        self,
        execution: GraphExecution,
    ) -> RunExecutionSnapshot:
        record = self._executions.get(execution.execution_id)
        if record is not None:
            return self._snapshot_locked(record)
        return RunExecutionSnapshot(
            workspace_id=execution.workspace_id,
            execution_id=execution.execution_id,
            status=execution.status,
            active_node_id=None,
            result=None,
            error=execution.error,
            queue_position=None,
        )

    @staticmethod
    def _normalize_idempotency_key(idempotency_key: str) -> str:
        normalized = idempotency_key.strip()
        if normalized == "":
            raise ValueError("Execution idempotency key must not be blank")
        if len(normalized) > 255:
            raise ValueError("Execution idempotency key must be at most 255 characters")
        return normalized

    def _pending_count_locked(self) -> int:
        return sum(
            1
            for execution_id in self._pending_execution_ids
            if (
                (record := self._executions.get(execution_id)) is not None
                and record.status == "queued"
                and record.task is None
            )
        )

    def _insert_pending_locked(self, record: _RunExecutionRecord) -> None:
        history = record.history_execution
        if history is None:
            raise RuntimeError("Only durable saved-graph executions may be queued")
        key = (history.created_at, record.execution_id.int)
        position = 0
        while position < len(self._pending_execution_ids):
            queued = self._executions[self._pending_execution_ids[position]]
            queued_history = queued.history_execution
            if queued_history is None:
                raise RuntimeError("Pending execution has no durable history record")
            queued_key = (queued_history.created_at, queued.execution_id.int)
            if key < queued_key:
                break
            position += 1
        self._pending_execution_ids.insert(position, record.execution_id)

    def _remove_pending_locked(self, execution_id: UUID) -> None:
        try:
            self._pending_execution_ids.remove(execution_id)
        except ValueError:
            pass

    def _ensure_dispatcher_locked(self) -> None:
        task = self._dispatcher_task
        if task is not None and not task.done():
            return
        self._dispatcher_task = asyncio.create_task(
            self._dispatch(),
            name="grafy-execution-dispatcher",
        )
        self._dispatcher_task.add_done_callback(self._dispatcher_done)

    async def _dispatch(self) -> None:
        while True:
            await self._dispatch_wake.wait()
            self._dispatch_wake.clear()
            while True:
                async with self._lock:
                    if self._shutting_down:
                        return
                    record: _RunExecutionRecord | None = None
                    while self._pending_execution_ids:
                        execution_id = self._pending_execution_ids[0]
                        record = self._executions.get(execution_id)
                        if (
                            record is not None
                            and record.status == "queued"
                            and record.task is None
                        ):
                            break
                        self._pending_execution_ids.pop(0)
                    if not self._pending_execution_ids:
                        break
                    if record is None:
                        continue
                    admission_lease = self._admission_limiter.try_acquire()
                    if admission_lease is None:
                        break
                    self._pending_execution_ids.pop(0)
                    record.admission_lease = admission_lease
                    history = record.history_execution
                    if history is None:
                        raise RuntimeError(
                            "Dispatched execution has no durable history record"
                        )
                    wait_seconds = max(
                        0.0,
                        (datetime.now(UTC) - history.created_at).total_seconds(),
                    )
                    self._dispatched_graphs += 1
                    self._total_dispatch_wait_seconds += wait_seconds
                    self._maximum_dispatch_wait_seconds = max(
                        self._maximum_dispatch_wait_seconds,
                        wait_seconds,
                    )
                    logger.info(
                        "execution_dispatched wait_seconds=%.6f pending_graphs=%s "
                        "active_executions=%s",
                        wait_seconds,
                        self._pending_count_locked(),
                        self._admission_limiter.diagnostics().active_executions,
                    )
                    self._create_run_task_locked(record)

    def _create_run_task_locked(
        self,
        record: _RunExecutionRecord,
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(
            self._run(record.execution_id),
            name=f"grafy-run-{record.execution_id}",
        )
        record.task = task
        task.add_done_callback(
            lambda completed, owned_id=record.execution_id: self._task_done(
                owned_id,
                completed,
            )
        )
        return task

    def _dispatcher_done(self, task: asyncio.Task[None]) -> None:
        if task.cancelled() or self._shutting_down:
            return
        exception = task.exception()
        if exception is not None:
            logger.critical(
                "execution_dispatcher_stopped",
                exc_info=(type(exception), exception, exception.__traceback__),
            )
            asyncio.create_task(self._restart_dispatcher(task))

    async def _restart_dispatcher(self, stopped_task: asyncio.Task[None]) -> None:
        async with self._lock:
            if self._shutting_down or self._dispatcher_task is not stopped_task:
                return
            self._dispatcher_task = None
            self._ensure_dispatcher_locked()
            self._dispatch_wake.set()

    async def _publish_active(self, record: _RunExecutionRecord) -> None:
        hub = self._graph_room_hub
        history = record.history_execution
        summary = record.active_summary()
        if hub is None or history is None or summary is None:
            return
        try:
            await hub.publish_execution_active(
                workspace_id=record.workspace_id,
                graph_id=history.graph_id,
                message=ExecutionActiveMessage(execution=summary),
            )
        except Exception:
            logger.exception(
                "active_execution_publish_failed workspace_id=%s graph_id=%s "
                "execution_id=%s",
                record.workspace_id,
                history.graph_id,
                record.execution_id,
            )

    async def _publish_cleared(
        self,
        record: _RunExecutionRecord,
        *,
        status: Literal["cancelled", "succeeded", "failed"],
    ) -> None:
        hub = self._graph_room_hub
        history = record.history_execution
        if hub is None or history is None:
            return
        terminal = record.terminal
        error = terminal.error if terminal is not None else None
        bounded_error = None if error is None else error[:2000]
        try:
            await hub.publish_execution_cleared(
                workspace_id=record.workspace_id,
                graph_id=history.graph_id,
                message=ExecutionClearedMessage(
                    execution_id=record.execution_id,
                    status=status,
                    graph_revision=history.graph_revision,
                    error=bounded_error,
                ),
            )
        except Exception:
            logger.exception(
                "active_execution_clear_publish_failed workspace_id=%s graph_id=%s "
                "execution_id=%s",
                record.workspace_id,
                history.graph_id,
                record.execution_id,
            )


def _contains_cancellation(exception: BaseException) -> bool:
    seen: set[int] = set()
    current: BaseException | None = exception
    while current is not None and id(current) not in seen:
        if isinstance(current, asyncio.CancelledError):
            return True
        seen.add(id(current))
        if current.__cause__ is not None:
            current = current.__cause__
            continue
        current = None if current.__suppress_context__ else current.__context__
    return False


__all__ = [
    "RunExecutionEventBatch",
    "RunExecutionEventSubscription",
    "RunExecutionCapacityError",
    "RunExecutionIdempotencyConflictError",
    "RunExecutionQueueFullError",
    "RunExecutionManager",
    "RunExecutionQueueDiagnostics",
    "RunExecutionSnapshot",
    "RunExecutionStatus",
]
