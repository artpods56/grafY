"""The Project aggregate and the Graph document it holds (ADR 0020).

A Project is the Workspace-owned object a room opens on; its content is a
``ProjectDocument`` of named Graphs. These tests hold no clock, touch no disk
and wait for nothing: every timestamp a rule needs is passed in.
"""

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence, ArtifactTypeKey
from grafy_core.domain.graph_documents import (
    GraphPoint,
    GraphPresentationAnnotation,
    GraphPresentationDocument,
    GraphPresentationLink,
    GraphPresentationViewer,
    SAVED_GRAPH_SCHEMA_VERSION,
    GraphAnnotationLayout,
    GraphArtifactTypeBinding,
    GraphConversion,
    GraphDocument,
    GraphEdge,
    GraphInputPlug,
    GraphNode,
    GraphNodeLayout,
    GraphOrigin,
)
from grafy_core.domain.identity import WorkspaceKind
from grafy_core.domain.projects import (
    Project,
    ProjectBrowserCreator,
    ProjectBrowserDraft,
    ProjectBrowserFolder,
    ProjectBrowserItem,
    ProjectBrowserLocation,
    ProjectCheckpoint,
    ProjectFolder,
    ProjectOrganization,
    UserProjectState,
)
from grafy_core.kernel.project import GraphDefinition, ProjectDocument

WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")
MORNING = datetime(2026, 7, 14, 8, 30, tzinfo=UTC)
AFTERNOON = datetime(2026, 7, 14, 15, 0, tzinfo=UTC)
NAIVE_MORNING = datetime(2026, 7, 14, 8, 30)


def _node(
    node_id: str,
    *,
    kind: str = "builtin",
    operator_id: str = "example.operator",
    input_plugs: tuple[GraphInputPlug, ...] = (),
    artifact_type_bindings: tuple[GraphArtifactTypeBinding, ...] = (),
) -> GraphNode:
    return GraphNode(
        kind=kind,  # type: ignore[arg-type]
        id=node_id,
        operator_id=operator_id,
        operator_version=1,
        config={},
        position=GraphPoint(x=10.0, y=20.0),
        input_plugs=input_plugs,
        artifact_type_bindings=artifact_type_bindings,
    )


def _edge(
    edge_id: str,
    *,
    from_node: str = "source",
    to_node: str = "target",
) -> GraphEdge:
    return GraphEdge(
        id=edge_id,
        from_node=from_node,
        from_port="result",
        to_node=to_node,
        to_port="value",
    )


def _origin(
    origin_id: str = "origin",
    *,
    to_node: str = "target",
    to_port: str = "value",
    to_plug: str | None = None,
) -> GraphOrigin:
    return GraphOrigin(
        id=origin_id,
        to_node=to_node,
        to_port=to_port,
        to_plug=to_plug,
        value=ArtifactRef(
            artifact_id=UUID("00000000-0000-0000-0000-000000000401"),
            artifact_type="image.raster",
            schema_version=1,
        ),
    )


def test_graph_document_allows_drafts_without_executable_connections() -> None:
    empty_draft = GraphDocument()
    incomplete_draft = GraphDocument(
        nodes=(
            GraphNode(
                kind="builtin",
                id="unconnected",
                operator_id="plugin.that-is-not-installed",
                operator_version=99,
                config={"unfinished": True},
                position=GraphPoint(x=0.0, y=0.0),
            ),
        )
    )

    assert empty_draft.nodes == ()
    assert empty_draft.edges == ()
    assert incomplete_draft.nodes[0].operator_id == "plugin.that-is-not-installed"
    assert incomplete_draft.edges == ()


def test_graph_edge_defaults_enabled_for_legacy_payloads() -> None:
    payload = _edge("legacy").model_dump(mode="json")
    payload.pop("enabled")

    edge = GraphEdge.model_validate(payload)

    assert edge.enabled is True
    assert edge.model_dump(mode="json")["enabled"] is True


