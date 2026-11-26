"""``graph_commands`` sends what a gesture would send, and the replay lands.

The point of the diff is not that it is small, it is that feeding its commands
through the server's own ``apply_graph_command`` produces exactly the document the
client edited. Every test here therefore replays, and only then checks that the
edit was expressed as the fine-grained command the Workbench uses rather than a
wholesale document swap.
"""

from collections.abc import Mapping, Sequence
from uuid import UUID

from grafy_client import graph_commands
from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.domain.collaboration import (
    UpdateNodeConfigurationCommand,
    apply_graph_command,
)
from grafy_core.domain.graph_documents import (
    GraphAnnotationLayout,
    GraphArtifactTypeBinding,
    GraphDocument,
    GraphEdge,
    GraphInputPlug,
    GraphNode,
    GraphNodeLayout,
    GraphOrigin,
    GraphPoint,
    GraphPresentationAnnotation,
    GraphPresentationDocument,
    GraphPresentationLink,
    GraphPresentationViewer,
)

ARTIFACT_ID = UUID("11111111-1111-1111-1111-111111111111")
CSV = ArtifactTypeKey(id="file.csv", schema_version=1)


def _plug(plug_id: str, port: str = "items") -> GraphInputPlug:
    return GraphInputPlug(id=plug_id, port=port)


def _binding(
    artifact_type: ArtifactTypeKey, variable: str = "T"
) -> GraphArtifactTypeBinding:
    return GraphArtifactTypeBinding(variable=variable, artifact_type=artifact_type)


def _node(
    node_id: str,
    *,
    operator_id: str = "value.integer",
    config: Mapping[str, object] | None = None,
    x: float = 0.0,
    y: float = 0.0,
    layout: GraphNodeLayout | None = None,
    input_plugs: Sequence[GraphInputPlug] = (),
    artifact_type_bindings: Sequence[GraphArtifactTypeBinding] = (),
) -> GraphNode:
    return GraphNode(
        kind="builtin",
        id=node_id,
        operator_id=operator_id,
        operator_version=1,
        config=dict(config or {}),
        position=GraphPoint(x=x, y=y),
        layout=layout,
        input_plugs=tuple(input_plugs),
        artifact_type_bindings=tuple(artifact_type_bindings),
    )


def _edge(
    edge_id: str,
    *,
    from_node: str,
    to_node: str,
    to_port: str = "value",
    to_plug: str | None = None,
    enabled: bool = True,
) -> GraphEdge:
    return GraphEdge(
        id=edge_id,
        from_node=from_node,
        from_port="out",
        to_node=to_node,
        to_port=to_port,
        to_plug=to_plug,
        enabled=enabled,
    )


def _origin(
    origin_id: str,
    *,
    to_node: str,
    to_port: str,
    artifact_type: ArtifactTypeKey = CSV,
) -> GraphOrigin:
    return GraphOrigin(
        id=origin_id,
        to_node=to_node,
        to_port=to_port,
        value=ArtifactRef.from_key(artifact_id=ARTIFACT_ID, key=artifact_type),
    )


def _viewer(
    viewer_id: str = "artifact-viewer-0001",
    *,
    x: float = 0.0,
    y: float = 0.0,
) -> GraphPresentationViewer:
    return GraphPresentationViewer(
        id=viewer_id, position=GraphPoint(x=x, y=y), mode="artifact"
    )


def _link(
    *,
    source_node_id: str,
    target_viewer_id: str = "artifact-viewer-0001",
) -> GraphPresentationLink:
    return GraphPresentationLink(
        id="artifact-viewer-edge-0001",
        source_node_id=source_node_id,
        source_port_name="out",
        target_viewer_id=target_viewer_id,
    )


def _annotation(
    *,
    x: float = 0.0,
    y: float = 0.0,
    text: str = "notes",
) -> GraphPresentationAnnotation:
    return GraphPresentationAnnotation(
        id="annotation-1",
        kind="text",
        position=GraphPoint(x=x, y=y),
        layout=GraphAnnotationLayout(width=200, height=80),
        text=text,
    )


