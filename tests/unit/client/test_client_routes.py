import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from grafy_core.domain.credentials import (
    SharedCredentialBindingMode,
    UserCredentialOverrideMode,
)

from grafy_client import (
    GrafyClient,
    GrafyClientError,
    ProjectHead,
)

WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")
SOURCE_WORKSPACE_ID = UUID("12121212-1212-4121-8121-121212121212")
PROJECT_ID = UUID("22222222-2222-4222-8222-222222222222")
COPIED_PROJECT_ID = UUID("23232323-2323-4232-8232-232323232323")
FOLDER_ID = UUID("33333333-3333-4333-8333-333333333333")
PARENT_FOLDER_ID = UUID("34343434-3434-4343-8343-343434343434")
ROOM_EPOCH = UUID("44444444-4444-4444-8444-444444444444")
COMMAND_ID = UUID("55555555-5555-4555-8555-555555555555")
ARTIFACT_ID = UUID("66666666-6666-4666-8666-666666666666")
CREDENTIAL_ID = UUID("77777777-7777-4777-8777-777777777777")
CONVERSATION_ID = UUID("88888888-8888-4888-8888-888888888888")
TURN_ID = UUID("99999999-9999-4999-8999-999999999999")
USER_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
MESSAGE_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

STAMP = "2026-11-26T04:00:00Z"


def _head(sequence: int = 3) -> ProjectHead:
    return ProjectHead.model_validate(
        {
            "project_id": str(PROJECT_ID),
            "room_epoch": str(ROOM_EPOCH),
            "collaboration_sequence": sequence,
            "checkpoint_sequence": 1,
            "checkpoint_revision": 1,
            "name": "Project",
            "updated_at": STAMP,
            "document": {"graphs": []},
        }
    )


def _folder_payload(folder_id: UUID = FOLDER_ID, name: str = "Maps") -> dict[str, Any]:
    return {
        "id": str(folder_id),
        "name": name,
        "created_at": STAMP,
        "updated_at": STAMP,
    }


def _library_folder_payload(
    folder_id: UUID = FOLDER_ID,
    parent_id: UUID | None = None,
    name: str = "Scans",
) -> dict[str, Any]:
    return {
        "folder_id": str(folder_id),
        "workspace_id": str(WORKSPACE_ID),
        "parent_id": str(parent_id) if parent_id is not None else None,
        "name": name,
        "created_at": STAMP,
        "updated_at": STAMP,
    }


def _organization_payload(
    *,
    folder_id: UUID | None = FOLDER_ID,
    archived: bool = False,
) -> dict[str, Any]:
    return {
        "folder_id": str(folder_id) if folder_id is not None else None,
        "archived": archived,
        "archived_at": STAMP if archived else None,
        "updated_at": STAMP,
    }


def _node_secret_detail_payload(
    *,
    shared_mode: str = "none",
    personal_mode: str = "none",
) -> dict[str, Any]:
    return {
        "node_id": "llm",
        "name": "api_key",
        "configured": shared_mode != "none" or personal_mode != "none",
        "provider_kind": "openai",
        "effective_source": "shared_credential" if shared_mode != "none" else "none",
        "effective_credential_id": (
            str(CREDENTIAL_ID) if shared_mode == "credential" else None
        ),
        "effective_credential_label": (
            "Team Key" if shared_mode == "credential" else None
        ),
        "effective_verification_status": (
            "valid" if shared_mode == "credential" else None
        ),
        "shared_binding_mode": shared_mode,
        "shared_credential_id": (
            str(CREDENTIAL_ID) if shared_mode == "credential" else None
        ),
        "shared_credential_label": "Team Key" if shared_mode == "credential" else None,
        "shared_credential_missing": False,
        "personal_override_mode": personal_mode,
        "personal_credential_id": (
            str(CREDENTIAL_ID) if personal_mode == "credential" else None
        ),
        "personal_credential_label": (
            "My Key" if personal_mode == "credential" else None
        ),
        "deployment_default_available": True,
        "supports_verification": True,
    }