def test_graph_document_requires_current_schema_version() -> None:
    document = GraphDocument(
        nodes=(
            _node(
                "collect",
                artifact_type_bindings=(
                    GraphArtifactTypeBinding(
                        variable="T",
                        artifact_type=ArtifactTypeKey("example.value", 2),
                    ),
                ),
            ),
        )
    )

    assert document.schema_version == 7
    assert document.nodes[0].artifact_type_binding_map() == {
        "T": ArtifactTypeKey("example.value", 2)
    }


def test_graph_node_layout_round_trips_and_rejects_empty_or_out_of_range() -> None:
    layout = GraphNodeLayout(width=420, body_height=180, appendix_height=320)
    node = GraphNode(
        kind="builtin",
        id="resized",
        operator_id="example.operator",
        operator_version=1,
        config={},
        position=GraphPoint(x=0.0, y=0.0),
        layout=layout,
    )

    payload = node.model_dump(mode="json")
    assert payload["layout"] == {
        "width": 420.0,
        "body_height": 180.0,
        "appendix_height": 320.0,
    }
    assert GraphNode.model_validate(payload) == node

    with pytest.raises(ValidationError, match="at least one of width"):
        GraphNodeLayout()
    with pytest.raises(ValidationError):
        GraphNodeLayout(width=100)
    with pytest.raises(ValidationError):
        GraphNodeLayout(body_height=10)
    with pytest.raises(ValidationError):
        GraphNodeLayout(appendix_height=10)
    # Past the shared browser/GPU compositing ceiling.
    with pytest.raises(ValidationError):
        GraphNodeLayout(width=16_385)
    assert GraphNodeLayout(body_height=900).body_height == 900.0


def test_presentation_annotations_round_trip_and_reject_shape_text() -> None:
    annotation = GraphPresentationAnnotation(
        id="annotation-note",
        kind="text",
        position=GraphPoint(x=1.0, y=2.0),
        layout=GraphAnnotationLayout(width=200, height=100),
        text="Document this branch",
        color="#b45309",
    )
    document = GraphDocument(
        presentation=GraphPresentationDocument(annotations=(annotation,)),
    )
    payload = document.model_dump(mode="json")
    assert payload["presentation"]["annotations"][0]["text"] == ("Document this branch")
    assert payload["presentation"]["annotations"][0]["color"] == "#B45309"
    assert GraphDocument.model_validate(payload) == document

    with pytest.raises(ValidationError, match="pattern"):
        GraphPresentationAnnotation(
            id="annotation-named-color",
            kind="text",
            position=GraphPoint(x=0.0, y=0.0),
            layout=GraphAnnotationLayout(width=80, height=80),
            color="amber",
        )

    with pytest.raises(ValidationError, match="must start with 'annotation-'"):
        GraphPresentationAnnotation(
            id="bad-id",
            kind="rectangle",
            position=GraphPoint(x=0.0, y=0.0),
            layout=GraphAnnotationLayout(width=80, height=80),
        )
    with pytest.raises(ValidationError, match="must not carry text"):
        GraphPresentationAnnotation(
            id="annotation-shape",
            kind="ellipse",
            position=GraphPoint(x=0.0, y=0.0),
            layout=GraphAnnotationLayout(width=80, height=80),
            text="nope",
        )
    with pytest.raises(ValidationError):
        GraphPresentationAnnotation(
            id="annotation-bad-color",
            kind="text",
            position=GraphPoint(x=0.0, y=0.0),
            layout=GraphAnnotationLayout(width=80, height=80),
            color="red",
        )


ARTIFACT_CARD_REF = ArtifactRef.from_key(
    artifact_id=UUID("00000000-0000-0000-0000-0000000000aa"),
    key=ArtifactTypeKey("table.data", 1),
    content_hash="a" * 64,
)


