"""Phase 4 authenticated graph-room WebSocket protocol tests."""

import asyncio
import json
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from queue import Queue
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from pydantic import SecretStr
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect, WebSocketState

from grafy_api.settings import Settings
from grafy_api.v1.models import PluginReleasePinModel
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_api.v1.routes.workspaces.models import WorkspaceMemberRoleRequest
from grafy_api.realtime.hub import (
    CLOSE_SLOW_CONSUMER,
    OUTBOUND_QUEUE_MAXSIZE,
    GraphRoomHub,
    GraphRoomSession,
)
from grafy_api.realtime.protocol import (
    ActorPresentation,
    PresenceUpdateSubmitMessage,
    RoomHeartbeatMessage,
    RoomReadyMessage,
)
from grafy_api.v1.routes.collaboration.views import websocket_browser_actor
from grafy_api.execution.requests import RunRequest
from grafy_api.graph_contracts import (
    CreateSavedGraphRequest,
    SubmitGraphCommandRequest,
    UpdateSavedGraphRequest,
)
from grafy_core.domain.collaboration import (
    RenameGraphCommand,
    UpdateNodePluginReleaseCommand,
)
from grafy_core.domain.identity import ActorContext, User, Workspace, WorkspaceRole
from grafy_core.domain.plugin_identity import PluginReleaseScope
from grafy_core.domain.saved_graphs import (
    GraphPoint,
    SavedGraphDocument,
    SavedGraphNode,
    SavedGraphPluginReleasePin,
)
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.support.clients import GrafyApi
from tests.support.factories.identity import IdentitySeeder
from tests.support.identity import TEST_USER_ID, WORKSPACE_ID, ActorSwitcher
from tests.testkit import client_with_overrides, create_db_url, db

FIXTURES = Path(__file__).parents[2] / "fixtures"


@dataclass(frozen=True, slots=True)
class RoomPopulation:
    """The seeded room cast: one shared workspace and its members."""

    workspace: Workspace
    owner: User
    editor: User
    viewer: User
    stranger: User


type RoomClient = tuple[GrafyApi, ActorSwitcher, RoomPopulation]


async def _seed_room_population(database_url: str) -> RoomPopulation:
    async with db(database_url) as database:
        seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
        owner = await seeder.user(email="owner@example.test", display_name="Owner")
        editor = await seeder.user(email="editor@example.test", display_name="Editor")
        viewer = await seeder.user(email="viewer@example.test", display_name="Viewer")
        stranger = await seeder.user(
            email="stranger@example.test", display_name="Stranger"
        )
        workspace = await seeder.workspace(slug="team", name="Team")
        for user, role in (
            (owner, WorkspaceRole.OWNER),
            (editor, WorkspaceRole.EDITOR),
            (viewer, WorkspaceRole.VIEWER),
        ):
            await seeder.membership(user=user, workspace=workspace, role=role)
        return RoomPopulation(
            workspace=workspace,
            owner=owner,
            editor=editor,
            viewer=viewer,
            stranger=stranger,
        )


@pytest.fixture
def room_client(tmp_path: Path, settings: Settings) -> Iterator[RoomClient]:
    database_url = create_db_url(tmp_path, "room.sqlite3")
    population = asyncio.run(_seed_room_population(database_url))
    switcher = ActorSwitcher(population.owner.id)

    with client_with_overrides(
        settings=settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "workspace": tmp_path / "workbench",
                "graph_room_heartbeat_seconds": 0.0,
            }
        ),
        overrides={
            browser_actor: switcher.actor,
            workspace_actor: switcher.actor,
            websocket_browser_actor: switcher.actor,
        },
    ) as client:
        yield GrafyApi(client), switcher, population


@pytest.fixture
def heartbeat_room_client(tmp_path: Path, settings: Settings) -> Iterator[RoomClient]:
    database_url = create_db_url(tmp_path, "room.sqlite3")
    population = asyncio.run(_seed_room_population(database_url))
    switcher = ActorSwitcher(population.owner.id)

    with client_with_overrides(
        settings=settings.model_copy(
            update={
                "database_url": SecretStr(database_url),
                "workspace": tmp_path / "workbench",
                "graph_room_heartbeat_seconds": 0.05,
            }
        ),
        overrides={
            browser_actor: switcher.actor,
            workspace_actor: switcher.actor,
            websocket_browser_actor: switcher.actor,
        },
    ) as client:
        yield GrafyApi(client), switcher, population


def _connect_room(
    api: GrafyApi,
    workspace_id: UUID,
    graph_id: UUID,
    *,
    origin: str = "http://testserver",
):
    # The facade has no typed WebSocket method; the raw TestClient is the
    # escape hatch for the room handshake.
    return api.raw.websocket_connect(
        f"/v1/workspaces/{workspace_id}/graphs/{graph_id}/room",
        headers={"Origin": origin},
    )


def _receive_until(websocket, message_type: str, *, limit: int = 20) -> dict:
    for _ in range(limit):
        message = websocket.receive_json()
        if message["type"] == message_type:
            return message
    raise AssertionError(f"did not receive {message_type!r} within {limit} messages")


