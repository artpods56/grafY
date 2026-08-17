from datetime import UTC, datetime, timedelta
from types import TracebackType
from uuid import UUID, uuid4

import pytest

from grafy_core.application.agent_authoring import AgentAuthoringService
from grafy_core.domain.agent_authoring import (
    AgentArtifactType,
    AgentAuthoringConflictError,
    AgentAuthoringIdempotencyError,
    AgentEnvironment,
    AgentEnvironmentStatus,
    AgentEvent,
    AgentPortDirection,
    AgentRun,
    AgentRunStatus,
    AgentThread,
    AnchoredPortContract,
    BuildArtifactSet,
    CapabilityApproval,
    CapabilityManifest,
    DraftNode,
    DraftNodeStatus,
    GeneratedNodeManifest,
    GeneratedNodePort,
    NodeBuildAttempt,
    NodeBuildStatus,
    NodeRelease,
    RuntimeArtifactReference,
)
from grafy_core.nodes import PortShape


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000951")
GRAPH_ID = UUID("00000000-0000-0000-0000-000000000952")
USER_ID = UUID("00000000-0000-0000-0000-000000000953")
NOW = datetime(2026, 8, 17, 8, tzinfo=UTC)


class FakeAgentAuthoringRepository:
    def __init__(self) -> None:
        self.environments: dict[tuple[UUID, UUID], AgentEnvironment] = {}
        self.threads: dict[tuple[UUID, UUID], AgentThread] = {}
        self.drafts: dict[tuple[UUID, UUID], DraftNode] = {}
        self.runs: dict[tuple[UUID, UUID], AgentRun] = {}
        self.builds: dict[tuple[UUID, UUID], NodeBuildAttempt] = {}
        self.events: list[AgentEvent] = []
        self.approvals: dict[tuple[UUID, UUID], CapabilityApproval] = {}
        self.releases: dict[tuple[UUID, UUID, int], NodeRelease] = {}
        self.lock_calls: list[tuple[str, UUID]] = []

    async def add_environment(self, environment: AgentEnvironment) -> None:
        self.environments[(environment.workspace_id, environment.id)] = environment

    async def get_environment(
        self,
        workspace_id: UUID,
        environment_id: UUID,
    ) -> AgentEnvironment | None:
        return self.environments.get((workspace_id, environment_id))

    async def lock_environment(
        self,
        workspace_id: UUID,
        environment_id: UUID,
    ) -> AgentEnvironment | None:
        self.lock_calls.append(("environment", environment_id))
        return await self.get_environment(workspace_id, environment_id)

    async def save_environment(self, environment: AgentEnvironment) -> None:
        self.environments[(environment.workspace_id, environment.id)] = environment

    async def list_environments(
        self,
        workspace_id: UUID,
    ) -> list[AgentEnvironment]:
        return [
            environment
            for (owner, _), environment in self.environments.items()
            if owner == workspace_id
        ]

    async def list_provisionable_environment_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        keys = [
            key
            for key, environment in self.environments.items()
            if environment.status.value == "provisioning"
            or (
                environment.status.value == "creating"
                and environment.provisioning_lease_is_expired(when)
            )
        ]
        return sorted(keys, key=lambda key: (str(key[0]), str(key[1])))[:limit]

    async def lock_provisionable_environment(
        self,
        workspace_id: UUID,
        environment_id: UUID,
        *,
        when: datetime,
    ) -> AgentEnvironment | None:
        self.lock_calls.append(("environment", environment_id))
        environment = await self.get_environment(workspace_id, environment_id)
        if environment is None:
            return None
        if environment.status.value == "provisioning" or (
            environment.status.value == "creating"
            and environment.provisioning_lease_is_expired(when)
        ):
            return environment
        return None

    async def add_thread(self, thread: AgentThread) -> None:
        self.threads[(thread.workspace_id, thread.id)] = thread

    async def get_thread(
        self,
        workspace_id: UUID,
        thread_id: UUID,
    ) -> AgentThread | None:
        return self.threads.get((workspace_id, thread_id))

    async def lock_thread(
        self,
        workspace_id: UUID,
        thread_id: UUID,
    ) -> AgentThread | None:
        self.lock_calls.append(("thread", thread_id))
        return await self.get_thread(workspace_id, thread_id)

    async def save_thread(self, thread: AgentThread) -> None:
        self.threads[(thread.workspace_id, thread.id)] = thread

    async def add_draft(self, draft: DraftNode) -> None:
        self.drafts[(draft.workspace_id, draft.id)] = draft

    async def get_draft(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> DraftNode | None:
        return self.drafts.get((workspace_id, draft_node_id))

    async def lock_draft(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> DraftNode | None:
        self.lock_calls.append(("draft", draft_node_id))
        return await self.get_draft(workspace_id, draft_node_id)

    async def save_draft(self, draft: DraftNode) -> None:
        self.drafts[(draft.workspace_id, draft.id)] = draft

    async def list_drafts(
        self,
        workspace_id: UUID,
        *,
        thread_id: UUID | None = None,
    ) -> list[DraftNode]:
        return [
            draft
            for (owner, _), draft in self.drafts.items()
            if owner == workspace_id
            and (thread_id is None or draft.thread_id == thread_id)
        ]

    async def add_run(self, run: AgentRun) -> None:
        self.runs[(run.workspace_id, run.id)] = run

    async def get_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> AgentRun | None:
        return self.runs.get((workspace_id, run_id))

    async def lock_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> AgentRun | None:
        self.lock_calls.append(("run", run_id))
        return await self.get_run(workspace_id, run_id)

    async def lock_claimable_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        when: datetime,
    ) -> AgentRun | None:
        self.lock_calls.append(("run", run_id))
        run = await self.get_run(workspace_id, run_id)
        if run is None:
            return None
        environment = await self.get_environment(workspace_id, run.environment_id)
        if environment is None:
            return None
        queued_and_free = (
            run.status is AgentRunStatus.QUEUED
            and environment.active_run_id is None
        )
        expired_claim_and_same_writer = (
            run.status is AgentRunStatus.CLAIMED
            and run.lease_is_expired(when)
            and environment.active_run_id == run.id
        )
        if queued_and_free or expired_claim_and_same_writer:
            return run
        return None

    async def lock_expired_running_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
        *,
        when: datetime,
    ) -> AgentRun | None:
        self.lock_calls.append(("run", run_id))
        run = await self.get_run(workspace_id, run_id)
        if run is None:
            return None
        environment = await self.get_environment(workspace_id, run.environment_id)
        if (
            run.status is AgentRunStatus.RUNNING
            and run.lease_is_expired(when)
            and environment is not None
            and environment.active_run_id == run.id
        ):
            return run
        return None

    async def save_run(self, run: AgentRun) -> None:
        self.runs[(run.workspace_id, run.id)] = run

    async def get_run_by_idempotency(
        self,
        workspace_id: UUID,
        idempotency_key: str,
    ) -> AgentRun | None:
        return next(
            (
                run
                for (owner, _), run in self.runs.items()
                if owner == workspace_id and run.idempotency_key == idempotency_key
            ),
            None,
        )

    async def list_runs_for_thread(
        self,
        workspace_id: UUID,
        thread_id: UUID,
    ) -> list[AgentRun]:
        runs = [
            run
            for (owner, _), run in self.runs.items()
            if owner == workspace_id and run.thread_id == thread_id
        ]
        return sorted(runs, key=lambda run: (run.created_at, run.id))

    async def list_claimable_run_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        keys = [
            key
            for key, run in self.runs.items()
            if run.status is AgentRunStatus.QUEUED
            or (
                run.status is AgentRunStatus.CLAIMED
                and run.lease_is_expired(when)
            )
        ]
        return keys[:limit]

    async def list_expired_running_run_keys(
        self,
        *,
        when: datetime,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        return [
            key
            for key, run in self.runs.items()
            if run.status is AgentRunStatus.RUNNING and run.lease_is_expired(when)
        ][:limit]

    async def list_interrupting_run_keys(
        self,
        *,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        return [
            key
            for key, run in self.runs.items()
            if run.status is AgentRunStatus.INTERRUPTING
        ][:limit]

    async def list_cancelling_run_keys(
        self,
        *,
        limit: int,
    ) -> list[tuple[UUID, UUID]]:
        return [
            key
            for key, run in self.runs.items()
            if run.status is AgentRunStatus.CANCELLING
        ][:limit]

    async def add_build_attempt(self, build: NodeBuildAttempt) -> None:
        self.builds[(build.workspace_id, build.id)] = build

    async def get_build_attempt(
        self,
        workspace_id: UUID,
        build_attempt_id: UUID,
    ) -> NodeBuildAttempt | None:
        return self.builds.get((workspace_id, build_attempt_id))

    async def lock_build_attempt(
        self,
        workspace_id: UUID,
        build_attempt_id: UUID,
    ) -> NodeBuildAttempt | None:
        self.lock_calls.append(("build", build_attempt_id))
        return await self.get_build_attempt(workspace_id, build_attempt_id)

    async def save_build_attempt(self, build: NodeBuildAttempt) -> None:
        self.builds[(build.workspace_id, build.id)] = build

    async def list_build_attempts_for_run(
        self,
        workspace_id: UUID,
        run_id: UUID,
    ) -> list[NodeBuildAttempt]:
        return [
            build
            for (owner, _), build in self.builds.items()
            if owner == workspace_id and build.run_id == run_id
        ]

    async def list_build_attempts_for_draft(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> list[NodeBuildAttempt]:
        builds = [
            build
            for (owner, _), build in self.builds.items()
            if owner == workspace_id and build.draft_node_id == draft_node_id
        ]
        return sorted(builds, key=lambda build: (build.attempt_number, build.id))

    async def get_latest_build_attempt_for_draft(
        self,
        workspace_id: UUID,
        draft_node_id: UUID,
    ) -> NodeBuildAttempt | None:
        builds = await self.list_build_attempts_for_draft(
            workspace_id,
            draft_node_id,
        )
        return builds[-1] if builds else None

    async def add_event(self, event: AgentEvent) -> None:
        self.events.append(event)

    async def list_events(
        self,
        workspace_id: UUID,
        thread_id: UUID,
        *,
        after_sequence: int,
        limit: int,
    ) -> list[AgentEvent]:
        events = [
            event
            for event in self.events
            if event.workspace_id == workspace_id
            and event.thread_id == thread_id
            and event.sequence > after_sequence
        ]
        return sorted(events, key=lambda event: event.sequence)[:limit]

    async def add_capability_approval(
        self,
        approval: CapabilityApproval,
    ) -> None:
        self.approvals[(approval.workspace_id, approval.build_attempt_id)] = approval

    async def get_capability_approval(
        self,
        workspace_id: UUID,
        build_attempt_id: UUID,
    ) -> CapabilityApproval | None:
        return self.approvals.get((workspace_id, build_attempt_id))

    async def add_release(self, release: NodeRelease) -> None:
        self.releases[(release.workspace_id, release.node_id, release.revision)] = (
            release
        )

    async def get_release(
        self,
        workspace_id: UUID,
        node_id: UUID,
        revision: int,
    ) -> NodeRelease | None:
        return self.releases.get((workspace_id, node_id, revision))

    async def list_releases(self, workspace_id: UUID) -> list[NodeRelease]:
        return [
            release
            for (owner, _, _), release in self.releases.items()
            if owner == workspace_id
        ]


class FakeAgentAuthoringUnitOfWork:
    def __init__(self, repository: FakeAgentAuthoringRepository) -> None:
        self.agent_authoring = repository
        self.commit_count = 0
        self.rollback_count = 0

    async def __aenter__(self) -> "FakeAgentAuthoringUnitOfWork":
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc, traceback

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


def anchor() -> AnchoredPortContract:
    return AnchoredPortContract(
        direction=AgentPortDirection.INPUT,
        name="texts",
        artifact_type=AgentArtifactType(id="scalar.text", schema_version=1),
        shape=PortShape.MANY,
    )


def build_artifacts() -> BuildArtifactSet:
    return BuildArtifactSet(
        source_bundle_key="nodes/source.tar.zst",
        source_digest="1" * 64,
        lock_digest="2" * 64,
        tests_digest="3" * 64,
        build_digest="4" * 64,
        implementation_digest="5" * 64,
        runtime_image_digest="6" * 64,
        profile_digest="7" * 64,
        runtime_artifact=RuntimeArtifactReference(
            provider="docker-trusted-development",
            ref="snapshot-generated-node-v1",
            digest="8" * 64,
        ),
        tests_passed=True,
    )


async def ready_environment(
    service: AgentAuthoringService,
) -> AgentEnvironment:
    environment = await service.create_environment(
        workspace_id=WORKSPACE_ID,
        name="Python agent",
        profile_id="python-3.12-uv",
        provider="docker-trusted-development",
        created_by_user_id=USER_ID,
    )
    claim = await service.claim_environment_provisioning(
        workspace_id=WORKSPACE_ID,
        environment_id=environment.id,
        worker_id="provisioner-a",
        lease_duration=timedelta(minutes=5),
        when=NOW,
    )
    return await service.complete_environment_provisioning(
        workspace_id=WORKSPACE_ID,
        environment_id=environment.id,
        provider_environment_id="sandbox-1",
        provisioning_token=claim.provisioning_token,
        provisioning_fencing_token=claim.provisioning_fencing_token,
        when=NOW,
    )


@pytest.mark.asyncio
async def test_draft_creation_can_share_one_thread_and_stage_without_commit() -> None:
    repository = FakeAgentAuthoringRepository()
    unit_of_work = FakeAgentAuthoringUnitOfWork(repository)
    service = AgentAuthoringService(lambda: unit_of_work)
    environment = await ready_environment(service)
    commits_before_staging = unit_of_work.commit_count

    first = await service.create_draft_in_unit_of_work(
        unit_of_work,
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        prompt="Append an API result to every text.",
        anchor=anchor(),
        created_by_user_id=USER_ID,
        idempotency_key="draft-1",
        environment_id=environment.id,
    )

    assert unit_of_work.commit_count == commits_before_staging
    assert first.draft.title == "Generated node"
    assert first.draft.operator_id.startswith("generated.node.")
    assert first.run.target_draft_ids == (first.draft.id,)
    assert first.thread.environment_id == environment.id

    replay = await service.create_draft_in_unit_of_work(
        unit_of_work,
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        prompt="Append an API result to every text.",
        anchor=anchor(),
        created_by_user_id=USER_ID,
        idempotency_key="draft-1",
        environment_id=environment.id,
    )
    assert replay.draft.id == first.draft.id
    assert len(repository.drafts) == 1

    second = await service.create_draft(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        prompt="Summarize every text.",
        anchor=anchor(),
        created_by_user_id=USER_ID,
        idempotency_key="draft-2",
        thread_id=first.thread.id,
    )
    assert second.thread.id == first.thread.id
    assert second.environment.id == first.environment.id
    assert second.draft.id != first.draft.id
    assert second.thread.event_sequence == 2

    with pytest.raises(
        AgentAuthoringIdempotencyError,
        match="different draft request",
    ):
        await service.create_draft(
            workspace_id=WORKSPACE_ID,
            graph_id=GRAPH_ID,
            prompt="Different behavior.",
            anchor=anchor(),
            created_by_user_id=USER_ID,
            idempotency_key="draft-1",
            environment_id=environment.id,
        )


@pytest.mark.asyncio
async def test_environment_writer_serializes_runs_from_the_same_thread() -> None:
    repository = FakeAgentAuthoringRepository()
    unit_of_work = FakeAgentAuthoringUnitOfWork(repository)
    service = AgentAuthoringService(lambda: unit_of_work)
    environment = await ready_environment(service)
    first = await service.create_draft(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        prompt="First node",
        anchor=anchor(),
        created_by_user_id=USER_ID,
        idempotency_key="first",
        environment_id=environment.id,
    )
    second = await service.create_draft(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        prompt="Second node",
        anchor=anchor(),
        created_by_user_id=USER_ID,
        idempotency_key="second",
        thread_id=first.thread.id,
    )
    first_claim = await service.claim_run(
        workspace_id=WORKSPACE_ID,
        run_id=first.run.id,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=1),
        when=NOW,
    )

    with pytest.raises(AgentAuthoringConflictError, match="not currently claimable"):
        await service.claim_run(
            workspace_id=WORKSPACE_ID,
            run_id=second.run.id,
            worker_id="worker-b",
            lease_duration=timedelta(minutes=1),
            when=NOW,
        )

    assert first_claim.fencing_token == 1
    assert environment.active_run_id == first.run.id


@pytest.mark.asyncio
async def test_build_publication_requires_exact_approval_and_keeps_operator_identity() -> None:
    repository = FakeAgentAuthoringRepository()
    unit_of_work = FakeAgentAuthoringUnitOfWork(repository)
    service = AgentAuthoringService(lambda: unit_of_work)
    environment = await ready_environment(service)
    creation = await service.create_draft(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        prompt="Append a remote value to each text.",
        anchor=anchor(),
        created_by_user_id=USER_ID,
        idempotency_key="publication",
        environment_id=environment.id,
    )
    claim = await service.claim_run(
        workspace_id=WORKSPACE_ID,
        run_id=creation.run.id,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=5),
        when=NOW,
    )
    await service.start_run(
        workspace_id=WORKSPACE_ID,
        run_id=creation.run.id,
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
        when=NOW,
    )
    for status in (
        NodeBuildStatus.PREPARING,
        NodeBuildStatus.CODING,
        NodeBuildStatus.TESTING,
    ):
        await service.advance_build(
            workspace_id=WORKSPACE_ID,
            build_attempt_id=creation.build.id,
            status=status,
            lease_token=claim.lease_token,
            fencing_token=claim.fencing_token,
            when=NOW,
        )
    output = GeneratedNodePort(
        direction=AgentPortDirection.OUTPUT,
        name="result",
        artifact_type=AgentArtifactType(id="scalar.text", schema_version=1),
        shape=PortShape.MANY,
    )
    manifest = GeneratedNodeManifest(
        title="Remote append",
        description="Appends a remote response to every text.",
        inputs=(GeneratedNodePort.from_anchor(creation.draft.anchor),),
        outputs=(output,),
    )
    capabilities = CapabilityManifest(
        outbound_http_origins=("https://api.example.com",),
        secret_refs=("REMOTE_API_TOKEN",),
    )
    repository.lock_calls.clear()
    awaiting = await service.request_build_approval(
        workspace_id=WORKSPACE_ID,
        build_attempt_id=creation.build.id,
        manifest=manifest,
        capabilities=capabilities,
        artifacts=build_artifacts(),
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
        when=NOW,
    )
    assert [kind for kind, _ in repository.lock_calls] == [
        "run",
        "environment",
        "thread",
        "draft",
        "build",
    ]
    assert awaiting.capability_digest == capabilities.digest
    assert creation.run.status is AgentRunStatus.RUNNING
    assert environment.active_run_id == creation.run.id
    await service.complete_run_awaiting_approval(
        workspace_id=WORKSPACE_ID,
        run_id=creation.run.id,
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
        when=NOW,
    )
    assert creation.run.status is AgentRunStatus.AWAITING_APPROVAL
    assert environment.active_run_id is None

    with pytest.raises(AgentAuthoringConflictError, match="does not match"):
        await service.approve_build(
            workspace_id=WORKSPACE_ID,
            build_attempt_id=creation.build.id,
            capability_digest="f" * 64,
            approved_by_user_id=USER_ID,
            when=NOW,
        )
    approval = await service.approve_build(
        workspace_id=WORKSPACE_ID,
        build_attempt_id=creation.build.id,
        capability_digest=capabilities.digest,
        approved_by_user_id=USER_ID,
        when=NOW,
    )

    with pytest.raises(AgentAuthoringConflictError, match="exact capability"):
        await service.publish_build(
            workspace_id=WORKSPACE_ID,
            build_attempt_id=creation.build.id,
            capability_approval_id=uuid4(),
            published_by_user_id=USER_ID,
            when=NOW,
        )
    publication = await service.publish_build(
        workspace_id=WORKSPACE_ID,
        build_attempt_id=creation.build.id,
        capability_approval_id=approval.id,
        published_by_user_id=USER_ID,
        when=NOW,
    )

    assert publication.release.operator_id == creation.draft.operator_id
    assert publication.release.operator_version == 1
    assert creation.draft.operator_version == 2
    assert publication.release.capability_digest == approval.capability_digest
    assert publication.release.capability_approval_id == approval.id
    assert publication.draft.status is DraftNodeStatus.PUBLISHED
    assert publication.run.status is AgentRunStatus.COMPLETED

    with pytest.raises(AgentAuthoringConflictError, match="exact capability"):
        await service.publish_build(
            workspace_id=WORKSPACE_ID,
            build_attempt_id=creation.build.id,
            capability_approval_id=uuid4(),
            published_by_user_id=USER_ID,
            when=NOW,
        )
    published_replay = await service.publish_build(
        workspace_id=WORKSPACE_ID,
        build_attempt_id=creation.build.id,
        capability_approval_id=approval.id,
        published_by_user_id=USER_ID,
        when=NOW,
    )
    assert published_replay.release == publication.release

    follow_up = await service.queue_follow_up_run(
        workspace_id=WORKSPACE_ID,
        thread_id=creation.thread.id,
        draft_node_ids=(creation.draft.id,),
        instructions="Keep the contract and make the remote call retryable.",
        idempotency_key="publication-v2",
        created_by_user_id=USER_ID,
        when=NOW + timedelta(seconds=1),
    )
    assert follow_up.run.thread_id == creation.thread.id
    assert follow_up.run.environment_id == environment.id
    assert follow_up.builds[0].attempt_number == 2
    assert creation.draft.status is DraftNodeStatus.AUTHORING
    assert creation.draft.operator_version == 2
    assert publication.release.operator_version == 1
    assert publication.release.build_attempt_id == creation.build.id
    assert await service.list_releases(WORKSPACE_ID) == [publication.release]

    replay = await service.queue_follow_up_run(
        workspace_id=WORKSPACE_ID,
        thread_id=creation.thread.id,
        draft_node_ids=(creation.draft.id,),
        instructions="Keep the contract and make the remote call retryable.",
        idempotency_key="publication-v2",
        created_by_user_id=USER_ID,
        when=NOW + timedelta(seconds=2),
    )
    assert replay.run.id == follow_up.run.id
    assert replay.builds[0].id == follow_up.builds[0].id

    detail = await service.get_draft_detail(WORKSPACE_ID, creation.draft.id)
    assert detail.latest_build.id == follow_up.builds[0].id
    assert detail.latest_run.id == follow_up.run.id
    assert detail.thread.id == creation.thread.id
    assert detail.environment.id == environment.id

    with pytest.raises(AgentAuthoringConflictError, match="active build"):
        await service.queue_follow_up_run(
            workspace_id=WORKSPACE_ID,
            thread_id=creation.thread.id,
            draft_node_ids=(creation.draft.id,),
            instructions="Try another revision while v2 is active.",
            idempotency_key="publication-v3-too-soon",
            created_by_user_id=USER_ID,
            when=NOW + timedelta(seconds=3),
        )


@pytest.mark.asyncio
async def test_multi_target_run_keeps_writer_until_every_build_is_reviewable() -> None:
    repository = FakeAgentAuthoringRepository()
    unit_of_work = FakeAgentAuthoringUnitOfWork(repository)
    service = AgentAuthoringService(lambda: unit_of_work)
    environment = await ready_environment(service)
    first = await service.create_draft(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        prompt="Implement two related nodes.",
        anchor=anchor(),
        created_by_user_id=USER_ID,
        idempotency_key="multi-target",
        environment_id=environment.id,
    )
    second_draft = DraftNode(
        workspace_id=WORKSPACE_ID,
        thread_id=first.thread.id,
        graph_id=GRAPH_ID,
        title="Generated node",
        description="Second related node.",
        prompt="Implement the second related node.",
        anchor=anchor(),
        created_by_user_id=USER_ID,
    )
    second_build = NodeBuildAttempt(
        workspace_id=WORKSPACE_ID,
        thread_id=first.thread.id,
        draft_node_id=second_draft.id,
        run_id=first.run.id,
        attempt_number=second_draft.begin_build(),
        prompt=second_draft.prompt,
    )
    first.run.target_draft_ids = (first.draft.id, second_draft.id)
    await repository.add_draft(second_draft)
    await repository.add_build_attempt(second_build)

    claim = await service.claim_run(
        workspace_id=WORKSPACE_ID,
        run_id=first.run.id,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=5),
        when=NOW,
    )
    await service.start_run(
        workspace_id=WORKSPACE_ID,
        run_id=first.run.id,
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
        when=NOW,
    )
    for build in (first.build, second_build):
        for status in (
            NodeBuildStatus.PREPARING,
            NodeBuildStatus.CODING,
            NodeBuildStatus.TESTING,
        ):
            await service.advance_build(
                workspace_id=WORKSPACE_ID,
                build_attempt_id=build.id,
                status=status,
                lease_token=claim.lease_token,
                fencing_token=claim.fencing_token,
                when=NOW,
            )

    manifest = GeneratedNodeManifest(
        title="Related node",
        description="One of two related generated nodes.",
        inputs=(GeneratedNodePort.from_anchor(first.draft.anchor),),
    )
    capabilities = CapabilityManifest()
    await service.request_build_approval(
        workspace_id=WORKSPACE_ID,
        build_attempt_id=first.build.id,
        manifest=manifest,
        capabilities=capabilities,
        artifacts=build_artifacts(),
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
        when=NOW,
    )
    assert first.run.status is AgentRunStatus.RUNNING
    assert environment.active_run_id == first.run.id

    await service.request_build_approval(
        workspace_id=WORKSPACE_ID,
        build_attempt_id=second_build.id,
        manifest=manifest,
        capabilities=capabilities,
        artifacts=build_artifacts(),
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
        when=NOW,
    )
    assert first.run.status is AgentRunStatus.RUNNING
    assert environment.active_run_id == first.run.id
    await service.complete_run_awaiting_approval(
        workspace_id=WORKSPACE_ID,
        run_id=first.run.id,
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
        when=NOW,
    )
    assert first.run.status is AgentRunStatus.AWAITING_APPROVAL
    assert environment.active_run_id is None

    first_approval = await service.approve_build(
        workspace_id=WORKSPACE_ID,
        build_attempt_id=first.build.id,
        capability_digest=capabilities.digest,
        approved_by_user_id=USER_ID,
        when=NOW,
    )
    await service.publish_build(
        workspace_id=WORKSPACE_ID,
        build_attempt_id=first.build.id,
        capability_approval_id=first_approval.id,
        published_by_user_id=USER_ID,
        when=NOW,
    )
    assert first.run.status is AgentRunStatus.AWAITING_APPROVAL

    second_approval = await service.approve_build(
        workspace_id=WORKSPACE_ID,
        build_attempt_id=second_build.id,
        capability_digest=capabilities.digest,
        approved_by_user_id=USER_ID,
        when=NOW,
    )
    await service.publish_build(
        workspace_id=WORKSPACE_ID,
        build_attempt_id=second_build.id,
        capability_approval_id=second_approval.id,
        published_by_user_id=USER_ID,
        when=NOW,
    )
    assert first.run.status is AgentRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_expired_running_run_requires_explicit_continuation() -> None:
    repository = FakeAgentAuthoringRepository()
    unit_of_work = FakeAgentAuthoringUnitOfWork(repository)
    service = AgentAuthoringService(lambda: unit_of_work)
    environment = await ready_environment(service)
    creation = await service.create_draft(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        prompt="Implement a retry-safe node.",
        anchor=anchor(),
        created_by_user_id=USER_ID,
        idempotency_key="interrupted",
        environment_id=environment.id,
    )
    claim = await service.claim_run(
        workspace_id=WORKSPACE_ID,
        run_id=creation.run.id,
        worker_id="worker-a",
        lease_duration=timedelta(seconds=5),
        when=NOW,
    )
    await service.start_run(
        workspace_id=WORKSPACE_ID,
        run_id=creation.run.id,
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
        when=NOW,
    )

    expired = await service.list_expired_running_run_keys(
        when=NOW + timedelta(seconds=6),
        limit=10,
    )
    assert expired == [(WORKSPACE_ID, creation.run.id)]
    revocation = await service.fence_expired_run(
        workspace_id=WORKSPACE_ID,
        run_id=creation.run.id,
        when=NOW + timedelta(seconds=6),
    )
    assert revocation.run.status is AgentRunStatus.INTERRUPTING
    assert environment.active_run_id == creation.run.id
    interrupted = await service.confirm_run_interrupted(
        workspace_id=WORKSPACE_ID,
        run_id=creation.run.id,
        revocation_fencing_token=revocation.revocation_fencing_token,
        when=NOW + timedelta(seconds=7),
    )
    assert interrupted.status is AgentRunStatus.INTERRUPTED
    assert environment.active_run_id is None

    continuation = await service.queue_continuation(
        workspace_id=WORKSPACE_ID,
        interrupted_run_id=creation.run.id,
        idempotency_key="continuation-1",
        created_by_user_id=USER_ID,
        when=NOW + timedelta(seconds=8),
    )
    assert continuation.run.status is AgentRunStatus.QUEUED
    assert continuation.run.continued_from_run_id == interrupted.id
    assert continuation.run.id != interrupted.id
    assert continuation.builds[0].attempt_number == 2
    assert creation.draft.status is DraftNodeStatus.AUTHORING

    replay = await service.queue_continuation(
        workspace_id=WORKSPACE_ID,
        interrupted_run_id=creation.run.id,
        idempotency_key="continuation-1",
        created_by_user_id=USER_ID,
        when=NOW + timedelta(seconds=9),
    )
    assert replay.run.id == continuation.run.id
    assert len(repository.runs) == 2


