import asyncio
from uuid import UUID

import pytest

from grafy_agent.models import (
    SandboxExecutionAuthority,
    SandboxExecutionRequest,
    SandboxExecutionResult,
)
from grafy_agent.sandbox.memory import InMemorySandboxWorkspace


ENVIRONMENT_ONE = UUID("10000000-0000-0000-0000-000000000001")
ENVIRONMENT_TWO = UUID("10000000-0000-0000-0000-000000000002")
EXECUTION_ID = UUID("10000000-0000-0000-0000-000000000003")
TOKEN = UUID("10000000-0000-0000-0000-000000000004")


@pytest.mark.asyncio
async def test_provider_session_identity_isolated_by_environment() -> None:
    sandbox = InMemorySandboxWorkspace()
    first = await sandbox.ensure_workspace(
        environment_id=ENVIRONMENT_ONE,
        provider_environment_id=None,
        profile_id="python-3.12",
    )
    second = await sandbox.ensure_workspace(
        environment_id=ENVIRONMENT_TWO,
        provider_environment_id=None,
        profile_id="python-3.12",
    )
    authority = SandboxExecutionAuthority(
        execution_id=EXECUTION_ID,
        token=TOKEN,
        fencing_token=1,
    )

    first_session = await sandbox.open_session(first, authority)
    second_session = await sandbox.open_session(second, authority)
    await sandbox.terminate_session(first_session)
    written = await sandbox.write_text(
        second_session,
        path="node/value.txt",
        content="still active",
        max_bytes=128,
    )

    assert first_session.provider_session_id != second_session.provider_session_id
    assert written.byte_count == 12


@pytest.mark.asyncio
async def test_termination_cancels_active_command_before_session_can_be_reused() -> (
    None
):
    sandbox = InMemorySandboxWorkspace()
    workspace = await sandbox.ensure_workspace(
        environment_id=ENVIRONMENT_ONE,
        provider_environment_id=None,
        profile_id="python-3.12",
    )
    session = await sandbox.open_session(
        workspace,
        SandboxExecutionAuthority(
            execution_id=EXECUTION_ID,
            token=TOKEN,
            fencing_token=1,
        ),
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def blocking_command(
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        del request
        started.set()
        await release.wait()
        return SandboxExecutionResult(
            exit_code=0,
            stdout="late mutation",
            stderr="",
            duration_ms=1,
        )

    sandbox.register_command(
        environment_id=ENVIRONMENT_ONE,
        cwd="node",
        argv=("python", "mutate.py"),
        handler=blocking_command,
    )
    execution = asyncio.create_task(
        sandbox.execute(
            session,
            SandboxExecutionRequest(
                argv=("python", "mutate.py"),
                cwd="node",
            ),
        )
    )
    await started.wait()

    termination = await sandbox.terminate_execution(
        workspace,
        execution_id=EXECUTION_ID,
    )

    assert termination.terminated_execution_count == 1
    assert termination.revocation_verified
    with pytest.raises(asyncio.CancelledError):
        await execution
