"""Contracts for canonical graph values crossing the compatibility transport."""

from datetime import UTC, datetime
from types import MappingProxyType
from uuid import UUID
from typing import Literal

import pytest
from pydantic import ValidationError

from grafy_api.graph_contracts import (
    CanonicalCollaborativeHeadResponse,
    CollaborativeHeadResponse,
    SavedGraphEdgeModel,
    SavedGraphNodeModel,
    SavedGraphNodeLayoutModel,
)
from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.domain.collaboration import CollaborativeGraphHead
from grafy_core.domain.saved_graphs import (
    SavedGraphDocument,
    GraphPoint,
    GraphPresentationDocument,
    GraphPresentationViewer,
    SavedGraphEdge,
    SavedGraphNode,
    SavedGraphNodeLayout,
)


@pytest.fixture
def head() -> CollaborativeGraphHead:
    return CollaborativeGraphHead(
        workspace_id=UUID(int=1), graph_id=UUID(int=2), room_epoch=UUID(int=3),
        collaboration_sequence=8, checkpoint_sequence=3, checkpoint_revision=2,
        name="Uncheckpointed changes", updated_at=datetime(2026, 9, 9, tzinfo=UTC),
        document=SavedGraphDocument(nodes=tuple(
            SavedGraphNode.model_validate({
                "id": node_id, "kind": "builtin", "operator_id": "example",
                "operator_version": 1, "position": {"x": 0, "y": 0},
                "input_plugs": [{"id": "plug", "port": "input"}],
            }) for node_id in ["node", "source", "target"]
        )),
    )


@pytest.mark.parametrize("kind", ["builtin", "plugin", "module"])
def test_node_conversion_preserves_pin_name_and_copies_nested_config(
    kind: Literal["builtin", "plugin", "module"],
    head: CollaborativeGraphHead,
) -> None:
    node = SavedGraphNode.model_validate(
        {
            "kind": kind,
            "id": "node",
            "operator_id": "example.node",
            "operator_version": 2,
            "config": {"items": [{"name": "Żółw", "enabled": True}], "empty": None},
            "position": {"x": 1, "y": 2},
            "layout": {"width": 300},
            "input_plugs": [{"id": "plug", "port": "items"}],
            "artifact_type_bindings": [
                {
                    "variable": "T",
                    "artifact_type": {"id": "scalar.text", "schema_version": 1},
                }
            ],
            "plugin_release_pin": {
                "scope": "workspace",
                "slug": "example",
                "revision": 3,
            }
            if kind == "plugin"
            else None,
        }
    )
    head.document = SavedGraphDocument(nodes=(node,))
    wire = CollaborativeHeadResponse.from_head(head).nodes[0]
    payload = wire.model_dump(mode="json")

    assert "plugin_release_pin" not in payload
    assert payload["plugin_release"] == (
        {"scope": "workspace", "slug": "example", "revision": 3}
        if kind == "plugin"
        else None
    )
    assert payload["input_plugs"] == [{"id": "plug", "port": "items"}]
    assert payload["artifact_type_bindings"] == [
        {"variable": "T", "artifact_type": {"id": "scalar.text", "schema_version": 1}}
    ]
    assert payload["layout"] == {
        "width": 300,
        "body_height": None,
        "appendix_height": None,
    }
    assert payload["config"] == {
        "items": [{"name": "Żółw", "enabled": True}],
        "empty": None,
    }
    wire.config["items"] = ["changed"]
    assert node.config_dict()["items"] == [{"name": "Żółw", "enabled": True}]
    assert CollaborativeHeadResponse.from_head(head).nodes[0].config["items"] == [
        {"name": "Żółw", "enabled": True}
    ]


def test_edge_conversion_retains_projection_conversion_order_and_routing(head: CollaborativeGraphHead) -> None:
    payload = {
        "id": "edge",
        "enabled": False,
        "from_node": "source",
        "from_port": "output",
        "to_node": "target",
        "to_port": "input",
        "to_plug": "plug",
        "collection_mode": "map",
        "projection": {"path": ["nested", "value"]},
        "conversion_path": [{"id": "one", "version": 1}, {"id": "two", "version": 2}],
        "route_offset": {"x": -5, "y": 10},
    }
    head.document = SavedGraphDocument(nodes=head.document.nodes, edges=(SavedGraphEdge.model_validate(payload),))
    wire = CollaborativeHeadResponse.from_head(head).edges[0]
    assert wire.model_dump(mode="json") == payload


