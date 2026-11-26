"""The `/mcp` endpoint: PAT-only admission and tools that act through the REST API.

Real sessions and real personal access tokens drive these requests with no identity
override, so a refusal can only come from the credential the caller presented. The
MCP requests are plain stateless Streamable HTTP JSON-RPC posts, the wire form any
MCP client sends.
"""

import asyncio
import base64
import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr

from grafy_api.auth import CSRF_COOKIE, SESSION_COOKIE, AuthService
from grafy_api.settings import Settings
from grafy_core.application.identity import IdentityService
from grafy_core.domain.identity import (
    ActorContext,
    Workspace,
    WorkspaceCapability,
    WorkspaceKind,
    WorkspaceRole,
)
from grafy_persistence.database import Database
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork
from grafy_shared.config import AppConfig

from tests.support.factories.identity import IdentitySeeder
from tests.testkit import client_with_overrides, create_db_url, db, with_setting_values

EDITOR_SCOPES = (
    WorkspaceCapability.VIEW_PROJECT,
    WorkspaceCapability.VIEW_ARTIFACTS,
    WorkspaceCapability.VIEW_RUNS,
    WorkspaceCapability.CREATE_PROJECT,
    WorkspaceCapability.EDIT_PROJECT,
    WorkspaceCapability.CHECKPOINT_PROJECT,
    WorkspaceCapability.START_RUN,
    WorkspaceCapability.CANCEL_RUN,
)
READER_SCOPES = (
    WorkspaceCapability.VIEW_PROJECT,
    WorkspaceCapability.VIEW_ARTIFACTS,
)
ACCEPT = "application/json, text/event-stream"


@dataclass(frozen=True)
class Stage:
    client: TestClient
    workspace: Workspace
    other_workspace: Workspace
    editor_token: str
    reader_token: str
    session_cookie: str
    csrf_value: str

    def rpc(
        self,
        method: str,
        params: dict[str, object],
        *,
        token: str | None,
        cookies: dict[str, str] | None = None,
    ) -> httpx.Response:
        headers = {"Accept": ACCEPT}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        self.client.cookies.clear()
        for name, value in (cookies or {}).items():
            self.client.cookies.set(name, value)
        try:
            return self.client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                headers=headers,
            )
        finally:
            self.client.cookies.clear()

    def tool(
        self, name: str, arguments: dict[str, object], *, token: str
    ) -> dict[str, Any]:
        """Call one tool and return its JSON-RPC result (``isError`` included)."""

        response = self.rpc(
            "tools/call", {"name": name, "arguments": arguments}, token=token
        )
        assert response.status_code == 200, response.text
        body = cast(dict[str, Any], response.json())
        assert "result" in body, body
        return cast(dict[str, Any], body["result"])

    def ok(self, name: str, arguments: dict[str, object], *, token: str) -> Any:
        result = self.tool(name, arguments, token=token)
        assert not result.get("isError"), result
        structured = cast(dict[str, Any], result["structuredContent"])
        return structured.get("result", structured)


def _auth_service(settings: Settings, database: Database) -> AuthService:
    def unit_of_work_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(database.sessions)

    return AuthService(
        auth=settings.auth,
        public_origin=settings.app.public_origin,
        unit_of_work_factory=unit_of_work_factory,
        identity_service=IdentityService(unit_of_work_factory),
    )


