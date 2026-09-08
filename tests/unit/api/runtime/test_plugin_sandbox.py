import asyncio
from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest
from typing_extensions import override

from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.modules import GraphModuleDefinition, GraphModuleReference
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraphArtifactTypeBinding,
    SavedGraphDocument,
    SavedGraphEdge,
    SavedGraphNode,
)
from grafy_core.nodes import NodeExecutionContext

from grafy_api.execution.requests import RunRequest
from grafy_api.execution.control import RunExecutionControl
from grafy_api.execution.models import GraphExecutionResult
from grafy_api.plugins.runtime.sandbox import (
    PluginSandboxScopeId,
    current_plugin_sandbox_scope,
)
from grafy_api.execution.run_graph import RunGraph


WORKSPACE_ID = UUID("00000000-0000-4000-8000-000000000952")
MODULE_GRAPH_ID = UUID("00000000-0000-4000-8000-000000000953")
MODULE_ARTIFACT_TYPE = ArtifactTypeKey("example.value", 1)


class RecordingSandboxLifecycle:
    def __init__(self, *, block_cleanup: bool = False) -> None:
        self.closed: list[PluginSandboxScopeId] = []
        self.observed_during_close: list[PluginSandboxScopeId | None] = []
        self.cleanup_started = asyncio.Event()
        self.cleanup_release = asyncio.Event()
        if not block_cleanup:
            self.cleanup_release.set()

    async def close_scope(self, scope_id: PluginSandboxScopeId, /) -> None:
        self.cleanup_started.set()
        await self.cleanup_release.wait()
        self.closed.append(scope_id)
        self.observed_during_close.append(current_plugin_sandbox_scope())


class ScopeObservingRunGraph(RunGraph):
    def __init__(
        self,
        lifecycle: RecordingSandboxLifecycle,
        *,
        block_execution: bool = False,
    ) -> None:
        self._plugin_sandboxes = lifecycle
        self.observed: list[PluginSandboxScopeId | None] = []
        self.observed_in_child_tasks: list[PluginSandboxScopeId | None] = []
        self.execution_started = asyncio.Event()
        self.execution_release = asyncio.Event()
        if not block_execution:
            self.execution_release.set()

    @override
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
        del (
            request,
            workspace_id,
            module_path,
            node_path,
            invocation_path,
            persist_materializations,
            validate_materialized_pins,
            raise_node_errors,
            control,
        )
        self.observed.append(current_plugin_sandbox_scope())
        child_scope = await asyncio.create_task(_scope_after_task_yield())
        self.observed_in_child_tasks.append(child_scope)
        self.execution_started.set()
        await self.execution_release.wait()
        outputs: Mapping[str, Mapping[str, ArtifactOutputValue]] = {}
        return GraphExecutionResult(
            workflow_run_id=uuid4(),
            status="succeeded",
            node_results=(),
            outputs=outputs,
        )


async def _scope_after_task_yield() -> PluginSandboxScopeId | None:
    await asyncio.sleep(0)
    return current_plugin_sandbox_scope()


class NestedModuleObservingRunGraph(RunGraph):
    def __init__(self, lifecycle: RecordingSandboxLifecycle) -> None:
        self._plugin_sandboxes = lifecycle
        self.observed: list[tuple[tuple[str, ...], PluginSandboxScopeId | None]] = []
        self.nested_output: ArtifactRef | None = None
        binding = SavedGraphArtifactTypeBinding(
            variable="T",
            artifact_type=MODULE_ARTIFACT_TYPE,
        )
        self.definition = GraphModuleDefinition(
            reference=GraphModuleReference(MODULE_GRAPH_ID, 1),
            name="Nested scope",
            document=SavedGraphDocument(
                nodes=(
                    SavedGraphNode(
                        kind="builtin",
                        id="input",
                        operator_id="module.input",
                        operator_version=1,
                        config={"public_name": "source"},
                        position=GraphPoint(x=0, y=0),
                        artifact_type_bindings=(binding,),
                    ),
                    SavedGraphNode(
                        kind="builtin",
                        id="output",
                        operator_id="module.output",
                        operator_version=1,
                        config={"public_name": "result"},
                        position=GraphPoint(x=0, y=0),
                        artifact_type_bindings=(binding,),
                    ),
                ),
                edges=(
                    SavedGraphEdge(
                        id="boundary",
                        from_node="input",
                        from_port="value",
                        to_node="output",
                        to_port="value",
                    ),
                ),
            ),
        )

    @override
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
        del (
            node_path,
            invocation_path,
            persist_materializations,
            validate_materialized_pins,
            raise_node_errors,
            control,
        )
        self.observed.append((module_path, current_plugin_sandbox_scope()))
        outputs: Mapping[str, Mapping[str, ArtifactOutputValue]] = {}
        if not module_path:
            source = ArtifactRef.from_key(
                artifact_id=uuid4(),
                key=MODULE_ARTIFACT_TYPE,
            )
            nested = await self.execute_module(
                self.definition,
                NodeExecutionContext(
                    workspace_id=workspace_id,
                    node_id="nested-module",
                ),
                {"source": source},
            )
            self.nested_output = nested.outputs["result"]
        else:
            pinned = request.pinned_outputs[0].value
            assert isinstance(pinned, ArtifactRef)
            outputs = {"output": {"value": pinned}}
        return GraphExecutionResult(
            workflow_run_id=uuid4(),
            status="succeeded",
            node_results=(),
            outputs=outputs,
        )


@pytest.mark.asyncio
async def test_concurrent_top_level_runs_use_isolated_inherited_scopes() -> None:
    lifecycle = RecordingSandboxLifecycle()
    graph = ScopeObservingRunGraph(lifecycle)
    request = RunRequest(nodes=[])

    await asyncio.gather(
        graph.run(WORKSPACE_ID, request),
        graph.run(WORKSPACE_ID, request),
    )

    scopes = [scope for scope in graph.observed if scope is not None]
    assert len(scopes) == 2
    assert scopes[0] != scopes[1]
    assert graph.observed_in_child_tasks == scopes
    assert set(lifecycle.closed) == set(scopes)
    assert lifecycle.observed_during_close == lifecycle.closed
    assert current_plugin_sandbox_scope() is None


@pytest.mark.asyncio
async def test_nested_module_reuses_top_level_sandbox_scope() -> None:
    lifecycle = RecordingSandboxLifecycle()
    graph = NestedModuleObservingRunGraph(lifecycle)

    await graph.run(WORKSPACE_ID, RunRequest(nodes=[]))

    assert graph.nested_output is not None
    assert [module_path for module_path, _scope in graph.observed] == [
        (),
        (graph.definition.reference.module_path_item,),
    ]
    scopes = [scope for _module_path, scope in graph.observed]
    assert scopes[0] is not None
    assert scopes[1] == scopes[0]
    assert lifecycle.closed == [scopes[0]]
    assert current_plugin_sandbox_scope() is None


@pytest.mark.asyncio
async def test_cancellation_waits_for_scope_cleanup_and_resets_context() -> None:
    lifecycle = RecordingSandboxLifecycle(block_cleanup=True)
    graph = ScopeObservingRunGraph(lifecycle, block_execution=True)
    task = asyncio.create_task(graph.run(WORKSPACE_ID, RunRequest(nodes=[])))
    await graph.execution_started.wait()

    task.cancel()
    await lifecycle.cleanup_started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()

    lifecycle.cleanup_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert lifecycle.closed == graph.observed
    assert lifecycle.observed_during_close == graph.observed
    assert current_plugin_sandbox_scope() is None
