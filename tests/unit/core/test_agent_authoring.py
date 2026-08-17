from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from grafy_core.domain.agent_authoring import (
    AgentArtifactType,
    AgentAuthoringConflictError,
    AgentAuthoringError,
    AgentEnvironment,
    AgentEnvironmentStatus,
    AgentEventKind,
    AgentEventPayload,
    AgentPortDirection,
    AgentRun,
    AgentRunStatus,
    AgentThread,
    AnchoredPortContract,
    BuildArtifactSet,
    CapabilityManifest,
    DraftNode,
    GeneratedNodeManifest,
    GeneratedNodePort,
    NodeBuildAttempt,
    NodeBuildStatus,
    NodeRelease,
    ObjectStoreAccess,
    ObjectStoreCapability,
    PortConversion,
    PortFeed,
    RuntimeArtifactReference,
    RuntimeLimits,
)
from grafy_core.nodes import PortShape


WORKSPACE_ID = UUID("00000000-0000-0000-0000-000000000901")
GRAPH_ID = UUID("00000000-0000-0000-0000-000000000902")
ENVIRONMENT_ID = UUID("00000000-0000-0000-0000-000000000903")
THREAD_ID = UUID("00000000-0000-0000-0000-000000000904")
NOW = datetime(2026, 8, 16, 12, tzinfo=UTC)
DIGEST = "a" * 64


def anchor(
    direction: AgentPortDirection = AgentPortDirection.INPUT,
) -> AnchoredPortContract:
    return AnchoredPortContract(
        direction=direction,
        name="documents" if direction is AgentPortDirection.INPUT else "result",
        artifact_type=AgentArtifactType(id="scalar.text", schema_version=1),
        shape=PortShape.MANY,
        collection_mode="direct",
        feed=PortFeed(
            projection_path=("body", "text"),
            conversion_path=(PortConversion(id="text.extract", version=2),),
        ),
    )


def artifacts(*, tests_passed: bool = True) -> BuildArtifactSet:
    return BuildArtifactSet(
        source_bundle_key="generated/nodes/source.tar.zst",
        source_digest=DIGEST,
        lock_digest="b" * 64,
        tests_digest="c" * 64,
        build_digest="d" * 64,
        implementation_digest="e" * 64,
        runtime_image_digest="f" * 64,
        profile_digest="0" * 64,
        runtime_artifact=RuntimeArtifactReference(
            provider="docker-trusted-development",
            ref="snapshot-generated-node-v1",
            digest="1" * 64,
        ),
        tests_passed=tests_passed,
    )


def capability_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        outbound_http_origins=(
            "https://API.EXAMPLE.com:443/",
            "https://api.example.com",
            "https://[2606:4700:4700::1111]:8443",
        ),
        secret_refs=("SERVICE_TOKEN", "SERVICE_TOKEN"),
        object_store=(
            ObjectStoreCapability(
                scope=ObjectStoreAccess.WRITE,
                prefix="generated/output",
            ),
        ),
        runtime=RuntimeLimits(memory_megabytes=768),
    )


def test_draft_reserves_stable_operator_and_exact_anchor_manifest() -> None:
    draft = DraftNode(
        workspace_id=WORKSPACE_ID,
        thread_id=THREAD_ID,
        graph_id=GRAPH_ID,
        title="Append API values",
        description="Append a remote value to each text scalar.",
        prompt="Call the API and append the response.",
        anchor=anchor(),
        id=UUID("11111111-1111-1111-1111-111111111111"),
        created_at=NOW,
        updated_at=NOW,
    )

    assert draft.operator_id == (
        "generated.node.11111111-1111-1111-1111-111111111111"
    )
    assert draft.operator_version == 1
    assert draft.provisional_manifest.inputs == (
        GeneratedNodePort.from_anchor(draft.anchor),
    )
    assert draft.provisional_manifest.outputs == ()
    assert draft.provisional_manifest.preserves(draft.anchor)
    assert draft.anchor.feed.projection_path == ("body", "text")


