"""Phase 7 two-session collaboration acceptance at the API/WebSocket boundary.

These tests are the automatable stand-in for the plan's two-browser journey:
owner invites collaborators, two sessions converge and share a run, a viewer
observes without mutating, membership revoke closes the victim room, and a
personal graph stays invisible. Live OIDC/SSH rehearsal remains an operator gate.
"""

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from grafy_api.settings import Settings
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_api.v1.routes.auth.models import WorkspaceInvitationCreateRequest
from grafy_api.v1.routes.collaboration.views import websocket_browser_actor
from grafy_api.execution.requests import RunRequest
from grafy_api.v1.routes.saved_graphs.models import CreateSavedGraphRequest
from grafy_core.domain.identity import (
    User,
    Workspace,
    WorkspaceKind,
    WorkspaceRole,
)
from grafy_core.domain.saved_graphs import SavedGraphDocument
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork

from tests.support.clients import GrafyApi
from tests.support.factories.identity import IdentitySeeder
from tests.support.identity import ActorSwitcher
from tests.testkit import client_with_overrides, create_db_url, db


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


def _receive_until(websocket, message_type: str, *, limit: int = 30) -> dict:
    for _ in range(limit):
        message = websocket.receive_json()
        if message["type"] == message_type:
            return message
    raise AssertionError(f"did not receive {message_type!r} within {limit} messages")


