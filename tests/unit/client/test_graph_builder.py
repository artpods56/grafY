from typing import Annotated, ClassVar, override

import pytest
from grafy_client import (
    CatalogConversion,
    CatalogConversionKey,
    CatalogNode,
    CatalogPort,
    GraphBuilder,
    GraphBuilderError,
    NodeCatalog,
)
from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactRefSequence,
    ArtifactTypeKey,
    NoConfig,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.plugin_identity import PluginReleaseScope
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraphConversion,
    SavedGraphPluginReleasePin,
)
from grafy_core.nodes import (
    ArtifactTypeVariable,
    InPort,
    Node,
    NodeExecutionContext,
    OutPort,
    PortShape,
)

TEXT = ArtifactTypeKey("scalar.text", 1)
MARKDOWN = ArtifactTypeKey("text.markdown", 1)
T = ArtifactTypeVariable("T")


class TextConfig(NodeConfig):
    text: str


class EmptyInput(NodeInput):
    pass


class TextOutput(NodeOutput):
    text: Annotated[str, OutPort(TEXT)]


class TextNode(Node[TextConfig, EmptyInput, TextOutput]):
    operator_id: ClassVar[str] = "text.input"
    operator_version: ClassVar[int] = 1
    plugin_slug: ClassVar[str] = "text"
    title: ClassVar[str] = "Text"
    description: ClassVar[str] = "Produces text."

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: TextConfig,
        inputs: EmptyInput,
        /,
    ) -> TextOutput:
        del context, inputs
        return TextOutput(text=config.text)


class CollectInput(NodeInput):
    items: Annotated[
        list[ArtifactRef | ArtifactRefSequence],
        InPort(T, variadic=True, instance_plugs=True),
    ]


class CollectOutput(NodeOutput):
    items: Annotated[ArtifactRefSequence, OutPort(T)]


class CollectNode(Node[NoConfig, CollectInput, CollectOutput]):
    operator_id: ClassVar[str] = "sequence.collect"
    operator_version: ClassVar[int] = 1
    plugin_slug: ClassVar[str] = "sequence"
    title: ClassVar[str] = "Collect"
    description: ClassVar[str] = "Collects ordered artifacts."

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: NoConfig,
        inputs: CollectInput,
        /,
    ) -> CollectOutput:
        del context, config, inputs
        raise NotImplementedError


class MarkdownInput(NodeInput):
    markdown: Annotated[str, InPort(MARKDOWN)]


class EmptyOutput(NodeOutput):
    pass


class MarkdownNode(Node[NoConfig, MarkdownInput, EmptyOutput]):
    operator_id: ClassVar[str] = "markdown.consume"
    operator_version: ClassVar[int] = 1
    plugin_slug: ClassVar[str] = "test.markdown"
    title: ClassVar[str] = "Markdown consumer"
    description: ClassVar[str] = "Consumes Markdown."

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: NoConfig,
        inputs: MarkdownInput,
        /,
    ) -> EmptyOutput:
        del context, config, inputs
        return EmptyOutput()


class TransformInput(NodeInput):
    text: Annotated[str, InPort(TEXT)]


class TransformOutput(NodeOutput):
    text: Annotated[str, OutPort(TEXT)]


class TransformNode(Node[NoConfig, TransformInput, TransformOutput]):
    operator_id: ClassVar[str] = "text.transform"
    operator_version: ClassVar[int] = 1
    plugin_slug: ClassVar[str] = "text"
    title: ClassVar[str] = "Transform"
    description: ClassVar[str] = "Transforms text."

    @override
    async def run(
        self,
        context: NodeExecutionContext,
        config: NoConfig,
        inputs: TransformInput,
        /,
    ) -> TransformOutput:
        del context, config
        return TransformOutput(text=inputs.text)


