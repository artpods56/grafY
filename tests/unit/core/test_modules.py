from collections.abc import Mapping
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactTypeKey,
)
from grafy_core.domain.modules import (
    GraphModuleDefinition,
    GraphModuleDefinitionError,
    GraphModuleReference,
    GraphModuleReferenceError,
    ModuleBoundaryConfig,
    ModuleInputConfig,
)
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraph,
    SavedGraphArtifactTypeBinding,
    SavedGraphDocument,
    SavedGraphEdge,
    SavedGraphNode,
)
from grafy_core.nodes import ArtifactTypeVariable, NodeExecutionContext, PortShape
from grafy_core.operators.modules import (
    MODULE_BOUNDARY_REGISTRATIONS,
    GraphModuleExecutionError,
    GraphModuleNode,
    ModuleBoundaryExecutionError,
    ModuleInputNode,
    ModuleOutputNode,
)
from grafy_core.plugins import PluginRegistry
from grafy_core.ports.modules import (
    GraphModuleExecutionResult,
    GraphModuleExecutorPort,
)
from grafy_core.runtime.execution import NodeRunError, NodeRuntime
from grafy_core.runtime.materialization import InputMaterializer
from grafy_core.runtime.persistence import (
    ArtifactWriterRegistry,
    OutputPersister,
    PersistedNodeOutput,
)
from grafy_core.runtime.plugin_protocol import PluginFailureCode
from grafy_core.runtime.resolvers import ResolverRegistry


VALUE_TYPE = ArtifactTypeKey("example.value", 1)
OTHER_TYPE = ArtifactTypeKey("example.other", 1)
GRAPH_ID = UUID("00000000-0000-0000-0000-000000000123")
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")


def _binding(
    artifact_type: ArtifactTypeKey = VALUE_TYPE,
    *,
    variable: str = "T",
) -> SavedGraphArtifactTypeBinding:
    return SavedGraphArtifactTypeBinding(
        variable=variable,
        artifact_type=artifact_type,
    )


def _boundary(
    node_id: str,
    operator_id: str,
    public_name: str,
    *,
    description: str | None = None,
    required: bool | None = None,
    version: int = 1,
    bindings: tuple[SavedGraphArtifactTypeBinding, ...] | None = None,
) -> SavedGraphNode:
    config: dict[str, object] = {"public_name": public_name}
    if description is not None:
        config["description"] = description
    if required is not None:
        config["required"] = required
    return SavedGraphNode(
        kind="builtin",
        id=node_id,
        operator_id=operator_id,
        operator_version=version,
        config=config,
        position=GraphPoint(x=0, y=0),
        artifact_type_bindings=(_binding(),) if bindings is None else bindings,
    )


def _edge(
    edge_id: str,
    from_node: str,
    to_node: str,
    *,
    collection_mode: str = "direct",
    enabled: bool = True,
) -> SavedGraphEdge:
    return SavedGraphEdge.model_validate(
        {
            "id": edge_id,
            "from_node": from_node,
            "from_port": "value",
            "to_node": to_node,
            "to_port": "value",
            "collection_mode": collection_mode,
            "enabled": enabled,
        }
    )


def _document(
    *,
    input_name: str = "source",
    output_name: str = "result",
) -> SavedGraphDocument:
    return SavedGraphDocument(
        nodes=(
            _boundary("input", "module.input", input_name),
            _boundary("output", "module.output", output_name),
        ),
        edges=(_edge("pass-through", "input", "output"),),
    )


def _definition() -> GraphModuleDefinition:
    return GraphModuleDefinition.from_saved_graph(
        SavedGraph(
            workspace_id=WORKSPACE_ID,
            id=GRAPH_ID,
            revision=3,
            name="Example module",
            document=_document(),
        )
    )


def _optional_definition() -> GraphModuleDefinition:
    return GraphModuleDefinition.from_saved_graph(
        SavedGraph(
            workspace_id=WORKSPACE_ID,
            id=GRAPH_ID,
            revision=4,
            name="Optional input module",
            document=SavedGraphDocument(
                nodes=(
                    _boundary(
                        "required-input",
                        "module.input",
                        "required_source",
                    ),
                    _boundary(
                        "optional-input",
                        "module.input",
                        "optional_context",
                        required=False,
                    ),
                    SavedGraphNode(
                        kind="builtin",
                        id="optional-consumer",
                        operator_id="example.optional-consumer",
                        operator_version=1,
                        config={},
                        position=GraphPoint(x=100, y=0),
                    ),
                    _boundary("output", "module.output", "result"),
                ),
                edges=(
                    _edge("required", "required-input", "output"),
                    _edge("optional", "optional-input", "optional-consumer"),
                ),
            ),
        )
    )