def _receive_execution_active_status(
    websocket,
    status: str,
    *,
    limit: int = 20,
) -> dict:
    for _ in range(limit):
        message = websocket.receive_json()
        if (
            message.get("type") == "execution.active"
            and message.get("execution", {}).get("status") == status
        ):
            return message
    raise AssertionError(
        f"did not receive execution.active status={status!r} within {limit} messages"
    )


def _room_session(
    websocket: AsyncMock,
    *,
    graph_id: UUID,
    actor_id: UUID = TEST_USER_ID,
    display_name: str = "Owner",
    color: str = "indigo",
) -> GraphRoomSession:
    return GraphRoomSession(
        workspace_id=WORKSPACE_ID,
        graph_id=graph_id,
        graph_room_session_id=uuid4(),
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


def test_room_ready_fixture_matches_protocol_model() -> None:
    payload = json.loads((FIXTURES / "graph_room_ready.v1.json").read_text())
    ready = RoomReadyMessage.model_validate(payload)
    assert ready.type == "room.ready"
    assert ready.protocol_version == 1
    assert ready.active_execution is None


def test_room_ready_admits_authenticated_member(room_client: RoomClient) -> None:
    api, _switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )

    with _connect_room(api, population.workspace.id, graph.id) as websocket:
        ready = websocket.receive_json()

    assert ready["type"] == "room.ready"
    assert ready["protocol_version"] == 1
    assert ready["workspace_id"] == str(population.workspace.id)
    assert ready["graph_id"] == str(graph.id)
    assert ready["actor"]["actor_id"] == str(population.owner.id)
    assert ready["actor"]["display_name"] == "Owner"
    assert ready["capabilities"]["authorization_version"] >= 1
    assert "edit_graph" in ready["capabilities"]["capabilities"]
    assert ready["head"]["graph_id"] == str(graph.id)
    assert ready["head"]["collaboration_sequence"] == 1
    assert ready["graph_room_session_id"]
    assert len(ready["participants"]) == 1
    assert (
        ready["participants"][0]["graph_room_session_id"]
        == (ready["graph_room_session_id"])
    )
    assert ready["participants"][0]["actor"]["actor_id"] == str(population.owner.id)
    assert ready["active_execution"] is None


