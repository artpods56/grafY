"""Run HTTP routes: tenancy, capability, demand, cancel, instances and results.

ADR 0020 makes a Run a demand for targets to become fresh, keeps any number of them
active in one Project, withdraws one demand without stopping work another Run still
needs, and derives instance state from the document instead of storing it. Each claim
is checked here over HTTP with the computation gated on an event, so a test stands at
the moment a node is running rather than racing it.

Every route is asked from outside twice: as a member of the Workspace that owns the
Project and as a member of a Workspace that does not, which must be a 404 — the same
answer as for a Project that was never opened. Capability denials come from a role
that lacks the capability, and from a Personal Access Token whose scope leaves it
out, because effective permission is role ∩ PAT scope ∩ capability.

Nothing here sleeps: the moments a test waits for are a gate the runner opens, or a
frame the room sends once the row behind it is already written.
"""

from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from starlette.testclient import WebSocketDenialResponse

from grafy_api.settings import Settings
from grafy_core.domain.collaboration import (
    AddGraphCommand,
    InGraphCommand,
    RemoveGraphCommand,
    RemoveNodesCommand,
    UpdateNodeConfigurationCommand,
)
from grafy_core.domain.graph_documents import GraphDocument

from tests.integration.runs.support import (
    FLOW_GRAPH_ID,
    RoomHarness,
    accepted_head,
    command_batch,
    integer_node,
    receive_next,
    receive_until,
    room_harness,
)

FIRST = "first"
SECOND = "second"
FRAME_LIMIT = 60


@pytest.fixture
def harness(tmp_path: Path, settings: Settings) -> RoomHarness:
    with room_harness(tmp_path, settings, concurrency=4) as live:
        yield live


def start_url(project_id: UUID, run_id: UUID | None = None) -> str:
    if run_id is None:
        return f"/projects/{project_id}/runs"
    return f"/projects/{project_id}/runs/{run_id}"


def start_run(
    harness: RoomHarness,
    project_id: UUID,
    node_id: str | None = None,
    **kwargs: Any,
):
    targets = [] if node_id is None else [{"node_id": node_id}]
    return harness.post(
        start_url(project_id),
        json={"graph_id": FLOW_GRAPH_ID, "targets": targets},
        **kwargs,
    )


def active_run_ids(harness: RoomHarness, project_id: UUID) -> list[str]:
    response = harness.get(f"{start_url(project_id)}?active=true")
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["runs"]]


