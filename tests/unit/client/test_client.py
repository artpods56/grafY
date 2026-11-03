import json
from uuid import UUID

import httpx
import pytest
from pydantic import SecretStr

from grafy_core.domain.graph_documents import GraphDocument

from grafy_client import ExecutionTimeoutError, GrafyClient, GrafyClientError


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


@pytest.mark.asyncio
async def test_graph_create_sends_canonical_document_and_returns_saved_graph() -> None:
    graph_id = UUID("22222222-2222-4222-8222-222222222222")
    document = GraphDocument()

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == f"/v1/workspaces/{WORKSPACE_ID}/graphs"
        assert json.loads(request.content) == {
            "name": "Vision E2E",
            "document": document.model_dump(mode="json"),
        }
        return httpx.Response(
            201,
            json={
                "id": str(graph_id),
                "name": "Vision E2E",
                "revision": 1,
                "created_at": "2026-09-01T10:00:00Z",
                "updated_at": "2026-09-01T10:00:00Z",
                "document": document.model_dump(mode="json"),
            },
        )

    async with GrafyClient(
        base_url="https://grafy.test",
        token=SecretStr("nrt_live_secret"),
        transport=httpx.MockTransport(respond),
    ) as client:
        saved = await client.graphs.create(
            WORKSPACE_ID,
            name="Vision E2E",
            document=document,
        )

    assert saved.id == graph_id
    assert saved.revision == 1
    assert saved.document == document


@pytest.mark.asyncio
async def test_graph_get_and_update_use_typed_saved_graph_contract() -> None:
    graph_id = UUID("22222222-2222-4222-8222-222222222222")
    document = GraphDocument()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            revision = 1
            name = "Existing graph"
        else:
            assert request.method == "PUT"
            assert json.loads(request.content) == {
                "name": "Updated graph",
                "document": document.model_dump(mode="json"),
                "expected_revision": 1,
            }
            revision = 2
            name = "Updated graph"
        assert request.url.path == (f"/v1/workspaces/{WORKSPACE_ID}/graphs/{graph_id}")
        return httpx.Response(
            200,
            json={
                "id": str(graph_id),
                "name": name,
                "revision": revision,
                "created_at": "2026-09-01T10:00:00Z",
                "updated_at": "2026-09-01T10:00:00Z",
                "document": document.model_dump(mode="json"),
            },
        )

    async with GrafyClient(
        base_url="https://grafy.test",
        token=SecretStr("nrt_live_secret"),
        transport=httpx.MockTransport(respond),
    ) as client:
        existing = await client.graphs.get(WORKSPACE_ID, graph_id)
        updated = await client.graphs.update(
            WORKSPACE_ID,
            graph_id,
            name="Updated graph",
            document=document,
            expected_revision=existing.revision,
        )

    assert existing.name == "Existing graph"
    assert updated.name == "Updated graph"
    assert updated.revision == 2


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
    graph_id = UUID("22222222-2222-4222-8222-222222222222")
    request_id = "33333333-3333-4333-8333-333333333333"

    def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.path == (
            f"/v1/workspaces/{WORKSPACE_ID}/graphs/{graph_id}/nodes/llm/secrets/api_key"
        )
        assert json.loads(request.content) == {
            "value": "sk-test-sensitive",
            "expected_graph_revision": 3,
        }
        return httpx.Response(
            422,
            headers={"X-Request-ID": request_id},
            json={"detail": "Provider rejected sk-test-sensitive"},
        )

    async with GrafyClient(
        base_url="https://grafy.test",
        token=SecretStr("nrt_live_secret"),
        transport=httpx.MockTransport(respond),
    ) as client:
        with pytest.raises(GrafyClientError) as caught:
            await client.graphs.configure_secret(
                WORKSPACE_ID,
                graph_id,
                node_id="llm",
                secret_name="api_key",
                value=SecretStr("sk-test-sensitive"),
                expected_revision=3,
            )

    error = caught.value
    assert error.operation == "configure graph node secret"
    assert error.status_code == 422
    assert error.request_id == request_id
    assert "<redacted>" in str(error)
    assert "sk-test-sensitive" not in str(error)
    assert "nrt_live_secret" not in str(error)
    assert "sk-test-sensitive" not in repr(error)


