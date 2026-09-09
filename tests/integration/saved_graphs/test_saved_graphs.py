import asyncio
from typing import cast
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from grafy_api.v1.models import ArtifactTypeBindingModel, ArtifactTypeKeyResponse
from grafy_api.graph_contracts import (
    CheckpointGraphRequest,
    CopyExactHeadRequest,
    CreateSavedGraphRequest,
    GraphPointModel,
    SavedGraphConversionModel,
    SavedGraphEdgeModel,
    SavedGraphInputPlugModel,
    SavedGraphNodeLayoutModel,
    SavedGraphNodeModel,
    SavedGraphProjectionModel,
    SubmitGraphCommandRequest,
    UpdateSavedGraphRequest,
)
from grafy_core.domain.collaboration import RenameGraphCommand
from grafy_core.domain.identity import ActorContext
from grafy_core.domain.saved_graphs import SavedGraphDocument

from tests.support.clients import GrafyApi
from tests.support.identity import TEST_USER_ID, WORKSPACE_ID


def _graph_nodes() -> list[SavedGraphNodeModel]:
    return [
        SavedGraphNodeModel(
            kind="builtin",
            id="source",
            operator_id="plugin.source",
            operator_version=1,
            config={"text": "draft"},
            position=GraphPointModel(x=10.0, y=20.0),
            layout=SavedGraphNodeLayoutModel(width=420.0, body_height=180.0),
        ),
        SavedGraphNodeModel(
            kind="builtin",
            id="target",
            operator_id="plugin.target",
            operator_version=1,
            config={},
            position=GraphPointModel(x=300.0, y=20.0),
            layout=SavedGraphNodeLayoutModel(appendix_height=320.0),
            input_plugs=[
                SavedGraphInputPlugModel(id="primary-value", port="value"),
            ],
            artifact_type_bindings=[
                ArtifactTypeBindingModel(
                    variable="T",
                    artifact_type=ArtifactTypeKeyResponse(
                        id="image.raster", schema_version=1
                    ),
                )
            ],
        ),
    ]


def _graph_edges() -> list[SavedGraphEdgeModel]:
    return [
        SavedGraphEdgeModel(
            id="source-to-target",
            from_node="source",
            from_port="result",
            to_node="target",
            to_port="value",
            to_plug="primary-value",
            collection_mode="map",
            projection=SavedGraphProjectionModel(path=["payload", "text"]),
            conversion_path=[
                SavedGraphConversionModel(id="example.text.normalize", version=2),
            ],
            route_offset=GraphPointModel(x=5.0, y=-3.0),
        ),
    ]


def _graph_document(
    *,
    nodes: list[SavedGraphNodeModel] | None = None,
    edges: list[SavedGraphEdgeModel] | None = None,
) -> SavedGraphDocument:
    effective_nodes = nodes if nodes is not None else _graph_nodes()
    effective_edges = edges if edges is not None else _graph_edges()
    serialized_nodes = []
    for node in effective_nodes:
        serialized = node.model_dump(mode="json")
        serialized["plugin_release_pin"] = serialized.pop("plugin_release")
        serialized_nodes.append(serialized)
    return SavedGraphDocument.model_validate(
        {
            "nodes": serialized_nodes,
            "edges": [edge.model_dump(mode="json") for edge in effective_edges],
        }
    )


def _graph_request(name: str = "Draft graph") -> CreateSavedGraphRequest:
    return CreateSavedGraphRequest(
        name=name,
        document=_graph_document(),
    )


def _update_request(name: str, expected_revision: int) -> UpdateSavedGraphRequest:
    return UpdateSavedGraphRequest(
        name=name,
        expected_revision=expected_revision,
        document=_graph_document(),
    )


