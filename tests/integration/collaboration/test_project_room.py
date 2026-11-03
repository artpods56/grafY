"""The Project room: admission, one head, two participants, and shared Runs.

ADR 0020 makes the Project the collaborative document, so this is the room's contract
at the WebSocket boundary: a member gets in and nobody else does; the head a
participant loads is the head it may submit against; an accepted batch moves the
sequence once and reaches everyone; a Run that started before a participant joined is
still in its ``room.ready``, and one that starts while it is there arrives as
``run.started``; an edit moves instance state and everyone is told which instances.

Presence keeps the graph room's rules — rate limits, stale-sequence drops, TTL
expiry, and a best-effort channel that drops an update rather than a session — and
Runs add one rule of their own: no participant owns the document, so nobody can edit
their way out of someone else's computation.

A participant here is a ``Room``: frames arrive on a bounded queue, so a frame the
room never sends fails the test naming itself instead of blocking forever.
"""

import asyncio
import json
import logging
import threading
from pathlib import Path
from queue import Queue
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from pydantic import ValidationError
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect, WebSocketState

from grafy_api.realtime import hub as hub_module
from grafy_api.realtime.hub import (
    CLOSE_SLOW_CONSUMER,
    OUTBOUND_QUEUE_MAXSIZE,
    ProjectRoomHub,
    ProjectRoomSession,
)
from grafy_api.realtime.protocol import (
    ActorPresentation,
    PresenceUpdateSubmitMessage,
    RoomHeartbeatMessage,
    RoomReadyMessage,
)

from grafy_api.settings import Settings
from grafy_core.domain.collaboration import (
    InGraphCommand,
    RenameProjectCommand,
    UpdateNodeConfigurationCommand,
)
from grafy_core.domain.identity import ActorContext, WorkspaceRole

from tests.integration.runs.support import (
    FLOW_GRAPH_ID,
    Room,
    RoomHarness,
    command_batch,
    room_harness,
)

FIRST = "first"
SECOND = "second"

FIXTURES = Path(__file__).parents[2] / "fixtures"


@pytest.fixture
def harness(tmp_path: Path, settings: Settings) -> RoomHarness:
    with room_harness(tmp_path, settings, concurrency=4) as live:
        yield live


@pytest.fixture
def heartbeat_harness(tmp_path: Path, settings: Settings) -> RoomHarness:
    with room_harness(
        tmp_path, settings, heartbeat_seconds=0.05, concurrency=4
    ) as live:
        yield live


def rename(ready: dict[str, Any], name: str) -> dict[str, Any]:
    """A ``rename_project`` batch observed against the head this room loaded."""

    return command_batch(
        ready,
        [RenameProjectCommand(name=name, expected_name=ready["head"]["name"])],
    )


# --- The ready frame ---------------------------------------------------------


def test_the_ready_fixture_is_a_ready_the_protocol_accepts() -> None:
    payload = json.loads(
        (FIXTURES / "project_room_ready.v1.json").read_text(encoding="utf-8")
    )
    ready = RoomReadyMessage.model_validate(payload)
    assert ready.type == "room.ready"
    assert ready.protocol_version == 1
    assert ready.registry_marker == "builtin"
    # Everything a participant cannot reconstruct from the head alone.
    assert [item.run_id.hex for item in ready.active_runs] == [
        payload["active_runs"][0]["run_id"].replace("-", "")
    ]
    assert ready.active_runs[0].starter is not None
    assert [(item.node_id, item.state) for item in ready.instances] == [
        ("first", "running"),
        ("second", "stale"),
    ]
    assert ready.head.document.get_graph("flow") is not None
    assert [graph.id for graph in ready.head.document.graphs] == ["main", "flow"]
    assert ready.participants[1].graph_id == "flow"
    assert ready.participants[1].cursor is not None
    # A frame from a protocol this server does not speak is refused, not coerced.
    with pytest.raises(ValidationError):
        RoomReadyMessage.model_validate(payload | {"active_execution": None})
    with pytest.raises(ValidationError):
        RoomReadyMessage.model_validate(payload | {"graph_id": payload["project_id"]})


def test_ready_admits_a_member_with_the_state_it_cannot_get_elsewhere(
    harness: RoomHarness,
) -> None:
    project_id = harness.project_id

    with harness.open_room(project_id) as room:
        ready = room.expect("room.ready")

    assert ready["protocol_version"] == 1
    assert ready["workspace_id"] == str(harness.workspace_id)
    assert ready["project_id"] == str(project_id)
    assert ready["actor"]["actor_id"] == str(harness.cast.owner.id)
    assert ready["actor"]["display_name"] == "Owner"
    assert ready["capabilities"]["authorization_version"] >= 1
    assert "edit_project" in ready["capabilities"]["capabilities"]
    head = ready["head"]
    # The opening batch is checkpoint 1 at sequence 0; the Graph the harness added is
    # the one accepted batch since, and nothing was checkpointed after it.
    assert head["collaboration_sequence"] == 1
    assert head["checkpoint_sequence"] == 0
    assert head["checkpoint_revision"] == 1
    assert [graph["id"] for graph in head["document"]["graphs"]] == [
        "main",
        FLOW_GRAPH_ID,
    ]
    assert ready["active_runs"] == []
    assert [(item["node_id"], item["state"]) for item in ready["instances"]] == [
        (FIRST, "stale"),
        (SECOND, "stale"),
    ]
    assert len(ready["participants"]) == 1
    assert (
        ready["participants"][0]["project_room_session_id"]
        == ready["project_room_session_id"]
    )


def test_the_room_rejects_another_origins_page(harness: RoomHarness) -> None:
    with pytest.raises(WebSocketDenialResponse) as denied:
        with harness.open_room(harness.project_id, origin="http://evil.example"):
            pass
    assert denied.value.status_code == 403


