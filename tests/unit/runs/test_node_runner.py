"""The node computation runner: one instance, computed from stored upstream results.

The operators are the workbench's own -- ``schema.builder`` and ``value.integer``,
with their real inline writers and resolvers over an in-memory unit of work -- and
the instances come from the kernel's own expansion of a Project document, so what
the runner is handed is what the scheduler will hand it: one ``ExpandedInstance``,
the fingerprint to store under, and the fingerprint of each instance it reads
from. The one operator the suite adds is ``test.echo_text``, because the workbench
has no operator that consumes a text value.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, final, override
from uuid import UUID

import pytest
from grafy_api.runs.errors import NodeComputationError
from grafy_api.runs.node_runner import NodeComputationRunnerFactory
from grafy_core.artifact_contracts import INTEGER_VALUE, TEXT_VALUE
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.canonical_conversions import INTEGER_TO_TEXT
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.graph_documents import (
    GraphArtifactTypeBinding,
    GraphConversion,
    GraphDocument,
    GraphEdge,
    GraphInputPlug,
    GraphNode,
    GraphOrigin,
    GraphPoint,
    GraphProjection,
)
from grafy_core.kernel.expansion import expand_graph
from grafy_core.kernel.instances import ExpandedGraph, InstanceKey
from grafy_core.kernel.memory_results import InMemoryResultStore
from grafy_core.kernel.project import GraphDefinition, ProjectDocument
from grafy_core.kernel.scheduler import ComputationRequest, ComputationRunner
from grafy_core.nodes import InPort, Node, NodeExecutionContext, OutPort
from grafy_core.plugins import Plugin, PluginRegistry, PluginRuntimeContext
from grafy_core.ports.node_secrets import UnavailableNodeSecretResolver
from grafy_core.runtime.execution import NodeRunError, NodeRuntime
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import (
    InputMaterializer,
    MaterializationProvenance,
)
from grafy_core.runtime.persistence import (
    ArtifactWriteContext,
    ArtifactWriterRegistry,
    OutputPersister,
)
from grafy_core.runtime.resolvers import ResolverRegistry
from grafy_core.schema_contracts import JSON_SCHEMA
from grafy_storage import LocalFileObjectStore
from grafy_workbench.schema import SCHEMAS
from grafy_workbench.text import TEXT
from grafy_workbench.value import VALUE
from pydantic import Field, StrictStr

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000941")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000942")
PROJECT_KEY = str(PROJECT_ID)
GRAPH_ID = "main"

#: The context each ``test.echo_text`` run was handed, in run order.
ECHO_RUNS: list[NodeExecutionContext] = []


ECHO = Plugin(slug="test.runs", title="Runner fixtures")
ECHO.register_artifact_type_dependency(TEXT_VALUE)


class EchoConfig(NodeConfig):
    prefix: StrictStr = Field(default="", description="Text put before the input.")


class EchoInput(NodeInput):
    text: Annotated[str, InPort(TEXT_VALUE)]


class EchoOutput(NodeOutput):
    text: Annotated[str, OutPort(TEXT_VALUE)]


@ECHO.node(operator_id="test.echo_text", version=1, title="Echo text")
@final
class EchoTextNode(Node[EchoConfig, EchoInput, EchoOutput]):
    """Returns its input with a prefix, recording the context it ran with."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: EchoConfig,
        inputs: EchoInput,
        /,
    ) -> EchoOutput:
        ECHO_RUNS.append(context)
        return EchoOutput(text=f"{config.prefix}{inputs.text}")


