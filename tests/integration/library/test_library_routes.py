"""HTTP wiring for the Library artifact endpoints.

Saving is half of what the Library is; this file also covers taking an artifact
back out, which is the part that can strand a saved graph or the bytes other
artifacts share.
"""

from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from grafy_api.v1.routes.auth.dependencies import workspace_actor
from grafy_core.domain.identity import (
    ActorContext,
    WorkspaceCapability,
    WorkspacePatPrincipal,
)
from tests.support.clients import GrafyApi
from tests.support.identity import TEST_USER_ID, WORKSPACE_ID

CSV_BYTES = b"station,salinity\nA,34.2\n"


def _library_path(suffix: str = "") -> str:
    return f"/v1/workspaces/{WORKSPACE_ID}/library{suffix}"


def test_library_is_empty_before_anything_is_saved(builtin_client: TestClient) -> None:
    response = builtin_client.get(_library_path("/artifacts"))

    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_saving_an_unknown_artifact_is_not_found(builtin_client: TestClient) -> None:
    response = builtin_client.post(
        _library_path("/artifacts/from-upload"),
        json={"artifact_id": str(uuid4()), "original_filename": "measurements.csv"},
    )

    assert response.status_code == 404


def _instance_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "project_id": str(uuid4()),
        "graph_id": "main",
        "node_id": "resize-1",
        "result_fingerprint": "a" * 64,
        "output_port": "image",
        "name": "Quarterly report",
    }
    body.update(overrides)
    return body


