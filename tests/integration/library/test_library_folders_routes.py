"""HTTP wiring for the Library folder tree and artifact placements.

The panel used to keep this tree in `localStorage`. These tests are what it
promised: folders nest to any depth, a folder never moves inside itself, sibling
names are unique without regard to case, a folder deletes only when empty, and
reading the tree asks a smaller permission than changing it.
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


def _folders_path(suffix: str = "") -> str:
    return f"/v1/workspaces/{WORKSPACE_ID}/library/folders{suffix}"


def _placements_path() -> str:
    return f"/v1/workspaces/{WORKSPACE_ID}/library/placements"


def _library_path(suffix: str = "") -> str:
    return f"/v1/workspaces/{WORKSPACE_ID}/library{suffix}"


def _create_folder(
    client: TestClient,
    name: str,
    parent_id: UUID | None = None,
) -> dict:
    response = client.post(
        _folders_path(),
        json={"name": name, "parent_id": None if parent_id is None else str(parent_id)},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _folder_ids(client: TestClient) -> set[str]:
    response = client.get(_folders_path())
    assert response.status_code == 200, response.text
    return {folder["folder_id"] for folder in response.json()["folders"]}


def _library_artifact(client: TestClient, filename: str) -> UUID:
    """Put one real uploaded file into the Library and return its artifact id."""
    uploaded = GrafyApi(client).workspace(WORKSPACE_ID).uploads.upload_ok(
        filename,
        CSV_BYTES,
        content_type="text/csv",
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


def _library_items(client: TestClient) -> list[dict]:
    response = client.get(_library_path("/artifacts"))
    assert response.status_code == 200, response.text
    return response.json()["items"]


def _move_artifacts(
    client: TestClient,
    artifact_ids: list[UUID],
    folder_id: str | UUID | None,
) -> object:
    return client.put(
        _placements_path(),
        json={
            "artifact_ids": [str(artifact_id) for artifact_id in artifact_ids],
            "folder_id": None if folder_id is None else str(folder_id),
        },
    )


def test_the_tree_is_empty_before_the_user_makes_a_folder(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.get(_folders_path())

    assert response.status_code == 200
    assert response.json() == {"folders": []}


def test_a_folder_without_a_parent_is_a_root_folder(
    builtin_client: TestClient,
) -> None:
    folder = _create_folder(builtin_client, "Fieldwork")

    assert folder["name"] == "Fieldwork"
    assert folder["parent_id"] is None
    assert folder["workspace_id"] == str(WORKSPACE_ID)
    assert folder["created_at"].endswith("Z")


def test_a_named_parent_makes_a_subfolder(builtin_client: TestClient) -> None:
    parent = _create_folder(builtin_client, "Fieldwork")

    child = _create_folder(builtin_client, "September", parent_id=parent["folder_id"])

    assert child["parent_id"] == parent["folder_id"]
    assert {parent["folder_id"], child["folder_id"]} == _folder_ids(builtin_client)


def test_a_folder_nests_as_deep_as_the_user_keeps_clicking(
    builtin_client: TestClient,
) -> None:
    first = _create_folder(builtin_client, "Fieldwork")
    second = _create_folder(builtin_client, "September", parent_id=first["folder_id"])

    third = _create_folder(builtin_client, "Raw photos", parent_id=second["folder_id"])

    assert third["parent_id"] == second["folder_id"]
    assert len(_folder_ids(builtin_client)) == 3


def test_a_folder_inside_a_folder_that_does_not_exist_is_not_found(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.post(
        _folders_path(),
        json={"name": "Orphan", "parent_id": str(uuid4())},
    )

    assert response.status_code == 404
    assert response.json()["code"] == "resource.not_found"


def test_two_root_folders_cannot_share_a_name_whatever_its_case(
    builtin_client: TestClient,
) -> None:
    _create_folder(builtin_client, "Fieldwork")

    response = builtin_client.post(
        _folders_path(),
        json={"name": " fieldwork ", "parent_id": None},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "library.folder_name_conflict"


def test_the_same_name_in_two_different_parents_is_two_folders(
    builtin_client: TestClient,
) -> None:
    fieldwork = _create_folder(builtin_client, "Fieldwork")
    reports = _create_folder(builtin_client, "Reports")

    nested = _create_folder(builtin_client, "September", parent_id=fieldwork["folder_id"])
    other = _create_folder(builtin_client, "September", parent_id=reports["folder_id"])

    assert nested["folder_id"] != other["folder_id"]


def test_renaming_a_folder_keeps_its_place_in_the_tree(
    builtin_client: TestClient,
) -> None:
    parent = _create_folder(builtin_client, "Fieldwork")
    child = _create_folder(builtin_client, "Sept", parent_id=parent["folder_id"])

    response = builtin_client.patch(
        _folders_path(f"/{child['folder_id']}"),
        json={"name": "September"},
    )

    assert response.status_code == 200
    renamed = response.json()
    assert renamed["name"] == "September"
    assert renamed["parent_id"] == parent["folder_id"]


def test_a_rename_onto_a_siblings_name_is_refused_with_that_name(
    builtin_client: TestClient,
) -> None:
    _create_folder(builtin_client, "Fieldwork")
    reports = _create_folder(builtin_client, "Reports")

    response = builtin_client.patch(
        _folders_path(f"/{reports['folder_id']}"),
        json={"name": "FIELDWORK"},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "library.folder_name_conflict"


def test_a_folder_never_moves_inside_itself_or_its_own_descendants(
    builtin_client: TestClient,
) -> None:
    parent = _create_folder(builtin_client, "Fieldwork")
    child = _create_folder(builtin_client, "September", parent_id=parent["folder_id"])
    grandchild = _create_folder(
        builtin_client,
        "Raw photos",
        parent_id=child["folder_id"],
    )

    inside_itself = builtin_client.put(
        _folders_path(f"/{parent['folder_id']}/parent"),
        json={"parent_id": parent["folder_id"]},
    )
    under_its_own_child = builtin_client.put(
        _folders_path(f"/{parent['folder_id']}/parent"),
        json={"parent_id": grandchild["folder_id"]},
    )

    assert inside_itself.status_code == 422
    assert inside_itself.json()["code"] == "library.folder_cycle"
    assert under_its_own_child.status_code == 422
    assert under_its_own_child.json()["code"] == "library.folder_cycle"


def test_a_folder_moves_between_parents_and_back_to_the_root(
    builtin_client: TestClient,
) -> None:
    fieldwork = _create_folder(builtin_client, "Fieldwork")
    loose = _create_folder(builtin_client, "September")

    filed = builtin_client.put(
        _folders_path(f"/{loose['folder_id']}/parent"),
        json={"parent_id": fieldwork["folder_id"]},
    )
    unfilled = builtin_client.put(
        _folders_path(f"/{loose['folder_id']}/parent"),
        json={"parent_id": None},
    )
    assert filed.status_code == 200
    assert filed.json()["parent_id"] == fieldwork["folder_id"]
    assert unfilled.status_code == 200
    assert unfilled.json()["parent_id"] is None


def test_moving_into_a_parent_that_already_has_the_name_is_refused(
    builtin_client: TestClient,
) -> None:
    fieldwork = _create_folder(builtin_client, "Fieldwork")
    _create_folder(builtin_client, "September", parent_id=fieldwork["folder_id"])
    reports = _create_folder(builtin_client, "Reports")
    other = _create_folder(builtin_client, "September", parent_id=reports["folder_id"])

    response = builtin_client.put(
        _folders_path(f"/{other['folder_id']}/parent"),
        json={"parent_id": fieldwork["folder_id"]},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "library.folder_name_conflict"


def test_an_empty_folder_deletes_and_the_tree_goes_back_to_empty(
    builtin_client: TestClient,
) -> None:
    folder = _create_folder(builtin_client, "Fieldwork")

    response = builtin_client.delete(_folders_path(f"/{folder['folder_id']}"))

    assert response.status_code == 204
    assert response.content == b""
    assert _folder_ids(builtin_client) == set()


def test_a_folder_with_a_child_refuses_deletion_and_says_what_is_inside(
    builtin_client: TestClient,
) -> None:
    parent = _create_folder(builtin_client, "Fieldwork")
    _create_folder(builtin_client, "September", parent_id=parent["folder_id"])

    response = builtin_client.delete(_folders_path(f"/{parent['folder_id']}"))

    assert response.status_code == 409
    assert response.json()["code"] == "library.folder_not_empty"


def test_a_folder_holding_an_artifact_refuses_deletion(
    builtin_client: TestClient,
) -> None:
    folder = _create_folder(builtin_client, "Fieldwork")
    artifact_id = _library_artifact(builtin_client, "measurements.csv")
    assert _move_artifacts(builtin_client, [artifact_id], folder["folder_id"]).status_code == 204

    response = builtin_client.delete(_folders_path(f"/{folder['folder_id']}"))

    assert response.status_code == 409
    assert response.json()["code"] == "library.folder_not_empty"


def test_emptying_a_folder_is_what_lets_it_delete(builtin_client: TestClient) -> None:
    folder = _create_folder(builtin_client, "Fieldwork")
    artifact_id = _library_artifact(builtin_client, "measurements.csv")
    _ = _move_artifacts(builtin_client, [artifact_id], folder["folder_id"])

    _ = _move_artifacts(builtin_client, [artifact_id], None)
    response = builtin_client.delete(_folders_path(f"/{folder['folder_id']}"))

    assert response.status_code == 204


def test_a_library_artifact_starts_unfiled_and_remembers_its_folder(
    builtin_client: TestClient,
) -> None:
    folder = _create_folder(builtin_client, "Fieldwork")
    artifact_id = _library_artifact(builtin_client, "measurements.csv")
    assert _library_items(builtin_client)[0]["folder_id"] is None

    moved = _move_artifacts(builtin_client, [artifact_id], folder["folder_id"])

    assert moved.status_code == 204
    assert moved.content == b""
    assert _library_items(builtin_client)[0]["folder_id"] == folder["folder_id"]


def test_filing_an_artifact_moves_it_rather_than_copying_it(
    builtin_client: TestClient,
) -> None:
    fieldwork = _create_folder(builtin_client, "Fieldwork")
    reports = _create_folder(builtin_client, "Reports")
    artifact_id = _library_artifact(builtin_client, "measurements.csv")

    _ = _move_artifacts(builtin_client, [artifact_id], fieldwork["folder_id"])
    _ = _move_artifacts(builtin_client, [artifact_id], reports["folder_id"])

    items = _library_items(builtin_client)
    assert len(items) == 1
    assert items[0]["folder_id"] == reports["folder_id"]


def test_one_drop_files_every_artifact_it_carries(builtin_client: TestClient) -> None:
    folder = _create_folder(builtin_client, "Fieldwork")
    first = _library_artifact(builtin_client, "first.csv")
    second = _library_artifact(builtin_client, "second.csv")

    response = _move_artifacts(builtin_client, [first, second], folder["folder_id"])

    assert response.status_code == 204
    assert [item["folder_id"] for item in _library_items(builtin_client)] == [
        folder["folder_id"],
        folder["folder_id"],
    ]


def test_filing_an_artifact_the_workspace_does_not_have_is_not_found(
    builtin_client: TestClient,
) -> None:
    folder = _create_folder(builtin_client, "Fieldwork")

    response = _move_artifacts(builtin_client, [uuid4()], folder["folder_id"])

    assert response.status_code == 404
    assert response.json()["code"] == "resource.not_found"


def test_something_that_is_not_in_the_library_is_not_filed_anywhere(
    builtin_client: TestClient,
) -> None:
    folder = _create_folder(builtin_client, "Fieldwork")
    uploaded = GrafyApi(builtin_client).workspace(WORKSPACE_ID).uploads.upload_ok(
        "not-saved.csv",
        CSV_BYTES,
        content_type="text/csv",
    )
    assert uploaded.artifact_id is not None

    response = _move_artifacts(
        builtin_client,
        [uploaded.artifact_id],
        folder["folder_id"],
    )

    assert response.status_code == 404
    assert _folder_ids(builtin_client) == {folder["folder_id"]}


def test_filing_into_a_folder_that_does_not_exist_is_not_found(
    builtin_client: TestClient,
) -> None:
    artifact_id = _library_artifact(builtin_client, "measurements.csv")

    response = _move_artifacts(builtin_client, [artifact_id], uuid4())

    assert response.status_code == 404
    assert _library_items(builtin_client)[0]["folder_id"] is None


def test_a_placement_request_must_name_at_least_one_artifact(
    builtin_client: TestClient,
) -> None:
    folder = _create_folder(builtin_client, "Fieldwork")

    response = builtin_client.put(
        _placements_path(),
        json={"artifact_ids": [], "folder_id": folder["folder_id"]},
    )

    assert response.status_code == 422


def test_folder_routes_answer_the_shape_the_panel_reads(
    builtin_client: TestClient,
) -> None:
    created = _create_folder(builtin_client, "Fieldwork")

    listed = builtin_client.get(_folders_path()).json()["folders"][0]

    assert set(listed) == {
        "folder_id",
        "workspace_id",
        "parent_id",
        "name",
        "created_at",
        "updated_at",
    }
    assert listed["folder_id"] == created["folder_id"]


def test_unknown_folder_is_not_found_on_every_write(
    builtin_client: TestClient,
) -> None:
    missing = str(uuid4())

    renamed = builtin_client.patch(
        _folders_path(f"/{missing}"),
        json={"name": "Anything"},
    )
    moved = builtin_client.put(_folders_path(f"/{missing}/parent"), json={"parent_id": None})
    deleted = builtin_client.delete(_folders_path(f"/{missing}"))

    assert [renamed.status_code, moved.status_code, deleted.status_code] == [404, 404, 404]


def _acting_with_only(
    client: TestClient,
    capabilities: set[WorkspaceCapability],
) -> None:
    """Send the next requests as a workspace token that grants only these.

    Only the credential is replaced. `require_workspace_capability`, the shared
    user's real owner membership, the refusal, and the 403 envelope are all the
    code under test, and the client belongs to this one test so nothing has to
    be put back afterwards.
    """
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


def test_a_member_without_the_edit_capability_is_refused_every_folder_write(
    builtin_client: TestClient,
) -> None:
    fieldwork = _create_folder(builtin_client, "Fieldwork")
    reports = _create_folder(builtin_client, "Reports")
    artifact_id = _library_artifact(builtin_client, "measurements.csv")

    _acting_with_only(builtin_client, {WorkspaceCapability.VIEW_ARTIFACTS})

    assert builtin_client.get(_folders_path()).status_code == 200
    refusals = {
        "create": builtin_client.post(
            _folders_path(),
            json={"name": "Denied", "parent_id": None},
        ),
        "rename": builtin_client.patch(
            _folders_path(f"/{fieldwork['folder_id']}"),
            json={"name": "Denied"},
        ),
        "move": builtin_client.put(
            _folders_path(f"/{fieldwork['folder_id']}/parent"),
            json={"parent_id": reports["folder_id"]},
        ),
        "delete": builtin_client.delete(_folders_path(f"/{fieldwork['folder_id']}")),
        "file": _move_artifacts(builtin_client, [artifact_id], reports["folder_id"]),
    }

    for route, response in refusals.items():
        assert response.status_code == 403, (route, response.text)
        assert response.json()["code"] == "identity.capability_denied", (
            route,
            response.text,
        )
    # The gate answers before the service opens a transaction, so a refused
    # writer leaves the tree and the filing exactly as it found them.
    assert _folder_ids(builtin_client) == {fieldwork["folder_id"], reports["folder_id"]}
    assert _library_items(builtin_client)[0]["folder_id"] is None


def test_the_folder_listing_is_the_one_route_that_asks_for_the_artifact_read(
    builtin_client: TestClient,
) -> None:
    fieldwork = _create_folder(builtin_client, "Fieldwork")
    artifact_id = _library_artifact(builtin_client, "measurements.csv")

    _acting_with_only(builtin_client, {WorkspaceCapability.EDIT_GRAPH})

    refused = builtin_client.get(_folders_path())

    assert refused.status_code == 403
    assert refused.json()["code"] == "identity.capability_denied"
    # A caller who can edit answers every other route, so the refusal above names
    # the read capability rather than a block on the folder surface as a whole.
    created = builtin_client.post(
        _folders_path(),
        json={"name": "Reports", "parent_id": None},
    )
    assert created.status_code == 201, created.text
    folder_id = created.json()["folder_id"]
    renamed = builtin_client.patch(
        _folders_path(f"/{folder_id}"),
        json={"name": "Field report"},
    )
    assert renamed.status_code == 200, renamed.text
    filed = _move_artifacts(builtin_client, [artifact_id], fieldwork["folder_id"])
    assert filed.status_code == 204, filed.text
    moved = builtin_client.put(
        _folders_path(f"/{folder_id}/parent"),
        json={"parent_id": fieldwork["folder_id"]},
    )
    assert moved.status_code == 200, moved.text
    deleted = builtin_client.delete(_folders_path(f"/{folder_id}"))
    assert deleted.status_code == 204, deleted.text


def test_a_folder_name_is_accepted_to_the_domain_limit_and_refused_past_it(
    builtin_client: TestClient,
) -> None:
    """The request model and the domain have to agree on where a name stops."""
    longest = builtin_client.post(
        _folders_path(),
        json={"name": "x" * 160, "parent_id": None},
    )
    too_long = builtin_client.post(
        _folders_path(),
        json={"name": "x" * 161, "parent_id": None},
    )

    assert longest.status_code == 201, longest.text
    assert len(longest.json()["name"]) == 160
    assert too_long.status_code == 422, too_long.text
    assert too_long.json()["code"] == "request.validation_failed"
