from grafy_api.execution.requests import (
    ArtifactConversionRequest,
    ExecutionIdentifier,
    FieldProjectionRequest,
    InputPlugIdentifier,
    InvocationIndex,
    MAX_EXECUTION_NODE_PATH_LENGTH,
    PinnedOutputRequest,
    RunEdgeRequest,
    RunInputPlugRequest,
    RunNodeRequest,
    RunRequest,
)
from grafy_api.execution.events import (
    ExecutionStatusEvent,
    NodeExecutionEventBase,
    NodeExecutionEventStatus,
    NodeProgressEvent,
    NodeStatusEvent,
    RunExecutionEvent,
    RunExecutionEventBase,
    RunExecutionStatus,
)

import base64
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
    ValidationError,
)

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence
from grafy_core.domain.execution_history import (
    GraphExecution,
    GraphExecutionCursor,
    GraphExecutionDetail,
    GraphExecutionNodeResult,
    GraphExecutionNodeStatus,
    GraphExecutionPage,
    GraphExecutionScope,
    GraphExecutionStatus,
)

from grafy_api.v1.models import (
    ApiResponse,
)
from grafy_api.v1.routes.artifacts.models import ArtifactSummaryResponse


class SavedGraphExecutionRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class RunPortOutputResponse(ApiResponse):
    port: str
    kind: Literal["single", "sequence"]
    value: ArtifactRef | ArtifactRefSequence
    artifacts: list[ArtifactSummaryResponse]


class RunNodeResponse(ApiResponse):
    node_id: str
    status: Literal["succeeded", "failed", "skipped"]
    error: str | None
    outputs: list[RunPortOutputResponse]


class RunResponse(ApiResponse):
    status: Literal["succeeded", "failed"]
    node_runs: list[RunNodeResponse]


class RunExecutionResponse(ApiResponse):
    execution_id: UUID
    status: Literal[
        "queued",
        "running",
        "cancelling",
        "cancelled",
        "succeeded",
        "failed",
    ]
    active_node_id: str | None
    result: RunResponse | None
    error: str | None
    queue_position: int | None = Field(default=None, ge=1)


class RunExecutionCapacityErrorDetail(ApiResponse):
    error_code: Literal["execution_capacity_exceeded"]
    message: str
    max_active_executions: int = Field(ge=1)


class RunExecutionCapacityErrorResponse(ApiResponse):
    detail: RunExecutionCapacityErrorDetail


class RunExecutionQueueFullErrorDetail(ApiResponse):
    error_code: Literal["execution_queue_full"]
    message: str
    max_pending_graphs: int = Field(ge=1)


class RunExecutionQueueFullErrorResponse(ApiResponse):
    detail: RunExecutionQueueFullErrorDetail


class RunExecutionIdempotencyConflictErrorDetail(ApiResponse):
    error_code: Literal["execution_idempotency_conflict"]
    message: str
    idempotency_key: str
    execution_id: UUID


class RunExecutionIdempotencyConflictErrorResponse(ApiResponse):
    detail: RunExecutionIdempotencyConflictErrorDetail


class GraphMaterializationsResponse(ApiResponse):
    graph_id: UUID
    graph_revision: int
    node_runs: list[RunNodeResponse]


class GraphExecutionCursorModel(BaseModel):
    created_at: datetime
    execution_id: UUID

    @classmethod
    def decode(cls, value: str) -> GraphExecutionCursor:
        try:
            padding = "=" * (-len(value) % 4)
            payload = base64.urlsafe_b64decode(value + padding)
            cursor = cls.model_validate_json(payload)
            return GraphExecutionCursor(
                created_at=cursor.created_at,
                execution_id=cursor.execution_id,
            )
        except (ValueError, ValidationError) as exc:
            raise ValueError("Invalid execution history cursor") from exc

    @classmethod
    def encode(cls, cursor: GraphExecutionCursor) -> str:
        payload = cls(
            created_at=cursor.created_at,
            execution_id=cursor.execution_id,
        ).model_dump_json()
        return (
            base64.urlsafe_b64encode(payload.encode("utf-8"))
            .decode("ascii")
            .rstrip("=")
        )