def test_artifact_card_reference_round_trips_without_a_link() -> None:
    document = GraphDocument(
        presentation=GraphPresentationDocument(
            viewers=(
                GraphPresentationViewer(
                    id="artifact-viewer-card",
                    position=GraphPoint(x=4.0, y=8.0),
                    layout=GraphNodeLayout(width=320, body_height=240),
                    artifact_ref=ARTIFACT_CARD_REF,
                ),
            ),
        ),
    )

    payload = document.model_dump(mode="json")

    assert payload["schema_version"] == 7
    assert payload["presentation"]["viewers"][0]["artifact_ref"] == {
        "artifact_id": "00000000-0000-0000-0000-0000000000aa",
        "artifact_type": "table.data",
        "schema_version": 1,
        "content_hash": "a" * 64,
    }
    assert GraphDocument.model_validate(payload) == document


def test_artifact_card_sequence_round_trips_in_order() -> None:
    # A card that carries many artifacts keeps their order, because that order
    # is what the card passes on.
    card = GraphPresentationViewer(
        id="artifact-viewer-card",
        position=GraphPoint(x=0.0, y=0.0),
        artifact_ref=ArtifactRefSequence(
            artifact_type="file.jpg",
            schema_version=1,
            item_refs=[
                ArtifactRef(
                    artifact_id=UUID("00000000-0000-0000-0000-000000000001"),
                    artifact_type="file.jpg",
                    schema_version=1,
                ),
                ArtifactRef(
                    artifact_id=UUID("00000000-0000-0000-0000-000000000002"),
                    artifact_type="file.jpg",
                    schema_version=1,
                ),
            ],
        ),
    )
    document = GraphDocument(presentation=GraphPresentationDocument(viewers=(card,)))

    payload = document.model_dump(mode="json")

    assert [
        item["artifact_id"]
        for item in payload["presentation"]["viewers"][0]["artifact_ref"]["item_refs"]
    ] == [
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-0000-0000-000000000002",
    ]
    assert GraphDocument.model_validate(payload) == document


def test_artifact_card_keeps_its_reference_when_the_artifact_is_missing() -> None:
    # Loading a document never consults the artifact store, so a deleted or
    # inaccessible artifact leaves the stored reference untouched.
    document = GraphDocument.model_validate(
        {
            "schema_version": SAVED_GRAPH_SCHEMA_VERSION,
            "nodes": [],
            "edges": [],
            "presentation": {
                "viewers": [
                    {
                        "id": "artifact-viewer-card",
                        "position": {"x": 0.0, "y": 0.0},
                        "artifact_ref": {
                            "artifact_id": "00000000-0000-0000-0000-00000000dead",
                            "artifact_type": "table.data",
                            "schema_version": 1,
                        },
                    }
                ]
            },
        }
    )

    card = document.presentation.viewers[0]
    assert card.artifact_ref is not None
    assert card.artifact_ref.artifact_id == UUID("00000000-0000-0000-0000-00000000dead")
    reloaded = GraphDocument.model_validate(document.model_dump(mode="json"))
    assert reloaded.presentation.viewers[0].artifact_ref == card.artifact_ref


def test_presentation_viewer_without_artifact_reference_reads_as_unset() -> None:
    document = GraphDocument.model_validate(
        {
            "schema_version": SAVED_GRAPH_SCHEMA_VERSION,
            "nodes": [],
            "edges": [],
            "presentation": {
                "viewers": [
                    {
                        "id": "artifact-viewer-node-output",
                        "position": {"x": 1.0, "y": 2.0},
                    }
                ]
            },
        }
    )

    assert document.presentation.viewers[0].artifact_ref is None
    assert (
        document.model_dump(mode="json")["presentation"]["viewers"][0]["artifact_ref"]
        is None
    )


def test_artifact_card_cannot_be_a_presentation_link_target() -> None:
    with pytest.raises(ValidationError, match="cannot target artifact card"):
        GraphPresentationDocument(
            viewers=(
                GraphPresentationViewer(
                    id="artifact-viewer-card",
                    position=GraphPoint(x=0.0, y=0.0),
                    artifact_ref=ARTIFACT_CARD_REF,
                ),
            ),
            links=(
                GraphPresentationLink(
                    id="artifact-viewer-edge-1",
                    source_node_id="source",
                    source_port_name="result",
                    target_viewer_id="artifact-viewer-card",
                ),
            ),
        )


