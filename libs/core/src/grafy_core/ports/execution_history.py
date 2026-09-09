from datetime import datetime
from typing import Protocol
from uuid import UUID

from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.domain.execution_history import (
    GraphExecution,
    GraphExecutionCursor,
    GraphExecutionDetail,
    GraphExecutionNodeResult,
    GraphExecutionPage,
    GraphExecutionStatus,
)


class GraphExecutionHistoryRepositoryPort(Protocol):
    async def add(self, execution: GraphExecution) -> None: ...

    async def update(self, execution: GraphExecution) -> None: ...

    async def add_node_result(self, result: GraphExecutionNodeResult) -> None: ...

    async def get(
        self,
        workspace_id: UUID,
        execution_id: UUID,
    ) -> GraphExecutionDetail | None: ...

    async def list_for_graph(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        *,
        limit: int,
        cursor: GraphExecutionCursor | None = None,
        graph_revision: int | None = None,
        status: GraphExecutionStatus | None = None,
        node_id: str | None = None,
    ) -> GraphExecutionPage: ...

    async def find_active_execution_id(
        self,
        workspace_id: UUID,
        graph_id: UUID,
    ) -> UUID | None:
        """Return the identity of the graph's queued, running, or cancelling execution."""
        ...

    async def list_queued(self) -> tuple[GraphExecution, ...]: ...

    async def get_by_idempotency_key(
        self,
        workspace_id: UUID,
        idempotency_key: str,
    ) -> GraphExecution | None: ...

    async def claim_queued(
        self,
        workspace_id: UUID,
        execution_id: UUID,
        *,
        started_at: datetime,
    ) -> bool: ...

    async def interrupt_started(
        self,
        *,
        finished_at: datetime,
        error: str,
    ) -> tuple[GraphExecution, ...]: ...


class ExecutionHistoryUnitOfWorkPort(UnitOfWorkPort, Protocol):
    @property
    def execution_history(self) -> GraphExecutionHistoryRepositoryPort: ...


__all__ = [
    "ExecutionHistoryUnitOfWorkPort",
    "GraphExecutionHistoryRepositoryPort",
]