def _runtime() -> NodeRuntime:
    return NodeRuntime(
        materializer=InputMaterializer(ResolverRegistry()),
        persister=OutputPersister(ArtifactWriterRegistry()),
    )


class EchoModuleExecutor(GraphModuleExecutorPort):
    def __init__(self) -> None:
        self.calls: list[
            tuple[
                GraphModuleDefinition, NodeExecutionContext, Mapping[str, ArtifactRef]
            ]
        ] = []

    async def execute_module(
        self,
        definition: GraphModuleDefinition,
        context: NodeExecutionContext,
        inputs: Mapping[str, ArtifactRef],
        /,
    ) -> GraphModuleExecutionResult:
        self.calls.append((definition, context, dict(inputs)))
        return GraphModuleExecutionResult(outputs={"result": inputs["source"]})


class FailingModuleExecutor(GraphModuleExecutorPort):
    async def execute_module(
        self,
        _definition: GraphModuleDefinition,
        _context: NodeExecutionContext,
        _inputs: Mapping[str, ArtifactRef],
        /,
    ) -> GraphModuleExecutionResult:
        raise RuntimeError("inner graph failed")


class OptionalModuleExecutor(GraphModuleExecutorPort):
    def __init__(self) -> None:
        self.calls: list[Mapping[str, ArtifactRef]] = []

    async def execute_module(
        self,
        _definition: GraphModuleDefinition,
        _context: NodeExecutionContext,
        inputs: Mapping[str, ArtifactRef],
        /,
    ) -> GraphModuleExecutionResult:
        self.calls.append(dict(inputs))
        return GraphModuleExecutionResult(outputs={"result": inputs["required_source"]})


def test_module_boundary_nodes_are_generic_scalar_contracts() -> None:
    module_input = ModuleInputNode.output_contract.ports["value"]
    module_output_input = ModuleOutputNode.input_contract.ports["value"]
    module_output = ModuleOutputNode.output_contract.ports["value"]

    assert ModuleInputNode.input_contract.ports == {}
    assert isinstance(module_input.produces, ArtifactTypeVariable)
    assert module_input.produces.name == "T"
    assert module_input.shape is PortShape.ONE
    assert module_output_input.accepts is module_input.produces
    assert module_output_input.shape is PortShape.ONE
    assert module_output.produces is module_input.produces
    assert module_output.shape is PortShape.ONE


def test_module_input_has_required_config_without_changing_module_output() -> None:
    input_config = ModuleInputConfig.model_validate({"public_name": "source"})
    output_config = ModuleBoundaryConfig.model_validate({"public_name": "result"})

    assert ModuleInputNode.config_contract.model is ModuleInputConfig
    assert input_config.required is True
    assert ModuleOutputNode.config_contract.model is ModuleBoundaryConfig
    assert output_config.model_dump() == {
        "public_name": "result",
        "description": None,
    }
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ModuleBoundaryConfig.model_validate(
            {"public_name": "result", "required": False}
        )


def test_module_boundaries_register_without_a_plugin_family() -> None:
    registry = PluginRegistry()
    registry.register_module_boundaries(MODULE_BOUNDARY_REGISTRATIONS)
    registry.freeze()

    assert registry.plugins == ()
    assert [registration.key for registration in registry.nodes] == [
        ("module.input", 1),
        ("module.output", 1),
    ]
    assert {registration.plugin_slug for registration in registry.nodes} == {
        "graph.module"
    }
    assert [registration.listed for registration in registry.nodes] == [
        False,
        False,
    ]


@pytest.mark.parametrize(
    "public_name",
    ["", "Source", "two words", "has-dash", "model_dump"],
)
def test_module_boundary_config_requires_canonical_public_names(
    public_name: str,
) -> None:
    with pytest.raises(ValidationError, match="Module public name"):
        ModuleBoundaryConfig(public_name=public_name)