def test_graph_document_rejects_presentation_link_to_a_missing_node() -> None:
    """A card link naming a node the document does not hold stays refused.

    The web client now drops such links before building a save request, which is what
    turns the reported 422 into an ordinary save. This check is the last line of
    defence and the authority, so it must not weaken along with the client fix.
    """
    presentation = GraphPresentationDocument(
        viewers=(
            GraphPresentationViewer(
                id="artifact-viewer-1",
                position=GraphPoint(x=0.0, y=0.0),
            ),
        ),
        links=(
            GraphPresentationLink(
                id="artifact-viewer-edge-1",
                source_node_id="deleted-node",
                source_port_name="result",
                target_viewer_id="artifact-viewer-1",
            ),
        ),
    )

    with pytest.raises(
        ValidationError,
        match=(
            "Presentation link artifact-viewer-edge-1 references missing "
            "source node deleted-node"
        ),
    ):
        GraphDocument(nodes=(_node("surviving-node"),), presentation=presentation)

    accepted = GraphDocument(
        nodes=(_node("surviving-node"), _node("deleted-node")),
        presentation=presentation,
    )
    assert accepted.presentation.links[0].source_node_id == "deleted-node"


def test_graph_node_config_is_deeply_immutable_and_serializable() -> None:
    node = GraphNode(
        kind="builtin",
        id="configured",
        operator_id="example.operator",
        operator_version=1,
        config={"nested": {"enabled": True}, "values": [1, 2]},
        position=GraphPoint(x=0.0, y=0.0),
    )

    with pytest.raises(TypeError):
        cast(dict[str, object], node.config)["new"] = "value"
    with pytest.raises(TypeError):
        cast(dict[str, object], node.config["nested"])["enabled"] = False

    assert node.config_dict() == {
        "nested": {"enabled": True},
        "values": [1, 2],
    }
    assert node.model_dump(mode="json")["config"] == node.config_dict()


def test_graph_node_serializes_validated_artifact_type_bindings() -> None:
    binding = GraphArtifactTypeBinding(
        variable="T",
        artifact_type=ArtifactTypeKey("image.raster", 1),
    )
    node = _node("collect", artifact_type_bindings=(binding,))

    payload = node.model_dump(mode="json")

    assert payload["artifact_type_bindings"] == [
        {
            "variable": "T",
            "artifact_type": {
                "id": "image.raster",
                "schema_version": 1,
            },
        }
    ]
    assert GraphNode.model_validate(payload) == node
    assert node.artifact_type_binding_map() == {"T": ArtifactTypeKey("image.raster", 1)}


def test_graph_node_requires_unique_artifact_type_binding_variables() -> None:
    first = GraphArtifactTypeBinding(
        variable="T",
        artifact_type=ArtifactTypeKey("example.first", 1),
    )
    second = GraphArtifactTypeBinding(
        variable="T",
        artifact_type=ArtifactTypeKey("example.second", 1),
    )

    with pytest.raises(
        ValidationError,
        match="artifact type binding variables must be unique",
    ):
        _node("collect", artifact_type_bindings=(first, second))


@pytest.mark.parametrize(
    "artifact_type",
    [
        ArtifactTypeKey("", 1),
        ArtifactTypeKey("example.value", 0),
    ],
)
def test_graph_artifact_type_binding_rejects_invalid_concrete_key(
    artifact_type: ArtifactTypeKey,
) -> None:
    with pytest.raises(ValidationError, match="bound artifact type"):
        GraphArtifactTypeBinding(
            variable="T",
            artifact_type=artifact_type,
        )


def test_graph_document_requires_unique_node_ids() -> None:
    with pytest.raises(ValidationError, match="node ids must be unique"):
        GraphDocument(nodes=(_node("duplicate"), _node("duplicate")))


