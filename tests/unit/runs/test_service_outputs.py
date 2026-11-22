"""Service outputs: the consumer builds the provider in-process with its secrets."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, final, override
from uuid import UUID

import pytest
from grafy_api.runs.errors import NodeComputationError
from grafy_api.runs.node_runner import NodeComputationRunnerFactory
from grafy_core.artifact_contracts import TEXT_VALUE
from grafy_core.artifacts import NodeConfig, NodeInput, NodeOutput
from grafy_core.domain.artifact_outputs import ArtifactOutputValue
from grafy_core.domain.graph_documents import (
    GraphDocument,
    GraphEdge,
    GraphNode,
    GraphPoint,
)
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.domain.plugin_capabilities import PluginRuntimeCapability
from grafy_core.kernel.expansion import expand_graph
from grafy_core.kernel.instances import ExpandedGraph
from grafy_core.kernel.memory_results import InMemoryResultStore
from grafy_core.kernel.project import GraphDefinition, ProjectDocument
from grafy_core.kernel.scheduler import ComputationRequest
from grafy_core.nodes import (
    Node,
    NodeExecutionContext,
    service_contract,
)
from grafy_core.plugins import (
    NodeSecretInput,
    Plugin,
    PluginRegistry,
    PluginRuntimeContext,
)
from grafy_core.ports.node_secrets import NodeSecretUnavailableError
from grafy_core.runtime.artifact_values import ArtifactValues
from grafy_core.runtime.execution import NodeRuntime
from grafy_core.runtime.in_memory import InMemoryUnitOfWork
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import OutputPersister
from grafy_core.service_contracts import implements_service_contract
from grafy_storage import LocalFileObjectStore
from grafy_workbench.text import TEXT
from pydantic import Field, SecretStr, StrictStr

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000951")
PROJECT_ID = UUID("00000000-0000-0000-0000-000000000952")
PROJECT_KEY = str(PROJECT_ID)
GRAPH_ID = "main"

PROVIDER_BUILDS: list[tuple[str | None, str]] = []
API_KEY = NodeSecretInput(
    name="api_key",
    title="API key",
    config_dependencies=("label",),
)

SERVICES = Plugin(slug="test.services", title="Service fixtures")
SERVICES.register_artifact_type_dependency(TEXT_VALUE)


@service_contract("test.reader", version=1, title="Test reader")
class FakeReader(Protocol):
    async def read(self) -> str: ...


SERVICES.register_service_contract(FakeReader)


class AlphaReader(FakeReader):
    def __init__(self, *, label: str, api_key: SecretStr) -> None:
        self.label = label
        self.api_key = api_key

    async def read(self) -> str:
        return f"{self.label}:{self.api_key.get_secret_value()}"


class BetaReader(FakeReader):
    def __init__(self, *, label: str, api_key: SecretStr) -> None:
        self.label = label
        self.api_key = api_key

    async def read(self) -> str:
        return f"beta:{self.label}:{self.api_key.get_secret_value()}"


class ProviderConfig(NodeConfig):
    label: StrictStr = Field(default="shared")


class EmptyInput(NodeInput):
    pass


class AlphaOutput(NodeOutput):
    reader: AlphaReader


class BetaOutput(NodeOutput):
    reader: BetaReader


@SERVICES.node(
    operator_id="test.alpha_provider",
    version=1,
    title="Alpha provider",
    secret_inputs=(API_KEY,),
    required_capabilities=(PluginRuntimeCapability.NODE_SECRETS,),
)
@final
class AlphaProvider(Node[ProviderConfig, EmptyInput, AlphaOutput]):
    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: ProviderConfig,
        _inputs: EmptyInput,
        /,
    ) -> AlphaOutput:
        api_key = await context.secrets.require(API_KEY.name)
        PROVIDER_BUILDS.append((context.node_id, api_key.get_secret_value()))
        return AlphaOutput(
            reader=AlphaReader(label=config.label, api_key=api_key)
        )


@SERVICES.node(
    operator_id="test.beta_provider",
    version=1,
    title="Beta provider",
    secret_inputs=(API_KEY,),
    required_capabilities=(PluginRuntimeCapability.NODE_SECRETS,),
)
@final
class BetaProvider(Node[ProviderConfig, EmptyInput, BetaOutput]):
    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: ProviderConfig,
        _inputs: EmptyInput,
        /,
    ) -> BetaOutput:
        api_key = await context.secrets.require(API_KEY.name)
        PROVIDER_BUILDS.append((context.node_id, api_key.get_secret_value()))
        return BetaOutput(reader=BetaReader(label=config.label, api_key=api_key))


class ConsumerConfig(NodeConfig):
    pass


class ConsumerInput(NodeInput):
    reader: FakeReader


class ConsumerOutput(NodeOutput):
    text: str


@SERVICES.node(operator_id="test.reader_consumer", version=1, title="Reader consumer")
@final
class ReaderConsumer(Node[ConsumerConfig, ConsumerInput, ConsumerOutput]):
    @override
    async def run(
        self,
        _context: NodeExecutionContext,
        _config: ConsumerConfig,
        inputs: ConsumerInput,
        /,
    ) -> ConsumerOutput:
        assert implements_service_contract(inputs.reader, FakeReader)
        return ConsumerOutput(text=await inputs.reader.read())


class RecordingNodeSecrets:
    def __init__(self, keys: Mapping[str, str] | None = None) -> None:
        self.keys: dict[str, str] = dict(keys or {})

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
        del workspace_id, project_id, graph_id, name, dependencies
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


def _node(
    node_id: str,
    operator_id: str,
    *,
    config: Mapping[str, object] | None = None,
) -> GraphNode:
    return GraphNode(
        kind="builtin",
        id=node_id,
        operator_id=operator_id,
        operator_version=1,
        config=dict(config or {}),
        position=GraphPoint(x=0, y=0),
    )


def _edge(
    from_node: str,
    from_port: str,
    to_node: str,
    to_port: str,
) -> GraphEdge:
    return GraphEdge(
        id=f"{from_node}-{to_node}",
        from_node=from_node,
        from_port=from_port,
        to_node=to_node,
        to_port=to_port,
    )


def _expand(
    *nodes: GraphNode,
    edges: Sequence[GraphEdge] = (),
) -> ExpandedGraph:
    document = GraphDocument(nodes=tuple(nodes), edges=tuple(edges), origins=())
    project = ProjectDocument(
        graphs=(GraphDefinition(id=GRAPH_ID, name="Main", document=document),),
    )
    return expand_graph(project, GRAPH_ID, project_id=PROJECT_KEY)


@pytest.fixture(autouse=True)
def _clear_builds() -> None:
    PROVIDER_BUILDS.clear()


@pytest.fixture
def harness(tmp_path: Path) -> tuple[
    ExpandedGraph,
    object,
    RecordingNodeSecrets,
    InMemoryUnitOfWork,
]:
    uow = InMemoryUnitOfWork()
    storage = LocalFileObjectStore(tmp_path / "objects")
    registry = PluginRegistry()
    registry.install(TEXT)
    registry.install(SERVICES)
    registry.freeze()
    secrets = RecordingNodeSecrets()
    values = ArtifactValues(
        registry.artifacts,
        uow=uow,
        storage=storage,
        bucket="artifacts",
        storage_backend="local",
    )
    runtime = NodeRuntime(
        materializer=InputMaterializer(values),
        persister=OutputPersister(values),
    )
    factory = NodeComputationRunnerFactory(
        registry=registry,
        runtime=runtime,
        node_secrets=secrets,
        values=values,
        plugin_context=PluginRuntimeContext(
            workspace=tmp_path,
            storage=storage,
            uow=uow,
            bucket="artifacts",
            values=values,
        ),
        max_map_concurrency=2,
    )
    store = InMemoryResultStore()
    runner = factory.for_project(
        workspace_id=WORKSPACE_ID,
        project_id=PROJECT_ID,
        store=store,
    )
    return runner, secrets, uow, values


async def _compute_consumer(
    runner: object,
    graph: ExpandedGraph,
    consumer_id: str,
    provider_id: str,
) -> Mapping[str, ArtifactOutputValue]:
    keys = {key.node_id: key for key in graph.instances}
    consumer = graph.instances[keys[consumer_id]]
    provider = graph.instances[keys[provider_id]]
    return await runner(  # type: ignore[operator]
        ComputationRequest(
            fingerprint=f"fingerprint-{consumer_id}",
            instance=consumer,
            upstream_fingerprints={keys[provider_id]: f"fp-{provider_id}"},
            service_sources={keys[provider_id]: provider},
        )
    )


async def test_two_providers_each_supply_their_own_secret(
    harness: tuple[object, RecordingNodeSecrets, InMemoryUnitOfWork, ArtifactValues],
) -> None:
    runner, secrets, uow, values = harness
    secrets.keys["alpha"] = "key-alpha"
    secrets.keys["beta"] = "key-beta"
    graph = _expand(
        _node("alpha", "test.alpha_provider", config={"label": "shared"}),
        _node("beta", "test.beta_provider", config={"label": "shared"}),
        _node("left", "test.reader_consumer"),
        _node("right", "test.reader_consumer"),
        edges=(
            _edge("alpha", "reader", "left", "reader"),
            _edge("beta", "reader", "right", "reader"),
        ),
    )

    left = await _compute_consumer(runner, graph, "left", "alpha")
    right = await _compute_consumer(runner, graph, "right", "beta")

    assert await _text(uow, values, left["text"]) == "shared:key-alpha"
    assert await _text(uow, values, right["text"]) == "beta:shared:key-beta"
    assert PROVIDER_BUILDS == [("alpha", "key-alpha"), ("beta", "key-beta")]


async def test_consumer_metadata_records_the_provider_without_the_secret(
    harness: tuple[object, RecordingNodeSecrets, InMemoryUnitOfWork, ArtifactValues],
) -> None:
    runner, secrets, uow, _values = harness
    secrets.keys["alpha"] = "secret-value"
    graph = _expand(
        _node("alpha", "test.alpha_provider", config={"label": "lab"}),
        _node("left", "test.reader_consumer"),
        edges=(_edge("alpha", "reader", "left", "reader"),),
    )

    outputs = await _compute_consumer(runner, graph, "left", "alpha")
    ref = outputs["text"]
    async with uow as unit:
        artifact = await unit.artifacts.get(WORKSPACE_ID, ref.artifact_id)  # type: ignore[union-attr]
    assert artifact is not None
    providers = artifact.metadata.get("service_providers")
    assert providers == [
        {
            "input": "reader",
            "operator_id": "test.alpha_provider",
            "operator_version": 1,
            "config": {"label": "lab"},
        }
    ]
    dumped = str(artifact.metadata)
    assert "secret-value" not in dumped


async def test_an_unfed_service_plug_is_refused(
    harness: tuple[object, RecordingNodeSecrets, InMemoryUnitOfWork, ArtifactValues],
) -> None:
    runner, _secrets, _uow, _values = harness
    graph = _expand(_node("left", "test.reader_consumer"))
    keys = {key.node_id: key for key in graph.instances}
    with pytest.raises(NodeComputationError, match="no incoming connection"):
        await runner(  # type: ignore[operator]
            ComputationRequest(
                fingerprint="fingerprint-left",
                instance=graph.instances[keys["left"]],
                upstream_fingerprints={},
                service_sources={},
            )
        )


async def _text(
    uow: InMemoryUnitOfWork,
    values: ArtifactValues,
    ref: object,
) -> str:
    del values
    from grafy_core.artifacts import ArtifactRef

    assert isinstance(ref, ArtifactRef)
    async with uow as unit:
        artifact = await unit.artifacts.get(WORKSPACE_ID, ref.artifact_id)
    assert artifact is not None
    payload = artifact.inline_payload
    assert isinstance(payload, dict)
    value = payload["value"]
    assert isinstance(value, str)
    return value