@dataclass
class Harness:
    """One project's runner, wired with the workbench's own writers and resolvers."""

    unit_of_work: InMemoryUnitOfWork
    store: InMemoryResultStore
    writers: ArtifactWriterRegistry
    resolvers: ResolverRegistry
    runner: ComputationRunner

    async def write(self, artifact_type: ArtifactTypeKey, value: object) -> ArtifactRef:
        ref = await self.writers.writer_for(artifact_type).write(
            value,
            ArtifactWriteContext(
                node_context=NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    project_id=PROJECT_ID,
                    node_id="seed",
                ),
                provenance=MaterializationProvenance(refs_by_input={}),
            ),
        )
        return ref

    async def write_sequence(
        self,
        artifact_type: ArtifactTypeKey,
        values: Sequence[object],
    ) -> ArtifactRefSequence:
        refs = [await self.write(artifact_type, value) for value in values]
        return ArtifactRefSequence.from_key(key=artifact_type, item_refs=refs)

    async def store_result(
        self,
        fingerprint: str,
        outputs: Mapping[str, ArtifactOutputValue],
    ) -> None:
        """Record what an upstream instance produced, as the scheduler would."""

        _ = await self.store.put_result(fingerprint, dict(outputs))

    async def text_of(self, ref: ArtifactRef) -> str:
        async with self.unit_of_work as unit_of_work:
            artifact = await unit_of_work.artifacts.get(WORKSPACE_ID, ref.artifact_id)
        assert artifact is not None
        payload = artifact.inline_payload
        assert isinstance(payload, dict)
        value = payload["value"]
        assert isinstance(value, str)
        return value

    async def artifacts_of(self, key: ArtifactTypeKey) -> list[ArtifactObject]:
        async with self.unit_of_work as unit_of_work:
            return await unit_of_work.artifacts.list_by_type(WORKSPACE_ID, key)

    async def compute_node(
        self,
        graph: ExpandedGraph,
        node_id: str,
        upstream: Mapping[str, str] | None = None,
    ) -> Mapping[str, ArtifactOutputValue]:
        """Compute one instance, reading each named feeder's result from the store."""

        keys = {key.node_id: key for key in graph.instances}
        if node_id not in keys:
            raise AssertionError(f"Expanded graph has no node {node_id!r}")
        instance = graph.instances[keys[node_id]]
        fingerprints: dict[InstanceKey, str] = {
            keys[feeder]: fingerprint
            for feeder, fingerprint in (upstream or {}).items()
        }
        return await self.runner(
            ComputationRequest(
                fingerprint=f"fingerprint-{node_id}",
                instance=instance,
                upstream_fingerprints=fingerprints,
            )
        )


def _node(
    node_id: str,
    operator_id: str,
    *,
    version: int = 1,
    config: Mapping[str, object] | None = None,
    plugs: Sequence[tuple[str, str]] = (),
    bindings: Sequence[tuple[str, ArtifactTypeKey]] = (),
) -> GraphNode:
    return GraphNode(
        kind="builtin",
        id=node_id,
        operator_id=operator_id,
        operator_version=version,
        config=dict(config or {}),
        position=GraphPoint(x=0, y=0),
        input_plugs=tuple(
            GraphInputPlug(id=plug_id, port=port) for plug_id, port in plugs
        ),
        artifact_type_bindings=tuple(
            GraphArtifactTypeBinding(variable=variable, artifact_type=artifact_type)
            for variable, artifact_type in bindings
        ),
    )


def _edge(
    from_node: str,
    from_port: str,
    to_node: str,
    to_port: str,
    *,
    edge_id: str | None = None,
    to_plug: str | None = None,
    collection_mode: str = "direct",
    projection: Sequence[str] | None = None,
    conversions: Sequence[tuple[str, int]] = (),
) -> GraphEdge:
    return GraphEdge(
        id=edge_id or f"{from_node}-{to_node}",
        from_node=from_node,
        from_port=from_port,
        to_node=to_node,
        to_port=to_port,
        to_plug=to_plug,
        collection_mode=collection_mode,  # type: ignore[arg-type]
        projection=(
            None if projection is None else GraphProjection(path=tuple(projection))
        ),
        conversion_path=tuple(
            GraphConversion(id=conversion_id, version=version)
            for conversion_id, version in conversions
        ),
    )


def _origin(
    to_node: str,
    to_port: str,
    value: ArtifactRef | ArtifactRefSequence,
    *,
    origin_id: str | None = None,
    collection_mode: str = "direct",
) -> GraphOrigin:
    return GraphOrigin(
        id=origin_id or f"origin-{to_node}",
        to_node=to_node,
        to_port=to_port,
        value=value,
        collection_mode=collection_mode,  # type: ignore[arg-type]
    )


def _expand(
    *nodes: GraphNode,
    edges: Sequence[GraphEdge] = (),
    origins: Sequence[GraphOrigin] = (),
) -> ExpandedGraph:
    document = GraphDocument(
        nodes=tuple(nodes),
        edges=tuple(edges),
        origins=tuple(origins),
    )
    project = ProjectDocument(
        graphs=(GraphDefinition(id=GRAPH_ID, name="Main", document=document),),
    )
    return expand_graph(project, GRAPH_ID, project_id=PROJECT_KEY)


def _field(field_id: str, name: str, kind: str) -> dict[str, object]:
    return {"id": field_id, "name": name, "kind": kind}


@pytest.fixture(autouse=True)
def _clear_echo_runs() -> None:
    ECHO_RUNS.clear()


