from hashlib import sha256
from uuid import UUID

import pytest
from pydantic import ValidationError

from grafy_core.artifacts import ArtifactTypeKey, ArtifactTypeSpec, NoConfig
from grafy_core.domain.agent_authoring import (
    AgentArtifactType,
    AgentPortDirection,
    BuildArtifactSet,
    CapabilityManifest,
    GeneratedNodeManifest,
    GeneratedNodePort,
    GeneratedNodeReference,
    GeneratedNodeReferenceError,
    NodeRelease,
    RuntimeArtifactReference,
)
from grafy_core.domain.node_secrets import JsonValue
from grafy_core.nodes import NodeExecutionContext, PortShape
from grafy_core.operators.arithmetic import INTEGER_VALUE
from grafy_core.operators.generated import (
    GeneratedNode,
    GeneratedNodeContractError,
    GeneratedNodeExecutionError,
)
from grafy_core.operators.text import TEXT_VALUE
from grafy_core.ports.generated_execution import (
    GeneratedNodeExecutionRequest,
    GeneratedNodeExecutionResult,
    generated_execution_signature_payload,
)
from grafy_core.source_bundles import GeneratedNodeBuildDocument


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000501")
NODE_ID = UUID("00000000-0000-0000-0000-000000000502")
DRAFT_ID = UUID("00000000-0000-0000-0000-000000000503")
BUILD_ID = UUID("00000000-0000-0000-0000-000000000504")
THREAD_ID = UUID("00000000-0000-0000-0000-000000000505")
ENVIRONMENT_ID = UUID("00000000-0000-0000-0000-000000000506")
APPROVAL_ID = UUID("00000000-0000-0000-0000-000000000507")
USER_ID = UUID("00000000-0000-0000-0000-000000000508")
DIGESTS = tuple(character * 64 for character in "abcdef01")


class RecordingExecutor:
    def __init__(self, outputs: dict[str, JsonValue]) -> None:
        self.outputs = outputs
        self.requests: list[GeneratedNodeExecutionRequest] = []

    async def execute(
        self,
        request: GeneratedNodeExecutionRequest,
        /,
    ) -> GeneratedNodeExecutionResult:
        self.requests.append(request)
        return GeneratedNodeExecutionResult(
            request_id=request.request_id,
            outputs=self.outputs,
            execution_digest="9" * 64,
            duration_ms=12,
        )


def release(
    *,
    capabilities: CapabilityManifest | None = None,
) -> NodeRelease:
    manifest = GeneratedNodeManifest(
        title="Triple values",
        description="Multiply every integer by three.",
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
        outputs=(
            GeneratedNodePort(
                direction=AgentPortDirection.OUTPUT,
                name="result",
                artifact_type=AgentArtifactType(
                    id="scalar.integer",
                    schema_version=1,
                ),
                shape=PortShape.MANY,
            ),
        ),
    )
    effective_capabilities = capabilities or CapabilityManifest()
    runtime_artifact = RuntimeArtifactReference(
        provider="daytona",
        ref="snapshot/triple-values-v1",
        digest=DIGESTS[7],
    )
    document = GeneratedNodeBuildDocument(
        source_digest=DIGESTS[0],
        lock_digest=DIGESTS[1],
        tests_digest=DIGESTS[2],
        implementation_digest=DIGESTS[3],
        manifest=manifest,
        capabilities=effective_capabilities,
        runtime_image_digest=DIGESTS[4],
        profile_digest=DIGESTS[5],
        runtime_artifact=runtime_artifact,
    )
    artifacts = BuildArtifactSet(
        source_bundle_key=f"generated/sources/{DIGESTS[0]}.tar.gz",
        source_digest=DIGESTS[0],
        lock_digest=DIGESTS[1],
        tests_digest=DIGESTS[2],
        build_digest=document.digest,
        implementation_digest=DIGESTS[3],
        runtime_image_digest=DIGESTS[4],
        profile_digest=DIGESTS[5],
        runtime_artifact=runtime_artifact,
        tests_passed=True,
    )
    return NodeRelease(
        workspace_id=WORKSPACE_ID,
        node_id=NODE_ID,
        revision=1,
        draft_node_id=DRAFT_ID,
        build_attempt_id=BUILD_ID,
        thread_id=THREAD_ID,
        environment_id=ENVIRONMENT_ID,
        manifest=manifest,
        capabilities=effective_capabilities,
        capability_digest=effective_capabilities.digest,
        artifacts=artifacts,
        capability_approval_id=APPROVAL_ID,
        approved_by_user_id=USER_ID,
        created_by_user_id=USER_ID,
    )


