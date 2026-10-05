"""Application-level error handlers, registered by ``create_app`` and proven on real routes.

Every test here drives an actual route through the client built by ``create_app``, because
registration is the thing that used to live in the route. Each response body is asserted in full
rather than by status alone, since the handlers exist to keep answering the way the deleted route
clauses did. The one value no test pins is the random ``error_id``.
"""

import asyncio
import logging
from collections.abc import Mapping
from typing import cast
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

from grafy_api.app_state import get_resources
from grafy_api.execution.admission import (
    ExecutionAdmissionLimiter,
    RunExecutionCapacityError,
    RunExecutionQueueFullError,
)
from grafy_api.execution.manager import RunExecutionIdempotencyConflictError
from grafy_api.execution.requests import RunRequest
from grafy_api.node_secrets import (
    NodeSecretConfigurationError,
    NodeSecretDeclarationError,
    NodeSecretValueError,
)
from grafy_api.services.composition import WorkbenchComponents
from grafy_api.services.errors import (
    ArtifactContentUnavailableError,
    WorkbenchOperationError,
)
from grafy_api.uploads import UploadTooLargeError
from grafy_api.v1.routes.artifacts import services as artifact_services
from grafy_api.v1.routes.executions.dependencies import (
    execution_admission_limiter,
    run_execution_manager,
)
from grafy_core.artifacts import ArtifactObject, ArtifactRef
from grafy_core.domain.errors import GrafyCoreError
from grafy_core.nodes import NodeExecutionContext
from grafy_core.runtime.materialization import MaterializationProvenance
from grafy_core.runtime.persistence import ArtifactWriteContext
from grafy_core.table_contracts import Table, TableColumn, TableValueType
from grafy_workbench.table.persistence import TableArtifactWriter

from tests.support.clients import GrafyApi
from tests.support.identity import WORKSPACE_ID

# Errors whose handler lives in the HTTP boundary. Each one answers the same way on every route
# that can raise it.
HANDLED_ERRORS = (
    UploadTooLargeError,
    ArtifactContentUnavailableError,
    NodeSecretValueError,
    RunExecutionCapacityError,
    RunExecutionQueueFullError,
    RunExecutionIdempotencyConflictError,
)

# Errors with no handler on purpose: a table artifact route shows they still surface as internal
# failures. NodeSecretDeclarationError and NodeSecretConfigurationError also surface while an inline
# run resolves a secret binding, where that internal failure is today's answer; WorkbenchOperationError
# answers 400 in some route modules and 422 in others.
UNHANDLED_ERRORS = (
    ValueError("table page cursor is not valid"),
    RuntimeError("object storage driver exploded"),
    NodeSecretDeclarationError("Node llm does not declare secret admin_token"),
    NodeSecretConfigurationError(
        "GRAFY_CREDENTIAL_ENCRYPTION_KEY is required for node secret operations"
    ),
    WorkbenchOperationError("workbench operation is not supported"),
)


def _table(name: str) -> Table:
    return Table(
        columns=[
            TableColumn(id="value", title="Value", value_type=TableValueType.TEXT)
        ],
        rows=[{"value": name}],
    )


def _event_records(
    caplog: pytest.LogCaptureFixture,
    event: str,
) -> list[Mapping[str, object]]:
    records: list[Mapping[str, object]] = []
    for record in caplog.records:
        raw_message = cast(object, record.msg)
        if not isinstance(raw_message, Mapping):
            continue
        message = cast(Mapping[str, object], raw_message)
        if message.get("event") == event:
            records.append(message)
    return records


def _stored_table_artifact(
    writer: TableArtifactWriter,
    node_id: str,
) -> ArtifactRef:
    return asyncio.run(
        writer.write(
            _table("stored"),
            ArtifactWriteContext(
                node_context=NodeExecutionContext(
                    workspace_id=WORKSPACE_ID,
                    node_id=node_id,
                ),
                provenance=MaterializationProvenance(refs_by_input={}),
            ),
        )
    )