def _conversation_payload(title: str = "Research") -> dict[str, Any]:
    return {
        "id": str(CONVERSATION_ID),
        "workspace_id": str(WORKSPACE_ID),
        "project_id": str(PROJECT_ID),
        "graph_id": "main",
        "agent_id": "agent-1",
        "author_user_id": str(USER_ID),
        "title": title,
        "source_conversation_id": None,
        "source_sequence": None,
        "last_sequence": 2,
        "created_at": STAMP,
        "updated_at": STAMP,
    }


def _turn_payload(status: str = "running") -> dict[str, Any]:
    return {
        "id": str(TURN_ID),
        "conversation_id": str(CONVERSATION_ID),
        "client_turn_id": "turn-1",
        "status": status,
        "model_source": "deployment",
        "model_name": "gpt-5",
        "requested_by_user_id": str(USER_ID),
        "user_message_sequence": 1,
        "outcome_detail": None,
        "created_at": STAMP,
        "finished_at": None if status == "running" else STAMP,
    }


@dataclass(frozen=True)
class RouteCase:
    name: str
    call: Callable[[GrafyClient], Awaitable[Any]]
    expected_method: str
    expected_path: str
    expected_query: dict[str, list[str]] | None = None
    expected_json: dict[str, Any] | None = None
    expect_empty_body: bool = False
    response_status: int = 200
    response_json: Any = None
    response_content: bytes | None = None
    assert_result: Callable[[Any], Any] | None = None


BASE = f"/v1/workspaces/{WORKSPACE_ID}"
PROJECTS = f"{BASE}/projects"
LIBRARY = f"{BASE}/library"
AGENTS = f"{PROJECTS}/{PROJECT_ID}/graphs/main/agents/agent-1"


