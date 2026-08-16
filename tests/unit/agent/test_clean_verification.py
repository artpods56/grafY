from gzip import GzipFile
from hashlib import sha256
from io import BytesIO
import tarfile
from uuid import UUID

import pytest

from grafy_agent.bundles import inspect_node_source_bundle
from grafy_agent.models import (
    AgentLease,
    SandboxArchive,
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxRuntimeArtifact,
    SandboxSession,
    SandboxTerminationResult,
)
from grafy_agent.sandbox.memory import InMemorySandboxWorkspace
from grafy_agent.verification import CleanSandboxSourceBundleVerifier


WORKSPACE_ID = UUID("50000000-0000-0000-0000-000000000001")
THREAD_ID = UUID("50000000-0000-0000-0000-000000000002")
ENVIRONMENT_ID = UUID("50000000-0000-0000-0000-000000000003")
RUN_ID = UUID("50000000-0000-0000-0000-000000000004")
DRAFT_ID = UUID("50000000-0000-0000-0000-000000000005")
TOKEN = UUID("50000000-0000-0000-0000-000000000006")
REVIEWED_SOURCE = "def run(inputs):\n    return {'result': inputs['value']}\n"


def reviewed_archive() -> SandboxArchive:
    files = (
        ("node.json", b"{}\n"),
        ("pyproject.toml", b"[project]\nname='verified-node'\n"),
        ("src/node.py", REVIEWED_SOURCE.encode()),
        ("tests/test_node.py", b"def test_node(): assert True\n"),
        ("uv.lock", b"version = 1\n"),
    )
    raw = BytesIO()
    with GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as bundle:
            for path, content in files:
                member = tarfile.TarInfo(path)
                member.size = len(content)
                member.mtime = 0
                member.uid = 0
                member.gid = 0
                member.mode = 0o644
                bundle.addfile(member, BytesIO(content))
    data = raw.getvalue()
    return SandboxArchive(
        data=data,
        sha256=sha256(data).hexdigest(),
        byte_count=len(data),
    )


class MutatingTestSandbox(InMemorySandboxWorkspace):
    def __init__(self) -> None:
        super().__init__()
        self.test_mutated_source = False
        self.frozen_source: str | None = None
        self.frozen_runtime: str | None = None
        self.terminated_sessions: list[str] = []

    async def execute(
        self,
        session: SandboxSession,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        if request.argv == ("uv", "sync", "--locked", "--no-build"):
            await self.write_text(
                session,
                path="node/.venv/bin/python",
                content="locked clean runtime",
                max_bytes=1_024,
            )
        if request.argv == ("uv", "run", "--locked", "pytest", "-q"):
            await self.write_text(
                session,
                path="node/src/node.py",
                content="def run(inputs): return {'result': 'tampered'}\n",
                max_bytes=1_024,
            )
            self.test_mutated_source = True
            await self.write_text(
                session,
                path="node/.venv/bin/python",
                content="poisoned by tests",
                max_bytes=1_024,
            )
        return SandboxExecutionResult(
            exit_code=0,
            stdout="ok",
            stderr="",
            duration_ms=1,
        )

    async def freeze_workspace(
        self,
        session: SandboxSession,
        *,
        artifact_name: str,
        source_digest: str,
    ) -> SandboxRuntimeArtifact:
        source = await self.read_text(
            session,
            path="node/src/node.py",
            max_bytes=1_024,
        )
        self.frozen_source = source.content
        runtime = await self.read_text(
            session,
            path="node/.venv/bin/python",
            max_bytes=1_024,
        )
        self.frozen_runtime = runtime.content
        return await super().freeze_workspace(
            session,
            artifact_name=artifact_name,
            source_digest=source_digest,
        )

    async def terminate_session(
        self,
        session: SandboxSession,
    ) -> SandboxTerminationResult:
        self.terminated_sessions.append(session.provider_session_id)
        return await super().terminate_session(session)


@pytest.mark.asyncio
async def test_verifier_reconstructs_reviewed_source_after_mutating_tests() -> None:
    sandbox = MutatingTestSandbox()
    source_bundle = inspect_node_source_bundle(reviewed_archive())
    lease = AgentLease(
        workspace_id=WORKSPACE_ID,
        thread_id=THREAD_ID,
        environment_id=ENVIRONMENT_ID,
        run_id=RUN_ID,
        lease_token=TOKEN,
        fencing_token=1,
        target_draft_ids=(DRAFT_ID,),
    )

    verification = await CleanSandboxSourceBundleVerifier(sandbox).verify(
        lease=lease,
        source_bundle=source_bundle,
        profile_id="python-3.12",
    )

    assert sandbox.test_mutated_source
    assert sandbox.frozen_source == REVIEWED_SOURCE
    assert sandbox.frozen_runtime == "locked clean runtime"
    assert verification.source_digest == source_bundle.source_digest
    assert verification.runtime_artifact.reference.startswith("grafy-node-")
    assert len(set(sandbox.terminated_sessions)) == 3
