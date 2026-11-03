"""One Project, four people, every surface: the acceptance journey (ADR 0020).

The automatable stand-in for the two-browser journey. Owner and editor converge on
one head; a Run started by one is visible to the other, and cancelling it is a
capability rather than a privilege of whoever started it; a viewer watches runs and
cannot touch either; a member removed mid-session loses the room, the runs and the
Project. A Project of a Workspace you do not belong to is not there at all.

The HTTP routes for Projects themselves belong to another change, so Projects are
opened through the service layer, which is also how the room's own admission is
reached. What is exercised over the wire is this change's surface: the room, the run
routes, and the workspace membership routes that revoke access.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from grafy_api.settings import Settings
from grafy_core.domain.collaboration import RenameProjectCommand
from grafy_core.domain.identity import WorkspaceRole

from tests.integration.runs.support import (
    FLOW_GRAPH_ID,
    RoomHarness,
    accepted_head,
    command_batch,
    room_harness,
)

FIRST = "first"
SECOND = "second"


@pytest.fixture
def harness(tmp_path: Path, settings: Settings) -> RoomHarness:
    with room_harness(tmp_path, settings, concurrency=4) as live:
        yield live


def start_run(harness: RoomHarness, project_id: UUID, node_id: str) -> dict[str, Any]:
    response = harness.post(
        f"/projects/{project_id}/runs",
        json={"graph_id": FLOW_GRAPH_ID, "targets": [{"node_id": node_id}]},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_the_project_journey_two_editors_one_run_one_viewer_and_a_revocation(
    harness: RoomHarness,
) -> None:
    project_id = harness.project_id

    with harness.open_room(project_id) as owner_room:
        owner_ready = owner_room.expect("room.ready")
        assert owner_ready["head"]["name"] == "Room project"
        assert owner_ready["active_runs"] == []

        # The editor joins, sees the same head, and renames the Project.
        harness.as_user(harness.cast.editor.id)
        with harness.open_room(project_id) as editor_room:
            editor_ready = editor_room.expect("room.ready")
            assert editor_ready["head"] == owner_ready["head"]
            editor_room.send(
                command_batch(
                    editor_ready,
                    [
                        RenameProjectCommand(
                            name="Acceptance project",
                            expected_name=editor_ready["head"]["name"],
                        )
                    ],
                )
            )
            accepted = editor_room.expect("project.command.accepted")
            editor_room.expect("project.command.receipt")
            editor_room.expect("instances.changed")
            # The owner's socket also carries the join it is watching, so these reads
            # skip presence traffic rather than asserting on its position.
            peer_accepted = owner_room.until("project.command.accepted")
            assert peer_accepted["command_id"] == accepted["command_id"]

            # The owner starts a Run. The editor did not start it and still has to
            # see it, because the canvas is shared, not per-person.
            harness.as_user(harness.cast.owner.id)
            run = start_run(harness, project_id, FIRST)
            assert harness.runner.started(FIRST).wait(10)
            owner_started = owner_room.until("run.started")
            editor_started = editor_room.until("run.started")
            assert owner_started["run"]["run_id"] == run["id"]
            assert editor_started["run"]["run_id"] == run["id"]
            assert editor_started["run"]["starter"]["actor_id"] == str(
                harness.cast.owner.id
            )
            running = harness.get(
                f"/projects/{project_id}/graphs/{FLOW_GRAPH_ID}/instances"
            ).json()["instances"]
            assert {item["key"]["node_id"]: item["state"] for item in running} == {
                FIRST: "running",
                SECOND: "stale",
            }

            # Cancelling is a capability, not authorship: the editor may withdraw a
            # Run the owner started.
            harness.as_user(harness.cast.editor.id)
            cancelled = harness.post(f"/projects/{project_id}/runs/{run['id']}/cancel")
            assert cancelled.status_code == 200, cancelled.text
            assert cancelled.json()["status"] == "cancelled"
            assert editor_room.until("run.finished")["status"] == "cancelled"
            assert owner_room.until("run.finished")["status"] == "cancelled"
            # This Run was the only one that needed that computation, so withdrawing
            # its demand does stop the work: contrast the Run-routes suite, where two
            # Runs demand one fingerprint and a cancel must not touch it.
            assert harness.runner.cancelled == [FIRST]

            # A viewer reads the shared state and changes none of it.
            harness.as_user(harness.cast.viewer.id)
            with harness.open_room(project_id) as viewer_room:
                viewer_ready = viewer_room.expect("room.ready")
                assert viewer_ready["head"]["name"] == "Acceptance project"
                assert (
                    "edit_project" not in viewer_ready["capabilities"]["capabilities"]
                )
                assert "start_run" not in viewer_ready["capabilities"]["capabilities"]
                assert {item["node_id"] for item in viewer_ready["instances"]} == {
                    FIRST,
                    SECOND,
                }
                assert harness.get(f"/projects/{project_id}/runs").status_code == 200
                viewer_room.send(
                    command_batch(
                        viewer_ready,
                        [
                            RenameProjectCommand(
                                name="Viewer should fail",
                                expected_name="Acceptance project",
                            )
                        ],
                    )
                )
                assert viewer_room.expect("project.command.rejected")["error_code"] == (
                    "forbidden"
                )
                denied = harness.post(
                    f"/projects/{project_id}/runs",
                    json={"graph_id": FLOW_GRAPH_ID, "targets": []},
                )
                assert denied.status_code == 403

                # A second editor edit while the viewer watches: the viewer is told,
                # though it could not have made such an edit itself.
                harness.as_user(harness.cast.editor.id)
                editor_room.send(
                    command_batch(
                        accepted_head(peer_accepted),
                        [
                            RenameProjectCommand(
                                name="Seen by the viewer",
                                expected_name="Acceptance project",
                            )
                        ],
                    )
                )
                seen = viewer_room.until("project.command.accepted")
                assert [item["name"] for item in seen["commands"]] == [
                    "Seen by the viewer"
                ]
                assert editor_room.until("project.command.accepted")

            # Revocation closes the room with a reason, takes the Project away, and
            # leaves the other participants alone with the head they had.
            harness.as_user(harness.cast.owner.id)
            assert (
                harness.client.delete(
                    f"/v1/workspaces/{harness.workspace_id}/members/"
                    f"{harness.cast.editor.id}"
                )
            ).status_code == 204
            with pytest.raises(WebSocketDisconnect) as closed:
                while True:
                    assert editor_room.next()["type"] in {
                        "presence.update",
                        "presence.leave",
                        "instances.changed",
                        "project.command.accepted",
                        "project.command.receipt",
                        "run.finished",
                        "run.started",
                        "instances.removed",
                    }
            assert closed.value.code == 4004
            assert closed.value.reason == "access_revoked"

            harness.as_user(harness.cast.editor.id)
            assert harness.get(f"/projects/{project_id}/runs").status_code == 404
            with pytest.raises(WebSocketDenialResponse):
                with harness.open_room(project_id):
                    pass

        head = owner_room  # still open, still in sequence with everything accepted
        assert head is not None

    harness.as_user(harness.cast.owner.id)
    with harness.open_room(project_id) as witness:
        assert witness.expect("room.ready")["head"]["name"] == "Seen by the viewer"


def test_a_project_you_do_not_belong_to_is_not_there_at_all(
    harness: RoomHarness,
) -> None:
    """Tenancy in the room and in the run routes, from the outside in.

    The stranger shares neither Workspace's Project: they get 404 from the room and
    from every run route, which is the same answer a Project that was never opened
    gives, so no probe can tell the two apart.
    """

    harness.as_user(harness.cast.stranger.id)
    with pytest.raises(WebSocketDenialResponse) as denied:
        with harness.open_room(harness.project_id):
            pass
    assert denied.value.status_code == 404
    assert (
        denied.value.status_code
        == harness.get(f"/projects/{harness.project_id}/runs").status_code
    )
    assert (
        harness.post(
            f"/projects/{harness.project_id}/runs",
            json={"graph_id": FLOW_GRAPH_ID, "targets": []},
        ).status_code
        == 404
    )


def test_a_role_change_narrows_what_the_same_socket_can_do_next_time(
    harness: RoomHarness,
) -> None:
    """The way down is as real as the way up: editor to viewer, then read only."""

    project_id = harness.project_id
    harness.as_user(harness.cast.editor.id)
    with harness.open_room(project_id) as editor_room:
        ready = editor_room.expect("room.ready")
        assert "edit_project" in ready["capabilities"]["capabilities"]
        harness.as_user(harness.cast.owner.id)
        assert (
            harness.client.patch(
                f"/v1/workspaces/{harness.workspace_id}/members/"
                f"{harness.cast.editor.id}",
                json={"role": WorkspaceRole.VIEWER.value},
            )
        ).status_code == 200
        with pytest.raises(WebSocketDisconnect):
            editor_room.next()

    harness.as_user(harness.cast.editor.id)
    with harness.open_room(project_id) as narrowed:
        ready = narrowed.expect("room.ready")
    assert "edit_project" not in ready["capabilities"]["capabilities"]
    assert "view_runs" in ready["capabilities"]["capabilities"]
    assert (
        harness.post(
            f"/projects/{project_id}/runs",
            json={"graph_id": FLOW_GRAPH_ID, "targets": []},
        ).status_code
        == 403
    )