def _raw_graph_payload(name: str = "Draft graph") -> dict[str, object]:
    """A hand-built graph body for boundaries the request models reject."""
    return {
        "name": name,
        "nodes": [
            {
                "kind": "builtin",
                "id": "source",
                "operator_id": "plugin.source",
                "operator_version": 1,
                "config": {"text": "draft"},
                "position": {"x": 10.0, "y": 20.0},
                "layout": {
                    "width": 420.0,
                    "body_height": 180.0,
                    "appendix_height": None,
                },
                "input_plugs": [],
                "artifact_type_bindings": [],
            },
            {
                "kind": "builtin",
                "id": "target",
                "operator_id": "plugin.target",
                "operator_version": 1,
                "config": {},
                "position": {"x": 300.0, "y": 20.0},
                "layout": {
                    "width": None,
                    "body_height": None,
                    "appendix_height": 320.0,
                },
                "input_plugs": [{"id": "primary-value", "port": "value"}],
                "artifact_type_bindings": [
                    {
                        "variable": "T",
                        "artifact_type": {
                            "id": "image.raster",
                            "schema_version": 1,
                        },
                    }
                ],
            },
        ],
        "edges": [
            {
                "id": "source-to-target",
                "enabled": True,
                "from_node": "source",
                "from_port": "result",
                "to_node": "target",
                "to_port": "value",
                "to_plug": "primary-value",
                "collection_mode": "map",
                "projection": {"path": ["payload", "text"]},
                "conversion_path": [
                    {"id": "example.text.normalize", "version": 2},
                ],
                "route_offset": {"x": 5.0, "y": -3.0},
            },
        ],
        "presentation": {
            "viewers": [],
            "links": [],
            "bindings": [],
            "annotations": [],
        },
    }


def _canonical_raw_graph_payload(name: str = "Draft graph") -> dict[str, object]:
    payload = _raw_graph_payload(name)
    return {
        "name": payload.pop("name"),
        "document": {
            "schema_version": 6,
            "nodes": payload.pop("nodes"),
            "edges": payload.pop("edges"),
            "presentation": payload.pop("presentation"),
        },
    }


def test_create_accepts_the_canonical_saved_graph_document(
    builtin_client: TestClient,
) -> None:
    payload = _canonical_raw_graph_payload("Canonical graph")
    document = cast(dict[str, object], payload["document"])
    for node in cast(list[dict[str, object]], document["nodes"]):
        node["plugin_release_pin"] = None
    payload["document"] = document

    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs",
        json=payload,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Canonical graph"
    assert body["document"] == document
    assert "nodes" not in body
    assert "edges" not in body


def test_saved_graph_crud_round_trip(builtin_client: TestClient) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    create_response = graphs.create(_graph_request("  Parish index draft  "))

    assert create_response.status_code == 201
    created = create_response.json()
    graph_id = UUID(created["id"])
    assert created["name"] == "Parish index draft"
    assert created["revision"] == 1
    document = created["document"]
    assert document["schema_version"] == 6
    assert len(document["nodes"]) == 2
    assert len(document["edges"]) == 1
    assert document["nodes"][0]["input_plugs"] == []
    assert document["nodes"][0]["layout"] == {
        "width": 420.0,
        "body_height": 180.0,
        "appendix_height": None,
    }
    assert document["nodes"][1]["input_plugs"] == [
        {"id": "primary-value", "port": "value"}
    ]
    assert document["nodes"][1]["layout"] == {
        "width": None,
        "body_height": None,
        "appendix_height": 320.0,
    }
    assert document["nodes"][1]["artifact_type_bindings"] == [
        {
            "variable": "T",
            "artifact_type": {
                "id": "image.raster",
                "schema_version": 1,
            },
        }
    ]
    assert document["edges"][0]["to_plug"] == "primary-value"
    assert document["edges"][0]["enabled"] is True
    assert document["edges"][0]["projection"] == {"path": ["payload", "text"]}
    assert document["edges"][0]["conversion_path"] == [
        {
            "id": "example.text.normalize",
            "version": 2,
        }
    ]
    assert "conversion" not in document["edges"][0]

    get_response = graphs.get(graph_id)
    assert get_response.status_code == 200
    assert get_response.json() == created

    list_response = graphs.list()
    assert list_response.status_code == 200
    assert list_response.json() == {
        "graphs": [
            {
                "id": str(graph_id),
                "name": "Parish index draft",
                "revision": 1,
                "node_count": 2,
                "edge_count": 1,
                "updated_at": created["updated_at"],
            }
        ]
    }

    update_response = graphs.update(
        graph_id, _update_request("Updated draft", expected_revision=1)
    )
    assert update_response.status_code == 200
    updated = update_response.json()
    assert updated["id"] == str(graph_id)
    assert updated["name"] == "Updated draft"
    assert updated["revision"] == 2
    assert updated["created_at"] == created["created_at"]

    delete_response = graphs.delete(graph_id, expected_revision=updated["revision"])
    assert delete_response.status_code == 204
    assert delete_response.content == b""
    assert graphs.get(graph_id).status_code == 404