def test_the_room_rejects_someone_who_is_not_a_member(harness: RoomHarness) -> None:
    harness.as_user(harness.cast.stranger.id)
    with pytest.raises(WebSocketDenialResponse) as denied:
        with harness.open_room(harness.project_id):
            pass
    assert denied.value.status_code == 404


def test_the_room_rejects_a_project_of_another_workspace(harness: RoomHarness) -> None:
    """The stranger's Workspace holds a Project too; ours is not readable there."""

    with pytest.raises(WebSocketDenialResponse) as denied:
        with harness.open_room(
            harness.project_id, workspace_id=harness.foreign_workspace_id
        ):
            pass
    assert denied.value.status_code == 404


# --- Two participants on one head -------------------------------------------


def test_two_sessions_converge_on_the_accepted_sequence_and_head(
    harness: RoomHarness,
) -> None:
    project_id = harness.project_id

    with harness.open_room(project_id) as owner_room:
        owner_ready = owner_room.expect("room.ready")
        harness.as_user(harness.cast.editor.id)
        with harness.open_room(project_id) as editor_room:
            editor_ready = editor_room.expect("room.ready")
            assert editor_ready["workspace_id"] == owner_ready["workspace_id"]
            assert editor_ready["project_id"] == owner_ready["project_id"]
            assert (
                editor_ready["head"]["collaboration_sequence"]
                == owner_ready["head"]["collaboration_sequence"]
            )

            command_id = uuid4()
            editor_room.send(
                command_batch(
                    editor_ready,
                    [
                        RenameProjectCommand(
                            name="Renamed live",
                            expected_name=editor_ready["head"]["name"],
                        )
                    ],
                    command_id=command_id,
                )
            )
            expected = editor_ready["head"]["collaboration_sequence"] + 1
            accepted = editor_room.expect("project.command.accepted")
            receipt = editor_room.expect("project.command.receipt")
            assert accepted["command_id"] == str(command_id)
            assert accepted["sequence"] == expected
            assert receipt["accepted_sequence"] == expected
            assert receipt["current_sequence"] == expected
            assert receipt["deduplicated"] is False

            owner_accepted = owner_room.until("project.command.accepted")
            assert owner_accepted["command_id"] == str(command_id)
            assert owner_accepted["sequence"] == expected
            assert [command["name"] for command in owner_accepted["commands"]] == [
                "Renamed live"
            ]
            assert owner_accepted["actor"]["actor_id"] == str(harness.cast.editor.id)
            assert (
                owner_accepted["project_room_session_id"]
                == editor_ready["project_room_session_id"]
            )

    head = _head_of(harness, project_id)
    assert head["collaboration_sequence"] == expected
    assert head["name"] == "Renamed live"


def test_a_command_the_document_refuses_is_answered_without_closing_the_room(
    harness: RoomHarness,
) -> None:
    """An unapplicable batch is a rejection on one socket, not a closed room."""

    project_id = harness.project_id

    with harness.open_room(project_id) as room:
        ready = room.expect("room.ready")
        room.send(
            command_batch(
                ready,
                [
                    InGraphCommand(
                        graph_id=FLOW_GRAPH_ID,
                        command=UpdateNodeConfigurationCommand(
                            node_id="absent",
                            field="value",
                            value=2,
                            expected_value=1,
                        ),
                    )
                ],
            )
        )
        rejected = room.expect("project.command.rejected")
        assert rejected["error_code"] == "missing_node"
        assert "absent" in rejected["detail"]

        # The room survives its own rejection and keeps serving batches.
        room.send(rename(ready, "Still alive"))
        accepted = room.expect("project.command.accepted")

    assert [command["name"] for command in accepted["commands"]] == ["Still alive"]
    assert _head_of(harness, project_id)["name"] == "Still alive"


def test_a_retried_command_replays_and_is_not_fanned_out_twice(
    harness: RoomHarness,
) -> None:
    project_id = harness.project_id
    submit: dict[str, Any] | None = None

    with harness.open_room(project_id) as first_room:
        ready = first_room.expect("room.ready")
        submit = rename(ready, "Once only")
        first_room.send(submit)
        first_accepted = first_room.expect("project.command.accepted")
        assert first_room.expect("project.command.receipt")["outcome"] == "accepted"
        accepted_sequence = first_accepted["sequence"]

    harness.as_user(harness.cast.editor.id)
    with harness.open_room(project_id) as peer_room:
        peer_ready = peer_room.expect("room.ready")
        assert peer_ready["head"]["collaboration_sequence"] == accepted_sequence
        assert peer_ready["head"]["name"] == "Once only"

        harness.as_user(harness.cast.owner.id)
        with harness.open_room(project_id) as retry_room:
            retry_ready = retry_room.expect("room.ready")
            assert retry_ready["head"]["collaboration_sequence"] == accepted_sequence
            retry_room.send(submit)
            replay = retry_room.expect("project.command.receipt")
            assert replay["outcome"] == "idempotent_replay"
            assert replay["deduplicated"] is True
            assert replay["accepted_sequence"] == accepted_sequence
            assert replay["current_sequence"] == accepted_sequence
            # A replay answers the caller alone. The peer's own next batch is the
            # barrier: everything the room will say about the replay has to precede
            # it, and none of it may name the replayed command.
            peer_room.send(
                command_batch(
                    peer_ready,
                    [
                        RenameProjectCommand(
                            name="Peer marker", expected_name="Once only"
                        )
                    ],
                )
            )
            accepted = _next_command_frame(peer_room, named=submit["command_id"])
            receipt = peer_room.expect("project.command.receipt")
            assert [command["name"] for command in accepted["commands"]] == [
                "Peer marker"
            ]
            assert accepted["sequence"] == accepted_sequence + 1
            assert receipt["accepted_sequence"] == accepted_sequence + 1

    head = _head_of(harness, project_id)
    assert head["collaboration_sequence"] == accepted_sequence + 1
    assert head["name"] == "Peer marker"