@pytest.mark.asyncio
async def test_saved_graph_execution_waits_for_typed_terminal_outputs() -> None:
    graph_id = UUID("22222222-2222-4222-8222-222222222222")
    execution_id = UUID("44444444-4444-4444-8444-444444444444")
    artifact_id = UUID("55555555-5555-4555-8555-555555555555")
    polls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal polls
        if request.method == "POST":
            assert request.url.path == (
                f"/v1/workspaces/{WORKSPACE_ID}/graphs/{graph_id}/executions"
            )
            assert request.headers["Idempotency-Key"] == "vision-e2e"
            assert json.loads(request.content) == {"expected_revision": 3}
            return httpx.Response(
                202,
                json={
                    "execution_id": str(execution_id),
                    "status": "queued",
                    "active_node_id": None,
                    "result": None,
                    "error": None,
                    "queue_position": 1,
                },
            )

        assert request.method == "GET"
        assert request.url.path == (
            f"/v1/workspaces/{WORKSPACE_ID}/executions/{execution_id}"
        )
        polls += 1
        if polls == 1:
            return httpx.Response(
                200,
                json={
                    "execution_id": str(execution_id),
                    "status": "running",
                    "active_node_id": "llm",
                    "result": None,
                    "error": None,
                    "queue_position": None,
                },
            )
        return httpx.Response(
            200,
            json={
                "execution_id": str(execution_id),
                "status": "succeeded",
                "active_node_id": None,
                "error": None,
                "queue_position": None,
                "result": {
                    "status": "succeeded",
                    "node_runs": [
                        {
                            "node_id": "llm",
                            "status": "succeeded",
                            "error": None,
                            "outputs": [
                                {
                                    "port": "completion",
                                    "kind": "single",
                                    "value": {
                                        "artifact_id": str(artifact_id),
                                        "artifact_type": "llm.completion",
                                        "schema_version": 1,
                                    },
                                    "artifacts": [
                                        {
                                            "artifact_id": str(artifact_id),
                                            "artifact_type": "llm.completion",
                                            "schema_version": 1,
                                            "content_type": "application/json",
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                },
            },
        )

    async with GrafyClient(
        base_url="https://grafy.test",
        token=SecretStr("nrt_live_secret"),
        transport=httpx.MockTransport(respond),
    ) as client:
        execution = await client.graphs.execute(
            WORKSPACE_ID,
            graph_id,
            expected_revision=3,
            idempotency_key="vision-e2e",
        )
        terminal = await execution.wait(timeout=1, poll_interval=0)

    assert terminal.status == "succeeded"
    assert terminal.result is not None
    assert [node.node_id for node in terminal.result.node_runs] == ["llm"]
    completion = terminal.result.node("llm").output("completion")
    assert completion.artifact_id == artifact_id
    assert completion.artifact_type == "llm.completion"


@pytest.mark.asyncio
async def test_execution_wait_reports_id_and_last_status_on_timeout() -> None:
    graph_id = UUID("22222222-2222-4222-8222-222222222222")
    execution_id = UUID("44444444-4444-4444-8444-444444444444")

    def respond(request: httpx.Request) -> httpx.Response:
        status_code = 202 if request.method == "POST" else 200
        return httpx.Response(
            status_code,
            json={
                "execution_id": str(execution_id),
                "status": "queued",
                "active_node_id": None,
                "result": None,
                "error": None,
                "queue_position": 1,
            },
        )

    async with GrafyClient(
        base_url="https://grafy.test",
        token=SecretStr("nrt_live_secret"),
        transport=httpx.MockTransport(respond),
    ) as client:
        execution = await client.graphs.execute(
            WORKSPACE_ID,
            graph_id,
            expected_revision=3,
        )
        with pytest.raises(ExecutionTimeoutError) as caught:
            await execution.wait(timeout=0.001, poll_interval=0.01)

    message = str(caught.value)
    assert str(execution_id) in message
    assert "last status was 'queued'" in message