def test_create_rejects_structurally_invalid_graph(builtin_client: TestClient) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    payload = _canonical_raw_graph_payload()
    document = cast(dict[str, object], payload["document"])
    document["edges"] = [
        {
            "id": "dangling",
            "from_node": "source",
            "from_port": "result",
            "to_node": "missing",
            "to_port": "value",
        }
    ]

    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs", json=payload
    )

    assert response.status_code == 422
    assert "missing target node missing" in str(response.json())
    assert graphs.list().json() == {"graphs": []}


def test_create_rejects_ambiguous_conversion_fields(
    builtin_client: TestClient,
) -> None:
    payload = _canonical_raw_graph_payload()
    document = cast(dict[str, object], payload["document"])
    edge = cast(list[dict[str, object]], document["edges"])[0]
    edge["conversion"] = edge["conversion_path"][0]

    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs", json=payload
    )

    assert response.status_code == 422
    assert "both conversion and conversion_path" in str(response.json())


def test_create_rejects_duplicate_artifact_type_binding_variables(
    builtin_client: TestClient,
) -> None:
    payload = _canonical_raw_graph_payload()
    document = cast(dict[str, object], payload["document"])
    nodes = cast(list[dict[str, object]], document["nodes"])
    target = nodes[1]
    bindings = cast(list[dict[str, object]], target["artifact_type_bindings"])
    bindings.append(
        {
            "variable": "T",
            "artifact_type": {
                "id": "scalar.text",
                "schema_version": 1,
            },
        }
    )

    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs", json=payload
    )

    assert response.status_code == 422
    assert "binding variables must be unique" in str(response.json())