def build_factory(
    *,
    registry: PluginRegistry,
    runtime: NodeRuntime,
    resolvers: ResolverRegistry,
    writers: ArtifactWriterRegistry,
    unit_of_work: InMemoryUnitOfWork,
    plugin_context: PluginRuntimeContext | None,
) -> NodeComputationRunnerFactory:
    return NodeComputationRunnerFactory(
        registry=registry,
        runtime=runtime,
        resolvers=resolvers,
        writers=writers,
        unit_of_work=unit_of_work,
        node_secrets=UnavailableNodeSecretResolver(),
        max_map_concurrency=2,
        plugin_context=plugin_context,
    )


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    unit_of_work = InMemoryUnitOfWork()
    runtime_context = PluginRuntimeContext(
        workspace=tmp_path,
        storage=LocalFileObjectStore(tmp_path / "objects"),
        uow=unit_of_work,
        bucket="artifacts",
    )
    registry = PluginRegistry()
    for family in (VALUE, TEXT, SCHEMAS, ECHO):
        registry.install(family)
    registry.freeze()
    resolvers = ResolverRegistry(list(registry.build_resolvers(runtime_context)))
    writers = ArtifactWriterRegistry(list(registry.build_writers(runtime_context)))
    runtime = NodeRuntime(
        materializer=InputMaterializer(resolvers),
        persister=OutputPersister(writers),
    )
    factory = build_factory(
        registry=registry,
        runtime=runtime,
        resolvers=resolvers,
        writers=writers,
        unit_of_work=unit_of_work,
        plugin_context=runtime_context,
    )
    store = InMemoryResultStore()
    return Harness(
        unit_of_work=unit_of_work,
        store=store,
        writers=writers,
        resolvers=resolvers,
        runner=factory.for_project(
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            store=store,
        ),
    )


async def test_computes_a_node_from_the_result_its_upstream_stored(
    harness: Harness,
) -> None:
    """A child schema reaches its parent through the store, not through memory."""

    graph = _expand(
        _node(
            "child",
            "schema.builder",
            config={"fields": [_field("amount", "Amount", "integer")]},
        ),
        _node(
            "parent",
            "schema.builder",
            config={"fields": [_field("line", "Line", "schema")]},
            plugs=(("line", "schemas"),),
        ),
        edges=(_edge("child", "json_schema", "parent", "schemas", to_plug="line"),),
    )

    child_outputs = await harness.compute_node(graph, "child")
    child_ref = child_outputs["json_schema"]
    assert isinstance(child_ref, ArtifactRef)
    await harness.store_result("child", child_outputs)

    parent_outputs = await harness.compute_node(graph, "parent", {"child": "child"})
    parent_ref = parent_outputs["json_schema"]
    assert isinstance(parent_ref, ArtifactRef)
    assert parent_ref.key() == JSON_SCHEMA.key
    assert await harness.text_of(parent_ref) == (
        '{"type":"object","properties":{"Line":{"type":"object","properties":'
        '{"Amount":{"type":["integer","null"]}},"additionalProperties":false}},'
        '"additionalProperties":false}'
    )
    # The child ran once: the parent read its stored output rather than re-running it.
    assert len([item for item in await harness.artifacts_of(JSON_SCHEMA.key)]) == 2


async def test_applies_the_projection_an_edge_declares(harness: Harness) -> None:
    """An edge projected at ``value`` delivers that field as a text artifact."""

    schema_text = '{"type":"object","properties":{},"required":[]}'
    child_ref = await harness.write(JSON_SCHEMA.key, schema_text)
    graph = _expand(
        _node("child", "schema.builder", config={"fields": []}),
        _node("echo", "test.echo_text", config={"prefix": "projected: "}),
        edges=(_edge("child", "json_schema", "echo", "text", projection=("value",)),),
    )
    await harness.store_result("child", {"json_schema": child_ref})

    outputs = await harness.compute_node(graph, "echo", {"child": "child"})
    echo_ref = outputs["text"]
    assert isinstance(echo_ref, ArtifactRef)
    assert echo_ref.key() == TEXT_VALUE.key
    assert await harness.text_of(echo_ref) == f"projected: {schema_text}"

    projected = [
        artifact
        for artifact in await harness.artifacts_of(TEXT_VALUE.key)
        if artifact.id != echo_ref.artifact_id
    ]
    assert len(projected) == 1
    assert projected[0].metadata["projection_path"] == ["value"]
    assert projected[0].metadata["source_node_id"] == "child"
    assert projected[0].metadata["target_node_id"] == "echo"


