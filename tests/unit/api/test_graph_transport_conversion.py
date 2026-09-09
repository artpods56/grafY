"""Contracts for canonical graph values crossing the compatibility transport."""

from types import MappingProxyType
from typing import Literal

import pytest
from pydantic import ValidationError

from grafy_api.graph_contracts import (
    GraphPresentationDocumentModel,
    SavedGraphEdgeModel,
    SavedGraphNodeModel,
    SavedGraphNodeLayoutModel,
)
from grafy_core.domain.saved_graphs import (
    GraphPresentationDocument,
    SavedGraphEdge,
    SavedGraphNode,
    SavedGraphNodeLayout,
)


@pytest.mark.parametrize("kind", ["builtin", "plugin", "module"])
def test_node_conversion_preserves_pin_name_and_copies_nested_config(
    kind: Literal["builtin", "plugin", "module"],
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
    wire = SavedGraphNodeModel.from_domain(node)
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
    assert SavedGraphNodeModel.from_domain(node).config["items"] == [
        {"name": "Żółw", "enabled": True}
    ]


def test_edge_conversion_retains_projection_conversion_order_and_routing() -> None:
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
    wire = SavedGraphEdgeModel.from_domain(SavedGraphEdge.model_validate(payload))
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
) -> None:
    wire = GraphPresentationDocumentModel.from_domain(presentation)
    assert wire.model_dump(mode="json") == presentation.model_dump(mode="json")
    assert wire.to_domain() == presentation
    wire.viewers[0].position.x = 999
    assert presentation.viewers[0].position.x == 1
    assert wire.to_domain().viewers[0].position.x == 999


def test_presentation_conversion_still_enforces_domain_relationships(
    presentation: GraphPresentationDocument,
) -> None:
    wire = GraphPresentationDocumentModel.from_domain(presentation)
    wire.bindings[0].target_viewer_id = "artifact-viewer-missing"
    with pytest.raises(ValidationError, match="references missing target viewer"):
        wire.to_domain()


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