def test_graph_module_reference_round_trips_one_virtual_operator_identity() -> None:
    reference = GraphModuleReference(graph_id=GRAPH_ID, revision=7)

    assert reference.operator_id == f"graph.module.{GRAPH_ID}"
    assert reference.operator_version == 7
    assert reference.operator_key == (f"graph.module.{GRAPH_ID}", 7)
    assert reference.module_path_item == f"graph.module.{GRAPH_ID}@7"
    assert (
        GraphModuleReference.from_operator_identity(
            reference.operator_id,
            reference.operator_version,
        )
        == reference
    )
    assert GraphModuleReference.try_from_operator_identity("text.input", 1) is None


@pytest.mark.parametrize(
    ("operator_id", "version", "message"),
    [
        ("graph.module.not-a-uuid", 1, "invalid saved graph UUID"),
        (
            "graph.module.AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA",
            1,
            "canonical lowercase",
        ),
        (f"graph.module.{GRAPH_ID}", 0, "invalid revision"),
    ],
)
def test_graph_module_reference_rejects_ambiguous_virtual_identities(
    operator_id: str,
    version: int,
    message: str,
) -> None:
    with pytest.raises(GraphModuleReferenceError, match=message):
        GraphModuleReference.from_operator_identity(operator_id, version)


def test_graph_module_definition_derives_ordered_typed_public_ports() -> None:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        id=GRAPH_ID,
        revision=3,
        name="  Example module  ",
        document=SavedGraphDocument(
            nodes=(
                _boundary(
                    "first-input",
                    "module.input",
                    "primary",
                    description="Primary value",
                ),
                _boundary("first-output", "module.output", "primary_result"),
                _boundary("second-input", "module.input", "secondary"),
                _boundary("second-output", "module.output", "secondary_result"),
            ),
            edges=(
                _edge("first", "first-input", "first-output"),
                _edge("second", "second-input", "second-output"),
            ),
        ),
    )

    definition = GraphModuleDefinition.from_saved_graph(graph)
    snapshot_definition = GraphModuleDefinition.from_saved_graph_revision(
        graph.snapshot()
    )

    assert definition.reference == GraphModuleReference(GRAPH_ID, 3)
    assert definition.name == "Example module"
    assert definition.document is graph.document
    assert [port.name for port in definition.input_ports] == ["primary", "secondary"]
    assert [port.name for port in definition.output_ports] == [
        "primary_result",
        "secondary_result",
    ]
    assert definition.input_port("primary").artifact_type == VALUE_TYPE
    assert definition.input_port("primary").description == "Primary value"
    assert definition.input_port("primary").required is True
    assert definition.output_port("secondary_result").boundary_node_id == (
        "second-output"
    )
    assert snapshot_definition == definition


def test_graph_module_definition_requires_unique_public_names_per_direction() -> None:
    document = SavedGraphDocument(
        nodes=(
            _boundary("input-a", "module.input", "duplicate"),
            _boundary("output-a", "module.output", "result_a"),
            _boundary("input-b", "module.input", "duplicate"),
            _boundary("output-b", "module.output", "result_b"),
        ),
        edges=(
            _edge("a", "input-a", "output-a"),
            _edge("b", "input-b", "output-b"),
        ),
    )

    with pytest.raises(
        GraphModuleDefinitionError,
        match="duplicate public input name 'duplicate'",
    ):
        GraphModuleDefinition(
            reference=GraphModuleReference(GRAPH_ID, 1),
            name="Duplicates",
            document=document,
        )


def test_graph_module_definition_requires_unique_public_output_names() -> None:
    document = SavedGraphDocument(
        nodes=(
            _boundary("input-a", "module.input", "source_a"),
            _boundary("output-a", "module.output", "duplicate"),
            _boundary("input-b", "module.input", "source_b"),
            _boundary("output-b", "module.output", "duplicate"),
        ),
        edges=(
            _edge("a", "input-a", "output-a"),
            _edge("b", "input-b", "output-b"),
        ),
    )

    with pytest.raises(
        GraphModuleDefinitionError,
        match="duplicate public output name 'duplicate'",
    ):
        GraphModuleDefinition(
            reference=GraphModuleReference(GRAPH_ID, 1),
            name="Duplicates",
            document=document,
        )


