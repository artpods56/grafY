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

from grafy_persistence.database import create_database
from grafy_persistence.orm import metadata

from grafy_api.main import create_app
from tests.unit.api.conftest import WORKSPACE_ID, install_browser_actor_override
from grafy_api.v1.routes.catalog.models import NodeRegistryResponse
from grafy_api.v1.routes.executions.models import (
    RunExecutionCapacityErrorResponse,
    RunExecutionResponse,
    RunResponse,
)
from grafy_api.v1.routes.executions.dependencies import run_execution_manager
from grafy_api.v1.routes.executions.dependencies import execution_admission_limiter
from grafy_api.v1.routes.executions.runtime.admission import (
    ExecutionAdmissionLimiter,
    RunExecutionCapacityError,
)
from grafy_api.v1.routes.uploads.services import ImageUploadService
from grafy_api.settings import Settings
from grafy_core.artifacts import InMemoryUnitOfWork
from grafy_core.plugins import PluginOrigin


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


async def _prepare_database(database_url: str) -> None:
    database = create_database(database_url)
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
    finally:
        await database.dispose()


def test_application_lifespan_builds_and_releases_workbench_components(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'lifespan.sqlite3'}"
    asyncio.run(_prepare_database(database_url))
    application = create_app(
        Settings(
            workspace=tmp_path / "workbench",
            database_url=SecretStr(database_url),
            execution_backend="inline",
        )
    )
    install_browser_actor_override(application)
    assert not hasattr(application.state, "resources")
    assert hasattr(application.state, "identity")

    with TestClient(application) as client:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert hasattr(application.state, "resources")
        assert application.state.resources.plugin_registry.plugins

    assert not hasattr(application.state, "resources")


