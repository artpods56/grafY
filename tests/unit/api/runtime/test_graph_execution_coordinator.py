"""Behavioral contracts for direct in-process graph execution."""

import asyncio
import logging
from collections.abc import Mapping, Sequence
from typing import Annotated, ClassVar, cast, override
from uuid import UUID, uuid4

import pytest

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    ArtifactTypeSpec,
    NoConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.invocation_cache import InvocationCacheEntry
from grafy_core.nodes import (
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    UserFacingNodeError,
    resolve_node_contracts,
)
from grafy_core.plugins import NodeCachePolicy, NodeRegistration
from grafy_core.ports.node_secrets import UnavailableNodeSecretResolver
from grafy_core.runtime.execution import NodeRunError, NodeRuntime
from grafy_core.runtime.invocation import InvocationMode, NodeInvocation
from grafy_core.runtime.invocation_cache import InvocationCachePort
from grafy_core.runtime.plugin_protocol import PluginFailureCode
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import (
    ArtifactOutputWriter,
    ArtifactWriteContext,
    ArtifactWriterRegistry,
    OutputPersister,
)
from grafy_core.runtime.plugin_invocation import PluginInvocationError
from grafy_core.runtime.resolvers import Resolver, ResolverRegistry

from grafy_api.execution.requests import (
    RunEdgeRequest,
    RunNodeRequest,
)
from grafy_api.execution.control import RunExecutionControl
from grafy_api.execution.coordinator import GraphExecutionCoordinator
from grafy_api.execution.edge_values import EdgeValueResolver
from grafy_api.execution.errors import GraphExecutionError
from grafy_api.execution.models import (
    PreparedGraphExecution,
    CompiledEdge,
    CompiledGraph,
    CompiledNode,
)
from grafy_api.execution.node_execution import NodeExecutionService


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


VALUE = ArtifactTypeSpec(
    key=ArtifactTypeKey("test.local_execution.value", 1),
    title="Local execution value",
)


class IntegerResolver:
    source = VALUE.key
    target = int

    def __init__(self, values: Mapping[UUID, int]) -> None:
        self._values = dict(values)

    async def resolve(self, ref: ArtifactRef, workspace_id: UUID) -> int:
        del workspace_id
        return self._values[ref.artifact_id]


class RecordingWriter:
    artifact_type = VALUE.key

    def __init__(self) -> None:
        self.values: list[int] = []
        self.item_indexes: list[int | None] = []
        self.refs: list[ArtifactRef] = []

    async def write(
        self,
        value: object,
        context: ArtifactWriteContext,
    ) -> ArtifactRef:
        assert isinstance(value, int)
        ref = ArtifactRef.from_key(
            artifact_id=uuid4(),
            key=self.artifact_type,
            content_hash=f"{value:064x}",
        )
        self.values.append(value)
        self.item_indexes.append(context.item_index)
        self.refs.append(ref)
        return ref


class AddInput(NodeInput):
    item: Annotated[int, InPort(VALUE)]
    broadcast: Annotated[int, InPort(VALUE)]


class AddOutput(NodeOutput):
    value: Annotated[int, OutPort(VALUE)]


class AddNode(Node[NoConfig, AddInput, AddOutput]):
    operator_id: ClassVar[str] = "test.local_execution.add"
    operator_version: ClassVar[int] = 1

    def __init__(self) -> None:
        self.calls: list[tuple[int | None, int, int]] = []

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: AddInput,
        /,
    ) -> AddOutput:
        self.calls.append((context.invocation_index, inputs.item, inputs.broadcast))
        return AddOutput(value=inputs.item + inputs.broadcast)