def test_join_ready_precedes_command_committed_after_head_snapshot(
    room_client: RoomClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A command committed across the join snapshot window cannot be missed."""

    api, _switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )
    initial_head = workspace_api.graphs.get_head_ok(graph.id)

    # The WS join and the raced HTTP command must hit the same live service
    # instance for the snapshot window to be real, so instrument it directly.
    collaboration = cast(FastAPI, api.raw.app).state.resources.collaboration
    original_get_head = collaboration.get_head
    snapshot_captured = threading.Event()
    release_snapshot = threading.Event()

    async def get_head_after_snapshot(
        *,
        actor: ActorContext,
        workspace_id: UUID,
        graph_id: UUID,
    ):
        head = await original_get_head(
            actor=actor,
            workspace_id=workspace_id,
            graph_id=graph_id,
        )
        snapshot_captured.set()
        await asyncio.to_thread(release_snapshot.wait)
        return head

    monkeypatch.setattr(collaboration, "get_head", get_head_after_snapshot)

    received: Queue[dict] = Queue()
    failures: Queue[Exception] = Queue()
    first_message_received = threading.Event()

    def receive_join_messages() -> None:
        try:
            with _connect_room(api, population.workspace.id, graph.id) as websocket:
                received.put(websocket.receive_json())
                first_message_received.set()
                received.put(websocket.receive_json())
        except Exception as exc:
            failures.put(exc)
            first_message_received.set()

    receiver = threading.Thread(target=receive_join_messages, daemon=True)
    receiver.start()
    try:
        assert snapshot_captured.wait(timeout=5)
        raced_command_id = str(uuid4())
        raced = workspace_api.graphs.submit_command_ok(
            graph.id,
            SubmitGraphCommandRequest(
                command_id=raced_command_id,
                room_epoch=initial_head.room_epoch,
                observed_sequence=initial_head.collaboration_sequence,
                command=RenameGraphCommand(
                    name="Committed during join",
                    expected_name=initial_head.name,
                ),
            ),
        )
    finally:
        release_snapshot.set()

    assert first_message_received.wait(timeout=5)
    if not failures.empty():
        raise failures.get_nowait()
    first = received.get(timeout=1)

    # This later fanout guarantees the receiver terminates even if the raced
    # accepted event was lost; the assertion below then identifies the loss.
    workspace_api.graphs.submit_command_ok(
        graph.id,
        SubmitGraphCommandRequest(
            command_id=uuid4(),
            room_epoch=raced.head.room_epoch,
            observed_sequence=raced.head.collaboration_sequence,
            command=RenameGraphCommand(
                name="Post-ready marker",
                expected_name=raced.head.name,
            ),
        ),
    )

    receiver.join(timeout=5)
    assert not receiver.is_alive()
    if not failures.empty():
        raise failures.get_nowait()
    second = received.get(timeout=1)

    assert first["type"] == "room.ready"
    assert (
        first["head"]["collaboration_sequence"] == initial_head.collaboration_sequence
    )
    assert second["type"] == "graph.command.accepted"
    assert second["command_id"] == raced_command_id
    assert second["sequence"] == raced.head.collaboration_sequence
    assert second["command"]["name"] == "Committed during join"


def test_room_rejects_invalid_origin(room_client: RoomClient) -> None:
    api, _switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )

    with pytest.raises(WebSocketDenialResponse) as denied:
        with _connect_room(
            api,
            population.workspace.id,
            graph.id,
            origin="http://evil.example",
        ):
            pass
    assert denied.value.status_code == 403


def test_room_rejects_non_member(room_client: RoomClient) -> None:
    api, switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )
    switcher.as_user(population.stranger.id)

    with pytest.raises(WebSocketDenialResponse) as denied:
        with _connect_room(api, population.workspace.id, graph.id):
            pass
    assert denied.value.status_code == 404


def test_two_sessions_converge_on_accepted_sequence_and_head(
    room_client: RoomClient,
) -> None:
    """Phase 4 exit: two sessions on the same room observe one accepted head."""

    api, switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )

    with _connect_room(api, population.workspace.id, graph.id) as owner_ws:
        owner_ready = owner_ws.receive_json()
        switcher.as_user(population.editor.id)
        with _connect_room(api, population.workspace.id, graph.id) as editor_ws:
            editor_ready = editor_ws.receive_json()
            assert editor_ready["type"] == "room.ready"
            assert editor_ready["workspace_id"] == owner_ready["workspace_id"]
            assert editor_ready["graph_id"] == owner_ready["graph_id"]
            assert (
                editor_ready["head"]["collaboration_sequence"]
                == owner_ready["head"]["collaboration_sequence"]
            )

            command_id = str(uuid4())
            expected_sequence = editor_ready["head"]["collaboration_sequence"] + 1
            editor_ws.send_json(
                {
                    "protocol_version": 1,
                    "type": "graph.command.submit",
                    "command_id": command_id,
                    "room_epoch": editor_ready["head"]["room_epoch"],
                    "observed_sequence": editor_ready["head"]["collaboration_sequence"],
                    "command": {
                        "kind": "rename_graph",
                        "name": "Renamed live",
                        "expected_name": editor_ready["head"]["name"],
                    },
                }
            )

            editor_accepted = _receive_until(editor_ws, "graph.command.accepted")
            editor_receipt = _receive_until(editor_ws, "graph.command.receipt")
            assert editor_accepted["sequence"] == expected_sequence
            assert editor_receipt["accepted_sequence"] == expected_sequence
            assert editor_receipt["current_sequence"] == expected_sequence
            assert editor_receipt["deduplicated"] is False

            owner_accepted = _receive_until(owner_ws, "graph.command.accepted")
            assert owner_accepted["command_id"] == command_id
            assert owner_accepted["sequence"] == expected_sequence
            assert owner_accepted["command"]["name"] == "Renamed live"
            assert owner_accepted["actor"]["actor_id"] == str(population.editor.id)

    head = workspace_api.graphs.get_head_ok(graph.id)
    assert head.collaboration_sequence == expected_sequence
    assert head.name == "Renamed live"


def test_reconnect_idempotent_retry_does_not_double_apply(
    room_client: RoomClient,
) -> None:
    """Phase 4 exit: reconnect + same command id returns receipt without rebroadcast."""

    api, switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )
    command_id = str(uuid4())

    with _connect_room(api, population.workspace.id, graph.id) as first_ws:
        ready = first_ws.receive_json()
        submit = {
            "protocol_version": 1,
            "type": "graph.command.submit",
            "command_id": command_id,
            "room_epoch": ready["head"]["room_epoch"],
            "observed_sequence": ready["head"]["collaboration_sequence"],
            "command": {
                "kind": "rename_graph",
                "name": "Once only",
                "expected_name": ready["head"]["name"],
            },
        }
        first_ws.send_json(submit)
        first_accepted = _receive_until(first_ws, "graph.command.accepted")
        first_receipt = _receive_until(first_ws, "graph.command.receipt")
        assert first_receipt["outcome"] == "accepted"
        accepted_sequence = first_accepted["sequence"]

    switcher.as_user(population.editor.id)
    with _connect_room(api, population.workspace.id, graph.id) as peer_ws:
        peer_ready = peer_ws.receive_json()
        assert peer_ready["head"]["collaboration_sequence"] == accepted_sequence
        assert peer_ready["head"]["name"] == "Once only"

        switcher.as_user(population.owner.id)
        with _connect_room(api, population.workspace.id, graph.id) as retry_ws:
            retry_ready = retry_ws.receive_json()
            assert retry_ready["head"]["collaboration_sequence"] == accepted_sequence
            retry_ws.send_json(submit)
            receipt = _receive_until(retry_ws, "graph.command.receipt")
            assert receipt["outcome"] == "idempotent_replay"
            assert receipt["deduplicated"] is True
            assert receipt["accepted_sequence"] == accepted_sequence
            assert receipt["current_sequence"] == accepted_sequence

            # Peer must not observe a second accepted fanout for the retry.
            peer_ws.send_json(
                {
                    "protocol_version": 1,
                    "type": "graph.command.submit",
                    "command_id": str(uuid4()),
                    "room_epoch": peer_ready["head"]["room_epoch"],
                    "observed_sequence": accepted_sequence,
                    "command": {
                        "kind": "rename_graph",
                        "name": "Peer marker",
                        "expected_name": "Once only",
                    },
                }
            )
            accepted = _receive_until(peer_ws, "graph.command.accepted")
            receipt = _receive_until(peer_ws, "graph.command.receipt")
            assert accepted["command"]["name"] == "Peer marker"
            assert accepted["sequence"] == accepted_sequence + 1
            assert receipt["accepted_sequence"] == accepted_sequence + 1

    head = workspace_api.graphs.get_head_ok(graph.id)
    assert head.collaboration_sequence == accepted_sequence + 1
    assert head.name == "Peer marker"


def test_viewer_command_is_rejected_without_fanout(room_client: RoomClient) -> None:
    api, switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )

    with _connect_room(api, population.workspace.id, graph.id) as owner_ws:
        owner_ws.receive_json()
        switcher.as_user(population.viewer.id)
        with _connect_room(api, population.workspace.id, graph.id) as viewer_ws:
            ready = viewer_ws.receive_json()
            assert "edit_graph" not in ready["capabilities"]["capabilities"]
            viewer_ws.send_json(
                {
                    "protocol_version": 1,
                    "type": "graph.command.submit",
                    "command_id": str(uuid4()),
                    "room_epoch": ready["head"]["room_epoch"],
                    "observed_sequence": ready["head"]["collaboration_sequence"],
                    "command": {
                        "kind": "rename_graph",
                        "name": "Nope",
                        "expected_name": ready["head"]["name"],
                    },
                }
            )
            rejected = _receive_until(viewer_ws, "graph.command.rejected")
            assert rejected["error_code"] == "forbidden"


def test_role_change_closes_with_permissions_changed(room_client: RoomClient) -> None:
    api, switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )
    switcher.as_user(population.editor.id)

    with _connect_room(api, population.workspace.id, graph.id) as editor_ws:
        editor_ws.receive_json()
        switcher.as_user(population.owner.id)
        workspace_api.change_member_role_ok(
            population.editor.id,
            WorkspaceMemberRoleRequest(role=WorkspaceRole.VIEWER),
        )

        with pytest.raises(WebSocketDisconnect) as closed:
            editor_ws.receive_json()
        assert closed.value.code == 4003
        assert closed.value.reason == "permissions_changed"

    # Reconnect as viewer and confirm fresh capability snapshot.
    switcher.as_user(population.editor.id)
    with _connect_room(api, population.workspace.id, graph.id) as viewer_ws:
        ready = viewer_ws.receive_json()
    assert "edit_graph" not in ready["capabilities"]["capabilities"]
    assert "view_graph" in ready["capabilities"]["capabilities"]
    assert ready["capabilities"]["authorization_version"] >= 2


def test_http_epoch_reset_rehydrates_connected_sessions(
    room_client: RoomClient,
) -> None:
    api, _switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )
    revision = workspace_api.graphs.get_ok(graph.id).revision

    with _connect_room(api, population.workspace.id, graph.id) as websocket:
        ready = websocket.receive_json()
        workspace_api.graphs.update_ok(
            graph.id,
            UpdateSavedGraphRequest(
                name="Replaced document",
                document=SavedGraphDocument(),
                expected_revision=revision,
            ),
        )
        rehydrate = _receive_until(websocket, "room.rehydrate")
        assert rehydrate["reason"] == "epoch_reset"
        assert rehydrate["head"]["name"] == "Replaced document"
        assert rehydrate["head"]["collaboration_sequence"] == 0
        assert rehydrate["head"]["room_epoch"] != ready["head"]["room_epoch"]


def test_http_command_publishes_to_room(room_client: RoomClient) -> None:
    api, _switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )
    command_id = str(uuid4())

    with _connect_room(api, population.workspace.id, graph.id) as websocket:
        ready = websocket.receive_json()
        workspace_api.graphs.submit_command_ok(
            graph.id,
            SubmitGraphCommandRequest(
                command_id=command_id,
                room_epoch=ready["head"]["room_epoch"],
                observed_sequence=ready["head"]["collaboration_sequence"],
                command=RenameGraphCommand(
                    name="HTTP rename",
                    expected_name=ready["head"]["name"],
                ),
            ),
        )
        accepted = _receive_until(websocket, "graph.command.accepted")
        assert accepted["command_id"] == command_id
        assert accepted["command"]["name"] == "HTTP rename"


def test_http_plugin_release_update_publishes_semantic_command(
    room_client: RoomClient,
) -> None:
    api, _switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    current_pin = SavedGraphPluginReleasePin(
        scope=PluginReleaseScope.SYSTEM,
        slug="notes",
        revision=1,
    )
    next_pin = current_pin.model_copy(update={"revision": 2})
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(
            name="Room graph",
            document=SavedGraphDocument(
                nodes=(
                    SavedGraphNode(
                        kind="plugin",
                        id="n1",
                        operator_id="notes.write",
                        operator_version=1,
                        position=GraphPoint(x=10, y=20),
                        config={"text": "preserve"},
                        plugin_release_pin=current_pin,
                    ),
                ),
            ),
        )
    )
    command_id = uuid4()

    with _connect_room(api, population.workspace.id, graph.id) as websocket:
        ready = websocket.receive_json()
        response = workspace_api.graphs.submit_command_ok(
            graph.id,
            SubmitGraphCommandRequest(
                command_id=command_id,
                room_epoch=ready["head"]["room_epoch"],
                observed_sequence=ready["head"]["collaboration_sequence"],
                command=UpdateNodePluginReleaseCommand(
                    node_id="n1",
                    plugin_release_pin=next_pin,
                    expected_plugin_release_pin=current_pin,
                ),
            ),
        )
        accepted = _receive_until(websocket, "graph.command.accepted")

    assert response.head.nodes[0].config == {"text": "preserve"}
    assert response.head.nodes[
        0
    ].plugin_release == PluginReleasePinModel.from_saved_pin(next_pin)
    assert accepted["command_id"] == str(command_id)
    assert accepted["command"] == {
        "kind": "update_node_plugin_release",
        "node_id": "n1",
        "plugin_release_pin": {
            "scope": "system",
            "slug": "notes",
            "revision": 2,
        },
        "expected_plugin_release_pin": {
            "scope": "system",
            "slug": "notes",
            "revision": 1,
        },
    }


def test_room_sends_application_heartbeat(heartbeat_room_client: RoomClient) -> None:
    api, _switcher, population = heartbeat_room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )

    with _connect_room(api, population.workspace.id, graph.id) as websocket:
        ready = websocket.receive_json()
        heartbeat = websocket.receive_json()

    assert heartbeat["type"] == "room.heartbeat"
    assert heartbeat["protocol_version"] == 1
    assert (
        heartbeat["authorization_version"]
        == ready["capabilities"]["authorization_version"]
    )
    RoomHeartbeatMessage.model_validate(heartbeat)


def test_heartbeat_revalidation_closes_on_lost_role_invalidation(
    heartbeat_room_client: RoomClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heartbeat covers lost post-commit room invalidation (auth tenancy design)."""

    async def _skip_close(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(
        "grafy_api.v1.routes.workspaces.views.close_user_rooms_for_permission_change",
        _skip_close,
    )

    api, switcher, population = heartbeat_room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )
    switcher.as_user(population.editor.id)

    with _connect_room(api, population.workspace.id, graph.id) as editor_ws:
        editor_ws.receive_json()
        switcher.as_user(population.owner.id)
        workspace_api.change_member_role_ok(
            population.editor.id,
            WorkspaceMemberRoleRequest(role=WorkspaceRole.VIEWER),
        )

        with pytest.raises(WebSocketDisconnect) as closed:
            while True:
                message = editor_ws.receive_json()
                # A heartbeat enqueued before the role commit may still arrive.
                assert message["type"] == "room.heartbeat"
        assert closed.value.code == 4003
        assert closed.value.reason == "permissions_changed"


def test_presence_join_leave_fanout_and_room_ready_participants(
    room_client: RoomClient,
) -> None:
    api, switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )

    with _connect_room(api, population.workspace.id, graph.id) as owner_ws:
        owner_ready = owner_ws.receive_json()
        assert len(owner_ready["participants"]) == 1
        assert (
            owner_ready["participants"][0]["graph_room_session_id"]
            == (owner_ready["graph_room_session_id"])
        )

        switcher.as_user(population.editor.id)
        with _connect_room(api, population.workspace.id, graph.id) as editor_ws:
            editor_ready = editor_ws.receive_json()
            participant_ids = {
                item["graph_room_session_id"] for item in editor_ready["participants"]
            }
            assert participant_ids == {
                owner_ready["graph_room_session_id"],
                editor_ready["graph_room_session_id"],
            }

            join = _receive_until(owner_ws, "presence.join")
            assert (
                join["participant"]["graph_room_session_id"]
                == (editor_ready["graph_room_session_id"])
            )
            assert join["participant"]["actor"]["actor_id"] == str(population.editor.id)

            editor_ws.send_json(
                {
                    "protocol_version": 1,
                    "type": "presence.update",
                    "presence_sequence": 1,
                    "cursor": {"x": 12.5, "y": -4.0},
                    "selected_node_ids": ["node-a"],
                    "selected_edge_ids": [],
                    "activity": "editing_node",
                    "activity_target_ids": ["node-a"],
                    "transient_node_positions": [],
                }
            )
            update = _receive_until(owner_ws, "presence.update")
            assert update["participant"]["presence_sequence"] == 1
            assert update["participant"]["cursor"] == {"x": 12.5, "y": -4.0}
            assert update["participant"]["selected_node_ids"] == ["node-a"]
            assert update["participant"]["activity"] == "editing_node"

        leave = _receive_until(owner_ws, "presence.leave")
        assert leave["graph_room_session_id"] == editor_ready["graph_room_session_id"]