def test_graph_module_definition_rejects_unknown_boundary_versions() -> None:
    document = SavedGraphDocument(
        nodes=(
            _boundary("input", "module.input", "source", version=2),
            _boundary("output", "module.output", "result"),
        ),
        edges=(_edge("edge", "input", "output"),),
    )

    with pytest.raises(
        GraphModuleDefinitionError,
        match="module.input@2.*version must be 1",
    ):
        GraphModuleDefinition(
            reference=GraphModuleReference(GRAPH_ID, 1),
            name="Future boundary",
            document=document,
        )


@pytest.mark.parametrize(
    ("bindings", "message"),
    [
        ((), "missing concrete artifact type binding 'T'"),
        (
            (_binding(), _binding(OTHER_TYPE, variable="Other")),
            "unknown artifact type bindings: Other",
        ),
    ],
)
def test_graph_module_definition_requires_one_concrete_boundary_binding(
    bindings: tuple[SavedGraphArtifactTypeBinding, ...],
    message: str,
) -> None:
    document = SavedGraphDocument(
        nodes=(
            _boundary("input", "module.input", "source", bindings=bindings),
            _boundary("output", "module.output", "result"),
        ),
        edges=(_edge("edge", "input", "output"),),
    )

    with pytest.raises(GraphModuleDefinitionError, match=message) as raised:
        GraphModuleDefinition(
            reference=GraphModuleReference(GRAPH_ID, 4),
            name="Invalid binding",
            document=document,
        )

    assert "revision 4" in str(raised.value)
    assert "boundary node 'input'" in str(raised.value)


def test_graph_module_definition_requires_connected_boundaries() -> None:
    document = SavedGraphDocument(
        nodes=(
            _boundary("unused", "module.input", "unused"),
            _boundary("input", "module.input", "source"),
            _boundary("output", "module.output", "result"),
        ),
        edges=(_edge("edge", "input", "output"),),
    )

    with pytest.raises(
        GraphModuleDefinitionError,
        match="boundary node 'unused'.*must connect its 'value' output",
    ):
        GraphModuleDefinition(
            reference=GraphModuleReference(GRAPH_ID, 1),
            name="Unconnected",
            document=document,
        )


def test_graph_module_definition_does_not_treat_disabled_edges_as_connections() -> None:
    document = SavedGraphDocument(
        nodes=(
            _boundary("input", "module.input", "source"),
            _boundary("output", "module.output", "result"),
        ),
        edges=(_edge("disabled", "input", "output", enabled=False),),
    )

    with pytest.raises(
        GraphModuleDefinitionError,
        match="boundary node 'input'.*must connect its 'value' output",
    ):
        GraphModuleDefinition(
            reference=GraphModuleReference(GRAPH_ID, 1),
            name="Disabled pass-through",
            document=document,
        )


def test_graph_module_definition_requires_scalar_direct_outputs() -> None:
    document = SavedGraphDocument(
        nodes=(
            _boundary("input", "module.input", "source"),
            _boundary("output", "module.output", "result"),
        ),
        edges=(_edge("mapped", "input", "output", collection_mode="map"),),
    )

    with pytest.raises(
        GraphModuleDefinitionError,
        match="module ports are scalar",
    ):
        GraphModuleDefinition(
            reference=GraphModuleReference(GRAPH_ID, 1),
            name="Mapped output",
            document=document,
        )


def test_graph_module_definition_requires_at_least_one_output_boundary() -> None:
    with pytest.raises(
        GraphModuleDefinitionError,
        match="at least one Module Output boundary",
    ):
        GraphModuleDefinition(
            reference=GraphModuleReference(GRAPH_ID, 1),
            name="Not a module",
            document=SavedGraphDocument(),
        )


@pytest.mark.asyncio
async def test_module_input_cannot_execute_outside_a_graph_module() -> None:
    with pytest.raises(
        ModuleBoundaryExecutionError,
        match="public input 'source'.*inside a graph module",
    ):
        await ModuleInputNode().run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="module-input"),
            ModuleInputConfig(public_name="source"),
            ModuleInputNode.input_contract.model(),
        )


@pytest.mark.asyncio
async def test_module_output_preserves_the_boundary_artifact_ref() -> None:
    ref = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE_TYPE)

    output = await ModuleOutputNode().run(
        NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="module-output"),
        ModuleBoundaryConfig(public_name="result"),
        ModuleOutputNode.input_contract.model(value=ref),
    )

    assert output.value == ref


