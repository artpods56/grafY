"""Application use case for top-level and nested graph execution."""

import asyncio
from collections.abc import Mapping
from contextvars import ContextVar
from uuid import UUID

from grafy_core.artifacts import ArtifactRef
from grafy_core.domain.modules import MODULE_BOUNDARY_PORT, GraphModuleDefinition
from grafy_core.nodes import NodeExecutionContext
from grafy_core.operators.modules import GraphModuleExecutionError
from grafy_core.ports.modules import GraphModuleExecutionResult


from grafy_api.execution.requests import (
    MAX_EXECUTION_NODE_PATH_LENGTH,
    PinnedOutputRequest,
    RunEdgeRequest,
    RunNodeRequest,
    RunRequest,
)
from grafy_api.execution.materializations import MaterializationService
from grafy_api.execution.compiler import GraphCompiler
from grafy_api.execution.control import RunExecutionControl
from grafy_api.execution.coordinator import GraphExecutionCoordinator
from grafy_api.execution.errors import GraphExecutionError
from grafy_api.execution.models import (
    GraphExecutionResult,
    PreparedGraphExecution,
)
from grafy_api.execution.preflight import GraphRunPreflight
from grafy_api.plugins.runtime.sandbox import (
    PluginSandboxLifecycle,
    PluginSandboxScopeId,
    activate_plugin_sandbox_scope,
    reset_plugin_sandbox_scope,
)


_current_execution_control: ContextVar[RunExecutionControl | None] = ContextVar(
    "grafy_current_execution_control",
    default=None,
)


