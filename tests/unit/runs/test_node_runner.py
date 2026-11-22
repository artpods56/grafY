"""The node computation runner: one instance, computed from stored upstream results.

The operators are the workbench's own -- ``schema.builder`` and ``value.integer``,
with their real artifact declarations over an in-memory unit of work -- and
the instances come from the kernel's own expansion of a Project document, so what
the runner is handed is what the scheduler will hand it: one ``ExpandedInstance``,
the fingerprint to store under, and the fingerprint of each instance it reads
from. The one operator the suite adds is ``test.echo_text``, because the workbench
has no operator that consumes a text value.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import final, override
from uuid import UUID

import pytest
from PIL import Image
from grafy_api.runs.errors import NodeComputationError
from grafy_api.runs.node_runner import NodeComputationRunnerFactory
from grafy_core.artifact_contracts import INTEGER_VALUE, RASTER_IMAGE, TEXT_VALUE
from grafy_core.artifacts import (
    ArtifactObject,
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.canonical_conversions import (
    INTEGER_TO_TEXT,
    PNG_FILE_TO_RASTER,
    TEXT_FILE_TO_TEXT,
)
from grafy_core.documents import (
    FILE_ARTIFACTS,
    RASTER_IMAGE_ARTIFACT,
    PngFile,
    RasterImage,
    TxtFile,
)
from grafy_core.file_contracts import PNG_FILE, TXT_FILE
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
from grafy_core.nodes import (
    Node,
    NodeExecutionContext,
    RefSequence,
)
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.plugins import (
    NodeSecretInput,
    Plugin,
    PluginRegistry,
    PluginRuntimeContext,
)
from grafy_core.ports.node_secrets import (
    NodeSecretResolverPort,
    NodeSecretUnavailableError,
    UnavailableNodeSecretResolver,
)
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.execution import NodeRunError, NodeRuntime
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import (
    InputMaterializer,
    MaterializationProvenance,
)
from grafy_core.runtime.persistence import (
    ArtifactWriteContext,
    OutputPersister,
)
from grafy_core.schema_contracts import JSON_SCHEMA
from grafy_storage import LocalFileObjectStore
from grafy_workbench.schema import SCHEMAS
from grafy_workbench.schema.values import JsonSchemaText
from grafy_workbench.sequence import SEQUENCES
from grafy_workbench.text import TEXT
from grafy_workbench.value import VALUE
from pydantic import Field, SecretStr, StrictStr

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000941")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000942")
PROJECT_KEY = str(PROJECT_ID)
GRAPH_ID = "main"

#: The context each ``test.echo_text`` run was handed, in run order.
ECHO_RUNS: list[NodeExecutionContext] = []
#: The node and the key each ``test.read_secret`` run resolved, in run order.
SECRET_RUNS: list[tuple[str | None, str]] = []
JOINED: list[list[str]] = []
RASTER_HANDLES: list[RasterImage] = []
RASTER_SEQUENCES: list[RefSequence[RasterImage]] = []


ECHO = Plugin(slug="test.runs", title="Runner fixtures")
ECHO.register_artifact_type_dependency(TEXT_VALUE)
ECHO.register_artifact_type_dependency(RASTER_IMAGE)


class EchoConfig(NodeConfig):
    prefix: StrictStr = Field(default="", description="Text put before the input.")


class EchoInput(NodeInput):
    text: str


class EchoOutput(NodeOutput):
    text: str


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


#: A key declared against the origin it belongs to, so a saved base URL moves it.
API_KEY = NodeSecretInput(
    name="api_key",
    title="API key",
    config_dependencies=("base_url",),
)


class SecretConfig(NodeConfig):
    base_url: StrictStr = Field(
        default="https://api.example.test",
        description="Origin the key belongs to.",
    )


class SecretInput(NodeInput):
    pass


class SecretOutput(NodeOutput):
    text: str


@ECHO.node(
    operator_id="test.read_secret",
    version=1,
    title="Read secret",
    secret_inputs=(API_KEY,),
    required_capabilities=(PluginRuntimeCapability.NODE_SECRETS,),
)
@final
class ReadSecretNode(Node[SecretConfig, SecretInput, SecretOutput]):
    """Reads its own API key off its execution context and returns it as text."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: SecretConfig,
        inputs: SecretInput,
        /,
    ) -> SecretOutput:
        del config, inputs
        api_key = await context.secrets.require(API_KEY.name)
        SECRET_RUNS.append((context.node_id, api_key.get_secret_value()))
        return SecretOutput(text=api_key.get_secret_value())


