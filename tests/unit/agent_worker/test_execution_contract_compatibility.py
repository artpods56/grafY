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
    GeneratedNodeExecutionRequest,
    GeneratedNodeExecutionResult,
)
from grafy_core.source_bundles import GeneratedNodeBuildDocument

from grafy_agent_worker.http import (
    ExecutionRequestAuthenticator,
    create_execution_app,
)
from grafy_api.v1.routes.executions.runtime.generated_executor import (
    GeneratedNodeExecutorClient,
)


HMAC_KEY = b"worker-api-contract-test-key-32-bytes"
REQUEST_ID = UUID("70000000-0000-0000-0000-000000000001")


class EchoGeneratedReleaseExecutor:
    async def execute(
        self,
        request: GeneratedNodeExecutionRequest,
        /,
    ) -> GeneratedNodeExecutionResult:
        value = request.inputs["value"]
        assert isinstance(value, int)
        return GeneratedNodeExecutionResult(
            request_id=request.request_id,
            outputs={"result": value * 3},
            execution_digest=sha256(request.canonical_json_bytes()).hexdigest(),
            duration_ms=3,
        )


def generated_execution_request() -> GeneratedNodeExecutionRequest:
    manifest = GeneratedNodeManifest(
        title="Triple value",
        description="Multiply one integer by three.",
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
        workspace_id=UUID("70000000-0000-0000-0000-000000000002"),
        node_id=UUID("70000000-0000-0000-0000-000000000003"),
        revision=1,
        build_digest=document.digest,
        build_document=document,
        inputs={"value": 7},
    )


@pytest.mark.asyncio
async def test_api_client_and_worker_endpoint_share_exact_signed_contract() -> None:
    app = create_execution_app(
        executor=EchoGeneratedReleaseExecutor(),
        authenticator=ExecutionRequestAuthenticator(
            HMAC_KEY,
            skew_seconds=30,
            replay_cache_entries=128,
        ),
        max_request_bytes=1_048_576,
    )
    client = GeneratedNodeExecutorClient(
        base_url="https://agent-worker.test",
        hmac_key=HMAC_KEY,
        timeout_seconds=5,
        transport=httpx.ASGITransport(app=app),
    )
    try:
        result = await client.execute(generated_execution_request())
    finally:
        await client.close()

    assert result.request_id == REQUEST_ID
    assert result.outputs == {"result": 21}
