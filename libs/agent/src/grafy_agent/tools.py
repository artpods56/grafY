from dataclasses import dataclass
from uuid import UUID

from pydantic_ai import FunctionToolset, RunContext

from grafy_core.domain.agent_authoring import CapabilityManifest, GeneratedNodeManifest
from grafy_core.source_bundles import (
    GeneratedNodeSourceDefinition,
    read_source_bundle,
)

from grafy_agent.errors import AgentRuntimeError
from grafy_agent.bundles import inspect_node_source_bundle
from grafy_agent.models import (
    AgentLease,
    AgentProgress,
    CapabilityProposal,
    CapabilityProposalReceipt,
    ReleaseProposal,
    ReleaseProposalReceipt,
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxFileChange,
    SandboxFileContents,
    SandboxPatchResult,
    SandboxNetworkMode,
    SandboxSession,
    normalized_relative_path,
    validated_package_requirements,
)
from grafy_agent.ports import (
    AgentAuthoringControlPort,
    SandboxWorkspacePort,
    SourceBundleVerifierPort,
)


NODE_PROJECT_FILE_LIMIT = 1_048_576
NODE_COMMAND_OUTPUT_LIMIT = 1_048_576


@dataclass(frozen=True, slots=True)
class NodeToolDependencies:
    tools: "NodeAuthoringTools"