class RecordingNodeSecrets:
    """A secret store holding one key per node, looked up by where the node sits."""

    def __init__(self, keys: Mapping[str, str] | None = None) -> None:
        self.keys: dict[str, str] = dict(keys or {})
        self.lookups: list[dict[str, object]] = []

    async def resolve_secret(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
        actor_user_id: UUID | None = None,
    ) -> SecretStr:
        self.lookups.append(
            {
                "workspace_id": workspace_id,
                "project_id": project_id,
                "graph_id": graph_id,
                "node_id": node_id,
                "name": name,
                "dependencies": dict(dependencies),
            }
        )
        key = self.keys.get(str(node_id))
        if key is None:
            raise NodeSecretUnavailableError("Required node secret is not configured")
        return SecretStr(key)

    async def cache_revision(
        self,
        *,
        workspace_id: UUID,
        project_id: UUID | None,
        graph_id: str | None,
        node_id: str | None,
        name: str,
        dependencies: Mapping[str, JsonValue],
    ) -> str:
        del workspace_id, project_id, graph_id, node_id, name, dependencies
        return "revision"


class JoinConfig(NodeConfig):
    pass


class JoinInput(NodeInput):
    items: list[str]


class JoinOutput(NodeOutput):
    text: str


@ECHO.node(operator_id="test.join_text", version=1, title="Join text")
@final
class JoinTextNode(Node[JoinConfig, JoinInput, JoinOutput]):
    """Joins each sequence item with a bar, in the order the sequence carries."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: JoinConfig,
        inputs: JoinInput,
        /,
    ) -> JoinOutput:
        del context, config
        JOINED.append(list(inputs.items))
        return JoinOutput(text="|".join(inputs.items))


class RasterConfig(NodeConfig):
    pass


class RasterInput(NodeInput):
    image: RasterImage


class RasterOutput(NodeOutput):
    text: str


@ECHO.node(operator_id="test.take_raster", version=1, title="Take raster")
@final
class TakeRasterNode(Node[RasterConfig, RasterInput, RasterOutput]):
    """Records the raster handle a value port receives."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: RasterConfig,
        inputs: RasterInput,
        /,
    ) -> RasterOutput:
        del context, config
        RASTER_HANDLES.append(inputs.image)
        return RasterOutput(text="handle")


class RasterSequenceInput(NodeInput):
    images: RefSequence[RasterImage]


@ECHO.node(operator_id="test.take_rasters", version=1, title="Take rasters")
@final
class TakeRastersNode(Node[RasterConfig, RasterSequenceInput, RasterOutput]):
    """Records the stored sequence a ref-sequence port receives."""

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: RasterConfig,
        inputs: RasterSequenceInput,
        /,
    ) -> RasterOutput:
        del context, config
        RASTER_SEQUENCES.append(inputs.images)
        return RasterOutput(text="images")