async def test_applies_the_conversion_path_an_edge_declares(harness: Harness) -> None:
    graph = _expand(
        _node("number", "value.integer", config={"value": 41}),
        _node("echo", "test.echo_text", config={"prefix": "got "}),
        edges=(
            _edge(
                "number",
                "value",
                "echo",
                "text",
                conversions=[(INTEGER_TO_TEXT.key.id, INTEGER_TO_TEXT.key.version)],
            ),
        ),
    )
    number_ref = await harness.write(INTEGER_VALUE.key, 41)
    await harness.store_result("number", {"value": number_ref})

    outputs = await harness.compute_node(graph, "echo", {"number": "number"})
    echo_ref = outputs["text"]
    assert isinstance(echo_ref, ArtifactRef)
    assert await harness.text_of(echo_ref) == "got 41"
    assert await harness.resolvers.resolve(echo_ref, str, WORKSPACE_ID) == "got 41"

    converted = [
        artifact
        for artifact in await harness.artifacts_of(TEXT_VALUE.key)
        if artifact.id != echo_ref.artifact_id
    ]
    assert len(converted) == 1
    assert converted[0].metadata["conversion_id"] == INTEGER_TO_TEXT.key.id
    assert converted[0].metadata["source_node_id"] == "number"


async def test_boundary_nodes_pass_their_single_value_through(harness: Harness) -> None:
    """``graph.input`` and ``graph.output`` run no operator and change no value."""

    held = await harness.write(TEXT_VALUE.key, "carried")
    graph = _expand(
        _node(
            "in",
            "graph.input",
            config={"public_name": "seed"},
            bindings=[("T", TEXT_VALUE.key)],
        ),
        _node(
            "out",
            "graph.output",
            config={"public_name": "result"},
            bindings=[("T", TEXT_VALUE.key)],
        ),
        edges=(_edge("in", "value", "out", "value"),),
        origins=(_origin("in", "value", held),),
    )

    input_outputs = await harness.compute_node(graph, "in")
    assert input_outputs == {"value": held}

    await harness.store_result("in", input_outputs)
    output_outputs = await harness.compute_node(graph, "out", {"in": "in"})
    assert output_outputs == {"value": held}
    assert ECHO_RUNS == []
    # Nothing was written: a boundary passes the reference it was given.
    assert [artifact.id for artifact in await harness.artifacts_of(TEXT_VALUE.key)] == [
        held.artifact_id
    ]


async def test_map_runs_the_node_once_per_item(harness: Harness) -> None:
    sequence = await harness.write_sequence(
        TEXT_VALUE.key, ["first", "second", "third"]
    )
    graph = _expand(
        _node("echo", "test.echo_text", config={"prefix": "* "}),
        origins=(_origin("echo", "text", sequence, collection_mode="map"),),
    )

    outputs = await harness.compute_node(graph, "echo")
    mapped = outputs["text"]
    assert isinstance(mapped, ArtifactRefSequence)
    assert ArtifactTypeKey(mapped.artifact_type, mapped.schema_version) == (
        TEXT_VALUE.key
    )
    assert len(mapped.item_refs) == 3
    items = [await harness.text_of(ref) for ref in mapped.item_refs]
    assert items == ["* first", "* second", "* third"]

    assert [context.invocation_index for context in ECHO_RUNS] == [0, 1, 2]
    assert [context.invocation_path for context in ECHO_RUNS] == [(0,), (1,), (2,)]
    for context in ECHO_RUNS:
        assert context.workspace_id is WORKSPACE_ID
        assert context.project_id is PROJECT_ID
        assert context.graph_id == GRAPH_ID
        assert context.node_id == "echo"
        assert context.call_path == ()
        assert context.fingerprint == "fingerprint-echo"


async def test_a_map_connection_must_carry_a_sequence(harness: Harness) -> None:
    single = await harness.write(TEXT_VALUE.key, "one")
    graph = _expand(
        _node("echo", "test.echo_text", config={"prefix": ""}),
        origins=(_origin("echo", "text", single, collection_mode="map"),),
    )

    with pytest.raises(NodeComputationError, match="collection mode 'map'"):
        await harness.compute_node(graph, "echo")


async def test_an_operator_this_build_does_not_register_raises(
    harness: Harness,
) -> None:
    graph = _expand(_node("ghost", "ghost.thing", version=7))

    with pytest.raises(
        NodeComputationError,
        match=r"unavailable operator ghost\.thing@7",
    ):
        await harness.compute_node(graph, "ghost")