def _presentation(
    viewers: Sequence[GraphPresentationViewer] = (),
    links: Sequence[GraphPresentationLink] = (),
    annotations: Sequence[GraphPresentationAnnotation] = (),
) -> GraphPresentationDocument:
    return GraphPresentationDocument(
        viewers=tuple(viewers),
        links=tuple(links),
        annotations=tuple(annotations),
    )


def _document(
    nodes: Sequence[GraphNode] = (),
    edges: Sequence[GraphEdge] = (),
    origins: Sequence[GraphOrigin] = (),
    presentation: GraphPresentationDocument | None = None,
) -> GraphDocument:
    return GraphDocument(
        nodes=tuple(nodes),
        edges=tuple(edges),
        origins=tuple(origins),
        presentation=presentation or GraphPresentationDocument(),
    )


def _replay(before: GraphDocument, after: GraphDocument) -> list[str]:
    commands = graph_commands(before, after)
    document = before
    for command in commands:
        document = apply_graph_command(document=document, command=command)
    assert document == after
    return [command.kind.value for command in commands]


def test_equal_documents_produce_no_commands() -> None:
    document = _document(
        nodes=[_node("node-a", config={"value": 1}, x=10, y=20)],
        edges=[_edge("edge-1", from_node="node-a", to_node="node-a")],
    )

    assert _replay(document, document) == []


def test_moving_two_nodes_is_one_move_nodes_command() -> None:
    before = _document(nodes=[_node("node-a"), _node("node-b", x=400, y=40)])
    after = _document(
        nodes=[_node("node-a", x=100, y=100), _node("node-b", x=420, y=60)]
    )

    assert _replay(before, after) == ["move_nodes"]


def test_changing_one_config_field_carries_the_expected_value() -> None:
    before = _document(nodes=[_node("node-a", config={"value": 3, "label": "a"})])
    after = _document(nodes=[_node("node-a", config={"value": 4, "label": "a"})])

    assert _replay(before, after) == ["update_node_configuration"]

    command = graph_commands(before, after)[0]
    assert isinstance(command, UpdateNodeConfigurationCommand)
    assert command.field == "value"
    assert command.value == 4
    assert command.expected_value == 3


def test_removing_a_config_key_is_one_compound_command() -> None:
    before = _document(nodes=[_node("node-a", config={"value": 3, "label": "a"})])
    after = _document(nodes=[_node("node-a", config={"value": 3})])

    assert _replay(before, after) == ["update_node_configuration_and_input_plugs"]


def test_adding_a_node_and_its_edge_appends_add_then_wire() -> None:
    before = _document(nodes=[_node("node-a")])
    after = _document(
        nodes=[_node("node-a"), _node("node-b", operator_id="sequence.count")],
        edges=[_edge("edge-1", from_node="node-a", to_node="node-b")],
    )

    assert _replay(before, after) == ["add_node", "add_edge"]


def test_removing_a_node_takes_its_edge_and_origin_without_extra_commands() -> None:
    before = _document(
        nodes=[_node("node-a"), _node("node-b", input_plugs=[_plug("plug-0001")])],
        edges=[_edge("edge-1", from_node="node-a", to_node="node-b", to_port="items")],
        origins=[_origin("origin-1", to_node="node-b", to_port="spare")],
    )
    after = _document(nodes=[_node("node-a")])

    assert _replay(before, after) == ["remove_nodes"]


def test_removing_only_an_edge_is_a_removal_not_a_document_swap() -> None:
    before = _document(
        nodes=[_node("node-a"), _node("node-b")],
        edges=[_edge("edge-1", from_node="node-a", to_node="node-b")],
    )
    after = _document(nodes=[_node("node-a"), _node("node-b")])

    assert _replay(before, after) == ["remove_edges"]


