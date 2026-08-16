from hashlib import sha256
import json
from uuid import UUID

import pytest

from grafy_agent.models import (
    SandboxExecutionAuthority,
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxNetworkMode,
    SandboxSession,
    SandboxWorkspace,
)
from grafy_agent.sandbox.memory import InMemorySandboxWorkspace
from grafy_core.domain.agent_authoring import (
    AgentArtifactType,
    AgentPortDirection,
    CapabilityManifest,
    GeneratedNodeManifest,
    GeneratedNodePort,
    RuntimeArtifactReference,
)
from grafy_core.nodes import PortShape
from grafy_core.ports.generated_execution import GeneratedNodeExecutionRequest
from grafy_core.source_bundles import GeneratedNodeBuildDocument

from grafy_agent_worker.execution import SandboxGeneratedReleaseExecutor


AUTHORING_ENVIRONMENT_ID = UUID("40000000-0000-0000-0000-000000000001")
EXECUTION_REQUEST_ID = UUID("40000000-0000-0000-0000-000000000002")
WORKSPACE_ID = UUID("40000000-0000-0000-0000-000000000003")
NODE_ID = UUID("40000000-0000-0000-0000-000000000004")
TOKEN = UUID("40000000-0000-0000-0000-000000000005")
SOURCE_DIGEST = "1" * 64


class OfflineRuntimeSandbox(InMemorySandboxWorkspace):
    def __init__(self) -> None:
        super().__init__()
        self.runtime_requests: list[SandboxExecutionRequest] = []
        self.destroyed_runtime_ids: list[UUID] = []

    async def execute(
        self,
        session: SandboxSession,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        if session.workspace.environment_id == AUTHORING_ENVIRONMENT_ID:
            return await super().execute(session, request)
        self.runtime_requests.append(request)
        source = await self.read_text(
            session,
            path="node/src/node.py",
            max_bytes=1_024,
        )
        assert "value * 3" in source.content
        assert request.stdin is not None
        inputs = json.loads(request.stdin)
        values = inputs["values"]
        return SandboxExecutionResult(
            exit_code=0,
            stdout=json.dumps({"result": [value * 3 for value in values]}),
            stderr="",
            duration_ms=3,
        )

    async def destroy_workspace(self, workspace: SandboxWorkspace) -> None:
        if workspace.environment_id != AUTHORING_ENVIRONMENT_ID:
            self.destroyed_runtime_ids.append(workspace.environment_id)
        await super().destroy_workspace(workspace)


@pytest.mark.asyncio
async def test_published_release_runs_from_exact_artifact_without_network_or_uv() -> (
    None
):
    sandbox = OfflineRuntimeSandbox()
    authoring = await sandbox.ensure_workspace(
        environment_id=AUTHORING_ENVIRONMENT_ID,
        provider_environment_id=None,
        profile_id="python-3.12",
    )
    session = await sandbox.open_session(
        authoring,
        SandboxExecutionAuthority(
            execution_id=NODE_ID,
            token=TOKEN,
            fencing_token=1,
        ),
    )
    await sandbox.write_text(
        session,
        path="node/src/node.py",
        content=(
            "def run(inputs):\n"
            "    return {'result': [value * 3 for value in inputs['values']]}\n"
        ),
        max_bytes=1_024,
    )
    await sandbox.write_text(
        session,
        path="node/.venv/bin/python",
        content="immutable locked runtime",
        max_bytes=1_024,
    )
    artifact_identity = sha256(
        (
            f"{SOURCE_DIGEST}:{authoring.runtime_image_digest}:"
            f"{authoring.profile_digest}"
        ).encode("ascii")
    ).hexdigest()
    artifact = await sandbox.freeze_workspace(
        session,
        artifact_name=f"grafy-node-{artifact_identity}",
        source_digest=SOURCE_DIGEST,
    )
    await sandbox.terminate_session(session)

    manifest = GeneratedNodeManifest(
        title="Triple",
        description="Triple values.",
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
    runtime_artifact = RuntimeArtifactReference(
        provider=artifact.provider,
        ref=artifact.reference,
        digest=artifact.digest,
    )
    document = GeneratedNodeBuildDocument(
        source_digest=SOURCE_DIGEST,
        lock_digest="2" * 64,
        tests_digest="3" * 64,
        implementation_digest="4" * 64,
        manifest=manifest,
        capabilities=CapabilityManifest(),
        runtime_image_digest=authoring.runtime_image_digest,
        profile_digest=authoring.profile_digest,
        runtime_artifact=runtime_artifact,
    )
    request = GeneratedNodeExecutionRequest(
        request_id=EXECUTION_REQUEST_ID,
        workspace_id=WORKSPACE_ID,
        node_id=NODE_ID,
        revision=1,
        build_digest=document.digest,
        build_document=document,
        inputs={"values": [1, 2]},
    )
    executor = SandboxGeneratedReleaseExecutor(
        {"memory": sandbox},
        max_request_bytes=1_048_576,
        max_response_bytes=1_048_576,
    )

    result = await executor.execute(request)

    assert result.outputs == {"result": [3, 6]}
    assert len(sandbox.runtime_requests) == 1
    runtime_request = sandbox.runtime_requests[0]
    assert runtime_request.argv[:2] == (".venv/bin/python", "-I")
    assert runtime_request.network_mode is SandboxNetworkMode.BLOCKED
    assert "uv" not in runtime_request.argv
    assert len(sandbox.destroyed_runtime_ids) == 1