async def test_a_missing_upstream_result_raises(harness: Harness) -> None:
    graph = _expand(
        _node("child", "schema.builder", config={"fields": []}),
        _node(
            "parent",
            "schema.builder",
            config={"fields": [_field("line", "Line", "schema")]},
            plugs=(("line", "schemas"),),
        ),
        edges=(_edge("child", "json_schema", "parent", "schemas", to_plug="line"),),
    )

    with pytest.raises(
        NodeComputationError,
        match=r"under fingerprint absent, which the result store does not hold",
    ):
        await harness.compute_node(graph, "parent", {"child": "absent"})


async def test_a_value_of_a_type_the_input_rejects_raises(harness: Harness) -> None:
    number_ref = await harness.write(INTEGER_VALUE.key, 1)
    graph = _expand(
        _node("number", "value.integer", config={"value": 1}),
        _node("echo", "test.echo_text", config={"prefix": ""}),
        edges=(_edge("number", "value", "echo", "text"),),
    )
    await harness.store_result("number", {"value": number_ref})

    with pytest.raises(
        NodeComputationError,
        match=r"delivers scalar.integer@1 to node 'echo' input 'text', which accepts "
        r"scalar.text@1",
    ):
        await harness.compute_node(graph, "echo", {"number": "number"})


async def test_a_failing_operator_raises(harness: Harness) -> None:
    """The node runs, its operator refuses, and the failure travels up."""

    child_ref = await harness.write(
        JSON_SCHEMA.key,
        '{"type":"object","properties":{},"required":[]}',
    )
    graph = _expand(
        _node("child", "schema.builder", config={"fields": []}),
        _node(
            "parent",
            "schema.builder",
            config={"fields": [_field("name", "Name", "string")]},
            plugs=(("nested", "schemas"),),
        ),
        edges=(_edge("child", "json_schema", "parent", "schemas", to_plug="nested"),),
    )
    await harness.store_result("child", {"json_schema": child_ref})

    with pytest.raises(
        NodeRunError,
        match=r"Node 'parent' operator schema.builder@1 failed",
    ):
        await harness.compute_node(graph, "parent", {"child": "child"})


async def test_a_runner_with_no_plugin_context_computes_operators_that_need_none(
    tmp_path: Path,
) -> None:
    """The composition seam is complete without a plugin runtime context.

    An operator that needs no runtime services is built from its own class, so a
    caller that wires the runner with the registry, the node runtime, the
    resolvers, the writers and the unit of work gets a working computation.
    """

    unit_of_work = InMemoryUnitOfWork()
    runtime_context = PluginRuntimeContext(
        workspace=tmp_path,
        storage=LocalFileObjectStore(tmp_path / "objects"),
        uow=unit_of_work,
        bucket="artifacts",
    )
    registry = PluginRegistry()
    for family in (VALUE, TEXT, ECHO):
        registry.install(family)
    registry.freeze()
    resolvers = ResolverRegistry(list(registry.build_resolvers(runtime_context)))
    writers = ArtifactWriterRegistry(list(registry.build_writers(runtime_context)))
    factory = build_factory(
        registry=registry,
        runtime=NodeRuntime(
            materializer=InputMaterializer(resolvers),
            persister=OutputPersister(writers),
        ),
        resolvers=resolvers,
        writers=writers,
        unit_of_work=unit_of_work,
        plugin_context=None,
    )
    store = InMemoryResultStore()
    harness = Harness(
        unit_of_work=unit_of_work,
        store=store,
        writers=writers,
        resolvers=resolvers,
        runner=factory.for_project(
            workspace_id=WORKSPACE_ID,
            project_id=PROJECT_ID,
            store=store,
        ),
    )
    number_ref = await harness.write(INTEGER_VALUE.key, 7)
    graph = _expand(
        _node("number", "value.integer", config={"value": 7}),
        _node("echo", "test.echo_text", config={"prefix": "seven: "}),
        edges=(
            _edge(
                "number",
                "value",
                "echo",
                "text",
                conversions=[(INTEGER_TO_TEXT.key.id, INTEGER_TO_TEXT.key.version)],
            ),
        ),
    )
    await harness.store_result("number", {"value": number_ref})

    outputs = await harness.compute_node(graph, "echo", {"number": "number"})

    echo_ref = outputs["text"]
    assert isinstance(echo_ref, ArtifactRef)
    assert await harness.text_of(echo_ref) == "seven: 7"