def instances_of(
    harness: RoomHarness,
    project_id: UUID,
    *,
    graph_id: str = FLOW_GRAPH_ID,
    headers: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    response = harness.client.get(
        harness.path(f"/projects/{project_id}/graphs/{graph_id}/instances"),
        headers=headers,
    )
    assert response.status_code == 200, response.text
    return {item["key"]["node_id"]: item for item in response.json()["instances"]}


def instance_result(
    harness: RoomHarness,
    project_id: UUID,
    node_id: str,
    *,
    headers: dict[str, str] | None = None,
    call_path: tuple[str, ...] = (),
):
    query = f"?graph_id={FLOW_GRAPH_ID}&node_id={node_id}" + "".join(
        f"&call_path={step}" for step in call_path
    )
    return harness.client.get(
        harness.path(f"/projects/{project_id}/instance-result{query}"), headers=headers
    )


def wait_for_finished(websocket, run_id: str, *, limit: int = FRAME_LIMIT) -> str:
    """The status this Run ended with, taken from the frame that says so."""

    for _ in range(limit):
        message = websocket.receive_json()
        if message["type"] == "run.finished" and message["run_id"] == run_id:
            return str(message["status"])
    raise AssertionError(f"run {run_id} never finished within {limit} frames")


# --- Starting a Run ----------------------------------------------------------


def test_start_run_records_the_demand_and_a_joining_room_sees_it_active(
    harness: RoomHarness,
) -> None:
    project_id = harness.project_id

    started = start_run(harness, project_id, FIRST)
    assert started.status_code == 201, started.text
    run = started.json()
    assert run["status"] == "running"
    assert run["graph_id"] == FLOW_GRAPH_ID
    assert run["project_id"] == str(project_id)
    assert run["workspace_id"] == str(harness.workspace_id)
    assert run["started_by_user_id"] == str(harness.cast.owner.id)
    assert run["targets"] == [{"node_id": FIRST, "call_path": []}]
    assert run["finished_at"] is None
    assert harness.runner.started(FIRST).wait(10)

    assert active_run_ids(harness, project_id) == [run["id"]]
    assert [
        item["id"] for item in harness.get(start_url(project_id)).json()["runs"]
    ] == [run["id"]]
    one = harness.get(start_url(project_id, UUID(run["id"])))
    assert one.status_code == 200, one.text
    assert one.json()["id"] == run["id"]

    # A participant that joined after the start still has to learn about it.
    with harness.connect_room(project_id) as websocket:
        ready = receive_next(websocket, "room.ready")
        assert [item["run_id"] for item in ready["active_runs"]] == [run["id"]]
        summary = ready["active_runs"][0]
        assert summary["graph_id"] == FLOW_GRAPH_ID
        assert summary["targets"] == [{"node_id": FIRST, "call_path": []}]
        assert summary["starter"]["actor_id"] == str(harness.cast.owner.id)

        harness.runner.release(FIRST)
        assert wait_for_finished(websocket, run["id"]) == "succeeded"

    done = harness.get(start_url(project_id, UUID(run["id"]))).json()
    assert done["status"] == "succeeded"
    assert done["finished_at"] is not None
    assert active_run_ids(harness, project_id) == []


def test_start_run_with_no_targets_demands_the_whole_graph(
    harness: RoomHarness,
) -> None:
    project_id = harness.project_id

    assert start_run(harness, project_id).status_code == 201
    assert harness.runner.started(FIRST).wait(10)
    assert harness.runner.started(SECOND).wait(10)
    assert sorted(harness.runner.calls) == [FIRST, SECOND]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"graph_id": "absent", "targets": []}, "unknown_graph"),
        (
            {"graph_id": FLOW_GRAPH_ID, "targets": [{"node_id": "nope"}]},
            "unknown_target",
        ),
    ],
)
def test_start_run_says_why_it_refused(
    harness: RoomHarness,
    payload: dict[str, Any],
    code: str,
) -> None:
    refused = harness.post(start_url(harness.project_id), json=payload)
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == code


def test_cancel_run_withdraws_its_own_demand_and_leaves_the_shared_computation(
    harness: RoomHarness,
) -> None:
    """Two Runs demand one fingerprint; cancelling one must not stop the work.

    The cancelled Run still ends, because its own demand is gone. The computation the
    survivor needs is neither cancelled nor released until the test says so, and the
    survivor succeeds on the result that computation eventually stored.
    """

    project_id = harness.project_id

    first = start_run(harness, project_id, FIRST).json()
    second = start_run(harness, project_id, FIRST).json()
    assert first["id"] != second["id"]
    assert harness.runner.started(FIRST).wait(10)
    # One computation for one fingerprint, however many Runs asked for it.
    assert harness.runner.calls == [FIRST]
    assert active_run_ids(harness, project_id) == [second["id"], first["id"]]

    with harness.connect_room(project_id) as websocket:
        receive_next(websocket, "room.ready")

        cancelled = harness.post(start_url(project_id, UUID(first["id"])) + "/cancel")
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert active_run_ids(harness, project_id) == [second["id"]]

        # What the survivor still needs was never cancelled, and has not run to its
        # end: the cancel withdrew a demand, not a node.
        assert harness.runner.cancelled == []
        assert harness.runner.released == []

        harness.runner.release(FIRST)
        assert wait_for_finished(websocket, first["id"]) == "cancelled"
        assert wait_for_finished(websocket, second["id"]) == "succeeded"

    assert harness.runner.cancelled == []
    assert harness.runner.released == [FIRST]
    assert instances_of(harness, project_id)[FIRST]["state"] == "fresh"


# --- Instance state and instance results -------------------------------------