def test_graph_document_requires_unique_edge_ids() -> None:
    with pytest.raises(ValidationError, match="edge ids must be unique"):
        GraphDocument(
            nodes=(_node("source"), _node("target")),
            edges=(_edge("duplicate"), _edge("duplicate")),
        )


def test_graph_document_preserves_ordered_input_plugs() -> None:
    plugs = (
        GraphInputPlug(id="second", port="items"),
        GraphInputPlug(id="first", port="items"),
    )

    document = GraphDocument(nodes=(_node("collect", input_plugs=plugs),))

    assert document.nodes[0].input_plugs == plugs
    assert document.model_dump(mode="json")["nodes"][0]["input_plugs"] == [
        {"id": "second", "port": "items"},
        {"id": "first", "port": "items"},
    ]


def test_graph_document_requires_unique_input_plug_ids_per_node() -> None:
    duplicate_plugs = (
        GraphInputPlug(id="item", port="items"),
        GraphInputPlug(id="item", port="items"),
    )

    with pytest.raises(ValidationError, match="input plug ids must be unique"):
        GraphDocument(nodes=(_node("collect", input_plugs=duplicate_plugs),))


def test_graph_document_requires_edges_to_reference_target_input_plugs() -> None:
    target = _node(
        "target",
        input_plugs=(GraphInputPlug(id="item", port="items"),),
    )

    with pytest.raises(ValidationError, match="missing input plug absent"):
        GraphDocument(
            nodes=(_node("source"), target),
            edges=(
                _edge("plugged").model_copy(
                    update={"to_port": "items", "to_plug": "absent"}
                ),
            ),
        )


def test_graph_document_requires_edge_port_to_match_input_plug_port() -> None:
    target = _node(
        "target",
        input_plugs=(GraphInputPlug(id="item", port="items"),),
    )

    with pytest.raises(ValidationError, match="belongs to port items"):
        GraphDocument(
            nodes=(_node("source"), target),
            edges=(_edge("plugged").model_copy(update={"to_plug": "item"}),),
        )


def test_graph_document_allows_at_most_one_edge_per_input_plug() -> None:
    target = _node(
        "target",
        input_plugs=(GraphInputPlug(id="item", port="items"),),
    )
    plugged_edge = _edge("first").model_copy(
        update={"to_port": "items", "to_plug": "item"}
    )

    with pytest.raises(ValidationError, match="accepts at most one edge"):
        GraphDocument(
            nodes=(_node("source"), target),
            edges=(
                plugged_edge,
                plugged_edge.model_copy(update={"id": "second"}),
            ),
        )


def test_disabled_edge_still_reserves_its_target_input_plug() -> None:
    target = _node(
        "target",
        input_plugs=(GraphInputPlug(id="item", port="items"),),
    )
    disabled_edge = _edge("disabled").model_copy(
        update={"enabled": False, "to_port": "items", "to_plug": "item"}
    )
    replacement_edge = _edge("replacement", from_node="other-source").model_copy(
        update={"to_port": "items", "to_plug": "item"}
    )

    with pytest.raises(ValidationError, match="accepts at most one edge"):
        GraphDocument(
            nodes=(_node("source"), _node("other-source"), target),
            edges=(disabled_edge, replacement_edge),
        )


def test_disabled_edge_still_requires_structurally_valid_endpoints() -> None:
    disabled_edge = _edge("disabled", to_node="absent").model_copy(
        update={"enabled": False}
    )

    with pytest.raises(ValidationError, match="missing target node absent"):
        GraphDocument(
            nodes=(_node("source"),),
            edges=(disabled_edge,),
        )


