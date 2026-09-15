"""HTTP wiring for the Library artifact endpoints."""

from uuid import uuid4

from fastapi.testclient import TestClient

from tests.support.identity import WORKSPACE_ID


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


def test_saving_from_an_unknown_run_is_not_found(builtin_client: TestClient) -> None:
    response = builtin_client.post(
        _library_path("/artifacts/from-run"),
        json={
            "artifact_id": str(uuid4()),
            "execution_id": str(uuid4()),
            "node_id": "resize-1",
            "node_title": "Resize",
        },
    )

    assert response.status_code == 404


def test_a_save_request_must_name_a_node_and_title(builtin_client: TestClient) -> None:
    response = builtin_client.post(
        _library_path("/artifacts/from-run"),
        json={
            "artifact_id": str(uuid4()),
            "execution_id": str(uuid4()),
            "node_id": "   ",
            "node_title": "Resize",
        },
    )

    assert response.status_code == 422
