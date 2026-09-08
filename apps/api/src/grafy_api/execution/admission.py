"""Process-wide admission budget for top-level graph executions."""

from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal
from uuid import UUID, uuid4


class RunExecutionCapacityError(RuntimeError):
    """Raised before admission when the process execution budget is exhausted."""

    error_code: Literal["execution_capacity_exceeded"] = "execution_capacity_exceeded"

    def __init__(self, max_active_executions: int) -> None:
        self.max_active_executions = max_active_executions
        super().__init__(
            "Run execution capacity is exhausted; "
            f"the process already owns {max_active_executions} active executions"
        )


class RunExecutionQueueFullError(RuntimeError):
    """Raised before persistence when the durable pending queue is full."""

    error_code: Literal["execution_queue_full"] = "execution_queue_full"

    def __init__(self, max_pending_graphs: int) -> None:
        self.max_pending_graphs = max_pending_graphs
        super().__init__(
            "Run execution queue is full; "
            f"the process already owns {max_pending_graphs} pending executions"
        )


@dataclass(frozen=True, slots=True)
class ExecutionAdmissionDiagnostics:
    max_active_executions: int
    active_executions: int
    rejected_acquisitions: int


@dataclass(frozen=True, slots=True)
class ExecutionAdmissionLease:
    _limiter: "ExecutionAdmissionLimiter" = field(repr=False)
    _lease_id: UUID = field(repr=False)

    def release(self) -> None:
        self._limiter.release(self._lease_id)


class ExecutionAdmissionLimiter:
    """Reject top-level work above a shared process-wide execution budget."""

    def __init__(self, max_active_executions: int) -> None:
        if max_active_executions < 1:
            raise ValueError("Maximum active executions must be at least one")
        self._max_active_executions = max_active_executions
        self._active_lease_ids: set[UUID] = set()
        self._rejected_acquisitions = 0
        self._lock = Lock()
        self._capacity_listener: Callable[[], None] | None = None

    def acquire(self) -> ExecutionAdmissionLease:
        lease = self.try_acquire()
        if lease is None:
            raise RunExecutionCapacityError(self._max_active_executions)
        return lease

    def try_acquire(self) -> ExecutionAdmissionLease | None:
        with self._lock:
            if len(self._active_lease_ids) >= self._max_active_executions:
                self._rejected_acquisitions += 1
                return None
            lease_id = uuid4()
            self._active_lease_ids.add(lease_id)
        return ExecutionAdmissionLease(self, lease_id)

    def diagnostics(self) -> ExecutionAdmissionDiagnostics:
        with self._lock:
            return ExecutionAdmissionDiagnostics(
                max_active_executions=self._max_active_executions,
                active_executions=len(self._active_lease_ids),
                rejected_acquisitions=self._rejected_acquisitions,
            )

    def bind_capacity_listener(self, listener: Callable[[], None]) -> None:
        with self._lock:
            if self._capacity_listener is not None:
                raise RuntimeError(
                    "Execution admission capacity listener is already bound"
                )
            self._capacity_listener = listener

    def release(self, lease_id: UUID) -> None:
        with self._lock:
            released = lease_id in self._active_lease_ids
            self._active_lease_ids.discard(lease_id)
            listener = self._capacity_listener
        if released and listener is not None:
            listener()


__all__ = [
    "ExecutionAdmissionDiagnostics",
    "ExecutionAdmissionLease",
    "ExecutionAdmissionLimiter",
    "RunExecutionCapacityError",
    "RunExecutionQueueFullError",
]