def test_node_registry_exposes_builtin_plugins_and_runtime_contracts(
    builtin_client: TestClient,
) -> None:
    response = builtin_client.get("/v1/workspaces/00000000-0000-0000-0000-000000000007/nodes")

    assert response.status_code == 200
    registry = NodeRegistryResponse.model_validate(response.json())
    assert [(plugin.slug, plugin.title) for plugin in registry.plugins] == [
        ("builtin.image", "Image"),
        ("builtin.module", "Module"),
        ("builtin.sequence", "Sequence"),
        ("builtin.arithmetic", "Arithmetic"),
        ("builtin.text", "Text"),
        ("builtin.schema", "Schema"),
        ("builtin.prompt", "Prompt"),
        ("builtin.table", "Table"),
        ("graph.module", "Workspace library"),
        ("generated.agent", "Agent-authored nodes"),
    ]
    assert {plugin.origin for plugin in registry.plugins} == {
        PluginOrigin.AGENT,
        PluginOrigin.BUILTIN,
        PluginOrigin.MODULE,
    }
    nodes = {node.operator_id: node for node in registry.nodes}
    assert set(nodes) == {
        "image.upload",
        "module.input",
        "module.output",
        "sequence.collect",
        "sequence.count",
        "sequence.item_at",
        "sequence.slice",
        "arithmetic.number",
        "arithmetic.integer_sequence",
        "arithmetic.add",
        "arithmetic.subtract",
        "arithmetic.multiply",
        "arithmetic.sum",
        "text.input",
        "text.as_markdown",
        "text.split",
        "text.replace",
        "text.join",
        "schema.builder",
        "prompt.message.create",
        "table.file.import",
        "table.text.normalize",
        "table.fuzzy_match",
    }
    assert {
        (artifact_type.key.id, artifact_type.key.schema_version)
        for artifact_type in registry.artifact_types
    } == {
        ("image.raster", 1),
        ("scalar.integer", 1),
        ("scalar.text", 1),
        ("text.markdown", 1),
        ("json.schema", 1),
        ("prompt.message", 2),
        ("table.data", 1),
    }
    assert [
        conversion.model_dump() for conversion in registry.artifact_conversions
    ] == [
        {
            "key": {
                "id": "builtin.scalar.integer_to_text",
                "version": 1,
            },
            "source_artifact_type": {
                "id": "scalar.integer",
                "schema_version": 1,
            },
            "target_artifact_type": {
                "id": "scalar.text",
                "schema_version": 1,
            },
            "title": "As text",
        }
    ]

    upload = nodes["image.upload"]
    assert upload.plugin_slug == "builtin.image"
    assert upload.title == "Upload images"
    assert upload.description == (
        "Imports staged image uploads as an ordered raster image sequence."
    )
    assert upload.outputs[0].name == "images"
    assert upload.outputs[0].artifact_type is not None
    assert upload.outputs[0].artifact_type.id == "image.raster"
    assert upload.outputs[0].shape == "many"
    assert upload.outputs[0].description == (
        "Ordered raster images imported from staged uploads."
    )

    text_input_properties = cast(
        dict[str, object],
        nodes["text.input"].config_schema["properties"],
    )
    assert text_input_properties["text"] == {
        "description": "Multiline text emitted by the node.",
        "format": "textarea",
        "title": "Text",
        "type": "string",
    }

    schema_builder = nodes["schema.builder"]
    assert schema_builder.plugin_slug == "builtin.schema"
    assert schema_builder.title == "Schema Builder"
    assert schema_builder.inputs[0].name == "schemas"
    assert schema_builder.inputs[0].artifact_type is not None
    assert schema_builder.inputs[0].artifact_type.id == "json.schema"
    assert schema_builder.inputs[0].accepted_shapes == ["one"]
    assert schema_builder.inputs[0].instance_plugs is True
    assert schema_builder.inputs[0].required is False
    assert schema_builder.outputs[0].artifact_type is not None
    assert schema_builder.outputs[0].artifact_type.id == "json.schema"
    assert schema_builder.outputs[0].name == "json_schema"
    assert schema_builder.outputs[0].title == "JSON Schema"

    schema_builder_properties = cast(
        dict[str, object],
        schema_builder.config_schema["properties"],
    )
    fields_schema = cast(dict[str, object], schema_builder_properties["fields"])
    assert fields_schema["type"] == "array"

    prompt_message = nodes["prompt.message.create"]
    prompt_message_definitions = cast(
        dict[str, object],
        prompt_message.config_schema["$defs"],
    )
    role_definition = cast(
        dict[str, object],
        prompt_message_definitions["PromptMessageRole"],
    )
    assert role_definition["enum"] == ["system", "user"]
    image_input = next(port for port in prompt_message.inputs if port.name == "images")
    assert image_input.artifact_type is not None
    assert image_input.artifact_type.id == "image.raster"
    assert image_input.shape == "many"
    assert image_input.required is False

    add = nodes["arithmetic.add"]
    assert add.inputs[0].title == "Left"
    assert add.inputs[0].description == "Left-hand integer operand."

    collect = nodes["sequence.collect"]
    assert collect.inputs[0].name == "items"
    assert collect.inputs[0].shape == "one"
    assert collect.inputs[0].accepted_shapes == ["one", "many"]
    assert collect.inputs[0].instance_plugs is True
    assert collect.outputs[0].accepted_shapes == ["many"]
    assert collect.outputs[0].instance_plugs is False
    assert collect.inputs[0].artifact_type is None
    assert collect.inputs[0].artifact_type_variable == "T"
    assert collect.outputs[0].artifact_type is None
    assert collect.outputs[0].artifact_type_variable == "T"


def test_run_accepts_empty_graph(builtin_client: TestClient) -> None:
    response = builtin_client.post("/v1/workspaces/00000000-0000-0000-0000-000000000007/runs", json={"nodes": [], "edges": []})

    assert response.status_code == 200
    result = RunResponse.model_validate(response.json())
    assert result.status == "succeeded"
    assert result.node_runs == []


def test_synchronous_run_shares_typed_execution_capacity_contract(
    builtin_client: TestClient,
) -> None:
    application = cast(FastAPI, builtin_client.app)
    admission_limiter = ExecutionAdmissionLimiter(1)
    occupied_lease = admission_limiter.acquire()
    original_override = application.dependency_overrides[
        execution_admission_limiter
    ]
    application.dependency_overrides[execution_admission_limiter] = (
        lambda: admission_limiter
    )
    try:
        response = builtin_client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
            json={"nodes": [], "edges": []},
        )
    finally:
        occupied_lease.release()
        application.dependency_overrides[
            execution_admission_limiter
        ] = original_override

    error = RunExecutionCapacityErrorResponse.model_validate(response.json())
    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"
    assert error.detail.error_code == "execution_capacity_exceeded"
    assert error.detail.max_active_executions == 1