def test_manifest_must_preserve_the_connected_port_exactly() -> None:
    connected = anchor()
    changed = GeneratedNodeManifest(
        title="Changed",
        description="Changed the connected contract.",
        inputs=(
            GeneratedNodePort(
                direction=AgentPortDirection.INPUT,
                name="documents",
                artifact_type=AgentArtifactType(
                    id="scalar.integer",
                    schema_version=1,
                ),
                shape=PortShape.MANY,
            ),
        ),
    )
    build = NodeBuildAttempt(
        workspace_id=WORKSPACE_ID,
        thread_id=THREAD_ID,
        draft_node_id=uuid4(),
        run_id=uuid4(),
        attempt_number=1,
        prompt="Implement it",
        status=NodeBuildStatus.TESTING,
        created_at=NOW,
        updated_at=NOW,
    )

    with pytest.raises(
        AgentAuthoringError,
        match="changed or removed the connected port",
    ):
        build.request_approval(
            anchor=connected,
            manifest=changed,
            capabilities=CapabilityManifest(),
            artifacts=artifacts(),
            when=NOW,
        )


def test_capability_manifest_is_canonical_and_ipv6_safe() -> None:
    capabilities = capability_manifest()
    reordered = CapabilityManifest(
        outbound_http_origins=(
            "https://[2606:4700:4700::1111]:8443/",
            "https://api.example.com",
        ),
        secret_refs=("SERVICE_TOKEN",),
        object_store=capabilities.object_store,
        runtime=capabilities.runtime,
    )

    assert capabilities.outbound_http_origins == (
        "https://[2606:4700:4700::1111]:8443",
        "https://api.example.com",
    )
    assert capabilities.digest == reordered.digest
    assert len(capabilities.digest) == 64

    with pytest.raises(ValidationError, match="must use HTTPS"):
        CapabilityManifest(outbound_http_origins=("http://example.com",))
    with pytest.raises(ValidationError, match="non-public IP"):
        CapabilityManifest(outbound_http_origins=("https://[::1]",))


def test_environment_allows_only_one_active_writer() -> None:
    environment = AgentEnvironment(
        workspace_id=WORKSPACE_ID,
        name="Python",
        profile_id="python-3.12",
        provider="docker-trusted-development",
        status=AgentEnvironmentStatus.READY,
        provider_environment_id="sandbox-1",
        id=ENVIRONMENT_ID,
        created_at=NOW,
        updated_at=NOW,
    )
    first_run_id = uuid4()
    environment.claim_writer(first_run_id, when=NOW)

    with pytest.raises(AgentAuthoringConflictError, match="active writer"):
        environment.claim_writer(uuid4(), when=NOW)

    environment.release_writer(first_run_id, when=NOW)
    assert environment.active_run_id is None


def test_thread_assigns_monotonic_event_sequence() -> None:
    thread = AgentThread(
        workspace_id=WORKSPACE_ID,
        environment_id=ENVIRONMENT_ID,
        title="Multiple nodes",
        id=THREAD_ID,
        created_at=NOW,
        updated_at=NOW,
    )
    first = thread.record_event(
        kind=AgentEventKind.MESSAGE,
        payload=AgentEventPayload(message="First"),
        run_id=None,
        when=NOW,
    )
    second = thread.record_event(
        kind=AgentEventKind.MESSAGE,
        payload=AgentEventPayload(message="Second"),
        run_id=None,
        when=NOW + timedelta(seconds=1),
    )

    assert (first.sequence, second.sequence) == (1, 2)
    assert thread.event_sequence == 2