def test_graph_instances_are_derived_and_move_with_the_computation(
    harness: RoomHarness,
) -> None:
    project_id = harness.project_id

    before = instances_of(harness, project_id)
    assert sorted(before) == [FIRST, SECOND]
    assert before[FIRST]["state"] == "stale"
    assert before[FIRST]["last_result_fingerprint"] is None
    assert before[FIRST]["error"] is None
    assert before[FIRST]["key"] == {
        "project_id": str(project_id),
        "graph_id": FLOW_GRAPH_ID,
        "call_path": [],
        "node_id": FIRST,
        "map_index": None,
    }

    started = start_run(harness, project_id, FIRST).json()
    assert harness.runner.started(FIRST).wait(10)
    running = instances_of(harness, project_id)
    assert running[FIRST]["state"] == "running"
    # The other node did not move: a Run is not a document edit.
    assert running[SECOND]["state"] == "stale"
    assert running[SECOND]["fingerprint"] == before[SECOND]["fingerprint"]
    assert running[FIRST]["fingerprint"] == before[FIRST]["fingerprint"]

    with harness.connect_room(project_id) as websocket:
        receive_next(websocket, "room.ready")
        harness.runner.release(FIRST)
        assert wait_for_finished(websocket, started["id"]) == "succeeded"

    after = instances_of(harness, project_id)
    assert after[FIRST]["state"] == "fresh"
    assert after[FIRST]["last_result_fingerprint"] is not None

    result = instance_result(harness, project_id, FIRST)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["instance"]["state"] == "fresh"
    assert body["result_fingerprint"] == after[FIRST]["last_result_fingerprint"]
    assert body["created_at"] is not None
    # The output is addressed by the fingerprint it was computed for.
    assert body["outputs"]["result"]["content_hash"] == body["result_fingerprint"]


def test_instance_result_reads_the_last_result_after_the_document_moved(
    harness: RoomHarness,
) -> None:
    """A stale instance keeps showing what it last produced; that is the design."""

    project_id = harness.project_id
    started = start_run(harness, project_id, FIRST).json()
    assert harness.runner.started(FIRST).wait(10)

    with harness.connect_room(project_id) as websocket:
        receive_next(websocket, "room.ready")
        stored_fingerprint = instances_of(harness, project_id)[FIRST]["fingerprint"]

        harness.runner.release(FIRST)
        assert wait_for_finished(websocket, started["id"]) == "succeeded"

    stored = instance_result(harness, project_id, FIRST).json()
    assert stored["instance"]["state"] == "fresh"

    with harness.connect_room(project_id) as websocket:
        ready = receive_next(websocket, "room.ready")
        websocket.send_json(
            command_batch(
                ready,
                [
                    InGraphCommand(
                        graph_id=FLOW_GRAPH_ID,
                        command=UpdateNodeConfigurationCommand(
                            node_id=FIRST,
                            field="value",
                            value=99,
                            expected_value=1,
                        ),
                    )
                ],
            )
        )
        receive_until(websocket, "project.command.accepted")
        receive_until(websocket, "instances.changed")

    after = instances_of(harness, project_id)[FIRST]
    assert after["state"] == "stale"
    assert after["fingerprint"] != stored_fingerprint

    reread = instance_result(harness, project_id, FIRST).json()
    assert reread["instance"]["state"] == "stale"
    # The same result as before the edit, read through the instance's own pointer.
    assert reread["result_fingerprint"] == stored["result_fingerprint"]
    assert reread["outputs"] == stored["outputs"]


def test_a_project_is_only_ever_the_project_of_its_own_workspace(
    harness: RoomHarness,
) -> None:
    """Both directions of the same rule, on every route.

    The actor belongs to both Workspaces, so a 404 here is an answer about the
    Project and not about membership: a Project is real, it just is not in the
    Workspace the URL named. The URL's Workspace is the tenancy boundary, whichever
    side is named.
    """

    ours = harness.project_id
    theirs = harness.foreign_project_id
    here = harness.workspace_id
    there = harness.foreign_workspace_id

    for workspace_id, project_id in ((there, ours), (here, theirs)):
        runs = f"/v1/workspaces/{workspace_id}/projects/{project_id}/runs"
        project = f"/v1/workspaces/{workspace_id}/projects/{project_id}"
        missing_run = f"{runs}/{UUID(int=1)}"

        started = harness.client.post(
            runs, json={"graph_id": FLOW_GRAPH_ID, "targets": []}
        )
        assert started.status_code == 404, started.text
        assert harness.client.get(runs).status_code == 404
        assert harness.client.get(f"{runs}?active=true").status_code == 404
        assert harness.client.get(missing_run).status_code == 404
        assert harness.client.post(f"{missing_run}/cancel").status_code == 404
        assert (
            harness.client.get(
                f"{project}/graphs/{FLOW_GRAPH_ID}/instances"
            ).status_code
            == 404
        )
        refused = harness.client.get(
            f"{project}/instance-result?graph_id={FLOW_GRAPH_ID}&node_id={FIRST}"
        )
        assert refused.status_code == 404, refused.text

        with pytest.raises(WebSocketDenialResponse) as denial:
            with harness.client.websocket_connect(f"{project}/room"):
                pass
        assert denial.value.status_code == 404