@pytest.mark.parametrize(
    ("edge", "message"),
    [
        (_edge("missing-source", from_node="absent"), "missing source node absent"),
        (_edge("missing-target", to_node="absent"), "missing target node absent"),
    ],
)
def test_graph_document_rejects_edges_to_missing_nodes(
    edge: GraphEdge,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        GraphDocument(
            nodes=(_node("source"), _node("target")),
            edges=(edge,),
        )


def test_graph_document_rejects_a_version_six_document() -> None:
    with pytest.raises(ValidationError, match="schema_version"):
        GraphDocument.model_validate(
            {
                "schema_version": 6,
                "nodes": [_node("source").model_dump(mode="json")],
                "edges": [],
            }
        )


def test_graph_origin_round_trips_an_exact_reference() -> None:
    origin = _origin().model_copy(
        update={"conversion_path": (GraphConversion(id="as-text", version=1),)}
    )
    document = GraphDocument(
        nodes=(_node("target"),),
        origins=(origin,),
    )

    payload = document.model_dump(mode="json")

    assert payload["origins"][0]["value"]["artifact_type"] == "image.raster"
    assert payload["origins"][0]["conversion_path"] == [{"id": "as-text", "version": 1}]
    assert GraphDocument.model_validate(payload).origins[0].value == origin.value


def test_graph_origin_accepts_an_artifact_ref_sequence() -> None:
    sequence = ArtifactRefSequence(
        artifact_type="image.raster",
        schema_version=1,
        item_refs=[
            ArtifactRef(
                artifact_id=UUID("00000000-0000-0000-0000-000000000401"),
                artifact_type="image.raster",
                schema_version=1,
            )
        ],
    )

    origin = GraphOrigin(
        id="origin",
        to_node="target",
        to_port="value",
        value=sequence,
    )

    assert isinstance(origin.value, ArtifactRefSequence)


def test_graph_document_requires_unique_origin_ids() -> None:
    with pytest.raises(ValidationError, match="origin ids must be unique"):
        GraphDocument(
            nodes=(_node("target"),),
            origins=(_origin(), _origin()),
        )


def test_graph_document_requires_origins_to_reference_existing_nodes() -> None:
    with pytest.raises(ValidationError, match="missing target node absent"):
        GraphDocument(
            nodes=(_node("target"),),
            origins=(_origin(to_node="absent"),),
        )


def test_graph_document_requires_origin_plug_to_exist_and_match_port() -> None:
    target = _node(
        "target",
        input_plugs=(GraphInputPlug(id="item", port="items"),),
    )

    with pytest.raises(ValidationError, match="missing input plug absent"):
        GraphDocument(
            nodes=(target,),
            origins=(_origin(to_port="items", to_plug="absent"),),
        )

    with pytest.raises(ValidationError, match="belongs to port items"):
        GraphDocument(
            nodes=(target,),
            origins=(_origin(to_port="value", to_plug="item"),),
        )


def test_graph_document_allows_one_origin_per_input_slot() -> None:
    target = _node(
        "target",
        input_plugs=(GraphInputPlug(id="item", port="items"),),
    )
    origin = _origin(to_port="items", to_plug="item")

    document = GraphDocument(nodes=(target,), origins=(origin,))

    assert document.origins == (origin,)

    with pytest.raises(ValidationError, match="already satisfied"):
        GraphDocument(
            nodes=(target,),
            origins=(origin, origin.model_copy(update={"id": "second"})),
        )


def test_graph_document_origin_conflicts_with_enabled_edge_only() -> None:
    target = _node(
        "target",
        input_plugs=(GraphInputPlug(id="item", port="items"),),
    )
    origin = _origin(to_port="items", to_plug="item")
    edge = _edge("plugged").model_copy(update={"to_port": "items", "to_plug": "item"})

    disabled_edge_document = GraphDocument(
        nodes=(_node("source"), target),
        edges=(edge.model_copy(update={"enabled": False}),),
        origins=(origin,),
    )
    assert disabled_edge_document.origins == (origin,)

    with pytest.raises(ValidationError, match="already satisfied"):
        GraphDocument(
            nodes=(_node("source"), target),
            edges=(edge,),
            origins=(origin,),
        )


def test_graph_document_rejects_two_origins_on_one_unplugged_port() -> None:
    with pytest.raises(ValidationError, match="already satisfied"):
        GraphDocument(
            nodes=(_node("target"),),
            origins=(_origin("first"), _origin("second")),
        )


@pytest.mark.parametrize(
    "implementation_key",
    ["plugin_release", "plugin_release_pin"],
)
def test_graph_node_rejects_plugin_implementation_fields(
    implementation_key: str,
) -> None:
    base = _node("echo").model_dump(mode="json")
    # The saved node model is fail-closed about unknown fields.
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GraphNode.model_validate({**base, implementation_key: {"slug": "notes"}})


def test_graph_node_rejects_plugin_kind() -> None:
    base = _node("echo").model_dump(mode="json")
    with pytest.raises(ValidationError, match="kind"):
        GraphNode.model_validate({**base, "kind": "plugin"})


def _project_document(*graph_ids: str) -> ProjectDocument:
    return ProjectDocument(
        graphs=tuple(
            GraphDefinition(id=graph_id, name=graph_id, document=GraphDocument())
            for graph_id in graph_ids
        )
    )


# The Project aggregate: identity, metadata and filing.


@pytest.mark.parametrize("name", ["", "   ", "x" * 161])
def test_project_rejects_invalid_names(name: str) -> None:
    with pytest.raises(ValueError, match="Project name"):
        Project(workspace_id=WORKSPACE_ID, name=name)


def test_project_requires_aware_timestamps() -> None:
    with pytest.raises(ValueError, match="timestamps must be timezone-aware"):
        Project(
            workspace_id=WORKSPACE_ID,
            name="Draft",
            created_at=NAIVE_MORNING,
            updated_at=MORNING,
        )


def test_project_rename_normalizes_name_and_stamps_update() -> None:
    project = Project(
        workspace_id=WORKSPACE_ID,
        name="Original",
        created_at=MORNING,
        updated_at=MORNING,
    )

    project.rename("  Renamed draft  ", updated_at=AFTERNOON)

    assert project.name == "Renamed draft"
    assert project.created_at == MORNING
    assert project.updated_at == AFTERNOON


def test_project_rename_rejects_a_naive_timestamp_without_moving() -> None:
    project = Project(workspace_id=WORKSPACE_ID, name="Draft", updated_at=MORNING)

    with pytest.raises(ValueError, match="timezone-aware"):
        project.rename("Renamed", updated_at=NAIVE_MORNING)

    assert project.name == "Draft"
    assert project.updated_at == MORNING


def test_project_checkpoint_snapshots_one_revision_of_the_document() -> None:
    document = _project_document("main", "prepare")
    checkpoint = ProjectCheckpoint(
        workspace_id=WORKSPACE_ID,
        project_id=uuid4(),
        revision=3,
        name="  Nightly  ",
        document=document,
        created_at=MORNING,
    )

    assert checkpoint.name == "Nightly"
    assert [graph.name for graph in checkpoint.document.graphs] == ["main", "prepare"]


def test_project_checkpoint_rejects_stale_revision_and_naive_timestamp() -> None:
    with pytest.raises(ValueError, match="revision must be at least 1"):
        ProjectCheckpoint(
            workspace_id=WORKSPACE_ID,
            project_id=uuid4(),
            revision=0,
            name="Draft",
            document=_project_document("main"),
            created_at=MORNING,
        )

    with pytest.raises(ValueError, match="timestamp must be timezone-aware"):
        ProjectCheckpoint(
            workspace_id=WORKSPACE_ID,
            project_id=uuid4(),
            revision=1,
            name="Draft",
            document=_project_document("main"),
            created_at=NAIVE_MORNING,
        )


def test_project_checkpoint_is_frozen() -> None:
    checkpoint = ProjectCheckpoint(
        workspace_id=WORKSPACE_ID,
        project_id=uuid4(),
        revision=1,
        name="Draft",
        document=_project_document("main"),
        created_at=MORNING,
    )

    with pytest.raises(Exception, match="cannot assign"):
        checkpoint.name = "Rewritten"  # type: ignore[misc]


def test_project_folder_rename_and_timestamp_rules() -> None:
    folder = ProjectFolder(workspace_id=WORKSPACE_ID, name="  Analysis  ")
    assert folder.name == "Analysis"

    folder.rename("Archived analysis", updated_at=AFTERNOON)
    assert folder.name == "Archived analysis"
    assert folder.updated_at == AFTERNOON

    with pytest.raises(ValueError, match="Project folder name must not be blank"):
        ProjectFolder(workspace_id=WORKSPACE_ID, name="   ")

    with pytest.raises(ValueError, match="timezone-aware"):
        ProjectFolder(
            workspace_id=WORKSPACE_ID,
            name="Analysis",
            created_at=NAIVE_MORNING,
            updated_at=MORNING,
        )


def test_user_project_state_star_and_last_opened() -> None:
    state = UserProjectState(
        workspace_id=WORKSPACE_ID,
        project_id=uuid4(),
        user_id=uuid4(),
    )
    assert state.starred is False
    assert state.last_opened_at is None

    state.set_starred(True)
    state.record_open(opened_at=AFTERNOON)
    state.record_open(opened_at=MORNING)

    assert state.starred is True
    assert state.last_opened_at == AFTERNOON

    with pytest.raises(ValueError, match="timezone-aware"):
        state.record_open(opened_at=NAIVE_MORNING)


def test_project_organization_filing_and_archive_go_both_ways() -> None:
    folder_id = uuid4()
    organization = ProjectOrganization(
        workspace_id=WORKSPACE_ID,
        project_id=uuid4(),
    )
    assert organization.is_archived is False

    organization.assign_folder(folder_id, updated_at=MORNING)
    assert organization.folder_id == folder_id

    organization.archive(archived_at=AFTERNOON)
    assert organization.is_archived is True
    assert organization.archived_at == AFTERNOON

    organization.archive(archived_at=MORNING)
    assert organization.archived_at == AFTERNOON

    organization.restore(restored_at=MORNING)
    assert organization.is_archived is False
    assert organization.archived_at is None

    organization.assign_folder(None, updated_at=MORNING)
    assert organization.folder_id is None


def test_project_organization_rejects_naive_timestamps() -> None:
    with pytest.raises(
        ValueError, match="organization timestamp must be timezone-aware"
    ):
        ProjectOrganization(
            workspace_id=WORKSPACE_ID,
            project_id=uuid4(),
            updated_at=NAIVE_MORNING,
        )

    with pytest.raises(ValueError, match="archive timestamp must be timezone-aware"):
        ProjectOrganization(
            workspace_id=WORKSPACE_ID,
            project_id=uuid4(),
            archived_at=NAIVE_MORNING,
        )


def test_project_browser_item_carries_head_counts_and_archived_state() -> None:
    item = ProjectBrowserItem(
        id=uuid4(),
        draft=ProjectBrowserDraft(
            name="Nightly",
            head_sequence=7,
            checkpoint_sequence=6,
            checkpoint_revision=4,
            updated_at=AFTERNOON,
            graph_count=3,
            node_count=12,
            edge_count=9,
        ),
        location=ProjectBrowserLocation(
            id=WORKSPACE_ID,
            slug="analysis",
            name="Analysis",
            kind=WorkspaceKind.SHARED,
        ),
        folder=ProjectBrowserFolder(id=uuid4(), name="Nightly work"),
        archived_at=None,
        starred=True,
        last_opened_at=MORNING,
        organization_updated_at=MORNING,
        creator=ProjectBrowserCreator(id=uuid4(), display_name="Ada"),
    )

    assert item.is_archived is False
    assert item.draft.graph_count == 3
    assert item.draft.head_sequence == item.draft.checkpoint_sequence + 1

    assert replace(item, archived_at=AFTERNOON).is_archived is True