class SynchronizedAddNode(AddNode):
    def __init__(
        self,
        release_gates: Sequence[asyncio.Event],
        *,
        fail_index: int | None = None,
    ) -> None:
        super().__init__()
        self._release_gates = tuple(release_gates)
        self._fail_index = fail_index
        self.started = tuple(asyncio.Event() for _ in release_gates)
        self.started_totals = tuple(asyncio.Event() for _ in release_gates)
        self.completed = tuple(asyncio.Event() for _ in release_gates)
        self.started_indexes: list[int] = []
        self.completed_indexes: list[int] = []
        self.cancelled_indexes: list[int] = []
        self.active_count = 0
        self.max_active_count = 0

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: AddInput,
        /,
    ) -> AddOutput:
        index = context.invocation_index
        assert index is not None
        self.calls.append((index, inputs.item, inputs.broadcast))
        self.started_indexes.append(index)
        self.active_count += 1
        self.max_active_count = max(self.max_active_count, self.active_count)
        self.started[index].set()
        self.started_totals[len(self.started_indexes) - 1].set()
        try:
            await self._release_gates[index].wait()
            if index == self._fail_index:
                raise UserFacingNodeError("controlled MAP item failure")
            self.completed_indexes.append(index)
            self.completed[index].set()
            return AddOutput(value=inputs.item + inputs.broadcast)
        except asyncio.CancelledError:
            self.cancelled_indexes.append(index)
            raise
        finally:
            self.active_count -= 1


class FailingNode(AddNode):
    def __init__(self, error: Exception) -> None:
        super().__init__()
        self._error = error

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        _config: NoConfig,
        inputs: AddInput,
        /,
    ) -> AddOutput:
        del context, inputs
        raise self._error


class MemoryInvocationCache(InvocationCachePort):
    def __init__(self) -> None:
        self.entries: dict[tuple[UUID, str], InvocationCacheEntry] = {}

    async def get(
        self,
        workspace_id: UUID,
        key_sha256: str,
    ) -> InvocationCacheEntry | None:
        return self.entries.get((workspace_id, key_sha256))

    async def put_if_absent(self, entry: InvocationCacheEntry) -> bool:
        key = (entry.workspace_id, entry.key_sha256)
        if key in self.entries:
            return False
        self.entries[key] = entry
        return True

    async def remove_if_current(
        self,
        workspace_id: UUID,
        key_sha256: str,
        generation: UUID,
    ) -> bool:
        key = (workspace_id, key_sha256)
        entry = self.entries.get(key)
        if entry is None or entry.generation != generation:
            return False
        del self.entries[key]
        return True


class StubEdgeValueResolver:
    def __init__(self, inputs_by_node: Mapping[str, Mapping[str, object]]) -> None:
        self.inputs_by_node = {
            node_id: dict(node_inputs)
            for node_id, node_inputs in inputs_by_node.items()
        }
        self.calls: list[str] = []

    async def assemble_inputs(
        self,
        compiled_node: CompiledNode,
        incoming_edges: Sequence[CompiledEdge],
        outputs: dict[str, dict[str, ArtifactOutputValue]],
        workflow_run_id: UUID,
        workspace_id: UUID,
    ) -> dict[str, object]:
        del incoming_edges, outputs, workflow_run_id, workspace_id
        node_id = compiled_node.request.id
        self.calls.append(node_id)
        return dict(self.inputs_by_node[node_id])


def _runtime(
    resolver: IntegerResolver,
    writer: RecordingWriter,
    cache: InvocationCachePort | None = None,
) -> NodeRuntime:
    resolvers = ResolverRegistry([cast(Resolver[object], resolver)])
    writers = ArtifactWriterRegistry([cast(ArtifactOutputWriter, writer)])
    return NodeRuntime(
        materializer=InputMaterializer(resolvers),
        persister=OutputPersister(writers),
        invocation_cache=cache,
    )


def _compiled_add(
    *,
    node_id: str,
    node: AddNode,
    invocation: NodeInvocation,
    cache_policy: NodeCachePolicy = NodeCachePolicy.NEVER,
) -> CompiledNode:
    return CompiledNode(
        request=RunNodeRequest(
            kind="builtin",
            id=node_id,
            operator_id=node.operator_id,
            operator_version=node.operator_version,
        ),
        node=node,
        registration=NodeRegistration(
            node_class=AddNode,
            factory=None,
            cache_policy=cache_policy,
        ),
        resolved_contracts=resolve_node_contracts(node, {}),
        invocation=invocation,
        artifact_type_bindings={},
    )