def test_reads_name_the_reason_they_refused(harness: RoomHarness) -> None:
    project_id = harness.project_id

    refused = instance_result(harness, project_id, "ghost")
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "unknown_target"

    refused_call_path = instance_result(
        harness, project_id, FIRST, call_path=("caller",)
    )
    assert refused_call_path.status_code == 422, refused_call_path.text
    assert refused_call_path.json()["detail"]["code"] == "unknown_target"

    # A Graph this Project does not hold has no instances, which is the same answer
    # an empty Graph gives: state is derived from instances that exist.
    empty = harness.get(f"/projects/{project_id}/graphs/absent/instances")
    assert empty.status_code == 200, empty.text
    assert empty.json()["instances"] == []

    missing_run = harness.get(start_url(project_id, UUID(int=9)))
    assert missing_run.status_code == 404, missing_run.text


# --- Tenancy: a Project of another Workspace is not here ---------------------


def test_a_project_of_another_workspace_is_not_here_for_any_run_route(
    harness: RoomHarness,
) -> None:
    workspace = harness.workspace_id
    project_id = harness.foreign_project_id
    # The actor belongs to both Workspaces, so this is a Project answer and not a
    # membership answer: the Project is real and lives somewhere else.
    runs = f"/v1/workspaces/{workspace}/projects/{project_id}/runs"

    assert (
        harness.client.post(
            runs, json={"graph_id": FLOW_GRAPH_ID, "targets": []}
        ).status_code
        == 404
    )
    assert harness.client.get(runs).status_code == 404
    assert harness.client.get(f"{runs}/{UUID(int=1)}").status_code == 404
    assert harness.client.post(f"{runs}/{UUID(int=1)}/cancel").status_code == 404
    assert (
        harness.client.get(
            f"{runs.rsplit('/runs', 1)[0]}/graphs/{FLOW_GRAPH_ID}/instances"
        ).status_code
        == 404
    )
    denied = harness.client.get(
        f"{runs.rsplit('/runs', 1)[0]}/instance-result?graph_id={FLOW_GRAPH_ID}"
        f"&node_id={FIRST}"
    )
    assert denied.status_code == 404, denied.text


def test_a_project_of_another_workspace_cannot_be_run_or_read_through_our_workspace(
    harness: RoomHarness,
) -> None:
    """The URL's Workspace is the tenancy boundary, whichever side is named."""

    missing = harness.client.get(
        harness.path(f"/projects/{harness.foreign_project_id}/runs")
    )
    assert missing.status_code == 404, missing.text


# --- Capability --------------------------------------------------------------


def test_a_viewer_reads_runs_and_cannot_start_or_cancel(
    harness: RoomHarness,
) -> None:
    project_id = harness.project_id
    started = start_run(harness, project_id, FIRST).json()
    assert harness.runner.started(FIRST).wait(10)
    harness.as_user(harness.cast.viewer)

    assert harness.get(start_url(project_id)).status_code == 200
    assert instances_of(harness, project_id)[FIRST]["state"] == "running"
    assert instance_result(harness, project_id, FIRST).status_code == 200

    denied_start = start_run(harness, project_id, SECOND)
    assert denied_start.status_code == 403, denied_start.text
    assert denied_start.json()["code"] == "identity.capability_denied"

    denied_cancel = harness.post(start_url(project_id, UUID(started["id"])) + "/cancel")
    assert denied_cancel.status_code == 403, denied_cancel.text
    assert denied_cancel.json()["code"] == "identity.capability_denied"

    harness.runner.release(FIRST)


def test_a_token_scope_without_view_runs_is_refused_the_run_reads(
    harness: RoomHarness,
) -> None:
    """An owner's role is not a blanket grant when the credential is narrower."""

    project_id = harness.project_id
    headers = harness.bearer(harness.issue_token(["view_project", "view_artifacts"]))

    denied = harness.client.get(harness.path(start_url(project_id)), headers=headers)
    assert denied.status_code == 403, denied.text
    denied_active = harness.client.get(
        harness.path(f"{start_url(project_id)}?active=true"), headers=headers
    )
    assert denied_active.status_code == 403, denied_active.text
    denied_instances = harness.client.get(
        harness.path(f"/projects/{project_id}/graphs/{FLOW_GRAPH_ID}/instances"),
        headers=headers,
    )
    assert denied_instances.status_code == 403, denied_instances.text


