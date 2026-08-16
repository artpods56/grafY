from datetime import datetime
from typing import cast
from uuid import UUID

import pytest

from grafy_agent.models import (
    AgentLease,
    CodingAgentRequest,
    CodingAgentResult,
    SandboxSession,
    SandboxTerminationResult,
    SandboxWorkspace,
)
from grafy_agent.ports import (
    AgentAuthoringControlPort,
    SandboxWorkspacePort,
    SourceBundleVerifierPort,
)
from grafy_agent.sandbox.memory import InMemorySandboxWorkspace
from grafy_core.application.agent_authoring import AgentAuthoringService
from grafy_core.domain.agent_authoring import (
    AgentEnvironment,
    AgentEnvironmentStatus,
    AgentRun,
    AgentRunStatus,
)
from grafy_core.ports.storage import FileStoragePort

from grafy_agent_worker.settings import AgentWorkerSettings
from grafy_agent_worker.worker import AgentWorker


WORKSPACE_ID = UUID("60000000-0000-0000-0000-000000000001")
ENVIRONMENT_ID = UUID("60000000-0000-0000-0000-000000000002")
THREAD_ID = UUID("60000000-0000-0000-0000-000000000003")
RUN_ID = UUID("60000000-0000-0000-0000-000000000004")
DRAFT_ID = UUID("60000000-0000-0000-0000-000000000005")