@pytest.mark.asyncio
async def test_active_cancellation_fences_before_releasing_environment() -> None:
    repository = FakeAgentAuthoringRepository()
    unit_of_work = FakeAgentAuthoringUnitOfWork(repository)
    service = AgentAuthoringService(lambda: unit_of_work)
    environment = await ready_environment(service)
    creation = await service.create_draft(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        prompt="Implement a cancellable node.",
        anchor=anchor(),
        created_by_user_id=USER_ID,
        idempotency_key="cancellable",
        environment_id=environment.id,
    )
    claim = await service.claim_run(
        workspace_id=WORKSPACE_ID,
        run_id=creation.run.id,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=1),
        when=NOW,
    )
    await service.start_run(
        workspace_id=WORKSPACE_ID,
        run_id=creation.run.id,
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
        when=NOW,
    )

    cancellation = await service.request_run_cancellation(
        workspace_id=WORKSPACE_ID,
        run_id=creation.run.id,
        when=NOW + timedelta(seconds=1),
    )
    cancelling = cancellation.run
    assert cancelling.status is AgentRunStatus.CANCELLING
    assert cancelling.fencing_token == claim.fencing_token + 1
    assert cancelling.lease_token is None
    assert cancellation.revoked_lease is not None
    assert cancellation.revoked_lease.owner == "worker-a"
    assert cancellation.revoked_lease.fencing_token == claim.fencing_token
    assert cancellation.revocation_fencing_token == cancelling.fencing_token
    assert environment.active_run_id == creation.run.id
    assert await service.list_cancelling_run_keys(limit=10) == [
        (WORKSPACE_ID, creation.run.id)
    ]
    with pytest.raises(AgentAuthoringConflictError, match="stale"):
        await service.confirm_run_cancelled(
            workspace_id=WORKSPACE_ID,
            run_id=creation.run.id,
            revocation_fencing_token=claim.fencing_token,
            when=NOW + timedelta(seconds=2),
        )

    cancelled = await service.confirm_run_cancelled(
        workspace_id=WORKSPACE_ID,
        run_id=creation.run.id,
        revocation_fencing_token=cancelling.fencing_token,
        when=NOW + timedelta(seconds=2),
    )
    assert cancelled.status is AgentRunStatus.CANCELLED
    assert environment.active_run_id is None
    assert creation.build.status is NodeBuildStatus.CANCELLED
    assert creation.draft.status is DraftNodeStatus.CANCELLED


