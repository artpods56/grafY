import json
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from grafy_core.domain.collaboration import RenameProjectCommand

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


@pytest.mark.asyncio
async def test_upload_create_sends_multipart_bytes_and_returns_upload_item() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == f"/v1/workspaces/{WORKSPACE_ID}/uploads"
        assert request.headers["Content-Type"].startswith("multipart/form-data;")
        assert b'filename="pixel.png"' in request.content
        assert b"PNG_BYTES" in request.content
        return httpx.Response(
            200,
            json={
                "upload_key": "uploads/pixel.png",
                "filename": "pixel.png",
                "byte_size": 9,
            },
        )

    async with GrafyClient(
        base_url="https://grafy.test",
        token=SecretStr("nrt_live_secret"),
        transport=httpx.MockTransport(respond),
    ) as client:
        upload = await client.uploads.create(
            WORKSPACE_ID,
            filename="pixel.png",
            content=b"PNG_BYTES",
            content_type="image/png",
        )

    assert upload.upload_key == "uploads/pixel.png"
    assert upload.filename == "pixel.png"
    assert upload.byte_size == 9


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