def test_saved_graph_preserves_conversion_path_order(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    edges = _graph_edges()
    expected_conversion_path = [
        {"id": "example.text.normalize", "version": 2},
        {"id": "example.text.finalize", "version": 7},
    ]
    edges[0].conversion_path = [
        SavedGraphConversionModel(id="example.text.normalize", version=2),
        SavedGraphConversionModel(id="example.text.finalize", version=7),
    ]

    create_response = graphs.create(
        CreateSavedGraphRequest(
            name="Conversion path",
            document=_graph_document(edges=edges),
        )
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["document"]["edges"][0]["conversion_path"] == (
        expected_conversion_path
    )
    loaded = graphs.get(UUID(created["id"]))
    assert loaded.status_code == 200
    assert loaded.json()["document"]["edges"][0]["conversion_path"] == (
        expected_conversion_path
    )


def test_saved_graph_preserves_disabled_edges(builtin_client: TestClient) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    edges = _graph_edges()
    edges[0].enabled = False

    create_response = graphs.create(
        CreateSavedGraphRequest(
            name="Disabled edge",
            document=_graph_document(edges=edges),
        )
    )

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["document"]["edges"][0]["enabled"] is False
    loaded = graphs.get(UUID(created["id"]))
    assert loaded.status_code == 200
    assert loaded.json()["document"]["edges"][0]["enabled"] is False


def test_update_requires_positive_expected_revision(builtin_client: TestClient) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    created = graphs.create(_graph_request()).json()
    payload = _canonical_raw_graph_payload("Invalid revision")
    payload["expected_revision"] = 0

    response = builtin_client.put(
        f"/v1/workspaces/00000000-0000-0000-0000-000000000007/graphs/{created['id']}",
        json=payload,
    )

    assert response.status_code == 422


def test_missing_saved_graph_returns_not_found_for_crud_operations(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    graph_id = UUID("00000000-0000-0000-0000-000000000404")
    get_response = graphs.get(graph_id)
    update_response = graphs.update(
        graph_id, _update_request("Draft graph", expected_revision=1)
    )
    delete_response = graphs.delete(graph_id, expected_revision=1)

    assert get_response.status_code == 404
    assert update_response.status_code == 404
    assert delete_response.status_code == 404
    assert str(graph_id) in get_response.json()["detail"]


def test_stale_update_returns_revision_conflict(builtin_client: TestClient) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    created = graphs.create(_graph_request()).json()
    graph_id = UUID(created["id"])

    assert (
        graphs.update(
            graph_id, _update_request("First update", expected_revision=1)
        ).status_code
        == 200
    )
    conflict_response = graphs.update(
        graph_id, _update_request("Stale update", expected_revision=1)
    )

    assert conflict_response.status_code == 409
    assert "expected 1" in conflict_response.json()["detail"]
    assert "current revision is 2" in conflict_response.json()["detail"]


def test_stale_delete_returns_revision_conflict_and_preserves_graph(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    created = graphs.create(_graph_request()).json()
    graph_id = UUID(created["id"])
    updated = graphs.update(
        graph_id, _update_request("Newer graph", expected_revision=created["revision"])
    ).json()

    response = graphs.delete(graph_id, expected_revision=created["revision"])

    assert response.status_code == 409
    assert "current revision is 2" in response.json()["detail"]
    assert graphs.get(graph_id).json() == updated


def test_name_length_is_checked_after_whitespace_normalization(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    response = graphs.create(_graph_request("x" * 160 + " "))

    assert response.status_code == 201
    assert response.json()["name"] == "x" * 160


def test_http_create_bootstraps_collaborative_head(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    response = graphs.create(_graph_request("Bootstrapped"))
    assert response.status_code == 201
    created = response.json()
    graph_id = UUID(created["id"])
    assert created["revision"] == 1

    head = graphs.get_head_ok(graph_id)

    assert head.collaboration_sequence == 1
    assert head.checkpoint_sequence == 1
    assert head.checkpoint_revision == 1
    assert head.name == "Bootstrapped"


def test_http_replace_resets_collaborative_epoch_when_checkpointed(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    created = graphs.create(_graph_request("Before replace")).json()
    graph_id = UUID(created["id"])
    prior_head = graphs.get_head_ok(graph_id)
    prior_epoch = prior_head.room_epoch

    response = graphs.update(
        graph_id,
        _update_request("After replace", expected_revision=created["revision"]),
    )

    assert response.status_code == 200
    assert response.json()["revision"] == 2
    assert response.json()["name"] == "After replace"

    head = graphs.get_head_ok(graph_id)
    assert head.room_epoch != prior_epoch
    assert head.collaboration_sequence == 0
    assert head.checkpoint_sequence == 0
    assert head.checkpoint_revision == 2
    assert head.name == "After replace"


def test_http_replace_rejects_uncheckpointed_head(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    created = graphs.create(_graph_request("Live draft")).json()
    graph_id = UUID(created["id"])
    collaboration = builtin_client.app.state.resources.collaboration
    head = graphs.get_head_ok(graph_id)
    asyncio.run(
        collaboration.accept_command(
            actor=ActorContext(
                user_id=TEST_USER_ID,
                credential_reference="test-session",
            ),
            workspace_id=WORKSPACE_ID,
            graph_id=graph_id,
            command_id=uuid4(),
            observed_sequence=head.collaboration_sequence,
            observed_room_epoch=head.room_epoch,
            command=RenameGraphCommand(
                name="Uncheckpointed", expected_name="Live draft"
            ),
        )
    )

    response = graphs.update(
        graph_id, _update_request("Should fail", expected_revision=created["revision"])
    )

    assert response.status_code == 409
    assert "uncheckpointed" in response.json()["detail"].lower()


def test_http_delete_removes_collaborative_head(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    created = graphs.create(_graph_request("Delete me")).json()
    graph_id = UUID(created["id"])

    response = graphs.delete(graph_id, expected_revision=created["revision"])
    assert response.status_code == 204
    assert graphs.get(graph_id).status_code == 404

    assert graphs.get_head(graph_id).status_code == 404


def test_http_live_head_command_checkpoint_and_aware_delete(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    created = graphs.create(_graph_request("Command graph")).json()
    graph_id = UUID(created["id"])

    head_response = graphs.get_head(graph_id)
    assert head_response.status_code == 200
    head = head_response.json()
    assert head["name"] == "Command graph"
    assert head["collaboration_sequence"] == 1
    assert head["checkpoint_sequence"] == 1

    command_response = graphs.submit_command(
        graph_id,
        SubmitGraphCommandRequest(
            command_id=uuid4(),
            room_epoch=UUID(head["room_epoch"]),
            observed_sequence=head["collaboration_sequence"],
            command=RenameGraphCommand(
                name="Renamed live", expected_name="Command graph"
            ),
        ),
    )
    assert command_response.status_code == 200
    command_payload = command_response.json()
    assert command_payload["head"]["name"] == "Renamed live"
    assert command_payload["head"]["collaboration_sequence"] == 2
    assert command_payload["receipt"]["outcome"] == "accepted"
    assert command_payload["receipt"]["deduplicated"] is False

    checkpoint_response = graphs.checkpoint(
        graph_id,
        CheckpointGraphRequest(
            expected_room_epoch=UUID(command_payload["head"]["room_epoch"]),
            expected_sequence=command_payload["head"]["collaboration_sequence"],
        ),
    )
    assert checkpoint_response.status_code == 200
    assert checkpoint_response.json()["saved_revision"] == 2
    assert checkpoint_response.json()["head"]["checkpoint_sequence"] == 2

    saved = graphs.get(graph_id).json()
    assert saved["name"] == "Renamed live"
    assert saved["revision"] == 2

    # Leave an uncheckpointed command, then discard with exact-head delete.
    pending = graphs.submit_command(
        graph_id,
        SubmitGraphCommandRequest(
            command_id=uuid4(),
            room_epoch=UUID(checkpoint_response.json()["head"]["room_epoch"]),
            observed_sequence=checkpoint_response.json()["head"][
                "collaboration_sequence"
            ],
            command=RenameGraphCommand(name="Discard me", expected_name="Renamed live"),
        ),
    ).json()
    delete_response = graphs.delete(
        graph_id,
        expected_revision=saved["revision"],
        expected_room_epoch=UUID(pending["head"]["room_epoch"]),
        expected_sequence=pending["head"]["collaboration_sequence"],
    )
    assert delete_response.status_code == 204


def test_http_copy_exact_head_into_same_workspace(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    graphs = api.workspace(WORKSPACE_ID).graphs
    created = graphs.create(_graph_request("Copy source")).json()
    head = graphs.get_head(UUID(created["id"])).json()

    copy_response = graphs.copy(
        CopyExactHeadRequest(
            source_workspace_id=WORKSPACE_ID,
            source_graph_id=UUID(created["id"]),
            expected_room_epoch=UUID(head["room_epoch"]),
            expected_sequence=head["collaboration_sequence"],
            command_id=uuid4(),
            name="Copied graph",
        )
    )
    assert copy_response.status_code == 201
    copied = copy_response.json()
    assert copied["id"] != created["id"]
    assert copied["name"] == "Copied graph"
    assert copied["revision"] == 1

    copied_head = graphs.get_head(UUID(copied["id"])).json()
    assert copied_head["collaboration_sequence"] == 1
    assert copied_head["checkpoint_sequence"] == 1
    assert copied_head["checkpoint_revision"] == 1
