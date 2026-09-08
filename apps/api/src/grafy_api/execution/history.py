from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from grafy_core.application.saved_graphs import SavedGraphService
from grafy_core.artifacts import JsonObject
from grafy_core.domain.execution_history import (
    GraphExecution,
    GraphExecutionCursor,
    GraphExecutionDetail,
    GraphExecutionNodeResult,
    GraphExecutionPage,
    GraphExecutionScope,
    GraphExecutionStatus,
)
from grafy_core.domain.errors import (
    NotFoundError,
)
from grafy_core.domain.identity import WorkspaceCapability
from grafy_core.ports.execution_history import ExecutionHistoryUnitOfWorkPort


if TYPE_CHECKING:
    from grafy_api.execution.models import GraphExecutionResult


class ExecutionHistoryService:
    """Own the durable lifecycle and browsing of saved-graph executions."""

    def __init__(
        self,
        unit_of_work: ExecutionHistoryUnitOfWorkPort,
        saved_graphs: SavedGraphService | None,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._saved_graphs = saved_graphs

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
        if self._saved_graphs is None:
            raise RuntimeError(
                "Saved graph context is not configured for execution history"
            )
        await self._saved_graphs.get_revision(
            workspace_id,
            graph_id,
            graph_revision,
        )
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
        async with self._unit_of_work as unit_of_work:
            # graph_executions carries the one-active-execution invariant via a
            # partial unique index; a conflicting start raises from the insert.
            await unit_of_work.execution_history.add(execution)
            await unit_of_work.commit()
        return execution

    async def get_by_idempotency_key(
        self,
        workspace_id: UUID,
        idempotency_key: str,
    ) -> GraphExecution | None:
        async with self._unit_of_work as unit_of_work:
            return await unit_of_work.execution_history.get_by_idempotency_key(
                workspace_id,
                idempotency_key,
            )

    async def can_dispatch_recovered(self, execution: GraphExecution) -> bool:
        actor_id = execution.submitted_by_actor_id
        if actor_id is None:
            return False
        async with self._unit_of_work as unit_of_work:
            identity = getattr(unit_of_work, "identity", None)
            if identity is None:
                raise RuntimeError(
                    "Recovered execution authorization requires an identity-capable "
                    "unit of work"
                )
            membership = await identity.get_membership(
                workspace_id=execution.workspace_id,
                user_id=actor_id,
            )
        return membership is not None and membership.grants(
            WorkspaceCapability.EXECUTE_GRAPH
        )

    async def mark_running(
        self,
        workspace_id: UUID,
        execution: GraphExecution,
    ) -> bool:
        if execution.workspace_id != workspace_id:
            raise NotFoundError("Graph execution", str(execution.execution_id))
        started_at = datetime.now(UTC)
        async with self._unit_of_work as unit_of_work:
            claimed = await unit_of_work.execution_history.claim_queued(
                workspace_id,
                execution.execution_id,
                started_at=started_at,
            )
            await unit_of_work.commit()
        if not claimed:
            return False
        execution.status = "running"
        execution.started_at = started_at
        return True

    async def mark_cancelling(
        self,
        workspace_id: UUID,
        execution: GraphExecution,
    ) -> None:
        if execution.workspace_id != workspace_id:
            raise NotFoundError("Graph execution", str(execution.execution_id))
        execution.transition_to_cancelling()
        async with self._unit_of_work as unit_of_work:
            await unit_of_work.execution_history.update(execution)
            await unit_of_work.commit()

    async def complete(
        self,
        workspace_id: UUID,
        execution: GraphExecution,
        *,
        status: GraphExecutionStatus,
        result: "GraphExecutionResult | None",
        error: str | None,
    ) -> None:
        if execution.workspace_id != workspace_id:
            raise NotFoundError("Graph execution", str(execution.execution_id))
        execution.transition_to_terminal(
            status,
            workflow_run_id=result.workflow_run_id if result is not None else None,
            error=error,
        )
        completed_at = execution.finished_at
        if completed_at is None:
            raise RuntimeError("Graph execution completed without a finish timestamp")

        async with self._unit_of_work as unit_of_work:
            await unit_of_work.execution_history.update(execution)
            if result is not None:
                for position, node_result in enumerate(result.node_results):
                    diagnostics: JsonObject | None = None
                    release = node_result.plugin_release
                    if release is not None:
                        diagnostics = {
                            "plugin_release": {
                                "scope": release.scope.value,
                                "workspace_id": (
                                    None
                                    if release.workspace_id is None
                                    else str(release.workspace_id)
                                ),
                                "slug": release.slug,
                                "revision": release.revision,
                                "source_digest": release.source_digest,
                                "contract_digest": release.contract_digest,
                                "protocol_digest": release.protocol_digest,
                                "descriptor_digest": release.descriptor_digest,
                            },
                        }
                    await unit_of_work.execution_history.add_node_result(
                        GraphExecutionNodeResult(
                            workspace_id=workspace_id,
                            execution_id=execution.execution_id,
                            node_id=node_result.node_id,
                            position=position,
                            status=node_result.status,
                            outputs=dict(node_result.outputs),
                            error=node_result.error,
                            completed_at=completed_at,
                            diagnostics=diagnostics,
                        )
                    )
            await unit_of_work.commit()

    async def get_for_graph(
        self,
        workspace_id: UUID,
        graph_id: UUID,
        execution_id: UUID,
    ) -> GraphExecutionDetail | None:
        async with self._unit_of_work as unit_of_work:
            detail = await unit_of_work.execution_history.get(
                workspace_id,
                execution_id,
            )
        if detail is None or detail.execution.graph_id != graph_id:
            return None
        return detail

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
    ) -> GraphExecutionPage:
        async with self._unit_of_work as unit_of_work:
            return await unit_of_work.execution_history.list_for_graph(
                workspace_id,
                graph_id,
                limit=limit,
                cursor=cursor,
                graph_revision=graph_revision,
                status=status,
                node_id=node_id,
            )

    async def list_queued(self) -> tuple[GraphExecution, ...]:
        async with self._unit_of_work as unit_of_work:
            return await unit_of_work.execution_history.list_queued()

    async def interrupt_started(self) -> int:
        async with self._unit_of_work as unit_of_work:
            interrupted = await unit_of_work.execution_history.interrupt_started(
                finished_at=datetime.now(UTC),
                error=(
                    "Execution was interrupted because the API process stopped "
                    "before reporting a terminal result"
                ),
            )
            await unit_of_work.commit()
        return len(interrupted)
