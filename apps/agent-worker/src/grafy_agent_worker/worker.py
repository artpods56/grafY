import asyncio
from datetime import UTC, datetime, timedelta
import logging
from uuid import UUID

from grafy_agent.errors import terminal_error
from grafy_agent.models import (
    AgentLease,
    CodingAgentRequest,
    CodingMessage,
    SandboxExecutionAuthority,
    SandboxWorkspace,
)
from grafy_agent.ports import CodingAgentPort, SandboxWorkspacePort
from grafy_agent.tools import NodeAuthoringTools
from grafy_agent.verification import CleanSandboxSourceBundleVerifier
from grafy_core.application.agent_authoring import (
    AgentAuthoringService,
    EnvironmentProvisioningClaim,
    RunClaim,
)
from grafy_core.domain.agent_authoring import (
    AgentAuthoringConflictError,
    AgentEnvironment,
    AgentEventKind,
    AgentRun,
    AgentRunStatus,
    NodeBuildStatus,
)
from grafy_core.ports.storage import FileStoragePort

from grafy_agent_worker.control import WorkerAuthoringControl
from grafy_agent_worker.settings import AgentWorkerSettings


logger = logging.getLogger(__name__)


class AgentWorker:
    """Reconcile provisioning, fenced run leases, and provider revocation."""

    def __init__(
        self,
        *,
        settings: AgentWorkerSettings,
        service: AgentAuthoringService,
        coding_agent: CodingAgentPort,
        sandboxes: dict[str, SandboxWorkspacePort],
        storage: FileStoragePort,
    ) -> None:
        if not sandboxes:
            raise ValueError("Agent worker requires at least one sandbox provider")
        self._settings = settings
        self._service = service
        self._coding_agent = coding_agent
        self._sandboxes = dict(sandboxes)
        self._storage = storage
        self._lease_duration = timedelta(seconds=settings.lease_seconds)

    async def run_forever(self) -> None:
        while True:
            handled = await self.poll_once()
            if not handled:
                await asyncio.sleep(self._settings.poll_interval_seconds)

    async def poll_once(self) -> bool:
        handled = False
        batch_size = self._settings.poll_batch_size

        for workspace_id, run_id in await self._service.list_cancelling_run_keys(
            limit=batch_size
        ):
            handled = True
            await self._recover_cancelled_run(workspace_id, run_id)

        for workspace_id, run_id in await self._service.list_interrupting_run_keys(
            limit=batch_size
        ):
            handled = True
            await self._recover_interrupted_run(workspace_id, run_id)

        now = datetime.now(UTC)
        expired = await self._service.list_expired_running_run_keys(
            when=now,
            limit=batch_size,
        )
        for workspace_id, run_id in expired:
            handled = True
            try:
                revocation = await self._service.fence_expired_run(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    when=now,
                )
                await self._terminate_run(revocation.run)
                await self._service.confirm_run_interrupted(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    revocation_fencing_token=revocation.revocation_fencing_token,
                )
            except AgentAuthoringConflictError:
                continue
            except Exception:
                logger.exception(
                    "Could not revoke expired agent run %s; writer remains reserved",
                    run_id,
                )

        for (
            workspace_id,
            environment_id,
        ) in await self._service.list_provisionable_environment_keys(
            when=now,
            limit=batch_size,
        ):
            handled = True
            try:
                await self._provision_environment(workspace_id, environment_id)
            except AgentAuthoringConflictError:
                continue
            except Exception:
                logger.exception(
                    "Agent environment %s failed during provisioning",
                    environment_id,
                )

        candidates = await self._service.list_claimable_run_keys(
            when=datetime.now(UTC),
            limit=batch_size,
        )
        for workspace_id, run_id in candidates:
            handled = True
            try:
                claim = await self._service.claim_run(
                    workspace_id=workspace_id,
                    run_id=run_id,
                    worker_id=self._settings.worker_id,
                    lease_duration=self._lease_duration,
                )
                await self._execute_claim(claim)
            except AgentAuthoringConflictError:
                continue
            except Exception:
                logger.exception(
                    "Agent run %s failed during worker reconciliation", run_id
                )
        return handled

    async def _provision_environment(
        self,
        workspace_id: UUID,
        environment_id: UUID,
    ) -> None:
        claim = await self._service.claim_environment_provisioning(
            workspace_id=workspace_id,
            environment_id=environment_id,
            worker_id=self._settings.worker_id,
            lease_duration=self._lease_duration,
        )
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat_provisioning(claim, stop),
            name=f"provisioning-heartbeat-{environment_id}",
        )
        provision = asyncio.create_task(
            self._ensure_claimed_environment(claim),
            name=f"provision-environment-{environment_id}",
        )
        done, _ = await asyncio.wait(
            {heartbeat, provision},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if heartbeat in done:
            error = heartbeat.exception()
            if error is not None:
                provision.cancel()
                await asyncio.gather(provision, return_exceptions=True)
                raise error
        try:
            workspace = await provision
            stop.set()
            await heartbeat
            await self._service.complete_environment_provisioning(
                workspace_id=workspace_id,
                environment_id=environment_id,
                provider_environment_id=workspace.provider_environment_id,
                provisioning_token=claim.provisioning_token,
                provisioning_fencing_token=claim.provisioning_fencing_token,
            )
        except Exception as exc:
            stop.set()
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            try:
                await self._service.fail_environment_provisioning(
                    workspace_id=workspace_id,
                    environment_id=environment_id,
                    error=terminal_error("Sandbox environment provisioning", exc),
                    provisioning_token=claim.provisioning_token,
                    provisioning_fencing_token=claim.provisioning_fencing_token,
                )
            except AgentAuthoringConflictError:
                pass
            raise

    async def _ensure_claimed_environment(
        self,
        claim: EnvironmentProvisioningClaim,
    ) -> SandboxWorkspace:
        environment = claim.environment
        return await self._sandbox_for(environment).ensure_workspace(
            environment_id=environment.id,
            provider_environment_id=environment.provider_environment_id,
            profile_id=environment.profile_id,
        )

    async def _heartbeat_provisioning(
        self,
        claim: EnvironmentProvisioningClaim,
        stop: asyncio.Event,
    ) -> None:
        environment = claim.environment
        while not stop.is_set():
            await self._service.heartbeat_environment_provisioning(
                workspace_id=environment.workspace_id,
                environment_id=environment.id,
                provisioning_token=claim.provisioning_token,
                provisioning_fencing_token=claim.provisioning_fencing_token,
                lease_duration=self._lease_duration,
            )
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self._settings.heartbeat_seconds,
                )
            except TimeoutError:
                continue

    async def _execute_claim(self, claim: RunClaim) -> None:
        stop = asyncio.Event()
        heartbeat = asyncio.create_task(
            self._heartbeat_run(claim, stop),
            name=f"agent-heartbeat-{claim.run.id}",
        )
        work = asyncio.create_task(
            self._run_claim(claim),
            name=f"agent-run-{claim.run.id}",
        )
        done, _ = await asyncio.wait(
            {heartbeat, work},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if heartbeat in done:
            error = heartbeat.exception()
            if error is not None:
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
                try:
                    await self._terminate_run(claim.run)
                except Exception:
                    logger.exception(
                        "Lease-lost run %s could not be provider-revoked",
                        claim.run.id,
                    )
                raise error
        try:
            await work
        finally:
            stop.set()
            await asyncio.gather(heartbeat, return_exceptions=True)

    async def _run_claim(self, claim: RunClaim) -> None:
        run = claim.run
        lease = AgentLease(
            workspace_id=run.workspace_id,
            thread_id=run.thread_id,
            environment_id=run.environment_id,
            run_id=run.id,
            lease_token=claim.lease_token,
            fencing_token=claim.fencing_token,
            target_draft_ids=run.target_draft_ids,
        )
        environment = await self._service.get_environment(
            run.workspace_id,
            run.environment_id,
        )
        sandbox = self._sandbox_for(environment)
        workspace = await sandbox.ensure_workspace(
            environment_id=environment.id,
            provider_environment_id=environment.provider_environment_id,
            profile_id=environment.profile_id,
        )
        session = await sandbox.open_session(
            workspace,
            SandboxExecutionAuthority.from_agent_lease(lease),
        )
        provider_revoked = False
        try:
            await self._service.start_run(
                workspace_id=run.workspace_id,
                run_id=run.id,
                lease_token=lease.lease_token,
                fencing_token=lease.fencing_token,
            )
            builds = tuple(
                await self._service.list_build_attempts(run.workspace_id, run.id)
            )
            for build in builds:
                preparing = await self._service.advance_build(
                    workspace_id=run.workspace_id,
                    build_attempt_id=build.id,
                    status=NodeBuildStatus.PREPARING,
                    lease_token=lease.lease_token,
                    fencing_token=lease.fencing_token,
                )
                await self._service.advance_build(
                    workspace_id=run.workspace_id,
                    build_attempt_id=preparing.id,
                    status=NodeBuildStatus.CODING,
                    lease_token=lease.lease_token,
                    fencing_token=lease.fencing_token,
                )
            builds = tuple(
                await self._service.list_build_attempts(run.workspace_id, run.id)
            )
            control = WorkerAuthoringControl(
                service=self._service,
                storage=self._storage,
                storage_bucket=self._settings.storage_bucket,
                lease=lease,
                builds=builds,
            )
            verifier = CleanSandboxSourceBundleVerifier(sandbox)
            bootstrap = NodeAuthoringTools(
                sandbox=sandbox,
                session=session,
                control=control,
                verifier=verifier,
                profile_id=environment.profile_id,
                lease=lease,
            )
            for draft_node_id in lease.target_draft_ids:
                draft = await self._service.get_draft(run.workspace_id, draft_node_id)
                await bootstrap.bootstrap_project(
                    draft_node_id,
                    draft.provisional_manifest,
                )
            history = await self._conversation_history(run)
            await self._coding_agent.run(
                request=CodingAgentRequest(
                    instructions=run.instructions,
                    history=history,
                ),
                lease=lease,
                session=session,
                profile_id=environment.profile_id,
                sandbox=sandbox,
                verifier=verifier,
                control=control,
            )
            await sandbox.terminate_session(session)
            provider_revoked = True
            await self._service.complete_run_awaiting_approval(
                workspace_id=run.workspace_id,
                run_id=run.id,
                lease_token=lease.lease_token,
                fencing_token=lease.fencing_token,
            )
        except BaseException as exc:
            if not provider_revoked:
                try:
                    await sandbox.terminate_execution(
                        workspace,
                        execution_id=run.id,
                    )
                    provider_revoked = True
                except Exception:
                    logger.exception(
                        "Run %s provider work could not be terminated; DB writer retained",
                        run.id,
                    )
            if isinstance(exc, asyncio.CancelledError):
                raise
            if provider_revoked:
                await self._fail_owned_run(lease, exc)
            else:
                raise

    async def _fail_owned_run(self, lease: AgentLease, error: BaseException) -> None:
        current = await self._service.get_run(lease.workspace_id, lease.run_id)
        if current.status not in {AgentRunStatus.CLAIMED, AgentRunStatus.RUNNING}:
            return
        try:
            await self._service.fail_run(
                workspace_id=lease.workspace_id,
                run_id=lease.run_id,
                error=terminal_error("Coding agent run", error),
                lease_token=lease.lease_token,
                fencing_token=lease.fencing_token,
            )
        except AgentAuthoringConflictError:
            return

    async def _heartbeat_run(self, claim: RunClaim, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await self._service.heartbeat_run(
                workspace_id=claim.run.workspace_id,
                run_id=claim.run.id,
                lease_token=claim.lease_token,
                fencing_token=claim.fencing_token,
                lease_duration=self._lease_duration,
            )
            try:
                await asyncio.wait_for(
                    stop.wait(),
                    timeout=self._settings.heartbeat_seconds,
                )
            except TimeoutError:
                continue

    async def _conversation_history(
        self, current: AgentRun
    ) -> tuple[CodingMessage, ...]:
        messages: list[CodingMessage] = []
        runs = await self._service.list_runs_for_thread(
            current.workspace_id,
            current.thread_id,
        )
        for run in runs:
            if run.id == current.id:
                continue
            messages.append(CodingMessage(role="user", content=run.instructions))
        events = await self._service.list_events(
            workspace_id=current.workspace_id,
            thread_id=current.thread_id,
            after_sequence=0,
            limit=1_000,
        )
        messages.extend(
            CodingMessage(role="assistant", content=event.payload.message)
            for event in events
            if event.kind is AgentEventKind.MESSAGE and event.run_id != current.id
        )
        return tuple(messages[-200:])

    async def _recover_cancelled_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> None:
        try:
            run = await self._service.get_run(workspace_id, run_id)
            if run.status is not AgentRunStatus.CANCELLING:
                return
            await self._terminate_run(run)
            await self._service.confirm_run_cancelled(
                workspace_id=workspace_id,
                run_id=run_id,
                revocation_fencing_token=run.fencing_token,
            )
        except AgentAuthoringConflictError:
            return
        except Exception:
            logger.exception(
                "Could not finish cancellation for run %s; writer remains reserved",
                run_id,
            )

    async def _recover_interrupted_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> None:
        try:
            run = await self._service.get_run(workspace_id, run_id)
            if run.status is not AgentRunStatus.INTERRUPTING:
                return
            await self._terminate_run(run)
            await self._service.confirm_run_interrupted(
                workspace_id=workspace_id,
                run_id=run_id,
                revocation_fencing_token=run.fencing_token,
            )
        except AgentAuthoringConflictError:
            return
        except Exception:
            logger.exception(
                "Could not finish interruption for run %s; writer remains reserved",
                run_id,
            )

    async def _terminate_run(self, run: AgentRun) -> None:
        environment = await self._service.get_environment(
            run.workspace_id,
            run.environment_id,
        )
        sandbox = self._sandbox_for(environment)
        workspace = await sandbox.ensure_workspace(
            environment_id=environment.id,
            provider_environment_id=environment.provider_environment_id,
            profile_id=environment.profile_id,
        )
        termination = await sandbox.terminate_execution(
            workspace,
            execution_id=run.id,
        )
        if not termination.revocation_verified:
            raise RuntimeError(
                f"Sandbox did not verify revocation for agent run {run.id}"
            )

    def _sandbox_for(self, environment: AgentEnvironment) -> SandboxWorkspacePort:
        try:
            return self._sandboxes[environment.provider]
        except KeyError as exc:
            raise RuntimeError(
                f"No sandbox provider is configured for {environment.provider!r}"
            ) from exc


__all__ = ["AgentWorker"]