def _rejecting_manager(error: Exception) -> AsyncMock:
    manager = AsyncMock()
    manager.start.side_effect = error
    return manager


def test_create_app_registers_dedicated_and_shared_error_handlers(
    builtin_client: TestClient,
) -> None:
    handlers = cast(FastAPI, builtin_client.app).exception_handlers

    for error in HANDLED_ERRORS:
        assert error in handlers, error.__name__
    for error in (HTTPException, RequestValidationError, GrafyCoreError):
        assert error in handlers, error.__name__


def test_synchronous_run_capacity_response_keeps_its_declared_body_and_header(
    builtin_client: TestClient,
) -> None:
    application = cast(FastAPI, builtin_client.app)
    executions = GrafyApi(builtin_client).workspace(WORKSPACE_ID).executions
    limiter = ExecutionAdmissionLimiter(1)
    occupied_lease = limiter.acquire()
    original_override = application.dependency_overrides[execution_admission_limiter]
    application.dependency_overrides[execution_admission_limiter] = lambda: limiter
    try:
        response = executions.run(RunRequest(nodes=[]))
    finally:
        occupied_lease.release()
        application.dependency_overrides[execution_admission_limiter] = (
            original_override
        )

    assert response.status_code == 429
    assert response.json() == {
        "detail": {
            "error_code": "execution_capacity_exceeded",
            "message": (
                "Run execution capacity is exhausted; "
                "the process already owns 1 active executions"
            ),
            "max_active_executions": 1,
        }
    }
    assert response.headers["retry-after"] == "1"
    _ = UUID(response.headers["x-request-id"])


def test_async_run_capacity_response_keeps_its_declared_body_and_header(
    builtin_client: TestClient,
) -> None:
    application = cast(FastAPI, builtin_client.app)
    executions = GrafyApi(builtin_client).workspace(WORKSPACE_ID).executions
    original_override = application.dependency_overrides[run_execution_manager]
    application.dependency_overrides[run_execution_manager] = lambda: (
        _rejecting_manager(RunExecutionCapacityError(2))
    )
    try:
        response = executions.start_execution(RunRequest(nodes=[]))
    finally:
        application.dependency_overrides[run_execution_manager] = original_override

    assert response.status_code == 429
    assert response.json() == {
        "detail": {
            "error_code": "execution_capacity_exceeded",
            "message": (
                "Run execution capacity is exhausted; "
                "the process already owns 2 active executions"
            ),
            "max_active_executions": 2,
        }
    }
    assert response.headers["retry-after"] == "1"


def test_queue_full_response_keeps_its_declared_body_and_header(
    builtin_client: TestClient,
) -> None:
    application = cast(FastAPI, builtin_client.app)
    executions = GrafyApi(builtin_client).workspace(WORKSPACE_ID).executions
    original_override = application.dependency_overrides[run_execution_manager]
    application.dependency_overrides[run_execution_manager] = lambda: (
        _rejecting_manager(RunExecutionQueueFullError(20))
    )
    try:
        response = executions.start_execution(RunRequest(nodes=[]))
    finally:
        application.dependency_overrides[run_execution_manager] = original_override

    assert response.status_code == 429
    assert response.json() == {
        "detail": {
            "error_code": "execution_queue_full",
            "message": (
                "Run execution queue is full; "
                "the process already owns 20 pending executions"
            ),
            "max_pending_graphs": 20,
        }
    }
    assert response.headers["retry-after"] == "1"