class RunGraph:
    """Coordinate the collaborators required to execute a graph run."""

    def __init__(
        self,
        *,
        preflight: GraphRunPreflight,
        compiler: GraphCompiler,
        coordinator: GraphExecutionCoordinator,
        materializations: MaterializationService,
        plugin_sandboxes: PluginSandboxLifecycle | None = None,
    ) -> None:
        self._preflight = preflight
        self._compiler = compiler
        self._coordinator = coordinator
        self._materializations = materializations
        self._plugin_sandboxes = plugin_sandboxes

    async def run(
        self,
        workspace_id: UUID,
        request: RunRequest,
        control: RunExecutionControl | None = None,
    ) -> GraphExecutionResult:
        control_token = _current_execution_control.set(control)
        sandbox_scope = PluginSandboxScopeId.new()
        sandbox_token = activate_plugin_sandbox_scope(sandbox_scope)
        try:
            return await self._execute(
                request,
                workspace_id=workspace_id,
                module_path=(),
                node_path=(),
                invocation_path=(),
                persist_materializations=True,
                validate_materialized_pins=True,
                raise_node_errors=False,
                control=control,
            )
        finally:
            try:
                if self._plugin_sandboxes is not None:
                    cleanup_task = asyncio.create_task(
                        self._plugin_sandboxes.close_scope(sandbox_scope)
                    )
                    try:
                        await asyncio.shield(cleanup_task)
                    except asyncio.CancelledError:
                        await cleanup_task
                        raise
            finally:
                reset_plugin_sandbox_scope(sandbox_token)
                _current_execution_control.reset(control_token)

    async def execute_module(
        self,
        definition: GraphModuleDefinition,
        context: NodeExecutionContext,
        inputs: Mapping[str, ArtifactRef],
        /,
    ) -> GraphModuleExecutionResult:
        graph_id = definition.reference.graph_id
        graph_revision = definition.reference.revision
        graph_path_item = definition.reference.module_path_item
        if len(context.node_path) >= MAX_EXECUTION_NODE_PATH_LENGTH:
            rendered_node_path = " -> ".join(context.node_path)
            raise GraphModuleExecutionError(
                f"Graph module {definition.name!r} at revision {graph_revision} "
                "cannot be entered because child node paths would exceed the "
                f"maximum of {MAX_EXECUTION_NODE_PATH_LENGTH} instances: "
                f"{rendered_node_path}"
            )
        if graph_path_item in context.module_path:
            rendered_path = " -> ".join((*context.module_path, graph_path_item))
            raise GraphModuleExecutionError(
                f"Graph module cycle detected while entering {definition.name!r} "
                f"at revision {graph_revision}: {rendered_path}"
            )

        input_names_by_boundary_id = {
            port.boundary_node_id: port.name for port in definition.input_ports
        }
        input_boundary_ids = set(input_names_by_boundary_id)
        executed_nodes = [
            node
            for node in definition.document.nodes
            if node.id not in input_boundary_ids
        ]
        executed_node_ids = {node.id for node in executed_nodes}
        active_edges = [
            edge
            for edge in definition.document.edges
            if edge.enabled
            and edge.to_node in executed_node_ids
            and (
                edge.from_node not in input_names_by_boundary_id
                or input_names_by_boundary_id[edge.from_node] in inputs
            )
        ]
        active_input_plug_ids_by_node = {node.id: set[str]() for node in executed_nodes}
        for edge in active_edges:
            if edge.to_plug is not None:
                active_input_plug_ids_by_node[edge.to_node].add(edge.to_plug)

        request = RunRequest(
            nodes=[
                RunNodeRequest.from_saved_node(
                    node,
                    connected_plug_ids=active_input_plug_ids_by_node[node.id],
                )
                for node in executed_nodes
            ],
            edges=[RunEdgeRequest.from_saved_edge(edge) for edge in active_edges],
            pinned_outputs=[
                PinnedOutputRequest(
                    from_node=port.boundary_node_id,
                    from_port=MODULE_BOUNDARY_PORT,
                    value=inputs[port.name],
                )
                for port in definition.input_ports
                if port.name in inputs
            ],
            graph_id=graph_id,
            graph_revision=graph_revision,
            secret_graph_id=graph_id,
            secret_graph_revision=graph_revision,
        )
        execution = await self._execute(
            request,
            workspace_id=context.workspace_id,
            module_path=(*context.module_path, graph_path_item),
            node_path=context.node_path,
            invocation_path=context.invocation_path,
            persist_materializations=False,
            validate_materialized_pins=False,
            raise_node_errors=True,
            control=_current_execution_control.get(),
        )

        outputs: dict[str, ArtifactRef] = {}
        for port in definition.output_ports:
            boundary_outputs = execution.outputs.get(port.boundary_node_id)
            value = (
                boundary_outputs.get(MODULE_BOUNDARY_PORT)
                if boundary_outputs is not None
                else None
            )
            if value is None:
                raise GraphExecutionError(
                    f"Graph module {definition.name!r} revision {graph_revision} "
                    f"did not produce public output {port.name!r} at boundary "
                    f"node {port.boundary_node_id!r}"
                )
            if not isinstance(value, ArtifactRef):
                raise GraphExecutionError(
                    f"Graph module {definition.name!r} revision {graph_revision} "
                    f"public output {port.name!r} produced a sequence; module "
                    "boundary ports must be scalar"
                )
            outputs[port.name] = value
        return GraphModuleExecutionResult(outputs=outputs)

    async def _execute(
        self,
        request: RunRequest,
        *,
        workspace_id: UUID,
        module_path: tuple[str, ...],
        node_path: tuple[str, ...],
        invocation_path: tuple[int, ...],
        persist_materializations: bool,
        validate_materialized_pins: bool,
        raise_node_errors: bool,
        control: RunExecutionControl | None,
    ) -> GraphExecutionResult:
        if control is not None:
            control.check_cancelled()
        run_context = await self._preflight.validate(workspace_id, request)
        plan = await self._compiler.compile(
            request,
            self,
            workspace_id=workspace_id,
            resolved_releases=run_context.resolved_releases,
        )
        if (
            validate_materialized_pins
            and request.graph_id is not None
            and request.graph_revision is not None
        ):
            await self._materializations.validate_latest_pins(
                workspace_id,
                request.graph_id,
                request.graph_revision,
                plan.pinned_outputs,
            )
        initial_outputs = await self._materializations.resolve_pinned_outputs(
            workspace_id, plan.pinned_outputs
        )
        execution = await self._coordinator.execute(
            PreparedGraphExecution(
                plan=plan,
                initial_outputs=initial_outputs,
                workspace_id=workspace_id,
                graph_id=request.graph_id,
                graph_revision=request.graph_revision,
                secret_graph_id=request.secret_graph_id,
                secret_graph_revision=request.secret_graph_revision,
                secret_node_ids=frozenset(run_context.secret_node_ids),
                module_path=module_path,
                raise_node_errors=raise_node_errors,
                node_path=node_path,
                invocation_path=invocation_path,
                control=control,
            )
        )
        if control is not None:
            control.check_cancelled()
        if (
            persist_materializations
            and request.graph_id is not None
            and request.graph_revision is not None
        ):
            await self._materializations.persist_execution(
                workspace_id,
                request.graph_id,
                request.graph_revision,
                execution,
            )
        return execution


__all__ = ["RunGraph"]