@pytest.mark.asyncio
async def test_inline_map_reuses_cache_and_preserves_sequence_envelope() -> None:
    first_ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=VALUE.key,
        content_hash="1" * 64,
    )
    second_ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=VALUE.key,
        content_hash="2" * 64,
    )
    broadcast_ref = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=VALUE.key,
        content_hash="3" * 64,
    )
    resolver = IntegerResolver(
        {
            first_ref.artifact_id: 2,
            second_ref.artifact_id: 4,
            broadcast_ref.artifact_id: 10,
        }
    )
    writer = RecordingWriter()
    node = AddNode()
    compiled_node = _compiled_add(
        node_id="mapped",
        node=node,
        invocation=NodeInvocation(mode=InvocationMode.MAP, map_input="item"),
        cache_policy=NodeCachePolicy.EXACT,
    )
    plan = CompiledGraph(nodes=(compiled_node,), edges=(), pinned_outputs={})
    edge_values = StubEdgeValueResolver(
        {
            "mapped": {
                "item": ArtifactRefSequence.from_key(
                    key=VALUE.key,
                    item_refs=[first_ref],
                ),
                "broadcast": broadcast_ref,
            }
        }
    )
    coordinator = GraphExecutionCoordinator(
        node_execution=NodeExecutionService(
            runtime=_runtime(resolver, writer, MemoryInvocationCache()),
            edge_values=cast(EdgeValueResolver, edge_values),
            node_secrets=UnavailableNodeSecretResolver(),
        )
    )

    first = await coordinator.execute(
        PreparedGraphExecution(
            workspace_id=WORKSPACE_ID,
            plan=plan,
            initial_outputs={},
            graph_id=None,
            graph_revision=None,
            secret_graph_id=None,
            secret_graph_revision=None,
            secret_node_ids=frozenset(),
            module_path=(),
            raise_node_errors=False,
        )
    )
    second_source = ArtifactRefSequence(
        artifact_type=VALUE.key.id,
        schema_version=VALUE.key.schema_version,
        item_refs=[first_ref, second_ref],
        ordered=False,
        index_key="source_position",
    )
    edge_values.inputs_by_node["mapped"]["item"] = second_source
    second = await coordinator.execute(
        PreparedGraphExecution(
            workspace_id=WORKSPACE_ID,
            plan=plan,
            initial_outputs={},
            graph_id=None,
            graph_revision=None,
            secret_graph_id=None,
            secret_graph_revision=None,
            secret_node_ids=frozenset(),
            module_path=(),
            raise_node_errors=False,
        )
    )

    assert first.status == "succeeded"
    assert second.status == "succeeded"
    first_output = first.node_results[0].outputs["value"]
    second_output = second.node_results[0].outputs["value"]
    assert isinstance(first_output, ArtifactRefSequence)
    assert isinstance(second_output, ArtifactRefSequence)
    assert second_output.item_refs == [first_output.item_refs[0], writer.refs[1]]
    assert second_output.ordered is False
    assert second_output.index_key == "source_position"
    assert second_output.metadata == {
        "invocation_mode": "map",
        "map_input": "item",
        "source_sequence_id": str(second_source.sequence_id),
    }
    assert node.calls == [(0, 2, 10), (1, 4, 10)]
    assert writer.values == [12, 14]
    assert writer.item_indexes == [0, 1]


@pytest.mark.asyncio
async def test_map_execution_overlaps_items_and_aggregates_in_source_order() -> None:
    item_refs = [
        ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key) for _ in range(2)
    ]
    broadcast_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key)
    resolver = IntegerResolver(
        {
            item_refs[0].artifact_id: 1,
            item_refs[1].artifact_id: 2,
            broadcast_ref.artifact_id: 10,
        }
    )
    writer = RecordingWriter()
    release_gates = [asyncio.Event(), asyncio.Event()]
    node = SynchronizedAddNode(release_gates)
    compiled_node = _compiled_add(
        node_id="mapped",
        node=node,
        invocation=NodeInvocation(mode=InvocationMode.MAP, map_input="item"),
    )
    edge_values = StubEdgeValueResolver(
        {
            "mapped": {
                "item": ArtifactRefSequence.from_key(
                    key=VALUE.key,
                    item_refs=item_refs,
                ),
                "broadcast": broadcast_ref,
            }
        }
    )
    coordinator = GraphExecutionCoordinator(
        node_execution=NodeExecutionService(
            runtime=_runtime(resolver, writer),
            edge_values=cast(EdgeValueResolver, edge_values),
            node_secrets=UnavailableNodeSecretResolver(),
            max_map_concurrency=2,
        )
    )
    execution = PreparedGraphExecution(
        workspace_id=WORKSPACE_ID,
        plan=CompiledGraph(nodes=(compiled_node,), edges=(), pinned_outputs={}),
        initial_outputs={},
        graph_id=None,
        graph_revision=None,
        secret_graph_id=None,
        secret_graph_revision=None,
        secret_node_ids=frozenset(),
        module_path=(),
        raise_node_errors=False,
    )

    run_task = asyncio.create_task(coordinator.execute(execution))
    try:
        async with asyncio.timeout(3):
            await node.started[0].wait()
            await node.started[1].wait()
        assert node.active_count == 2

        release_gates[1].set()
        async with asyncio.timeout(3):
            await node.completed[1].wait()
        release_gates[0].set()
        result = await run_task
    finally:
        for gate in release_gates:
            gate.set()
        if not run_task.done():
            run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)

    assert result.status == "succeeded"
    output = result.node_results[0].outputs["value"]
    assert isinstance(output, ArtifactRefSequence)
    assert node.max_active_count == 2
    assert node.completed_indexes == [1, 0]
    assert writer.values == [12, 11]
    assert [ref.content_hash for ref in output.item_refs] == [
        f"{11:064x}",
        f"{12:064x}",
    ]