def test_presence_cleared_on_access_revoked(room_client: RoomClient) -> None:
    api, switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(name="Room graph", document=SavedGraphDocument())
    )

    with _connect_room(api, population.workspace.id, graph.id) as owner_ws:
        owner_ws.receive_json()
        switcher.as_user(population.editor.id)
        with _connect_room(api, population.workspace.id, graph.id) as editor_ws:
            editor_ready = editor_ws.receive_json()
            _receive_until(owner_ws, "presence.join")

            switcher.as_user(population.owner.id)
            assert workspace_api.remove_member(population.editor.id).status_code == 204

            with pytest.raises(WebSocketDisconnect) as closed:
                while True:
                    message = editor_ws.receive_json()
                    assert message["type"] in {"presence.update", "room.heartbeat"}
            assert closed.value.code == 4004
            assert closed.value.reason == "access_revoked"

            leave = _receive_until(owner_ws, "presence.leave")
            assert (
                leave["graph_room_session_id"] == editor_ready["graph_room_session_id"]
            )


def test_presence_rate_limit_and_stale_sequence_drop() -> None:
    async def _exercise() -> None:
        hub = GraphRoomHub(presence_max_updates_per_second=20.0)
        graph_id = uuid4()
        websocket = AsyncMock()
        websocket.application_state = WebSocketState.CONNECTED
        peer_ws = AsyncMock()
        peer_ws.application_state = WebSocketState.CONNECTED
        session = _room_session(websocket, graph_id=graph_id)
        peer = _room_session(
            peer_ws,
            graph_id=graph_id,
            actor_id=UUID(int=12),
            display_name="Editor",
            color="emerald",
        )
        await hub.join(session)
        await hub.join(peer)
        await hub.register_presence(session)
        await hub.register_presence(peer)
        # Drain join messages.
        while not peer.outbound.empty():
            peer.outbound.get_nowait()

        first = await hub.apply_presence_update(
            session,
            PresenceUpdateSubmitMessage(
                presence_sequence=1,
                cursor={"x": 1.0, "y": 2.0},
            ),
        )
        assert first is not None
        stale = await hub.apply_presence_update(
            session,
            PresenceUpdateSubmitMessage(
                presence_sequence=1,
                cursor={"x": 9.0, "y": 9.0},
            ),
        )
        assert stale is None
        burst = await hub.apply_presence_update(
            session,
            PresenceUpdateSubmitMessage(
                presence_sequence=2,
                cursor={"x": 3.0, "y": 4.0},
            ),
        )
        assert burst is None
        await hub.shutdown()

    asyncio.run(_exercise())


