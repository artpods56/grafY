"""Clean-room attestation for immutable generated-node source bundles."""

from hashlib import sha256
from uuid import uuid4

from grafy_agent.bundles import inspect_node_source_bundle
from grafy_agent.errors import AgentRuntimeError, bounded_error_detail
from grafy_agent.models import (
    AgentLease,
    NodeSourceBundle,
    SandboxExecutionAuthority,
    SandboxExecutionRequest,
    SandboxNetworkMode,
    SourceBundleVerification,
)
from grafy_agent.ports import SandboxWorkspacePort


_RESTORE_REVIEWED_SOURCE = """import pathlib,shutil
root=pathlib.Path('.')
for name in ('pyproject.toml','uv.lock','node.json','src','tests'):
 path=root/name
 if path.is_symlink() or path.is_file(): path.unlink(missing_ok=True)
 elif path.exists(): shutil.rmtree(path)
"""


class CleanSandboxSourceBundleVerifier:
    """Test exact source, then independently rebuild its offline runtime artifact."""

    def __init__(self, sandbox: SandboxWorkspacePort) -> None:
        self._sandbox = sandbox

    async def verify(
        self,
        *,
        lease: AgentLease,
        source_bundle: NodeSourceBundle,
        profile_id: str,
    ) -> SourceBundleVerification:
        test_workspace = await self._sandbox.ensure_workspace(
            environment_id=uuid4(),
            provider_environment_id=None,
            profile_id=profile_id,
        )
        test_session = None
        try:
            test_session = await self._sandbox.open_session(
                test_workspace,
                SandboxExecutionAuthority(
                    execution_id=uuid4(),
                    token=uuid4(),
                    fencing_token=1,
                ),
            )
            await self._sandbox.import_directory(
                test_session,
                path="node",
                archive=source_bundle.archive,
            )
            lock_check = await self._sandbox.execute(
                test_session,
                SandboxExecutionRequest(
                    argv=("uv", "lock", "--check"),
                    cwd="node",
                    timeout_seconds=60,
                    max_output_bytes=1_048_576,
                    network_mode=SandboxNetworkMode.BLOCKED,
                ),
            )
            if lock_check.exit_code != 0:
                raise AgentRuntimeError(
                    "Exact source bundle failed uv lock --check in a clean sandbox: "
                    f"{bounded_error_detail(lock_check.stderr or lock_check.stdout)}"
                )
            sync = await self._sandbox.execute(
                test_session,
                SandboxExecutionRequest(
                    argv=("uv", "sync", "--locked", "--no-build"),
                    cwd="node",
                    timeout_seconds=300,
                    max_output_bytes=1_048_576,
                    network_mode=SandboxNetworkMode.PACKAGE_INDEX,
                ),
            )
            if sync.exit_code != 0:
                raise AgentRuntimeError(
                    "Exact source bundle failed locked sync in a clean sandbox: "
                    f"{bounded_error_detail(sync.stderr or sync.stdout)}"
                )
            tests = await self._sandbox.execute(
                test_session,
                SandboxExecutionRequest(
                    argv=("uv", "run", "--locked", "pytest", "-q"),
                    cwd="node",
                    timeout_seconds=300,
                    max_output_bytes=1_048_576,
                    network_mode=SandboxNetworkMode.BLOCKED,
                ),
            )
            if tests.exit_code != 0:
                raise AgentRuntimeError(
                    "Exact source bundle tests failed in a clean sandbox: "
                    f"{bounded_error_detail(tests.stderr or tests.stdout)}"
                )
        finally:
            try:
                if test_session is not None:
                    await self._sandbox.terminate_session(test_session)
            finally:
                await self._sandbox.destroy_workspace(test_workspace)

        # Never preserve a byte from the workspace in which untrusted tests ran.
        # Build a second runtime workspace from the reviewed bundle and exact lock.
        runtime_workspace = await self._sandbox.ensure_workspace(
            environment_id=uuid4(),
            provider_environment_id=None,
            profile_id=profile_id,
        )
        build_session = None
        freeze_session = None
        try:
            build_session = await self._sandbox.open_session(
                runtime_workspace,
                SandboxExecutionAuthority(
                    execution_id=uuid4(),
                    token=uuid4(),
                    fencing_token=1,
                ),
            )
            await self._sandbox.import_directory(
                build_session,
                path="node",
                archive=source_bundle.archive,
            )
            final_lock_check = await self._sandbox.execute(
                build_session,
                SandboxExecutionRequest(
                    argv=("uv", "lock", "--check"),
                    cwd="node",
                    timeout_seconds=60,
                    max_output_bytes=1_048_576,
                    network_mode=SandboxNetworkMode.BLOCKED,
                ),
            )
            if final_lock_check.exit_code != 0:
                raise AgentRuntimeError(
                    "Runtime rebuild failed uv lock --check: "
                    f"{bounded_error_detail(final_lock_check.stderr or final_lock_check.stdout)}"
                )
            final_sync = await self._sandbox.execute(
                build_session,
                SandboxExecutionRequest(
                    argv=("uv", "sync", "--locked", "--no-build"),
                    cwd="node",
                    timeout_seconds=300,
                    max_output_bytes=1_048_576,
                    network_mode=SandboxNetworkMode.PACKAGE_INDEX,
                ),
            )
            if final_sync.exit_code != 0:
                raise AgentRuntimeError(
                    "Runtime rebuild failed locked sync: "
                    f"{bounded_error_detail(final_sync.stderr or final_sync.stdout)}"
                )
            await self._sandbox.terminate_session(build_session)
            build_session = None

            freeze_session = await self._sandbox.open_session(
                runtime_workspace,
                SandboxExecutionAuthority(
                    execution_id=uuid4(),
                    token=uuid4(),
                    fencing_token=1,
                ),
            )
            restored = await self._sandbox.execute(
                freeze_session,
                SandboxExecutionRequest(
                    argv=("python3", "-c", _RESTORE_REVIEWED_SOURCE),
                    cwd="node",
                    timeout_seconds=30,
                    max_output_bytes=65_536,
                    network_mode=SandboxNetworkMode.BLOCKED,
                ),
            )
            if restored.exit_code != 0:
                raise AgentRuntimeError(
                    "Could not reconstruct the reviewed source tree: "
                    f"{bounded_error_detail(restored.stderr or restored.stdout)}"
                )
            await self._sandbox.import_directory(
                freeze_session,
                path="node",
                archive=source_bundle.archive,
            )
            reexported = await self._sandbox.export_directory(
                freeze_session,
                path="node",
                max_bytes=67_108_864,
            )
            reconstructed = inspect_node_source_bundle(reexported)
            if reconstructed.source_digest != source_bundle.source_digest:
                raise AgentRuntimeError(
                    "Clean runtime source differs from the exact reviewed bundle"
                )
            artifact_identity = sha256(
                (
                    f"{source_bundle.source_digest}:"
                    f"{runtime_workspace.runtime_image_digest}:"
                    f"{runtime_workspace.profile_digest}"
                ).encode("ascii")
            ).hexdigest()
            artifact = await self._sandbox.freeze_workspace(
                freeze_session,
                artifact_name=f"grafy-node-{artifact_identity}",
                source_digest=source_bundle.source_digest,
            )
            return SourceBundleVerification(
                source_digest=source_bundle.source_digest,
                lock_digest=source_bundle.lock_digest,
                tests_digest=source_bundle.tests_digest,
                implementation_digest=source_bundle.implementation_digest,
                runtime_image_digest=runtime_workspace.runtime_image_digest,
                profile_digest=runtime_workspace.profile_digest,
                runtime_artifact=artifact,
            )
        finally:
            try:
                if freeze_session is not None:
                    await self._sandbox.terminate_session(freeze_session)
                elif build_session is not None:
                    await self._sandbox.terminate_session(build_session)
            finally:
                await self._sandbox.destroy_workspace(runtime_workspace)


__all__ = ["CleanSandboxSourceBundleVerifier"]