@pytest.mark.asyncio
async def test_map_execution_never_exceeds_configured_concurrency() -> None:
    item_refs = [
        ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key) for _ in range(7)
    ]
    broadcast_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key)
    resolver = IntegerResolver(
        {
            **{ref.artifact_id: index for index, ref in enumerate(item_refs, start=1)},
            broadcast_ref.artifact_id: 10,
        }
    )
    writer = RecordingWriter()
    release_gate = asyncio.Event()
    node = SynchronizedAddNode([release_gate] * len(item_refs))
    compiled_node = _compiled_add(
        node_id="mapped",
        node=node,
        invocation=NodeInvocation(mode=InvocationMode.MAP, map_input="item"),
    )
    edge_values = StubEdgeValueResolver(
        {
            "mapped": {
                "item": ArtifactRefSequence.from_key(
                    key=VALUE.key,
                    item_refs=item_refs,
                ),
                "broadcast": broadcast_ref,
            }
        }
    )
    coordinator = GraphExecutionCoordinator(
        node_execution=NodeExecutionService(
            runtime=_runtime(resolver, writer),
            edge_values=cast(EdgeValueResolver, edge_values),
            node_secrets=UnavailableNodeSecretResolver(),
            max_map_concurrency=3,
        )
    )
    execution = PreparedGraphExecution(
        workspace_id=WORKSPACE_ID,
        plan=CompiledGraph(nodes=(compiled_node,), edges=(), pinned_outputs={}),
        initial_outputs={},
        graph_id=None,
        graph_revision=None,
        secret_graph_id=None,
        secret_graph_revision=None,
        secret_node_ids=frozenset(),
        module_path=(),
        raise_node_errors=False,
    )

    run_task = asyncio.create_task(coordinator.execute(execution))
    try:
        async with asyncio.timeout(3):
            await node.started_totals[2].wait()
        assert node.active_count == 3
        release_gate.set()
        result = await run_task
    finally:
        release_gate.set()
        if not run_task.done():
            run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)

    assert result.status == "succeeded"
    assert len(node.started_indexes) == len(item_refs)
    assert node.max_active_count == 3