def _catalog() -> NodeCatalog:
    return NodeCatalog(
        plugins=(),
        artifact_types=(),
        nodes=(
            CatalogNode(
                origin="builtin",
                operator_id="text.input",
                operator_version=1,
                plugin_slug="text",
                title="Text",
                description="Produces text.",
                config_schema=TextConfig.model_json_schema(),
                input_schema=EmptyInput.model_json_schema(),
                output_schema=TextOutput.model_json_schema(),
                inputs=(),
                outputs=(
                    CatalogPort(
                        name="text",
                        direction="output",
                        artifact_type=TEXT,
                        shape=PortShape.ONE,
                        accepted_shapes=(PortShape.ONE,),
                    ),
                ),
                runnable=True,
            ),
            CatalogNode(
                origin="builtin",
                operator_id="sequence.collect",
                operator_version=1,
                plugin_slug="sequence",
                title="Collect",
                description="Collects ordered artifacts.",
                config_schema=NoConfig.model_json_schema(),
                input_schema=CollectInput.model_json_schema(),
                output_schema=CollectOutput.model_json_schema(),
                inputs=(
                    CatalogPort(
                        name="items",
                        direction="input",
                        artifact_type_variable="T",
                        shape=PortShape.ONE,
                        accepted_shapes=(PortShape.ONE, PortShape.MANY),
                        variadic=True,
                        instance_plugs=True,
                    ),
                ),
                outputs=(
                    CatalogPort(
                        name="items",
                        direction="output",
                        artifact_type_variable="T",
                        shape=PortShape.MANY,
                        accepted_shapes=(PortShape.MANY,),
                    ),
                ),
                runnable=True,
            ),
            CatalogNode(
                origin="plugin",
                operator_id="markdown.consume",
                operator_version=1,
                plugin_slug="test.markdown",
                title="Markdown consumer",
                description="Consumes Markdown.",
                config_schema=NoConfig.model_json_schema(),
                input_schema=MarkdownInput.model_json_schema(),
                output_schema=EmptyOutput.model_json_schema(),
                inputs=(
                    CatalogPort(
                        name="markdown",
                        direction="input",
                        artifact_type=MARKDOWN,
                        shape=PortShape.ONE,
                        accepted_shapes=(PortShape.ONE,),
                    ),
                ),
                outputs=(),
                plugin_release=SavedGraphPluginReleasePin(
                    scope=PluginReleaseScope.WORKSPACE,
                    slug="test.markdown",
                    revision=7,
                ),
                runnable=True,
            ),
            CatalogNode(
                origin="builtin",
                operator_id="text.transform",
                operator_version=1,
                plugin_slug="text",
                title="Transform",
                description="Transforms text.",
                config_schema=NoConfig.model_json_schema(),
                input_schema=TransformInput.model_json_schema(),
                output_schema=TransformOutput.model_json_schema(),
                inputs=(
                    CatalogPort(
                        name="text",
                        direction="input",
                        artifact_type=TEXT,
                        shape=PortShape.ONE,
                        accepted_shapes=(PortShape.ONE,),
                    ),
                ),
                outputs=(
                    CatalogPort(
                        name="text",
                        direction="output",
                        artifact_type=TEXT,
                        shape=PortShape.ONE,
                        accepted_shapes=(PortShape.ONE,),
                    ),
                ),
                runnable=True,
            ),
        ),
        artifact_conversions=(
            CatalogConversion(
                key=CatalogConversionKey(id="text.to_markdown", version=1),
                source_artifact_type=TEXT,
                target_artifact_type=MARKDOWN,
                title="Text to Markdown",
            ),
        ),
    )


def test_builder_adds_typed_builtin_node_without_a_plugin_pin() -> None:
    graph = GraphBuilder(_catalog())

    text = graph.add(TextNode, TextConfig(text="hello"))

    document = graph.build()

    assert text.node_id == "node-0001-text-input"
    assert document.model_dump(mode="json") == {
        "schema_version": 7,
        "nodes": [
            {
                "kind": "builtin",
                "id": "node-0001-text-input",
                "operator_id": "text.input",
                "operator_version": 1,
                "config": {"text": "hello"},
                "position": {"x": 0.0, "y": 0.0},
                "layout": None,
                "input_plugs": [],
                "artifact_type_bindings": [],
                "plugin_release_pin": None,
            }
        ],
        "edges": [],
        "origins": [],
        "presentation": {
            "viewers": [],
            "links": [],
            "bindings": [],
            "annotations": [],
        },
    }


def test_builder_adds_catalog_node_without_a_local_node_class() -> None:
    graph = GraphBuilder(_catalog())

    text = graph.add_catalog_node(
        "text.input",
        {"text": "catalog authored"},
        position=GraphPoint(x=480, y=160),
    )

    document = graph.build()

    assert text.node_id == "node-0001-text-input"
    assert document.nodes[0].config_dict() == {"text": "catalog authored"}
    assert document.nodes[0].position == GraphPoint(x=480, y=160)


def test_builder_validates_catalog_node_configuration() -> None:
    graph = GraphBuilder(_catalog())

    with pytest.raises(
        GraphBuilderError,
        match="Invalid configuration for text.input@1",
    ):
        graph.add_catalog_node("text.input", {"text": 42})


def test_builder_pins_catalog_only_plugin_node_release() -> None:
    graph = GraphBuilder(_catalog())
    text = graph.add_catalog_node("text.input", {"text": "hello"})
    markdown = graph.add_catalog_node(
        "markdown.consume",
        {},
        plugin_slug="test.markdown",
    )

    graph.connect(
        text.output("text"),
        markdown.input("markdown"),
        conversion_path=(SavedGraphConversion(id="text.to_markdown", version=1),),
    )

    document = graph.build()
    assert document.nodes[1].plugin_release_pin == SavedGraphPluginReleasePin(
        scope=PluginReleaseScope.WORKSPACE,
        slug="test.markdown",
        revision=7,
    )


