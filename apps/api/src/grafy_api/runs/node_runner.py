"""Compute one node instance from the results its upstream instances stored.

The scheduler hands over a ``ComputationRequest``: the fingerprint to store under,
the expanded instance to compute, and the fingerprint of every upstream instance
this one reads from. Nothing is passed in memory, so the runner reads each
connection's result out of the Workspace-bound result store, binds the instance to
its operator, applies the projections and conversions its connections declared,
and runs it once or once per item. It never writes the store: the scheduler
appends the returned outputs under the fingerprint it asked for (ADR 0020).

One call is independent of every other: the runner holds no state a computation
can disturb, so a scheduler may run any number of them concurrently.
"""

import asyncio
from collections.abc import Mapping, Sequence
from uuid import UUID

from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.kernel.instances import InstanceKey
from grafy_core.kernel.project import GRAPH_BOUNDARY_PORT
from grafy_core.kernel.results import ResultStore
from grafy_core.kernel.scheduler import ComputationRequest, ComputationRunner
from grafy_core.nodes import NodeExecutionContext
from grafy_core.plugins import PluginRegistry, PluginRuntimeContext
from grafy_core.ports.artifacts import UnitOfWorkPort
from grafy_core.ports.node_secrets import NodeSecretResolverPort
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.persistence import ArtifactWriterRegistry
from grafy_core.runtime.resolvers import ResolverRegistry

from grafy_api.runs.contract import NodeContractBinder, is_boundary
from grafy_api.runs.edge_values import EdgeValueResolver
from grafy_api.runs.errors import NodeComputationError
from grafy_api.runs.node_execution import NodeExecutionService


class NodeComputationRunner:
    """The kernel's ``ComputationRunner`` for one Project and one result store."""

    def __init__(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        store: ResultStore,
        binder: NodeContractBinder,
        edge_values: EdgeValueResolver,
        node_execution: NodeExecutionService,
    ) -> None:
        self._workspace_id = workspace_id
        self._project_id = project_id
        self._store = store
        self._binder = binder
        self._edge_values = edge_values
        self._node_execution = node_execution

    async def __call__(
        self,
        request: ComputationRequest,
    ) -> Mapping[str, ArtifactOutputValue]:
        instance = request.instance
        upstream = await self._read_upstream(request)
        context = NodeExecutionContext(
            workspace_id=self._workspace_id,
            project_id=self._project_id,
            graph_id=instance.key.graph_id,
            node_id=instance.key.node_id,
            call_path=instance.key.call_path,
            fingerprint=request.fingerprint,
        )
        if is_boundary(instance):
            # A Graph's own input or output is no operator: the one value that
            # reaches it is what the interface port carries.
            port, slot = self._binder.boundary_input(instance, upstream)
            values = await self._edge_values.assemble_inputs(
                slots=(slot,),
                ports=(port,),
                context=context,
            )
            return {GRAPH_BOUNDARY_PORT: values[port.name]}

        bound = self._binder.bind(instance, upstream)
        inputs = await self._edge_values.assemble_inputs(
            slots=bound.slots,
            ports=bound.ports,
            context=context,
        )
        return await self._node_execution.execute(
            bound=bound,
            inputs=inputs,
            context=context,
        )

    async def _read_upstream(
        self, request: ComputationRequest
    ) -> dict[InstanceKey, Mapping[str, ArtifactOutputValue]]:
        instance = request.instance
        sources = sorted(
            {connection.source for connection in instance.connections},
            key=lambda key: key.sort_key,
        )
        results = await asyncio.gather(
            *(self._stored_output(request, source) for source in sources)
        )
        return dict(zip(sources, results, strict=True))

    async def _stored_output(
        self,
        request: ComputationRequest,
        source: InstanceKey,
    ) -> Mapping[str, ArtifactOutputValue]:
        fingerprint = request.upstream_fingerprints.get(source)
        if fingerprint is None:
            raise NodeComputationError(
                f"Node {request.instance.key.node_id!r} is fed by an instance the "
                "computation was given no fingerprint for"
            )
        stored = await self._store.get_result(fingerprint)
        if stored is None:
            raise NodeComputationError(
                f"Node {request.instance.key.node_id!r} reads the result stored "
                f"under fingerprint {fingerprint}, which the result store does not "
                "hold"
            )
        return stored.outputs


class NodeComputationRunnerFactory:
    """Builds the kernel ``ComputationRunner`` for one Project.

    The adapters are the same ones the rest of the workbench runs nodes with, and
    every ``for_project`` call returns a fresh runner over the caller's result
    store: nothing is shared between Projects and nothing a runner mutates
    outlives one computation.

    ``plugin_context`` is what an operator needing runtime services -- storage,
    a workbench workspace -- is built with; an operator that needs none is built
    from its class and the runner works without one. ``node_secrets`` belongs to
    that same composition: a node resolves its own credentials through the plugin
    runtime context while it runs, and the secret revisions that make a node
    stale enter its fingerprint outside the runner, so a computation reads no
    secret here.
    """

    def __init__(
        self,
        *,
        registry: PluginRegistry,
        runtime: NodeRuntime,
        resolvers: ResolverRegistry,
        writers: ArtifactWriterRegistry,
        unit_of_work: UnitOfWorkPort,
        node_secrets: NodeSecretResolverPort,
        max_map_concurrency: int = 1,
        plugin_context: PluginRuntimeContext | None = None,
    ) -> None:
        self._binder = NodeContractBinder(
            registry=registry,
            plugin_context=plugin_context,
        )
        self._edge_values = EdgeValueResolver(
            resolvers=resolvers,
            writers=writers,
            unit_of_work=unit_of_work,
        )
        self._node_execution = NodeExecutionService(
            runtime=runtime,
            max_map_concurrency=max_map_concurrency,
        )
        self._node_secrets = node_secrets

    def for_project(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID,
        store: ResultStore,
    ) -> ComputationRunner:
        return NodeComputationRunner(
            workspace_id=workspace_id,
            project_id=project_id,
            store=store,
            binder=self._binder,
            edge_values=self._edge_values,
            node_execution=self._node_execution,
        )


__all__: Sequence[str] = ["NodeComputationRunner", "NodeComputationRunnerFactory"]