def test_idempotency_conflict_response_keeps_its_declared_body(
    builtin_client: TestClient,
) -> None:
    application = cast(FastAPI, builtin_client.app)
    executions = GrafyApi(builtin_client).workspace(WORKSPACE_ID).executions
    existing_execution_id = uuid4()
    original_override = application.dependency_overrides[run_execution_manager]
    application.dependency_overrides[run_execution_manager] = lambda: (
        _rejecting_manager(
            RunExecutionIdempotencyConflictError("api-retry-1", existing_execution_id)
        )
    )
    try:
        response = executions.start_execution(
            RunRequest(nodes=[]),
            headers={"Idempotency-Key": "api-retry-1"},
        )
    finally:
        application.dependency_overrides[run_execution_manager] = original_override

    assert response.status_code == 409
    assert response.json() == {
        "detail": {
            "error_code": "execution_idempotency_conflict",
            "message": (
                "Idempotency key 'api-retry-1' already belongs to execution "
                f"{existing_execution_id} with a different submitted request"
            ),
            "idempotency_key": "api-retry-1",
            "execution_id": str(existing_execution_id),
        }
    }


def test_oversized_content_length_response_keeps_its_plain_detail(
    builtin_client: TestClient,
) -> None:
    max_bytes = get_resources(
        cast(FastAPI, builtin_client.app)
    ).workbench.upload_config.max_upload_bytes
    upload_id = uuid4()

    # A chunked body keeps the test client from recomputing Content-Length, the header the route
    # validator reads before any bytes are stored.
    response = builtin_client.put(
        f"/v1/workspaces/{WORKSPACE_ID}/uploads/{upload_id}/content",
        content=iter([b"tiny"]),
        headers={"Content-Length": str(max_bytes + 1)},
    )

    assert response.status_code == 413
    assert response.json() == {
        "detail": f"Upload exceeds the upload limit of {max_bytes} bytes"
    }


def test_unavailable_artifact_content_keeps_the_internal_envelope(
    table_artifact_client: tuple[
        TestClient,
        TableArtifactWriter,
        WorkbenchComponents,
    ],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    client, writer, _ = table_artifact_client
    artifact = _stored_table_artifact(writer, "content-unavailable")

    async def offline(self: object, stored: ArtifactObject) -> None:
        raise ArtifactContentUnavailableError(f"Artifact {stored.id} bytes are offline")

    monkeypatch.setattr(artifact_services.ArtifactService, "open_content", offline)

    response = (
        GrafyApi(client).workspace(WORKSPACE_ID).artifacts.content(artifact.artifact_id)
    )

    assert response.status_code == 500
    body = response.json()
    assert body == {
        "detail": "An internal error occurred",
        "code": "internal.unexpected_error",
        "error_id": body["error_id"],
    }
    assert "offline" not in response.text
    _ = UUID(body["error_id"])
    request_id = response.headers["x-request-id"]
    _ = UUID(request_id)

    # The failure log names the artifact error itself: a mapped 500 is a rejected request, not an
    # unhandled error, and nothing wraps the original exception on the way out.
    failures = _event_records(caplog, "operation_failed")
    failure = next(event for event in failures if event.get("request_id") == request_id)
    assert failure["operation"] == "http.request.reject"
    assert failure["failure_code"] == "internal.unexpected_error"
    exception = cast(Mapping[str, object], failure["exception"])
    assert (
        exception["type"] == "grafy_api.services.errors.ArtifactContentUnavailableError"
    )


@pytest.mark.parametrize(
    "error", UNHANDLED_ERRORS, ids=lambda error: type(error).__name__
)
def test_unmapped_errors_on_a_converted_route_stay_internal_failures(
    table_artifact_client: tuple[
        TestClient,
        TableArtifactWriter,
        WorkbenchComponents,
    ],
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    client, writer, _ = table_artifact_client
    artifact = _stored_table_artifact(writer, "unmapped-error")

    async def fail(self: object, stored: ArtifactObject) -> None:
        raise error

    monkeypatch.setattr(artifact_services.ArtifactService, "open_content", fail)

    response = (
        GrafyApi(client).workspace(WORKSPACE_ID).artifacts.content(artifact.artifact_id)
    )

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "An internal error occurred"
    assert body["code"] == "internal.unexpected_error"
    assert type(error).__name__ not in response.text
    _ = UUID(response.headers["x-request-id"])