class NodeAuthoringTools:
    """Node-scoped coding operations within a shared environment workspace."""

    def __init__(
        self,
        *,
        sandbox: SandboxWorkspacePort,
        session: SandboxSession,
        control: AgentAuthoringControlPort,
        verifier: SourceBundleVerifierPort,
        profile_id: str,
        lease: AgentLease,
    ) -> None:
        self._sandbox = sandbox
        self._session = session
        self._control = control
        self._verifier = verifier
        self._profile_id = profile_id
        self._lease = lease
        self._target_ids = frozenset(lease.target_draft_ids)
        self._validated_steps: dict[UUID, set[str]] = {
            draft_node_id: set() for draft_node_id in lease.target_draft_ids
        }
        self._proposed_release_ids: set[UUID] = set()

    @property
    def proposed_release_ids(self) -> frozenset[UUID]:
        return frozenset(self._proposed_release_ids)

    async def read_file(self, draft_node_id: UUID, path: str) -> SandboxFileContents:
        return await self._sandbox.read_text(
            self._session,
            path=self._node_path(draft_node_id, path),
            max_bytes=NODE_PROJECT_FILE_LIMIT,
        )

    async def write_file(
        self,
        draft_node_id: UUID,
        path: str,
        content: str,
    ) -> SandboxFileChange:
        self._invalidate_validation(draft_node_id)
        result = await self._sandbox.write_text(
            self._session,
            path=self._node_path(draft_node_id, path),
            content=content,
            max_bytes=NODE_PROJECT_FILE_LIMIT,
        )
        await self._control.record_progress(
            self._lease,
            AgentProgress(
                message=f"Wrote {result.path} ({result.byte_count} bytes)",
                draft_node_id=draft_node_id,
            ),
        )
        return result

    async def apply_patch(
        self,
        draft_node_id: UUID,
        path: str,
        expected: str,
        replacement: str,
    ) -> SandboxPatchResult:
        if expected == "":
            raise AgentRuntimeError("Patch expected text must not be empty")
        self._invalidate_validation(draft_node_id)
        result = await self._sandbox.replace_text(
            self._session,
            path=self._node_path(draft_node_id, path),
            expected=expected,
            replacement=replacement,
            max_bytes=NODE_PROJECT_FILE_LIMIT,
        )
        await self._control.record_progress(
            self._lease,
            AgentProgress(
                message=f"Patched {result.path}",
                draft_node_id=draft_node_id,
            ),
        )
        return result

    async def run_command(
        self,
        draft_node_id: UUID,
        argv: tuple[str, ...],
        timeout_seconds: float,
    ) -> SandboxExecutionResult:
        self._invalidate_validation(draft_node_id)
        return await self._execute(
            draft_node_id,
            argv,
            timeout_seconds,
            network_mode=SandboxNetworkMode.BLOCKED,
        )

    async def _execute(
        self,
        draft_node_id: UUID,
        argv: tuple[str, ...],
        timeout_seconds: float,
        *,
        network_mode: SandboxNetworkMode,
    ) -> SandboxExecutionResult:
        self._require_target(draft_node_id)
        result = await self._sandbox.execute(
            self._session,
            SandboxExecutionRequest(
                argv=argv,
                cwd=self._node_root(draft_node_id),
                timeout_seconds=timeout_seconds,
                max_output_bytes=NODE_COMMAND_OUTPUT_LIMIT,
                network_mode=network_mode,
            ),
        )
        await self._control.record_progress(
            self._lease,
            AgentProgress(
                message=(f"Command {argv[0]!r} exited with status {result.exit_code}"),
                draft_node_id=draft_node_id,
            ),
        )
        return result

    async def uv_add(
        self,
        draft_node_id: UUID,
        packages: tuple[str, ...],
    ) -> SandboxExecutionResult:
        requirements = validated_package_requirements(packages)
        self._invalidate_validation(draft_node_id)
        return await self._execute(
            draft_node_id,
            ("uv", "add", "--", *requirements),
            180.0,
            network_mode=SandboxNetworkMode.PACKAGE_INDEX,
        )

    async def uv_lock(self, draft_node_id: UUID) -> SandboxExecutionResult:
        self._invalidate_validation(draft_node_id)
        locked = await self._execute(
            draft_node_id,
            ("uv", "lock"),
            180.0,
            network_mode=SandboxNetworkMode.PACKAGE_INDEX,
        )
        if locked.exit_code != 0:
            return locked
        checked = await self._execute(
            draft_node_id,
            ("uv", "lock", "--check"),
            60.0,
            network_mode=SandboxNetworkMode.BLOCKED,
        )
        if checked.exit_code == 0:
            self._validated_steps[draft_node_id] = {"lock"}
        return checked

    async def uv_sync(self, draft_node_id: UUID) -> SandboxExecutionResult:
        self._validated_steps[draft_node_id].discard("sync")
        self._validated_steps[draft_node_id].discard("test")
        result = await self._execute(
            draft_node_id,
            ("uv", "sync", "--locked"),
            300.0,
            network_mode=SandboxNetworkMode.PACKAGE_INDEX,
        )
        if result.exit_code == 0:
            self._validated_steps[draft_node_id].add("sync")
        return result

    async def uv_test(self, draft_node_id: UUID) -> SandboxExecutionResult:
        self._validated_steps[draft_node_id].discard("test")
        result = await self._execute(
            draft_node_id,
            ("uv", "run", "--locked", "pytest", "-q"),
            300.0,
            network_mode=SandboxNetworkMode.BLOCKED,
        )
        if result.exit_code == 0:
            self._validated_steps[draft_node_id].add("test")
        return result

    async def request_capabilities(
        self,
        draft_node_id: UUID,
        capabilities: CapabilityManifest,
        rationale: str,
    ) -> CapabilityProposalReceipt:
        self._require_target(draft_node_id)
        return await self._control.request_capabilities(
            self._lease,
            CapabilityProposal(
                draft_node_id=draft_node_id,
                capabilities=capabilities,
                rationale=rationale,
            ),
        )

    async def propose_release(
        self,
        draft_node_id: UUID,
        summary: str,
    ) -> ReleaseProposalReceipt:
        self._require_target(draft_node_id)
        missing_steps = {"lock", "sync", "test"} - self._validated_steps[draft_node_id]
        if missing_steps:
            missing = ", ".join(sorted(missing_steps))
            raise AgentRuntimeError(
                f"Draft node {draft_node_id} cannot be proposed until these current "
                f"validation steps pass: {missing}"
            )
        archive = await self._sandbox.export_directory(
            self._session,
            path=self._node_root(draft_node_id),
            max_bytes=67_108_864,
        )
        source_bundle = inspect_node_source_bundle(archive)
        bundle_index = read_source_bundle(archive.data)
        definition = GeneratedNodeSourceDefinition.model_validate_json(
            bundle_index.file("node.json").content
        )
        if definition.capabilities.secret_refs:
            raise AgentRuntimeError(
                "Generated-node secret capabilities are not executable in this slice"
            )
        if definition.capabilities.object_store:
            raise AgentRuntimeError(
                "Generated-node object-store capabilities are not executable in this slice"
            )
        if definition.capabilities.outbound_http_origins:
            raise AgentRuntimeError(
                "Generated-node outbound HTTP capabilities require the isolated "
                "egress proxy and are not executable in this slice"
            )
        verification = await self._verifier.verify(
            lease=self._lease,
            source_bundle=source_bundle,
            profile_id=self._profile_id,
        )
        receipt = await self._control.propose_release(
            self._lease,
            ReleaseProposal(
                draft_node_id=draft_node_id,
                manifest=definition.manifest,
                capabilities=definition.capabilities,
                source_bundle=source_bundle,
                verification=verification,
                summary=summary,
            ),
        )
        self._proposed_release_ids.add(draft_node_id)
        return receipt

    async def bootstrap_project(
        self,
        draft_node_id: UUID,
        manifest: GeneratedNodeManifest,
    ) -> None:
        self._require_target(draft_node_id)
        pyproject = (
            "[project]\n"
            f'name = "grafy-node-{str(draft_node_id)}"\n'
            'version = "0.1.0"\n'
            'requires-python = ">=3.12,<3.13"\n'
            "dependencies = []\n\n"
            "[dependency-groups]\n"
            'dev = ["pytest>=8.4,<9"]\n\n'
            "[tool.pytest.ini_options]\n"
            'testpaths = ["tests"]\n'
        )
        definition = GeneratedNodeSourceDefinition(
            manifest=manifest,
            capabilities=CapabilityManifest(),
        )
        files = (
            ("pyproject.toml", pyproject),
            ("node.json", definition.model_dump_json(indent=2) + "\n"),
            (
                "src/node.py",
                "def run(inputs: dict[str, object]) -> dict[str, object]:\n    raise NotImplementedError\n",
            ),
            (
                "tests/test_node.py",
                'def test_node_is_implemented() -> None:\n    raise AssertionError("Agent must replace this placeholder test")\n',
            ),
        )
        for path, content in files:
            full_path = self._node_path(draft_node_id, path)
            try:
                await self._sandbox.read_text(
                    self._session,
                    path=full_path,
                    max_bytes=NODE_PROJECT_FILE_LIMIT,
                )
            except FileNotFoundError:
                await self._sandbox.write_text(
                    self._session,
                    path=full_path,
                    content=content,
                    max_bytes=NODE_PROJECT_FILE_LIMIT,
                )

    def _node_path(self, draft_node_id: UUID, path: str) -> str:
        relative = normalized_relative_path(path, label="Node project path")
        return f"{self._node_root(draft_node_id)}/{relative}"

    def _node_root(self, draft_node_id: UUID) -> str:
        self._require_target(draft_node_id)
        return f"nodes/{draft_node_id}"

    def _require_target(self, draft_node_id: UUID) -> None:
        if draft_node_id not in self._target_ids:
            raise AgentRuntimeError(
                f"Draft node {draft_node_id} is not assigned to run {self._lease.run_id}"
            )

    def _invalidate_validation(self, draft_node_id: UUID) -> None:
        self._require_target(draft_node_id)
        self._validated_steps[draft_node_id].clear()
        self._proposed_release_ids.discard(draft_node_id)