@pytest.mark.asyncio
async def test_provisioning_lease_is_reclaimable_and_fenced() -> None:
    repository = FakeAgentAuthoringRepository()
    unit_of_work = FakeAgentAuthoringUnitOfWork(repository)
    service = AgentAuthoringService(lambda: unit_of_work)
    environment = await service.create_environment(
        workspace_id=WORKSPACE_ID,
        name="Python agent",
        profile_id="python-3.12-uv",
        provider="docker-trusted-development",
        created_by_user_id=USER_ID,
    )

    assert await service.list_provisionable_environment_keys(
        when=NOW,
        limit=10,
    ) == [(WORKSPACE_ID, environment.id)]
    first = await service.claim_environment_provisioning(
        workspace_id=WORKSPACE_ID,
        environment_id=environment.id,
        worker_id="provisioner-a",
        lease_duration=timedelta(seconds=5),
        when=NOW,
    )
    assert first.environment.status is AgentEnvironmentStatus.CREATING
    assert first.provisioning_fencing_token == 1
    assert await service.list_provisionable_environment_keys(
        when=NOW + timedelta(seconds=4),
        limit=10,
    ) == []
    with pytest.raises(AgentAuthoringConflictError, match="expired"):
        await service.heartbeat_environment_provisioning(
            workspace_id=WORKSPACE_ID,
            environment_id=environment.id,
            provisioning_token=first.provisioning_token,
            provisioning_fencing_token=first.provisioning_fencing_token,
            lease_duration=timedelta(seconds=5),
            when=NOW + timedelta(seconds=6),
        )

    second = await service.claim_environment_provisioning(
        workspace_id=WORKSPACE_ID,
        environment_id=environment.id,
        worker_id="provisioner-b",
        lease_duration=timedelta(seconds=5),
        when=NOW + timedelta(seconds=6),
    )
    assert second.provisioning_fencing_token == 2
    with pytest.raises(AgentAuthoringConflictError, match="stale"):
        await service.complete_environment_provisioning(
            workspace_id=WORKSPACE_ID,
            environment_id=environment.id,
            provider_environment_id="stale-sandbox",
            provisioning_token=first.provisioning_token,
            provisioning_fencing_token=first.provisioning_fencing_token,
            when=NOW + timedelta(seconds=7),
        )
    ready = await service.complete_environment_provisioning(
        workspace_id=WORKSPACE_ID,
        environment_id=environment.id,
        provider_environment_id="sandbox-2",
        provisioning_token=second.provisioning_token,
        provisioning_fencing_token=second.provisioning_fencing_token,
        when=NOW + timedelta(seconds=7),
    )
    assert ready.status is AgentEnvironmentStatus.READY
    assert ready.provider_environment_id == "sandbox-2"
    assert ready.provisioning_token is None