def test_a_token_scope_without_view_artifacts_is_refused_the_instance_result(
    harness: RoomHarness,
) -> None:
    project_id = harness.project_id
    headers = harness.bearer(harness.issue_token(["view_project", "view_runs"]))

    assert (
        harness.client.get(harness.path(start_url(project_id)), headers=headers)
    ).status_code == 200
    assert (
        harness.client.get(
            harness.path(f"/projects/{project_id}/graphs/{FLOW_GRAPH_ID}/instances"),
            headers=headers,
        )
    ).status_code == 200

    denied = harness.client.get(
        harness.path(
            f"/projects/{project_id}/instance-result?graph_id={FLOW_GRAPH_ID}"
            f"&node_id={FIRST}"
        ),
        headers=headers,
    )
    assert denied.status_code == 403, denied.text


def test_a_token_scope_without_run_capabilities_is_refused_start_and_cancel(
    harness: RoomHarness,
) -> None:
    project_id = harness.project_id
    start_only = harness.bearer(harness.issue_token(["view_project", "start_run"]))
    cancel_only = harness.bearer(harness.issue_token(["view_project", "cancel_run"]))

    assert (
        harness.client.post(
            harness.path(start_url(project_id)),
            json={"graph_id": FLOW_GRAPH_ID, "targets": [{"node_id": FIRST}]},
            headers=start_only,
        )
    ).status_code == 201
    assert (
        harness.client.post(
            harness.path(start_url(project_id)),
            json={"graph_id": FLOW_GRAPH_ID, "targets": []},
            headers=cancel_only,
        )
    ).status_code == 403

    listed = harness.get(start_url(project_id)).json()["runs"]
    assert len(listed) == 1
    refused_cancel = harness.client.post(
        harness.path(start_url(project_id, UUID(listed[0]["id"])) + "/cancel"),
        headers=start_only,
    )
    assert refused_cancel.status_code == 403, refused_cancel.text

    accepted = harness.post(start_url(project_id, UUID(listed[0]["id"])) + "/cancel")
    assert accepted.status_code == 200, accepted.text
    harness.runner.release_everything()


# --- Instances follow the document -------------------------------------------


def test_an_added_graph_adds_an_instance_and_its_removal_removes_it(
    harness: RoomHarness,
) -> None:
    """The way in is the way out: an instance that stops existing is removed."""

    project_id = harness.project_id
    with harness.connect_room(project_id) as websocket:
        ready = receive_next(websocket, "room.ready")
        assert sorted(item["node_id"] for item in ready["instances"]) == [
            FIRST,
            SECOND,
        ]

        websocket.send_json(
            command_batch(
                ready,
                [
                    AddGraphCommand(
                        graph_id="extra",
                        name="Graph extra",
                        document=GraphDocument(nodes=(integer_node("only"),)),
                    )
                ],
            )
        )
        added = receive_until(websocket, "project.command.accepted")
        changed = receive_until(websocket, "instances.changed")
        # The first publish this API owner owes this Project publishes everything it
        # derives: state is a diff against what was published, and nothing had been.
        assert sorted(item["node_id"] for item in changed["changed"]) == sorted(
            [FIRST, SECOND, "only"]
        )
        assert {item["graph_id"] for item in changed["changed"]} == {
            FLOW_GRAPH_ID,
            "extra",
        }
        assert all(item["state"] == "stale" for item in changed["changed"])
        assert changed["removed"] == []

        websocket.send_json(
            command_batch(
                accepted_head(added),
                [
                    InGraphCommand(
                        graph_id="extra",
                        command=RemoveNodesCommand(node_ids=("only",)),
                    )
                ],
            )
        )
        removed_batch = receive_until(websocket, "project.command.accepted")
        removed = receive_until(websocket, "instances.changed")
        assert [item["node_id"] for item in removed["removed"]] == ["only"]

        # A Graph removed with it takes its instances, and there is nothing left
        # of it to report.
        websocket.send_json(
            command_batch(
                accepted_head(removed_batch), [RemoveGraphCommand(graph_id="extra")]
            )
        )
        receive_until(websocket, "project.command.accepted")
        emptied = receive_until(websocket, "instances.changed")
        assert emptied["changed"] == []
        assert emptied["removed"] == []

    emptied = harness.get(f"/projects/{project_id}/graphs/extra/instances")
    assert emptied.status_code == 200, emptied.text
    assert emptied.json()["instances"] == []
