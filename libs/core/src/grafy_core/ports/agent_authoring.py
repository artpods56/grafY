"""Persistence ports for the agent-authoring bounded context."""

from datetime import datetime
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

from grafy_core.domain.agent_authoring import (
    AgentEnvironment,
    AgentEvent,
    AgentRun,
    AgentThread,
    CapabilityApproval,
    DraftNode,
    NodeBuildAttempt,
    NodeRelease,
)


class AgentAuthoringRepositoryPort(Protocol):
    async def add_environment(self, environment: AgentEnvironment) -> None: ...

    async def get_environment(
        self,
        workspace_id: UUID,
        environment_id: UUID,
    ) -> AgentEnvironment | None: ...

    async def lock_environment(
        self,
        workspace_id: UUID,
        environment_id: UUID,
    ) -> AgentEnvironment | None: ...

    async def save_environment(self, environment: AgentEnvironment) -> None: ...

    async def list_environments(
        self,
        workspace_id: UUID,
    ) -> list[AgentEnvironment]: ...

    async def list_provisionable_environment_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        """Return pending or expired-claim environment keys."""
        ...

    async def lock_provisionable_environment(
        self,
        workspace_id: UUID,
        environment_id: UUID,
        *,
        when: datetime,
    ) -> AgentEnvironment | None:
        """Non-blockingly lock a pending or expired provisioning environment."""
        ...

    async def add_thread(self, thread: AgentThread) -> None: ...

    async def get_thread(
        self,
        workspace_id: UUID,
        thread_id: UUID,
    ) -> AgentThread | None: ...

    async def lock_thread(
        self,
        workspace_id: UUID,
        thread_id: UUID,
    ) -> AgentThread | None: ...

    async def save_thread(self, thread: AgentThread) -> None: ...

    async def add_draft(self, draft: DraftNode) -> None: ...

    async def get_draft(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> DraftNode | None: ...

    async def lock_draft(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> DraftNode | None: ...

    async def save_draft(self, draft: DraftNode) -> None: ...

    async def list_drafts(
        self,
        workspace_id: UUID,
        *,
        thread_id: UUID | None = None,
    ) -> list[DraftNode]: ...

    async def add_run(self, run: AgentRun) -> None: ...

    async def get_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> AgentRun | None: ...

    async def lock_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> AgentRun | None: ...

    async def lock_claimable_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        when: datetime,
    ) -> AgentRun | None:
        """Lock an eligible run and free/same-writer environment without waiting."""
        ...

    async def lock_expired_running_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        when: datetime,
    ) -> AgentRun | None:
        """Non-blockingly lock an expired running run and its writer environment."""
        ...

    async def save_run(self, run: AgentRun) -> None: ...

    async def get_run_by_idempotency(
        self,
        workspace_id: UUID,
        idempotency_key: str,
    ) -> AgentRun | None: ...

    async def list_runs_for_thread(
        self,
        workspace_id: UUID,
        thread_id: UUID,
    ) -> list[AgentRun]:
        """Return thread runs in deterministic creation/id order."""
        ...

    async def list_claimable_run_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        """Return workspace/run keys for queued or expired-claim runs."""
        ...

    async def list_expired_running_run_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        """Return workspace/run keys requiring explicit interruption recovery."""
        ...

    async def list_interrupting_run_keys(
        self,
        *,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        """Return fenced runs whose provider execution still needs termination."""
        ...

    async def list_cancelling_run_keys(
        self,
        *,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        """Return user-cancelled runs awaiting provider termination confirmation."""
        ...

    async def add_build_attempt(self, build: NodeBuildAttempt) -> None: ...

    async def get_build_attempt(
        self,
        workspace_id: UUID,
        build_attempt_id: UUID,
    ) -> NodeBuildAttempt | None: ...

    async def lock_build_attempt(
        self,
        workspace_id: UUID,
        build_attempt_id: UUID,
    ) -> NodeBuildAttempt | None: ...

    async def save_build_attempt(self, build: NodeBuildAttempt) -> None: ...

    async def list_build_attempts_for_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> list[NodeBuildAttempt]: ...

    async def list_build_attempts_for_draft(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> list[NodeBuildAttempt]: ...

    async def get_latest_build_attempt_for_draft(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> NodeBuildAttempt | None: ...

    async def add_event(self, event: AgentEvent) -> None: ...

    async def list_events(
        self,
        workspace_id: UUID,
        thread_id: UUID,
        *,
        after_sequence: int,
        limit: int,
    ) -> list[AgentEvent]: ...

    async def add_capability_approval(
        self,
        approval: CapabilityApproval,
    ) -> None: ...

    async def get_capability_approval(
        self,
        workspace_id: UUID,
        build_attempt_id: UUID,
    ) -> CapabilityApproval | None: ...

    async def add_release(self, release: NodeRelease) -> None: ...

    async def get_release(
        self,
        workspace_id: UUID,
        node_id: UUID,
        revision: int,
    ) -> NodeRelease | None: ...

    async def list_releases(
        self,
        workspace_id: UUID,
    ) -> list[NodeRelease]: ...


class AgentAuthoringUnitOfWorkPort(Protocol):
    @property
    def agent_authoring(self) -> AgentAuthoringRepositoryPort: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


__all__ = ["AgentAuthoringRepositoryPort", "AgentAuthoringUnitOfWorkPort"]
