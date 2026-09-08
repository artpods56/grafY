from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    Field,
    StringConstraints,
    model_validator,
)

from grafy_core.nodes import (
    MAX_NODE_PROGRESS_COUNTER,
    MAX_NODE_PROGRESS_MESSAGE_LENGTH,
)

from grafy_api.v1.models import (
    ApiResponse,
)


from grafy_api.execution.requests import (
    ExecutionIdentifier,
    InvocationIndex,
    MAX_EXECUTION_NODE_PATH_LENGTH,
)


type RunExecutionStatus = Literal[
    "queued",
    "running",
    "cancelling",
    "cancelled",
    "succeeded",
    "failed",
]


class RunExecutionEventBase(ApiResponse):
    sequence: int = Field(ge=1)
    execution_id: UUID
    occurred_at: datetime


class ExecutionStatusEvent(RunExecutionEventBase):
    kind: Literal["execution.status"] = "execution.status"
    status: RunExecutionStatus
    active_node_id: ExecutionIdentifier | None


type NodeExecutionEventStatus = Literal[
    "running",
    "succeeded",
    "failed",
    "skipped",
]


class NodeExecutionEventBase(RunExecutionEventBase):
    node_path: list[ExecutionIdentifier] = Field(
        min_length=1,
        max_length=MAX_EXECUTION_NODE_PATH_LENGTH,
    )
    node_id: ExecutionIdentifier
    node_run_id: UUID | None
    invocation_index: InvocationIndex | None = None
    invocation_path: list[InvocationIndex] = Field(
        default_factory=list,
        max_length=MAX_EXECUTION_NODE_PATH_LENGTH,
    )


class NodeStatusEvent(NodeExecutionEventBase):
    kind: Literal["node.status"] = "node.status"
    status: NodeExecutionEventStatus


class NodeProgressEvent(NodeExecutionEventBase):
    kind: Literal["node.progress"] = "node.progress"
    message: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=MAX_NODE_PROGRESS_MESSAGE_LENGTH,
        ),
    ]
    current: int | None = Field(
        default=None,
        ge=0,
        le=MAX_NODE_PROGRESS_COUNTER,
    )
    total: int | None = Field(
        default=None,
        ge=0,
        le=MAX_NODE_PROGRESS_COUNTER,
    )

    @model_validator(mode="after")
    def validate_progress(self) -> "NodeProgressEvent":
        if (
            self.current is not None
            and self.total is not None
            and self.current > self.total
        ):
            raise ValueError("Node progress current value must not exceed total")
        return self


type RunExecutionEvent = Annotated[
    ExecutionStatusEvent | NodeStatusEvent | NodeProgressEvent,
    Field(discriminator="kind"),
]