def test_presence_update_after_close_cannot_recreate_membership() -> None:
    """A delayed presence update after close is dropped; it must not recreate
    presence for an already-closed (unregistered) participant."""

    async def _exercise() -> None:
        hub = GraphRoomHub()
        websocket = AsyncMock()
        websocket.application_state = WebSocketState.CONNECTED
        session = _room_session(websocket, graph_id=uuid4())
        await hub.join(session)
        await hub.register_presence(session)
        await hub.close_session(session, code=1000, reason="left")

        # A stale update racing after close: no member remains, so it is dropped.
        result = await hub.apply_presence_update(
            session,
            PresenceUpdateSubmitMessage(
                presence_sequence=1,
                cursor={"x": 1.0, "y": 2.0},
            ),
        )
        assert result is None
        # Presence cannot be recreated: no participant is present for the graph.
        assert (
            await hub.participants_for(
                workspace_id=session.workspace_id,
                graph_id=session.graph_id,
            )
            == []
        )
        await hub.shutdown()

    asyncio.run(_exercise())


def test_presence_update_race_with_close_never_recreates_after_close() -> None:
    """Even when an update arrives between join and close, a subsequent close
    removes the member; a later update cannot resurrect presence."""

    async def _exercise() -> None:
        hub = GraphRoomHub()
        websocket = AsyncMock()
        websocket.application_state = WebSocketState.CONNECTED
        session = _room_session(websocket, graph_id=uuid4())
        await hub.join(session)
        await hub.register_presence(session)

        first = await hub.apply_presence_update(
            session,
            PresenceUpdateSubmitMessage(
                presence_sequence=1,
                cursor={"x": 3.0, "y": 4.0},
            ),
        )
        assert first is not None
        await hub.close_session(session, code=1000, reason="left")

        # After close the exact session is gone; a late update is dropped.
        late = await hub.apply_presence_update(
            session,
            PresenceUpdateSubmitMessage(
                presence_sequence=2,
                cursor={"x": 9.0, "y": 9.0},
            ),
        )
        assert late is None
        assert (
            await hub.participants_for(
                workspace_id=session.workspace_id,
                graph_id=session.graph_id,
            )
            == []
        )
        await hub.shutdown()

    asyncio.run(_exercise())