def test_async_execution_routes_return_pollable_typed_state(
    builtin_client: TestClient,
) -> None:
    start_response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/executions",
        json={"nodes": [], "edges": []},
    )

    assert start_response.status_code == 202
    started = RunExecutionResponse.model_validate(start_response.json())
    assert started.status == "queued"
    assert started.active_node_id is None
    assert started.result is None
    assert started.error is None

    polled = started
    for _ in range(20):
        response = builtin_client.get(f"/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/{started.execution_id}")
        assert response.status_code == 200
        polled = RunExecutionResponse.model_validate(response.json())
        if polled.status == "succeeded":
            break
    assert polled.status == "succeeded"
    assert polled.result is not None
    assert polled.result.status == "succeeded"

    cancel_response = builtin_client.delete(f"/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/{started.execution_id}")
    assert cancel_response.status_code == 200
    assert RunExecutionResponse.model_validate(cancel_response.json()).status == (
        "succeeded"
    )

    missing_id = uuid4()
    assert builtin_client.get(f"/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/{missing_id}").status_code == 404
    assert builtin_client.delete(f"/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/{missing_id}").status_code == 404


def test_async_execution_route_returns_typed_capacity_error(
    builtin_client: TestClient,
) -> None:
    rejecting_manager = AsyncMock()
    rejecting_manager.start.side_effect = RunExecutionCapacityError(2)
    application = cast(FastAPI, builtin_client.app)
    original_override = application.dependency_overrides[
        run_execution_manager
    ]
    application.dependency_overrides[run_execution_manager] = (
        lambda: rejecting_manager
    )
    try:
        response = builtin_client.post(
            "/v1/workspaces/00000000-0000-0000-0000-000000000007/executions",
            json={"nodes": [], "edges": []},
        )
    finally:
        application.dependency_overrides[run_execution_manager] = original_override

    error = RunExecutionCapacityErrorResponse.model_validate(response.json())
    assert response.status_code == 429
    assert response.headers["retry-after"] == "1"
    assert error.detail.error_code == "execution_capacity_exceeded"
    assert error.detail.max_active_executions == 2
    assert "2 active executions" in error.detail.message


def test_execution_event_stream_replays_ids_and_closes_after_terminal(
    builtin_client: TestClient,
) -> None:
    started = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/executions",
        json={"nodes": [], "edges": []},
    ).json()
    execution_id = started["execution_id"]

    response = builtin_client.get(f"/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/{execution_id}/events")
    events = _parse_sse_events(response.text)
    replay_response = builtin_client.get(
        f"/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/{execution_id}/events",
        headers={"Last-Event-ID": "1"},
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
    assert all(event["execution_id"] == execution_id for event in events)
    assert [event["sequence"] for event in replayed] == [2, 3]


def test_execution_event_stream_validates_replay_and_missing_execution_ids(
    builtin_client: TestClient,
) -> None:
    started = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/executions",
        json={"nodes": [], "edges": []},
    ).json()
    execution_id = started["execution_id"]
    missing_id = uuid4()

    invalid_replay = builtin_client.get(
        f"/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/{execution_id}/events",
        headers={"Last-Event-ID": "not-a-sequence"},
    )
    oversized_replay = builtin_client.get(
        f"/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/{execution_id}/events",
        headers={"Last-Event-ID": "9" * 5_000},
    )
    missing = builtin_client.get(f"/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/{missing_id}/events")
    malformed = builtin_client.get("/v1/workspaces/00000000-0000-0000-0000-000000000007/executions/not-a-uuid/events")

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


@pytest.mark.asyncio
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
    response = builtin_client.post(
        f"/v1/workspaces/{WORKSPACE_ID}/uploads",
        files={
            "file": (
                "historical-map.tif",
                b"geotiff-bytes",
                "image/tiff",
            )
        },
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
    sample_response = builtin_client.post("/v1/workspaces/00000000-0000-0000-0000-000000000007/samples", json={"count": 2})
    assert sample_response.status_code == 200
    uploads = sample_response.json()

    run_response = builtin_client.post(
        "/v1/workspaces/00000000-0000-0000-0000-000000000007/runs",
        json={
            "nodes": [
                {
                    "id": "upload",
                    "operator_id": "image.upload",
                    "operator_version": 1,
                    "config": {"uploads": uploads},
                },
            ],
            "edges": [],
        },
    )

    assert run_response.status_code == 200
    result = RunResponse.model_validate(run_response.json())
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
