from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from grafy_core.domain.agent_authoring import (
    AgentArtifactType,
    AgentEnvironment,
    AgentEnvironmentStatus,
    AgentEvent,
    AgentEventKind,
    AgentEventPayload,
    AgentPortDirection,
    AgentRun,
    AgentRunStatus,
    AgentThread,
    AnchoredPortContract,
    BuildArtifactSet,
    CapabilityApproval,
    CapabilityManifest,
    DraftNode,
    GeneratedNodeManifest,
    GeneratedNodePort,
    NodeBuildAttempt,
    NodeBuildStatus,
    NodeRelease,
    RuntimeArtifactReference,
)
from grafy_core.domain.identity import User, Workspace, WorkspaceKind
from grafy_core.domain.saved_graphs import SavedGraph, SavedGraphDocument
from grafy_core.nodes import PortShape
from grafy_persistence.adapters.repositories import SqlAgentAuthoringRepository
from grafy_persistence.database import Database, create_database
from grafy_persistence.orm import metadata
from grafy_persistence.unit_of_work import SqlAlchemyUnitOfWork


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")
OTHER_WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000902")
USER_ID = UUID("00000000-0000-0000-0000-000000000903")
GRAPH_ID = UUID("00000000-0000-0000-0000-000000000904")
CREATED_AT = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
async def database(tmp_path: Path) -> AsyncIterator[Database]:
    created = create_database(
        f"sqlite+aiosqlite:///{tmp_path / 'agent-authoring.sqlite3'}"
    )
    async with created.engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    async with SqlAlchemyUnitOfWork(created.sessions) as unit_of_work:
        await unit_of_work.identity.add_user(User(id=USER_ID))
        await unit_of_work.identity.add_workspace(
            Workspace(
                id=WORKSPACE_ID,
                slug="authoring",
                name="Authoring",
                kind=WorkspaceKind.SHARED,
            )
        )
        await unit_of_work.identity.add_workspace(
            Workspace(
                id=OTHER_WORKSPACE_ID,
                slug="other-authoring",
                name="Other authoring",
                kind=WorkspaceKind.SHARED,
            )
        )
        await unit_of_work.commit()
    try:
        yield created
    finally:
        await created.dispose()


def _anchor() -> AnchoredPortContract:
    return AnchoredPortContract(
        direction=AgentPortDirection.INPUT,
        name="texts",
        artifact_type=AgentArtifactType(id="scalar.text", schema_version=1),
        shape=PortShape.MANY,
    )


def _manifest(anchor: AnchoredPortContract) -> GeneratedNodeManifest:
    return GeneratedNodeManifest(
        title="Append API value",
        description="Append a fetched value to every text input.",
        inputs=(GeneratedNodePort.from_anchor(anchor),),
        outputs=(
            GeneratedNodePort(
                direction=AgentPortDirection.OUTPUT,
                name="results",
                artifact_type=anchor.artifact_type,
                shape=PortShape.MANY,
            ),
        ),
    )


def _artifacts() -> BuildArtifactSet:
    return BuildArtifactSet(
        source_bundle_key="agent-nodes/draft/source.tar.zst",
        source_digest="1" * 64,
        lock_digest="2" * 64,
        tests_digest="3" * 64,
        build_digest="4" * 64,
        implementation_digest="5" * 64,
        runtime_image_digest="6" * 64,
        profile_digest="7" * 64,
        runtime_artifact=RuntimeArtifactReference(
            provider="local-development",
            ref="agent-nodes/draft/runtime.tar.zst",
            digest="8" * 64,
        ),
        tests_passed=True,
    )