def test_slow_consumer_is_disconnected_instead_of_unbounded_queue() -> None:
    """Phase 4 exit: one slow connection cannot grow an unbounded send queue."""

    async def _exercise() -> None:
        hub = GraphRoomHub()
        websocket = AsyncMock()
        websocket.application_state = WebSocketState.CONNECTED
        session = _room_session(websocket, graph_id=uuid4())
        await hub.join(session)
        filler = RoomHeartbeatMessage(authorization_version=1)
        for _ in range(OUTBOUND_QUEUE_MAXSIZE):
            session.outbound.put_nowait(filler)

        await hub.deliver_private(
            session, RoomHeartbeatMessage(authorization_version=1)
        )

        assert session.closed is True
        websocket.close.assert_awaited()
        close_kwargs = websocket.close.await_args.kwargs
        assert close_kwargs["code"] == CLOSE_SLOW_CONSUMER[0]
        assert close_kwargs["reason"] == CLOSE_SLOW_CONSUMER[1]
        await hub.shutdown()

    asyncio.run(_exercise())


def test_activated_session_has_one_fifo_post_activation_writer() -> None:
    """After activation every message routes through the hub's single sender.

    A blocked socket must not allow direct writes to overtake queued messages;
    the activated session owns exactly one sender task, so ``deliver_private``
    messages are delivered strictly in FIFO order.
    """

    async def _exercise() -> None:
        hub = GraphRoomHub()
        websocket = AsyncMock()
        websocket.application_state = WebSocketState.CONNECTED
        session = _room_session(websocket, graph_id=uuid4())
        await hub.join(session)
        await hub.activate(session)

        # Simulate a blocked socket: the sender task awaits an event that never
        # fires until after both messages have been enqueued, so the queue is
        # the only path and delivery is strictly FIFO.
        blocked = asyncio.Event()

        async def _blocking_send(payload: dict) -> None:
            await blocked.wait()

        websocket.send_json.side_effect = _blocking_send

        first = RoomHeartbeatMessage(authorization_version=1)
        second = RoomHeartbeatMessage(authorization_version=2)
        await hub.deliver_private(session, first)
        await hub.deliver_private(session, second)

        await asyncio.sleep(0.05)
        # Unblock the single sender so it drains the queue in order.
        blocked.set()
        await asyncio.sleep(0.05)
        calls = websocket.send_json.await_args_list
        sent = [call.args[0]["authorization_version"] for call in calls]
        assert sent == [1, 2], sent
        assert len(calls) == 2

        # Exactly one sender task exists for this activated session.
        assert session.sender_task is not None
        await hub.shutdown()

    asyncio.run(_exercise())


