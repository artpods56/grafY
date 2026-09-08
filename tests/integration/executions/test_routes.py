import asyncio
from io import BytesIO
import json
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.support.identity import WORKSPACE_ID, browser_actor_override
from grafy_workbench import BUILTIN_FAMILIES
from grafy_api.v1.routes.auth.dependencies import browser_actor, workspace_actor
from grafy_api.v1.routes.catalog.models import NodeRegistryResponse
from grafy_api.v1.routes.executions.models import (
    RunExecutionCapacityErrorResponse,
    RunExecutionIdempotencyConflictErrorResponse,
    RunExecutionQueueFullErrorResponse,
)
from grafy_api.execution.requests import RunRequest
from grafy_core.canonical_conversions import CANONICAL_ARTIFACT_CONVERSIONS
from tests.support.system_plugins import (
    TEST_SYSTEM_PLUGINS,
    selected_system_run_node as RunNodeRequest,
)
from tests.support.clients import GrafyApi
from grafy_api.v1.routes.executions.dependencies import run_execution_manager
from grafy_api.v1.routes.executions.dependencies import execution_admission_limiter
from grafy_api.execution.admission import (
    ExecutionAdmissionLimiter,
    RunExecutionCapacityError,
    RunExecutionQueueFullError,
)
from grafy_api.execution.manager import RunExecutionIdempotencyConflictError
from grafy_api.v1.routes.uploads.models import SampleRequest
from grafy_api.v1.routes.uploads.services import ImageUploadService
from grafy_api.settings import Settings
from grafy_core.artifacts import InMemoryUnitOfWork

from tests.testkit import app_with_overrides, create_db_url, db


def _parse_sse_events(body: str) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for frame in body.split("\n\n"):
        fields: dict[str, str] = {}
        for line in frame.splitlines():
            if ": " not in line:
                continue
            name, value = line.split(": ", 1)
            fields[name] = value
        if "data" not in fields:
            continue
        data = cast(dict[str, object], json.loads(fields["data"]))
        assert fields["id"] == str(data["sequence"])
        assert fields["event"] == data["kind"]
        events.append(data)
    return events


