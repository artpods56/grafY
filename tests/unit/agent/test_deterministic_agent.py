from uuid import UUID

import pytest

from grafy_agent.deterministic_agent import (
    DeterministicCodingAgent,
    DeterministicNodeProject,
)
from grafy_agent.models import (
    AgentLease,
    AgentProgress,
    CapabilityProposal,
    CapabilityProposalReceipt,
    CodingAgentRequest,
    NodeSourceBundle,
    ReleaseProposal,
    ReleaseProposalReceipt,
    SandboxExecutionAuthority,
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxRuntimeArtifact,
    SourceBundleVerification,
)
from grafy_agent.sandbox.memory import InMemorySandboxWorkspace
from grafy_core.domain.agent_authoring import (
    AgentArtifactType,
    AgentPortDirection,
    CapabilityManifest,
    GeneratedNodeManifest,
    GeneratedNodePort,
)
from grafy_core.nodes import PortShape
from grafy_core.source_bundles import GeneratedNodeSourceDefinition


WORKSPACE_ID = UUID("30000000-0000-0000-0000-000000000001")
THREAD_ID = UUID("30000000-0000-0000-0000-000000000002")
ENVIRONMENT_ID = UUID("30000000-0000-0000-0000-000000000003")
RUN_ID = UUID("30000000-0000-0000-0000-000000000004")
DRAFT_ID = UUID("30000000-0000-0000-0000-000000000005")
TOKEN = UUID("30000000-0000-0000-0000-000000000006")


class RecordingControl:
    def __init__(self) -> None:
        self.progress: list[AgentProgress] = []
        self.releases: list[ReleaseProposal] = []

    async def record_progress(
        self,
        lease: AgentLease,
        progress: AgentProgress,
    ) -> None:
        del lease
        self.progress.append(progress)

    async def cancellation_requested(self, lease: AgentLease) -> bool:
        del lease
        return False

    async def request_capabilities(
        self,
        lease: AgentLease,
        proposal: CapabilityProposal,
    ) -> CapabilityProposalReceipt:
        del lease
        return CapabilityProposalReceipt(
            capability_digest=proposal.capabilities.digest,
        )

    async def propose_release(
        self,
        lease: AgentLease,
        proposal: ReleaseProposal,
    ) -> ReleaseProposalReceipt:
        del lease
        self.releases.append(proposal)
        return ReleaseProposalReceipt(build_attempt_id=RUN_ID)


class SuccessfulVerifier:
    async def verify(
        self,
        *,
        lease: AgentLease,
        source_bundle: NodeSourceBundle,
        profile_id: str,
    ) -> SourceBundleVerification:
        del lease, profile_id
        return SourceBundleVerification(
            source_digest=source_bundle.source_digest,
            lock_digest=source_bundle.lock_digest,
            tests_digest=source_bundle.tests_digest,
            implementation_digest=source_bundle.implementation_digest,
            runtime_image_digest="a" * 64,
            profile_digest="b" * 64,
            runtime_artifact=SandboxRuntimeArtifact(
                provider="memory",
                reference="deterministic-runtime",
                digest="c" * 64,
            ),
        )


async def successful_command(
    request: SandboxExecutionRequest,
) -> SandboxExecutionResult:
    del request
    return SandboxExecutionResult(
        exit_code=0,
        stdout="ok",
        stderr="",
        duration_ms=1,
    )


@pytest.mark.asyncio
async def test_deterministic_agent_builds_explicit_project_without_model_provider() -> (
    None
):
    sandbox = InMemorySandboxWorkspace()
    workspace = await sandbox.ensure_workspace(
        environment_id=ENVIRONMENT_ID,
        provider_environment_id=None,
        profile_id="python-3.12",
    )
    lease = AgentLease(
        workspace_id=WORKSPACE_ID,
        thread_id=THREAD_ID,
        environment_id=ENVIRONMENT_ID,
        run_id=RUN_ID,
        lease_token=TOKEN,
        fencing_token=1,
        target_draft_ids=(DRAFT_ID,),
    )
    session = await sandbox.open_session(
        workspace,
        SandboxExecutionAuthority.from_agent_lease(lease),
    )
    node_root = f"nodes/{DRAFT_ID}"
    await sandbox.write_text(
        session,
        path=f"{node_root}/pyproject.toml",
        content="[project]\nname='deterministic-node'\nversion='0.1.0'\n",
        max_bytes=1_048_576,
    )
    await sandbox.write_text(
        session,
        path=f"{node_root}/uv.lock",
        content="version = 1\n",
        max_bytes=1_048_576,
    )
    for argv in (
        ("uv", "lock"),
        ("uv", "lock", "--check"),
        ("uv", "sync", "--locked"),
        ("uv", "run", "--locked", "pytest", "-q"),
    ):
        sandbox.register_command(
            environment_id=ENVIRONMENT_ID,
            cwd=node_root,
            argv=argv,
            handler=successful_command,
        )
    integer_type = AgentArtifactType(id="scalar.integer", schema_version=1)
    definition = GeneratedNodeSourceDefinition(
        manifest=GeneratedNodeManifest(
            title="Triple values",
            description="Multiply integer values by three.",
            inputs=(
                GeneratedNodePort(
                    direction=AgentPortDirection.INPUT,
                    name="values",
                    artifact_type=integer_type,
                    shape=PortShape.MANY,
                ),
            ),
            outputs=(
                GeneratedNodePort(
                    direction=AgentPortDirection.OUTPUT,
                    name="result",
                    artifact_type=integer_type,
                    shape=PortShape.MANY,
                ),
            ),
        ),
        capabilities=CapabilityManifest(),
    )
    control = RecordingControl()
    agent = DeterministicCodingAgent(
        {
            DRAFT_ID: DeterministicNodeProject(
                definition=definition,
                source=(
                    "def run(inputs):\n"
                    "    return {'result': [value * 3 for value in inputs['values']]}\n"
                ),
                tests="def test_node():\n    assert True\n",
            )
        }
    )

    result = await agent.run(
        request=CodingAgentRequest(instructions="Multiply every value by three."),
        lease=lease,
        session=session,
        profile_id="python-3.12",
        sandbox=sandbox,
        verifier=SuccessfulVerifier(),
        control=control,
    )

    assert result.model_name == "deterministic-local"
    assert len(control.releases) == 1
    assert control.releases[0].manifest == definition.manifest
    assert control.releases[0].source_bundle.file_count == 5
