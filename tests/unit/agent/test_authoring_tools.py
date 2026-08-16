from uuid import UUID

import pytest

from grafy_agent.errors import AgentRuntimeError
from grafy_agent.models import (
    AgentLease,
    AgentProgress,
    CapabilityProposal,
    CapabilityProposalReceipt,
    NodeSourceBundle,
    ReleaseProposal,
    ReleaseProposalReceipt,
    SandboxExecutionAuthority,
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SourceBundleVerification,
)
from grafy_agent.sandbox.memory import InMemorySandboxWorkspace
from grafy_agent.tools import NodeAuthoringTools, node_authoring_toolset


WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000001")
THREAD_ID = UUID("20000000-0000-0000-0000-000000000002")
ENVIRONMENT_ID = UUID("20000000-0000-0000-0000-000000000003")
RUN_ID = UUID("20000000-0000-0000-0000-000000000004")
DRAFT_ID = UUID("20000000-0000-0000-0000-000000000005")
TOKEN = UUID("20000000-0000-0000-0000-000000000006")


class RecordingControl:
    def __init__(self) -> None:
        self.progress: list[AgentProgress] = []

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
        del lease, proposal
        return ReleaseProposalReceipt(build_attempt_id=RUN_ID)


class UnusedVerifier:
    async def verify(
        self,
        *,
        lease: AgentLease,
        source_bundle: NodeSourceBundle,
        profile_id: str,
    ) -> SourceBundleVerification:
        del lease, source_bundle, profile_id
        raise AssertionError("Invalidated source must not reach clean verification")


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
async def test_arbitrary_command_after_tests_invalidates_release_proof() -> None:
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
    for argv in (
        ("uv", "lock"),
        ("uv", "lock", "--check"),
        ("uv", "sync", "--locked"),
        ("uv", "run", "--locked", "pytest", "-q"),
        ("python", "mutate_source.py"),
    ):
        sandbox.register_command(
            environment_id=ENVIRONMENT_ID,
            cwd=node_root,
            argv=argv,
            handler=successful_command,
        )
    tools = NodeAuthoringTools(
        sandbox=sandbox,
        session=session,
        control=RecordingControl(),
        verifier=UnusedVerifier(),
        profile_id="python-3.12",
        lease=lease,
    )

    assert (await tools.uv_lock(DRAFT_ID)).exit_code == 0
    assert (await tools.uv_sync(DRAFT_ID)).exit_code == 0
    assert (await tools.uv_test(DRAFT_ID)).exit_code == 0
    assert (
        await tools.run_command(
            DRAFT_ID,
            ("python", "mutate_source.py"),
            30,
        )
    ).exit_code == 0

    with pytest.raises(AgentRuntimeError, match="validation steps"):
        await tools.propose_release(DRAFT_ID, "should not be accepted")


def test_real_pydantic_ai_toolset_exposes_typed_capability_and_uv_tools() -> None:
    toolset = node_authoring_toolset()

    assert set(toolset.tools) == {
        "apply_node_patch",
        "propose_node_release",
        "read_node_file",
        "request_node_capabilities",
        "run_node_command",
        "uv_add",
        "uv_lock",
        "uv_sync",
        "uv_test",
        "write_node_file",
    }
    capabilities_schema = toolset.tools[
        "request_node_capabilities"
    ].function_schema.json_schema
    runtime_schema = capabilities_schema["$defs"]["RuntimeLimits"]["properties"]
    assert "persistent_disk_bytes" in runtime_schema
    assert "thread_count" in runtime_schema
    assert "outbound_total_bytes" in runtime_schema
