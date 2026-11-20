from typing import Annotated, Any, ClassVar, override
from uuid import UUID

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
from grafy_core.artifact_contracts import MarkdownValue
from grafy_core.artifacts import (
    ArtifactRef,
    ArtifactTypeKey,
    NoConfig,
    NodeConfig,
    NodeInput,
    NodeOutput,
)
from grafy_core.domain.graph_documents import (
    GraphPoint,
    GraphConversion,
)
from grafy_core.nodes import (
    ArtifactTypeVariable,
    Binds,
    Node,
    NodeExecutionContext,
    Plugs,
    PortShape,
    Ref,
    RefSequence,
)

import grafy_workbench.text.nodes as _text_nodes

_ = _text_nodes.__name__  # notes str before these ports

TEXT = ArtifactTypeKey("scalar.text", 1)
MARKDOWN = ArtifactTypeKey("text.markdown", 1)
T = ArtifactTypeVariable("T")


class TextConfig(NodeConfig):
    text: str


class EmptyInput(NodeInput):
    pass


class TextOutput(NodeOutput):
    text: str


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
        list[Ref[Any] | RefSequence[Any]],
        Plugs(variadic=True, instance=True),
        Binds("T"),
    ]


class CollectOutput(NodeOutput):
    items: Annotated[RefSequence[Any], Binds("T")]


class CollectNode(Node[NoConfig, CollectInput, CollectOutput]):
    operator_id: ClassVar[str] = "test.sequence.collect"
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
    markdown: MarkdownValue


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
    text: str


class TransformOutput(NodeOutput):
    text: str


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
                operator_id="test.sequence.collect",
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
                origin="builtin",
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
            }
        ],
        "edges": [],
        "origins": [],
        "agents": [],
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


def test_builder_writes_a_family_node_as_builtin_without_a_pin() -> None:
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
        conversion_path=(GraphConversion(id="text.to_markdown", version=1),),
    )

    document = graph.build()
    assert document.nodes[1].kind == "builtin"
    assert "plugin_release_pin" not in document.nodes[1].model_dump()


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
        conversion_path=(GraphConversion(id="text.to_markdown", version=1),),
    )

    document = graph.build()
    assert document.edges[0].conversion_path == (
        GraphConversion(id="text.to_markdown", version=1),
    )


def test_builder_infers_variable_from_explicit_conversion_result() -> None:
    graph = GraphBuilder(_catalog())
    text = graph.add(TextNode, TextConfig(text="hello"))
    collect = graph.add(CollectNode, NoConfig())

    graph.connect(
        text.output("text"),
        collect.input("items"),
        conversion_path=(GraphConversion(id="text.to_markdown", version=1),),
    )

    document = graph.build()
    assert document.nodes[1].artifact_type_binding_map() == {"T": MARKDOWN}
    assert document.edges[0].conversion_path == (
        GraphConversion(id="text.to_markdown", version=1),
    )


def test_builder_rejected_connection_does_not_mutate_graph() -> None:
    graph = GraphBuilder(_catalog())
    text = graph.add(TextNode, TextConfig(text="hello"))
    collect = graph.add(CollectNode, NoConfig())

    with pytest.raises(GraphBuilderError, match="does.not.exist@1"):
        graph.connect(
            text.output("text"),
            collect.input("items"),
            conversion_path=(GraphConversion(id="does.not.exist", version=1),),
        )

    graph.connect(
        text.output("text"),
        collect.input("items"),
        conversion_path=(GraphConversion(id="text.to_markdown", version=1),),
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
            conversion_path=(GraphConversion(id="text.to_markdown", version=1),),
        )