async def _persist_authoring_scenario(
    database: Database,
) -> tuple[AgentEnvironment, AgentThread, DraftNode, AgentRun, NodeBuildAttempt]:
    graph = SavedGraph(
        workspace_id=WORKSPACE_ID,
        id=GRAPH_ID,
        name="Agent graph",
        document=SavedGraphDocument(),
        created_by_user_id=USER_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    environment = AgentEnvironment(
        workspace_id=WORKSPACE_ID,
        name="Python workspace",
        profile_id="python-3.12-uv",
        provider="local-development",
        created_by_user_id=USER_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    provisioning_token = uuid4()
    environment.claim_provisioning(
        worker_id="provisioner-one",
        provisioning_token=provisioning_token,
        provisioning_expires_at=CREATED_AT + timedelta(minutes=5),
        when=CREATED_AT,
    )
    environment.complete_provisioning(
        provider_environment_id="local-env-1",
        provisioning_token=provisioning_token,
        provisioning_fencing_token=environment.provisioning_fencing_token,
        when=CREATED_AT,
    )
    thread = AgentThread(
        workspace_id=WORKSPACE_ID,
        environment_id=environment.id,
        title="Text enrichment nodes",
        created_by_user_id=USER_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    draft = DraftNode(
        workspace_id=WORKSPACE_ID,
        thread_id=thread.id,
        graph_id=graph.id,
        title="Append API value",
        description="Append a fetched value to every text input.",
        prompt="Call an API and append one response value to every text.",
        anchor=_anchor(),
        created_by_user_id=USER_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    build = NodeBuildAttempt(
        workspace_id=WORKSPACE_ID,
        thread_id=thread.id,
        draft_node_id=draft.id,
        run_id=uuid4(),
        attempt_number=draft.begin_build(when=CREATED_AT),
        prompt=draft.prompt,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    run = AgentRun(
        workspace_id=WORKSPACE_ID,
        id=build.run_id,
        thread_id=thread.id,
        environment_id=environment.id,
        target_draft_ids=(draft.id,),
        instructions=draft.prompt,
        idempotency_key="generate-api-append-node",
        request_digest="a" * 64,
        created_by_user_id=USER_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    event = thread.record_event(
        kind=AgentEventKind.RUN_QUEUED,
        payload=AgentEventPayload(
            message="Agent run queued",
            draft_node_id=draft.id,
            build_attempt_id=build.id,
            run_status=AgentRunStatus.QUEUED,
            build_status=NodeBuildStatus.QUEUED,
        ),
        run_id=run.id,
        when=CREATED_AT,
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.graphs.add(graph)
        await unit_of_work.agent_authoring.add_environment(environment)
        await unit_of_work.agent_authoring.add_thread(thread)
        await unit_of_work.agent_authoring.add_draft(draft)
        await unit_of_work.agent_authoring.add_run(run)
        await unit_of_work.agent_authoring.add_build_attempt(build)
        await unit_of_work.agent_authoring.add_event(event)
        await unit_of_work.commit()
    return environment, thread, draft, run, build


@pytest.mark.asyncio
async def test_authoring_aggregates_round_trip_with_workspace_scoping_and_typed_json(
    database: Database,
) -> None:
    environment, thread, draft, run, build = await _persist_authoring_scenario(database)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        stored_environment = await unit_of_work.agent_authoring.get_environment(
            WORKSPACE_ID,
            environment.id,
        )
        stored_draft = await unit_of_work.agent_authoring.get_draft(
            WORKSPACE_ID,
            draft.id,
        )
        stored_run = await unit_of_work.agent_authoring.get_run_by_idempotency(
            WORKSPACE_ID,
            run.idempotency_key,
        )
        builds = await unit_of_work.agent_authoring.list_build_attempts_for_run(
            WORKSPACE_ID,
            run.id,
        )
        draft_builds = await unit_of_work.agent_authoring.list_build_attempts_for_draft(
            WORKSPACE_ID,
            draft.id,
        )
        latest_build = (
            await unit_of_work.agent_authoring.get_latest_build_attempt_for_draft(
                WORKSPACE_ID,
                draft.id,
            )
        )
        events = await unit_of_work.agent_authoring.list_events(
            WORKSPACE_ID,
            thread.id,
            after_sequence=0,
            limit=20,
        )
        other_workspace_draft = await unit_of_work.agent_authoring.get_draft(
            OTHER_WORKSPACE_ID,
            draft.id,
        )

    assert stored_environment == environment
    assert stored_draft == draft
    assert stored_draft is not None
    assert stored_draft.anchor == draft.anchor
    assert stored_run == run
    assert stored_run is not None
    assert stored_run.target_draft_ids == (draft.id,)
    assert builds == [build]
    assert draft_builds == [build]
    assert latest_build == build
    assert events[0].sequence == 1
    assert events[0].payload.build_attempt_id == build.id
    assert other_workspace_draft is None

    duplicate_sequence = AgentEvent(
        workspace_id=WORKSPACE_ID,
        thread_id=thread.id,
        sequence=1,
        kind=AgentEventKind.MESSAGE,
        payload=AgentEventPayload(message="This sequence is already occupied"),
        created_at=CREATED_AT,
    )
    with pytest.raises(IntegrityError):
        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            await unit_of_work.agent_authoring.add_event(duplicate_sequence)


@pytest.mark.asyncio
async def test_provisioning_claim_is_fenced_and_recoverable(
    database: Database,
) -> None:
    environment = AgentEnvironment(
        workspace_id=WORKSPACE_ID,
        name="Provisioning workspace",
        profile_id="python-3.12-uv",
        provider="local-development",
        created_by_user_id=USER_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.agent_authoring.add_environment(environment)
        await unit_of_work.commit()

    first_expiry = CREATED_AT + timedelta(minutes=5)
    first_token = uuid4()
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.agent_authoring.list_provisionable_environment_keys(
            when=CREATED_AT,
            limit=10,
        ) == [(WORKSPACE_ID, environment.id)]
        claimed = await unit_of_work.agent_authoring.lock_provisionable_environment(
            WORKSPACE_ID,
            environment.id,
            when=CREATED_AT,
        )
        assert claimed is not None
        claimed.claim_provisioning(
            worker_id="provisioner-one",
            provisioning_token=first_token,
            provisioning_expires_at=first_expiry,
            when=CREATED_AT,
        )
        await unit_of_work.agent_authoring.save_environment(claimed)
        await unit_of_work.commit()

    before_expiry = first_expiry - timedelta(seconds=1)
    after_expiry = first_expiry + timedelta(seconds=1)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        stored = await unit_of_work.agent_authoring.get_environment(
            WORKSPACE_ID,
            environment.id,
        )
        assert (
            await unit_of_work.agent_authoring.list_provisionable_environment_keys(
                when=before_expiry,
                limit=10,
            )
            == []
        )
    assert stored is not None
    assert stored.status is AgentEnvironmentStatus.CREATING
    assert stored.provisioning_owner == "provisioner-one"
    assert stored.provisioning_token == first_token
    assert stored.provisioning_fencing_token == 1

    second_token = uuid4()
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        reclaimed = await unit_of_work.agent_authoring.lock_provisionable_environment(
            WORKSPACE_ID,
            environment.id,
            when=after_expiry,
        )
        assert reclaimed is not None
        reclaimed.claim_provisioning(
            worker_id="provisioner-two",
            provisioning_token=second_token,
            provisioning_expires_at=after_expiry + timedelta(minutes=5),
            when=after_expiry,
        )
        await unit_of_work.agent_authoring.save_environment(reclaimed)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        stored = await unit_of_work.agent_authoring.get_environment(
            WORKSPACE_ID,
            environment.id,
        )
    assert stored is not None
    assert stored.provisioning_owner == "provisioner-two"
    assert stored.provisioning_token == second_token
    assert stored.provisioning_fencing_token == 2


@pytest.mark.asyncio
async def test_latest_build_attempt_uses_workspace_and_highest_attempt_number(
    database: Database,
) -> None:
    environment, thread, draft, _, first_build = await _persist_authoring_scenario(
        database
    )
    second_created_at = CREATED_AT + timedelta(minutes=1)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        stored_draft = await unit_of_work.agent_authoring.lock_draft(
            WORKSPACE_ID,
            draft.id,
        )
        stored_first_build = await unit_of_work.agent_authoring.lock_build_attempt(
            WORKSPACE_ID,
            first_build.id,
        )
        assert stored_draft is not None
        assert stored_first_build is not None
        stored_first_build.fail("Initial implementation failed", when=second_created_at)
        second_run = AgentRun(
            workspace_id=WORKSPACE_ID,
            thread_id=thread.id,
            environment_id=environment.id,
            target_draft_ids=(draft.id,),
            instructions="Retry the implementation.",
            idempotency_key="retry-api-append-node",
            request_digest="8" * 64,
            created_by_user_id=USER_ID,
            created_at=second_created_at,
            updated_at=second_created_at,
        )
        second_build = NodeBuildAttempt(
            workspace_id=WORKSPACE_ID,
            thread_id=thread.id,
            draft_node_id=draft.id,
            run_id=second_run.id,
            attempt_number=stored_draft.begin_build(when=second_created_at),
            prompt=second_run.instructions,
            created_at=second_created_at,
            updated_at=second_created_at,
        )
        await unit_of_work.agent_authoring.save_build_attempt(stored_first_build)
        await unit_of_work.agent_authoring.save_draft(stored_draft)
        await unit_of_work.agent_authoring.add_run(second_run)
        await unit_of_work.agent_authoring.add_build_attempt(second_build)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        latest = await unit_of_work.agent_authoring.get_latest_build_attempt_for_draft(
            WORKSPACE_ID,
            draft.id,
        )
        other_workspace = (
            await unit_of_work.agent_authoring.get_latest_build_attempt_for_draft(
                OTHER_WORKSPACE_ID,
                draft.id,
            )
        )

    assert latest == second_build
    assert other_workspace is None


@pytest.mark.asyncio
async def test_claim_and_revocation_discovery_reserve_environment_writer(
    database: Database,
) -> None:
    environment, _, _, run, _ = await _persist_authoring_scenario(database)
    second_run = AgentRun(
        workspace_id=WORKSPACE_ID,
        thread_id=run.thread_id,
        environment_id=run.environment_id,
        target_draft_ids=run.target_draft_ids,
        instructions="Improve the same node after the first run.",
        idempotency_key="improve-api-append-node",
        request_digest="b" * 64,
        created_by_user_id=USER_ID,
        continued_from_run_id=run.id,
        created_at=CREATED_AT + timedelta(seconds=1),
        updated_at=CREATED_AT + timedelta(seconds=1),
    )
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        await unit_of_work.agent_authoring.add_run(second_run)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        claimable = await unit_of_work.agent_authoring.list_claimable_run_keys(
            when=CREATED_AT,
            limit=10,
        )
    assert claimable == [(WORKSPACE_ID, run.id)]

    first_token = uuid4()
    first_expiry = CREATED_AT + timedelta(minutes=5)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        locked_run = await unit_of_work.agent_authoring.lock_claimable_run(
            WORKSPACE_ID,
            run.id,
            when=CREATED_AT,
        )
        locked_environment = await unit_of_work.agent_authoring.lock_environment(
            WORKSPACE_ID,
            environment.id,
        )
        assert locked_environment is not None
        assert locked_run is not None
        locked_run.claim(
            worker_id="worker-one",
            lease_token=first_token,
            lease_expires_at=first_expiry,
            when=CREATED_AT,
        )
        locked_environment.claim_writer(locked_run.id, when=CREATED_AT)
        locked_run.start(first_token, when=CREATED_AT)
        await unit_of_work.agent_authoring.save_run(locked_run)
        await unit_of_work.agent_authoring.save_environment(locked_environment)
        await unit_of_work.commit()

    after_expiry = first_expiry + timedelta(seconds=1)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert (
            await unit_of_work.agent_authoring.list_claimable_run_keys(
                when=after_expiry,
                limit=10,
            )
            == []
        )
        assert await unit_of_work.agent_authoring.list_expired_running_run_keys(
            when=after_expiry,
            limit=10,
        ) == [(WORKSPACE_ID, run.id)]
        assert (
            await unit_of_work.agent_authoring.lock_claimable_run(
                WORKSPACE_ID,
                second_run.id,
                when=after_expiry,
            )
            is None
        )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        locked_run = await unit_of_work.agent_authoring.lock_expired_running_run(
            WORKSPACE_ID,
            run.id,
            when=after_expiry,
        )
        assert locked_run is not None
        revoked_lease = locked_run.begin_interruption(when=after_expiry)
        await unit_of_work.agent_authoring.save_run(locked_run)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.agent_authoring.list_interrupting_run_keys(
            limit=10
        ) == [(WORKSPACE_ID, run.id)]
        assert (
            await unit_of_work.agent_authoring.list_claimable_run_keys(
                when=after_expiry,
                limit=10,
            )
            == []
        )

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        locked_environment = await unit_of_work.agent_authoring.lock_environment(
            WORKSPACE_ID,
            environment.id,
        )
        locked_run = await unit_of_work.agent_authoring.lock_run(
            WORKSPACE_ID,
            run.id,
        )
        assert locked_environment is not None
        assert locked_run is not None
        locked_run.confirm_interrupted(
            revoked_lease.fencing_token + 1,
            when=after_expiry,
        )
        locked_environment.release_writer(locked_run.id, when=after_expiry)
        await unit_of_work.agent_authoring.save_run(locked_run)
        await unit_of_work.agent_authoring.save_environment(locked_environment)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        stored_second_run = await unit_of_work.agent_authoring.get_run(
            WORKSPACE_ID,
            second_run.id,
        )
        thread_runs = await unit_of_work.agent_authoring.list_runs_for_thread(
            WORKSPACE_ID,
            run.thread_id,
        )
        assert await unit_of_work.agent_authoring.list_claimable_run_keys(
            when=after_expiry,
            limit=10,
        ) == [(WORKSPACE_ID, second_run.id)]
    assert stored_second_run is not None
    assert stored_second_run.continued_from_run_id == run.id
    assert [thread_run.id for thread_run in thread_runs] == [run.id, second_run.id]

    cancellation_token = uuid4()
    cancellation_expiry = after_expiry + timedelta(minutes=5)
    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        locked_run = await unit_of_work.agent_authoring.lock_claimable_run(
            WORKSPACE_ID,
            second_run.id,
            when=after_expiry,
        )
        locked_environment = await unit_of_work.agent_authoring.lock_environment(
            WORKSPACE_ID,
            environment.id,
        )
        assert locked_environment is not None
        assert locked_run is not None
        locked_run.claim(
            worker_id="worker-two",
            lease_token=cancellation_token,
            lease_expires_at=cancellation_expiry,
            when=after_expiry,
        )
        locked_environment.claim_writer(locked_run.id, when=after_expiry)
        revoked = locked_run.request_cancellation(when=after_expiry)
        assert revoked is not None
        await unit_of_work.agent_authoring.save_run(locked_run)
        await unit_of_work.agent_authoring.save_environment(locked_environment)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        assert await unit_of_work.agent_authoring.list_cancelling_run_keys(
            limit=10
        ) == [(WORKSPACE_ID, second_run.id)]


@pytest.mark.asyncio
async def test_approval_and_release_are_append_only_and_reconstitute_contract(
    database: Database,
) -> None:
    _, thread, draft, _, build = await _persist_authoring_scenario(database)
    manifest = _manifest(draft.anchor)
    capabilities = CapabilityManifest(
        outbound_http_origins=("https://api.example.test",),
        secret_refs=("EXAMPLE_API_TOKEN",),
    )
    artifacts = _artifacts()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        locked_draft = await unit_of_work.agent_authoring.lock_draft(
            WORKSPACE_ID,
            draft.id,
        )
        locked_build = await unit_of_work.agent_authoring.lock_build_attempt(
            WORKSPACE_ID,
            build.id,
        )
        assert locked_draft is not None
        assert locked_build is not None
        for status in (
            NodeBuildStatus.PREPARING,
            NodeBuildStatus.CODING,
            NodeBuildStatus.TESTING,
        ):
            locked_build.advance(status, when=CREATED_AT)
        locked_build.request_approval(
            anchor=locked_draft.anchor,
            manifest=manifest,
            capabilities=capabilities,
            artifacts=artifacts,
            when=CREATED_AT,
        )
        locked_draft.await_approval(when=CREATED_AT)
        approval = CapabilityApproval(
            workspace_id=WORKSPACE_ID,
            draft_node_id=locked_draft.id,
            build_attempt_id=locked_build.id,
            capability_digest=capabilities.digest,
            approved_by_user_id=USER_ID,
            approved_at=CREATED_AT,
        )
        await unit_of_work.agent_authoring.save_build_attempt(locked_build)
        await unit_of_work.agent_authoring.save_draft(locked_draft)
        await unit_of_work.agent_authoring.add_capability_approval(approval)
        await unit_of_work.commit()

    release = NodeRelease(
        workspace_id=WORKSPACE_ID,
        node_id=draft.id,
        revision=1,
        draft_node_id=draft.id,
        build_attempt_id=build.id,
        capability_approval_id=approval.id,
        thread_id=thread.id,
        environment_id=thread.environment_id,
        manifest=manifest,
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        artifacts=artifacts,
        approved_by_user_id=USER_ID,
        created_by_user_id=USER_ID,
        created_at=CREATED_AT,
    )
    wrong_approval_release = replace(
        release,
        capability_approval_id=uuid4(),
    )
    with pytest.raises(IntegrityError):
        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            await unit_of_work.agent_authoring.add_release(wrong_approval_release)

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        locked_draft = await unit_of_work.agent_authoring.lock_draft(
            WORKSPACE_ID,
            draft.id,
        )
        locked_build = await unit_of_work.agent_authoring.lock_build_attempt(
            WORKSPACE_ID,
            build.id,
        )
        assert locked_draft is not None
        assert locked_build is not None
        locked_build.advance(NodeBuildStatus.PUBLISHED, when=CREATED_AT)
        locked_draft.publish(1, when=CREATED_AT)
        await unit_of_work.agent_authoring.save_build_attempt(locked_build)
        await unit_of_work.agent_authoring.save_draft(locked_draft)
        await unit_of_work.agent_authoring.add_release(release)
        await unit_of_work.commit()

    async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
        stored_approval = await unit_of_work.agent_authoring.get_capability_approval(
            WORKSPACE_ID,
            build.id,
        )
        stored_release = await unit_of_work.agent_authoring.get_release(
            WORKSPACE_ID,
            draft.id,
            1,
        )
        releases = await unit_of_work.agent_authoring.list_releases(WORKSPACE_ID)

    assert stored_approval == approval
    assert stored_release == release
    assert stored_release is not None
    assert stored_release.manifest == manifest
    assert stored_release.capabilities == capabilities
    assert stored_release.artifacts == artifacts
    assert releases == [release]

    duplicate = NodeRelease(
        workspace_id=release.workspace_id,
        node_id=release.node_id,
        revision=release.revision,
        draft_node_id=release.draft_node_id,
        build_attempt_id=release.build_attempt_id,
        capability_approval_id=release.capability_approval_id,
        thread_id=release.thread_id,
        environment_id=release.environment_id,
        manifest=release.manifest,
        capabilities=release.capabilities,
        capability_digest=release.capability_digest,
        artifacts=release.artifacts,
        approved_by_user_id=release.approved_by_user_id,
        created_by_user_id=release.created_by_user_id,
        created_at=release.created_at,
    )
    with pytest.raises(IntegrityError):
        async with SqlAlchemyUnitOfWork(database.sessions) as unit_of_work:
            await unit_of_work.agent_authoring.add_release(duplicate)


@pytest.mark.asyncio
async def test_postgresql_claim_queries_lock_run_before_environment() -> None:
    session = AsyncMock(spec=AsyncSession)
    session.execute.return_value = []
    session.scalar.return_value = None
    repository = SqlAgentAuthoringRepository(session)

    await repository.list_provisionable_environment_keys(
        when=CREATED_AT,
        limit=5,
    )
    provision_statement = session.execute.await_args.args[0]
    provision_sql = str(provision_statement.compile(dialect=postgresql.dialect()))

    await repository.lock_provisionable_environment(
        WORKSPACE_ID,
        UUID("00000000-0000-0000-0000-000000000998"),
        when=CREATED_AT,
    )
    provision_lock_statement = session.scalar.await_args.args[0]
    provision_lock_sql = str(
        provision_lock_statement.compile(dialect=postgresql.dialect())
    )

    await repository.list_claimable_run_keys(when=CREATED_AT, limit=5)
    claim_statement = session.execute.await_args.args[0]
    claim_sql = str(claim_statement.compile(dialect=postgresql.dialect()))

    environment = AgentEnvironment(
        workspace_id=WORKSPACE_ID,
        name="Python workspace",
        profile_id="python-3.12-uv",
        provider="local-development",
        created_by_user_id=USER_ID,
        status=AgentEnvironmentStatus.READY,
        provider_environment_id="local-env-1",
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    queued_run = AgentRun(
        workspace_id=WORKSPACE_ID,
        thread_id=uuid4(),
        environment_id=environment.id,
        target_draft_ids=(uuid4(),),
        instructions="Generate a node.",
        idempotency_key="postgresql-lock-order-queued",
        request_digest="a" * 64,
        created_by_user_id=USER_ID,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
    )
    session.scalar.side_effect = [queued_run, environment]
    claim_result = await repository.lock_claimable_run(
        WORKSPACE_ID,
        queued_run.id,
        when=CREATED_AT,
    )
    claim_run_statement = session.scalar.await_args_list[-2].args[0]
    claim_environment_statement = session.scalar.await_args_list[-1].args[0]
    claim_run_sql = str(
        claim_run_statement.compile(dialect=postgresql.dialect())
    )
    claim_environment_sql = str(
        claim_environment_statement.compile(dialect=postgresql.dialect())
    )

    expired_run = replace(
        queued_run,
        id=UUID("00000000-0000-0000-0000-000000000999"),
        idempotency_key="postgresql-lock-order-expired",
        status=AgentRunStatus.RUNNING,
        lease_expires_at=CREATED_AT - timedelta(seconds=1),
    )
    environment.active_run_id = expired_run.id
    session.scalar.side_effect = [expired_run, environment]
    expired_result = await repository.lock_expired_running_run(
        WORKSPACE_ID,
        expired_run.id,
        when=CREATED_AT,
    )
    expired_run_statement = session.scalar.await_args_list[-2].args[0]
    expired_environment_statement = session.scalar.await_args_list[-1].args[0]
    expired_run_sql = str(
        expired_run_statement.compile(dialect=postgresql.dialect())
    )
    expired_environment_sql = str(
        expired_environment_statement.compile(dialect=postgresql.dialect())
    )

    await repository.list_expired_running_run_keys(when=CREATED_AT, limit=5)
    expired_statement = session.execute.await_args.args[0]
    expired_sql = str(expired_statement.compile(dialect=postgresql.dialect()))

    assert "FOR UPDATE SKIP LOCKED" in provision_sql
    assert "FOR UPDATE SKIP LOCKED" in provision_lock_sql
    assert "FOR UPDATE SKIP LOCKED" in claim_sql
    assert claim_result is queued_run
    assert "FROM agent_runs" in claim_run_sql
    assert "JOIN agent_environments" not in claim_run_sql
    assert "FOR UPDATE SKIP LOCKED" in claim_run_sql
    assert "FROM agent_environments" in claim_environment_sql
    assert "FOR UPDATE SKIP LOCKED" in claim_environment_sql
    assert expired_result is expired_run
    assert "FROM agent_runs" in expired_run_sql
    assert "JOIN agent_environments" not in expired_run_sql
    assert "FOR UPDATE SKIP LOCKED" in expired_run_sql
    assert "FROM agent_environments" in expired_environment_sql
    assert "FOR UPDATE SKIP LOCKED" in expired_environment_sql
    assert "FOR UPDATE SKIP LOCKED" in expired_sql