@contextmanager
def stage_for(tmp_path: Path, name: str) -> Iterator[Stage]:
    database_url = create_db_url(tmp_path, name)
    settings = with_setting_values(
        Settings(
            app=AppConfig(
                public_origin="http://testserver",
                database_url=SecretStr("sqlite+aiosqlite:///"),
            )
        ),
        database_url=SecretStr(database_url),
        workspace=tmp_path / "workbench",
    )

    async def prepare() -> tuple[Workspace, Workspace, str, str, str, str]:
        async with db(database_url) as database:
            seeder = IdentitySeeder(lambda: SqlAlchemyUnitOfWork(database.sessions))
            owner = await seeder.user(email="owner@example.test", display_name="Owner")
            workspace = Workspace(slug="lab", name="Lab", kind=WorkspaceKind.SHARED)
            other = Workspace(slug="other", name="Other", kind=WorkspaceKind.SHARED)
            async with SqlAlchemyUnitOfWork(database.sessions) as uow:
                await uow.identity.add_workspace(workspace)
                await uow.identity.add_workspace(other)
                await uow.commit()
            for target in (workspace, other):
                await seeder.membership(
                    user=owner, workspace=target, role=WorkspaceRole.OWNER
                )
            auth = _auth_service(settings, database)
            identity = IdentityService(lambda: SqlAlchemyUnitOfWork(database.sessions))
            raw_tokens: list[str] = []
            for label, scopes in (("editor", EDITOR_SCOPES), ("reader", READER_SCOPES)):
                token, raw = auth.issue_personal_access_token(
                    user_id=owner.id,
                    workspace_id=workspace.id,
                    label=label,
                    scopes=scopes,
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
                _ = await identity.create_personal_access_token(
                    actor=ActorContext(user_id=owner.id), token=token
                )
                raw_tokens.append(raw)
            session = await auth.issue_session(owner.id)
            return (
                workspace,
                other,
                raw_tokens[0],
                raw_tokens[1],
                session.cookie_value,
                session.csrf_value,
            )

    workspace, other, editor, reader, cookie, csrf_value = asyncio.run(prepare())
    with client_with_overrides(settings=settings) as client:
        yield Stage(
            client=client,
            workspace=workspace,
            other_workspace=other,
            editor_token=editor,
            reader_token=reader,
            session_cookie=cookie,
            csrf_value=csrf_value,
        )


def test_mcp_admits_only_a_bearer_personal_access_token(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-admission.sqlite3") as stage:
        session = {SESSION_COOKIE: stage.session_cookie}

        anonymous = stage.rpc("tools/list", {}, token=None)
        forged = stage.rpc("tools/list", {}, token="grafy_pat_not-a-token")
        ambient = stage.rpc("tools/list", {}, token=stage.editor_token, cookies=session)
        cookie_only = stage.rpc("tools/list", {}, token=None, cookies=session)
        admitted = stage.rpc("tools/list", {}, token=stage.editor_token)

    for refused in (anonymous, forged, ambient, cookie_only):
        assert refused.status_code == 401, refused.text
        assert refused.headers["WWW-Authenticate"] == "Bearer"
    assert admitted.status_code == 200, admitted.text
    names = {tool["name"] for tool in admitted.json()["result"]["tools"]}
    assert {
        "get_workspace",
        "list_projects",
        "list_nodes",
        "describe_node",
        "author_graph",
        "apply_project_commands",
        "start_run",
        "wait_for_run",
        "get_instance_result",
        "read_table_page",
        "query_table",
        "get_geo_render",
        "create_artifact",
        "list_authorable_artifact_types",
    } <= names


def test_artifact_authoring_rest_round_trips(tmp_path: Path) -> None:
    with stage_for(tmp_path, "author-artifacts.sqlite3") as stage:
        token = stage.editor_token
        headers = {"Authorization": f"Bearer {token}"}
        url = f"/v1/workspaces/{stage.workspace.id}/artifacts"
        with BytesIO() as image, Image.new("L", (4, 4)) as tiff:
            tiff.save(image, "TIFF")
            uploaded = stage.ok(
                "upload_file",
                {
                    "filename": "scan.tif",
                    "content_base64": base64.b64encode(image.getvalue()).decode(),
                },
                token=token,
            )
        source = {
            "artifact_id": uploaded["artifact_id"],
            "artifact_type": "file.tiff",
            "schema_version": 1,
            "content_hash": uploaded["content_hash"],
        }
        regions: dict[str, object] = {
            "source": source,
            "window": {"page": 0, "col": 0, "row": 0, "width": 4, "height": 4},
            "regions": [],
        }
        cases: dict[str, dict[str, object]] = {
            "scalar.text": {"value": "Draft"},
            "table.data": {
                "columns": [{"id": "name", "title": "Name", "value_type": "text"}],
                "rows": [{"name": "Site A"}],
            },
            "ocr.tiff_text_regions": regions,
            "geo.feature_collection": {
                "type": "FeatureCollection",
                "crs": "EPSG:4326",
                "features": [],
                "source_name": "Empty collection",
                "bounds": None,
            },
        }
        created_ids: dict[str, str] = {}
        for artifact_type, payload in cases.items():
            response = stage.client.post(
                url,
                headers=headers,
                json={"artifact_type": artifact_type, "payload": payload},
            )
            assert response.status_code == 201, response.text
            created = response.json()
            assert created["artifact_type"] == artifact_type
            assert created["schema_version"] == 1
            assert len(created["content_hash"]) == 64
            assert created["derived_from_artifact_id"] is None
            artifact_id = created["artifact_id"]
            created_ids[artifact_type] = artifact_id
            content = stage.client.get(f"{url}/{artifact_id}/content", headers=headers)
            assert content.status_code == 200, content.text
            assert content.headers["Content-Type"] in {
                "application/json",
                "application/geo+json",
            }
            assert content.json() == payload

        table = stage.client.get(
            f"{url}/{created_ids['table.data']}/table/schema", headers=headers
        )
        assert table.status_code == 200, table.text
        assert table.json() == {
            "columns": cases["table.data"]["columns"],
            "total_rows": 1,
        }

        invalid_cases: list[tuple[str, dict[str, object]]] = [
            ("scalar.text", {"value": 1}),
            ("unknown.artifact", {}),
            ("file.tiff", {}),
            ("image.raster", {}),
            ("table.data", {"columns": [], "rows": [{"unknown": 1}]}),
            (
                "ocr.tiff_text_regions",
                {
                    **regions,
                    "source": {**source, "artifact_id": created_ids["scalar.text"]},
                },
            ),
        ]
        for artifact_type, payload in invalid_cases:
            response = stage.client.post(
                url,
                headers=headers,
                json={"artifact_type": artifact_type, "payload": payload},
            )
            assert response.status_code == 422, response.text

        missing = stage.client.post(
            url,
            headers=headers,
            json={
                "artifact_type": "ocr.tiff_text_regions",
                "payload": {
                    **regions,
                    "source": {**source, "artifact_id": str(uuid4())},
                },
            },
        )
        assert missing.status_code == 404, missing.text

        text = {"artifact_type": "scalar.text", "payload": {"value": "Edited"}}
        denied = stage.client.post(
            url, headers={"Authorization": f"Bearer {stage.reader_token}"}, json=text
        )
        assert denied.status_code == 403, denied.text
        derive = {**text, "derived_from_artifact_id": created_ids["scalar.text"]}
        edit = stage.client.post(url, headers=headers, json=derive)
        assert edit.status_code == 201, edit.text
        assert edit.json()["artifact_id"] != created_ids["scalar.text"]
        assert edit.json()["derived_from_artifact_id"] == created_ids["scalar.text"]
        original = stage.client.get(
            f"{url}/{created_ids['scalar.text']}/content", headers=headers
        )
        assert original.json() == {"value": "Draft"}

        # A browser owner can write to both Workspaces.
        stage.client.cookies.set(SESSION_COOKIE, stage.session_cookie)
        stage.client.cookies.set(CSRF_COOKIE, stage.csrf_value)
        browser_headers = {
            "Origin": "http://testserver",
            "X-CSRF-Token": stage.csrf_value,
        }
        other_url = f"/v1/workspaces/{stage.other_workspace.id}/artifacts"
        assert (
            stage.client.post(other_url, headers=browser_headers, json=text).status_code
            == 201
        )
        for body in (
            derive,
            {"artifact_type": "ocr.tiff_text_regions", "payload": regions},
        ):
            other = stage.client.post(other_url, headers=browser_headers, json=body)
            assert other.status_code == 404, other.text


def test_mcp_places_an_authored_artifact_and_can_replace_its_bound_origin(
    tmp_path: Path,
) -> None:
    with stage_for(tmp_path, "mcp-authored-artifacts.sqlite3") as stage:
        token = stage.editor_token
        types = stage.ok("list_authorable_artifact_types", {}, token=token)
        schemas = {spec["key"]["id"]: spec["payload_schema"] for spec in types}
        assert {
            "scalar.text",
            "table.data",
            "geo.feature_collection",
            "ocr.tiff_text_regions",
        } <= schemas.keys()
        assert "image.raster" not in schemas and "file.tiff" not in schemas
        assert "features" in schemas["geo.feature_collection"]["properties"]

        project = stage.ok(
            "create_project", {"name": "Authored artifacts"}, token=token
        )
        card_id = "artifact-viewer-authored-text"
        prior: str | None = None
        for value in ("Draft", "Revision"):
            created = stage.ok(
                "create_artifact",
                {
                    "artifact_type": "scalar.text",
                    "payload": {"value": value},
                    "derived_from_artifact_id": prior,
                },
                token=token,
            )
            assert created["derived_from_artifact_id"] == prior
            assert created["artifact_id"] != prior
            prior = created["artifact_id"]
            content = stage.ok(
                "read_artifact_text", {"artifact_id": prior}, token=token
            )
            assert json.loads(content["text"]) == {"value": value}
            card_ref = {
                "artifact_id": prior,
                "artifact_type": "scalar.text@1",
                "content_hash": created["content_hash"],
            }
            _ = stage.ok(
                "author_graph",
                {
                    "project_id": project["id"],
                    "graph_id": "main",
                    "nodes": [{"id": "collect", "operator_id": "sequence.collect"}],
                    "cards": [{"id": card_id, "artifacts": [card_ref]}],
                    "origins": [
                        {
                            "target": {"node": "collect", "port": "items"},
                            "card": card_id,
                            "artifacts": [card_ref],
                        }
                    ],
                },
                token=token,
            )
            head = stage.ok(
                "get_project",
                {"project_id": project["id"], "graph_id": "main"},
                token=token,
            )
            document = head["document"]["graphs"][0]["document"]
            viewer = document["presentation"]["viewers"][0]
            origin = document["origins"][0]
            assert viewer["id"] == card_id
            assert viewer["artifact_ref"]["artifact_id"] == prior
            assert origin["source_card_ids"] == [card_id]
            assert origin["value"]["artifact_id"] == prior


def _counting_graph() -> dict[str, object]:
    return {
        "nodes": [
            {"id": "two", "operator_id": "value.integer", "config": {"value": 2}},
            {"id": "three", "operator_id": "value.integer", "config": {"value": 3}},
            {"id": "collect", "operator_id": "sequence.collect"},
            {"id": "count", "operator_id": "sequence.count"},
        ],
        "connections": [
            {
                "source": {"node": "two", "port": "value"},
                "target": {"node": "collect", "port": "items"},
            },
            {
                "source": {"node": "three", "port": "value"},
                "target": {"node": "collect", "port": "items"},
            },
            {
                "source": {"node": "collect", "port": "items"},
                "target": {"node": "count", "port": "items"},
            },
        ],
        "cards": [
            {
                "id": "artifact-viewer-count",
                "follows": {"node": "count", "port": "count"},
            }
        ],
    }


def test_an_agent_authors_runs_and_reads_a_graph(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-flow.sqlite3") as stage:
        token = stage.editor_token
        workspace = stage.ok("get_workspace", {}, token=token)
        project = stage.ok("create_project", {"name": "Agent built"}, token=token)
        authored = stage.ok(
            "author_graph",
            {"project_id": project["id"], "graph_id": "main", **_counting_graph()},
            token=token,
        )
        head = stage.ok(
            "get_project",
            {"project_id": project["id"], "graph_id": "main"},
            token=token,
        )
        run = stage.ok(
            "start_run",
            {"project_id": project["id"], "graph_id": "main"},
            token=token,
        )
        finished = stage.ok(
            "wait_for_run",
            {"project_id": project["id"], "run_id": run["id"], "timeout_seconds": 60},
            token=token,
        )
        result = stage.ok(
            "get_instance_result",
            {"project_id": project["id"], "graph_id": "main", "node_id": "count"},
            token=token,
        )
        projects = stage.ok("list_projects", {}, token=token)

    assert workspace["id"] == str(stage.workspace.id)
    assert set(workspace["capabilities"]) == {scope.value for scope in EDITOR_SCOPES}
    assert authored["checkpointed"] is True
    document = head["document"]["graphs"][0]["document"]
    assert [node["id"] for node in document["nodes"]] == [
        "two",
        "three",
        "collect",
        "count",
    ]
    assert document["presentation"]["links"][0]["target_viewer_id"] == (
        "artifact-viewer-count"
    )
    assert finished["status"] == "succeeded", finished
    assert result["instance"]["state"] == "fresh"
    assert "count" in result["outputs"]
    assert [item["id"] for item in projects] == [project["id"]]


def test_a_tool_is_refused_by_the_route_its_token_cannot_use(tmp_path: Path) -> None:
    """The reader token can look, and the REST route refuses its edit with a 403."""

    with stage_for(tmp_path, "mcp-scope.sqlite3") as stage:
        project = stage.ok(
            "create_project", {"name": "Owned"}, token=stage.editor_token
        )
        listed = stage.ok("list_projects", {}, token=stage.reader_token)
        refused = stage.tool(
            "author_graph",
            {"project_id": project["id"], "graph_id": "main", **_counting_graph()},
            token=stage.reader_token,
        )
        not_created = stage.tool(
            "create_project", {"name": "Nope"}, token=stage.reader_token
        )

    assert [item["id"] for item in listed] == [project["id"]]
    for result in (refused, not_created):
        assert result["isError"] is True
        assert "403" in result["content"][0]["text"], result


def test_an_invalid_graph_is_refused_before_anything_is_written(
    tmp_path: Path,
) -> None:
    with stage_for(tmp_path, "mcp-invalid.sqlite3") as stage:
        project = stage.ok(
            "create_project", {"name": "Strict"}, token=stage.editor_token
        )
        refused = stage.tool(
            "author_graph",
            {
                "project_id": project["id"],
                "graph_id": "main",
                "nodes": [{"id": "count", "operator_id": "sequence.count"}],
            },
            token=stage.editor_token,
        )
        head = stage.ok(
            "get_project", {"project_id": project["id"]}, token=stage.editor_token
        )

    assert refused["isError"] is True
    assert "Graph is invalid" in refused["content"][0]["text"]
    assert head["collaboration_sequence"] == 0


def test_an_agent_uploads_a_small_file_into_the_library(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-upload.sqlite3") as stage:
        uploaded = stage.ok(
            "upload_file",
            {
                "filename": "notes.txt",
                "content_base64": base64.b64encode(b"hello agent").decode(),
            },
            token=stage.editor_token,
        )
        library = stage.ok("list_library", {}, token=stage.editor_token)
        text = stage.ok(
            "read_artifact_text",
            {"artifact_id": uploaded["artifact_id"]},
            token=stage.editor_token,
        )

    assert uploaded["artifact_type"] == "file.txt@1"
    assert uploaded["saved_to_library"] is True
    assert [item["artifact"]["artifact_id"] for item in library] == [
        uploaded["artifact_id"]
    ]
    assert text == {"text": "hello agent", "byte_size": 11, "truncated": False}


def test_a_token_lists_only_its_own_workspace(tmp_path: Path) -> None:
    with stage_for(tmp_path, "mcp-workspaces.sqlite3") as stage:
        stage.client.cookies.clear()
        listed = stage.client.get(
            "/v1/workspaces",
            headers={"Authorization": f"Bearer {stage.reader_token}"},
        )
        stage.client.cookies.set(SESSION_COOKIE, stage.session_cookie)
        browser = stage.client.get("/v1/workspaces")
        stage.client.cookies.clear()

    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [str(stage.workspace.id)]
    assert set(listed.json()[0]["capabilities"]) == {
        scope.value for scope in READER_SCOPES
    }
    assert browser.status_code == 200, browser.text
    assert {item["id"] for item in browser.json()} == {
        str(stage.workspace.id),
        str(stage.other_workspace.id),
    }


def test_an_agent_imports_a_csv_and_queries_the_table(tmp_path: Path) -> None:
    csv = b"site,period\nA,roman\nB,medieval\nC,roman\n"
    with stage_for(tmp_path, "mcp-table.sqlite3") as stage:
        token = stage.editor_token
        uploaded = stage.ok(
            "upload_file",
            {"filename": "sites.csv", "content_base64": base64.b64encode(csv).decode()},
            token=token,
        )
        project = stage.ok("create_project", {"name": "Sites"}, token=token)
        source = {
            "artifact_id": uploaded["artifact_id"],
            "artifact_type": uploaded["artifact_type"],
        }
        _ = stage.ok(
            "author_graph",
            {
                "project_id": project["id"],
                "graph_id": "main",
                "nodes": [{"id": "import", "operator_id": "table.import"}],
                "cards": [
                    {"id": "artifact-viewer-file", "artifacts": [source]},
                    {
                        "id": "artifact-viewer-table",
                        "follows": {"node": "import", "port": "table"},
                    },
                ],
                "origins": [
                    {
                        "target": {"node": "import", "port": "file"},
                        "artifacts": [source],
                        "card": "artifact-viewer-file",
                    }
                ],
                "card_bindings": [
                    {
                        "source_card": "artifact-viewer-table",
                        "target_card": "artifact-viewer-file",
                        "fields": {"site": "site"},
                        "effects": ["filter"],
                    }
                ],
            },
            token=token,
        )
        run = stage.ok(
            "start_run", {"project_id": project["id"], "graph_id": "main"}, token=token
        )
        finished = stage.ok(
            "wait_for_run",
            {"project_id": project["id"], "run_id": run["id"]},
            token=token,
        )
        result = stage.ok(
            "get_instance_result",
            {"project_id": project["id"], "graph_id": "main", "node_id": "import"},
            token=token,
        )
        assert finished["status"] == "succeeded", result["instance"]["error"]
        assert uploaded["content_hash"] is not None
        table_id = result["outputs"]["table"]["artifact_id"]
        schema = stage.ok("get_table_schema", {"artifact_id": table_id}, token=token)
        page = stage.ok("read_table_page", {"artifact_id": table_id}, token=token)
        period = next(
            column["id"] for column in schema["columns"] if column["title"] == "period"
        )
        roman = stage.ok(
            "query_table",
            {"artifact_id": table_id, "match_rows": [{period: "roman"}]},
            token=token,
        )
        head = stage.ok(
            "get_project",
            {"project_id": project["id"], "graph_id": "main"},
            token=token,
        )

    assert uploaded["artifact_type"] == "file.csv@1"
    assert schema["total_rows"] == 3
    assert [column["title"] for column in schema["columns"]] == ["site", "period"]
    assert page["total_rows"] == 3
    assert roman["row_indices"] == [0, 2]
    document = head["document"]["graphs"][0]["document"]
    assert document["origins"][0]["source_card_ids"] == ["artifact-viewer-file"]
    assert document["presentation"]["bindings"][0]["effects"] == ["filter"]


def test_an_origin_resolves_the_exact_library_reference(tmp_path: Path) -> None:
    """An origin carries the stored hash; an unknown artifact needs one stated."""

    with stage_for(tmp_path, "mcp-origin.sqlite3") as stage:
        token = stage.editor_token
        uploaded = stage.ok(
            "upload_file",
            {
                "filename": "a.csv",
                "content_base64": base64.b64encode(b"x\n1\n").decode(),
            },
            token=token,
        )
        project = stage.ok("create_project", {"name": "Origins"}, token=token)
        spec = {
            "project_id": project["id"],
            "graph_id": "main",
            "nodes": [{"id": "import", "operator_id": "table.import"}],
        }
        artifact = {
            "artifact_id": uploaded["artifact_id"],
            "artifact_type": uploaded["artifact_type"],
        }
        _ = stage.ok(
            "author_graph",
            {
                **spec,
                "origins": [
                    {
                        "target": {"node": "import", "port": "file"},
                        "artifacts": [artifact],
                    }
                ],
            },
            token=token,
        )
        unknown = stage.tool(
            "author_graph",
            {
                **spec,
                "origins": [
                    {
                        "target": {"node": "import", "port": "file"},
                        "artifacts": [
                            {**artifact, "artifact_id": str(stage.workspace.id)}
                        ],
                    }
                ],
            },
            token=token,
        )
        head = stage.ok(
            "get_project",
            {"project_id": project["id"], "graph_id": "main"},
            token=token,
        )

    origin = head["document"]["graphs"][0]["document"]["origins"][0]
    assert origin["value"]["content_hash"] == uploaded["content_hash"]
    assert origin["source_card_ids"] is None
    assert unknown["isError"] is True
    assert "not in the Library" in unknown["content"][0]["text"]