async def read_node_file(
    ctx: RunContext[NodeToolDependencies],
    draft_node_id: UUID,
    path: str,
) -> SandboxFileContents:
    """Read one UTF-8 file under a draft node's isolated project directory."""
    return await ctx.deps.tools.read_file(draft_node_id, path)


async def write_node_file(
    ctx: RunContext[NodeToolDependencies],
    draft_node_id: UUID,
    path: str,
    content: str,
) -> SandboxFileChange:
    """Create or replace one UTF-8 file under a draft node project."""
    return await ctx.deps.tools.write_file(draft_node_id, path, content)


async def apply_node_patch(
    ctx: RunContext[NodeToolDependencies],
    draft_node_id: UUID,
    path: str,
    expected: str,
    replacement: str,
) -> SandboxPatchResult:
    """Atomically replace one exact text occurrence in a draft node file."""
    return await ctx.deps.tools.apply_patch(
        draft_node_id,
        path,
        expected,
        replacement,
    )


async def run_node_command(
    ctx: RunContext[NodeToolDependencies],
    draft_node_id: UUID,
    argv: list[str],
    timeout_seconds: float = 60.0,
) -> SandboxExecutionResult:
    """Run an argv command in a draft node project with time and output bounds."""
    return await ctx.deps.tools.run_command(
        draft_node_id,
        tuple(argv),
        timeout_seconds,
    )


