from types import SimpleNamespace
from uuid import UUID

import pytest
from pydantic_ai import ModelRetry

from grafy_agent.errors import AgentRuntimeError, SandboxPathError
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
    SandboxRuntimeArtifact,
    SourceBundleVerification,
    normalized_relative_path,
)
from grafy_agent.sandbox.memory import InMemorySandboxWorkspace
from grafy_agent.tools import (
    NodeAuthoringTools,
    NodeToolDependencies,
    node_authoring_toolset,
    propose_node_release,
    read_node_file,
)
from grafy_core.domain.agent_authoring import (
    AgentArtifactType,
    AgentPortDirection,
    CapabilityManifest,
    GeneratedNodeManifest,
    GeneratedNodePort,
)
from grafy_core.nodes import PortShape
from grafy_core.source_bundles import GeneratedNodeSourceDefinition


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
                reference="reviewed-runtime",
                digest="c" * 64,
            ),
        )


def _node_definition() -> GeneratedNodeSourceDefinition:
    text_type = AgentArtifactType(id="scalar.text", schema_version=1)
    return GeneratedNodeSourceDefinition(
        manifest=GeneratedNodeManifest(
            title="Append suffix",
            description="Append a suffix to every text item.",
            inputs=(
                GeneratedNodePort(
                    direction=AgentPortDirection.INPUT,
                    name="items",
                    artifact_type=text_type,
                    shape=PortShape.MANY,
                ),
            ),
            outputs=(
                GeneratedNodePort(
                    direction=AgentPortDirection.OUTPUT,
                    name="result",
                    artifact_type=text_type,
                    shape=PortShape.MANY,
                ),
            ),
        ),
        capabilities=CapabilityManifest(),
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


@pytest.mark.asyncio
async def test_node_json_alignment_after_tests_keeps_release_proof() -> None:
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
    definition = _node_definition()
    files = (
        ("pyproject.toml", "[project]\nname='node'\nversion='0.1.0'\n"),
        ("uv.lock", "version = 1\n"),
        ("node.json", definition.model_dump_json(indent=2) + "\n"),
        ("src/node.py", "def run(inputs): return inputs\n"),
        ("tests/test_node.py", "def test_node(): assert True\n"),
    )
    for path, content in files:
        await sandbox.write_text(
            session,
            path=f"{node_root}/{path}",
            content=content,
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
    tools = NodeAuthoringTools(
        sandbox=sandbox,
        session=session,
        control=RecordingControl(),
        verifier=SuccessfulVerifier(),
        profile_id="python-3.12",
        lease=lease,
    )

    assert (await tools.uv_lock(DRAFT_ID)).exit_code == 0
    assert (await tools.uv_sync(DRAFT_ID)).exit_code == 0
    assert (await tools.uv_test(DRAFT_ID)).exit_code == 0
    aligned = definition.model_copy(
        update={"capabilities": CapabilityManifest()},
    )
    await tools.write_file(
        DRAFT_ID,
        "node.json",
        aligned.model_dump_json(indent=2) + "\n",
    )

    receipt = await tools.propose_release(DRAFT_ID, "aligned node.json after tests")

    assert receipt.build_attempt_id == RUN_ID


@pytest.mark.asyncio
async def test_tool_failures_are_returned_to_the_model_instead_of_aborting() -> None:
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
    tools = NodeAuthoringTools(
        sandbox=sandbox,
        session=session,
        control=RecordingControl(),
        verifier=UnusedVerifier(),
        profile_id="python-3.12",
        lease=lease,
    )
    ctx = SimpleNamespace(deps=NodeToolDependencies(tools=tools))

    with pytest.raises(ModelRetry, match="does not exist"):
        await read_node_file(ctx, DRAFT_ID, "src/main.py")
    with pytest.raises(ModelRetry, match="validation steps"):
        await propose_node_release(ctx, DRAFT_ID, "too early")


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


def test_normalized_relative_path_collapses_harmless_prefixes() -> None:
    assert normalized_relative_path("./src/node.py") == "src/node.py"
    assert normalized_relative_path("src/node.py/") == "src/node.py"
    assert normalized_relative_path("src//node.py") == "src/node.py"
    with pytest.raises(SandboxPathError, match="parent segments"):
        normalized_relative_path("../etc/passwd")
    with pytest.raises(SandboxPathError, match="relative path"):
        normalized_relative_path("/workspace/src/node.py")