@dataclass
class Harness:
    """One project's runner, wired with the workbench's artifact declarations."""

    unit_of_work: InMemoryUnitOfWork
    store: InMemoryResultStore
    values: ArtifactValues
    runner: ComputationRunner
    object_root: Path
    secrets: RecordingNodeSecrets

    def stored_object_count(self) -> int:
        root = self.object_root
        if not root.exists():
            return 0
        return sum(
            1 for path in root.rglob("*") if path.is_file() and ".tmp-" not in path.name
        )

    async def write(self, artifact_type: ArtifactTypeKey, value: object) -> ArtifactRef:
        context = ArtifactWriteContext(
            node_context=NodeExecutionContext(
                workspace_id=WORKSPACE_ID,
                project_id=PROJECT_ID,
                node_id="seed",
            ),
            provenance=MaterializationProvenance(refs_by_input={}),
        )
        return await self.values.write(artifact_type, value, context)

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
        async with self.unit_of_work as uow:
            artifact = await uow.artifacts.get(WORKSPACE_ID, ref.artifact_id)
        assert artifact is not None
        payload = artifact.inline_payload
        assert isinstance(payload, dict)
        value = payload["value"]
        assert isinstance(value, str)
        return value

    async def artifacts_of(self, key: ArtifactTypeKey) -> list[ArtifactObject]:
        async with self.unit_of_work as uow:
            return await uow.artifacts.list_by_type(WORKSPACE_ID, key)

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
    conversions: Sequence[tuple[str, int]] = (),
) -> GraphOrigin:
    return GraphOrigin(
        id=origin_id or f"origin-{to_node}",
        to_node=to_node,
        to_port=to_port,
        value=value,
        collection_mode=collection_mode,  # type: ignore[arg-type]
        conversion_path=tuple(
            GraphConversion(id=conversion_id, version=version)
            for conversion_id, version in conversions
        ),
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
    SECRET_RUNS.clear()
    JOINED.clear()
    RASTER_HANDLES.clear()
    RASTER_SEQUENCES.clear()


def build_factory(
    *,
    registry: PluginRegistry,
    runtime: NodeRuntime,
    plugin_context: PluginRuntimeContext | None,
    values: ArtifactValues,
    node_secrets: NodeSecretResolverPort | None = None,
) -> NodeComputationRunnerFactory:
    return NodeComputationRunnerFactory(
        registry=registry,
        runtime=runtime,
        node_secrets=node_secrets or UnavailableNodeSecretResolver(),
        values=values,
        max_map_concurrency=2,
        plugin_context=plugin_context,
    )


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    uow = InMemoryUnitOfWork()
    object_root = tmp_path / "objects"
    storage = LocalFileObjectStore(object_root)
    registry = PluginRegistry()
    for family in (VALUE, TEXT, SCHEMAS, SEQUENCES, ECHO):
        registry.install(family)
    registry.freeze()
    secrets = RecordingNodeSecrets()
    values = ArtifactValues(
        (*registry.artifacts, *FILE_ARTIFACTS, RASTER_IMAGE_ARTIFACT),
        uow=uow,
        storage=storage,
        bucket="artifacts",
        storage_backend="local",
    )
    runtime_context = PluginRuntimeContext(
        workspace=tmp_path,
        storage=storage,
        uow=uow,
        bucket="artifacts",
        values=values,
    )
    runtime = NodeRuntime(
        materializer=InputMaterializer(values),
        persister=OutputPersister(values),
    )
    factory = build_factory(
        registry=registry,
        runtime=runtime,
        plugin_context=runtime_context,
        values=values,
        node_secrets=secrets,
    )
    store = InMemoryResultStore()
    return Harness(
        unit_of_work=uow,
        store=store,
        values=values,
        object_root=object_root,
        secrets=secrets,
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


async def test_collect_ignores_the_spare_plug_nothing_feeds(harness: Harness) -> None:
    """The canvas keeps an empty plug on a collection for its next member."""

    first = await harness.write(
        JSON_SCHEMA.key, JsonSchemaText(value='{"type":"object"}')
    )
    second = await harness.write(
        JSON_SCHEMA.key,
        JsonSchemaText(value='{"type":"object","properties":{}}'),
    )
    graph = _expand(
        _node("first", "schema.builder", config={"fields": []}),
        _node("second", "schema.builder", config={"fields": []}),
        _node(
            "collect",
            "sequence.collect",
            plugs=(("one", "items"), ("two", "items"), ("spare", "items")),
            bindings=(("T", JSON_SCHEMA.key),),
        ),
        edges=(
            _edge("first", "json_schema", "collect", "items", to_plug="one"),
            _edge("second", "json_schema", "collect", "items", to_plug="two"),
        ),
    )
    await harness.store_result("first", {"json_schema": first})
    await harness.store_result("second", {"json_schema": second})

    outputs = await harness.compute_node(
        graph, "collect", {"first": "first", "second": "second"}
    )

    sequence = outputs["items"]
    assert isinstance(sequence, ArtifactRefSequence)
    assert [ref.artifact_id for ref in sequence.item_refs] == [
        first.artifact_id,
        second.artifact_id,
    ]


async def test_collect_with_only_a_spare_plug_has_no_input(harness: Harness) -> None:
    graph = _expand(
        _node(
            "collect",
            "sequence.collect",
            plugs=(("spare", "items"),),
            bindings=(("T", JSON_SCHEMA.key),),
        ),
    )

    with pytest.raises(NodeComputationError, match=r"required input 'items' has no"):
        await harness.compute_node(graph, "collect")


async def test_a_plug_that_keeps_no_spares_must_be_fed(harness: Harness) -> None:
    """A schema field's plug is not a spare: leaving it empty is an error."""

    graph = _expand(
        _node(
            "parent",
            "schema.builder",
            config={"fields": [_field("line", "Line", "schema")]},
            plugs=(("line", "schemas"),),
        ),
    )

    with pytest.raises(
        NodeComputationError,
        match="Each slot needs exactly one connection",
    ):
        await harness.compute_node(graph, "parent")


async def test_applies_the_projection_an_edge_declares(harness: Harness) -> None:
    """An edge projected at ``value`` delivers that field as a text artifact."""

    schema_text = '{"type":"object","properties":{},"required":[]}'
    child_ref = await harness.write(JSON_SCHEMA.key, JsonSchemaText(value=schema_text))
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

    text_rows = await harness.artifacts_of(TEXT_VALUE.key)
    assert [artifact.id for artifact in text_rows] == [echo_ref.artifact_id]
    assert text_rows[0].metadata["provenance"] == {
        "text": [
            {
                "artifact_id": str(child_ref.artifact_id),
                "artifact_type": child_ref.artifact_type,
                "schema_version": child_ref.schema_version,
                "projection_path": ["value"],
            }
        ]
    }


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
                conversions=[(INTEGER_TO_TEXT.id, INTEGER_TO_TEXT.version)],
            ),
        ),
    )
    number_ref = await harness.write(INTEGER_VALUE.key, 41)
    await harness.store_result("number", {"value": number_ref})

    outputs = await harness.compute_node(graph, "echo", {"number": "number"})
    echo_ref = outputs["text"]
    assert isinstance(echo_ref, ArtifactRef)
    assert await harness.text_of(echo_ref) == "got 41"
    assert await harness.values.resolve(echo_ref, WORKSPACE_ID) == "got 41"

    text_rows = await harness.artifacts_of(TEXT_VALUE.key)
    assert [artifact.id for artifact in text_rows] == [echo_ref.artifact_id]
    assert text_rows[0].metadata["provenance"] == {
        "text": [
            {
                "artifact_id": str(number_ref.artifact_id),
                "artifact_type": number_ref.artifact_type,
                "schema_version": number_ref.schema_version,
                "conversion_keys": [
                    {"id": INTEGER_TO_TEXT.id, "version": INTEGER_TO_TEXT.version}
                ],
            }
        ]
    }


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