@pytest.fixture
def presentation() -> GraphPresentationDocument:
    return GraphPresentationDocument.model_validate(
        {
            "viewers": [
                {
                    "id": "artifact-viewer-source",
                    "position": {"x": 1, "y": 2},
                    "layout": {"body_height": 150},
                    "mode": "table",
                },
                {"id": "artifact-viewer-target", "position": {"x": 3, "y": 4}},
            ],
            "links": [
                {
                    "id": "artifact-viewer-edge-output",
                    "source_node_id": "node",
                    "source_port_name": "value",
                    "target_viewer_id": "artifact-viewer-source",
                    "projection": {"path": ["value"]},
                    "route_offset": {"x": 5, "y": 6},
                }
            ],
            "bindings": [
                {
                    "id": "artifact-viewer-binding-selection",
                    "source_viewer_id": "artifact-viewer-source",
                    "target_viewer_id": "artifact-viewer-target",
                    "mappings": [{"source_field": "id", "target_field": "selected_id"}],
                    "effects": ["highlight", "filter"],
                }
            ],
            "annotations": [
                {
                    "id": "annotation-note",
                    "kind": "text",
                    "position": {"x": 7, "y": 8},
                    "layout": {"width": 100, "height": 50},
                    "text": "A note",
                    "color": "#123456",
                }
            ],
        }
    )


def test_presentation_round_trip_retains_all_nested_fields_and_is_independent(
    presentation: GraphPresentationDocument,
    head: CollaborativeGraphHead,
) -> None:
    head.document = SavedGraphDocument(nodes=head.document.nodes, presentation=presentation)
    wire = CollaborativeHeadResponse.from_head(head).presentation
    assert wire.model_dump(mode="json") == presentation.model_dump(mode="json")
    assert GraphPresentationDocument.model_validate(wire.model_dump()) == presentation
    wire.viewers[0].position.x = 999
    assert presentation.viewers[0].position.x == 1
    assert GraphPresentationDocument.model_validate(wire.model_dump()).viewers[0].position.x == 999


def test_presentation_conversion_still_enforces_domain_relationships(
    presentation: GraphPresentationDocument,
    head: CollaborativeGraphHead,
) -> None:
    head.document = SavedGraphDocument(nodes=head.document.nodes, presentation=presentation)
    wire = CollaborativeHeadResponse.from_head(head).presentation
    wire.bindings[0].target_viewer_id = "artifact-viewer-missing"
    with pytest.raises(ValidationError, match="references missing target viewer"):
        GraphPresentationDocument.model_validate(wire.model_dump())


@pytest.mark.parametrize("model", [SavedGraphEdge, SavedGraphEdgeModel])
@pytest.mark.parametrize(
    ("conversion_fields", "expected"),
    [
        ({}, []),
        ({"conversion": None}, []),
        ({"conversion": {"id": "one", "version": 1}}, [{"id": "one", "version": 1}]),
        ({"conversion_path": []}, []),
        (
            {"conversion_path": [{"id": "one", "version": 1}, {"id": "two", "version": 2}]},
            [{"id": "one", "version": 1}, {"id": "two", "version": 2}],
        ),
    ],
)
def test_edge_models_normalize_legacy_conversion_without_mutating_input(
    model: type[SavedGraphEdge] | type[SavedGraphEdgeModel],
    conversion_fields: dict[str, object],
    expected: list[dict[str, object]],
) -> None:
    payload = {
        "id": "edge",
        "from_node": "source",
        "from_port": "output",
        "to_node": "target",
        "to_port": "input",
        **conversion_fields,
    }
    original = dict(payload)
    edge = model.model_validate(MappingProxyType(payload))
    serialized = edge.model_dump(mode="json")
    assert serialized["conversion_path"] == expected
    assert "conversion" not in serialized
    assert payload == original
    assert model.model_validate_json(edge.model_dump_json()) == edge


@pytest.mark.parametrize("model", [SavedGraphEdge, SavedGraphEdgeModel])
@pytest.mark.parametrize("conversion", [None, {"id": "one", "version": 1}])
def test_edge_models_reject_both_conversion_forms_even_when_empty(
    model: type[SavedGraphEdge] | type[SavedGraphEdgeModel],
    conversion: object,
) -> None:
    with pytest.raises(ValidationError, match="cannot declare both conversion and conversion_path"):
        model.model_validate({
            "id": "edge",
            "from_node": "source",
            "from_port": "output",
            "to_node": "target",
            "to_port": "input",
            "conversion": conversion,
            "conversion_path": [],
        })