def test_a_viewer_is_refused_a_batch_without_fanning_anything_out(
    harness: RoomHarness,
) -> None:
    project_id = harness.project_id

    with harness.open_room(project_id) as owner_room:
        owner_ready = owner_room.expect("room.ready")
        harness.as_user(harness.cast.viewer.id)
        with harness.open_room(project_id) as viewer_room:
            ready = viewer_room.expect("room.ready")
            assert "edit_project" not in ready["capabilities"]["capabilities"]
            refused = rename(ready, "Nope")
            viewer_room.send(refused)
            rejected = viewer_room.expect("project.command.rejected")
            assert rejected["error_code"] == "forbidden"

        owner_room.send(rename(owner_ready, "The owner's own"))
        accepted = _next_command_frame(owner_room, named=refused["command_id"])
        assert accepted["sequence"] == owner_ready["head"]["collaboration_sequence"] + 1


def test_a_batch_committed_while_the_join_snapshot_is_taken_is_not_missed(
    harness: RoomHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The head snapshot and the live fanout cannot leave a participant behind.

    A join registers with the hub, reads the head, then sends ``room.ready``. A batch
    that another participant commits inside that window has to arrive afterwards, and
    it has to arrive instead of nothing at all: the joiner would otherwise hold a head
    it never learns has moved.
    """

    project_id = harness.project_id
    collaboration = cast(FastAPI, harness.client.app).state.resources.collaboration
    original = collaboration.get_head
    snapshot_taken = threading.Event()
    release_snapshot = threading.Event()

    joining_as = harness.cast.owner.id

    async def get_head_after_snapshot(
        *, actor: ActorContext, workspace_id: UUID, project_id: UUID
    ):
        head = await original(
            actor=actor, workspace_id=workspace_id, project_id=project_id
        )
        if actor.user_id != joining_as:
            # Only the joining participant is held inside the snapshot window. Held
            # for everyone, the participant that is about to commit the raced batch
            # would be stuck in the same window it is supposed to race.
            return head
        snapshot_taken.set()
        await asyncio.to_thread(release_snapshot.wait)
        return head

    monkeypatch.setattr(collaboration, "get_head", get_head_after_snapshot)

    frames: Queue[dict[str, Any]] = Queue()
    failures: Queue[BaseException] = Queue()
    joined = threading.Event()

    def join_and_read() -> None:
        try:
            with harness.open_room(project_id) as room:
                frames.put(room.next())
                joined.set()
                frames.put(room.until("project.command.accepted"))
        except BaseException as exc:  # noqa: BLE001 - reported to the test thread
            failures.put(exc)
            joined.set()

    receiver = threading.Thread(target=join_and_read, daemon=True)
    receiver.start()
    try:
        assert snapshot_taken.wait(10), "the join never read the head"
        harness.as_user(harness.cast.editor.id)
        with harness.open_room(project_id) as editor_room:
            editor_ready = editor_room.expect("room.ready")
            observed = editor_ready["head"]["collaboration_sequence"]
            raced_id = uuid4()
            editor_room.send(
                command_batch(
                    editor_ready,
                    [
                        RenameProjectCommand(
                            name="Committed during join",
                            expected_name=editor_ready["head"]["name"],
                        )
                    ],
                    command_id=raced_id,
                )
            )
            raced_sequence = editor_room.expect("project.command.accepted")["sequence"]
    finally:
        release_snapshot.set()

    assert joined.wait(10), "the room never finished joining"
    if not failures.empty():
        raise failures.get_nowait()
    ready = frames.get(timeout=10)
    assert ready["type"] == "room.ready"
    assert ready["head"]["collaboration_sequence"] == observed

    if not failures.empty():
        raise failures.get_nowait()
    accepted = frames.get(timeout=10)
    assert accepted["command_id"] == str(raced_id)
    assert accepted["sequence"] == raced_sequence
    assert [command["name"] for command in accepted["commands"]] == [
        "Committed during join"
    ]


# --- Membership changes ------------------------------------------------------


def test_a_role_change_closes_the_room_with_permissions_changed(
    harness: RoomHarness,
) -> None:
    project_id = harness.project_id
    harness.as_user(harness.cast.editor.id)

    with harness.open_room(project_id) as editor_room:
        editor_room.expect("room.ready")
        harness.as_user(harness.cast.owner.id)
        _change_role(harness, harness.cast.editor.id, WorkspaceRole.VIEWER)

        with pytest.raises(WebSocketDisconnect) as closed:
            editor_room.next()
        assert closed.value.code == 4003
        assert closed.value.reason == "permissions_changed"

    harness.as_user(harness.cast.editor.id)
    with harness.open_room(project_id) as viewer_room:
        ready = viewer_room.expect("room.ready")
    assert "edit_project" not in ready["capabilities"]["capabilities"]
    assert "view_project" in ready["capabilities"]["capabilities"]
    assert ready["capabilities"]["authorization_version"] >= 2


def test_a_heartbeat_revalidates_membership_when_invalidation_was_lost(
    heartbeat_harness: RoomHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The heartbeat is the backstop for a post-commit room close that never came."""

    async def _skip_room_close(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "grafy_api.v1.routes.workspaces.views.close_user_rooms_for_permission_change",
        _skip_room_close,
    )
    harness = heartbeat_harness
    project_id = harness.project_id
    harness.as_user(harness.cast.editor.id)

    with harness.connect_room(project_id) as session:
        assert session.receive_json()["type"] == "room.ready"
        harness.as_user(harness.cast.owner.id)
        _change_role(harness, harness.cast.editor.id, WorkspaceRole.VIEWER)

        message = session.receive()
        while message["type"] == "websocket.send":
            # A heartbeat queued before the role commit may still arrive first.
            assert json.loads(message["text"])["type"] == "room.heartbeat"
            message = session.receive()
    assert message["type"] == "websocket.close"
    assert message["code"] == 4003
    assert message["reason"] == "permissions_changed"


def test_the_room_keeps_its_own_heartbeat_on_the_wire(
    heartbeat_harness: RoomHarness,
) -> None:
    harness = heartbeat_harness
    with harness.connect_room(harness.project_id) as session:
        ready = session.receive_json()
        heartbeat = session.receive_json()

    assert ready["type"] == "room.ready"
    assert heartbeat["type"] == "room.heartbeat"
    assert heartbeat["protocol_version"] == 1
    assert (
        heartbeat["authorization_version"]
        == ready["capabilities"]["authorization_version"]
    )
    RoomHeartbeatMessage.model_validate(heartbeat)


def test_presence_clears_when_access_is_revoked(harness: RoomHarness) -> None:
    project_id = harness.project_id

    with harness.open_room(project_id) as owner_room:
        owner_room.expect("room.ready")
        harness.as_user(harness.cast.editor.id)
        with harness.open_room(project_id) as editor_room:
            editor_ready = editor_room.expect("room.ready")
            owner_room.until("presence.join")

            harness.as_user(harness.cast.owner.id)
            removed = harness.client.delete(
                f"/v1/workspaces/{harness.workspace_id}/members/"
                f"{harness.cast.editor.id}"
            )
            assert removed.status_code == 204

            with pytest.raises(WebSocketDisconnect) as closed:
                while True:
                    assert editor_room.next()["type"] in {
                        "presence.update",
                        "room.heartbeat",
                    }
            assert closed.value.code == 4004
            assert closed.value.reason == "access_revoked"

            leave = owner_room.until("presence.leave")
            assert (
                leave["project_room_session_id"]
                == editor_ready["project_room_session_id"]
            )


# --- Presence ----------------------------------------------------------------


def test_presence_reaches_the_other_participant_and_the_next_joiner(
    harness: RoomHarness,
) -> None:
    project_id = harness.project_id

    with harness.open_room(project_id) as owner_room:
        owner_ready = owner_room.expect("room.ready")
        assert len(owner_ready["participants"]) == 1

        harness.as_user(harness.cast.editor.id)
        with harness.open_room(project_id) as editor_room:
            editor_ready = editor_room.expect("room.ready")
            assert {
                item["project_room_session_id"] for item in editor_ready["participants"]
            } == {
                owner_ready["project_room_session_id"],
                editor_ready["project_room_session_id"],
            }

            join = owner_room.until("presence.join")
            assert (
                join["participant"]["project_room_session_id"]
                == editor_ready["project_room_session_id"]
            )
            assert join["participant"]["actor"]["actor_id"] == str(
                harness.cast.editor.id
            )
            # A join says who is here, not where they are: the Graph and the cursor
            # arrive with the first update.
            assert join["participant"]["graph_id"] is None
            assert join["participant"]["cursor"] is None

            editor_room.send(
                {
                    "protocol_version": 1,
                    "type": "presence.update",
                    "graph_id": FLOW_GRAPH_ID,
                    "presence_sequence": 1,
                    "cursor": {"x": 12.5, "y": -4.0},
                    "selected_node_ids": ["first"],
                    "selected_edge_ids": [],
                    "activity": "moving_nodes",
                    "activity_target_ids": ["first"],
                    "transient_node_positions": [
                        {"node_id": "first", "x": 3.0, "y": 4.0}
                    ],
                }
            )
            update = owner_room.until("presence.update")
            assert update["participant"]["presence_sequence"] == 1
            assert update["participant"]["cursor"] == {"x": 12.5, "y": -4.0}
            assert update["participant"]["selected_node_ids"] == ["first"]
            assert update["participant"]["activity"] == "moving_nodes"
            assert update["participant"]["transient_node_positions"] == [
                {"node_id": "first", "x": 3.0, "y": 4.0}
            ]

        leave = owner_room.until("presence.leave")
        assert (
            leave["project_room_session_id"] == editor_ready["project_room_session_id"]
        )


def test_a_frame_that_is_not_a_room_message_closes_the_room_with_protocol_error(
    harness: RoomHarness,
) -> None:
    """One bad frame ends the connection, not the Project.

    The client that sent it reconnects; the participants it shares the room with keep
    their sequence, their head and their Runs.
    """

    project_id = harness.project_id
    with harness.open_room(project_id) as owner_room:
        owner_ready = owner_room.expect("room.ready")
        harness.as_user(harness.cast.viewer.id)
        with harness.open_room(project_id) as viewer_room:
            viewer_room.expect("room.ready")
            viewer_room.send({"protocol_version": 1, "type": "graph.command.submit"})
            with pytest.raises(WebSocketDisconnect) as closed:
                viewer_room.next()

            assert closed.value.code == 4008
            assert closed.value.reason == "protocol_error"

            # The participant it shared the room with is untouched by it: same head,
            # next batch accepted one after it.
            owner_room.send(rename(owner_ready, "Unbothered"))
            accepted = owner_room.until("project.command.accepted")
            assert accepted["sequence"] == (
                owner_ready["head"]["collaboration_sequence"] + 1
            )


# --- Runs in the room --------------------------------------------------------


def test_both_participants_see_both_runs_start_and_finish(
    harness: RoomHarness,
) -> None:
    """Two Runs, one Project, two participants: neither view is private.

    The Project does not narrow to one execution: two demands are active at once and
    every participant derives the same canvas from the same frames.
    """

    project_id = harness.project_id

    with harness.open_room(project_id) as owner_room:
        owner_ready = owner_room.expect("room.ready")
        assert owner_ready["active_runs"] == []
        harness.as_user(harness.cast.editor.id)
        with harness.open_room(project_id) as editor_room:
            editor_ready = editor_room.expect("room.ready")
            assert editor_ready["active_runs"] == []

            harness.as_user(harness.cast.owner.id)
            first = _start(harness, project_id, FIRST).json()
            second = _start(harness, project_id, SECOND).json()
            assert harness.runner.started(FIRST).wait(10)
            assert harness.runner.started(SECOND).wait(10)

            assert sorted(active_ids(harness, project_id)) == sorted(
                [first["id"], second["id"]]
            )
            for room in (owner_room, editor_room):
                started = {room.until("run.started")["run"]["run_id"] for _ in range(2)}
                assert started == {first["id"], second["id"]}

            # A third participant joining now learns about both from the ready frame.
            harness.as_user(harness.cast.viewer.id)
            with harness.open_room(project_id) as viewer_room:
                ready = viewer_room.expect("room.ready")
                assert {item["run_id"] for item in ready["active_runs"]} == {
                    first["id"],
                    second["id"],
                }
                assert {
                    item["starter"]["actor_id"] for item in ready["active_runs"]
                } == {str(harness.cast.owner.id)}
                # ... and still sees the instance states of every Graph it loaded.
                assert {item["node_id"] for item in ready["instances"]} == {
                    FIRST,
                    SECOND,
                }
                assert {item["state"] for item in ready["instances"]} == {"running"}

            harness.runner.release(FIRST, SECOND)
            for room in (owner_room, editor_room):
                statuses = {}
                while len(statuses) < 2:
                    message = room.next()
                    if message["type"] == "run.finished":
                        statuses[message["run_id"]] = message["status"]
                assert statuses == {first["id"]: "succeeded", second["id"]: "succeeded"}


def test_an_edit_while_a_run_is_gated_leaves_the_instance_stale_for_everyone(
    harness: RoomHarness,
) -> None:
    """Edits never lock the document, and the edit is what makes the result stale.

    The computation stores what it produced under the fingerprint it started with; the
    instance the edit moved reads stale from the moment the batch is accepted, and
    stays stale after that result lands, because the document asks for a different
    fingerprint now.
    """

    project_id = harness.project_id
    started = _start(harness, project_id, FIRST).json()
    assert harness.runner.started(FIRST).wait(10)

    with harness.open_room(project_id) as room:
        # This Run started before the join, so the participant learns of it from the
        # ready frame: there is no live run.started for news it missed.
        ready = room.expect("room.ready")
        assert [item["run_id"] for item in ready["active_runs"]] == [started["id"]]
        running = {item["node_id"]: item for item in ready["instances"]}
        assert running[FIRST]["state"] == "running"

        room.send(
            command_batch(
                ready,
                [
                    InGraphCommand(
                        graph_id=FLOW_GRAPH_ID,
                        command=UpdateNodeConfigurationCommand(
                            node_id=FIRST,
                            field="value",
                            value=2,
                            expected_value=1,
                        ),
                    )
                ],
            )
        )
        room.until("project.command.accepted")
        # A live Run makes its own claims about these instances, so the room can
        # report the run's view of them around the edit's delta. What the participant
        # must never miss is the moved instance going stale, under a new fingerprint.
        moved = _stale_delta_for(room, FIRST)
        assert moved["fingerprint"] != running[FIRST]["fingerprint"]

        harness.runner.release(FIRST)
        finished = room.until("run.finished")
        assert finished["run_id"] == started["id"]
        assert finished["status"] == "succeeded"

    after = _instances(harness, project_id)
    assert after[FIRST]["state"] == "stale"
    assert after[FIRST]["last_result_fingerprint"] is not None
    assert after[FIRST]["fingerprint"] == moved["fingerprint"]


def test_an_accepted_batch_reaches_a_participant_that_did_not_send_it(
    harness: RoomHarness,
) -> None:
    """The room's whole purpose: one accepted batch, every participant told."""

    project_id = harness.project_id

    with harness.open_room(project_id) as owner_room:
        harness.as_user(harness.cast.editor.id)
        with harness.open_room(project_id) as editor_room:
            editor_ready = editor_room.expect("room.ready")
            owner_room.expect("room.ready")

            editor_room.send(rename(editor_ready, "Seen by both"))
            accepted = editor_room.expect("project.command.accepted")
            editor_room.expect("project.command.receipt")
            editor_room.expect("instances.changed")

            peer_accepted = owner_room.until("project.command.accepted")
            assert peer_accepted["command_id"] == accepted["command_id"]
            assert peer_accepted["sequence"] == accepted["sequence"]
            # The receipt is private to the submitter; the peer reads the accepted
            # batch and the instance delta the batch owes, with presence traffic
            # about the join in between.
            peer_changed = owner_room.until("instances.changed")
            assert peer_changed["head_sequence"] == accepted["sequence"]
            assert peer_changed["removed"] == []
            assert {item["node_id"] for item in peer_changed["changed"]} == {
                FIRST,
                SECOND,
            }


# --- Whoever ends the room, it leaves ---------------------------------------


def _registered_room_sessions(harness: RoomHarness) -> list[ProjectRoomSession]:
    hub = harness.resources.project_room_hub
    return [
        member.session
        for room in hub._rooms.values()
        for member in room.values()  # noqa: SLF001 - the claim is about the registry
    ]


def test_a_room_cancelled_while_it_was_working_still_leaves(
    harness: RoomHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A room cancelled mid-command still leaves, and still tells the peer.

    This is the CI race itself. ``WebSocketTestSession.__exit__`` sends the disconnect and
    then cancels the session's task group, and when the endpoint is parked in work — here,
    a committed command — the cancellation, not the disconnect, is what ends it. A
    ``CancelledError`` is neither a ``WebSocketDisconnect`` nor an ``Exception``, so the
    departure written in those two arms never ran: the session stayed registered, its
    sender task outlived its socket, and the peer went on believing it was there.
    """

    project_id = harness.project_id
    collaboration = harness.resources.collaboration
    inside_a_command = asyncio.Event()
    abandoned = asyncio.Event()  # set by nobody: the command ends when the room does

    async def stuck_submit(*_args: object, **_kwargs: object) -> object:
        inside_a_command.set()
        await abandoned.wait()
        raise AssertionError("unreachable")

    monkeypatch.setattr(collaboration, "submit_commands", stuck_submit)

    with harness.open_room(project_id) as owner_room:
        owner_room.expect("room.ready")
        harness.as_user(harness.cast.editor.id)
        editor = harness.connect_room(project_id)
        editor.__enter__()
        ready = editor.receive_json()
        assert ready["type"] == "room.ready"
        owner_room.until("presence.join")

        editor.send_json(rename(ready, "Busy"))
        harness.client.portal.call(inside_a_command.wait)

        # The way a client leaves in practice: the session is abandoned from the client
        # thread, which cancels the task the room is running on.
        failures: list[BaseException] = []

        def abandon() -> None:
            try:
                editor.__exit__(None, None, None)
            except BaseException as exc:  # noqa: BLE001 - reported below
                failures.append(exc)

        thread = threading.Thread(target=abandon, name="abandon-the-room")
        thread.start()
        thread.join(timeout=20)
        assert not thread.is_alive(), "abandoning the room never returned"
        assert failures == []

        leave = owner_room.until("presence.leave")
        assert leave["project_room_session_id"] == ready["project_room_session_id"]

    assert _registered_room_sessions(harness) == []


@pytest.mark.timeout(60)
def test_a_room_the_test_forgot_to_close_cannot_outlive_the_harness(
    tmp_path: Path, settings: Settings
) -> None:
    """A session left open is the one thing that makes teardown never return.

    ``TestClient.__exit__`` joins the thread running the app, and an open room session is a
    task on that loop which only the session's own ``__exit__`` will cancel. The CI job died
    exactly there: the test thread in ``thread.join()``, the app loop idle, 45 minutes gone
    and nothing printed. The cap is the point of the marker — if this regresses it names
    itself in a minute instead of eating the job.
    """

    with room_harness(tmp_path, settings, concurrency=4) as harness:
        session = harness.connect_room(harness.project_id)
        session.__enter__()
        assert session.receive_json()["type"] == "room.ready"
        # The test forgets it: no ``with``, no ``__exit__``. The harness owns what it
        # handed out, so it closes the room on the way out.
        assert harness.open_sessions == [session]

    # Reaching this line is the claim: leaving the harness returned.
    assert harness.open_sessions == []


# --- The hub by itself -------------------------------------------------------


def _session(
    websocket: AsyncMock,
    *,
    project_id: UUID,
    actor_id: UUID = UUID(int=1),
    display_name: str = "Owner",
    color: str = "indigo",
) -> ProjectRoomSession:
    return ProjectRoomSession(
        workspace_id=UUID(int=7),
        project_id=project_id,
        project_room_session_id=uuid4(),
        actor_user_id=actor_id,
        credential_reference="test-session",
        authorization_version=1,
        actor_presentation=ActorPresentation(
            actor_id=actor_id,
            display_name=display_name,
            color=color,
        ),
        websocket=websocket,
    )


def _mock_socket() -> AsyncMock:
    websocket = AsyncMock()
    websocket.application_state = WebSocketState.CONNECTED
    return websocket


def _raising_socket(
    *, error: BaseException | None = None, disconnected: bool = False
) -> AsyncMock:
    """A socket the moment it is written to proves it is gone.

    ``disconnected`` is the quiet one: the peer closed its side, so the socket reports a
    disconnect instead of an error, and the sender has nothing to complain about.
    """

    websocket = _mock_socket()
    if disconnected:
        websocket.application_state = WebSocketState.DISCONNECTED
        return websocket

    async def _dead(_payload: dict) -> None:
        raise error or RuntimeError("stream is closed")

    websocket.send_json.side_effect = _dead
    return websocket


def _drain(session: ProjectRoomSession) -> list[dict]:
    """Everything a session's queue still holds, as the frames its peer would see."""
    frames: list[dict] = []
    while not session.outbound.empty():
        message = session.outbound.get_nowait()
        if message is not None:
            frames.append(message.model_dump(mode="json"))
    return frames


def test_presence_rate_limit_and_stale_sequence_are_dropped() -> None:
    async def exercise() -> None:
        hub = ProjectRoomHub(presence_max_updates_per_second=20.0)
        project_id = uuid4()
        session = _session(_mock_socket(), project_id=project_id)
        peer = _session(
            _mock_socket(),
            project_id=project_id,
            actor_id=UUID(int=12),
            display_name="Editor",
        )
        await hub.join(session)
        await hub.join(peer)
        await hub.register_presence(session)
        await hub.register_presence(peer)
        while not peer.outbound.empty():
            peer.outbound.get_nowait()

        first = await hub.apply_presence_update(
            session,
            PresenceUpdateSubmitMessage(
                presence_sequence=1, cursor={"x": 1.0, "y": 2.0}
            ),
        )
        assert first is not None
        stale = await hub.apply_presence_update(
            session,
            PresenceUpdateSubmitMessage(
                presence_sequence=1, cursor={"x": 9.0, "y": 9.0}
            ),
        )
        assert stale is None
        burst = await hub.apply_presence_update(
            session,
            PresenceUpdateSubmitMessage(
                presence_sequence=2, cursor={"x": 3.0, "y": 4.0}
            ),
        )
        assert burst is None
        await hub.shutdown()

    asyncio.run(exercise())


def test_a_late_presence_update_cannot_recreate_a_closed_participant() -> None:
    async def exercise() -> None:
        hub = ProjectRoomHub()
        session = _session(_mock_socket(), project_id=uuid4())
        await hub.join(session)
        await hub.register_presence(session)
        first = await hub.apply_presence_update(
            session,
            PresenceUpdateSubmitMessage(
                presence_sequence=1, cursor={"x": 3.0, "y": 4.0}
            ),
        )
        assert first is not None
        await hub.close_session(session, code=1000, reason="left")

        late = await hub.apply_presence_update(
            session,
            PresenceUpdateSubmitMessage(
                presence_sequence=2, cursor={"x": 9.0, "y": 9.0}
            ),
        )
        assert late is None
        assert (
            await hub.participants_for(
                workspace_id=session.workspace_id, project_id=session.project_id
            )
            == []
        )
        await hub.shutdown()

    asyncio.run(exercise())


def test_a_slow_consumer_is_disconnected_instead_of_growing_an_unbounded_queue() -> (
    None
):
    async def exercise() -> None:
        hub = ProjectRoomHub()
        websocket = _mock_socket()
        session = _session(websocket, project_id=uuid4())
        await hub.join(session)
        filler = RoomHeartbeatMessage(authorization_version=1)
        for _ in range(OUTBOUND_QUEUE_MAXSIZE):
            session.outbound.put_nowait(filler)

        await hub.deliver_private(
            session, RoomHeartbeatMessage(authorization_version=1)
        )

        assert session.closed is True
        websocket.close.assert_awaited()
        kwargs = websocket.close.await_args.kwargs
        assert kwargs["code"] == CLOSE_SLOW_CONSUMER[0]
        assert kwargs["reason"] == CLOSE_SLOW_CONSUMER[1]
        await hub.shutdown()

    asyncio.run(exercise())


def test_an_activated_session_has_exactly_one_fifo_writer() -> None:
    async def exercise() -> None:
        hub = ProjectRoomHub()
        websocket = _mock_socket()
        session = _session(websocket, project_id=uuid4())
        await hub.join(session)
        await hub.activate(session)

        blocked = asyncio.Event()

        async def blocking_send(payload: dict) -> None:
            del payload
            await blocked.wait()

        websocket.send_json.side_effect = blocking_send
        first = RoomHeartbeatMessage(authorization_version=1)
        second = RoomHeartbeatMessage(authorization_version=2)
        await hub.deliver_private(session, first)
        await hub.deliver_private(session, second)
        await asyncio.sleep(0.05)
        blocked.set()
        await asyncio.sleep(0.05)

        calls = websocket.send_json.await_args_list
        assert [call.args[0]["authorization_version"] for call in calls] == [1, 2]
        assert len(calls) == 2
        assert session.sender_task is not None
        await hub.shutdown()

    asyncio.run(exercise())


def test_closing_a_project_room_closes_every_participant() -> None:
    async def exercise() -> None:
        hub = ProjectRoomHub()
        project_id = uuid4()
        sessions = [
            _session(_mock_socket(), project_id=project_id, actor_id=UUID(int=number))
            for number in (1, 2)
        ]
        for session in sessions:
            await hub.join(session)
            await hub.register_presence(session)
        await hub.close_project(
            workspace_id=sessions[0].workspace_id, project_id=project_id
        )
        assert all(session.closed for session in sessions)
        assert (
            await hub.participants_for(
                workspace_id=sessions[0].workspace_id, project_id=project_id
            )
            == []
        )
        await hub.shutdown()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    ("socket", "label"),
    [
        (_raising_socket(), "a socket that raised"),
        (_raising_socket(disconnected=True), "a socket already closed"),
        (
            _raising_socket(error=WebSocketDisconnect(code=1000, reason="gone")),
            "a client that disconnected",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_sender_that_stops_takes_its_session_out_of_the_room(
    socket: AsyncMock, label: str
) -> None:
    """However the single writer stops, that participant is finished with the room.

    The three quiet exits used to `return` and leave the session registered: still in
    presence, still fanned out to, its queue filling with frames no one will ever send —
    and its peers never told. An error path already closed the session; the quiet ones
    ({label}) did not.
    """

    async def exercise() -> None:
        hub = ProjectRoomHub()
        project_id = uuid4()
        dying = _session(socket, project_id=project_id)
        peer = _session(_mock_socket(), project_id=project_id, actor_id=UUID(int=12))
        told_peer = asyncio.Event()

        async def record_frame(payload: dict) -> None:
            if payload.get("type") == "presence.leave":
                told_peer.set()

        peer.websocket.send_json.side_effect = record_frame
        for participant in (dying, peer):
            await hub.join(participant)
            await hub.register_presence(participant)
            await hub.activate(participant)

        await hub.publish_model(
            workspace_id=dying.workspace_id,
            project_id=project_id,
            message=RoomHeartbeatMessage(authorization_version=1),
        )
        # The sender stopping is the event to wait on, and it is the last thing the
        # retirement yields on: the session is marked dead, dropped from the room and its
        # peers offered `presence.leave` before the sender is awaited. The deadline is a
        # failure guard, not the mechanism — a hub that never finishes its sender is what
        # this test is for, and it must name itself rather than hang.
        assert dying.sender_task is not None, label
        await asyncio.wait_for(asyncio.wait({dying.sender_task}), timeout=5)
        await asyncio.wait_for(told_peer.wait(), timeout=5)

        assert dying.closed is True, label
        assert dying.sender_task.done(), label
        # The peer being told is the outward half of the claim. That frame leaves through
        # the peer's own sender, so the peer's socket is where the event is; the hub's
        # queue is not, because that sender is consuming it as fast as it is offered.
        remaining = await hub.participants_for(
            workspace_id=dying.workspace_id, project_id=project_id
        )
        assert [item.project_room_session_id for item in remaining] == [
            peer.project_room_session_id
        ], label
        delivered = [call.args[0] for call in peer.websocket.send_json.await_args_list]
        assert "presence.leave" in [frame["type"] for frame in delivered], (
            label,
            delivered,
        )
        await hub.shutdown()

    asyncio.run(exercise())


def test_hub_shutdown_waits_for_the_sender_it_cancelled() -> None:
    """Shutdown returns with the sender finished, not merely asked to stop.

    A sender that was only cancelled is still a live task when the hub is done with it,
    and the code that closes the event loop afterwards waits for every task on it without
    a deadline of its own. That is how a room becomes a process that cannot be stopped.
    """

    async def exercise() -> None:
        hub = ProjectRoomHub()
        writing = asyncio.Event()  # the sender has reached the socket
        silent_peer = asyncio.Event()  # and the socket is not going to answer

        async def parked_send(_payload: dict) -> None:
            writing.set()
            await silent_peer.wait()

        websocket = _mock_socket()
        websocket.send_json.side_effect = parked_send
        session = _session(websocket, project_id=uuid4())
        await hub.join(session)
        await hub.activate(session)
        await hub.deliver_private(
            session, RoomHeartbeatMessage(authorization_version=1)
        )
        await writing.wait()

        # Bounded so a hub that waits forever says so; the sender is parked on an event
        # with no timeout of its own, so nothing here is timed by a clock.
        await asyncio.wait_for(hub.shutdown(), timeout=2)

        assert session.sender_task is not None
        assert session.sender_task.done()

    asyncio.run(exercise())


def test_hub_shutdown_does_not_wait_forever_on_a_sender_that_ignores_cancellation(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The deadline is the last resort, and it is loud.

    A sender that swallows its cancellation must cost a bounded wait and a log line, not
    the process. Silence here is a container that gets SIGKILLed with no explanation.
    """

    async def exercise() -> None:
        monkeypatch.setattr(hub_module, "SENDER_STOP_TIMEOUT_SECONDS", 0.05)
        hub = ProjectRoomHub()
        writing = asyncio.Event()
        let_go = asyncio.Event()

        async def unstoppable(_payload: dict) -> None:
            """A sender that swallows its cancellation and parks again, on an event.

            No clock in it: every cancellation the hub sends returns it to `let_go`, so the
            only thing that ever ends this task is the release the test performs.
            """

            writing.set()
            while True:
                try:
                    await let_go.wait()
                    return
                except asyncio.CancelledError:
                    continue

        websocket = _mock_socket()
        websocket.send_json.side_effect = unstoppable
        session = _session(websocket, project_id=uuid4())
        await hub.join(session)
        await hub.activate(session)
        await hub.deliver_private(
            session, RoomHeartbeatMessage(authorization_version=1)
        )
        await writing.wait()
        runaway = session.sender_task
        assert runaway is not None
        caplog.set_level(logging.ERROR, logger="grafy_api.realtime.hub")
        try:
            await asyncio.wait_for(hub.shutdown(), timeout=2)

            reported = [
                record.getMessage()
                for record in caplog.records
                if record.getMessage().startswith("graph_room_sender_failed")
            ]
            assert len(reported) == 1, reported
            assert "sender_did_not_stop" in reported[0]
        finally:
            # Nothing here outlives the test. A sender this hub gave up on is exactly the
            # task that makes a loop's final cleanup wait forever, so it is released and
            # reaped whether the assertions held or not.
            let_go.set()
            runaway.cancel()
            await asyncio.wait({runaway}, timeout=2)

    asyncio.run(exercise())


# --- Small helpers -----------------------------------------------------------


def _start(harness: RoomHarness, project_id: UUID, node_id: str):
    return harness.post(
        f"/projects/{project_id}/runs",
        json={"graph_id": FLOW_GRAPH_ID, "targets": [{"node_id": node_id}]},
    )


def active_ids(harness: RoomHarness, project_id: UUID) -> list[str]:
    response = harness.get(f"/projects/{project_id}/runs?active=true")
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["runs"]]


def _instances(harness: RoomHarness, project_id: UUID) -> dict[str, dict[str, Any]]:
    response = harness.get(f"/projects/{project_id}/graphs/{FLOW_GRAPH_ID}/instances")
    assert response.status_code == 200, response.text
    return {item["key"]["node_id"]: item for item in response.json()["instances"]}


def _change_role(harness: RoomHarness, user_id: UUID, role: WorkspaceRole):
    response = harness.client.patch(
        f"/v1/workspaces/{harness.workspace_id}/members/{user_id}",
        json={"role": role.value},
    )
    assert response.status_code == 200, response.text
    return response


def _next_command_frame(room: Room, *, named: str, limit: int = 20) -> dict[str, Any]:
    """The participant's next accepted batch, failing on any frame naming `named`.

    Presence frames legitimately arrive between two batches, so this skips those. It
    does not tolerate a frame about `named`: a command this participant never sent
    must not be broadcast to it at all.
    """

    for _ in range(limit):
        frame = room.next()
        if frame.get("command_id") == named:
            pytest.fail(f"a command this participant never sent reached it: {frame}")
        if frame["type"] == "project.command.accepted":
            return frame
    raise AssertionError(f"no accepted batch within {limit} frames")


def _stale_delta_for(room: Room, node_id: str, *, limit: int = 8) -> dict[str, Any]:
    """The next instance delta that reports `node_id` stale."""

    for _ in range(limit):
        frame = room.next()
        if frame["type"] != "instances.changed":
            continue
        for item in frame["changed"]:
            if item["node_id"] == node_id and item["state"] == "stale":
                return item
    raise AssertionError(f"no delta reported {node_id} stale within {limit} frames")


def _head_of(harness: RoomHarness, project_id: UUID) -> dict[str, Any]:
    """The head as a joining participant sees it.

    There is no HTTP head route in this change — the Project head and command routes
    belong to the Project routes — so the suite reads it the way a client that is not
    already in the room can: by joining it.
    """

    with harness.open_room(project_id) as room:
        return room.expect("room.ready")["head"]
