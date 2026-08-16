"""Application service for durable, sandboxed agent-authored nodes."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from uuid import UUID, uuid4

from grafy_core.domain.agent_authoring import (
    MAX_AGENT_PROMPT_LENGTH,
    AgentAuthoringConflictError,
    AgentAuthoringError,
    AgentAuthoringIdempotencyError,
    AgentEnvironment,
    AgentEnvironmentStatus,
    AgentEvent,
    AgentEventKind,
    AgentEventPayload,
    AgentRun,
    AgentRunStatus,
    AgentThread,
    AnchoredPortContract,
    BuildArtifactSet,
    CapabilityApproval,
    CapabilityManifest,
    DraftNode,
    GeneratedNodeManifest,
    NodeBuildAttempt,
    NodeBuildStatus,
    NodeRelease,
    RevokedAgentLease,
)
from grafy_core.domain.errors import NotFoundError
from grafy_core.ports.agent_authoring import (
    AgentAuthoringRepositoryPort,
    AgentAuthoringUnitOfWorkPort,
)


@dataclass(frozen=True, slots=True)
class DraftCreation:
    environment: AgentEnvironment
    thread: AgentThread
    draft: DraftNode
    run: AgentRun
    build: NodeBuildAttempt


@dataclass(frozen=True, slots=True)
class DraftDetail:
    environment: AgentEnvironment
    thread: AgentThread
    draft: DraftNode
    latest_build: NodeBuildAttempt
    latest_run: AgentRun


@dataclass(frozen=True, slots=True)
class EnvironmentProvisioningClaim:
    environment: AgentEnvironment
    provisioning_token: UUID
    provisioning_fencing_token: int


@dataclass(frozen=True, slots=True)
class RunClaim:
    run: AgentRun
    lease_token: UUID
    fencing_token: int


@dataclass(frozen=True, slots=True)
class RunRevocation:
    run: AgentRun
    revoked_lease: RevokedAgentLease
    revocation_fencing_token: int


@dataclass(frozen=True, slots=True)
class RunCancellationRequest:
    run: AgentRun
    revoked_lease: RevokedAgentLease | None
    revocation_fencing_token: int | None


@dataclass(frozen=True, slots=True)
class RunContinuation:
    interrupted_run_id: UUID
    run: AgentRun
    builds: tuple[NodeBuildAttempt, ...]


@dataclass(frozen=True, slots=True)
class FollowUpRun:
    environment: AgentEnvironment
    thread: AgentThread
    run: AgentRun
    builds: tuple[NodeBuildAttempt, ...]


@dataclass(frozen=True, slots=True)
class NodePublication:
    draft: DraftNode
    build: NodeBuildAttempt
    run: AgentRun
    release: NodeRelease


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _normalized_prompt(prompt: str) -> str:
    normalized = prompt.strip()
    if normalized == "" or len(normalized) > MAX_AGENT_PROMPT_LENGTH:
        raise AgentAuthoringError(
            f"Agent prompt must contain 1 to {MAX_AGENT_PROMPT_LENGTH} characters"
        )
    return normalized


def _request_digest(document: dict[str, object]) -> str:
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _assert_worker_lease(
    run: AgentRun,
    *,
    lease_token: UUID,
    fencing_token: int,
    when: datetime,
) -> None:
    if run.lease_token != lease_token or run.fencing_token != fencing_token:
        raise AgentAuthoringConflictError(
            f"Agent run {run.id} worker lease is stale"
        )
    if run.lease_is_expired(when):
        raise AgentAuthoringConflictError(f"Agent run {run.id} worker lease expired")


@dataclass(frozen=True, slots=True)
class _LockedRunContext:
    run: AgentRun
    environment: AgentEnvironment
    thread: AgentThread


@dataclass(frozen=True, slots=True)
class _LockedBuildContext:
    run: AgentRun
    environment: AgentEnvironment
    thread: AgentThread
    draft: DraftNode
    build: NodeBuildAttempt


@dataclass(frozen=True, slots=True)
class _LockedRunTargets:
    drafts: tuple[DraftNode, ...]
    builds: tuple[NodeBuildAttempt, ...]


async def _lock_run_context(
    repository: AgentAuthoringRepositoryPort,
    workspace_id: UUID,
    run_id: UUID,
) -> _LockedRunContext:
    """Lock one run aggregate in run -> environment -> thread order."""

    run = await repository.lock_run(workspace_id, run_id)
    if run is None:
        raise NotFoundError("Agent run", str(run_id))
    environment = await repository.lock_environment(
        workspace_id,
        run.environment_id,
    )
    if environment is None:
        raise NotFoundError("Agent environment", str(run.environment_id))
    thread = await repository.lock_thread(workspace_id, run.thread_id)
    if thread is None:
        raise NotFoundError("Agent thread", str(run.thread_id))
    if thread.environment_id != environment.id:
        raise AgentAuthoringConflictError(
            f"Agent run {run.id} has inconsistent environment ownership"
        )
    return _LockedRunContext(
        run=run,
        environment=environment,
        thread=thread,
    )


async def _lock_build_context(
    repository: AgentAuthoringRepositoryPort,
    workspace_id: UUID,
    build_attempt_id: UUID,
) -> _LockedBuildContext:
    """Lock one build aggregate after its run-owned context."""

    candidate = await repository.get_build_attempt(workspace_id, build_attempt_id)
    if candidate is None:
        raise NotFoundError("Node build attempt", str(build_attempt_id))
    run_context = await _lock_run_context(
        repository,
        workspace_id,
        candidate.run_id,
    )
    draft = await repository.lock_draft(
        workspace_id,
        candidate.draft_node_id,
    )
    if draft is None:
        raise NotFoundError("Draft node", str(candidate.draft_node_id))
    build = await repository.lock_build_attempt(workspace_id, build_attempt_id)
    if build is None:
        raise NotFoundError("Node build attempt", str(build_attempt_id))
    if (
        build.run_id != run_context.run.id
        or build.draft_node_id != draft.id
        or build.thread_id != run_context.thread.id
        or draft.thread_id != run_context.thread.id
    ):
        raise AgentAuthoringConflictError(
            f"Build {build.id} has inconsistent authoring ownership"
        )
    return _LockedBuildContext(
        run=run_context.run,
        environment=run_context.environment,
        thread=run_context.thread,
        draft=draft,
        build=build,
    )


async def _lock_run_targets(
    repository: AgentAuthoringRepositoryPort,
    workspace_id: UUID,
    run: AgentRun,
) -> _LockedRunTargets:
    """Lock sorted drafts before sorted builds for one already-locked run."""

    candidates = await repository.list_build_attempts_for_run(workspace_id, run.id)
    drafts: list[DraftNode] = []
    for draft_node_id in sorted(
        {build.draft_node_id for build in candidates},
        key=str,
    ):
        draft = await repository.lock_draft(workspace_id, draft_node_id)
        if draft is None:
            raise NotFoundError("Draft node", str(draft_node_id))
        if draft.thread_id != run.thread_id:
            raise AgentAuthoringConflictError(
                f"Draft {draft.id} does not belong to run {run.id}'s thread"
            )
        drafts.append(draft)
    builds: list[NodeBuildAttempt] = []
    for candidate in sorted(candidates, key=lambda build: str(build.id)):
        build = await repository.lock_build_attempt(workspace_id, candidate.id)
        if build is None:
            raise NotFoundError("Node build attempt", str(candidate.id))
        if build.run_id != run.id or build.draft_node_id not in {
            draft.id for draft in drafts
        }:
            raise AgentAuthoringConflictError(
                f"Build {build.id} does not belong to run {run.id}"
            )
        builds.append(build)
    return _LockedRunTargets(drafts=tuple(drafts), builds=tuple(builds))


async def _cancel_locked_targets(
    repository: AgentAuthoringRepositoryPort,
    targets: _LockedRunTargets,
    *,
    when: datetime,
) -> None:
    drafts_by_id = {draft.id: draft for draft in targets.drafts}
    changed_draft_ids: set[UUID] = set()
    for build in targets.builds:
        if build.status in {
            NodeBuildStatus.PUBLISHED,
            NodeBuildStatus.FAILED,
            NodeBuildStatus.CANCELLED,
            NodeBuildStatus.SUPERSEDED,
        }:
            continue
        build.cancel(when=when)
        changed_draft_ids.add(build.draft_node_id)
        await repository.save_build_attempt(build)
    for draft_node_id in changed_draft_ids:
        draft = drafts_by_id[draft_node_id]
        draft.cancel(when=when)
        await repository.save_draft(draft)


async def _fail_locked_targets(
    repository: AgentAuthoringRepositoryPort,
    targets: _LockedRunTargets,
    *,
    error: str,
    when: datetime,
) -> None:
    drafts_by_id = {draft.id: draft for draft in targets.drafts}
    changed_draft_ids: set[UUID] = set()
    for build in targets.builds:
        if build.status in {
            NodeBuildStatus.PUBLISHED,
            NodeBuildStatus.FAILED,
            NodeBuildStatus.CANCELLED,
            NodeBuildStatus.SUPERSEDED,
        }:
            continue
        if build.status is NodeBuildStatus.AWAITING_APPROVAL:
            build.cancel(when=when)
        else:
            build.fail(error, when=when)
        changed_draft_ids.add(build.draft_node_id)
        await repository.save_build_attempt(build)
    for draft_node_id in changed_draft_ids:
        draft = drafts_by_id[draft_node_id]
        draft.mark_failed(when=when)
        await repository.save_draft(draft)


class AgentAuthoringService:
    """Own authoring transactions; HTTP, agents, and MCP remain adapters.

    Existing run aggregates are locked in one order: run, environment, thread,
    sorted drafts, then sorted builds. Creation without an existing run locks
    environment before thread and drafts. Repository-specific atomic claim and
    recovery methods lock the run/environment pair in that same leading order.
    """

    def __init__(
        self,
        unit_of_work_factory: Callable[[], AgentAuthoringUnitOfWorkPort],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def create_environment(
        self,
        *,
        workspace_id: UUID,
        name: str,
        profile_id: str,
        provider: str,
        created_by_user_id: UUID | None,
    ) -> AgentEnvironment:
        environment = AgentEnvironment(
            workspace_id=workspace_id,
            name=name,
            profile_id=profile_id,
            provider=provider,
            created_by_user_id=created_by_user_id,
        )
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.agent_authoring.add_environment(environment)
            await unit_of_work.commit()
        return environment

    async def claim_environment_provisioning(
        self,
        *,
        workspace_id: UUID,
        environment_id: UUID,
        worker_id: str,
        lease_duration: timedelta,
        when: datetime | None = None,
    ) -> EnvironmentProvisioningClaim:
        if lease_duration <= timedelta(0) or lease_duration > timedelta(hours=1):
            raise AgentAuthoringError(
                "Environment provisioning lease must be positive and at most one hour"
            )
        timestamp = when or _utc_now()
        provisioning_token = uuid4()
        async with self._unit_of_work_factory() as unit_of_work:
            environment = (
                await unit_of_work.agent_authoring.lock_provisionable_environment(
                    workspace_id,
                    environment_id,
                    when=timestamp,
                )
            )
            if environment is None:
                raise AgentAuthoringConflictError(
                    f"Environment {environment_id} is not currently provisionable"
                )
            environment.claim_provisioning(
                worker_id=worker_id,
                provisioning_token=provisioning_token,
                provisioning_expires_at=timestamp + lease_duration,
                when=timestamp,
            )
            await unit_of_work.agent_authoring.save_environment(environment)
            await unit_of_work.commit()
            return EnvironmentProvisioningClaim(
                environment=environment,
                provisioning_token=provisioning_token,
                provisioning_fencing_token=(
                    environment.provisioning_fencing_token
                ),
            )

    async def heartbeat_environment_provisioning(
        self,
        *,
        workspace_id: UUID,
        environment_id: UUID,
        provisioning_token: UUID,
        provisioning_fencing_token: int,
        lease_duration: timedelta,
        when: datetime | None = None,
    ) -> AgentEnvironment:
        if lease_duration <= timedelta(0) or lease_duration > timedelta(hours=1):
            raise AgentAuthoringError(
                "Environment provisioning lease must be positive and at most one hour"
            )
        timestamp = when or _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            environment = await unit_of_work.agent_authoring.lock_environment(
                workspace_id,
                environment_id,
            )
            if environment is None:
                raise NotFoundError("Agent environment", str(environment_id))
            environment.heartbeat_provisioning(
                provisioning_token=provisioning_token,
                provisioning_fencing_token=provisioning_fencing_token,
                provisioning_expires_at=timestamp + lease_duration,
                when=timestamp,
            )
            await unit_of_work.agent_authoring.save_environment(environment)
            await unit_of_work.commit()
            return environment

    async def complete_environment_provisioning(
        self,
        *,
        workspace_id: UUID,
        environment_id: UUID,
        provider_environment_id: str,
        provisioning_token: UUID,
        provisioning_fencing_token: int,
        when: datetime | None = None,
    ) -> AgentEnvironment:
        async with self._unit_of_work_factory() as unit_of_work:
            environment = await unit_of_work.agent_authoring.lock_environment(
                workspace_id,
                environment_id,
            )
            if environment is None:
                raise NotFoundError("Agent environment", str(environment_id))
            environment.complete_provisioning(
                provider_environment_id=provider_environment_id,
                provisioning_token=provisioning_token,
                provisioning_fencing_token=provisioning_fencing_token,
                when=when,
            )
            await unit_of_work.agent_authoring.save_environment(environment)
            await unit_of_work.commit()
            return environment

    async def fail_environment_provisioning(
        self,
        *,
        workspace_id: UUID,
        environment_id: UUID,
        error: str,
        provisioning_token: UUID,
        provisioning_fencing_token: int,
        when: datetime | None = None,
    ) -> AgentEnvironment:
        async with self._unit_of_work_factory() as unit_of_work:
            environment = await unit_of_work.agent_authoring.lock_environment(
                workspace_id,
                environment_id,
            )
            if environment is None:
                raise NotFoundError("Agent environment", str(environment_id))
            environment.fail_provisioning(
                error=error,
                provisioning_token=provisioning_token,
                provisioning_fencing_token=provisioning_fencing_token,
                when=when,
            )
            await unit_of_work.agent_authoring.save_environment(environment)
            await unit_of_work.commit()
            return environment

    async def get_environment(
        self,
        workspace_id: UUID,
        environment_id: UUID,
    ) -> AgentEnvironment:
        async with self._unit_of_work_factory() as unit_of_work:
            environment = await unit_of_work.agent_authoring.get_environment(
                workspace_id,
                environment_id,
            )
        if environment is None:
            raise NotFoundError("Agent environment", str(environment_id))
        return environment

    async def list_provisionable_environment_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        if limit < 1 or limit > 1_000:
            raise AgentAuthoringError(
                "Environment provisioning poll limit must be between 1 and 1000"
            )
        async with self._unit_of_work_factory() as unit_of_work:
            return (
                await unit_of_work.agent_authoring.list_provisionable_environment_keys(
                    when=when,
                    limit=limit,
                )
            )

    async def list_environments(
        self,
        workspace_id: UUID,
    ) -> list[AgentEnvironment]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.agent_authoring.list_environments(workspace_id)

    async def create_thread(
        self,
        *,
        workspace_id: UUID,
        environment_id: UUID,
        title: str = "Agent thread",
        created_by_user_id: UUID | None,
    ) -> AgentThread:
        async with self._unit_of_work_factory() as unit_of_work:
            environment = await unit_of_work.agent_authoring.lock_environment(
                workspace_id,
                environment_id,
            )
            if environment is None:
                raise NotFoundError("Agent environment", str(environment_id))
            if environment.status in {
                AgentEnvironmentStatus.FAILED,
                AgentEnvironmentStatus.ARCHIVED,
            }:
                raise AgentAuthoringConflictError(
                    f"Environment {environment.id} cannot host a new thread"
                )
            thread = AgentThread(
                workspace_id=workspace_id,
                environment_id=environment.id,
                title=title,
                created_by_user_id=created_by_user_id,
            )
            await unit_of_work.agent_authoring.add_thread(thread)
            await unit_of_work.commit()
            return thread

    async def create_draft(
        self,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        prompt: str,
        anchor: AnchoredPortContract,
        created_by_user_id: UUID | None,
        idempotency_key: str,
        environment_id: UUID | None = None,
        thread_id: UUID | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> DraftCreation:
        async with self._unit_of_work_factory() as unit_of_work:
            creation = await self.create_draft_in_unit_of_work(
                unit_of_work,
                workspace_id=workspace_id,
                graph_id=graph_id,
                prompt=prompt,
                anchor=anchor,
                created_by_user_id=created_by_user_id,
                idempotency_key=idempotency_key,
                environment_id=environment_id,
                thread_id=thread_id,
                title=title,
                description=description,
            )
            await unit_of_work.commit()
            return creation

    async def create_draft_in_unit_of_work(
        self,
        unit_of_work: AgentAuthoringUnitOfWorkPort,
        *,
        workspace_id: UUID,
        graph_id: UUID,
        prompt: str,
        anchor: AnchoredPortContract,
        created_by_user_id: UUID | None,
        idempotency_key: str,
        environment_id: UUID | None = None,
        thread_id: UUID | None = None,
        title: str | None = None,
        description: str | None = None,
    ) -> DraftCreation:
        normalized_prompt = _normalized_prompt(prompt)
        provisional_title = title if title is not None else "Generated node"
        provisional_description = (
            description
            if description is not None
            else normalized_prompt[:1_000]
        )
        normalized_idempotency_key = idempotency_key.strip()
        if normalized_idempotency_key == "" or len(normalized_idempotency_key) > 255:
            raise AgentAuthoringError(
                "Agent draft idempotency key must contain 1 to 255 characters"
            )
        digest = _request_digest(
            {
                "workspace_id": str(workspace_id),
                "graph_id": str(graph_id),
                "environment_id": (
                    str(environment_id) if environment_id is not None else None
                ),
                "thread_id": str(thread_id) if thread_id is not None else None,
                "prompt": normalized_prompt,
                "title": provisional_title,
                "description": provisional_description,
                "anchor": anchor.model_dump(mode="json"),
                "created_by_user_id": (
                    str(created_by_user_id)
                    if created_by_user_id is not None
                    else None
                ),
            }
        )
        repository = unit_of_work.agent_authoring
        existing_run = await repository.get_run_by_idempotency(
            workspace_id,
            normalized_idempotency_key,
        )
        if existing_run is not None:
            if existing_run.request_digest != digest:
                raise AgentAuthoringIdempotencyError(
                    f"Idempotency key {normalized_idempotency_key!r} was reused "
                    "for a different draft request"
                )
            return await self._reconstitute_draft_creation(
                repository,
                existing_run,
            )

        thread_is_new = thread_id is None
        if thread_id is None:
            if environment_id is None:
                raise AgentAuthoringError(
                    "A new agent thread requires an environment id"
                )
            selected_environment = await repository.lock_environment(
                workspace_id,
                environment_id,
            )
            if selected_environment is None:
                raise NotFoundError("Agent environment", str(environment_id))
            environment = selected_environment
            thread = AgentThread(
                workspace_id=workspace_id,
                environment_id=environment.id,
                title=provisional_title,
                created_by_user_id=created_by_user_id,
            )
        else:
            discovered_thread = await repository.get_thread(workspace_id, thread_id)
            if discovered_thread is None:
                raise NotFoundError("Agent thread", str(thread_id))
            if (
                environment_id is not None
                and environment_id != discovered_thread.environment_id
            ):
                raise AgentAuthoringConflictError(
                    "An agent thread cannot move to another environment"
                )
            selected_environment = await repository.lock_environment(
                workspace_id,
                discovered_thread.environment_id,
            )
            if selected_environment is None:
                raise NotFoundError(
                    "Agent environment",
                    str(discovered_thread.environment_id),
                )
            environment = selected_environment
            selected_thread = await repository.lock_thread(workspace_id, thread_id)
            if selected_thread is None:
                raise NotFoundError("Agent thread", str(thread_id))
            if selected_thread.environment_id != environment.id:
                raise AgentAuthoringConflictError(
                    f"Agent thread {thread_id} changed environment ownership"
                )
            thread = selected_thread
        if environment.status in {
            AgentEnvironmentStatus.FAILED,
            AgentEnvironmentStatus.ARCHIVED,
        }:
            raise AgentAuthoringConflictError(
                f"Environment {environment.id} cannot author a new draft"
            )

        draft = DraftNode(
            workspace_id=workspace_id,
            thread_id=thread.id,
            graph_id=graph_id,
            title=provisional_title,
            description=provisional_description,
            prompt=normalized_prompt,
            anchor=anchor,
            created_by_user_id=created_by_user_id,
        )
        attempt_number = draft.begin_build()
        run = AgentRun(
            workspace_id=workspace_id,
            thread_id=thread.id,
            environment_id=environment.id,
            target_draft_ids=(draft.id,),
            instructions=normalized_prompt,
            idempotency_key=normalized_idempotency_key,
            request_digest=digest,
            created_by_user_id=created_by_user_id,
        )
        build = NodeBuildAttempt(
            workspace_id=workspace_id,
            thread_id=thread.id,
            draft_node_id=draft.id,
            run_id=run.id,
            attempt_number=attempt_number,
            prompt=normalized_prompt,
        )
        event = thread.record_event(
            kind=AgentEventKind.RUN_QUEUED,
            payload=AgentEventPayload(
                message="Agent run queued for generated node",
                draft_node_id=draft.id,
                build_attempt_id=build.id,
                run_status=run.status,
                build_status=build.status,
            ),
            run_id=run.id,
        )
        if thread_is_new:
            await repository.add_thread(thread)
        else:
            await repository.save_thread(thread)
        await repository.add_draft(draft)
        await repository.add_run(run)
        await repository.add_build_attempt(build)
        await repository.add_event(event)
        return DraftCreation(
            environment=environment,
            thread=thread,
            draft=draft,
            run=run,
            build=build,
        )

    async def _reconstitute_draft_creation(
        self,
        repository: AgentAuthoringRepositoryPort,
        run: AgentRun,
    ) -> DraftCreation:
        if len(run.target_draft_ids) != 1 or run.continued_from_run_id is not None:
            raise AgentAuthoringConflictError(
                "Draft creation idempotency record does not describe one initial draft"
            )
        draft = await repository.get_draft(run.workspace_id, run.target_draft_ids[0])
        thread = await repository.get_thread(run.workspace_id, run.thread_id)
        environment = await repository.get_environment(
            run.workspace_id,
            run.environment_id,
        )
        builds = await repository.list_build_attempts_for_run(
            run.workspace_id,
            run.id,
        )
        if draft is None or thread is None or environment is None or len(builds) != 1:
            raise AgentAuthoringConflictError(
                "Draft creation idempotency record is incomplete"
            )
        return DraftCreation(
            environment=environment,
            thread=thread,
            draft=draft,
            run=run,
            build=builds[0],
        )

    async def get_draft(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> DraftNode:
        async with self._unit_of_work_factory() as unit_of_work:
            draft = await unit_of_work.agent_authoring.get_draft(
                workspace_id,
                draft_node_id,
            )
        if draft is None:
            raise NotFoundError("Draft node", str(draft_node_id))
        return draft

    async def get_draft_detail(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> DraftDetail:
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            draft = await repository.get_draft(workspace_id, draft_node_id)
            if draft is None:
                raise NotFoundError("Draft node", str(draft_node_id))
            thread = await repository.get_thread(workspace_id, draft.thread_id)
            latest_build = await repository.get_latest_build_attempt_for_draft(
                workspace_id,
                draft.id,
            )
            if thread is None:
                raise AgentAuthoringConflictError(
                    f"Draft {draft.id} is missing its authoring thread"
                )
            if latest_build is None:
                raise AgentAuthoringConflictError(
                    f"Draft {draft.id} is missing its latest build attempt"
                )
            latest_run = await repository.get_run(
                workspace_id,
                latest_build.run_id,
            )
            environment = await repository.get_environment(
                workspace_id,
                thread.environment_id,
            )
            if latest_run is None or environment is None:
                raise AgentAuthoringConflictError(
                    f"Draft {draft.id} authoring detail is incomplete"
                )
            return DraftDetail(
                environment=environment,
                thread=thread,
                draft=draft,
                latest_build=latest_build,
                latest_run=latest_run,
            )

    async def queue_follow_up_run(
        self,
        *,
        workspace_id: UUID,
        thread_id: UUID,
        draft_node_ids: tuple[UUID, ...],
        instructions: str,
        idempotency_key: str,
        created_by_user_id: UUID | None,
        when: datetime | None = None,
    ) -> FollowUpRun:
        if not draft_node_ids:
            raise AgentAuthoringError("A follow-up run must target at least one draft")
        if len(draft_node_ids) != len(set(draft_node_ids)):
            raise AgentAuthoringError("Follow-up run target drafts must be unique")
        normalized_instructions = _normalized_prompt(instructions)
        normalized_key = idempotency_key.strip()
        if normalized_key == "" or len(normalized_key) > 255:
            raise AgentAuthoringError(
                "Follow-up idempotency key must contain 1 to 255 characters"
            )
        timestamp = when or _utc_now()
        digest = _request_digest(
            {
                "workspace_id": str(workspace_id),
                "thread_id": str(thread_id),
                "draft_node_ids": [str(draft_id) for draft_id in draft_node_ids],
                "instructions": normalized_instructions,
                "created_by_user_id": (
                    str(created_by_user_id)
                    if created_by_user_id is not None
                    else None
                ),
            }
        )
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            existing = await repository.get_run_by_idempotency(
                workspace_id,
                normalized_key,
            )
            if existing is not None:
                if (
                    existing.request_digest != digest
                    or existing.thread_id != thread_id
                    or existing.target_draft_ids != draft_node_ids
                    or existing.continued_from_run_id is not None
                ):
                    raise AgentAuthoringIdempotencyError(
                        f"Idempotency key {normalized_key!r} was reused for a "
                        "different follow-up run"
                    )
                thread = await repository.get_thread(workspace_id, thread_id)
                environment = await repository.get_environment(
                    workspace_id,
                    existing.environment_id,
                )
                builds = await repository.list_build_attempts_for_run(
                    workspace_id,
                    existing.id,
                )
                if (
                    thread is None
                    or environment is None
                    or len(builds) != len(draft_node_ids)
                ):
                    raise AgentAuthoringConflictError(
                        "Follow-up run idempotency record is incomplete"
                    )
                return FollowUpRun(
                    environment=environment,
                    thread=thread,
                    run=existing,
                    builds=tuple(builds),
                )

            discovered_thread = await repository.get_thread(workspace_id, thread_id)
            if discovered_thread is None:
                raise NotFoundError("Agent thread", str(thread_id))
            environment = await repository.lock_environment(
                workspace_id,
                discovered_thread.environment_id,
            )
            if environment is None:
                raise NotFoundError(
                    "Agent environment",
                    str(discovered_thread.environment_id),
                )
            thread = await repository.lock_thread(workspace_id, thread_id)
            if thread is None:
                raise NotFoundError("Agent thread", str(thread_id))
            if thread.environment_id != environment.id:
                raise AgentAuthoringConflictError(
                    f"Agent thread {thread.id} changed environment ownership"
                )
            if environment.status in {
                AgentEnvironmentStatus.FAILED,
                AgentEnvironmentStatus.ARCHIVED,
            }:
                raise AgentAuthoringConflictError(
                    f"Environment {environment.id} cannot run follow-up authoring"
                )

            drafts: list[DraftNode] = []
            for draft_node_id in sorted(draft_node_ids, key=str):
                draft = await repository.lock_draft(workspace_id, draft_node_id)
                if draft is None:
                    raise NotFoundError("Draft node", str(draft_node_id))
                if draft.thread_id != thread.id:
                    raise AgentAuthoringConflictError(
                        f"Draft {draft.id} does not belong to thread {thread.id}"
                    )
                attempts = await repository.list_build_attempts_for_draft(
                    workspace_id,
                    draft.id,
                )
                if any(attempt.is_active for attempt in attempts):
                    raise AgentAuthoringConflictError(
                        f"Draft {draft.id} already has an active build attempt"
                    )
                drafts.append(draft)

            run = AgentRun(
                workspace_id=workspace_id,
                thread_id=thread.id,
                environment_id=environment.id,
                target_draft_ids=draft_node_ids,
                instructions=normalized_instructions,
                idempotency_key=normalized_key,
                request_digest=digest,
                created_by_user_id=created_by_user_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
            await repository.add_run(run)
            builds: list[NodeBuildAttempt] = []
            drafts_by_id = {draft.id: draft for draft in drafts}
            for draft_node_id in draft_node_ids:
                draft = drafts_by_id[draft_node_id]
                attempt_number = draft.begin_build(when=timestamp)
                build = NodeBuildAttempt(
                    workspace_id=workspace_id,
                    thread_id=thread.id,
                    draft_node_id=draft.id,
                    run_id=run.id,
                    attempt_number=attempt_number,
                    prompt=normalized_instructions,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                builds.append(build)
                await repository.save_draft(draft)
                await repository.add_build_attempt(build)
            event = thread.record_event(
                kind=AgentEventKind.RUN_QUEUED,
                payload=AgentEventPayload(
                    message=(
                        f"Follow-up agent run queued for {len(drafts)} generated "
                        "node revision(s)"
                    ),
                    run_status=run.status,
                ),
                run_id=run.id,
                when=timestamp,
            )
            await repository.save_thread(thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            return FollowUpRun(
                environment=environment,
                thread=thread,
                run=run,
                builds=tuple(builds),
            )

    async def list_drafts(
        self,
        workspace_id: UUID,
        *,
        thread_id: UUID | None = None,
    ) -> list[DraftNode]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.agent_authoring.list_drafts(
                workspace_id,
                thread_id=thread_id,
            )

    async def get_run(self, workspace_id: UUID, run_id: UUID) -> AgentRun:
        async with self._unit_of_work_factory() as unit_of_work:
            run = await unit_of_work.agent_authoring.get_run(workspace_id, run_id)
        if run is None:
            raise NotFoundError("Agent run", str(run_id))
        return run

    async def list_runs_for_thread(
        self,
        workspace_id: UUID,
        thread_id: UUID,
    ) -> list[AgentRun]:
        async with self._unit_of_work_factory() as unit_of_work:
            thread = await unit_of_work.agent_authoring.get_thread(
                workspace_id,
                thread_id,
            )
            if thread is None:
                raise NotFoundError("Agent thread", str(thread_id))
            return await unit_of_work.agent_authoring.list_runs_for_thread(
                workspace_id,
                thread_id,
            )

    async def list_build_attempts(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> list[NodeBuildAttempt]:
        async with self._unit_of_work_factory() as unit_of_work:
            run = await unit_of_work.agent_authoring.get_run(workspace_id, run_id)
            if run is None:
                raise NotFoundError("Agent run", str(run_id))
            return await unit_of_work.agent_authoring.list_build_attempts_for_run(
                workspace_id,
                run_id,
            )

    async def get_build_attempt(
        self,
        workspace_id: UUID,
        build_attempt_id: UUID,
    ) -> NodeBuildAttempt:
        async with self._unit_of_work_factory() as unit_of_work:
            build = await unit_of_work.agent_authoring.get_build_attempt(
                workspace_id,
                build_attempt_id,
            )
        if build is None:
            raise NotFoundError("Node build attempt", str(build_attempt_id))
        return build

    async def list_claimable_run_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        if limit < 1 or limit > 1_000:
            raise AgentAuthoringError("Agent run poll limit must be between 1 and 1000")
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.agent_authoring.list_claimable_run_keys(
                when=when,
                limit=limit,
            )

    async def list_expired_running_run_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        if limit < 1 or limit > 1_000:
            raise AgentAuthoringError("Agent run poll limit must be between 1 and 1000")
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.agent_authoring.list_expired_running_run_keys(
                when=when,
                limit=limit,
            )

    async def list_interrupting_run_keys(
        self,
        *,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        if limit < 1 or limit > 1_000:
            raise AgentAuthoringError("Agent run poll limit must be between 1 and 1000")
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.agent_authoring.list_interrupting_run_keys(
                limit=limit,
            )

    async def list_cancelling_run_keys(
        self,
        *,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        if limit < 1 or limit > 1_000:
            raise AgentAuthoringError("Agent run poll limit must be between 1 and 1000")
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.agent_authoring.list_cancelling_run_keys(
                limit=limit,
            )

    async def claim_run(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        worker_id: str,
        lease_duration: timedelta,
        when: datetime | None = None,
    ) -> RunClaim:
        if lease_duration <= timedelta(0) or lease_duration > timedelta(hours=1):
            raise AgentAuthoringError(
                "Agent run lease duration must be positive and at most one hour"
            )
        timestamp = when or _utc_now()
        lease_token = uuid4()
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            run = await repository.lock_claimable_run(
                workspace_id,
                run_id,
                when=timestamp,
            )
            if run is None:
                raise AgentAuthoringConflictError(
                    f"Agent run {run_id} is not currently claimable"
                )
            environment = await repository.lock_environment(
                workspace_id,
                run.environment_id,
            )
            if environment is None:
                raise NotFoundError("Agent environment", str(run.environment_id))
            thread = await repository.lock_thread(workspace_id, run.thread_id)
            if thread is None:
                raise NotFoundError("Agent thread", str(run.thread_id))
            run.claim(
                worker_id=worker_id,
                lease_token=lease_token,
                lease_expires_at=timestamp + lease_duration,
                when=timestamp,
            )
            environment.claim_writer(run.id, when=timestamp)
            event = thread.record_event(
                kind=AgentEventKind.RUN_CLAIMED,
                payload=AgentEventPayload(
                    message=f"Agent run claimed by worker {run.lease_owner}",
                    run_status=run.status,
                ),
                run_id=run.id,
                when=timestamp,
            )
            await repository.save_run(run)
            await repository.save_environment(environment)
            await repository.save_thread(thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            return RunClaim(
                run=run,
                lease_token=lease_token,
                fencing_token=run.fencing_token,
            )

    async def start_run(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        lease_token: UUID,
        fencing_token: int,
        when: datetime | None = None,
    ) -> AgentRun:
        timestamp = when or _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            context = await _lock_run_context(repository, workspace_id, run_id)
            run = context.run
            _assert_worker_lease(
                run,
                lease_token=lease_token,
                fencing_token=fencing_token,
                when=timestamp,
            )
            run.start(lease_token, when=timestamp)
            event = context.thread.record_event(
                kind=AgentEventKind.RUN_STATUS_CHANGED,
                payload=AgentEventPayload(
                    message="Agent run started",
                    run_status=run.status,
                ),
                run_id=run.id,
                when=timestamp,
            )
            await repository.save_run(run)
            await repository.save_thread(context.thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            return run

    async def heartbeat_run(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        lease_token: UUID,
        fencing_token: int,
        lease_duration: timedelta,
        when: datetime | None = None,
    ) -> AgentRun:
        if lease_duration <= timedelta(0) or lease_duration > timedelta(hours=1):
            raise AgentAuthoringError(
                "Agent run lease duration must be positive and at most one hour"
            )
        timestamp = when or _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            run = await unit_of_work.agent_authoring.lock_run(workspace_id, run_id)
            if run is None:
                raise NotFoundError("Agent run", str(run_id))
            _assert_worker_lease(
                run,
                lease_token=lease_token,
                fencing_token=fencing_token,
                when=timestamp,
            )
            run.heartbeat(
                lease_token,
                lease_expires_at=timestamp + lease_duration,
                when=timestamp,
            )
            await unit_of_work.agent_authoring.save_run(run)
            await unit_of_work.commit()
            return run

    async def advance_build(
        self,
        *,
        workspace_id: UUID,
        build_attempt_id: UUID,
        status: NodeBuildStatus,
        lease_token: UUID,
        fencing_token: int,
        when: datetime | None = None,
    ) -> NodeBuildAttempt:
        if status in {
            NodeBuildStatus.AWAITING_APPROVAL,
            NodeBuildStatus.PUBLISHED,
        }:
            raise AgentAuthoringError(
                "Approval and publication require their dedicated operations"
            )
        timestamp = when or _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            context = await _lock_build_context(
                repository,
                workspace_id,
                build_attempt_id,
            )
            run = context.run
            build = context.build
            _assert_worker_lease(
                run,
                lease_token=lease_token,
                fencing_token=fencing_token,
                when=timestamp,
            )
            if run.status is not AgentRunStatus.RUNNING:
                raise AgentAuthoringConflictError(
                    "Build progress requires a running agent run"
                )
            build.advance(status, when=timestamp)
            event = context.thread.record_event(
                kind=AgentEventKind.BUILD_STATUS_CHANGED,
                payload=AgentEventPayload(
                    message=f"Node build entered {build.status.value}",
                    draft_node_id=build.draft_node_id,
                    build_attempt_id=build.id,
                    run_status=run.status,
                    build_status=build.status,
                ),
                run_id=run.id,
                when=timestamp,
            )
            await repository.save_build_attempt(build)
            await repository.save_thread(context.thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            return build

    async def append_run_message(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        message: str,
        lease_token: UUID,
        fencing_token: int,
        draft_node_id: UUID | None = None,
        build_attempt_id: UUID | None = None,
        when: datetime | None = None,
    ) -> AgentEvent:
        timestamp = when or _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            context = await _lock_run_context(repository, workspace_id, run_id)
            run = context.run
            _assert_worker_lease(
                run,
                lease_token=lease_token,
                fencing_token=fencing_token,
                when=timestamp,
            )
            event = context.thread.record_event(
                kind=AgentEventKind.MESSAGE,
                payload=AgentEventPayload(
                    message=message,
                    draft_node_id=draft_node_id,
                    build_attempt_id=build_attempt_id,
                    run_status=run.status,
                ),
                run_id=run.id,
                when=timestamp,
            )
            await repository.save_thread(context.thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            return event

    async def request_build_approval(
        self,
        *,
        workspace_id: UUID,
        build_attempt_id: UUID,
        manifest: GeneratedNodeManifest,
        capabilities: CapabilityManifest,
        artifacts: BuildArtifactSet,
        lease_token: UUID,
        fencing_token: int,
        when: datetime | None = None,
    ) -> NodeBuildAttempt:
        timestamp = when or _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            context = await _lock_build_context(
                repository,
                workspace_id,
                build_attempt_id,
            )
            run = context.run
            draft = context.draft
            build = context.build
            _assert_worker_lease(
                run,
                lease_token=lease_token,
                fencing_token=fencing_token,
                when=timestamp,
            )
            build.request_approval(
                anchor=draft.anchor,
                manifest=manifest,
                capabilities=capabilities,
                artifacts=artifacts,
                when=timestamp,
            )
            draft.await_approval(when=timestamp)
            event = context.thread.record_event(
                kind=AgentEventKind.CAPABILITIES_REQUESTED,
                payload=AgentEventPayload(
                    message="Generated node is ready for capability review",
                    draft_node_id=draft.id,
                    build_attempt_id=build.id,
                    run_status=run.status,
                    build_status=build.status,
                    capability_digest=build.capability_digest,
                ),
                run_id=run.id,
                when=timestamp,
            )
            await repository.save_build_attempt(build)
            await repository.save_draft(draft)
            await repository.save_thread(context.thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            return build

    async def complete_run_awaiting_approval(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        lease_token: UUID,
        fencing_token: int,
        when: datetime | None = None,
    ) -> AgentRun:
        """Release the writer only after the provider session has returned."""

        timestamp = when or _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            context = await _lock_run_context(repository, workspace_id, run_id)
            run = context.run
            _assert_worker_lease(
                run,
                lease_token=lease_token,
                fencing_token=fencing_token,
                when=timestamp,
            )
            targets = await _lock_run_targets(repository, workspace_id, run)
            builds = targets.builds
            if not builds or any(
                build.status is not NodeBuildStatus.AWAITING_APPROVAL
                for build in builds
            ):
                raise AgentAuthoringConflictError(
                    "Every targeted build must await approval before the run can "
                    "release its environment writer"
            )
            run.await_approval(lease_token, when=timestamp)
            context.environment.release_writer(run.id, when=timestamp)
            event = context.thread.record_event(
                kind=AgentEventKind.RUN_STATUS_CHANGED,
                payload=AgentEventPayload(
                    message="Agent run finished coding and awaits publication",
                    run_status=run.status,
                ),
                run_id=run.id,
                when=timestamp,
            )
            await repository.save_run(run)
            await repository.save_environment(context.environment)
            await repository.save_thread(context.thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            return run

    async def approve_build(
        self,
        *,
        workspace_id: UUID,
        build_attempt_id: UUID,
        capability_digest: str,
        approved_by_user_id: UUID,
        when: datetime | None = None,
    ) -> CapabilityApproval:
        timestamp = when or _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            context = await _lock_build_context(
                repository,
                workspace_id,
                build_attempt_id,
            )
            build = context.build
            if context.run.status is not AgentRunStatus.AWAITING_APPROVAL:
                raise AgentAuthoringConflictError(
                    "Build approval requires an approval-waiting agent run"
                )
            if build.status is not NodeBuildStatus.AWAITING_APPROVAL:
                raise AgentAuthoringConflictError(
                    "Only a build awaiting approval can be approved"
                )
            if build.capability_digest != capability_digest:
                raise AgentAuthoringConflictError(
                    "Capability approval digest does not match the reviewed build"
                )
            existing = await repository.get_capability_approval(
                workspace_id,
                build.id,
            )
            if existing is not None:
                if existing.capability_digest != capability_digest:
                    raise AgentAuthoringConflictError(
                        "Build already has a different capability approval"
                    )
                return existing
            approval = CapabilityApproval(
                workspace_id=workspace_id,
                draft_node_id=build.draft_node_id,
                build_attempt_id=build.id,
                capability_digest=capability_digest,
                approved_by_user_id=approved_by_user_id,
                approved_at=timestamp,
            )
            event = context.thread.record_event(
                kind=AgentEventKind.CAPABILITIES_APPROVED,
                payload=AgentEventPayload(
                    message="Generated node capabilities approved",
                    draft_node_id=build.draft_node_id,
                    build_attempt_id=build.id,
                    build_status=build.status,
                    capability_digest=capability_digest,
                ),
                run_id=build.run_id,
                when=timestamp,
            )
            await repository.add_capability_approval(approval)
            await repository.save_thread(context.thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            return approval

    async def publish_build(
        self,
        *,
        workspace_id: UUID,
        build_attempt_id: UUID,
        capability_approval_id: UUID,
        published_by_user_id: UUID,
        when: datetime | None = None,
    ) -> NodePublication:
        async with self._unit_of_work_factory() as unit_of_work:
            publication = await self.publish_build_in_unit_of_work(
                unit_of_work,
                workspace_id=workspace_id,
                build_attempt_id=build_attempt_id,
                capability_approval_id=capability_approval_id,
                published_by_user_id=published_by_user_id,
                when=when,
            )
            await unit_of_work.commit()
            return publication

    async def publish_build_in_unit_of_work(
        self,
        unit_of_work: AgentAuthoringUnitOfWorkPort,
        *,
        workspace_id: UUID,
        build_attempt_id: UUID,
        capability_approval_id: UUID,
        published_by_user_id: UUID,
        when: datetime | None = None,
    ) -> NodePublication:
        timestamp = when or _utc_now()
        repository = unit_of_work.agent_authoring
        context = await _lock_build_context(
            repository,
            workspace_id,
            build_attempt_id,
        )
        build = context.build
        draft = context.draft
        run = context.run
        if build.status is NodeBuildStatus.PUBLISHED:
            matching_releases = [
                release
                for release in await repository.list_releases(workspace_id)
                if release.build_attempt_id == build.id
            ]
            if len(matching_releases) != 1:
                raise AgentAuthoringConflictError(
                    "Published build is missing its immutable release"
                )
            release = matching_releases[0]
            if release.capability_approval_id != capability_approval_id:
                raise AgentAuthoringConflictError(
                    "Publishing requires approval of the exact capability manifest"
                )
            return NodePublication(draft=draft, build=build, run=run, release=release)
        if build.status is not NodeBuildStatus.AWAITING_APPROVAL:
            raise AgentAuthoringConflictError(
                "Only an approval-waiting build can be published"
            )
        approval = await repository.get_capability_approval(
            workspace_id,
            build.id,
        )
        if (
            approval is None
            or approval.id != capability_approval_id
            or approval.capability_digest != build.capability_digest
        ):
            raise AgentAuthoringConflictError(
                "Publishing requires approval of the exact capability manifest"
            )
        if (
            build.manifest is None
            or build.capabilities is None
            or build.capability_digest is None
            or build.artifacts is None
        ):
            raise AgentAuthoringConflictError(
                "Approval-waiting build is missing release artifacts"
            )
        revision = draft.published_revision + 1
        release = NodeRelease(
            workspace_id=workspace_id,
            node_id=draft.id,
            revision=revision,
            draft_node_id=draft.id,
            build_attempt_id=build.id,
            thread_id=context.thread.id,
            environment_id=run.environment_id,
            manifest=build.manifest,
            capabilities=build.capabilities,
            capability_digest=build.capability_digest,
            artifacts=build.artifacts,
            capability_approval_id=approval.id,
            approved_by_user_id=approval.approved_by_user_id,
            created_by_user_id=published_by_user_id,
            created_at=timestamp,
        )
        build.advance(NodeBuildStatus.PUBLISHED, when=timestamp)
        draft.publish(revision, when=timestamp)
        run_builds = await repository.list_build_attempts_for_run(
            workspace_id,
            run.id,
        )
        every_build_is_published = all(
            candidate.id == build.id or candidate.status is NodeBuildStatus.PUBLISHED
            for candidate in run_builds
        )
        if every_build_is_published:
            run.complete(when=timestamp)
        event = context.thread.record_event(
            kind=AgentEventKind.RELEASE_PUBLISHED,
            payload=AgentEventPayload(
                message="Generated node release published",
                draft_node_id=draft.id,
                build_attempt_id=build.id,
                run_status=run.status,
                build_status=build.status,
                capability_digest=release.capability_digest,
                release_revision=release.revision,
            ),
            run_id=run.id,
            when=timestamp,
        )
        await repository.add_release(release)
        await repository.save_build_attempt(build)
        await repository.save_draft(draft)
        await repository.save_run(run)
        await repository.save_thread(context.thread)
        await repository.add_event(event)
        return NodePublication(draft=draft, build=build, run=run, release=release)

    async def cancel_run(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        when: datetime | None = None,
    ) -> AgentRun:
        cancellation = await self.request_run_cancellation(
            workspace_id=workspace_id,
            run_id=run_id,
            when=when,
        )
        return cancellation.run

    async def request_run_cancellation(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        when: datetime | None = None,
    ) -> RunCancellationRequest:
        timestamp = when or _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            context = await _lock_run_context(repository, workspace_id, run_id)
            run = context.run
            revoked_lease = run.request_cancellation(when=timestamp)
            if run.status is AgentRunStatus.CANCELLED:
                targets = await _lock_run_targets(
                    repository,
                    workspace_id,
                    run,
                )
                await _cancel_locked_targets(
                    repository,
                    targets,
                    when=timestamp,
                )
                context.environment.release_writer(run.id, when=timestamp)
                await repository.save_environment(context.environment)
            event = context.thread.record_event(
                kind=AgentEventKind.RUN_STATUS_CHANGED,
                payload=AgentEventPayload(
                    message=f"Agent run entered {run.status.value}",
                    run_status=run.status,
                ),
                run_id=run.id,
                when=timestamp,
            )
            await repository.save_run(run)
            await repository.save_thread(context.thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            revocation_fencing_token: int | None = None
            if run.status is AgentRunStatus.CANCELLING:
                revocation_fencing_token = run.fencing_token
            return RunCancellationRequest(
                run=run,
                revoked_lease=revoked_lease,
                revocation_fencing_token=revocation_fencing_token,
            )

    async def confirm_run_cancelled(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        revocation_fencing_token: int,
        when: datetime | None = None,
    ) -> AgentRun:
        timestamp = when or _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            context = await _lock_run_context(repository, workspace_id, run_id)
            run = context.run
            run.confirm_cancelled(
                revocation_fencing_token,
                when=timestamp,
            )
            targets = await _lock_run_targets(
                repository,
                workspace_id,
                run,
            )
            await _cancel_locked_targets(repository, targets, when=timestamp)
            context.environment.release_writer(run.id, when=timestamp)
            event = context.thread.record_event(
                kind=AgentEventKind.RUN_STATUS_CHANGED,
                payload=AgentEventPayload(
                    message="Agent run cancelled after sandbox termination",
                    run_status=run.status,
                ),
                run_id=run.id,
                when=timestamp,
            )
            await repository.save_run(run)
            await repository.save_environment(context.environment)
            await repository.save_thread(context.thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            return run

    async def fail_run(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        error: str,
        lease_token: UUID,
        fencing_token: int,
        when: datetime | None = None,
    ) -> AgentRun:
        timestamp = when or _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            context = await _lock_run_context(repository, workspace_id, run_id)
            run = context.run
            _assert_worker_lease(
                run,
                lease_token=lease_token,
                fencing_token=fencing_token,
                when=timestamp,
            )
            run.fail(error, lease_token=lease_token, when=timestamp)
            targets = await _lock_run_targets(
                repository,
                workspace_id,
                run,
            )
            await _fail_locked_targets(
                repository,
                targets,
                error=error,
                when=timestamp,
            )
            context.environment.release_writer(run.id, when=timestamp)
            event = context.thread.record_event(
                kind=AgentEventKind.RUN_STATUS_CHANGED,
                payload=AgentEventPayload(
                    message="Agent run failed",
                    run_status=run.status,
                ),
                run_id=run.id,
                when=timestamp,
            )
            await repository.save_run(run)
            await repository.save_environment(context.environment)
            await repository.save_thread(context.thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            return run

    async def fence_expired_run(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        when: datetime | None = None,
    ) -> RunRevocation:
        timestamp = when or _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            run = await repository.lock_expired_running_run(
                workspace_id,
                run_id,
                when=timestamp,
            )
            if run is None:
                raise AgentAuthoringConflictError(
                    f"Agent run {run_id} is not an expired running run"
                )
            environment = await repository.lock_environment(
                workspace_id,
                run.environment_id,
            )
            thread = await repository.lock_thread(workspace_id, run.thread_id)
            if environment is None:
                raise NotFoundError("Agent environment", str(run.environment_id))
            if thread is None:
                raise NotFoundError("Agent thread", str(run.thread_id))
            revoked_lease = run.begin_interruption(when=timestamp)
            event = thread.record_event(
                kind=AgentEventKind.RUN_STATUS_CHANGED,
                payload=AgentEventPayload(
                    message="Expired agent run fenced pending sandbox termination",
                    run_status=run.status,
                ),
                run_id=run.id,
                when=timestamp,
            )
            await repository.save_run(run)
            await repository.save_thread(thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            return RunRevocation(
                run=run,
                revoked_lease=revoked_lease,
                revocation_fencing_token=run.fencing_token,
            )

    async def confirm_run_interrupted(
        self,
        *,
        workspace_id: UUID,
        run_id: UUID,
        revocation_fencing_token: int,
        when: datetime | None = None,
    ) -> AgentRun:
        timestamp = when or _utc_now()
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            context = await _lock_run_context(repository, workspace_id, run_id)
            run = context.run
            run.confirm_interrupted(
                revocation_fencing_token,
                when=timestamp,
            )
            targets = await _lock_run_targets(
                repository,
                workspace_id,
                run,
            )
            await _fail_locked_targets(
                repository,
                targets,
                error=(run.terminal_error or "Agent run interrupted"),
                when=timestamp,
            )
            context.environment.release_writer(run.id, when=timestamp)
            event = context.thread.record_event(
                kind=AgentEventKind.RUN_STATUS_CHANGED,
                payload=AgentEventPayload(
                    message=(run.terminal_error or "Agent run interrupted"),
                    run_status=run.status,
                ),
                run_id=run.id,
                when=timestamp,
            )
            await repository.save_run(run)
            await repository.save_environment(context.environment)
            await repository.save_thread(context.thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            return run

    async def queue_continuation(
        self,
        *,
        workspace_id: UUID,
        interrupted_run_id: UUID,
        idempotency_key: str,
        instructions: str | None = None,
        created_by_user_id: UUID | None = None,
        when: datetime | None = None,
    ) -> RunContinuation:
        timestamp = when or _utc_now()
        normalized_key = idempotency_key.strip()
        if normalized_key == "" or len(normalized_key) > 255:
            raise AgentAuthoringError(
                "Continuation idempotency key must contain 1 to 255 characters"
            )
        async with self._unit_of_work_factory() as unit_of_work:
            repository = unit_of_work.agent_authoring
            context = await _lock_run_context(
                repository,
                workspace_id,
                interrupted_run_id,
            )
            interrupted = context.run
            if interrupted.status is not AgentRunStatus.INTERRUPTED:
                raise AgentAuthoringConflictError(
                    "Only an explicitly interrupted run can be continued"
                )
            continuation_instructions = _normalized_prompt(
                instructions if instructions is not None else interrupted.instructions
            )
            digest = _request_digest(
                {
                    "workspace_id": str(workspace_id),
                    "continued_from_run_id": str(interrupted.id),
                    "target_draft_ids": [
                        str(draft_id) for draft_id in interrupted.target_draft_ids
                    ],
                    "instructions": continuation_instructions,
                    "created_by_user_id": (
                        str(created_by_user_id)
                        if created_by_user_id is not None
                        else None
                    ),
                }
            )
            existing = await repository.get_run_by_idempotency(
                workspace_id,
                normalized_key,
            )
            if existing is not None:
                if (
                    existing.request_digest != digest
                    or existing.continued_from_run_id != interrupted.id
                ):
                    raise AgentAuthoringIdempotencyError(
                        f"Idempotency key {normalized_key!r} was reused for a "
                        "different continuation"
                    )
                builds = await repository.list_build_attempts_for_run(
                    workspace_id,
                    existing.id,
                )
                return RunContinuation(
                    interrupted_run_id=interrupted.id,
                    run=existing,
                    builds=tuple(builds),
                )
            if context.environment.status in {
                AgentEnvironmentStatus.FAILED,
                AgentEnvironmentStatus.ARCHIVED,
            }:
                raise AgentAuthoringConflictError(
                    f"Environment {context.environment.id} cannot continue authoring"
                )
            continuation = AgentRun(
                workspace_id=workspace_id,
                thread_id=interrupted.thread_id,
                environment_id=interrupted.environment_id,
                target_draft_ids=interrupted.target_draft_ids,
                instructions=continuation_instructions,
                idempotency_key=normalized_key,
                request_digest=digest,
                created_by_user_id=created_by_user_id,
                continued_from_run_id=interrupted.id,
                created_at=timestamp,
                updated_at=timestamp,
            )
            builds: list[NodeBuildAttempt] = []
            drafts: dict[UUID, DraftNode] = {}
            for draft_node_id in sorted(interrupted.target_draft_ids, key=str):
                draft = await repository.lock_draft(workspace_id, draft_node_id)
                if draft is None:
                    raise NotFoundError("Draft node", str(draft_node_id))
                attempts = await repository.list_build_attempts_for_draft(
                    workspace_id,
                    draft.id,
                )
                if any(attempt.is_active for attempt in attempts):
                    raise AgentAuthoringConflictError(
                        f"Draft {draft.id} already has an active build attempt"
                    )
                drafts[draft.id] = draft
            await repository.add_run(continuation)
            for draft_node_id in interrupted.target_draft_ids:
                draft = drafts[draft_node_id]
                attempt_number = draft.begin_build(when=timestamp)
                build = NodeBuildAttempt(
                    workspace_id=workspace_id,
                    thread_id=context.thread.id,
                    draft_node_id=draft.id,
                    run_id=continuation.id,
                    attempt_number=attempt_number,
                    prompt=continuation_instructions,
                    created_at=timestamp,
                    updated_at=timestamp,
                )
                builds.append(build)
                await repository.save_draft(draft)
                await repository.add_build_attempt(build)
            event = context.thread.record_event(
                kind=AgentEventKind.RUN_QUEUED,
                payload=AgentEventPayload(
                    message=f"Continuation queued after interrupted run {interrupted.id}",
                    run_status=continuation.status,
                ),
                run_id=continuation.id,
                when=timestamp,
            )
            await repository.save_thread(context.thread)
            await repository.add_event(event)
            await unit_of_work.commit()
            return RunContinuation(
                interrupted_run_id=interrupted.id,
                run=continuation,
                builds=tuple(builds),
            )

    async def list_events(
        self,
        *,
        workspace_id: UUID,
        thread_id: UUID,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> list[AgentEvent]:
        if after_sequence < 0:
            raise AgentAuthoringError("Agent event cursor must not be negative")
        if limit < 1 or limit > 1_000:
            raise AgentAuthoringError("Agent event limit must be between 1 and 1000")
        async with self._unit_of_work_factory() as unit_of_work:
            thread = await unit_of_work.agent_authoring.get_thread(
                workspace_id,
                thread_id,
            )
            if thread is None:
                raise NotFoundError("Agent thread", str(thread_id))
            return await unit_of_work.agent_authoring.list_events(
                workspace_id,
                thread_id,
                after_sequence=after_sequence,
                limit=limit,
            )

    async def list_releases(self, workspace_id: UUID) -> list[NodeRelease]:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.agent_authoring.list_releases(workspace_id)

    async def get_release(
        self,
        *,
        workspace_id: UUID,
        node_id: UUID,
        revision: int,
    ) -> NodeRelease:
        if isinstance(revision, bool) or revision < 1:
            raise AgentAuthoringError("Node release revision must be positive")
        async with self._unit_of_work_factory() as unit_of_work:
            release = await unit_of_work.agent_authoring.get_release(
                workspace_id,
                node_id,
                revision,
            )
            if release is None:
                raise NotFoundError("Generated node release", f"{node_id}@{revision}")
            return release

    async def get_capability_approval(
        self,
        *,
        workspace_id: UUID,
        build_attempt_id: UUID,
    ) -> CapabilityApproval | None:
        async with self._unit_of_work_factory() as unit_of_work:
            return await unit_of_work.agent_authoring.get_capability_approval(
                workspace_id,
                build_attempt_id,
            )


__all__ = [
    "AgentAuthoringService",
    "DraftCreation",
    "DraftDetail",
    "EnvironmentProvisioningClaim",
    "FollowUpRun",
    "NodePublication",
    "RunClaim",
    "RunCancellationRequest",
    "RunContinuation",
    "RunRevocation",
]