ROUTE_CASES: tuple[RouteCase, ...] = (
    # Project folders
    RouteCase(
        name="projects.list_folders",
        call=lambda c: c.projects.list_folders(WORKSPACE_ID),
        expected_method="GET",
        expected_path=f"{BASE}/project-folders",
        response_json={"folders": [_folder_payload()]},
        assert_result=lambda r: (
            assert_eq(len(r), 1),
            assert_eq(r[0].id, FOLDER_ID),
            assert_eq(r[0].name, "Maps"),
        ),
    ),
    RouteCase(
        name="projects.create_folder",
        call=lambda c: c.projects.create_folder(WORKSPACE_ID, name="Maps"),
        expected_method="POST",
        expected_path=f"{BASE}/project-folders",
        expected_json={"name": "Maps"},
        response_status=201,
        response_json=_folder_payload(),
        assert_result=lambda r: assert_eq(r.id, FOLDER_ID),
    ),
    RouteCase(
        name="projects.rename_folder",
        call=lambda c: c.projects.rename_folder(WORKSPACE_ID, FOLDER_ID, name="Charts"),
        expected_method="PATCH",
        expected_path=f"{BASE}/project-folders/{FOLDER_ID}",
        expected_json={"name": "Charts"},
        response_json=_folder_payload(name="Charts"),
        assert_result=lambda r: assert_eq(r.name, "Charts"),
    ),
    RouteCase(
        name="projects.delete_folder",
        call=lambda c: c.projects.delete_folder(WORKSPACE_ID, FOLDER_ID),
        expected_method="DELETE",
        expected_path=f"{BASE}/project-folders/{FOLDER_ID}",
        response_status=204,
        assert_result=lambda r: assert_eq(r, None),
    ),
    RouteCase(
        name="projects.assign_folder",
        call=lambda c: c.projects.assign_folder(
            WORKSPACE_ID, PROJECT_ID, folder_id=FOLDER_ID
        ),
        expected_method="PUT",
        expected_path=f"{PROJECTS}/{PROJECT_ID}/folder",
        expected_json={"folder_id": str(FOLDER_ID)},
        response_json=_organization_payload(folder_id=FOLDER_ID),
        assert_result=lambda r: assert_eq(r.folder_id, FOLDER_ID),
    ),
    RouteCase(
        name="projects.assign_folder.clear",
        call=lambda c: c.projects.assign_folder(
            WORKSPACE_ID, PROJECT_ID, folder_id=None
        ),
        expected_method="PUT",
        expected_path=f"{PROJECTS}/{PROJECT_ID}/folder",
        expected_json={"folder_id": None},
        response_json=_organization_payload(folder_id=None),
        assert_result=lambda r: assert_eq(r.folder_id, None),
    ),
    # Archive & Star
    RouteCase(
        name="projects.archive",
        call=lambda c: c.projects.archive(WORKSPACE_ID, PROJECT_ID),
        expected_method="PUT",
        expected_path=f"{PROJECTS}/{PROJECT_ID}/archive",
        response_json=_organization_payload(archived=True),
        assert_result=lambda r: assert_eq(r.archived, True),
    ),
    RouteCase(
        name="projects.unarchive",
        call=lambda c: c.projects.unarchive(WORKSPACE_ID, PROJECT_ID),
        expected_method="DELETE",
        expected_path=f"{PROJECTS}/{PROJECT_ID}/archive",
        response_json=_organization_payload(archived=False),
        assert_result=lambda r: assert_eq(r.archived, False),
    ),
    RouteCase(
        name="projects.star",
        call=lambda c: c.projects.star(WORKSPACE_ID, PROJECT_ID),
        expected_method="PUT",
        expected_path=f"{PROJECTS}/{PROJECT_ID}/star",
        response_json={"starred": True, "last_opened_at": STAMP},
        assert_result=lambda r: assert_eq(r.starred, True),
    ),
    RouteCase(
        name="projects.unstar",
        call=lambda c: c.projects.unstar(WORKSPACE_ID, PROJECT_ID),
        expected_method="DELETE",
        expected_path=f"{PROJECTS}/{PROJECT_ID}/star",
        response_json={"starred": False, "last_opened_at": None},
        assert_result=lambda r: (
            assert_eq(r.starred, False),
            assert_eq(r.last_opened_at, None),
        ),
    ),
    # Copy
    RouteCase(
        name="projects.copy",
        call=lambda c: c.projects.copy(
            WORKSPACE_ID,
            PROJECT_ID,
            head=_head(5),
            source_workspace_id=SOURCE_WORKSPACE_ID,
            name="Copy",
            project_id=COPIED_PROJECT_ID,
            command_id=COMMAND_ID,
        ),
        expected_method="POST",
        expected_path=f"{PROJECTS}/copies",
        expected_json={
            "source_workspace_id": str(SOURCE_WORKSPACE_ID),
            "source_project_id": str(PROJECT_ID),
            "project_id": str(COPIED_PROJECT_ID),
            "expected_room_epoch": str(ROOM_EPOCH),
            "expected_sequence": 5,
            "command_id": str(COMMAND_ID),
            "name": "Copy",
        },
        response_status=201,
        response_json={
            "id": str(COPIED_PROJECT_ID),
            "name": "Copy",
            "created_at": STAMP,
            "updated_at": STAMP,
        },
        assert_result=lambda r: assert_eq(r.id, COPIED_PROJECT_ID),
    ),
    # Checkpoints
    RouteCase(
        name="projects.list_checkpoints",
        call=lambda c: c.projects.list_checkpoints(WORKSPACE_ID, PROJECT_ID),
        expected_method="GET",
        expected_path=f"{PROJECTS}/{PROJECT_ID}/checkpoints",
        response_json={
            "checkpoints": [
                {"revision": 1, "name": "Init", "created_at": STAMP},
                {"revision": 2, "name": "Step 2", "created_at": STAMP},
            ]
        },
        assert_result=lambda r: assert_eq([item.revision for item in r], [1, 2]),
    ),
    RouteCase(
        name="projects.get_checkpoint",
        call=lambda c: c.projects.get_checkpoint(WORKSPACE_ID, PROJECT_ID, 2),
        expected_method="GET",
        expected_path=f"{PROJECTS}/{PROJECT_ID}/checkpoints/2",
        response_json={
            "revision": 2,
            "name": "Step 2",
            "created_at": STAMP,
            "document": {"graphs": []},
        },
        assert_result=lambda r: (
            assert_eq(r.revision, 2),
            assert_eq(r.document.graphs, ()),
        ),
    ),
    RouteCase(
        name="projects.restore_checkpoint",
        call=lambda c: c.projects.restore_checkpoint(
            WORKSPACE_ID, PROJECT_ID, 1, head=_head(4)
        ),
        expected_method="POST",
        expected_path=f"{PROJECTS}/{PROJECT_ID}/checkpoints/1/restore",
        expected_json={
            "expected_room_epoch": str(ROOM_EPOCH),
            "expected_sequence": 4,
        },
        response_json={
            "head": {
                **_head(5).model_dump(mode="json"),
                "checkpoint_sequence": 5,
                "checkpoint_revision": 3,
            },
            "checkpoint_revision": 3,
        },
        assert_result=lambda r: assert_eq(r.checkpoint_revision, 3),
    ),
    # Node secrets
    RouteCase(
        name="projects.secret_status",
        call=lambda c: c.projects.secret_status(
            WORKSPACE_ID, PROJECT_ID, graph_id="sub"
        ),
        expected_method="GET",
        expected_path=f"{PROJECTS}/{PROJECT_ID}/node-secrets",
        expected_query={"graph_id": ["sub"]},
        response_json={
            "project_id": str(PROJECT_ID),
            "graph_id": "sub",
            "head_sequence": 3,
            "secrets": [_node_secret_detail_payload(shared_mode="credential")],
            "unresolved_nodes": [
                {
                    "node_id": "ocr",
                    "status": "unresolved",
                    "reason": "contract_unavailable",
                }
            ],
        },
        assert_result=lambda r: (
            assert_eq(r.graph_id, "sub"),
            assert_eq(r.secrets[0].effective_credential_id, CREDENTIAL_ID),
            assert_eq(r.unresolved_nodes[0].reason, "contract_unavailable"),
        ),
    ),
    RouteCase(
        name="projects.delete_secret",
        call=lambda c: c.projects.delete_secret(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            node_id="llm",
            secret_name="api_key",
            head=_head(7),
        ),
        expected_method="DELETE",
        expected_path=f"{PROJECTS}/{PROJECT_ID}/graphs/main/nodes/llm/secrets/api_key",
        expected_query={"expected_head_sequence": ["7"]},
        response_status=204,
    ),
    RouteCase(
        name="projects.set_secret_shared_binding",
        call=lambda c: c.projects.set_secret_shared_binding(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            node_id="llm",
            secret_name="api_key",
            mode=SharedCredentialBindingMode.CREDENTIAL,
            credential_id=CREDENTIAL_ID,
            head=_head(7),
        ),
        expected_method="PUT",
        expected_path=(
            f"{PROJECTS}/{PROJECT_ID}/graphs/main/nodes/llm/secrets/api_key"
            "/shared-binding"
        ),
        expected_json={
            "mode": "credential",
            "credential_id": str(CREDENTIAL_ID),
            "expected_head_sequence": 7,
        },
        response_json=_node_secret_detail_payload(shared_mode="credential"),
        assert_result=lambda r: assert_eq(r.shared_credential_id, CREDENTIAL_ID),
    ),
    RouteCase(
        name="projects.set_secret_personal_selection",
        call=lambda c: c.projects.set_secret_personal_selection(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            node_id="llm",
            secret_name="api_key",
            mode=UserCredentialOverrideMode.CREDENTIAL,
            credential_id=CREDENTIAL_ID,
        ),
        expected_method="PUT",
        expected_path=(
            f"{PROJECTS}/{PROJECT_ID}/graphs/main/nodes/llm/secrets/api_key"
            "/personal-selection"
        ),
        expected_json={
            "mode": "credential",
            "credential_id": str(CREDENTIAL_ID),
        },
        response_json=_node_secret_detail_payload(personal_mode="credential"),
        assert_result=lambda r: assert_eq(r.personal_credential_id, CREDENTIAL_ID),
    ),
    RouteCase(
        name="projects.verify_secret.saved",
        call=lambda c: c.projects.verify_secret(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            node_id="llm",
            secret_name="api_key",
        ),
        expected_method="POST",
        expected_path=(
            f"{PROJECTS}/{PROJECT_ID}/graphs/main/nodes/llm/secrets/api_key/verify"
        ),
        expect_empty_body=True,
        response_json={
            "status": "valid",
            "message": "Key verified.",
            "account_hint": "acct-1",
        },
        assert_result=lambda r: assert_eq(r.account_hint, "acct-1"),
    ),
    RouteCase(
        name="projects.verify_secret.candidate",
        call=lambda c: c.projects.verify_secret(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            node_id="llm",
            secret_name="api_key",
            value=SecretStr("sk-candidate"),
        ),
        expected_method="POST",
        expected_path=(
            f"{PROJECTS}/{PROJECT_ID}/graphs/main/nodes/llm/secrets/api_key/verify"
        ),
        expected_json={"value": "sk-candidate"},
        response_json={
            "status": "valid",
            "message": "Key verified.",
            "account_hint": None,
        },
        assert_result=lambda r: assert_eq(r.status, "valid"),
    ),
    # Library
    RouteCase(
        name="library.delete",
        call=lambda c: c.library.delete(WORKSPACE_ID, ARTIFACT_ID),
        expected_method="DELETE",
        expected_path=f"{LIBRARY}/artifacts/{ARTIFACT_ID}",
        response_status=204,
    ),
    RouteCase(
        name="library.list_folders",
        call=lambda c: c.library.list_folders(WORKSPACE_ID),
        expected_method="GET",
        expected_path=f"{LIBRARY}/folders",
        response_json={"folders": [_library_folder_payload()]},
        assert_result=lambda r: assert_eq(r[0].folder_id, FOLDER_ID),
    ),
    RouteCase(
        name="library.create_folder",
        call=lambda c: c.library.create_folder(
            WORKSPACE_ID, name="Scans", parent_id=PARENT_FOLDER_ID
        ),
        expected_method="POST",
        expected_path=f"{LIBRARY}/folders",
        expected_json={"name": "Scans", "parent_id": str(PARENT_FOLDER_ID)},
        response_status=201,
        response_json=_library_folder_payload(parent_id=PARENT_FOLDER_ID),
        assert_result=lambda r: assert_eq(r.parent_id, PARENT_FOLDER_ID),
    ),
    RouteCase(
        name="library.rename_folder",
        call=lambda c: c.library.rename_folder(WORKSPACE_ID, FOLDER_ID, name="Plates"),
        expected_method="PATCH",
        expected_path=f"{LIBRARY}/folders/{FOLDER_ID}",
        expected_json={"name": "Plates"},
        response_json=_library_folder_payload(name="Plates"),
        assert_result=lambda r: assert_eq(r.name, "Plates"),
    ),
    RouteCase(
        name="library.delete_folder",
        call=lambda c: c.library.delete_folder(WORKSPACE_ID, FOLDER_ID),
        expected_method="DELETE",
        expected_path=f"{LIBRARY}/folders/{FOLDER_ID}",
        response_status=204,
    ),
    RouteCase(
        name="library.move_folder",
        call=lambda c: c.library.move_folder(WORKSPACE_ID, FOLDER_ID, parent_id=None),
        expected_method="PUT",
        expected_path=f"{LIBRARY}/folders/{FOLDER_ID}/parent",
        expected_json={"parent_id": None},
        response_json=_library_folder_payload(parent_id=None),
        assert_result=lambda r: assert_eq(r.parent_id, None),
    ),
    RouteCase(
        name="library.move_artifacts",
        call=lambda c: c.library.move_artifacts(
            WORKSPACE_ID, artifact_ids=[ARTIFACT_ID], folder_id=FOLDER_ID
        ),
        expected_method="PUT",
        expected_path=f"{LIBRARY}/placements",
        expected_json={
            "artifact_ids": [str(ARTIFACT_ID)],
            "folder_id": str(FOLDER_ID),
        },
        response_status=204,
    ),
    # Catalog
    RouteCase(
        name="catalog.packs",
        call=lambda c: c.catalog.packs(WORKSPACE_ID),
        expected_method="GET",
        expected_path=f"{BASE}/packs",
        response_json=[
            {
                "slug": "essentials",
                "title": "Essentials",
                "description": "Core tools.",
                "always_on": True,
                "subscribed": True,
                "operator_count": 8,
                "provider_count": 0,
                "includes_project_graphs": False,
            }
        ],
        assert_result=lambda r: assert_eq(r[0].slug, "essentials"),
    ),
    # Artifacts
    RouteCase(
        name="artifacts.table_cell",
        call=lambda c: c.artifacts.table_cell(
            WORKSPACE_ID, ARTIFACT_ID, row_index=4, column_id="col_1"
        ),
        expected_method="GET",
        expected_path=f"{BASE}/artifacts/{ARTIFACT_ID}/table/cell",
        expected_query={"row_index": ["4"], "column_id": ["col_1"]},
        response_json={
            "row_index": 4,
            "column_id": "col_1",
            "value": "12345",
            "encoding": "integer",
        },
        assert_result=lambda r: (
            assert_eq(r.value, "12345"),
            assert_eq(r.encoding, "integer"),
        ),
    ),
    RouteCase(
        name="artifacts.image_info",
        call=lambda c: c.artifacts.image_info(WORKSPACE_ID, ARTIFACT_ID, page=2),
        expected_method="GET",
        expected_path=f"{BASE}/artifacts/{ARTIFACT_ID}/image/info",
        expected_query={"page": ["2"]},
        response_json={
            "width": 2048,
            "height": 1024,
            "page_count": 4,
            "has_alpha": False,
            "tile_size": 256,
            "min_level": 0,
            "max_level": 3,
            "tile_format": "png",
            "georeferenced": True,
            "bounds_wgs84": [14.0, 49.0, 24.0, 55.0],
        },
        assert_result=lambda r: (
            assert_eq(r.width, 2048),
            assert_eq(r.tile_size, 256),
            assert_eq(r.bounds_wgs84, (14.0, 49.0, 24.0, 55.0)),
        ),
    ),
    # Agents
    RouteCase(
        name="agents.start_conversation",
        call=lambda c: c.agents.start_conversation(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            agent_id="agent-1",
            title="Research",
        ),
        expected_method="POST",
        expected_path=f"{AGENTS}/conversations",
        expected_json={"title": "Research"},
        response_status=201,
        response_json=_conversation_payload(),
        assert_result=lambda r: assert_eq(r.id, CONVERSATION_ID),
    ),
    RouteCase(
        name="agents.list_conversations",
        call=lambda c: c.agents.list_conversations(
            WORKSPACE_ID, PROJECT_ID, graph_id="main", agent_id="agent-1"
        ),
        expected_method="GET",
        expected_path=f"{AGENTS}/conversations",
        response_json={"conversations": [_conversation_payload()]},
        assert_result=lambda r: assert_eq([item.id for item in r], [CONVERSATION_ID]),
    ),
    RouteCase(
        name="agents.get_conversation",
        call=lambda c: c.agents.get_conversation(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            agent_id="agent-1",
            conversation_id=CONVERSATION_ID,
        ),
        expected_method="GET",
        expected_path=f"{AGENTS}/conversations/{CONVERSATION_ID}",
        response_json=_conversation_payload(),
        assert_result=lambda r: assert_eq(r.last_sequence, 2),
    ),
    RouteCase(
        name="agents.send_turn",
        call=lambda c: c.agents.send_turn(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            agent_id="agent-1",
            conversation_id=CONVERSATION_ID,
            text="Hello",
            client_turn_id="turn-1",
        ),
        expected_method="POST",
        expected_path=f"{AGENTS}/conversations/{CONVERSATION_ID}/turns",
        expected_json={"client_turn_id": "turn-1", "text": "Hello"},
        response_status=201,
        response_json=_turn_payload("running"),
        assert_result=lambda r: (
            assert_eq(r.id, TURN_ID),
            assert_eq(r.terminal, False),
        ),
    ),
    RouteCase(
        name="agents.active_turn.running",
        call=lambda c: c.agents.active_turn(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            agent_id="agent-1",
            conversation_id=CONVERSATION_ID,
        ),
        expected_method="GET",
        expected_path=f"{AGENTS}/conversations/{CONVERSATION_ID}/active-turn",
        response_json={
            "turn": _turn_payload("running"),
            "message_id": str(MESSAGE_ID),
            "partial_offset": 5,
            "partial_text": "Hello",
        },
        assert_result=lambda r: (
            assert_eq(r.message_id, MESSAGE_ID),
            assert_eq(r.partial_text, "Hello"),
        ),
    ),
    RouteCase(
        name="agents.active_turn.idle",
        call=lambda c: c.agents.active_turn(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            agent_id="agent-1",
            conversation_id=CONVERSATION_ID,
        ),
        expected_method="GET",
        expected_path=f"{AGENTS}/conversations/{CONVERSATION_ID}/active-turn",
        response_content=b"null",
        assert_result=lambda r: assert_eq(r, None),
    ),
    RouteCase(
        name="agents.list_events",
        call=lambda c: c.agents.list_events(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            agent_id="agent-1",
            conversation_id=CONVERSATION_ID,
            after_sequence=1,
            limit=50,
        ),
        expected_method="GET",
        expected_path=f"{AGENTS}/conversations/{CONVERSATION_ID}/events",
        expected_query={"after_sequence": ["1"], "limit": ["50"]},
        response_json={
            "events": [
                {
                    "sequence": 2,
                    "turn_id": str(TURN_ID),
                    "payload": {"kind": "assistant_message", "text": "Hi there"},
                    "created_at": STAMP,
                }
            ],
            "next_sequence": 2,
            "last_sequence": 2,
        },
        assert_result=lambda r: (
            assert_eq(r.next_sequence, 2),
            assert_eq(r.events[0].payload.kind, "assistant_message"),
        ),
    ),
    RouteCase(
        name="agents.cancel_turn.default",
        call=lambda c: c.agents.cancel_turn(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            agent_id="agent-1",
            conversation_id=CONVERSATION_ID,
        ),
        expected_method="POST",
        expected_path=f"{AGENTS}/conversations/{CONVERSATION_ID}/cancel",
        expect_empty_body=True,
        response_json=_turn_payload("cancelled"),
        assert_result=lambda r: (
            assert_eq(r.status, "cancelled"),
            assert_eq(r.terminal, True),
        ),
    ),
    RouteCase(
        name="agents.cancel_turn.explicit",
        call=lambda c: c.agents.cancel_turn(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            agent_id="agent-1",
            conversation_id=CONVERSATION_ID,
            turn_id=TURN_ID,
        ),
        expected_method="POST",
        expected_path=f"{AGENTS}/conversations/{CONVERSATION_ID}/cancel",
        expected_json={"turn_id": str(TURN_ID)},
        response_json=_turn_payload("cancelled"),
        assert_result=lambda r: assert_eq(r.id, TURN_ID),
    ),
    RouteCase(
        name="agents.get_model",
        call=lambda c: c.agents.get_model(
            WORKSPACE_ID, PROJECT_ID, graph_id="main", agent_id="agent-1"
        ),
        expected_method="GET",
        expected_path=f"{AGENTS}/model",
        response_json={
            "source": "deployment",
            "model_name": "gpt-5",
            "base_url": "https://api.openai.com/v1",
            "key_configured": True,
        },
        assert_result=lambda r: (
            assert_eq(r.model_name, "gpt-5"),
            assert_eq(r.key_configured, True),
        ),
    ),
)