@pytest.mark.asyncio
async def test_map_execution_failure_cancels_items_and_skips_dependents() -> None:
    item_refs = [
        ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key) for _ in range(3)
    ]
    broadcast_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key)
    resolver = IntegerResolver(
        {
            **{ref.artifact_id: index for index, ref in enumerate(item_refs, start=1)},
            broadcast_ref.artifact_id: 10,
        }
    )
    writer = RecordingWriter()
    release_gates = [asyncio.Event() for _ in item_refs]
    node = SynchronizedAddNode(release_gates, fail_index=1)
    failed_node = _compiled_add(
        node_id="failed",
        node=node,
        invocation=NodeInvocation(mode=InvocationMode.MAP, map_input="item"),
    )
    downstream_node = _compiled_add(
        node_id="downstream",
        node=AddNode(),
        invocation=NodeInvocation(),
    )
    dependency = CompiledEdge(
        request=RunEdgeRequest(
            from_node="failed",
            from_port="value",
            to_node="downstream",
            to_port="item",
        ),
        projection=None,
        conversion_path=(),
    )
    edge_values = StubEdgeValueResolver(
        {
            "failed": {
                "item": ArtifactRefSequence.from_key(
                    key=VALUE.key,
                    item_refs=item_refs,
                ),
                "broadcast": broadcast_ref,
            },
            "downstream": {
                "item": broadcast_ref,
                "broadcast": broadcast_ref,
            },
        }
    )
    coordinator = GraphExecutionCoordinator(
        node_execution=NodeExecutionService(
            runtime=_runtime(resolver, writer),
            edge_values=cast(EdgeValueResolver, edge_values),
            node_secrets=UnavailableNodeSecretResolver(),
            max_map_concurrency=3,
        )
    )
    execution = PreparedGraphExecution(
        workspace_id=WORKSPACE_ID,
        plan=CompiledGraph(
            nodes=(failed_node, downstream_node),
            edges=(dependency,),
            pinned_outputs={},
        ),
        initial_outputs={},
        graph_id=None,
        graph_revision=None,
        secret_graph_id=None,
        secret_graph_revision=None,
        secret_node_ids=frozenset(),
        module_path=(),
        raise_node_errors=False,
    )

    run_task = asyncio.create_task(coordinator.execute(execution))
    try:
        async with asyncio.timeout(3):
            await node.started_totals[2].wait()
        release_gates[1].set()
        async with asyncio.timeout(3):
            result = await run_task
    finally:
        for gate in release_gates:
            gate.set()
        if not run_task.done():
            run_task.cancel()
        await asyncio.gather(run_task, return_exceptions=True)

    assert result.status == "failed"
    assert [node_result.status for node_result in result.node_results] == [
        "failed",
        "skipped",
    ]
    assert node.active_count == 0
    assert set(node.cancelled_indexes) == {0, 2}
    assert writer.values == []
    error = result.node_results[0].error
    assert error is not None
    assert f"MAP input 'item' failed at item 1 ({item_refs[1].artifact_id})" in error
    assert "controlled MAP item failure" in error
    assert edge_values.calls == ["failed"]


@pytest.mark.asyncio
async def test_inline_map_failure_skips_dependents_and_preserves_cause() -> None:
    missing_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key)
    broadcast_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key)
    resolver = IntegerResolver({broadcast_ref.artifact_id: 10})
    writer = RecordingWriter()
    failed_node = _compiled_add(
        node_id="failed",
        node=AddNode(),
        invocation=NodeInvocation(mode=InvocationMode.MAP, map_input="item"),
    )
    downstream_node = _compiled_add(
        node_id="downstream",
        node=AddNode(),
        invocation=NodeInvocation(),
    )
    dependency = CompiledEdge(
        request=RunEdgeRequest(
            from_node="failed",
            from_port="value",
            to_node="downstream",
            to_port="item",
        ),
        projection=None,
        conversion_path=(),
    )
    plan = CompiledGraph(
        nodes=(failed_node, downstream_node),
        edges=(dependency,),
        pinned_outputs={},
    )
    edge_values = StubEdgeValueResolver(
        {
            "failed": {
                "item": ArtifactRefSequence.from_key(
                    key=VALUE.key,
                    item_refs=[missing_ref],
                ),
                "broadcast": broadcast_ref,
            },
            "downstream": {
                "item": broadcast_ref,
                "broadcast": broadcast_ref,
            },
        }
    )
    coordinator = GraphExecutionCoordinator(
        node_execution=NodeExecutionService(
            runtime=_runtime(resolver, writer),
            edge_values=cast(EdgeValueResolver, edge_values),
            node_secrets=UnavailableNodeSecretResolver(),
        )
    )

    result = await coordinator.execute(
        PreparedGraphExecution(
            workspace_id=WORKSPACE_ID,
            plan=plan,
            initial_outputs={},
            graph_id=None,
            graph_revision=None,
            secret_graph_id=None,
            secret_graph_revision=None,
            secret_node_ids=frozenset(),
            module_path=(),
            raise_node_errors=False,
        )
    )

    assert result.status == "failed"
    assert [node_result.status for node_result in result.node_results] == [
        "failed",
        "skipped",
    ]
    error = result.node_results[0].error
    assert error is not None
    assert (
        f"InvocationError: Node 'test.local_execution.add' MAP input 'item' "
        f"failed at item 0 ({missing_ref.artifact_id})" in error
    )
    assert "caused by KeyError" in error
    assert edge_values.calls == ["failed"]

    with pytest.raises(
        GraphExecutionError,
        match="nested graph node 'failed' \\(test.local_execution.add@1\\) failed",
    ) as raised:
        await coordinator.execute(
            PreparedGraphExecution(
                workspace_id=WORKSPACE_ID,
                plan=plan,
                initial_outputs={},
                graph_id=None,
                graph_revision=None,
                secret_graph_id=None,
                secret_graph_revision=None,
                secret_node_ids=frozenset(),
                module_path=(),
                raise_node_errors=True,
            )
        )

    assert raised.value.__cause__ is not None
    assert isinstance(raised.value.__cause__, RuntimeError)
    assert raised.value.__cause__.__cause__ is not None
    assert isinstance(raised.value.__cause__.__cause__, KeyError)