def test_saving_from_an_unknown_instance_result_is_not_found(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.post(
        _library_path("/artifacts/from-instance"), json=_instance_body()
    )

    assert response.status_code in {400, 404}, response.text


def test_an_instance_save_must_name_a_node(builtin_client: TestClient) -> None:
    response = builtin_client.post(
        _library_path("/artifacts/from-instance"),
        json=_instance_body(node_id=""),
    )

    assert response.status_code == 422


def test_an_instance_save_needs_a_bounded_name_and_a_fingerprint(
    builtin_client: TestClient,
) -> None:
    body = _instance_body()
    del body["name"]

    missing = builtin_client.post(_library_path("/artifacts/from-instance"), json=body)
    too_long = builtin_client.post(
        _library_path("/artifacts/from-instance"),
        json=_instance_body(name="r" * 161),
    )
    bad_fingerprint = builtin_client.post(
        _library_path("/artifacts/from-instance"),
        json=_instance_body(result_fingerprint="not-a-digest"),
    )

    assert missing.status_code == 422
    assert too_long.status_code == 422
    assert bad_fingerprint.status_code == 422


def _library_artifact(client: TestClient, filename: str = "measurements.csv") -> UUID:
    """Upload a real file and save it to the Library, returning its artifact id."""

    uploaded = (
        GrafyApi(client)
        .workspace(WORKSPACE_ID)
        .uploads.upload_ok(
            filename,
            CSV_BYTES,
            content_type="text/csv",
        )
    )
    assert uploaded.artifact_id is not None
    saved = client.post(
        _library_path("/artifacts/from-upload"),
        json={
            "artifact_id": str(uploaded.artifact_id),
            "original_filename": uploaded.filename,
        },
    )
    assert saved.status_code == 200, saved.text
    return uploaded.artifact_id


def _library_ids(client: TestClient) -> set[str]:
    response = client.get(_library_path("/artifacts"))
    assert response.status_code == 200, response.text
    return {item["artifact"]["artifact_id"] for item in response.json()["items"]}


def _project_showing_artifact(
    client: TestClient,
    *,
    name: str,
    artifact_id: UUID,
) -> dict:
    """Open a Project whose only content is a card showing the artifact.

    An artifact card holds the artifact identity so it can present it. Building it
    as a card keeps the test off the Run path.
    """

    base = f"/v1/workspaces/{WORKSPACE_ID}/projects"
    created = client.post(base, json={"name": name})
    assert created.status_code == 201, created.text
    project = created.json()
    head = client.get(f"{base}/{project['id']}/head").json()
    presentation = {
        "viewers": [
            {
                "id": "artifact-viewer-card",
                "position": {"x": 0.0, "y": 0.0},
                "artifact_ref": {
                    "artifact_id": str(artifact_id),
                    "artifact_type": "file.csv",
                    "schema_version": 1,
                },
            }
        ]
    }
    submitted = client.post(
        f"{base}/{project['id']}/commands",
        json={
            "command_id": str(uuid4()),
            "room_epoch": head["room_epoch"],
            "observed_sequence": head["collaboration_sequence"],
            "commands": [
                {
                    "kind": "in_graph",
                    "graph_id": "main",
                    "command": {
                        "kind": "replace_presentation",
                        "presentation": presentation,
                    },
                }
            ],
        },
    )
    assert submitted.status_code == 200, submitted.text
    return project


def test_deleting_a_library_artifact_removes_it(builtin_client: TestClient) -> None:
    artifact_id = _library_artifact(builtin_client)
    assert str(artifact_id) in _library_ids(builtin_client)

    response = builtin_client.delete(_library_path(f"/artifacts/{artifact_id}"))

    assert response.status_code == 204, response.text
    assert response.content == b""
    assert str(artifact_id) not in _library_ids(builtin_client)
    # The artifact row is gone, not merely unfiled.
    detail = builtin_client.get(
        f"/v1/workspaces/{WORKSPACE_ID}/artifacts/{artifact_id}"
    )
    assert detail.status_code == 404


def test_deleting_an_unknown_library_artifact_is_not_found(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.delete(_library_path(f"/artifacts/{uuid4()}"))

    assert response.status_code == 404
    assert response.json()["code"] == "resource.not_found"


def test_deleting_an_artifact_that_was_never_saved_is_not_found(
    builtin_client: TestClient,
) -> None:
    """An artifact only in Files is not the Library's to delete."""

    uploaded = (
        GrafyApi(builtin_client)
        .workspace(WORKSPACE_ID)
        .uploads.upload_ok(
            "not-saved.csv",
            CSV_BYTES,
            content_type="text/csv",
        )
    )
    assert uploaded.artifact_id is not None

    response = builtin_client.delete(
        _library_path(f"/artifacts/{uploaded.artifact_id}")
    )

    assert response.status_code == 404
    assert response.json()["code"] == "resource.not_found"
    # The artifact itself is untouched and still saves to the Library.
    saved = builtin_client.post(
        _library_path("/artifacts/from-upload"),
        json={
            "artifact_id": str(uploaded.artifact_id),
            "original_filename": uploaded.filename,
        },
    )
    assert saved.status_code == 200, saved.text


def test_deleting_an_artifact_a_project_shows_is_refused(
    builtin_client: TestClient,
) -> None:
    artifact_id = _library_artifact(builtin_client)
    _project_showing_artifact(
        builtin_client,
        name="Salinity study",
        artifact_id=artifact_id,
    )

    response = builtin_client.delete(_library_path(f"/artifacts/{artifact_id}"))

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "library.artifact_in_use"
    assert "Salinity study" in body["detail"]
    # The refusal is the whole response: the artifact stays where it was.
    assert str(artifact_id) in _library_ids(builtin_client)


def test_deleting_an_artifact_after_its_project_is_gone_succeeds(
    builtin_client: TestClient,
) -> None:
    """Unlinking the saved work is the other way to clear the refusal."""

    artifact_id = _library_artifact(builtin_client)
    graph = _project_showing_artifact(
        builtin_client,
        name="Salinity study",
        artifact_id=artifact_id,
    )

    refused = builtin_client.delete(_library_path(f"/artifacts/{artifact_id}"))
    assert refused.status_code == 409, refused.text
    # A Project with uncheckpointed commands cannot be deleted: checkpoint first.
    head = builtin_client.get(
        f"/v1/workspaces/{WORKSPACE_ID}/projects/{graph['id']}/head"
    ).json()
    checkpointed = builtin_client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/projects/{graph['id']}/checkpoints",
        json={
            "expected_room_epoch": head["room_epoch"],
            "expected_sequence": head["collaboration_sequence"],
        },
    )
    assert checkpointed.status_code == 200, checkpointed.text
    deleted_project = builtin_client.delete(
        f"/v1/workspaces/{WORKSPACE_ID}/projects/{graph['id']}"
    )
    assert deleted_project.status_code == 204, deleted_project.text

    deleted = builtin_client.delete(_library_path(f"/artifacts/{artifact_id}"))

    assert deleted.status_code == 204, deleted.text
    assert str(artifact_id) not in _library_ids(builtin_client)


def _acting_with_only(
    client: TestClient,
    capabilities: set[WorkspaceCapability],
) -> None:
    """Send the next requests as a workspace token that grants only these."""

    principal = WorkspacePatPrincipal(
        actor=ActorContext(
            user_id=TEST_USER_ID,
            credential_reference="test-workspace-token",
        ),
        workspace_id=WORKSPACE_ID,
        capabilities=frozenset(capabilities),
        token_id=uuid4(),
    )
    client.app.dependency_overrides[workspace_actor] = lambda: principal


def test_deleting_a_library_artifact_needs_graph_edit_right(
    builtin_client: TestClient,
) -> None:
    """Reading the Library stays a smaller permission than emptying it."""

    artifact_id = _library_artifact(builtin_client)

    _acting_with_only(builtin_client, {WorkspaceCapability.VIEW_ARTIFACTS})

    refused = builtin_client.delete(_library_path(f"/artifacts/{artifact_id}"))

    assert refused.status_code == 403
    assert refused.json()["code"] == "identity.capability_denied"
    assert str(artifact_id) in _library_ids(builtin_client)