def test_disabling_an_edge_updates_it_in_place() -> None:
    before = _document(
        nodes=[_node("node-a"), _node("node-b")],
        edges=[_edge("edge-1", from_node="node-a", to_node="node-b")],
    )
    after = _document(
        nodes=[_node("node-a"), _node("node-b")],
        edges=[_edge("edge-1", from_node="node-a", to_node="node-b", enabled=False)],
    )

    assert _replay(before, after) == ["update_edge"]


def test_swapping_the_operator_under_a_kept_id_rebuilds_the_node() -> None:
    before = _document(
        nodes=[_node("node-a"), _node("node-b", operator_id="value.integer")],
        edges=[_edge("edge-1", from_node="node-a", to_node="node-b")],
    )
    after = _document(
        # Remove then add leaves the rebuilt node at the end of the tuple.
        nodes=[_node("node-a"), _node("node-b", operator_id="sequence.count")],
        edges=[_edge("edge-1", from_node="node-a", to_node="node-b")],
    )

    assert _replay(before, after) == ["remove_nodes", "add_node", "add_edge"]


def test_resizing_a_node_is_one_update_node_layout_command() -> None:
    before = _document(nodes=[_node("node-a", layout=GraphNodeLayout(width=300))])
    after = _document(nodes=[_node("node-a", layout=GraphNodeLayout(width=420))])

    assert _replay(before, after) == ["update_node_layout"]


def test_adding_an_artifact_type_binding_is_its_own_command() -> None:
    before = _document(nodes=[_node("node-a")])
    after = _document(nodes=[_node("node-a", artifact_type_bindings=[_binding(CSV)])])

    assert _replay(before, after) == ["set_node_artifact_type_binding"]


def test_clearing_an_artifact_type_binding_is_its_own_command() -> None:
    before = _document(nodes=[_node("node-a", artifact_type_bindings=[_binding(CSV)])])
    after = _document(nodes=[_node("node-a")])

    assert _replay(before, after) == ["clear_node_artifact_type_binding"]


def test_changing_only_input_plugs_is_one_set_command() -> None:
    before = _document(nodes=[_node("node-a", input_plugs=[_plug("plug-0001")])])
    after = _document(
        nodes=[_node("node-a", input_plugs=[_plug("plug-0001"), _plug("plug-0002")])]
    )

    assert _replay(before, after) == ["set_node_input_plugs"]


def test_moving_only_a_card_is_a_viewer_move_not_a_presentation_swap() -> None:
    before = _document(
        nodes=[_node("node-a")],
        presentation=_presentation(viewers=[_viewer()]),
    )
    after = _document(
        nodes=[_node("node-a")],
        presentation=_presentation(viewers=[_viewer(x=640, y=120)]),
    )

    assert _replay(before, after) == ["move_artifact_viewers"]


def test_moving_only_an_annotation_is_an_annotation_move() -> None:
    before = _document(
        nodes=[_node("node-a")],
        presentation=_presentation(annotations=[_annotation()]),
    )
    after = _document(
        nodes=[_node("node-a")],
        presentation=_presentation(annotations=[_annotation(x=90, y=30)]),
    )

    assert _replay(before, after) == ["move_annotations"]


def test_editing_annotation_text_has_to_replace_the_presentation() -> None:
    before = _document(
        nodes=[_node("node-a")],
        presentation=_presentation(annotations=[_annotation()]),
    )
    after = _document(
        nodes=[_node("node-a")],
        presentation=_presentation(annotations=[_annotation(text="done")]),
    )

    assert _replay(before, after) == ["replace_presentation"]


def test_removing_a_card_followed_node_prunes_the_link_on_the_server() -> None:
    before = _document(
        nodes=[_node("node-a"), _node("node-b")],
        presentation=_presentation(
            viewers=[_viewer()], links=[_link(source_node_id="node-b")]
        ),
    )
    after = _document(
        nodes=[_node("node-a")],
        presentation=_presentation(viewers=[_viewer()]),
    )

    assert _replay(before, after) == ["remove_nodes"]