async def test_a_slot_with_no_connection_raises_without_naming_an_id(
    harness: Harness,
) -> None:
    graph = _expand(
        _node(
            "parent",
            "schema.builder",
            config={"fields": [_field("line", "Line", "schema")]},
            plugs=(("line", "schemas"),),
        ),
    )

    with pytest.raises(
        NodeComputationError,
        match="Each slot needs exactly one connection",
    ) as failure:
        await harness.compute_node(graph, "parent")

    assert "line" not in str(failure.value)


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
        JsonSchemaText(value='{"type":"object","properties":{},"required":[]}'),
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
    artifact declarations and the unit of work gets a working computation.
    """

    uow = InMemoryUnitOfWork()
    object_root = tmp_path / "objects"
    storage = LocalFileObjectStore(object_root)
    registry = PluginRegistry()
    for family in (VALUE, TEXT, ECHO):
        registry.install(family)
    registry.freeze()
    values = ArtifactValues(
        registry.artifacts,
        uow=uow,
        storage=storage,
        bucket="artifacts",
        storage_backend="local",
    )
    secrets = RecordingNodeSecrets()
    factory = build_factory(
        registry=registry,
        runtime=NodeRuntime(
            materializer=InputMaterializer(values),
            persister=OutputPersister(values),
        ),
        plugin_context=None,
        values=values,
        node_secrets=secrets,
    )
    store = InMemoryResultStore()
    harness = Harness(
        unit_of_work=uow,
        store=store,
        values=values,
        object_root=object_root,
        secrets=secrets,
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
                conversions=[(INTEGER_TO_TEXT.id, INTEGER_TO_TEXT.version)],
            ),
        ),
    )
    await harness.store_result("number", {"value": number_ref})

    outputs = await harness.compute_node(graph, "echo", {"number": "number"})

    echo_ref = outputs["text"]
    assert isinstance(echo_ref, ArtifactRef)
    assert await harness.text_of(echo_ref) == "seven: 7"


def _png_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


async def test_a_text_file_becomes_the_decoded_string_without_a_new_row(
    harness: Harness,
) -> None:
    payload = b"hello\n"
    source = await harness.write(
        TXT_FILE.key,
        TxtFile.from_content(
            payload,
            content_type="text/plain",
            filename="note.txt",
        ),
    )
    graph = _expand(
        _node("echo", "test.echo_text", config={"prefix": ""}),
        origins=(
            _origin(
                "echo",
                "text",
                source,
                conversions=[(TEXT_FILE_TO_TEXT.id, TEXT_FILE_TO_TEXT.version)],
            ),
        ),
    )

    outputs = await harness.compute_node(graph, "echo")

    echo_ref = outputs["text"]
    assert isinstance(echo_ref, ArtifactRef)
    assert await harness.text_of(echo_ref) == "hello\n"
    assert [artifact.id for artifact in await harness.artifacts_of(TEXT_VALUE.key)] == [
        echo_ref.artifact_id
    ]
    assert [artifact.id for artifact in await harness.artifacts_of(TXT_FILE.key)] == [
        source.artifact_id
    ]


async def test_a_png_becomes_a_raster_handle_without_a_new_row(
    harness: Harness,
) -> None:
    payload = _png_bytes()
    source = await harness.write(
        PNG_FILE.key,
        PngFile.from_content(payload, content_type="image/png", filename="dot.png"),
    )
    stored_before = harness.stored_object_count()
    graph = _expand(
        _node("take", "test.take_raster"),
        origins=(
            _origin(
                "take",
                "image",
                source,
                conversions=[(PNG_FILE_TO_RASTER.id, PNG_FILE_TO_RASTER.version)],
            ),
        ),
    )

    await harness.compute_node(graph, "take")

    assert len(RASTER_HANDLES) == 1
    handle = RASTER_HANDLES[0]
    assert handle.filename == "dot.png"
    assert await handle.read(max_bytes=1024 * 1024) == payload
    assert await harness.artifacts_of(RASTER_IMAGE.key) == []
    assert harness.stored_object_count() == stored_before


async def test_a_png_into_a_raster_sequence_still_writes_one_artifact(
    harness: Harness,
) -> None:
    payload = _png_bytes()
    source = await harness.write(
        PNG_FILE.key,
        PngFile.from_content(payload, content_type="image/png", filename="dot.png"),
    )
    sequence = ArtifactRefSequence.from_key(key=PNG_FILE.key, item_refs=[source])
    graph = _expand(
        _node("take", "test.take_rasters"),
        origins=(
            _origin(
                "take",
                "images",
                sequence,
                conversions=[(PNG_FILE_TO_RASTER.id, PNG_FILE_TO_RASTER.version)],
            ),
        ),
    )

    outputs = await harness.compute_node(graph, "take")

    assert len(RASTER_SEQUENCES) == 1
    seen = RASTER_SEQUENCES[0]
    assert len(seen.item_refs) == 1
    written = seen.item_refs[0]
    assert written.key() == RASTER_IMAGE.key
    loaded = await harness.values.resolve(written, WORKSPACE_ID)
    assert isinstance(loaded, RasterImage)
    assert await loaded.read(max_bytes=1024 * 1024) == payload
    raster_rows = await harness.artifacts_of(RASTER_IMAGE.key)
    assert [artifact.id for artifact in raster_rows] == [written.artifact_id]

    echo_ref = outputs["text"]
    assert isinstance(echo_ref, ArtifactRef)
    text_rows = await harness.artifacts_of(TEXT_VALUE.key)
    assert text_rows[0].metadata["provenance"] == {
        "images": [
            {
                "artifact_id": str(source.artifact_id),
                "artifact_type": source.artifact_type,
                "schema_version": source.schema_version,
                "conversion_keys": [
                    {
                        "id": PNG_FILE_TO_RASTER.id,
                        "version": PNG_FILE_TO_RASTER.version,
                    }
                ],
            }
        ]
    }
    assert echo_ref.artifact_id != written.artifact_id


async def test_a_sequence_conversion_yields_one_value_per_item_in_order(
    harness: Harness,
) -> None:
    sequence = await harness.write_sequence(INTEGER_VALUE.key, [2, 3, 5])
    graph = _expand(
        _node("join", "test.join_text"),
        origins=(
            _origin(
                "join",
                "items",
                sequence,
                conversions=[(INTEGER_TO_TEXT.id, INTEGER_TO_TEXT.version)],
            ),
        ),
    )

    outputs = await harness.compute_node(graph, "join")

    assert JOINED == [["2", "3", "5"]]
    echo_ref = outputs["text"]
    assert isinstance(echo_ref, ArtifactRef)
    assert await harness.text_of(echo_ref) == "2|3|5"
    assert [artifact.id for artifact in await harness.artifacts_of(TEXT_VALUE.key)] == [
        echo_ref.artifact_id
    ]


async def test_map_runs_each_item_on_its_converted_value(harness: Harness) -> None:
    sequence = await harness.write_sequence(INTEGER_VALUE.key, [2, 3])
    graph = _expand(
        _node("echo", "test.echo_text", config={"prefix": "n "}),
        origins=(
            _origin(
                "echo",
                "text",
                sequence,
                collection_mode="map",
                conversions=[(INTEGER_TO_TEXT.id, INTEGER_TO_TEXT.version)],
            ),
        ),
    )

    outputs = await harness.compute_node(graph, "echo")

    mapped = outputs["text"]
    assert isinstance(mapped, ArtifactRefSequence)
    items = [await harness.text_of(ref) for ref in mapped.item_refs]
    assert items == ["n 2", "n 3"]
    text_ids = {artifact.id for artifact in await harness.artifacts_of(TEXT_VALUE.key)}
    assert text_ids == {ref.artifact_id for ref in mapped.item_refs}


async def test_a_graph_boundary_conversion_still_writes(harness: Harness) -> None:
    number_ref = await harness.write(INTEGER_VALUE.key, 8)
    graph = _expand(
        _node("number", "value.integer", config={"value": 8}),
        _node(
            "out",
            "graph.output",
            config={"public_name": "result"},
            bindings=[("T", TEXT_VALUE.key)],
        ),
        edges=(
            _edge(
                "number",
                "value",
                "out",
                "value",
                conversions=[(INTEGER_TO_TEXT.id, INTEGER_TO_TEXT.version)],
            ),
        ),
    )
    await harness.store_result("number", {"value": number_ref})

    outputs = await harness.compute_node(graph, "out", {"number": "number"})

    written = outputs["value"]
    assert isinstance(written, ArtifactRef)
    assert written.key() == TEXT_VALUE.key
    assert await harness.text_of(written) == "8"
    assert written.artifact_id != number_ref.artifact_id


async def test_each_node_reads_its_own_key_off_its_own_context(
    harness: Harness,
) -> None:
    """Two runs of one operator, each with its own credential.

    The runner binds secrets to the node it is about to compute, so the operator
    never says whose key it wants: it names one. The second node's document does not
    even carry the base URL its key belongs to, and still gets its own rather than
    the first node's.
    """

    harness.secrets.keys.update({"first": "key-of-first", "second": "key-of-second"})
    graph = _expand(
        _node("first", "test.read_secret", config={"base_url": "https://one.test"}),
        _node("second", "test.read_secret"),
    )

    first_outputs = await harness.compute_node(graph, "first")
    second_outputs = await harness.compute_node(graph, "second")

    assert SECRET_RUNS == [("first", "key-of-first"), ("second", "key-of-second")]
    assert [
        (lookup["node_id"], lookup["dependencies"])
        for lookup in harness.secrets.lookups
    ] == [
        ("first", {"base_url": "https://one.test"}),
        # The document omits base_url, so the node's own contract says what its
        # key was stored against.
        ("second", {"base_url": "https://api.example.test"}),
    ]
    first_ref = first_outputs["text"]
    second_ref = second_outputs["text"]
    assert isinstance(first_ref, ArtifactRef)
    assert isinstance(second_ref, ArtifactRef)
    assert await harness.text_of(first_ref) == "key-of-first"
    assert await harness.text_of(second_ref) == "key-of-second"


async def test_a_node_whose_key_was_never_set_fails_as_a_user_error(
    harness: Harness,
) -> None:
    """A missing credential is the graph's own state, said in user terms."""

    graph = _expand(_node("first", "test.read_secret"))

    with pytest.raises(NodeRunError, match="could not resolve its API key"):
        await harness.compute_node(graph, "first")

    assert harness.secrets.lookups[0]["node_id"] == "first"