@pytest.mark.asyncio
async def test_follow_up_accepts_cancelled_and_failed_drafts_atomically() -> None:
    repository = FakeAgentAuthoringRepository()
    unit_of_work = FakeAgentAuthoringUnitOfWork(repository)
    service = AgentAuthoringService(lambda: unit_of_work)
    environment = await ready_environment(service)
    cancelled = await service.create_draft(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        prompt="Create the first node.",
        anchor=anchor(),
        created_by_user_id=USER_ID,
        idempotency_key="cancelled-draft",
        environment_id=environment.id,
    )
    await service.cancel_run(
        workspace_id=WORKSPACE_ID,
        run_id=cancelled.run.id,
        when=NOW,
    )
    assert cancelled.draft.status is DraftNodeStatus.CANCELLED

    failed = await service.create_draft(
        workspace_id=WORKSPACE_ID,
        graph_id=GRAPH_ID,
        prompt="Create the second node.",
        anchor=anchor(),
        created_by_user_id=USER_ID,
        idempotency_key="failed-draft",
        thread_id=cancelled.thread.id,
    )
    claim = await service.claim_run(
        workspace_id=WORKSPACE_ID,
        run_id=failed.run.id,
        worker_id="worker-a",
        lease_duration=timedelta(minutes=1),
        when=NOW,
    )
    await service.start_run(
        workspace_id=WORKSPACE_ID,
        run_id=failed.run.id,
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
        when=NOW,
    )
    await service.fail_run(
        workspace_id=WORKSPACE_ID,
        run_id=failed.run.id,
        error="Initial implementation failed verification",
        lease_token=claim.lease_token,
        fencing_token=claim.fencing_token,
        when=NOW,
    )
    assert failed.draft.status is DraftNodeStatus.FAILED

    follow_up = await service.queue_follow_up_run(
        workspace_id=WORKSPACE_ID,
        thread_id=cancelled.thread.id,
        draft_node_ids=(cancelled.draft.id, failed.draft.id),
        instructions="Repair both implementations and keep their contracts.",
        idempotency_key="repair-both",
        created_by_user_id=USER_ID,
        when=NOW + timedelta(seconds=1),
    )
    assert follow_up.run.target_draft_ids == (
        cancelled.draft.id,
        failed.draft.id,
    )
    assert {build.draft_node_id for build in follow_up.builds} == {
        cancelled.draft.id,
        failed.draft.id,
    }
    assert {build.attempt_number for build in follow_up.builds} == {2}
    assert cancelled.draft.status is DraftNodeStatus.AUTHORING
    assert failed.draft.status is DraftNodeStatus.AUTHORING

    replay = await service.queue_follow_up_run(
        workspace_id=WORKSPACE_ID,
        thread_id=cancelled.thread.id,
        draft_node_ids=(cancelled.draft.id, failed.draft.id),
        instructions="Repair both implementations and keep their contracts.",
        idempotency_key="repair-both",
        created_by_user_id=USER_ID,
        when=NOW + timedelta(seconds=2),
    )
    assert replay.run.id == follow_up.run.id
    assert len(replay.builds) == 2
    assert [run.id for run in await service.list_runs_for_thread(
        WORKSPACE_ID,
        cancelled.thread.id,
    )] == [cancelled.run.id, failed.run.id, follow_up.run.id]

    with pytest.raises(AgentAuthoringIdempotencyError, match="different follow-up"):
        await service.queue_follow_up_run(
            workspace_id=WORKSPACE_ID,
            thread_id=cancelled.thread.id,
            draft_node_ids=(failed.draft.id, cancelled.draft.id),
            instructions="Repair both implementations and keep their contracts.",
            idempotency_key="repair-both",
            created_by_user_id=USER_ID,
            when=NOW + timedelta(seconds=3),
        )