class GraphExecutionSummaryResponse(ApiResponse):
    execution_id: UUID
    graph_id: UUID
    graph_revision: int
    scope: GraphExecutionScope
    status: GraphExecutionStatus
    requested_node_ids: list[str]
    node_count: int
    artifact_count: int
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    workflow_run_id: UUID | None
    error: str | None

    @classmethod
    def from_execution(
        cls,
        execution: GraphExecution,
        *,
        node_count: int,
        artifact_count: int,
    ) -> "GraphExecutionSummaryResponse":
        return cls(
            execution_id=execution.execution_id,
            graph_id=execution.graph_id,
            graph_revision=execution.graph_revision,
            scope=execution.scope,
            status=execution.status,
            requested_node_ids=list(execution.requested_node_ids),
            node_count=node_count,
            artifact_count=artifact_count,
            created_at=execution.created_at,
            started_at=execution.started_at,
            finished_at=execution.finished_at,
            workflow_run_id=execution.workflow_run_id,
            error=execution.error,
        )


class GraphExecutionListResponse(ApiResponse):
    items: list[GraphExecutionSummaryResponse]
    next_cursor: str | None

    @classmethod
    def from_page(cls, page: GraphExecutionPage) -> "GraphExecutionListResponse":
        return cls(
            items=[
                GraphExecutionSummaryResponse.from_execution(
                    item.execution,
                    node_count=item.node_count,
                    artifact_count=item.artifact_count,
                )
                for item in page.items
            ],
            next_cursor=(
                GraphExecutionCursorModel.encode(page.next_cursor)
                if page.next_cursor is not None
                else None
            ),
        )


class GraphExecutionNodeResultResponse(ApiResponse):
    node_id: str
    position: int
    status: GraphExecutionNodeStatus
    error: str | None
    completed_at: datetime
    outputs: list[RunPortOutputResponse]
    diagnostics: dict[str, object] | None = None

    @classmethod
    def from_result(
        cls,
        result: GraphExecutionNodeResult,
        *,
        outputs: list[RunPortOutputResponse],
    ) -> "GraphExecutionNodeResultResponse":
        return cls(
            node_id=result.node_id,
            position=result.position,
            status=result.status,
            error=result.error,
            completed_at=result.completed_at,
            outputs=outputs,
            diagnostics=result.diagnostics,
        )


class GraphExecutionDetailResponse(GraphExecutionSummaryResponse):
    node_results: list[GraphExecutionNodeResultResponse]

    @classmethod
    def from_detail(
        cls,
        detail: GraphExecutionDetail,
        *,
        node_results: list[GraphExecutionNodeResultResponse],
    ) -> "GraphExecutionDetailResponse":
        execution = detail.execution
        return cls(
            execution_id=execution.execution_id,
            graph_id=execution.graph_id,
            graph_revision=execution.graph_revision,
            scope=execution.scope,
            status=execution.status,
            requested_node_ids=list(execution.requested_node_ids),
            node_count=len(detail.node_results),
            artifact_count=sum(result.artifact_count for result in detail.node_results),
            created_at=execution.created_at,
            started_at=execution.started_at,
            finished_at=execution.finished_at,
            workflow_run_id=execution.workflow_run_id,
            error=execution.error,
            node_results=node_results,
        )


__all__ = [
    "ArtifactConversionRequest",
    "ExecutionStatusEvent",
    "ExecutionIdentifier",
    "FieldProjectionRequest",
    "GraphExecutionCursorModel",
    "GraphExecutionDetailResponse",
    "GraphExecutionListResponse",
    "GraphExecutionNodeResultResponse",
    "GraphExecutionSummaryResponse",
    "GraphMaterializationsResponse",
    "InputPlugIdentifier",
    "InvocationIndex",
    "MAX_EXECUTION_NODE_PATH_LENGTH",
    "NodeExecutionEventBase",
    "NodeExecutionEventStatus",
    "NodeProgressEvent",
    "NodeStatusEvent",
    "PinnedOutputRequest",
    "RunEdgeRequest",
    "RunExecutionEvent",
    "RunExecutionEventBase",
    "RunExecutionCapacityErrorDetail",
    "RunExecutionCapacityErrorResponse",
    "RunExecutionQueueFullErrorDetail",
    "RunExecutionQueueFullErrorResponse",
    "RunExecutionIdempotencyConflictErrorDetail",
    "RunExecutionIdempotencyConflictErrorResponse",
    "RunExecutionResponse",
    "RunExecutionStatus",
    "RunInputPlugRequest",
    "RunNodeRequest",
    "RunNodeResponse",
    "RunPortOutputResponse",
    "RunRequest",
    "RunResponse",
    "SavedGraphExecutionRequest",
]
