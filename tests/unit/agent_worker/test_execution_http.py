import asyncio
from hashlib import sha256
import hmac
from time import time
from uuid import UUID

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient, Headers
import pytest

from grafy_agent.errors import AgentRuntimeError
from grafy_core.domain.agent_authoring import (
    AgentArtifactType,
    AgentPortDirection,
    CapabilityManifest,
    GeneratedNodeManifest,
    GeneratedNodePort,
    RuntimeArtifactReference,
)
from grafy_core.nodes import PortShape
from grafy_core.ports.generated_execution import (
    GENERATED_EXECUTION_REQUEST_ID_HEADER,
    GENERATED_EXECUTION_SIGNATURE_HEADER,
    GENERATED_EXECUTION_TIMESTAMP_HEADER,
    GeneratedNodeExecutionFailure,
    GeneratedNodeExecutionRequest,
    GeneratedNodeExecutionResult,
    generated_execution_signature_payload,
)
from grafy_core.source_bundles import GeneratedNodeBuildDocument

from grafy_agent_worker.http import (
    ExecutionRequestAuthenticator,
    create_execution_app,
)


SECRET = b"test-generated-execution-secret-32-bytes-minimum"
REQUEST_ID = UUID("30000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("30000000-0000-0000-0000-000000000002")
NODE_ID = UUID("30000000-0000-0000-0000-000000000003")


class SuccessfulExecutor:
    async def execute(
        self,
        request: GeneratedNodeExecutionRequest,
        /,
    ) -> GeneratedNodeExecutionResult:
        return GeneratedNodeExecutionResult(
            request_id=request.request_id,
            outputs={"result": [3, 6]},
            execution_digest="9" * 64,
            duration_ms=4,
        )


class FailingExecutor:
    async def execute(
        self,
        request: GeneratedNodeExecutionRequest,
        /,
    ) -> GeneratedNodeExecutionResult:
        del request
        raise AgentRuntimeError("node behavior was rejected")


class BlockingExecutor:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.call_count = 0

    async def execute(
        self,
        request: GeneratedNodeExecutionRequest,
        /,
    ) -> GeneratedNodeExecutionResult:
        self.call_count += 1
        self.started.set()
        await self.release.wait()
        return GeneratedNodeExecutionResult(
            request_id=request.request_id,
            outputs={"result": [3, 6]},
            execution_digest="9" * 64,
            duration_ms=4,
        )


def execution_request(
    request_id: UUID = REQUEST_ID,
) -> GeneratedNodeExecutionRequest:
    manifest = GeneratedNodeManifest(
        title="Triple",
        description="Triple integers.",
        inputs=(
            GeneratedNodePort(
                direction=AgentPortDirection.INPUT,
                name="values",
                artifact_type=AgentArtifactType(
                    id="scalar.integer",
                    schema_version=1,
                ),
                shape=PortShape.MANY,
            ),
        ),
    )
    artifact = RuntimeArtifactReference(
        provider="memory",
        ref="artifact-1",
        digest="7" * 64,
    )
    document = GeneratedNodeBuildDocument(
        source_digest="0" * 64,
        lock_digest="1" * 64,
        tests_digest="2" * 64,
        implementation_digest="3" * 64,
        manifest=manifest,
        capabilities=CapabilityManifest(),
        runtime_image_digest="4" * 64,
        profile_digest="5" * 64,
        runtime_artifact=artifact,
    )
    return GeneratedNodeExecutionRequest(
        request_id=request_id,
        workspace_id=WORKSPACE_ID,
        node_id=NODE_ID,
        revision=1,
        build_digest=document.digest,
        build_document=document,
        inputs={"values": [1, 2]},
    )


def signed_headers(
    request: GeneratedNodeExecutionRequest,
    *,
    timestamp: int | None = None,
) -> dict[str, str]:
    body = request.canonical_json_bytes()
    signed_at = timestamp if timestamp is not None else int(time())
    payload = generated_execution_signature_payload(
        direction="request",
        timestamp=signed_at,
        request_id=request.request_id,
        body=body,
    )
    return {
        GENERATED_EXECUTION_TIMESTAMP_HEADER: str(signed_at),
        GENERATED_EXECUTION_REQUEST_ID_HEADER: str(request.request_id),
        GENERATED_EXECUTION_SIGNATURE_HEADER: hmac.new(
            SECRET,
            payload,
            sha256,
        ).hexdigest(),
        "content-type": "application/json",
    }


def app_client(executor: SuccessfulExecutor | FailingExecutor) -> TestClient:
    return TestClient(
        create_execution_app(
            executor=executor,
            authenticator=ExecutionRequestAuthenticator(
                SECRET,
                skew_seconds=30,
                replay_cache_entries=128,
            ),
            max_request_bytes=1_048_576,
        )
    )


def assert_response_signature(
    response_body: bytes,
    headers: Headers,
    status_code: int,
    request_id: UUID = REQUEST_ID,
) -> None:
    timestamp = int(headers[GENERATED_EXECUTION_TIMESTAMP_HEADER])
    payload = generated_execution_signature_payload(
        direction="response",
        timestamp=timestamp,
        request_id=request_id,
        body=response_body,
        status_code=status_code,
    )
    expected = hmac.new(SECRET, payload, sha256).hexdigest()
    assert hmac.compare_digest(
        expected,
        headers[GENERATED_EXECUTION_SIGNATURE_HEADER],
    )


def test_executor_accepts_canonical_hmac_request_and_signs_exact_response() -> None:
    request = execution_request()
    client = app_client(SuccessfulExecutor())

    response = client.post(
        "/v1/generated-node-executions",
        content=request.canonical_json_bytes(),
        headers=signed_headers(request),
    )

    assert response.status_code == 200
    result = GeneratedNodeExecutionResult.model_validate_json(response.content)
    assert result.outputs == {"result": [3, 6]}
    assert_response_signature(response.content, response.headers, 200)

    replay = client.post(
        "/v1/generated-node-executions",
        content=request.canonical_json_bytes(),
        headers=signed_headers(request),
    )
    assert replay.status_code == 401


def test_health_check_is_unauthenticated_and_does_not_invoke_executor() -> None:
    executor = BlockingExecutor()
    app = create_execution_app(
        executor=executor,
        authenticator=ExecutionRequestAuthenticator(
            SECRET,
            skew_seconds=30,
            replay_cache_entries=128,
        ),
        max_request_bytes=1_048_576,
        max_concurrent_executions=1,
        max_queued_executions=0,
        admission_timeout_seconds=0.1,
    )

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.text == "ok"
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert executor.call_count == 0


def test_executor_rejects_body_tampering_before_deserialization() -> None:
    request = execution_request()
    body = request.canonical_json_bytes().replace(b"[1,2]", b"[1,3]")

    response = app_client(SuccessfulExecutor()).post(
        "/v1/generated-node-executions",
        content=body,
        headers=signed_headers(request),
    )

    assert response.status_code == 401


def test_executor_rejects_signature_outside_clock_skew_window() -> None:
    request = execution_request()

    response = app_client(SuccessfulExecutor()).post(
        "/v1/generated-node-executions",
        content=request.canonical_json_bytes(),
        headers=signed_headers(request, timestamp=int(time()) - 31),
    )

    assert response.status_code == 401


def test_authenticated_execution_failure_is_bounded_and_response_signed() -> None:
    request = execution_request()

    response = app_client(FailingExecutor()).post(
        "/v1/generated-node-executions",
        content=request.canonical_json_bytes(),
        headers=signed_headers(request),
    )

    assert response.status_code == 422
    failure = GeneratedNodeExecutionFailure.model_validate_json(response.content)
    assert failure.error_code == "execution_rejected"
    assert not failure.retryable
    assert_response_signature(response.content, response.headers, 422)


@pytest.mark.asyncio
async def test_executor_rejects_authenticated_request_when_admission_is_full() -> None:
    executor = BlockingExecutor()
    app = create_execution_app(
        executor=executor,
        authenticator=ExecutionRequestAuthenticator(
            SECRET,
            skew_seconds=30,
            replay_cache_entries=128,
        ),
        max_request_bytes=1_048_576,
        max_concurrent_executions=1,
        max_queued_executions=0,
        admission_timeout_seconds=0.1,
    )
    first_request = execution_request()
    rejected_request_id = UUID("30000000-0000-0000-0000-000000000004")
    rejected_request = execution_request(rejected_request_id)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first_response_task = asyncio.create_task(
            client.post(
                "/v1/generated-node-executions",
                content=first_request.canonical_json_bytes(),
                headers=signed_headers(first_request),
            )
        )
        await asyncio.wait_for(executor.started.wait(), timeout=1.0)

        rejected_response = await client.post(
            "/v1/generated-node-executions",
            content=rejected_request.canonical_json_bytes(),
            headers=signed_headers(rejected_request),
        )
        executor.release.set()
        first_response = await first_response_task

    assert first_response.status_code == 200
    assert rejected_response.status_code == 503
    failure = GeneratedNodeExecutionFailure.model_validate_json(
        rejected_response.content
    )
    assert failure.error_code == "executor_busy"
    assert failure.retryable
    assert executor.call_count == 1
    assert_response_signature(
        rejected_response.content,
        rejected_response.headers,
        503,
        rejected_request_id,
    )


@pytest.mark.asyncio
async def test_executor_bounds_how_long_authenticated_request_can_queue() -> None:
    executor = BlockingExecutor()
    app = create_execution_app(
        executor=executor,
        authenticator=ExecutionRequestAuthenticator(
            SECRET,
            skew_seconds=30,
            replay_cache_entries=128,
        ),
        max_request_bytes=1_048_576,
        max_concurrent_executions=1,
        max_queued_executions=1,
        admission_timeout_seconds=0.01,
    )
    first_request = execution_request()
    queued_request_id = UUID("30000000-0000-0000-0000-000000000005")
    queued_request = execution_request(queued_request_id)

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        first_response_task = asyncio.create_task(
            client.post(
                "/v1/generated-node-executions",
                content=first_request.canonical_json_bytes(),
                headers=signed_headers(first_request),
            )
        )
        await asyncio.wait_for(executor.started.wait(), timeout=1.0)

        queued_response = await client.post(
            "/v1/generated-node-executions",
            content=queued_request.canonical_json_bytes(),
            headers=signed_headers(queued_request),
        )
        executor.release.set()
        first_response = await first_response_task

    assert first_response.status_code == 200
    assert queued_response.status_code == 503
    failure = GeneratedNodeExecutionFailure.model_validate_json(queued_response.content)
    assert failure.error_code == "executor_busy"
    assert failure.retryable
    assert executor.call_count == 1
    assert_response_signature(
        queued_response.content,
        queued_response.headers,
        503,
        queued_request_id,
    )
