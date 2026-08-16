from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from typing import BinaryIO, cast
from uuid import UUID

import pytest

from grafy_agent.models import (
    AgentLease,
    NodeSourceBundle,
    ReleaseProposal,
    SandboxArchive,
    SandboxRuntimeArtifact,
    SourceBundleVerification,
)
from grafy_core.application.agent_authoring import AgentAuthoringService
from grafy_core.domain.agent_authoring import (
    AgentArtifactType,
    AgentAuthoringConflictError,
    AgentPortDirection,
    BuildArtifactSet,
    CapabilityManifest,
    GeneratedNodeManifest,
    GeneratedNodePort,
    NodeBuildAttempt,
    NodeBuildStatus,
)
from grafy_core.domain.errors import ObjectAlreadyExistsError
from grafy_core.nodes import PortShape
from grafy_core.ports.storage import (
    FileStoragePort,
    SaveFileCommand,
    StoredFile,
    StoredObjectInfo,
)

from grafy_agent_worker.control import WorkerAuthoringControl


WORKSPACE_ID = UUID("70000000-0000-0000-0000-000000000001")
THREAD_ID = UUID("70000000-0000-0000-0000-000000000002")
ENVIRONMENT_ID = UUID("70000000-0000-0000-0000-000000000003")
RUN_ID = UUID("70000000-0000-0000-0000-000000000004")
DRAFT_ID = UUID("70000000-0000-0000-0000-000000000005")
BUILD_ID = UUID("70000000-0000-0000-0000-000000000006")
LEASE_TOKEN = UUID("70000000-0000-0000-0000-000000000007")
BUCKET = "artifacts"


class TrackingStream(BytesIO):
    close_called: bool

    def __init__(self, content: bytes) -> None:
        super().__init__(content)
        self.close_called = False

    def close(self) -> None:
        self.close_called = True
        super().close()


class RecordingStorage(FileStoragePort):
    def __init__(self, operations: list[str]) -> None:
        self.operations = operations
        self.objects: dict[tuple[str, str], bytes] = {}
        self.save_attempts = 0
        self.load_streams: list[TrackingStream] = []
        self.concurrent_create: bytes | None = None

    async def save(self, command: SaveFileCommand) -> StoredFile:
        self.operations.append("save")
        self.save_attempts += 1
        key = (command.bucket, command.path)
        if self.concurrent_create is not None:
            self.objects[key] = self.concurrent_create
            self.concurrent_create = None
        if key in self.objects and not command.allow_overwrite:
            raise ObjectAlreadyExistsError(
                f"File already exists: {command.bucket}/{command.path}"
            )
        content = command.stream.read()
        self.objects[key] = content
        return StoredFile(
            bucket=command.bucket,
            path=command.path,
            etag=None,
            version_id=None,
            byte_size=len(content),
            sha256=sha256(content).hexdigest(),
        )

    async def move(
        self,
        bucket: str,
        source_path: str,
        destination_path: str,
    ) -> None:
        self.operations.append("move")
        self.objects[(bucket, destination_path)] = self.objects.pop(
            (bucket, source_path)
        )

    async def load(self, bucket: str, path: str) -> BinaryIO:
        self.operations.append("load")
        stream = TrackingStream(self.objects[(bucket, path)])
        self.load_streams.append(stream)
        return stream

    async def stat(self, bucket: str, path: str) -> StoredObjectInfo | None:
        self.operations.append("stat")
        content = self.objects.get((bucket, path))
        if content is None:
            return None
        return StoredObjectInfo(
            bucket=bucket,
            path=path,
            byte_size=len(content),
            etag=None,
            version_id=None,
        )

    async def load_range(
        self,
        bucket: str,
        path: str,
        start: int,
        end_exclusive: int,
    ) -> bytes:
        return self.objects[(bucket, path)][start:end_exclusive]

    async def delete(self, bucket: str, path: str) -> None:
        self.operations.append("delete")
        self.objects.pop((bucket, path), None)

    def exists(self, bucket: str, path: str) -> bool:
        return (bucket, path) in self.objects