@pytest.mark.asyncio
async def test_nested_execution_does_not_replace_outer_module_progress() -> None:
    item_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key)
    broadcast_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key)
    resolver = IntegerResolver(
        {
            item_ref.artifact_id: 2,
            broadcast_ref.artifact_id: 3,
        }
    )
    writer = RecordingWriter()
    compiled_node = _compiled_add(
        node_id="nested-node",
        node=AddNode(),
        invocation=NodeInvocation(),
    )
    edge_values = StubEdgeValueResolver(
        {
            "nested-node": {
                "item": item_ref,
                "broadcast": broadcast_ref,
            }
        }
    )
    coordinator = GraphExecutionCoordinator(
        node_execution=NodeExecutionService(
            runtime=_runtime(resolver, writer),
            edge_values=cast(EdgeValueResolver, edge_values),
            node_secrets=UnavailableNodeSecretResolver(),
        )
    )
    control = RunExecutionControl()
    control.start_outer_node("outer-module")

    result = await coordinator.execute(
        PreparedGraphExecution(
            workspace_id=WORKSPACE_ID,
            plan=CompiledGraph(
                nodes=(compiled_node,),
                edges=(),
                pinned_outputs={},
            ),
            initial_outputs={},
            graph_id=None,
            graph_revision=None,
            secret_graph_id=None,
            secret_graph_revision=None,
            secret_node_ids=frozenset(),
            module_path=("nested-module@1",),
            raise_node_errors=True,
            control=control,
        )
    )

    assert result.status == "succeeded"
    assert control.active_node_id == "outer-module"


