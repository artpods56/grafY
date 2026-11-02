"""The one collaborative head transport carries the canonical saved graph document."""

from datetime import UTC, datetime
from types import MappingProxyType
from uuid import UUID

import pytest
from grafy_api.graph_contracts import CollaborativeHeadResponse
from grafy_core.artifacts import ArtifactRef, ArtifactRefSequence, ArtifactTypeKey
from grafy_core.domain.collaboration import CollaborativeGraphHead
from grafy_core.domain.saved_graphs import (
    SAVED_GRAPH_SCHEMA_VERSION,
    GraphPoint,
    GraphPresentationDocument,
    GraphPresentationViewer,
    SavedGraphDocument,
    SavedGraphEdge,
    SavedGraphNode,
    SavedGraphOrigin,
)
from pydantic import ValidationError


@pytest.fixture
def head() -> CollaborativeGraphHead:
    return CollaborativeGraphHead(
        workspace_id=UUID(int=1),
        graph_id=UUID(int=2),
        room_epoch=UUID(int=3),
        collaboration_sequence=8,
        checkpoint_sequence=3,
        checkpoint_revision=2,
        name="Uncheckpointed changes",
        updated_at=datetime(2026, 9, 9, tzinfo=UTC),
        document=SavedGraphDocument(
            nodes=tuple(
                SavedGraphNode.model_validate(
                    {
                        "id": node_id,
                        "kind": "builtin",
                        "operator_id": "example",
                        "operator_version": 1,
                        "position": {"x": 0, "y": 0},
                        "input_plugs": [{"id": "plug", "port": "input"}],
                    }
                )
                for node_id in ["node", "source", "target"]
            )
        ),
    )


def test_head_serializes_metadata_and_the_document_only(
    head: CollaborativeGraphHead,
) -> None:
    head.document = SavedGraphDocument()
    payload = CollaborativeHeadResponse.from_head(head).model_dump(mode="json")

    assert payload["graph_id"] == str(UUID(int=2))
    assert payload["room_epoch"] == str(UUID(int=3))
    assert payload["collaboration_sequence"] == 8
    assert payload["checkpoint_sequence"] == 3
    assert payload["checkpoint_revision"] == 2
    assert payload["name"] == "Uncheckpointed changes"
    assert "workspace_id" not in payload
    assert set(payload["document"]) == {
        "schema_version",
        "nodes",
        "edges",
        "origins",
        "presentation",
    }
    assert payload["document"]["schema_version"] == SAVED_GRAPH_SCHEMA_VERSION
    assert payload["document"]["nodes"] == []
    assert payload["document"]["origins"] == []
    assert payload["document"]["presentation"] == {
        "viewers": [],
        "links": [],
        "bindings": [],
        "annotations": [],
    }


def test_head_round_trips_the_document(head: CollaborativeGraphHead) -> None:
    wire = CollaborativeHeadResponse.from_head(head)
    assert CollaborativeHeadResponse.model_validate_json(wire.model_dump_json()) == wire
    assert wire.document == head.document


def test_head_node_config_is_a_copy_the_document_does_not_share(
    head: CollaborativeGraphHead,
) -> None:
    node = SavedGraphNode.model_validate(
        {
            "kind": "builtin",
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
        }
    )
    head.document = SavedGraphDocument(nodes=(node,))

    payload = CollaborativeHeadResponse.from_head(head).document.nodes[0]

    assert payload.config_dict() == {
        "items": [{"name": "Żółw", "enabled": True}],
        "empty": None,
    }
    assert [(plug.id, plug.port) for plug in payload.input_plugs] == [("plug", "items")]
    assert payload.artifact_type_bindings[0].variable == "T"
    assert node.config_dict()["items"] == [{"name": "Żółw", "enabled": True}]


def test_head_keeps_edge_projection_conversion_order_and_routing(
    head: CollaborativeGraphHead,
) -> None:
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
    edge = SavedGraphEdge.model_validate(MappingProxyType(payload))
    assert edge.model_dump(mode="json") == payload
    assert SavedGraphEdge.model_validate_json(edge.model_dump_json()) == edge


@pytest.mark.parametrize(
    "conversion_fields",
    [
        {"conversion": None},
        {"conversion": {"id": "one", "version": 1}},
        {"conversion": {"id": "one", "version": 1}, "conversion_path": []},
    ],
)
def test_edge_rejects_the_singular_conversion_key(
    conversion_fields: dict[str, object],
) -> None:
    with pytest.raises(ValidationError, match="conversion"):
        SavedGraphEdge.model_validate(
            {
                "id": "edge",
                "from_node": "source",
                "from_port": "output",
                "to_node": "target",
                "to_port": "input",
                **conversion_fields,
            }
        )


def test_head_keeps_an_origin_reference_and_conversion_path(
    head: CollaborativeGraphHead,
) -> None:
    payload = {
        "id": "origin",
        "to_node": "target",
        "to_port": "input",
        "to_plug": "plug",
        "value": {
            "artifact_id": "00000000-0000-0000-0000-0000000000a1",
            "artifact_type": "scalar.text",
            "schema_version": 1,
            "content_hash": None,
        },
        "collection_mode": "direct",
        "conversion_path": [{"id": "one", "version": 1}, {"id": "two", "version": 2}],
    }
    origin = SavedGraphOrigin.model_validate(payload)
    head.document = SavedGraphDocument(
        nodes=head.document.nodes,
        origins=(origin,),
    )

    wire = CollaborativeHeadResponse.from_head(head).document.origins[0]

    assert wire.model_dump(mode="json") == payload


def test_head_keeps_an_artifact_ref_sequence_on_an_origin(
    head: CollaborativeGraphHead,
) -> None:
    sequence = ArtifactRefSequence(
        artifact_type="file.jpg",
        schema_version=1,
        item_refs=[
            ArtifactRef(
                artifact_id=UUID(int=81),
                artifact_type="file.jpg",
                schema_version=1,
            ),
            ArtifactRef(
                artifact_id=UUID(int=82),
                artifact_type="file.jpg",
                schema_version=1,
            ),
        ],
    )
    head.document = head.document.with_topology(
        origins=(
            SavedGraphOrigin(
                id="origin",
                to_node="target",
                to_port="input",
                value=sequence,
            ),
        ),
    )

    wire = CollaborativeHeadResponse.from_head(head).document.origins[0]

    assert wire.value == sequence


def test_head_keeps_presentation_and_artifact_card_references(
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
            annotations=(),
        ),
    )

    wire = CollaborativeHeadResponse.from_head(head)
    payload = wire.model_dump(mode="json")

    assert wire.document.presentation.viewers[0].artifact_ref == reference
    assert (
        payload["document"]["presentation"]["viewers"][0]["artifact_ref"][
            "artifact_type"
        ]
        == "table.data"
    )


@pytest.mark.parametrize(
    "node_fields",
    [
        {"kind": "plugin"},
        {"plugin_release_pin": {"scope": "system", "slug": "example", "revision": 1}},
        {"plugin_release": {"scope": "system", "slug": "example", "revision": 1}},
    ],
)
def test_head_rejects_a_document_with_plugin_node_identity(
    node_fields: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        SavedGraphDocument.model_validate(
            {
                "schema_version": SAVED_GRAPH_SCHEMA_VERSION,
                "nodes": [
                    {
                        "id": "node",
                        "kind": "builtin",
                        "operator_id": "example",
                        "operator_version": 1,
                        "position": {"x": 0, "y": 0},
                        **node_fields,
                    }
                ],
            }
        )