async def uv_add(
    ctx: RunContext[NodeToolDependencies],
    draft_node_id: UUID,
    packages: list[str],
) -> SandboxExecutionResult:
    """Add validated Python requirements to one node project using uv."""
    return await ctx.deps.tools.uv_add(draft_node_id, tuple(packages))


async def uv_lock(
    ctx: RunContext[NodeToolDependencies],
    draft_node_id: UUID,
) -> SandboxExecutionResult:
    """Resolve and write the node project's uv.lock file."""
    return await ctx.deps.tools.uv_lock(draft_node_id)


async def uv_sync(
    ctx: RunContext[NodeToolDependencies],
    draft_node_id: UUID,
) -> SandboxExecutionResult:
    """Install exactly the node project's locked dependency graph."""
    return await ctx.deps.tools.uv_sync(draft_node_id)


async def uv_test(
    ctx: RunContext[NodeToolDependencies],
    draft_node_id: UUID,
) -> SandboxExecutionResult:
    """Run the node project's pytest suite against its locked environment."""
    return await ctx.deps.tools.uv_test(draft_node_id)


async def request_node_capabilities(
    ctx: RunContext[NodeToolDependencies],
    draft_node_id: UUID,
    capabilities: CapabilityManifest,
    rationale: str,
) -> CapabilityProposalReceipt:
    """Request user approval for the node's least-privilege runtime capabilities."""
    return await ctx.deps.tools.request_capabilities(
        draft_node_id,
        capabilities,
        rationale,
    )


async def propose_node_release(
    ctx: RunContext[NodeToolDependencies],
    draft_node_id: UUID,
    summary: str,
) -> ReleaseProposalReceipt:
    """Submit tested source and node.json for explicit user publication review."""
    return await ctx.deps.tools.propose_release(draft_node_id, summary)


def node_authoring_toolset() -> FunctionToolset[NodeToolDependencies]:
    return FunctionToolset(
        tools=[
            read_node_file,
            write_node_file,
            apply_node_patch,
            run_node_command,
            uv_add,
            uv_lock,
            uv_sync,
            uv_test,
            request_node_capabilities,
            propose_node_release,
        ],
        instructions=(
            "Each draft has a separate project under the shared environment. "
            "Use only the draft_node_id values assigned to this run. Keep node.json "
            "aligned with the implementation. Use uv for every dependency change. "
            "Before proposing a release, run uv_lock, uv_sync, and uv_test and inspect "
            "every non-zero exit. Request only capabilities the code actually needs."
        ),
        sequential=True,
    )


__all__ = [
    "NODE_COMMAND_OUTPUT_LIMIT",
    "NODE_PROJECT_FILE_LIMIT",
    "NodeAuthoringTools",
    "NodeToolDependencies",
    "node_authoring_toolset",
]
