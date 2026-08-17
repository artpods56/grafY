import hmac
from hashlib import sha256
from uuid import UUID

import httpx
import pytest

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

from grafy_api.v1.routes.executions.runtime.generated_executor import (
    GeneratedNodeExecutorClient,
    GeneratedNodeExecutorError,
    GeneratedNodeRemoteExecutionError,
)


REQUEST_ID = UUID("00000000-0000-0000-0000-000000000701")
WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000702")
NODE_ID = UUID("00000000-0000-0000-0000-000000000703")
NOW = 1_797_508_800
HMAC_KEY = b"test-generated-executor-key-32-bytes"


def execution_request() -> GeneratedNodeExecutionRequest:
    manifest = GeneratedNodeManifest(
        title="Triple value",
        description="Multiply an integer by three.",
        inputs=(
            GeneratedNodePort(
                direction=AgentPortDirection.INPUT,
                name="value",
                artifact_type=AgentArtifactType(
                    id="scalar.integer",
                    schema_version=1,
                ),
                shape=PortShape.ONE,
            ),
        ),
        outputs=(
            GeneratedNodePort(
                direction=AgentPortDirection.OUTPUT,
                name="result",
                artifact_type=AgentArtifactType(
                    id="scalar.integer",
                    schema_version=1,
                ),
                shape=PortShape.ONE,
            ),
        ),
    )
    document = GeneratedNodeBuildDocument(
        source_digest="a" * 64,
        lock_digest="b" * 64,
        tests_digest="c" * 64,
        implementation_digest="d" * 64,
        manifest=manifest,
        capabilities=CapabilityManifest(),
        runtime_image_digest="e" * 64,
        profile_digest="f" * 64,
        runtime_artifact=RuntimeArtifactReference(
            provider="docker-trusted-development",
            ref="snapshot/triple-v1",
            digest="0" * 64,
        ),
    )
    return GeneratedNodeExecutionRequest(
        request_id=REQUEST_ID,
        workspace_id=WORKSPACE_ID,
        graph_node_id="canvas-node",
        node_id=NODE_ID,
        revision=1,
        build_digest=document.digest,
        build_document=document,
        inputs={"value": 7},
    )


def signed_response(
    *,
    request: httpx.Request,
    body: bytes,
    status_code: int,
    signature: str | None = None,
) -> httpx.Response:
    request_id = UUID(request.headers[GENERATED_EXECUTION_REQUEST_ID_HEADER])
    effective_signature = signature or hmac.new(
        HMAC_KEY,
        generated_execution_signature_payload(
            direction="response",
            timestamp=NOW,
            request_id=request_id,
            body=body,
            status_code=status_code,
        ),
        sha256,
    ).hexdigest()
    return httpx.Response(
        status_code,
        content=body,
        headers={
            GENERATED_EXECUTION_TIMESTAMP_HEADER: str(NOW),
            GENERATED_EXECUTION_REQUEST_ID_HEADER: str(request_id),
            GENERATED_EXECUTION_SIGNATURE_HEADER: effective_signature,
        },
    )


@pytest.mark.asyncio
async def test_executor_signs_request_and_accepts_exact_signed_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "grafy_api.v1.routes.executions.runtime.generated_executor.time.time",
        lambda: NOW,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        timestamp = int(request.headers[GENERATED_EXECUTION_TIMESTAMP_HEADER])
        request_id = UUID(request.headers[GENERATED_EXECUTION_REQUEST_ID_HEADER])
        expected = hmac.new(
            HMAC_KEY,
            generated_execution_signature_payload(
                direction="request",
                timestamp=timestamp,
                request_id=request_id,
                body=body,
            ),
            sha256,
        ).hexdigest()
        assert request.url.path == "/v1/generated-node-executions"
        assert hmac.compare_digest(
            request.headers[GENERATED_EXECUTION_SIGNATURE_HEADER],
            expected,
        )
        result = GeneratedNodeExecutionResult(
            request_id=request_id,
            outputs={"result": 21},
            execution_digest="1" * 64,
            duration_ms=8,
        )
        return signed_response(
            request=request,
            body=result.canonical_json_bytes(),
            status_code=200,
        )

    client = GeneratedNodeExecutorClient(
        base_url="https://agent-worker.test",
        hmac_key=HMAC_KEY,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )
    try:
        result = await client.execute(execution_request())
    finally:
        await client.close()

    assert result.outputs == {"result": 21}


@pytest.mark.asyncio
async def test_executor_rejects_tampered_or_replayed_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "grafy_api.v1.routes.executions.runtime.generated_executor.time.time",
        lambda: NOW,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        result = GeneratedNodeExecutionResult(
            request_id=REQUEST_ID,
            outputs={"result": 21},
            execution_digest="1" * 64,
            duration_ms=8,
        )
        return signed_response(
            request=request,
            body=result.canonical_json_bytes(),
            status_code=200,
            signature="0" * 64,
        )

    client = GeneratedNodeExecutorClient(
        base_url="https://agent-worker.test",
        hmac_key=HMAC_KEY,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(GeneratedNodeExecutorError, match="signature is invalid"):
            await client.execute(execution_request())
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_executor_preserves_signed_typed_worker_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "grafy_api.v1.routes.executions.runtime.generated_executor.time.time",
        lambda: NOW,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        failure = GeneratedNodeExecutionFailure(
            request_id=REQUEST_ID,
            error_code="runtime_limit",
            message="Execution exceeded its approved wall-time limit.",
            retryable=False,
        )
        return signed_response(
            request=request,
            body=failure.canonical_json_bytes(),
            status_code=422,
        )

    client = GeneratedNodeExecutorClient(
        base_url="https://agent-worker.test",
        hmac_key=HMAC_KEY,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )
    try:
        with pytest.raises(GeneratedNodeRemoteExecutionError) as raised:
            await client.execute(execution_request())
    finally:
        await client.close()

    assert raised.value.error_code == "runtime_limit"
    assert raised.value.retryable is False