def assert_eq(actual: Any, expected: Any) -> None:
    assert actual == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ROUTE_CASES, ids=[case.name for case in ROUTE_CASES])
async def test_client_route_contracts(case: RouteCase) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer nrt_live_secret"
        assert request.method == case.expected_method
        assert request.url.path == case.expected_path
        if case.expected_query is not None:
            assert parse_qs(request.url.query.decode()) == case.expected_query
        if case.expected_json is not None:
            assert json.loads(request.content) == case.expected_json
        elif case.expect_empty_body:
            assert request.content == b""
        if case.response_status == 204:
            return httpx.Response(204)
        if case.response_content is not None:
            return httpx.Response(
                case.response_status,
                content=case.response_content,
                headers={"content-type": "application/json"},
            )
        return httpx.Response(case.response_status, json=case.response_json)

    async with GrafyClient(
        base_url="https://grafy.test",
        token=SecretStr("nrt_live_secret"),
        transport=httpx.MockTransport(respond),
    ) as client:
        result = await case.call(client)

    if case.assert_result is not None:
        case.assert_result(result)


@pytest.mark.asyncio
async def test_verify_secret_redacts_candidate_secret_on_error() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={"detail": "Rejected sk-candidate-secret"},
        )

    async with GrafyClient(
        base_url="https://grafy.test",
        token=SecretStr("nrt_live_secret"),
        transport=httpx.MockTransport(respond),
    ) as client:
        with pytest.raises(GrafyClientError) as caught:
            await client.projects.verify_secret(
                WORKSPACE_ID,
                PROJECT_ID,
                graph_id="main",
                node_id="llm",
                secret_name="api_key",
                value=SecretStr("sk-candidate-secret"),
            )

    assert "sk-candidate-secret" not in str(caught.value)
    assert "<redacted>" in str(caught.value)


