"""Framework-neutral coordination of one prepared graph execution."""

import logging
from uuid import uuid4

from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.nodes import UserFacingNodeError
from grafy_core.runtime.execution import NodeRunError
from grafy_core.runtime.plugin_protocol import PluginFailureCode

from grafy_api.execution.errors import (
    NestedGraphExecutionError,
    render_execution_error,
)
from grafy_api.execution.models import (
    CompiledEdge,
    GraphExecutionResult,
    NodeExecutionResult,
    PreparedGraphExecution,
)
from grafy_api.execution.node_execution import NodeExecutionService


logger = logging.getLogger(__name__)


class GraphExecutionCoordinator:
    """Visit compiled nodes and assemble their graph-level execution result."""

    def __init__(self, *, node_execution: NodeExecutionService) -> None:
        self._node_execution = node_execution

    async def execute(
        self,
        execution: PreparedGraphExecution,
        /,
    ) -> GraphExecutionResult:
        workflow_run_id = uuid4()
        plan = execution.plan
        outputs: dict[str, dict[str, ArtifactOutputValue]] = {
            node_id: dict(node_outputs)
            for node_id, node_outputs in execution.initial_outputs.items()
        }
        # Phase-local adjacency index: group compiled edges by target node once
        # instead of rescanning the whole edge list per node (O(VE) -> O(V+E)).
        incoming_by_node: dict[str, list[CompiledEdge]] = {}
        for edge in plan.edges:
            incoming_by_node.setdefault(edge.request.to_node, []).append(edge)
        incoming_edges = {
            compiled_node.request.id: tuple(
                incoming_by_node.get(compiled_node.request.id, ())
            )
            for compiled_node in plan.nodes
        }
        failed: set[str] = set()
        node_results: list[NodeExecutionResult] = []

        for compiled_node in plan.nodes:
            if execution.control is not None:
                execution.control.check_cancelled()
            node_request = compiled_node.request
            node_path = (*execution.node_path, node_request.id)
            node_edges = incoming_edges[node_request.id]
            upstream_node_ids = {edge.request.from_node for edge in node_edges}
            if upstream_node_ids & failed:
                failed.add(node_request.id)
                node_results.append(
                    NodeExecutionResult(
                        node_id=node_request.id,
                        status="skipped",
                        error=None,
                        outputs={},
                        plugin_release=compiled_node.plugin_release,
                    )
                )
                if execution.control is not None:
                    execution.control.publish_node_status(
                        status="skipped",
                        node_path=node_path,
                        node_id=node_request.id,
                        node_run_id=None,
                        invocation_path=execution.invocation_path,
                    )
                continue

            control = execution.control
            tracks_outer_progress = (
                not execution.module_path and not execution.node_path
            )
            if control is not None and tracks_outer_progress:
                control.start_outer_node(node_request.id)
                control.publish_execution_status("running", node_request.id)
            node_run_id = uuid4()
            if control is not None:
                control.publish_node_status(
                    status="running",
                    node_path=node_path,
                    node_id=node_request.id,
                    node_run_id=node_run_id,
                    invocation_path=execution.invocation_path,
                )
            try:
                node_outputs = await self._node_execution.execute(
                    execution=execution,
                    compiled_node=compiled_node,
                    incoming_edges=node_edges,
                    outputs=outputs,
                    workflow_run_id=workflow_run_id,
                    node_run_id=node_run_id,
                )
            except Exception as exc:
                failure_code = (
                    exc.failure_code
                    if isinstance(exc, NodeRunError)
                    else PluginFailureCode.INTERNAL_ADAPTER_FAILURE
                )
                plugin_release = compiled_node.plugin_release
                logger.error(
                    "node_execution_failed",
                    extra={
                        "workspace_id": str(execution.workspace_id),
                        "graph_id": (
                            None
                            if execution.graph_id is None
                            else str(execution.graph_id)
                        ),
                        "graph_revision": execution.graph_revision,
                        "workflow_run_id": str(workflow_run_id),
                        "node_id": node_request.id,
                        "node_run_id": str(node_run_id),
                        "operator_id": node_request.operator_id,
                        "operator_version": node_request.operator_version,
                        "plugin_slug": (
                            None if plugin_release is None else plugin_release.slug
                        ),
                        "plugin_revision": (
                            None if plugin_release is None else plugin_release.revision
                        ),
                        "failure_code": failure_code.value,
                    },
                    exc_info=(type(exc), exc, exc.__traceback__),
                )
                if control is not None:
                    control.publish_node_status(
                        status="failed",
                        node_path=node_path,
                        node_id=node_request.id,
                        node_run_id=node_run_id,
                        invocation_path=execution.invocation_path,
                    )
                if execution.raise_node_errors:
                    graph_context = "nested graph"
                    if execution.graph_id is not None:
                        graph_context = (
                            f"graph {execution.graph_id}@{execution.graph_revision}"
                        )
                    public_context = (
                        f": {exc}"
                        if isinstance(exc, (NodeRunError, UserFacingNodeError))
                        else ""
                    )
                    raise NestedGraphExecutionError(
                        f"{graph_context} node {node_request.id!r} "
                        f"({node_request.operator_id}@"
                        f"{node_request.operator_version}) failed{public_context}"
                    ) from exc
                failed.add(node_request.id)
                node_results.append(
                    NodeExecutionResult(
                        node_id=node_request.id,
                        status="failed",
                        error=render_execution_error(exc),
                        outputs={},
                        plugin_release=compiled_node.plugin_release,
                        failure_code=failure_code,
                    )
                )
                continue
            finally:
                if control is not None and tracks_outer_progress:
                    control.finish_outer_node(node_request.id)
                    if not control.cancel_requested:
                        control.publish_execution_status("running", None)

            copied_node_outputs = dict(node_outputs)
            outputs[node_request.id] = copied_node_outputs
            node_results.append(
                NodeExecutionResult(
                    node_id=node_request.id,
                    status="succeeded",
                    error=None,
                    outputs=copied_node_outputs,
                    plugin_release=compiled_node.plugin_release,
                )
            )
            if control is not None:
                control.publish_node_status(
                    status="succeeded",
                    node_path=node_path,
                    node_id=node_request.id,
                    node_run_id=node_run_id,
                    invocation_path=execution.invocation_path,
                )

        status = "failed" if failed else "succeeded"
        return GraphExecutionResult(
            workflow_run_id=workflow_run_id,
            status=status,
            node_results=tuple(node_results),
            outputs=outputs,
        )


__all__ = ["GraphExecutionCoordinator"]