def test_application_lifespan_builds_and_releases_workbench_components(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("GRAFY_SYSTEM_PLUGIN_DEPLOYMENT_MANIFEST", raising=False)
    database_url = create_db_url(tmp_path, "lifespan.sqlite3")

    async def prepare_schema() -> None:
        async with db(database_url):
            pass

    asyncio.run(prepare_schema())
    application = app_with_overrides(
        settings=Settings(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            workspace=tmp_path / "workbench",
            database_url=SecretStr(database_url),
        ),
        overrides={
            browser_actor: browser_actor_override,
            workspace_actor: browser_actor_override,
        },
    )
    assert not hasattr(application.state, "resources")
    assert hasattr(application.state, "identity")

    with TestClient(application) as client:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert hasattr(application.state, "resources")
        registry = application.state.resources.plugin_registry
        assert {plugin.slug for plugin in registry.plugins} == {
            plugin.slug for plugin in BUILTIN_FAMILIES
        }
        assert {node.key for node in registry.nodes} == {
            ("module.input", 1),
            ("module.output", 1),
            *(
                registration.key
                for plugin in BUILTIN_FAMILIES
                for registration in plugin.nodes
            ),
        }

    assert not hasattr(application.state, "resources")


def test_node_registry_does_not_synthesize_plugins_from_runtime_registry(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.get(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/nodes"
    )

    assert response.status_code == 200
    registry = NodeRegistryResponse.model_validate(response.json())
    assert {(plugin.slug, plugin.title) for plugin in registry.plugins} == {
        ("graph.module", "Workspace library"),
        *((plugin.slug, plugin.title) for plugin in TEST_SYSTEM_PLUGINS),
    }
    assert {node.operator_id for node in registry.nodes} == {
        "module.input",
        "module.output",
        *(
            registration.key[0]
            for plugin in TEST_SYSTEM_PLUGINS
            for registration in plugin.nodes
        ),
    }
    assert {spec.key.id for spec in registry.artifact_types} == {
        spec.key.id
        for plugin in TEST_SYSTEM_PLUGINS
        for spec in plugin.artifact_types
    }
    assert {spec.key.id for spec in registry.artifact_conversions} == {
        conversion.key.id for conversion in CANONICAL_ARTIFACT_CONVERSIONS
    }


def test_run_accepts_empty_graph(builtin_client: TestClient) -> None:
    api = GrafyApi(builtin_client)
    executions = api.workspace(WORKSPACE_ID).executions

    result = executions.run_ok(RunRequest(nodes=[]))

    assert result.status == "succeeded"
    assert result.node_runs == []


def test_synchronous_run_shares_typed_execution_capacity_contract(
    builtin_client: TestClient,
) -> None:
    application = cast(FastAPI, builtin_client.app)
    api = GrafyApi(builtin_client)
    executions = api.workspace(WORKSPACE_ID).executions
    admission_limiter = ExecutionAdmissionLimiter(1)
    occupied_lease = admission_limiter.acquire()
    original_override = application.dependency_overrides[execution_admission_limiter]
    application.dependency_overrides[execution_admission_limiter] = (
        lambda: admission_limiter
    )
    try:
        response = executions.run(RunRequest(nodes=[]))
    finally:
        occupied_lease.release()
        application.dependency_overrides[execution_admission_limiter] = (
            original_override
        )

    error = RunExecutionCapacityErrorResponse.model_validate(response.json())
    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"
    assert error.detail.error_code == "execution_capacity_exceeded"
    assert error.detail.max_active_executions == 1


def test_async_execution_routes_return_pollable_typed_state(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    executions = api.workspace(WORKSPACE_ID).executions

    started = executions.start_execution_ok(RunRequest(nodes=[]))

    assert started.status == "queued"
    assert started.active_node_id is None
    assert started.result is None
    assert started.error is None

    polled = started
    for _ in range(20):
        polled = executions.get_execution_ok(started.execution_id)
        if polled.status == "succeeded":
            break
    assert polled.status == "succeeded"
    assert polled.result is not None
    assert polled.result.status == "succeeded"

    cancelled = executions.cancel_execution_ok(started.execution_id)
    assert cancelled.status == "succeeded"

    missing_id = uuid4()
    assert executions.get_execution(missing_id).status_code == 404
    assert executions.cancel_execution(missing_id).status_code == 404


def test_async_execution_route_returns_typed_capacity_error(
    builtin_client: TestClient,
) -> None:
    rejecting_manager = AsyncMock()
    rejecting_manager.start.side_effect = RunExecutionCapacityError(2)
    application = cast(FastAPI, builtin_client.app)
    api = GrafyApi(builtin_client)
    executions = api.workspace(WORKSPACE_ID).executions
    original_override = application.dependency_overrides[run_execution_manager]
    application.dependency_overrides[run_execution_manager] = lambda: rejecting_manager
    try:
        response = executions.start_execution(RunRequest(nodes=[]))
    finally:
        application.dependency_overrides[run_execution_manager] = original_override

    error = RunExecutionCapacityErrorResponse.model_validate(response.json())
    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"
    assert error.detail.error_code == "execution_capacity_exceeded"
    assert error.detail.max_active_executions == 2
    assert "2 active executions" in error.detail.message


def test_async_execution_route_returns_typed_queue_full_error(
    builtin_client: TestClient,
) -> None:
    rejecting_manager = AsyncMock()
    rejecting_manager.start.side_effect = RunExecutionQueueFullError(20)
    application = cast(FastAPI, builtin_client.app)
    api = GrafyApi(builtin_client)
    executions = api.workspace(WORKSPACE_ID).executions
    original_override = application.dependency_overrides[run_execution_manager]
    application.dependency_overrides[run_execution_manager] = lambda: rejecting_manager
    try:
        response = executions.start_execution(RunRequest(nodes=[]))
    finally:
        application.dependency_overrides[run_execution_manager] = original_override

    error = RunExecutionQueueFullErrorResponse.model_validate(response.json())
    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"
    assert error.detail.error_code == "execution_queue_full"
    assert error.detail.max_pending_graphs == 20
    assert "20 pending executions" in error.detail.message


def test_async_execution_route_returns_idempotency_conflict(
    builtin_client: TestClient,
) -> None:
    existing_execution_id = uuid4()
    rejecting_manager = AsyncMock()
    rejecting_manager.start.side_effect = RunExecutionIdempotencyConflictError(
        "api-retry-1",
        existing_execution_id,
    )
    application = cast(FastAPI, builtin_client.app)
    api = GrafyApi(builtin_client)
    executions = api.workspace(WORKSPACE_ID).executions
    original_override = application.dependency_overrides[run_execution_manager]
    application.dependency_overrides[run_execution_manager] = lambda: rejecting_manager
    try:
        response = executions.start_execution(
            RunRequest(nodes=[]),
            headers={"Idempotency-Key": "api-retry-1"},
        )
    finally:
        application.dependency_overrides[run_execution_manager] = original_override

    error = RunExecutionIdempotencyConflictErrorResponse.model_validate(response.json())
    assert response.status_code == 409
    assert error.detail.error_code == "execution_idempotency_conflict"
    assert error.detail.idempotency_key == "api-retry-1"
    assert error.detail.execution_id == existing_execution_id
    rejecting_manager.start.assert_awaited_once()
    assert rejecting_manager.start.await_args.kwargs["idempotency_key"] == "api-retry-1"


def test_execution_event_stream_replays_ids_and_closes_after_terminal(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    executions = api.workspace(WORKSPACE_ID).executions
    started = executions.start_execution_ok(RunRequest(nodes=[]))
    execution_id = started.execution_id

    response = executions.stream_execution_events(execution_id)
    events = _parse_sse_events(response.text)
    replay_response = executions.stream_execution_events(
        execution_id, headers={"Last-Event-ID": "1"}
    )
    replayed = _parse_sse_events(replay_response.text)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    assert [event["sequence"] for event in events] == [1, 2, 3]
    assert [event["status"] for event in events] == [
        "queued",
        "running",
        "succeeded",
    ]
    assert all(event["execution_id"] == str(execution_id) for event in events)
    assert [event["sequence"] for event in replayed] == [2, 3]


def test_execution_event_stream_validates_replay_and_missing_execution_ids(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    executions = api.workspace(WORKSPACE_ID).executions
    started = executions.start_execution_ok(RunRequest(nodes=[]))
    execution_id = started.execution_id
    missing_id = uuid4()

    invalid_replay = executions.stream_execution_events(
        execution_id, headers={"Last-Event-ID": "not-a-sequence"}
    )
    oversized_replay = executions.stream_execution_events(
        execution_id, headers={"Last-Event-ID": "9" * 5_000}
    )
    missing = executions.stream_execution_events(missing_id)
    # A non-UUID execution id cannot be expressed by the typed client;
    # exercise that boundary through the raw client.
    malformed = builtin_client.get(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/not-a-uuid/events"
    )

    assert invalid_replay.status_code == 422
    assert invalid_replay.json()["detail"] == (
        "Last-Event-ID must be a non-negative integer"
    )
    assert oversized_replay.status_code == 422
    assert oversized_replay.json()["detail"] == (
        "Last-Event-ID exceeds the supported sequence range"
    )
    assert missing.status_code == 404
    assert malformed.status_code == 422


def test_execution_request_rejects_oversized_node_ids(
    builtin_client: TestClient,
) -> None:
    # A node id beyond the 255-character bound is rejected by the request
    # model itself, so it cannot be expressed client-side; raw body.
    response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/executions",
        json={
            "nodes": [
                {
                    "id": "x" * 256,
                    "operator_id": "text.input",
                    "operator_version": 1,
                    "config": {"value": "hello"},
                }
            ]
        },
    )

    assert response.status_code == 422


async def test_upload_from_relative_workspace_returns_opaque_upload_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    unit_of_work = InMemoryUnitOfWork()
    service = ImageUploadService(
        Path("relative-workbench/uploads"),
        unit_of_work_factory=lambda: unit_of_work,
    )
    workspace_id = UUID("00000000-0000-0000-0000-000000000007")
    user_id = UUID("00000000-0000-0000-0000-000000000001")

    item = await service.save_upload(
        workspace_id=workspace_id,
        created_by_user_id=user_id,
        filename="page.png",
        stream=BytesIO(b"image-bytes"),
    )

    assert "/" not in item.upload_key
    assert "\\" not in item.upload_key
    assert item.upload_key.endswith("-page.png")
    assert item.filename == "page.png"
    assert item.byte_size == len(b"image-bytes")
    staged_path = (
        Path("relative-workbench/uploads") / str(workspace_id) / item.upload_key
    )
    assert staged_path.is_file()
    assert staged_path.read_bytes() == b"image-bytes"
    async with unit_of_work as entered:
        stored = await entered.staged_uploads.get(workspace_id, item.upload_key)
    assert stored is not None
    assert stored.original_filename == "page.png"
    assert stored.created_by_user_id == user_id


def test_upload_endpoint_streams_an_opaque_file(
    builtin_client: TestClient,
    tmp_path: Path,
) -> None:
    api = GrafyApi(builtin_client)
    response = api.workspace(WORKSPACE_ID).uploads.upload(
        "historical-map.tif",
        b"geotiff-bytes",
        content_type="image/tiff",
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["filename"] == "historical-map.tif"
    assert payload["byte_size"] == len(b"geotiff-bytes")
    assert payload["upload_key"].endswith("-historical-map.tif")
    staged_path = (
        tmp_path / "workbench" / "uploads" / str(WORKSPACE_ID) / payload["upload_key"]
    )
    assert staged_path.is_file()
    assert staged_path.read_bytes() == b"geotiff-bytes"


def test_image_upload_materializes_sample_images(
    builtin_client: TestClient,
) -> None:
    api = GrafyApi(builtin_client)
    sample_response = api.workspace(WORKSPACE_ID).uploads.create_samples(
        SampleRequest(count=2)
    )
    assert sample_response.status_code == 200
    uploads = sample_response.json()

    executions = api.workspace(WORKSPACE_ID).executions
    result = executions.run_ok(
        RunRequest(
            nodes=[
                RunNodeRequest(
                    kind="builtin",
                    id="upload",
                    operator_id="image.upload",
                    operator_version=1,
                    config={"uploads": uploads},
                ),
            ],
            edges=[],
        )
    )

    assert result.status == "succeeded"
    upload_run = result.node_runs[0]
    assert upload_run.status == "succeeded"
    assert upload_run.outputs[0].port == "images"
    assert len(upload_run.outputs[0].artifacts) == 2

    content_response = builtin_client.get(
        f"/v1/workspaces/00000000-0000-0000-0000-000000000007/artifacts/{upload_run.outputs[0].artifacts[0].artifact_id}/content"
    )
    assert content_response.status_code == 200
    assert content_response.headers["content-type"] == "image/png"
    assert content_response.content.startswith(b"\x89PNG")