@pytest.mark.asyncio
async def test_client_guards_reject_empty_inputs_before_request() -> None:
    def respond(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    async with GrafyClient(
        base_url="https://grafy.test",
        token=SecretStr("nrt_live_secret"),
        transport=httpx.MockTransport(respond),
    ) as client:
        with pytest.raises(ValueError, match="must not be empty"):
            await client.projects.verify_secret(
                WORKSPACE_ID,
                PROJECT_ID,
                graph_id="main",
                node_id="llm",
                secret_name="api_key",
                value=SecretStr(""),
            )
        with pytest.raises(ValueError, match="artifact_id"):
            await client.library.move_artifacts(
                WORKSPACE_ID,
                artifact_ids=[],
                folder_id=None,
            )


@pytest.mark.asyncio
async def test_send_turn_generates_client_turn_id_when_omitted() -> None:
    seen_ids: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_ids.append(body["client_turn_id"])
        return httpx.Response(201, json=_turn_payload("running"))

    async with GrafyClient(
        base_url="https://grafy.test",
        token=SecretStr("nrt_live_secret"),
        transport=httpx.MockTransport(respond),
    ) as client:
        await client.agents.send_turn(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            agent_id="agent-1",
            conversation_id=CONVERSATION_ID,
            text="Hi",
        )

    assert len(seen_ids) == 1
    assert UUID(seen_ids[0]).version == 4