@pytest.mark.asyncio
async def test_failed_nodes_expose_typed_failure_codes_in_graph_results(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(
        logging.ERROR,
        logger="grafy_api.execution.coordinator",
    )
    writer = RecordingWriter()
    operator_node = _compiled_add(
        node_id="operator-failure",
        node=FailingNode(RuntimeError("host operator failure")),
        invocation=NodeInvocation(),
    )
    oci_node = _compiled_add(
        node_id="oci-failure",
        node=FailingNode(
            PluginInvocationError(
                "guest output rejected",
                failure_code=PluginFailureCode.OUTPUT_VALIDATION,
            )
        ),
        invocation=NodeInvocation(),
    )
    adapter_node = _compiled_add(
        node_id="adapter-failure",
        node=FailingNode(RuntimeError("never reached")),
        invocation=NodeInvocation(),
    )
    downstream_node = _compiled_add(
        node_id="downstream",
        node=AddNode(),
        invocation=NodeInvocation(),
    )
    edges = (
        CompiledEdge(
            request=RunEdgeRequest(
                from_node="operator-failure",
                from_port="value",
                to_node="downstream",
                to_port="item",
            ),
            projection=None,
            conversion_path=(),
        ),
    )
    operator_item = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key)
    operator_broadcast = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=VALUE.key,
    )
    oci_item = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key)
    oci_broadcast = ArtifactRef.from_key(
        artifact_id=uuid4(),
        key=VALUE.key,
    )
    edge_values = StubEdgeValueResolver(
        {
            "operator-failure": {
                "item": operator_item,
                "broadcast": operator_broadcast,
            },
            "oci-failure": {
                "item": oci_item,
                "broadcast": oci_broadcast,
            },
            "adapter-failure": {},
        }
    )
    resolver = IntegerResolver(
        {
            ref.artifact_id: index
            for index, ref in enumerate(
                (operator_item, operator_broadcast, oci_item, oci_broadcast),
                start=1,
            )
        }
    )
    coordinator = GraphExecutionCoordinator(
        node_execution=NodeExecutionService(
            runtime=_runtime(resolver, writer),
            edge_values=cast(EdgeValueResolver, edge_values),
            node_secrets=UnavailableNodeSecretResolver(),
        )
    )

    result = await coordinator.execute(
        PreparedGraphExecution(
            workspace_id=WORKSPACE_ID,
            plan=CompiledGraph(
                nodes=(operator_node, oci_node, adapter_node, downstream_node),
                edges=edges,
                pinned_outputs={},
            ),
            initial_outputs={},
            graph_id=None,
            graph_revision=None,
            secret_graph_id=None,
            secret_graph_revision=None,
            secret_node_ids=frozenset(),
            module_path=(),
            raise_node_errors=False,
        )
    )

    assert result.status == "failed"
    codes = [
        (node_result.node_id, node_result.failure_code)
        for node_result in result.node_results
    ]
    assert codes == [
        ("operator-failure", PluginFailureCode.OPERATOR_FAILURE),
        ("oci-failure", PluginFailureCode.OUTPUT_VALIDATION),
        ("adapter-failure", PluginFailureCode.INTERNAL_ADAPTER_FAILURE),
        ("downstream", None),
    ]
    adapter_error = result.node_results[2].error
    assert adapter_error is not None
    assert "is required" in adapter_error
    failure_records = [
        record for record in caplog.records if record.message == "node_execution_failed"
    ]
    assert [cast(str, record.__dict__["node_id"]) for record in failure_records] == [
        "operator-failure",
        "oci-failure",
        "adapter-failure",
    ]
    assert [
        cast(str, record.__dict__["failure_code"]) for record in failure_records
    ] == [
        PluginFailureCode.OPERATOR_FAILURE.value,
        PluginFailureCode.OUTPUT_VALIDATION.value,
        PluginFailureCode.INTERNAL_ADAPTER_FAILURE.value,
    ]
    assert all(
        cast(str, record.__dict__["workspace_id"]) == str(WORKSPACE_ID)
        for record in failure_records
    )
    assert all(
        record.exc_info is not None or hasattr(record, "exception")
        for record in failure_records
    )


@pytest.mark.asyncio
async def test_raise_mode_keeps_the_typed_failure_in_the_cause_chain() -> None:
    native_error = RuntimeError("controlled operator failure")
    item_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key)
    broadcast_ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE.key)
    resolver = IntegerResolver(
        {item_ref.artifact_id: 1, broadcast_ref.artifact_id: 2},
    )
    writer = RecordingWriter()
    failing_node = _compiled_add(
        node_id="typed-failure",
        node=FailingNode(native_error),
        invocation=NodeInvocation(),
    )
    coordinator = GraphExecutionCoordinator(
        node_execution=NodeExecutionService(
            runtime=_runtime(resolver, writer),
            edge_values=cast(
                EdgeValueResolver,
                StubEdgeValueResolver(
                    {
                        "typed-failure": {
                            "item": item_ref,
                            "broadcast": broadcast_ref,
                        },
                    }
                ),
            ),
            node_secrets=UnavailableNodeSecretResolver(),
        )
    )

    with pytest.raises(GraphExecutionError) as raised:
        await coordinator.execute(
            PreparedGraphExecution(
                workspace_id=WORKSPACE_ID,
                plan=CompiledGraph(
                    nodes=(failing_node,),
                    edges=(),
                    pinned_outputs={},
                ),
                initial_outputs={},
                graph_id=None,
                graph_revision=None,
                secret_graph_id=None,
                secret_graph_revision=None,
                secret_node_ids=frozenset(),
                module_path=(),
                raise_node_errors=True,
            )
        )

    run_error = raised.value.__cause__
    assert isinstance(run_error, NodeRunError)
    assert run_error.failure_code is PluginFailureCode.OPERATOR_FAILURE
    assert run_error.__cause__ is native_error