def test_claimed_run_can_be_reclaimed_but_running_run_is_interrupted() -> None:
    run = AgentRun(
        workspace_id=WORKSPACE_ID,
        thread_id=THREAD_ID,
        environment_id=ENVIRONMENT_ID,
        target_draft_ids=(uuid4(),),
        instructions="Implement the node",
        idempotency_key="request-1",
        request_digest=DIGEST,
        created_at=NOW,
        updated_at=NOW,
    )
    first_token = uuid4()
    run.claim(
        worker_id="worker-a",
        lease_token=first_token,
        lease_expires_at=NOW + timedelta(seconds=10),
        when=NOW,
    )
    second_token = uuid4()
    run.claim(
        worker_id="worker-b",
        lease_token=second_token,
        lease_expires_at=NOW + timedelta(seconds=30),
        when=NOW + timedelta(seconds=11),
    )
    assert run.status is AgentRunStatus.CLAIMED
    assert run.attempt == 2
    assert run.fencing_token == 2

    run.start(second_token, when=NOW + timedelta(seconds=12))
    with pytest.raises(AgentAuthoringConflictError, match="stale"):
        run.start(first_token, when=NOW + timedelta(seconds=13))
    revoked = run.begin_interruption(when=NOW + timedelta(seconds=31))

    assert revoked.owner == "worker-b"
    assert revoked.fencing_token == 2
    assert run.status is AgentRunStatus.INTERRUPTING
    assert run.lease_token is None
    with pytest.raises(AgentAuthoringConflictError, match="stale"):
        run.confirm_interrupted(2, when=NOW + timedelta(seconds=32))
    run.confirm_interrupted(run.fencing_token, when=NOW + timedelta(seconds=32))
    assert run.status is AgentRunStatus.INTERRUPTED
    with pytest.raises(AgentAuthoringConflictError, match="cannot be claimed"):
        run.claim(
            worker_id="worker-c",
            lease_token=uuid4(),
            lease_expires_at=NOW + timedelta(minutes=2),
            when=NOW + timedelta(minutes=1),
        )


def test_build_approval_and_release_are_bound_to_exact_capabilities() -> None:
    connected = anchor(AgentPortDirection.OUTPUT)
    manifest = GeneratedNodeManifest(
        title="Remote append",
        description="Appends a remote value.",
        outputs=(GeneratedNodePort.from_anchor(connected),),
    )
    capabilities = capability_manifest()
    build = NodeBuildAttempt(
        workspace_id=WORKSPACE_ID,
        thread_id=THREAD_ID,
        draft_node_id=uuid4(),
        run_id=uuid4(),
        attempt_number=1,
        prompt="Implement it",
        status=NodeBuildStatus.TESTING,
        created_at=NOW,
        updated_at=NOW,
    )
    build.request_approval(
        anchor=connected,
        manifest=manifest,
        capabilities=capabilities,
        artifacts=artifacts(),
        when=NOW,
    )
    release = NodeRelease(
        workspace_id=WORKSPACE_ID,
        node_id=build.draft_node_id,
        revision=1,
        draft_node_id=build.draft_node_id,
        build_attempt_id=build.id,
        thread_id=THREAD_ID,
        environment_id=ENVIRONMENT_ID,
        manifest=manifest,
        capabilities=capabilities,
        capability_digest=capabilities.digest,
        artifacts=artifacts(),
        capability_approval_id=uuid4(),
        approved_by_user_id=uuid4(),
        created_at=NOW,
    )

    assert build.capability_digest == capabilities.digest
    assert release.operator_id.endswith(str(build.draft_node_id))
    assert release.operator_version == 1

    with pytest.raises(AgentAuthoringError, match="does not match"):
        NodeRelease(
            workspace_id=WORKSPACE_ID,
            node_id=build.draft_node_id,
            revision=1,
            draft_node_id=build.draft_node_id,
            build_attempt_id=build.id,
            thread_id=THREAD_ID,
            environment_id=ENVIRONMENT_ID,
            manifest=manifest,
            capabilities=capabilities,
            capability_digest="1" * 64,
            artifacts=artifacts(),
            capability_approval_id=uuid4(),
            approved_by_user_id=uuid4(),
            created_at=NOW,
        )
