"""The one Project head transport carries the canonical Project document."""

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from grafy_api.project_contracts import ProjectHeadResponse
from grafy_core.artifacts import ArtifactRef, ArtifactTypeKey
from grafy_core.domain.collaboration import ProjectHead
from grafy_core.domain.graph_documents import (
    GraphDocument,
    GraphNode,
    GraphPoint,
    GraphPresentationDocument,
    GraphPresentationViewer,
)
from grafy_core.kernel.project import GraphDefinition, ProjectDocument


def _graph(
    graph_id: str = "main",
    *,
    document: GraphDocument | None = None,
    name: str = "Main",
) -> GraphDefinition:
    return GraphDefinition(
        id=graph_id,
        name=name,
        document=(
            document
            if document is not None
            else GraphDocument(
                nodes=tuple(
                    GraphNode.model_validate(
                        {
                            "id": node_id,
                            "kind": "builtin",
                            "operator_id": "example",
                            "operator_version": 1,
                            "position": {"x": 0, "y": 0},
                            "input_plugs": [{"id": "plug", "port": "input"}],
                        }
                    )
                    for node_id in ["source", "target"]
                )
            )
        ),
    )


@pytest.fixture
def head() -> ProjectHead:
    return ProjectHead(
        workspace_id=UUID(int=1),
        project_id=UUID(int=2),
        room_epoch=UUID(int=3),
        collaboration_sequence=8,
        checkpoint_sequence=3,
        checkpoint_revision=2,
        name="Uncheckpointed changes",
        updated_at=datetime(2026, 9, 9, tzinfo=UTC),
        document=ProjectDocument(graphs=(_graph(),)),
    )


def test_head_serializes_metadata_and_the_document_only(
    head: ProjectHead,
) -> None:
    head.document = ProjectDocument(graphs=(_graph(document=GraphDocument()),))
    payload = ProjectHeadResponse.from_head(head).model_dump(mode="json")

    assert payload["project_id"] == str(UUID(int=2))
    assert payload["room_epoch"] == str(UUID(int=3))
    assert payload["collaboration_sequence"] == 8
    assert payload["checkpoint_sequence"] == 3
    assert payload["checkpoint_revision"] == 2
    assert payload["name"] == "Uncheckpointed changes"
    # The Workspace is in the path the caller used, never in what it reads back.
    assert "workspace_id" not in payload
    assert set(payload["document"]) == {"graphs"}
    graph = payload["document"]["graphs"][0]
    assert set(graph) == {"id", "name", "document", "refresh_generations"}
    assert set(graph["document"]) == {
        "schema_version",
        "nodes",
        "edges",
        "origins",
        "presentation",
        "agents",
    }
    assert graph["document"]["nodes"] == []
    # An Agent on the canvas travels with the Graph it was placed on, so a head carries them.
    assert graph["document"]["agents"] == []
    assert graph["document"]["presentation"] == {
        "viewers": [],
        "links": [],
        "bindings": [],
        "annotations": [],
    }


def test_head_round_trips_every_graph_of_the_project(head: ProjectHead) -> None:
    head.document = ProjectDocument(graphs=(_graph(), _graph("notes", name="Notes")))

    wire = ProjectHeadResponse.from_head(head)

    assert ProjectHeadResponse.model_validate_json(wire.model_dump_json()) == wire
    assert wire.document == head.document
    assert [graph.id for graph in wire.document.graphs] == ["main", "notes"]
    assert [graph.name for graph in wire.document.graphs] == ["Main", "Notes"]


def test_head_carries_a_nested_graph_unchanged(head: ProjectHead) -> None:
    """The Project transport adds nothing to a Graph document and loses nothing."""

    node = GraphNode.model_validate(
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
    reference = ArtifactRef.from_key(
        artifact_id=UUID(int=77),
        key=ArtifactTypeKey("table.data", 1),
        content_hash="b" * 64,
    )
    document = GraphDocument(nodes=(node,)).with_topology(
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
    head.document = ProjectDocument(graphs=(_graph(document=document),))

    wire = ProjectHeadResponse.from_head(head)
    carried = wire.document.get_graph("main").document
    payload = wire.model_dump(mode="json")

    assert carried == document
    assert carried.nodes[0].config_dict() == {
        "items": [{"name": "Żółw", "enabled": True}],
        "empty": None,
    }
    assert carried.presentation.viewers[0].artifact_ref == reference
    assert (
        payload["document"]["graphs"][0]["document"]["presentation"]["viewers"][0][
            "artifact_ref"
        ]["artifact_type"]
        == "table.data"
    )


def test_head_rejects_a_graph_document_with_plugin_node_identity(
    head: ProjectHead,
) -> None:
    with pytest.raises(ValidationError):
        GraphDocument.model_validate(
            {
                "nodes": [
                    {
                        "id": "node",
                        "kind": "builtin",
                        "operator_id": "example",
                        "operator_version": 1,
                        "position": {"x": 0, "y": 0},
                        "plugin_release": {
                            "scope": "system",
                            "slug": "example",
                            "revision": 1,
                        },
                    }
                ],
            }
        )


def test_head_names_the_project_it_belongs_to(head: ProjectHead) -> None:
    """One Project, one room: the head says which Project it is the state of."""

    wire = ProjectHeadResponse.from_head(head)

    assert wire.project_id == head.project_id
    assert ProjectHeadResponse.model_fields["document"].annotation is ProjectDocument