class RecordingAuthoringService:
    def __init__(
        self,
        build: NodeBuildAttempt,
        operations: list[str],
        *,
        fail_on_fence: int | None = None,
    ) -> None:
        self.build = build
        self.operations = operations
        self.fail_on_fence = fail_on_fence
        self.fence_count = 0
        self.approval_count = 0

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
    ) -> object:
        del message
        assert workspace_id == WORKSPACE_ID
        assert run_id == RUN_ID
        assert lease_token == LEASE_TOKEN
        assert fencing_token == 1
        assert draft_node_id == DRAFT_ID
        assert build_attempt_id == BUILD_ID
        self.operations.append("fence")
        self.fence_count += 1
        if self.fail_on_fence == self.fence_count:
            raise AgentAuthoringConflictError("Agent lease is stale")
        return object()

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
    ) -> NodeBuildAttempt:
        del manifest, capabilities, artifacts
        assert workspace_id == WORKSPACE_ID
        assert build_attempt_id == BUILD_ID
        assert lease_token == LEASE_TOKEN
        assert fencing_token == 1
        self.operations.append("finalize")
        self.approval_count += 1
        return replace(self.build, status=NodeBuildStatus.AWAITING_APPROVAL)


def make_testing_build() -> NodeBuildAttempt:
    return NodeBuildAttempt(
        workspace_id=WORKSPACE_ID,
        thread_id=THREAD_ID,
        draft_node_id=DRAFT_ID,
        run_id=RUN_ID,
        attempt_number=1,
        prompt="Implement the generated node",
        status=NodeBuildStatus.TESTING,
        id=BUILD_ID,
    )


def agent_lease() -> AgentLease:
    return AgentLease(
        workspace_id=WORKSPACE_ID,
        thread_id=THREAD_ID,
        environment_id=ENVIRONMENT_ID,
        run_id=RUN_ID,
        lease_token=LEASE_TOKEN,
        fencing_token=1,
        target_draft_ids=(DRAFT_ID,),
    )


def release_proposal(
    archive_data: bytes = b"exact immutable source archive",
    *,
    claimed_source_digest: str | None = None,
) -> ReleaseProposal:
    archive_digest = sha256(archive_data).hexdigest()
    source_digest = claimed_source_digest or archive_digest
    manifest = GeneratedNodeManifest(
        title="Generated text node",
        description="Returns generated text.",
        outputs=(
            GeneratedNodePort(
                direction=AgentPortDirection.OUTPUT,
                name="result",
                artifact_type=AgentArtifactType(
                    id="scalar.text",
                    schema_version=1,
                ),
                shape=PortShape.ONE,
            ),
        ),
    )
    source_bundle = NodeSourceBundle(
        archive=SandboxArchive(
            data=archive_data,
            sha256=archive_digest,
            byte_count=len(archive_data),
        ),
        source_digest=source_digest,
        lock_digest="b" * 64,
        tests_digest="c" * 64,
        implementation_digest="d" * 64,
        file_count=4,
    )
    verification = SourceBundleVerification(
        source_digest=source_digest,
        lock_digest=source_bundle.lock_digest,
        tests_digest=source_bundle.tests_digest,
        implementation_digest=source_bundle.implementation_digest,
        runtime_image_digest="e" * 64,
        profile_digest="f" * 64,
        runtime_artifact=SandboxRuntimeArtifact(
            provider="daytona",
            reference="snapshot:generated-node",
            digest="a" * 64,
        ),
    )
    return ReleaseProposal(
        draft_node_id=DRAFT_ID,
        manifest=manifest,
        capabilities=CapabilityManifest(),
        source_bundle=source_bundle,
        verification=verification,
        summary="Verified generated-node release",
    )


