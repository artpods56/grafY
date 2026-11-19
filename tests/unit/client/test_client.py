import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from grafy_core.domain.collaboration import RenameProjectCommand
from grafy_core.domain.graph_documents import GraphDocument, GraphNode, GraphPoint

from grafy_client import (
    ExecutionTimeoutError,
    GrafyClient,
    GrafyClientError,
    ProjectHead,
    RunTarget,
)


WORKSPACE_ID = UUID("11111111-1111-4111-8111-111111111111")


def _catalog_payload() -> dict[str, object]:
    return {
        "plugins": [],
        "artifact_types": [],
        "nodes": [
            {
                "operator_id": "text.input",
                "operator_version": 1,
                "plugin_slug": "text",
                "title": "Text",
                "description": "Produces text.",
                "config_schema": {},
                "input_schema": {},
                "output_schema": {},
                "inputs": [],
                "outputs": [
                    {
                        "name": "text",
                        "direction": "output",
                        "artifact_type": {
                            "id": "scalar.text",
                            "schema_version": 1,
                        },
                        "shape": "one",
                        "accepted_shapes": ["one"],
                    }
                ],
                "origin": "builtin",
                "runnable": True,
            }
        ],
        "artifact_conversions": [
            {
                "key": {"id": "text.to_markdown", "version": 1},
                "source_artifact_type": {
                    "id": "scalar.text",
                    "schema_version": 1,
                },
                "target_artifact_type": {
                    "id": "text.markdown",
                    "schema_version": 1,
                },
                "title": "Text to Markdown",
            }
        ],
    }