class CancellationService:
    def __init__(self, run: AgentRun, environment: AgentEnvironment) -> None:
        self.run = run
        self.environment = environment
        self.operations: list[str] = []

    async def list_cancelling_run_keys(
        self,
        *,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        del limit
        return [(WORKSPACE_ID, RUN_ID)]

    async def list_interrupting_run_keys(
        self,
        *,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        del limit
        return []

    async def list_expired_running_run_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        del when, limit
        return []

    async def list_provisionable_environment_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        del when, limit
        return []

    async def list_claimable_run_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        del when, limit
        return []

    async def get_run(self, workspace_id: UUID, run_id: UUID) -> AgentRun:
        assert (workspace_id, run_id) == (WORKSPACE_ID, RUN_ID)
        return self.run

    async def get_environment(
        self,
        workspace_id: UUID,
        environment_id: UUID,
    ) -> AgentEnvironment:
        assert (workspace_id, environment_id) == (WORKSPACE_ID, ENVIRONMENT_ID)
        return self.environment

    async def confirm_run_cancelled(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        revocation_fencing_token: int,
    ) -> AgentRun:
        assert (workspace_id, run_id) == (WORKSPACE_ID, RUN_ID)
        self.operations.append("confirm")
        self.run.confirm_cancelled(revocation_fencing_token)
        return self.run


class InterruptionService(CancellationService):
    async def list_cancelling_run_keys(
        self,
        *,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        del limit
        return []

    async def list_interrupting_run_keys(
        self,
        *,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        del limit
        return [(WORKSPACE_ID, RUN_ID)]

    async def confirm_run_interrupted(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        revocation_fencing_token: int,
    ) -> AgentRun:
        assert (workspace_id, run_id) == (WORKSPACE_ID, RUN_ID)
        self.operations.append("confirm")
        self.run.confirm_interrupted(revocation_fencing_token)
        return self.run


class RecordingMemorySandbox(InMemorySandboxWorkspace):
    def __init__(self, operations: list[str]) -> None:
        super().__init__()
        self._operations = operations

    async def terminate_execution(
        self,
        workspace: SandboxWorkspace,
        *,
        execution_id: UUID,
    ) -> SandboxTerminationResult:
        self._operations.append("kill")
        return await super().terminate_execution(
            workspace,
            execution_id=execution_id,
        )


class FailsFirstTerminationSandbox(RecordingMemorySandbox):
    def __init__(self, operations: list[str]) -> None:
        super().__init__(operations)
        self._failure_pending = True

    async def terminate_execution(
        self,
        workspace: SandboxWorkspace,
        *,
        execution_id: UUID,
    ) -> SandboxTerminationResult:
        self._operations.append("kill")
        if self._failure_pending:
            self._failure_pending = False
            raise RuntimeError("provider termination was interrupted")
        return await InMemorySandboxWorkspace.terminate_execution(
            self,
            workspace,
            execution_id=execution_id,
        )


class UnusedCodingAgent:
    async def run(
        self,
        *,
        request: CodingAgentRequest,
        lease: AgentLease,
        session: SandboxSession,
        profile_id: str,
        sandbox: SandboxWorkspacePort,
        verifier: SourceBundleVerifierPort,
        control: AgentAuthoringControlPort,
    ) -> CodingAgentResult:
        del request, lease, session, profile_id, sandbox, verifier, control
        raise AssertionError("Cancellation recovery must not start the coding agent")


@pytest.mark.asyncio
async def test_cancellation_kills_provider_before_releasing_database_writer() -> None:
    environment = AgentEnvironment(
        workspace_id=WORKSPACE_ID,
        name="Memory",
        profile_id="python-3.12",
        provider="memory",
        status=AgentEnvironmentStatus.READY,
        provider_environment_id=f"memory-{ENVIRONMENT_ID}",
        active_run_id=RUN_ID,
        id=ENVIRONMENT_ID,
    )
    run = AgentRun(
        workspace_id=WORKSPACE_ID,
        thread_id=THREAD_ID,
        environment_id=ENVIRONMENT_ID,
        target_draft_ids=(DRAFT_ID,),
        instructions="Implement the node",
        idempotency_key="cancel-test",
        request_digest="1" * 64,
        status=AgentRunStatus.CANCELLING,
        id=RUN_ID,
        fencing_token=2,
    )
    service = CancellationService(run, environment)
    sandbox = RecordingMemorySandbox(service.operations)
    await sandbox.ensure_workspace(
        environment_id=ENVIRONMENT_ID,
        provider_environment_id=environment.provider_environment_id,
        profile_id=environment.profile_id,
    )
    worker = AgentWorker(
        settings=AgentWorkerSettings(
            worker_id="worker-recovery-test",
            lease_seconds=60,
            heartbeat_seconds=10,
        ),
        service=cast(AgentAuthoringService, service),
        coding_agent=UnusedCodingAgent(),
        sandboxes={"memory": sandbox},
        storage=cast(FileStoragePort, object()),
    )

    handled = await worker.poll_once()

    assert handled
    assert service.operations == ["kill", "confirm"]
    assert run.status is AgentRunStatus.CANCELLED


@pytest.mark.asyncio
async def test_interruption_retries_provider_kill_before_releasing_writer() -> None:
    environment = AgentEnvironment(
        workspace_id=WORKSPACE_ID,
        name="Memory",
        profile_id="python-3.12",
        provider="memory",
        status=AgentEnvironmentStatus.READY,
        provider_environment_id=f"memory-{ENVIRONMENT_ID}",
        active_run_id=RUN_ID,
        id=ENVIRONMENT_ID,
    )
    run = AgentRun(
        workspace_id=WORKSPACE_ID,
        thread_id=THREAD_ID,
        environment_id=ENVIRONMENT_ID,
        target_draft_ids=(DRAFT_ID,),
        instructions="Implement the node",
        idempotency_key="interruption-test",
        request_digest="2" * 64,
        status=AgentRunStatus.INTERRUPTING,
        id=RUN_ID,
        fencing_token=2,
    )
    service = InterruptionService(run, environment)
    sandbox = FailsFirstTerminationSandbox(service.operations)
    await sandbox.ensure_workspace(
        environment_id=ENVIRONMENT_ID,
        provider_environment_id=environment.provider_environment_id,
        profile_id=environment.profile_id,
    )
    worker = AgentWorker(
        settings=AgentWorkerSettings(
            worker_id="worker-interruption-test",
            lease_seconds=60,
            heartbeat_seconds=10,
        ),
        service=cast(AgentAuthoringService, service),
        coding_agent=UnusedCodingAgent(),
        sandboxes={"memory": sandbox},
        storage=cast(FileStoragePort, object()),
    )

    assert await worker.poll_once()
    assert service.operations == ["kill"]
    assert run.status is AgentRunStatus.INTERRUPTING
    assert environment.active_run_id == RUN_ID

    assert await worker.poll_once()
    assert service.operations == ["kill", "kill", "confirm"]
    assert run.status is AgentRunStatus.INTERRUPTED
