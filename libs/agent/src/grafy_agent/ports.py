from typing import Protocol
from uuid import UUID

from grafy_agent.models import (
    AgentLease,
    AgentProgress,
    CapabilityProposal,
    CapabilityProposalReceipt,
    CodingAgentRequest,
    CodingAgentResult,
    NodeSourceBundle,
    ReleaseProposal,
    ReleaseProposalReceipt,
    SandboxArchive,
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxExecutionAuthority,
    SandboxFileChange,
    SandboxFileContents,
    SandboxImportResult,
    SandboxPatchResult,
    SandboxRuntimeArtifact,
    SandboxSession,
    SandboxTerminationResult,
    SandboxWorkspace,
    SourceBundleVerification,
)
from grafy_core.domain.agent_authoring import RuntimeLimits


class SandboxWorkspacePort(Protocol):
    """Provider-neutral access to one reusable agent environment."""

    async def ensure_workspace(
        self,
        *,
        environment_id: UUID,
        provider_environment_id: str | None,
        profile_id: str,
    ) -> SandboxWorkspace: ...

    async def open_session(
        self,
        workspace: SandboxWorkspace,
        authority: SandboxExecutionAuthority,
    ) -> SandboxSession:
        """Fence all subsequent mutations to one worker lease."""
        ...

    async def terminate_session(
        self,
        session: SandboxSession,
    ) -> SandboxTerminationResult:
        """Revoke future mutations and kill/reap every active execution."""
        ...

    async def terminate_execution(
        self,
        workspace: SandboxWorkspace,
        *,
        execution_id: UUID,
    ) -> SandboxTerminationResult:
        """Idempotently revoke a stable execution after worker/process recovery."""
        ...

    async def destroy_workspace(self, workspace: SandboxWorkspace) -> None:
        """Destroy a clean-room or runtime workspace after its bounded use."""
        ...

    async def freeze_workspace(
        self,
        session: SandboxSession,
        *,
        artifact_name: str,
        source_digest: str,
    ) -> SandboxRuntimeArtifact:
        """Freeze a verified clean-room workspace for offline execution."""
        ...

    async def create_runtime_workspace(
        self,
        *,
        environment_id: UUID,
        artifact: SandboxRuntimeArtifact,
        limits: RuntimeLimits,
    ) -> SandboxWorkspace:
        """Start an isolated workspace from an exact immutable runtime artifact."""
        ...

    async def read_text(
        self,
        session: SandboxSession,
        *,
        path: str,
        max_bytes: int,
    ) -> SandboxFileContents: ...

    async def write_text(
        self,
        session: SandboxSession,
        *,
        path: str,
        content: str,
        max_bytes: int,
    ) -> SandboxFileChange: ...

    async def replace_text(
        self,
        session: SandboxSession,
        *,
        path: str,
        expected: str,
        replacement: str,
        max_bytes: int,
    ) -> SandboxPatchResult: ...

    async def execute(
        self,
        session: SandboxSession,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult: ...

    async def export_directory(
        self,
        session: SandboxSession,
        *,
        path: str,
        max_bytes: int,
    ) -> SandboxArchive: ...

    async def import_directory(
        self,
        session: SandboxSession,
        *,
        path: str,
        archive: SandboxArchive,
    ) -> SandboxImportResult: ...


class AgentAuthoringControlPort(Protocol):
    """Durable authoring operations callable from model tools."""

    async def record_progress(
        self,
        lease: AgentLease,
        progress: AgentProgress,
    ) -> None: ...

    async def cancellation_requested(self, lease: AgentLease) -> bool: ...

    async def request_capabilities(
        self,
        lease: AgentLease,
        proposal: CapabilityProposal,
    ) -> CapabilityProposalReceipt: ...

    async def propose_release(
        self,
        lease: AgentLease,
        proposal: ReleaseProposal,
    ) -> ReleaseProposalReceipt: ...


class CodingAgentPort(Protocol):
    async def run(
        self,
        *,
        request: CodingAgentRequest,
        lease: AgentLease,
        session: SandboxSession,
        profile_id: str,
        sandbox: SandboxWorkspacePort,
        verifier: "SourceBundleVerifierPort",
        control: AgentAuthoringControlPort,
    ) -> CodingAgentResult: ...


class SourceBundleVerifierPort(Protocol):
    async def verify(
        self,
        *,
        lease: AgentLease,
        source_bundle: NodeSourceBundle,
        profile_id: str,
    ) -> SourceBundleVerification:
        """Test the exact immutable bundle in a clean provider environment."""
        ...


__all__ = [
    "AgentAuthoringControlPort",
    "CodingAgentPort",
    "SandboxWorkspacePort",
    "SourceBundleVerifierPort",
]