@pytest.mark.parametrize(
    ("base_url", "message"),
    [
        ("ftp://grafy.test", "must use HTTP or HTTPS"),
        ("http://grafy.test", "must use HTTPS unless it targets localhost"),
        ("https://user:password@grafy.test", "must not contain user information"),
    ],
)
def test_client_rejects_unsafe_base_urls(base_url: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        GrafyClient(
            base_url=base_url,
            token=SecretStr("nrt_live_secret"),
        )


@pytest.mark.asyncio
async def test_client_allows_plain_http_only_for_loopback_development() -> None:
    async with GrafyClient(
        base_url="http://127.0.0.1:8000",
        token=SecretStr("nrt_live_secret"),
        transport=httpx.MockTransport(lambda _request: httpx.Response(200, json={})),
    ) as client:
        assert "http://127.0.0.1:8000" in repr(client)


@pytest.mark.asyncio
async def test_catalog_uses_bearer_pat_and_returns_typed_snapshot() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == f"/v1/workspaces/{WORKSPACE_ID}/nodes"
        assert request.headers["Authorization"] == "Bearer nrt_live_secret"
        return httpx.Response(200, json=_catalog_payload())

    client = GrafyClient(
        base_url="https://grafy.test",
        token=SecretStr("nrt_live_secret"),
        transport=httpx.MockTransport(respond),
    )

    async with client:
        catalog = await client.catalog.get(WORKSPACE_ID)

    assert catalog.nodes[0].operator_id == "text.input"
    assert catalog.artifact_conversions[0].source.id == "scalar.text"
    assert catalog.artifact_conversions[0].target.id == "text.markdown"
    assert "nrt_live_secret" not in repr(client)


PROJECT_ID = UUID("22222222-2222-4222-8222-222222222222")
ROOM_EPOCH = UUID("44444444-4444-4444-8444-444444444444")
RUN_ID = UUID("55555555-5555-4555-8555-555555555555")


def _head_payload(sequence: int = 0) -> dict[str, object]:
    return {
        "project_id": str(PROJECT_ID),
        "room_epoch": str(ROOM_EPOCH),
        "collaboration_sequence": sequence,
        "checkpoint_sequence": 0,
        "checkpoint_revision": 1,
        "name": "Vision E2E",
        "updated_at": "2026-09-01T10:00:00Z",
        "document": {"graphs": []},
    }


def _run_payload(status: str) -> dict[str, object]:
    return {
        "id": str(RUN_ID),
        "workspace_id": str(WORKSPACE_ID),
        "project_id": str(PROJECT_ID),
        "graph_id": "main",
        "targets": [{"node_id": "text", "call_path": []}],
        "started_by_user_id": None,
        "status": status,
        "created_at": "2026-09-01T10:00:00Z",
        "finished_at": None if status == "running" else "2026-09-01T10:00:01Z",
        "error": None,
    }


def _client(handler: httpx.MockTransport) -> GrafyClient:
    return GrafyClient(
        base_url="https://grafy.test",
        token=SecretStr("nrt_live_secret"),
        transport=handler,
    )


@pytest.mark.asyncio
async def test_project_create_and_commands_use_the_project_contract() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        base = f"/v1/workspaces/{WORKSPACE_ID}/projects"
        if request.method == "POST" and request.url.path == base:
            assert json.loads(request.content) == {
                "name": "Vision E2E",
                "graph_id": "main",
                "graph_name": "Main",
            }
            return httpx.Response(
                201,
                json={
                    "id": str(PROJECT_ID),
                    "name": "Vision E2E",
                    "created_at": "2026-09-01T10:00:00Z",
                    "updated_at": "2026-09-01T10:00:00Z",
                },
            )
        if request.url.path == f"{base}/{PROJECT_ID}/head":
            return httpx.Response(200, json=_head_payload())
        assert request.url.path == f"{base}/{PROJECT_ID}/commands"
        body = json.loads(request.content)
        assert body["room_epoch"] == str(ROOM_EPOCH)
        assert body["observed_sequence"] == 0
        assert body["commands"] == [
            {
                "kind": "rename_project",
                "name": "Renamed",
                "expected_name": "Vision E2E",
            }
        ]
        return httpx.Response(
            200,
            json={
                "head": _head_payload(1),
                "receipt": {
                    "command_id": body["command_id"],
                    "outcome": "accepted",
                    "accepted_sequence": 1,
                    "room_epoch": str(ROOM_EPOCH),
                    "deduplicated": False,
                },
            },
        )

    async with _client(httpx.MockTransport(respond)) as client:
        project = await client.projects.create(WORKSPACE_ID, name="Vision E2E")
        head = await client.projects.head(WORKSPACE_ID, project.id)
        submitted = await client.projects.submit_commands(
            WORKSPACE_ID,
            project.id,
            head=head,
            commands=[RenameProjectCommand(name="Renamed", expected_name="Vision E2E")],
        )

    assert project.id == PROJECT_ID
    assert submitted.head.collaboration_sequence == 1
    assert submitted.receipt.outcome == "accepted"


@pytest.mark.asyncio
async def test_empty_command_batch_is_refused_before_the_request() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request expected")

    async with _client(httpx.MockTransport(respond)) as client:
        with pytest.raises(ValueError, match="must not be empty"):
            await client.projects.submit_commands(
                WORKSPACE_ID,
                PROJECT_ID,
                head=ProjectHead.model_validate(_head_payload()),
                commands=[],
            )


UPLOAD_ID = "77777777-7777-4777-8777-777777777777"
ARTIFACT_ID = "88888888-8888-4888-8888-888888888888"


def _upload_item() -> dict[str, object]:
    return {
        "upload_key": UPLOAD_ID,
        "filename": "scan.tif",
        "byte_size": 9,
        "artifact_id": ARTIFACT_ID,
        "artifact_type": "file.tiff@1",
    }


@pytest.mark.asyncio
async def test_upload_streams_a_file_to_the_api_target_then_completes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "scan.tif"
    source.write_bytes(b"TIFFBYTES")
    seen: list[tuple[str, str]] = []
    uploads = f"/v1/workspaces/{WORKSPACE_ID}/uploads"

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        assert request.headers["Authorization"] == "Bearer nrt_live_secret"
        if request.url.path == uploads:
            assert json.loads(request.content) == {
                "filename": "scan.tif",
                "byte_size": 9,
                "content_type": "image/tiff",
            }
            return httpx.Response(
                201,
                json={
                    "kind": "api",
                    "upload_id": UPLOAD_ID,
                    "url": f"{uploads}/{UPLOAD_ID}/content",
                    "method": "PUT",
                    "expires_at": "2026-09-01T10:15:00Z",
                    "headers": {},
                },
            )
        if request.method == "PUT":
            assert request.headers["Content-Length"] == "9"
            assert request.read() == b"TIFFBYTES"
            return httpx.Response(204)
        return httpx.Response(200, json=_upload_item())

    async with _client(httpx.MockTransport(respond)) as client:
        upload = await client.uploads.upload(WORKSPACE_ID, source, chunk_bytes=4)

    assert seen == [
        ("POST", uploads),
        ("PUT", f"{uploads}/{UPLOAD_ID}/content"),
        ("POST", f"{uploads}/{UPLOAD_ID}/complete"),
    ]
    assert upload.artifact_type == "file.tiff@1"


@pytest.mark.asyncio
async def test_upload_to_signed_storage_never_sends_the_bearer_token() -> None:
    signed = "https://storage.test/workbench-artifacts/objects/x?X-Amz-Signature=s"

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "storage.test":
            assert "Authorization" not in request.headers
            assert request.headers["If-None-Match"] == "*"
            assert request.read() == b"a,b\n1,2\n"
            return httpx.Response(200)
        if request.url.path.endswith("/uploads"):
            return httpx.Response(
                201,
                json={
                    "kind": "storage",
                    "upload_id": UPLOAD_ID,
                    "url": signed,
                    "method": "PUT",
                    "expires_at": "2026-09-01T10:15:00Z",
                    "headers": {"If-None-Match": "*"},
                },
            )
        return httpx.Response(200, json={**_upload_item(), "filename": "t.csv"})

    async with _client(httpx.MockTransport(respond)) as client:
        upload = await client.uploads.upload(
            WORKSPACE_ID, b"a,b\n1,2\n", filename="t.csv"
        )

    assert upload.filename == "t.csv"


@pytest.mark.asyncio
async def test_a_token_resolves_its_one_workspace() -> None:
    workspace = {
        "id": str(WORKSPACE_ID),
        "slug": "lab",
        "name": "Lab",
        "kind": "shared",
        "role": "editor",
        "capabilities": ["view_project"],
    }

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/workspaces"
        return httpx.Response(200, json=[workspace])

    async with _client(httpx.MockTransport(respond)) as client:
        current = await client.workspaces.current()

    assert current.id == WORKSPACE_ID
    assert current.capabilities == ("view_project",)


def _head_with_graph(sequence: int, document: dict[str, object]) -> dict[str, object]:
    return {
        **_head_payload(sequence),
        "document": {"graphs": [{"id": "main", "name": "Main", "document": document}]},
    }


@pytest.mark.asyncio
async def test_upsert_graph_replaces_a_changed_graph_and_checkpoints() -> None:
    base = f"/v1/workspaces/{WORKSPACE_ID}/projects/{PROJECT_ID}"
    sent: list[object] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"{base}/head":
            return httpx.Response(200, json=_head_with_graph(0, {}))
        if request.url.path == f"{base}/commands":
            body = json.loads(request.content)
            sent.append(body["commands"])
            return httpx.Response(
                200,
                json={
                    "head": _head_with_graph(1, {"nodes": []}),
                    "receipt": {
                        "command_id": body["command_id"],
                        "outcome": "accepted",
                        "accepted_sequence": 1,
                        "room_epoch": str(ROOM_EPOCH),
                        "deduplicated": False,
                    },
                },
            )
        assert request.url.path == f"{base}/checkpoints"
        assert json.loads(request.content)["expected_sequence"] == 1
        checkpointed = {**_head_with_graph(1, {}), "checkpoint_sequence": 1}
        return httpx.Response(200, json={"head": checkpointed})

    document = GraphDocument(
        nodes=(
            GraphNode(
                kind="builtin",
                id="text",
                operator_id="text.input",
                operator_version=1,
                config={"text": "x"},
                position=GraphPoint(x=0, y=0),
            ),
        )
    )
    async with _client(httpx.MockTransport(respond)) as client:
        head = await client.projects.upsert_graph(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            document=document,
            name="Renamed",
        )

    commands = cast(list[dict[str, Any]], sent[0])
    assert [command["kind"] for command in commands] == ["in_graph", "rename_graph"]
    assert commands[0]["command"]["kind"] == "replace_document"
    assert commands[1] == {
        "kind": "rename_graph",
        "graph_id": "main",
        "name": "Renamed",
        "expected_name": "Main",
    }
    assert head.checkpoint_sequence == 1


@pytest.mark.asyncio
async def test_table_query_and_geo_render_use_the_artifact_routes() -> None:
    artifact = f"/v1/workspaces/{WORKSPACE_ID}/artifacts/{ARTIFACT_ID}"

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"{artifact}/table/query":
            body = json.loads(request.content)
            assert body["filter_groups"] == [
                {"rows": [{"values": {"column_2": "roman"}}]}
            ]
            assert body["highlight_groups"] == []
            return httpx.Response(
                200,
                json={
                    "columns": [
                        {"id": "column_2", "title": "period", "value_type": "text"}
                    ],
                    "rows": [{"column_2": {"display": "roman", "truncated": False}}],
                    "row_indices": [0],
                    "highlighted_row_indices": [],
                    "offset": 0,
                    "limit": 50,
                    "total_rows": 1,
                    "column_offset": 0,
                    "column_limit": 25,
                    "total_columns": 1,
                },
            )
        assert request.url.path == f"{artifact}/geo/render"
        return httpx.Response(
            200,
            json={
                "artifact_id": ARTIFACT_ID,
                "kind": "raster_scan",
                "basemap": "none",
                "initial_bounds": [14.0, 49.0, 24.0, 55.0],
                "layers": [{"id": "scan"}],
            },
        )

    async with _client(httpx.MockTransport(respond)) as client:
        page = await client.artifacts.table_query(
            WORKSPACE_ID, UUID(ARTIFACT_ID), filter_rows=[{"column_2": "roman"}]
        )
        render = await client.artifacts.geo_render(WORKSPACE_ID, UUID(ARTIFACT_ID))

    assert page.row_indices == (0,)
    assert page.rows[0]["column_2"].display == "roman"
    assert render.initial_bounds == (14.0, 49.0, 24.0, 55.0)


@pytest.mark.asyncio
async def test_secret_configuration_error_keeps_context_and_redacts_secrets() -> None:
    request_id = "33333333-3333-4333-8333-333333333333"

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == (
            f"/v1/workspaces/{WORKSPACE_ID}/projects/{PROJECT_ID}/graphs/main/"
            "nodes/llm/secrets/api_key"
        )
        assert json.loads(request.content) == {
            "value": "sk-test-sensitive",
            "expected_head_sequence": 3,
        }
        return httpx.Response(
            422,
            headers={"X-Request-ID": request_id},
            json={"detail": "Provider rejected sk-test-sensitive"},
        )

    async with _client(httpx.MockTransport(respond)) as client:
        with pytest.raises(GrafyClientError) as caught:
            await client.projects.configure_secret(
                WORKSPACE_ID,
                PROJECT_ID,
                graph_id="main",
                node_id="llm",
                secret_name="api_key",
                value=SecretStr("sk-test-sensitive"),
                head=ProjectHead.model_validate(_head_payload(3)),
            )

    error = caught.value
    assert error.operation == "configure node secret"
    assert error.status_code == 422
    assert error.request_id == request_id
    assert "<redacted>" in str(error)
    assert "sk-test-sensitive" not in str(error)
    assert "nrt_live_secret" not in str(error)
    assert "sk-test-sensitive" not in repr(error)


@pytest.mark.asyncio
async def test_run_start_wait_and_cancel() -> None:
    polls = iter(["running", "succeeded"])
    runs = f"/v1/workspaces/{WORKSPACE_ID}/projects/{PROJECT_ID}/runs"

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == runs:
            assert json.loads(request.content) == {
                "graph_id": "main",
                "targets": [{"node_id": "text", "call_path": []}],
            }
            return httpx.Response(201, json=_run_payload("running"))
        assert request.url.path == f"{runs}/{RUN_ID}"
        return httpx.Response(200, json=_run_payload(next(polls)))

    async with _client(httpx.MockTransport(respond)) as client:
        run = await client.runs.start(
            WORKSPACE_ID,
            PROJECT_ID,
            graph_id="main",
            targets=[RunTarget(node_id="text")],
        )
        finished = await client.runs.wait(
            WORKSPACE_ID, PROJECT_ID, run.id, timeout=5, poll_interval=0
        )

    assert not run.terminal
    assert finished.status == "succeeded"
    assert finished.terminal


@pytest.mark.asyncio
async def test_run_wait_reports_id_and_last_status_on_timeout() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_run_payload("running"))

    async with _client(httpx.MockTransport(respond)) as client:
        with pytest.raises(ExecutionTimeoutError) as caught:
            await client.runs.wait(
                WORKSPACE_ID, PROJECT_ID, RUN_ID, timeout=0.01, poll_interval=0
            )

    assert str(RUN_ID) in str(caught.value)
    assert "running" in str(caught.value)


@pytest.mark.asyncio
async def test_run_cancel_and_instance_states() -> None:
    base = f"/v1/workspaces/{WORKSPACE_ID}/projects/{PROJECT_ID}"

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"{base}/runs/{RUN_ID}/cancel":
            assert request.method == "POST"
            return httpx.Response(200, json=_run_payload("cancelled"))
        assert request.url.path == f"{base}/graphs/main/instances"
        return httpx.Response(
            200,
            json={
                "instances": [
                    {
                        "key": {
                            "project_id": str(PROJECT_ID),
                            "graph_id": "main",
                            "call_path": [],
                            "node_id": "text",
                            "map_index": None,
                        },
                        "state": "stale",
                        "fingerprint": "abc",
                        "last_result_fingerprint": None,
                        "error": None,
                    }
                ]
            },
        )

    async with _client(httpx.MockTransport(respond)) as client:
        cancelled = await client.runs.cancel(WORKSPACE_ID, PROJECT_ID, RUN_ID)
        states = await client.runs.instances(WORKSPACE_ID, PROJECT_ID, "main")

    assert cancelled.status == "cancelled"
    assert [(state.key.node_id, state.state) for state in states] == [("text", "stale")]