def artifact_types() -> dict[ArtifactTypeKey, ArtifactTypeSpec]:
    return {
        INTEGER_VALUE.key: INTEGER_VALUE,
        TEXT_VALUE.key: TEXT_VALUE,
    }


@pytest.mark.asyncio
async def test_generated_node_executes_exact_release_with_typed_json_contract() -> None:
    executor = RecordingExecutor(outputs={"result": [3, 6, 9]})
    node = GeneratedNode(
        release(),
        executor,
        artifact_types(),
    )
    input_model = node.input_contract.model
    inputs = input_model.model_validate({"values": [1, 2, 3]})

    output = await node.run(
        NodeExecutionContext(
            workspace_id=WORKSPACE_ID,
            node_id="canvas-node",
            invocation_path=(2, 4),
        ),
        NoConfig(),
        inputs,
    )

    assert output.model_dump() == {"result": [3, 6, 9]}
    assert len(executor.requests) == 1
    request = executor.requests[0]
    assert request.node_id == NODE_ID
    assert request.revision == 1
    assert request.graph_node_id == "canvas-node"
    assert request.invocation_path == (2, 4)
    assert request.inputs == {"values": [1, 2, 3]}
    assert request.build_document.digest == request.build_digest


@pytest.mark.asyncio
async def test_generated_node_rejects_executor_output_outside_manifest() -> None:
    executor = RecordingExecutor(outputs={"result": [True]})
    node = GeneratedNode(
        release(),
        executor,
        artifact_types(),
    )
    inputs = node.input_contract.model.model_validate({"values": [1]})

    with pytest.raises(
        GeneratedNodeExecutionError,
        match="violate the published manifest",
    ):
        await node.run(
            NodeExecutionContext(workspace_id=WORKSPACE_ID),
            NoConfig(),
            inputs,
        )


def test_generated_node_rejects_capabilities_runtime_cannot_enforce() -> None:
    executor = RecordingExecutor(outputs={"result": [3]})

    with pytest.raises(GeneratedNodeContractError, match="outbound HTTP"):
        GeneratedNode(
            release(
                capabilities=CapabilityManifest(
                    outbound_http_origins=("https://api.example.com",),
                )
            ),
            executor,
            artifact_types(),
        )


def test_execution_payload_rejects_tampered_build_document() -> None:
    published = release()
    document = GeneratedNodeBuildDocument(
        source_digest=published.artifacts.source_digest,
        lock_digest=published.artifacts.lock_digest,
        tests_digest=published.artifacts.tests_digest,
        implementation_digest=published.artifacts.implementation_digest,
        manifest=published.manifest,
        capabilities=published.capabilities,
        runtime_image_digest=published.artifacts.runtime_image_digest,
        profile_digest=published.artifacts.profile_digest,
        runtime_artifact=published.artifacts.runtime_artifact,
    )

    with pytest.raises(ValidationError, match="does not match its build digest"):
        GeneratedNodeExecutionRequest(
            request_id=APPROVAL_ID,
            workspace_id=WORKSPACE_ID,
            node_id=NODE_ID,
            revision=1,
            build_digest="0" * 64,
            build_document=document,
            inputs={"values": [1]},
        )


def test_execution_signatures_bind_direction_status_and_exact_body() -> None:
    body = b'{"request":"exact"}'
    request_payload = generated_execution_signature_payload(
        direction="request",
        timestamp=1_797_508_800,
        request_id=APPROVAL_ID,
        body=body,
    )
    response_payload = generated_execution_signature_payload(
        direction="response",
        timestamp=1_797_508_800,
        request_id=APPROVAL_ID,
        body=body,
        status_code=200,
    )

    assert sha256(body).hexdigest().encode("ascii") in request_payload
    assert request_payload != response_payload
    assert b"\n200\n" in response_payload
    with pytest.raises(
        ValueError,
        match="request signatures do not include a status code",
    ):
        generated_execution_signature_payload(
            direction="request",
            timestamp=1_797_508_800,
            request_id=APPROVAL_ID,
            body=body,
            status_code=200,
        )


def test_generated_node_reference_parses_exact_operator_identity() -> None:
    reference = GeneratedNodeReference.from_operator_identity(
        f"generated.node.{NODE_ID}",
        4,
    )

    assert reference.node_id == NODE_ID
    assert reference.revision == 4
    assert reference.operator_id == f"generated.node.{NODE_ID}"
    assert reference.operator_version == 4
    assert GeneratedNodeReference.try_from_operator_identity("text.input", 1) is None
    with pytest.raises(GeneratedNodeReferenceError, match="invalid node UUID"):
        GeneratedNodeReference.from_operator_identity("generated.node.invalid", 1)