def test_builder_connects_ports_and_infers_variadic_artifact_binding() -> None:
    graph = GraphBuilder(_catalog())
    first = graph.add(TextNode, TextConfig(text="first"))
    second = graph.add(TextNode, TextConfig(text="second"))
    collect = graph.add(CollectNode, NoConfig())

    graph.connect(first.output("text"), collect.input("items"))
    graph.connect(second.output("text"), collect.input("items"))

    document = graph.build()
    collect_node = document.nodes[2]
    assert collect_node.artifact_type_binding_map() == {"T": TEXT}
    assert [(plug.id, plug.port) for plug in collect_node.input_plugs] == [
        ("plug-0001", "items"),
        ("plug-0002", "items"),
    ]
    assert [
        (
            edge.id,
            edge.from_node,
            edge.from_port,
            edge.to_node,
            edge.to_port,
            edge.to_plug,
        )
        for edge in document.edges
    ] == [
        (
            "edge-0001",
            first.node_id,
            "text",
            collect.node_id,
            "items",
            "plug-0001",
        ),
        (
            "edge-0002",
            second.node_id,
            "text",
            collect.node_id,
            "items",
            "plug-0002",
        ),
    ]


def test_builder_persists_only_an_explicit_catalog_conversion_path() -> None:
    graph = GraphBuilder(_catalog())
    text = graph.add(TextNode, TextConfig(text="hello"))
    markdown = graph.add(MarkdownNode, NoConfig())

    graph.connect(
        text.output("text"),
        markdown.input("markdown"),
        conversion_path=(SavedGraphConversion(id="text.to_markdown", version=1),),
    )

    document = graph.build()
    assert document.edges[0].conversion_path == (
        SavedGraphConversion(id="text.to_markdown", version=1),
    )


def test_builder_infers_variable_from_explicit_conversion_result() -> None:
    graph = GraphBuilder(_catalog())
    text = graph.add(TextNode, TextConfig(text="hello"))
    collect = graph.add(CollectNode, NoConfig())

    graph.connect(
        text.output("text"),
        collect.input("items"),
        conversion_path=(SavedGraphConversion(id="text.to_markdown", version=1),),
    )

    document = graph.build()
    assert document.nodes[1].artifact_type_binding_map() == {"T": MARKDOWN}
    assert document.edges[0].conversion_path == (
        SavedGraphConversion(id="text.to_markdown", version=1),
    )


def test_builder_rejected_connection_does_not_mutate_graph() -> None:
    graph = GraphBuilder(_catalog())
    text = graph.add(TextNode, TextConfig(text="hello"))
    collect = graph.add(CollectNode, NoConfig())

    with pytest.raises(GraphBuilderError, match="does.not.exist@1"):
        graph.connect(
            text.output("text"),
            collect.input("items"),
            conversion_path=(SavedGraphConversion(id="does.not.exist", version=1),),
        )

    graph.connect(
        text.output("text"),
        collect.input("items"),
        conversion_path=(SavedGraphConversion(id="text.to_markdown", version=1),),
    )
    document = graph.build()

    assert document.nodes[1].artifact_type_binding_map() == {"T": MARKDOWN}
    assert [plug.id for plug in document.nodes[1].input_plugs] == ["plug-0001"]
    assert [edge.id for edge in document.edges] == ["edge-0001"]


def test_builder_requires_an_explicit_binding_when_both_variables_are_unresolved() -> (
    None
):
    graph = GraphBuilder(_catalog())
    source = graph.add(CollectNode, NoConfig())
    target = graph.add(CollectNode, NoConfig())

    with pytest.raises(GraphBuilderError, match="bind the type variable"):
        graph.connect(
            source.output("items"),
            target.input("items"),
            conversion_path=(SavedGraphConversion(id="text.to_markdown", version=1),),
        )


def test_builder_requires_every_artifact_type_variable_before_build() -> None:
    graph = GraphBuilder(_catalog())
    graph.add(CollectNode, NoConfig())

    with pytest.raises(
        GraphBuilderError,
        match="sequence.collect@1 is missing artifact type binding T",
    ):
        graph.build()


def test_builder_rejects_local_node_port_contract_drift() -> None:
    catalog = _catalog()
    text_spec = catalog.nodes[0]
    drifted_text_spec = text_spec.model_copy(
        update={
            "outputs": (
                text_spec.outputs[0].model_copy(
                    update={"artifact_type": MARKDOWN},
                ),
            )
        }
    )
    graph = GraphBuilder(
        catalog.model_copy(
            update={"nodes": (drifted_text_spec, *catalog.nodes[1:])},
        )
    )

    with pytest.raises(
        GraphBuilderError,
        match="text.input@1 does not match the catalog port contracts",
    ):
        graph.add(TextNode, TextConfig(text="hello"))


def test_builder_rejects_required_unconnected_inputs() -> None:
    graph = GraphBuilder(_catalog())
    graph.add(MarkdownNode, NoConfig())

    with pytest.raises(
        GraphBuilderError,
        match="markdown.consume@1 required input 'markdown' has no connection",
    ):
        graph.build()


def test_builder_rejects_cycles_before_serialization() -> None:
    graph = GraphBuilder(_catalog())
    first = graph.add(TransformNode, NoConfig())
    second = graph.add(TransformNode, NoConfig())
    graph.connect(first.output("text"), second.input("text"))
    graph.connect(second.output("text"), first.input("text"))

    with pytest.raises(GraphBuilderError, match="Graph contains a cycle"):
        graph.build()