def test_phase7_two_session_collaboration_acceptance_journey(
    tmp_path: Path, settings: Settings
) -> None:
    """Owner invites peers; sessions converge, share a run, and revoke cleanly."""

    database_url = create_db_url(tmp_path, "acceptance.sqlite3")

    async def seed_acceptance_cast() -> tuple[User, User, User, Workspace, Workspace]:
        async with db(database_url) as database:
            seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
            owner = await seeder.user(
                email="owner@acceptance.test", display_name="Owner"
            )
            editor = await seeder.user(
                email="editor@acceptance.test", display_name="Editor"
            )
            viewer = await seeder.user(
                email="viewer@acceptance.test", display_name="Viewer"
            )
            personal = await seeder.workspace(
                slug=owner.id.hex,
                name="Owner personal",
                kind=WorkspaceKind.PERSONAL,
                personal_owner_user_id=owner.id,
            )
            shared = await seeder.workspace(
                slug="acceptance-team", name="Acceptance team"
            )
            await seeder.membership(
                user=owner, workspace=personal, role=WorkspaceRole.OWNER
            )
            await seeder.membership(
                user=owner, workspace=shared, role=WorkspaceRole.OWNER
            )
            return owner, editor, viewer, personal, shared

    owner, editor, viewer, personal, shared = asyncio.run(seed_acceptance_cast())
    switcher = ActorSwitcher(owner.id)

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
        api = GrafyApi(client)
        personal_api = api.workspace(personal.id)
        shared_api = api.workspace(shared.id)

        switcher.as_user(owner.id)
        personal_graph = personal_api.graphs.create_ok(
            CreateSavedGraphRequest(name="Private draft", document=SavedGraphDocument())
        )

        switcher.as_user(editor.id)
        assert personal_api.graphs.get(personal_graph.id).status_code == 404
        assert personal_api.graphs.list().status_code == 404

        switcher.as_user(owner.id)
        shared_graph = shared_api.graphs.create_ok(
            CreateSavedGraphRequest(
                name="Shared acceptance graph", document=SavedGraphDocument()
            )
        )
        editor_invitation = shared_api.create_invitation_ok(
            WorkspaceInvitationCreateRequest(
                email=editor.email or "editor@acceptance.test",
                role=WorkspaceRole.EDITOR,
            )
        )
        switcher.as_user(editor.id)
        assert shared_api.graphs.list().status_code == 404
        assert (
            api.raw.post(
                f"/v1/me/invitations/{editor_invitation.id}/accept"
            ).status_code
            == 200
        )

        switcher.as_user(owner.id)
        viewer_invitation = shared_api.create_invitation_ok(
            WorkspaceInvitationCreateRequest(
                email=viewer.email or "viewer@acceptance.test",
                role=WorkspaceRole.VIEWER,
            )
        )
        switcher.as_user(viewer.id)
        assert (
            api.raw.post(
                f"/v1/me/invitations/{viewer_invitation.id}/accept"
            ).status_code
            == 200
        )

        switcher.as_user(owner.id)
        member_ids = {member.user.id for member in shared_api.list_members_ok()}
        assert member_ids == {owner.id, editor.id, viewer.id}

        with _connect_room(api, shared.id, shared_graph.id) as owner_ws:
            owner_ready = owner_ws.receive_json()
            assert owner_ready["type"] == "room.ready"
            assert owner_ready["active_execution"] is None

            switcher.as_user(editor.id)
            with _connect_room(api, shared.id, shared_graph.id) as editor_ws:
                editor_ready = editor_ws.receive_json()
                assert editor_ready["type"] == "room.ready"
                assert {
                    item["graph_room_session_id"]
                    for item in editor_ready["participants"]
                } == {
                    owner_ready["graph_room_session_id"],
                    editor_ready["graph_room_session_id"],
                }

                join = _receive_until(owner_ws, "presence.join")
                assert join["participant"]["actor"]["actor_id"] == str(editor.id)
                assert (
                    join["participant"]["graph_room_session_id"]
                    == (editor_ready["graph_room_session_id"])
                )

                command_id = str(uuid4())
                expected_sequence = editor_ready["head"]["collaboration_sequence"] + 1
                editor_ws.send_json(
                    {
                        "protocol_version": 1,
                        "type": "graph.command.submit",
                        "command_id": command_id,
                        "room_epoch": editor_ready["head"]["room_epoch"],
                        "observed_sequence": editor_ready["head"][
                            "collaboration_sequence"
                        ],
                        "command": {
                            "kind": "rename_graph",
                            "name": "Converged name",
                            "expected_name": editor_ready["head"]["name"],
                        },
                    }
                )
                editor_accepted = _receive_until(editor_ws, "graph.command.accepted")
                editor_receipt = _receive_until(editor_ws, "graph.command.receipt")
                assert editor_accepted["sequence"] == expected_sequence
                assert editor_receipt["accepted_sequence"] == expected_sequence

                owner_accepted = _receive_until(owner_ws, "graph.command.accepted")
                assert owner_accepted["command_id"] == command_id
                assert owner_accepted["sequence"] == expected_sequence
                assert owner_accepted["command"]["name"] == "Converged name"
                assert owner_accepted["actor"]["actor_id"] == str(editor.id)

                switcher.as_user(owner.id)
                started = shared_api.executions.start_execution_ok(
                    RunRequest(
                        nodes=[],
                        edges=[],
                        graph_id=shared_graph.id,
                        graph_revision=shared_graph.revision,
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
                assert owner_active["execution"]["starter"]["actor_id"] == str(owner.id)

                owner_cleared = _receive_until(owner_ws, "execution.cleared")
                editor_cleared = _receive_until(editor_ws, "execution.cleared")
                assert owner_cleared["execution_id"] == str(started.execution_id)
                assert editor_cleared["execution_id"] == str(started.execution_id)

                switcher.as_user(viewer.id)
                with _connect_room(api, shared.id, shared_graph.id) as viewer_ws:
                    viewer_ready = viewer_ws.receive_json()
                    assert viewer_ready["type"] == "room.ready"
                    assert viewer_ready["head"]["name"] == "Converged name"
                    assert (
                        "edit_graph" not in viewer_ready["capabilities"]["capabilities"]
                    )
                    assert (
                        "execute_graph"
                        not in viewer_ready["capabilities"]["capabilities"]
                    )

                    viewer_ws.send_json(
                        {
                            "protocol_version": 1,
                            "type": "graph.command.submit",
                            "command_id": str(uuid4()),
                            "room_epoch": viewer_ready["head"]["room_epoch"],
                            "observed_sequence": viewer_ready["head"][
                                "collaboration_sequence"
                            ],
                            "command": {
                                "kind": "rename_graph",
                                "name": "Viewer should fail",
                                "expected_name": viewer_ready["head"]["name"],
                            },
                        }
                    )
                    rejected = _receive_until(viewer_ws, "graph.command.rejected")
                    assert rejected["error_code"] == "forbidden"

                switcher.as_user(owner.id)
                assert shared_api.remove_member(editor.id).status_code == 204

                with pytest.raises(WebSocketDisconnect) as closed:
                    while True:
                        message = editor_ws.receive_json()
                        assert message["type"] in {
                            "presence.update",
                            "presence.leave",
                            "presence.join",
                            "room.heartbeat",
                        }
                assert closed.value.code == 4004
                assert closed.value.reason == "access_revoked"

                for _ in range(30):
                    leave = owner_ws.receive_json()
                    if leave["type"] != "presence.leave":
                        continue
                    if (
                        leave["graph_room_session_id"]
                        == editor_ready["graph_room_session_id"]
                    ):
                        break
                else:
                    raise AssertionError("owner did not observe editor presence.leave")

        switcher.as_user(editor.id)
        assert shared_api.graphs.get_head(shared_graph.id).status_code == 404

        switcher.as_user(owner.id)
        head = shared_api.graphs.get_head_ok(shared_graph.id)
        assert head.name == "Converged name"
        assert head.collaboration_sequence == expected_sequence
