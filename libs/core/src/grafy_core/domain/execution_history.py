from dataclasses import dataclass, field
from copy import deepcopy
from datetime import UTC, datetime
from typing import Literal, cast
from uuid import UUID

from grafy_core.artifacts import ArtifactRefSequence, JsonObject
from grafy_core.domain.artifact_outputs import (
    ArtifactOutputValue,
    artifact_outputs_from_storage,
    artifact_outputs_to_storage,
    normalize_artifact_outputs,
)


type GraphExecutionStatus = Literal[
    "queued",
    "running",
    "cancelling",
    "cancelled",
    "succeeded",
    "failed",
]
type GraphExecutionNodeStatus = Literal["succeeded", "failed", "skipped"]
type GraphExecutionScope = Literal[
    "all",
    "selected",
    "selected-with-dependencies",
]

_EXECUTION_STATUSES = frozenset(
    {"queued", "running", "cancelling", "cancelled", "succeeded", "failed"}
)
_TERMINAL_EXECUTION_STATUSES = frozenset({"cancelled", "succeeded", "failed"})
_NODE_STATUSES = frozenset({"succeeded", "failed", "skipped"})
_EXECUTION_SCOPES = frozenset({"all", "selected", "selected-with-dependencies"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _require_aware_timestamp(value: datetime | None, label: str) -> None:
    if value is not None and value.tzinfo is None:
        raise ValueError(f"Graph execution {label} must be timezone-aware")


def _validated_json_object(value: object, label: str) -> JsonObject:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    mapping = cast(dict[object, object], value)
    if any(not isinstance(key, str) for key in mapping):
        raise ValueError(f"{label} must be a JSON object")
    return cast(JsonObject, value)


@dataclass(frozen=True, slots=True)
class ActiveGraphExecution:
    """Non-sensitive identity and state used by execution maintenance checks."""

    execution_id: UUID
    status: Literal["queued", "running", "cancelling"]


@dataclass(frozen=True, slots=True)
class TransientExecution:
    """Durable activity identity; no graph history or executable payload."""

    execution_id: UUID
    workspace_id: UUID
    owner_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        _require_aware_timestamp(self.created_at, "creation timestamp")


@dataclass
class GraphExecution:
    workspace_id: UUID
    execution_id: UUID
    graph_id: UUID
    graph_revision: int
    status: GraphExecutionStatus
    scope: GraphExecutionScope = "all"
    requested_node_ids: tuple[str, ...] = ()
    submitted_request: JsonObject | None = None
    idempotency_key: str | None = None
    submitted_by_actor_id: UUID | None = None
    created_at: datetime = field(default_factory=_utc_now)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    workflow_run_id: UUID | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if self.graph_revision < 1:
            raise ValueError("Graph execution revision must be at least 1")
        if self.status not in _EXECUTION_STATUSES:
            raise ValueError(f"Unknown graph execution status {self.status!r}")
        if self.scope not in _EXECUTION_SCOPES:
            raise ValueError(f"Unknown graph execution scope {self.scope!r}")

        normalized_node_ids: list[str] = []
        seen_node_ids: set[str] = set()
        for raw_node_id in self.requested_node_ids:
            node_id = raw_node_id.strip()
            if node_id == "":
                raise ValueError("Requested graph execution node id must not be blank")
            if len(node_id) > 255:
                raise ValueError(
                    "Requested graph execution node id must be at most 255 characters"
                )
            if node_id in seen_node_ids:
                raise ValueError(
                    f"Duplicate requested graph execution node id {node_id!r}"
                )
            seen_node_ids.add(node_id)
            normalized_node_ids.append(node_id)
        self.requested_node_ids = tuple(normalized_node_ids)
        if self.submitted_request is not None:
            self.submitted_request = deepcopy(
                _validated_json_object(
                    self.submitted_request,
                    "Graph execution submitted request",
                )
            )
        if self.idempotency_key is not None:
            self.idempotency_key = self.idempotency_key.strip()
            if self.idempotency_key == "":
                raise ValueError("Graph execution idempotency key must not be blank")
            if len(self.idempotency_key) > 255:
                raise ValueError(
                    "Graph execution idempotency key must be at most 255 characters"
                )

        _require_aware_timestamp(self.created_at, "creation timestamp")
        _require_aware_timestamp(self.started_at, "start timestamp")
        _require_aware_timestamp(self.finished_at, "finish timestamp")
        if self.started_at is not None and self.started_at < self.created_at:
            raise ValueError("Graph execution cannot start before it is created")
        if self.finished_at is not None and self.finished_at < self.created_at:
            raise ValueError("Graph execution cannot finish before it is created")
        if (
            self.started_at is not None
            and self.finished_at is not None
            and self.finished_at < self.started_at
        ):
            raise ValueError("Graph execution cannot finish before it starts")
        if self.status in _TERMINAL_EXECUTION_STATUSES and self.finished_at is None:
            raise ValueError(
                f"Terminal graph execution status {self.status!r} requires finished_at"
            )
        if (
            self.status not in _TERMINAL_EXECUTION_STATUSES
            and self.finished_at is not None
        ):
            raise ValueError(
                f"Non-terminal graph execution status {self.status!r} cannot have "
                "finished_at"
            )

    def transition_to_running(self) -> None:
        """Advance a queued execution into running, stamping its start time.

        Only a queued execution may start; this keeps the start timestamp
        correlated with the running status and rejects running-without-start or
        queued-with-start states.
        """

        if self.status != "queued":
            raise ValueError(
                f"Graph execution cannot start from status {self.status!r}"
            )
        self.status = "running"
        self.started_at = _utc_now()

    def transition_to_cancelling(self) -> None:
        """Request cancellation from a queued or running execution."""

        if self.status not in {"queued", "running"}:
            raise ValueError(
                f"Graph execution cannot cancel from status {self.status!r}"
            )
        self.status = "cancelling"

    def transition_to_terminal(
        self,
        status: GraphExecutionStatus,
        *,
        workflow_run_id: UUID | None,
        error: str | None,
    ) -> None:
        """Advance to one terminal outcome, stamping finish time and workflow id.

        The terminal status, finish timestamp, workflow identity, and error
        move together so a terminal record always carries a complete outcome.
        """

        if status not in _TERMINAL_EXECUTION_STATUSES:
            raise ValueError(f"Execution completion status {status!r} is not terminal")
        if self.status == "cancelling" and status != "cancelled":
            raise ValueError(
                "A cancelling graph execution can only complete as cancelled"
            )
        self.status = status
        self.finished_at = _utc_now()
        self.error = error
        self.workflow_run_id = workflow_run_id


@dataclass
class GraphExecutionNodeResult:
    workspace_id: UUID
    execution_id: UUID
    node_id: str
    position: int
    status: GraphExecutionNodeStatus
    outputs: dict[str, ArtifactOutputValue]
    error: str | None = None
    completed_at: datetime = field(default_factory=_utc_now)
    diagnostics: JsonObject | None = None
    artifact_count: int = field(init=False)

    def __post_init__(self) -> None:
        self.node_id = self.node_id.strip()
        if self.node_id == "":
            raise ValueError("Graph execution result node id must not be blank")
        if len(self.node_id) > 255:
            raise ValueError(
                "Graph execution result node id must be at most 255 characters"
            )
        if self.position < 0:
            raise ValueError("Graph execution result position must not be negative")
        if self.status not in _NODE_STATUSES:
            raise ValueError(f"Unknown graph execution node status {self.status!r}")
        _require_aware_timestamp(self.completed_at, "node completion timestamp")
        if self.diagnostics is not None:
            _validated_json_object(
                self.diagnostics,
                "Graph execution node result diagnostics",
            )
        self.outputs = normalize_artifact_outputs(self.outputs)
        self.artifact_count = sum(
            len(output.item_refs) if isinstance(output, ArtifactRefSequence) else 1
            for output in self.outputs.values()
        )

    def storage_envelopes(self) -> list[dict[str, object]]:
        return artifact_outputs_to_storage(self.outputs)

    @staticmethod
    def outputs_from_storage(value: object) -> dict[str, ArtifactOutputValue]:
        return artifact_outputs_from_storage(value)


@dataclass(frozen=True, slots=True)
class GraphExecutionDetail:
    execution: GraphExecution
    node_results: tuple[GraphExecutionNodeResult, ...]


@dataclass(frozen=True, slots=True)
class GraphExecutionCursor:
    created_at: datetime
    execution_id: UUID

    def __post_init__(self) -> None:
        _require_aware_timestamp(self.created_at, "cursor timestamp")


@dataclass(frozen=True, slots=True)
class GraphExecutionListItem:
    execution: GraphExecution
    node_count: int
    artifact_count: int

    def __post_init__(self) -> None:
        if self.node_count < 0:
            raise ValueError("Graph execution node count must not be negative")
        if self.artifact_count < 0:
            raise ValueError("Graph execution artifact count must not be negative")


@dataclass(frozen=True, slots=True)
class GraphExecutionPage:
    items: tuple[GraphExecutionListItem, ...]
    next_cursor: GraphExecutionCursor | None


__all__ = [
    "ActiveGraphExecution",
    "GraphExecution",
    "GraphExecutionCursor",
    "GraphExecutionDetail",
    "GraphExecutionListItem",
    "GraphExecutionNodeResult",
    "GraphExecutionNodeStatus",
    "GraphExecutionPage",
    "GraphExecutionScope",
    "GraphExecutionStatus",
]