def test_two_sessions_see_execution_start_and_complete(
    room_client: RoomClient,
) -> None:
    """Phase 5B: room advertises active execution lifecycle to every session."""

    api, switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(
            name="Execution room graph", document=SavedGraphDocument()
        )
    )

    with _connect_room(api, population.workspace.id, graph.id) as owner_ws:
        owner_ready = owner_ws.receive_json()
        assert owner_ready["active_execution"] is None
        switcher.as_user(population.editor.id)
        with _connect_room(api, population.workspace.id, graph.id) as editor_ws:
            editor_ready = editor_ws.receive_json()
            assert editor_ready["active_execution"] is None

            switcher.as_user(population.owner.id)
            started = workspace_api.executions.start_execution_ok(
                RunRequest(
                    nodes=[],
                    edges=[],
                    graph_id=graph.id,
                    graph_revision=graph.revision,
                )
            )

            owner_active = _receive_until(owner_ws, "execution.active")
            editor_active = _receive_until(editor_ws, "execution.active")
            assert owner_active["execution"]["execution_id"] == str(
                started.execution_id
            )
            assert editor_active["execution"]["execution_id"] == str(
                started.execution_id
            )
            assert owner_active["execution"]["status"] in {
                "queued",
                "running",
            }
            assert owner_active["execution"]["starter"]["actor_id"] == str(
                population.owner.id
            )
            assert owner_active["execution"]["cancellable"] is True

            owner_cleared = _receive_until(owner_ws, "execution.cleared")
            editor_cleared = _receive_until(editor_ws, "execution.cleared")
            assert owner_cleared["execution_id"] == str(started.execution_id)
            assert editor_cleared["execution_id"] == str(started.execution_id)
            assert owner_cleared["status"] == "succeeded"
            assert editor_cleared["status"] == "succeeded"