def test_builder_requires_every_artifact_type_variable_before_build() -> None:
    graph = GraphBuilder(_catalog())
    graph.add(CollectNode, NoConfig())

    with pytest.raises(
        GraphBuilderError,
        match="test.sequence.collect@1 is missing artifact type binding T",
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


TEXT_REF = ArtifactRef(
    artifact_id=UUID("66666666-6666-4666-8666-666666666666"),
    artifact_type="scalar.text",
    schema_version=1,
    content_hash="a" * 64,
)


def test_builder_keeps_an_explicit_node_id_and_refuses_a_duplicate() -> None:
    graph = GraphBuilder(_catalog())
    text = graph.add(TextNode, TextConfig(text="x"), node_id="title")

    with pytest.raises(GraphBuilderError, match="already in this graph"):
        _ = graph.add(TextNode, TextConfig(text="y"), node_id="title")

    assert text.node_id == "title"
    assert [node.id for node in graph.build().nodes] == ["title"]


def test_a_library_card_placed_on_an_input_owns_the_origin() -> None:
    graph = GraphBuilder(_catalog())
    collect = graph.add(CollectNode, NoConfig(), node_id="collect")
    card = graph.add_artifact_card(TEXT_REF)

    graph.place(collect.input("items"), card)
    document = graph.build()

    origin = document.origins[0]
    assert origin.value == TEXT_REF
    assert origin.to_plug == "plug-0001"
    assert origin.source_card_ids == (card.card_id,)
    assert document.presentation.viewers[0].artifact_ref == TEXT_REF
    assert document.nodes[0].artifact_type_binding_map() == {"T": TEXT}


def test_an_origin_of_the_wrong_artifact_type_is_refused() -> None:
    graph = GraphBuilder(_catalog())
    markdown = graph.add(MarkdownNode, NoConfig())

    with pytest.raises(GraphBuilderError, match="does not accept scalar.text@1"):
        graph.place(markdown.input("markdown"), TEXT_REF)
    graph.place(
        markdown.input("markdown"),
        TEXT_REF,
        conversion_path=(GraphConversion(id="text.to_markdown", version=1),),
    )

    assert graph.build().origins[0].conversion_path[0].id == "text.to_markdown"


def test_an_input_satisfied_by_an_origin_takes_no_edge() -> None:
    graph = GraphBuilder(_catalog())
    text = graph.add(TextNode, TextConfig(text="x"))
    markdown = graph.add(MarkdownNode, NoConfig())
    graph.place(
        markdown.input("markdown"),
        TEXT_REF,
        conversion_path=(GraphConversion(id="text.to_markdown", version=1),),
    )

    with pytest.raises(GraphBuilderError, match="accepts at most one edge"):
        graph.connect(
            text.output("text"),
            markdown.input("markdown"),
            conversion_path=(GraphConversion(id="text.to_markdown", version=1),),
        )


def test_output_cards_follow_a_node_and_bind_to_each_other() -> None:
    graph = GraphBuilder(_catalog())
    text = graph.add(TextNode, TextConfig(text="x"), node_id="text")
    shown = graph.add_output_card(text.output("text"))
    library = graph.add_artifact_card(TEXT_REF, card_id="artifact-viewer-library")

    binding_id = graph.bind_cards(shown, library, {"site": "site_id"})
    presentation = graph.build().presentation

    assert [viewer.id for viewer in presentation.viewers] == [
        shown.card_id,
        "artifact-viewer-library",
    ]
    assert presentation.viewers[0].mode == "artifact"
    link = presentation.links[0]
    assert (link.source_node_id, link.source_port_name, link.target_viewer_id) == (
        "text",
        "text",
        shown.card_id,
    )
    binding = presentation.bindings[0]
    assert binding.id == binding_id
    assert binding.effects == ("highlight", "focus")
    assert [(item.source_field, item.target_field) for item in binding.mappings] == [
        ("site", "site_id")
    ]


def test_cards_refuse_unknown_outputs_and_self_bindings() -> None:
    graph = GraphBuilder(_catalog())
    text = graph.add(TextNode, TextConfig(text="x"))
    card = graph.add_artifact_card(TEXT_REF)

    with pytest.raises(GraphBuilderError, match="no output port 'missing'"):
        _ = graph.add_output_card(text.output("missing"))
    with pytest.raises(GraphBuilderError, match="cannot target its source"):
        _ = graph.bind_cards(card, card, {"a": "b"})
    with pytest.raises(GraphBuilderError, match="follows a node output"):
        graph.place(
            graph.add(CollectNode, NoConfig()).input("items"),
            graph.add_output_card(text.output("text")),
        )