def source_key(proposal: ReleaseProposal) -> str:
    return (
        f"generated-nodes/{WORKSPACE_ID}/{DRAFT_ID}/sources/"
        f"{proposal.source_bundle.source_digest}.tar.gz"
    )


def authoring_control(
    service: RecordingAuthoringService,
    storage: RecordingStorage,
    build: NodeBuildAttempt,
) -> WorkerAuthoringControl:
    return WorkerAuthoringControl(
        service=cast(AgentAuthoringService, service),
        storage=storage,
        storage_bucket=BUCKET,
        lease=agent_lease(),
        builds=(build,),
    )


@pytest.mark.asyncio
async def test_revoked_lease_cannot_reach_source_storage_mutation() -> None:
    operations: list[str] = []
    build = make_testing_build()
    service = RecordingAuthoringService(build, operations, fail_on_fence=1)
    storage = RecordingStorage(operations)
    proposal = release_proposal()

    with pytest.raises(AgentAuthoringConflictError, match="stale"):
        await authoring_control(service, storage, build).propose_release(
            agent_lease(), proposal
        )

    assert operations == ["stat", "fence"]
    assert storage.save_attempts == 0
    assert storage.objects == {}
    assert service.approval_count == 0


@pytest.mark.asyncio
async def test_revocation_after_content_write_prevents_release_finalization() -> None:
    operations: list[str] = []
    build = make_testing_build()
    service = RecordingAuthoringService(build, operations, fail_on_fence=2)
    storage = RecordingStorage(operations)
    proposal = release_proposal()

    with pytest.raises(AgentAuthoringConflictError, match="stale"):
        await authoring_control(service, storage, build).propose_release(
            agent_lease(), proposal
        )

    assert operations == ["stat", "fence", "save", "fence"]
    assert storage.objects[(BUCKET, source_key(proposal))] == (
        proposal.source_bundle.archive.data
    )
    assert service.approval_count == 0


@pytest.mark.asyncio
async def test_existing_immutable_key_rejects_different_bytes_and_closes_stream() -> (
    None
):
    operations: list[str] = []
    build = make_testing_build()
    service = RecordingAuthoringService(build, operations)
    storage = RecordingStorage(operations)
    proposal = release_proposal()
    storage.objects[(BUCKET, source_key(proposal))] = b"different source archive"

    with pytest.raises(RuntimeError, match="Immutable source bundle collision"):
        await authoring_control(service, storage, build).propose_release(
            agent_lease(), proposal
        )

    assert operations == ["stat", "load"]
    assert storage.save_attempts == 0
    assert len(storage.load_streams) == 1
    assert storage.load_streams[0].close_called
    assert service.approval_count == 0


@pytest.mark.asyncio
async def test_concurrent_identical_create_is_revalidated_and_finalized() -> None:
    operations: list[str] = []
    build = make_testing_build()
    service = RecordingAuthoringService(build, operations)
    storage = RecordingStorage(operations)
    proposal = release_proposal()
    storage.concurrent_create = proposal.source_bundle.archive.data

    receipt = await authoring_control(service, storage, build).propose_release(
        agent_lease(), proposal
    )

    assert receipt.build_attempt_id == BUILD_ID
    assert operations == ["stat", "fence", "save", "load", "fence", "finalize"]
    assert storage.load_streams[0].close_called
    assert storage.objects[(BUCKET, source_key(proposal))] == (
        proposal.source_bundle.archive.data
    )


@pytest.mark.asyncio
async def test_claimed_digest_must_identify_the_exact_archive() -> None:
    operations: list[str] = []
    build = make_testing_build()
    service = RecordingAuthoringService(build, operations)
    storage = RecordingStorage(operations)
    proposal = release_proposal(claimed_source_digest="9" * 64)

    with pytest.raises(RuntimeError, match="does not match the source archive"):
        await authoring_control(service, storage, build).propose_release(
            agent_lease(), proposal
        )

    assert operations == []
    assert storage.objects == {}
    assert service.approval_count == 0