def test_viewer_discovers_active_execution_on_room_ready_and_cannot_cancel(
    room_client: RoomClient,
) -> None:
    api, switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(
            name="Execution room graph", document=SavedGraphDocument()
        )
    )

    # The execution manager captures the RunGraph instance during lifespan, so
    # a dependency override cannot intercept its worker call; hold the run open
    # by swapping the method on that shared instance.
    application = cast(FastAPI, api.raw.app)
    original_run = application.state.resources.workbench.run_graph.run

    async def blocking_run(*args, **kwargs):
        del args, kwargs
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise

    application.state.resources.workbench.run_graph.run = blocking_run
    try:
        started = workspace_api.executions.start_execution_ok(
            RunRequest(
                nodes=[],
                edges=[],
                graph_id=graph.id,
                graph_revision=graph.revision,
            )
        )

        switcher.as_user(population.viewer.id)
        with _connect_room(api, population.workspace.id, graph.id) as viewer_ws:
            ready = viewer_ws.receive_json()
            assert ready["active_execution"] is not None
            assert ready["active_execution"]["execution_id"] == str(
                started.execution_id
            )
            assert ready["active_execution"]["status"] in {"queued", "running"}
            assert "execute_graph" not in ready["capabilities"]["capabilities"]
            assert "cancel_execution" not in ready["capabilities"]["capabilities"]

            observed = workspace_api.executions.get_execution(started.execution_id)
            assert observed.status_code == 200

            denied = workspace_api.executions.cancel_execution(started.execution_id)
            assert denied.status_code == 403

        switcher.as_user(population.editor.id)
        cancel = workspace_api.executions.cancel_execution_ok(started.execution_id)
        assert cancel.status in {"cancelling", "cancelled"}
    finally:
        application.state.resources.workbench.run_graph.run = original_run


def test_second_saved_execution_conflicts_while_active(room_client: RoomClient) -> None:
    api, _switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(
            name="Execution room graph", document=SavedGraphDocument()
        )
    )

    # See test_viewer_discovers_active_execution...: the manager holds the
    # lifespan-built RunGraph, so the swap must target the shared instance.
    application = cast(FastAPI, api.raw.app)
    original_run = application.state.resources.workbench.run_graph.run

    async def blocking_run(*args, **kwargs):
        del args, kwargs
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise

    application.state.resources.workbench.run_graph.run = blocking_run
    try:
        run_request = RunRequest(
            nodes=[],
            edges=[],
            graph_id=graph.id,
            graph_revision=graph.revision,
        )
        first = workspace_api.executions.start_execution_ok(run_request)
        conflict = workspace_api.executions.start_execution(run_request)
        assert conflict.status_code == 409, conflict.text
        detail = conflict.json()["detail"]
        assert detail["error_code"] == "active_execution"
        assert detail["execution_id"] == str(first.execution_id)

        workspace_api.executions.cancel_execution_ok(first.execution_id)
    finally:
        application.state.resources.workbench.run_graph.run = original_run


def test_two_sessions_see_execution_cancel(room_client: RoomClient) -> None:
    api, switcher, population = room_client
    workspace_api = api.workspace(population.workspace.id)
    graph = workspace_api.graphs.create_ok(
        CreateSavedGraphRequest(
            name="Execution room graph", document=SavedGraphDocument()
        )
    )

    # See test_viewer_discovers_active_execution...: the manager holds the
    # lifespan-built RunGraph, so the swap must target the shared instance.
    application = cast(FastAPI, api.raw.app)
    original_run = application.state.resources.workbench.run_graph.run

    async def blocking_run(*args, **kwargs):
        del args, kwargs
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            raise

    application.state.resources.workbench.run_graph.run = blocking_run
    try:
        with _connect_room(api, population.workspace.id, graph.id) as owner_ws:
            owner_ws.receive_json()
            switcher.as_user(population.editor.id)
            with _connect_room(api, population.workspace.id, graph.id) as editor_ws:
                editor_ws.receive_json()

                switcher.as_user(population.owner.id)
                started = workspace_api.executions.start_execution_ok(
                    RunRequest(
                        nodes=[],
                        edges=[],
                        graph_id=graph.id,
                        graph_revision=graph.revision,
                    )
                )
                _receive_until(owner_ws, "execution.active")
                _receive_until(editor_ws, "execution.active")

                workspace_api.executions.cancel_execution_ok(started.execution_id)

                owner_cancelling = _receive_execution_active_status(
                    owner_ws,
                    "cancelling",
                )
                editor_cancelling = _receive_execution_active_status(
                    editor_ws,
                    "cancelling",
                )
                assert owner_cancelling["execution"]["cancellable"] is False
                assert editor_cancelling["execution"]["cancellable"] is False

                owner_cleared = _receive_until(owner_ws, "execution.cleared")
                editor_cleared = _receive_until(editor_ws, "execution.cleared")
                assert owner_cleared["status"] == "cancelled"
                assert editor_cleared["status"] == "cancelled"
    finally:
        application.state.resources.workbench.run_graph.run = original_run