@pytest.mark.parametrize("model", [SavedGraphNodeLayout, SavedGraphNodeLayoutModel])
@pytest.mark.parametrize("dimension", ["width", "body_height", "appendix_height"])
def test_graph_layout_accepts_each_dimension_independently(
    model: type[SavedGraphNodeLayout] | type[SavedGraphNodeLayoutModel],
    dimension: str,
) -> None:
    assert model.model_validate({dimension: 300}).model_dump()[dimension] == 300


@pytest.mark.parametrize("model", [SavedGraphNodeLayout, SavedGraphNodeLayoutModel])
@pytest.mark.parametrize("payload", [{}, {"width": None, "body_height": None, "appendix_height": None}])
def test_graph_layout_rejects_absent_dimensions(
    model: type[SavedGraphNodeLayout] | type[SavedGraphNodeLayoutModel],
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="must set at least one of width"):
        model.model_validate(payload)


@pytest.mark.parametrize("model", [SavedGraphNode, SavedGraphNodeModel])
@pytest.mark.parametrize("kind", ["builtin", "plugin", "module"])
@pytest.mark.parametrize("has_pin", [False, True])
def test_node_models_require_release_pins_only_for_plugins(
    model: type[SavedGraphNode] | type[SavedGraphNodeModel],
    kind: str,
    has_pin: bool,
) -> None:
    pin_field = "plugin_release_pin" if model is SavedGraphNode else "plugin_release"
    payload = {
        "id": "node", "kind": kind, "operator_id": "example", "operator_version": 1,
        "position": {"x": 0, "y": 0},
        pin_field: {"scope": "system", "slug": "example", "revision": 1} if has_pin else None,
    }
    if (kind == "plugin") == has_pin:
        assert model.model_validate(payload).kind == kind
    else:
        message = "Plugin node must pin an exact Plugin release" if kind == "plugin" else f"{kind} node cannot carry a Plugin release pin"
        with pytest.raises(ValidationError, match=message):
            model.model_validate(payload)


def test_head_adapter_preserves_metadata_and_empty_document(head: CollaborativeGraphHead) -> None:
    head.document = SavedGraphDocument()
    canonical = CanonicalCollaborativeHeadResponse.from_head(head)
    legacy = CollaborativeHeadResponse.from_head(head)
    assert legacy.model_dump(exclude={"nodes", "edges", "presentation"}) == canonical.model_dump(exclude={"document"})
    assert legacy.collaboration_sequence == 8
    assert legacy.checkpoint_sequence == 3
    assert legacy.checkpoint_revision == 2
    assert legacy.nodes == []
    assert legacy.edges == []
    assert legacy.presentation.model_dump(mode="json") == {"viewers": [], "links": [], "bindings": [], "annotations": []}
    payload = legacy.model_dump(mode="json")
    assert "document" not in payload
    assert "schema_version" not in payload
    assert "workspace_id" not in payload
    assert CollaborativeHeadResponse.model_validate_json(legacy.model_dump_json()) == legacy


def test_artifact_card_reference_survives_head_transport(
    head: CollaborativeGraphHead,
) -> None:
    reference = ArtifactRef.from_key(
        artifact_id=UUID(int=77),
        key=ArtifactTypeKey("table.data", 1),
        content_hash="b" * 64,
    )
    head.document = head.document.with_topology(
        presentation=GraphPresentationDocument(
            viewers=(
                GraphPresentationViewer(
                    id="artifact-viewer-card",
                    position=GraphPoint(x=1.0, y=2.0),
                    artifact_ref=reference,
                ),
            ),
        ),
    )

    canonical = CanonicalCollaborativeHeadResponse.from_head(head)
    legacy = CollaborativeHeadResponse.from_head(head)

    assert canonical.document.presentation.viewers[0].artifact_ref == reference
    assert legacy.presentation.viewers[0].artifact_ref == reference
    assert (
        legacy.model_dump(mode="json")["presentation"]["viewers"][0][
            "artifact_ref"
        ]["artifact_type"]
        == "table.data"
    )