def test_dynamic_graph_module_node_exposes_concrete_scalar_contracts() -> None:
    definition = _definition()
    node = GraphModuleNode(definition, EchoModuleExecutor())

    source = node.input_contract.ports["source"]
    result = node.output_contract.ports["result"]
    assert node.operator_id == f"graph.module.{GRAPH_ID}"
    assert node.operator_version == 3
    assert node.title == "Example module"
    assert source.accepts == VALUE_TYPE
    assert source.shape is PortShape.ONE
    assert source.preserves_ref_container is True
    assert result.produces == VALUE_TYPE
    assert result.shape is PortShape.ONE


def test_dynamic_graph_module_node_exposes_optional_inputs_as_nullable_defaults() -> (
    None
):
    node = GraphModuleNode(_optional_definition(), OptionalModuleExecutor())

    required_source = node.input_contract.ports["required_source"]
    optional_context = node.input_contract.ports["optional_context"]
    assert required_source.required is True
    assert required_source.allows_none is False
    assert optional_context.required is False
    assert optional_context.allows_none is True
    assert node.definition.input_port("optional_context").required is False


@pytest.mark.asyncio
async def test_graph_module_node_delegates_and_preserves_refs_through_runtime() -> None:
    executor = EchoModuleExecutor()
    definition = _definition()
    node = GraphModuleNode(definition, executor)
    source = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE_TYPE)
    context = NodeExecutionContext(
        workspace_id=WORKSPACE_ID,
        node_id="module-instance",
        module_path=("parent-module",),
    )

    result = await _runtime().run_node(
        node,
        context,
        {"source": source},
    )

    assert isinstance(result, PersistedNodeOutput)
    assert result["result"] == source
    assert len(executor.calls) == 1
    called_definition, called_context, called_inputs = executor.calls[0]
    assert called_definition is definition
    assert called_context == context
    assert called_inputs == {"source": source}


@pytest.mark.asyncio
async def test_graph_module_node_omits_absent_optional_inputs_from_execution() -> None:
    executor = OptionalModuleExecutor()
    node = GraphModuleNode(_optional_definition(), executor)
    source = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE_TYPE)

    result = await _runtime().run_node(
        node,
        NodeExecutionContext(
            workspace_id=WORKSPACE_ID, node_id="optional-module-instance"
        ),
        {"required_source": source},
    )

    assert isinstance(result, PersistedNodeOutput)
    assert result["result"] == source
    assert executor.calls == [{"required_source": source}]


@pytest.mark.asyncio
async def test_graph_module_node_rejects_absent_required_input_with_context() -> None:
    node = GraphModuleNode(_optional_definition(), OptionalModuleExecutor())
    input_model = node.input_contract.model
    inputs = input_model.model_construct(required_source=None)

    with pytest.raises(
        GraphModuleExecutionError,
        match="graph.module.*required input 'required_source' was absent",
    ):
        await node.run(
            NodeExecutionContext(
                workspace_id=WORKSPACE_ID, node_id="optional-module-instance"
            ),
            node.config_contract.model(),
            inputs,
        )


@pytest.mark.asyncio
async def test_graph_module_node_preserves_inner_failure_as_contextual_cause() -> None:
    node = GraphModuleNode(_definition(), FailingModuleExecutor())
    source = ArtifactRef.from_key(artifact_id=uuid4(), key=VALUE_TYPE)

    with pytest.raises(
        NodeRunError,
        match=(
            f"Node 'module-instance' operator graph\\.module\\.{GRAPH_ID}@3 failed "
            "\\(operator_failure\\): Graph module 'Example module'"
        ),
    ) as raised:
        await _runtime().run_node(
            node,
            NodeExecutionContext(workspace_id=WORKSPACE_ID, node_id="module-instance"),
            {"source": source},
        )

    assert raised.value.failure_code is PluginFailureCode.OPERATOR_FAILURE
    assert "inner graph failed" not in str(raised.value)
    module_error = raised.value.__cause__
    assert isinstance(module_error, GraphModuleExecutionError)
    assert "failed while executing parent node 'module-instance'" in str(module_error)
    assert isinstance(module_error.__cause__, RuntimeError)
    assert str(module_error.__cause__) == "inner graph failed"
