from datetime import datetime
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import ConfigDict, Field, field_validator, model_validator

from grafy_core.domain.agent_authoring import (
    AgentEnvironment,
    AgentEnvironmentStatus,
    AgentEvent,
    AgentEventKind,
    AgentPortDirection,
    AgentRun,
    AgentRunStatus,
    AgentThread,
    BuildArtifactSet,
    CapabilityApproval,
    CapabilityManifest,
    DraftNode,
    DraftNodeStatus,
    NodeBuildAttempt,
    NodeBuildStatus,
    NodeRelease,
    ObjectStoreAccess,
    RuntimeArtifactReference,
)
from grafy_core.nodes import PortShape

from grafy_api.v1.models import ApiResponse, ArtifactTypeKeyResponse
from grafy_api.v1.routes.catalog.models import NodeSpecResponse, PortResponse
from grafy_api.v1.routes.saved_graphs.models import (
    CollaborativeHeadResponse,
    GraphCommandReceiptResponse,
)

from .services import (
    BuildReviewChangeKind,
    BuildReviewFileKind,
    VerifiedBuildReview,
    VerifiedBuildReviewChange,
    VerifiedBuildReviewContent,
    VerifiedBuildReviewFile,
)


AgentAnchorDirection = Literal["downstream", "upstream"]


class AgentAuthoringApiModel(ApiResponse):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        from_attributes=True,
        extra="forbid",
        allow_inf_nan=False,
    )


class CreateAgentEnvironmentRequest(AgentAuthoringApiModel):
    name: str = Field(min_length=1, max_length=160)
    profile_slug: Literal["python-uv"] = "python-uv"

    @field_validator("name")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip()


class AgentEnvironmentResponse(AgentAuthoringApiModel):
    id: UUID
    name: str
    profile_slug: str
    provider: str
    status: AgentEnvironmentStatus
    active_run_id: UUID | None = None
    failure_message: str | None = None
    created_at: datetime
    updated_at: datetime
    last_used_at: datetime | None = None

    @classmethod
    def from_environment(cls, environment: AgentEnvironment) -> Self:
        return cls(
            id=environment.id,
            name=environment.name,
            profile_slug=environment.profile_id,
            provider=environment.provider,
            status=environment.status,
            active_run_id=environment.active_run_id,
            failure_message=environment.failure_message,
            created_at=environment.created_at,
            updated_at=environment.updated_at,
            last_used_at=environment.last_used_at,
        )


class AgentEnvironmentListResponse(AgentAuthoringApiModel):
    environments: list[AgentEnvironmentResponse]

    @classmethod
    def from_environments(cls, environments: list[AgentEnvironment]) -> Self:
        return cls(
            environments=[
                AgentEnvironmentResponse.from_environment(environment)
                for environment in environments
            ]
        )


class PortConversionRequest(AgentAuthoringApiModel):
    id: str = Field(min_length=1, max_length=255)
    version: int = Field(ge=1)


class PortFeedRequest(AgentAuthoringApiModel):
    projection_path: tuple[str, ...] = ()
    conversion_path: tuple[PortConversionRequest, ...] = ()


class AnchoredPortRequest(AgentAuthoringApiModel):
    node_id: str = Field(min_length=1, max_length=255)
    port_name: str = Field(min_length=1, max_length=255)
    direction: AgentAnchorDirection
    artifact_type: ArtifactTypeKeyResponse
    shape: PortShape
    input_plug_id: str | None = Field(default=None, min_length=1, max_length=255)
    collection_mode: Literal["direct", "map"] = "direct"
    feed: PortFeedRequest = Field(default_factory=PortFeedRequest)

    @model_validator(mode="after")
    def validate_input_plug_direction(self) -> Self:
        if self.direction == "downstream" and self.input_plug_id is not None:
            raise ValueError(
                "input_plug_id is only valid when generating upstream of an input"
            )
        return self


class DraftGraphPlacementRequest(AgentAuthoringApiModel):
    node_id: str = Field(min_length=1, max_length=255)
    edge_id: str = Field(min_length=1, max_length=255)
    x: float
    y: float
    command_id: UUID
    room_epoch: UUID
    observed_sequence: int = Field(ge=0)


class CreateAgentDraftRequest(AgentAuthoringApiModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    idempotency_key: UUID
    environment_id: UUID | None = None
    thread_id: UUID | None = None
    anchor: AnchoredPortRequest
    placement: DraftGraphPlacementRequest

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def select_exactly_one_agent_context(self) -> Self:
        if (self.environment_id is None) == (self.thread_id is None):
            raise ValueError(
                "Exactly one of environment_id or thread_id must be provided"
            )
        if self.idempotency_key != self.placement.command_id:
            raise ValueError(
                "idempotency_key and placement.command_id must identify the same "
                "atomic operation"
            )
        return self


class ApproveBuildRequest(AgentAuthoringApiModel):
    capability_digest: str = Field(min_length=64, max_length=64, pattern="^[0-9a-f]+$")


class PublishGraphPromotionRequest(AgentAuthoringApiModel):
    graph_id: UUID
    node_id: str = Field(min_length=1, max_length=255)
    command_id: UUID
    room_epoch: UUID
    observed_sequence: int = Field(ge=0)


class PublishBuildRequest(AgentAuthoringApiModel):
    capability_approval_id: UUID
    graph_promotion: PublishGraphPromotionRequest | None = None


class QueueAgentFollowUpRequest(AgentAuthoringApiModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    idempotency_key: UUID
    draft_node_ids: tuple[UUID, ...] = Field(min_length=1, max_length=32)

    @field_validator("prompt")
    @classmethod
    def normalize_prompt(cls, value: str) -> str:
        return value.strip()

    @field_validator("draft_node_ids")
    @classmethod
    def require_unique_drafts(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("draft_node_ids must be unique")
        return value


class AgentThreadResponse(AgentAuthoringApiModel):
    id: UUID
    environment_id: UUID
    title: str
    event_sequence: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_thread(cls, thread: AgentThread) -> Self:
        return cls(
            id=thread.id,
            environment_id=thread.environment_id,
            title=thread.title,
            event_sequence=thread.event_sequence,
            created_at=thread.created_at,
            updated_at=thread.updated_at,
        )


class AnchoredPortResponse(AgentAuthoringApiModel):
    direction: AgentPortDirection
    name: str
    artifact_type: ArtifactTypeKeyResponse
    shape: PortShape
    collection_mode: Literal["direct", "map"]
    required: bool


class AgentDraftResponse(AgentAuthoringApiModel):
    id: UUID
    graph_id: UUID
    thread_id: UUID
    operator_id: str
    operator_version: int
    title: str
    description: str
    prompt: str
    status: DraftNodeStatus
    anchor: AnchoredPortResponse
    build_attempt_number: int
    published_revision: int
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_draft(cls, draft: DraftNode) -> Self:
        return cls(
            id=draft.id,
            graph_id=draft.graph_id,
            thread_id=draft.thread_id,
            operator_id=draft.operator_id,
            operator_version=draft.operator_version,
            title=draft.title,
            description=draft.description,
            prompt=draft.prompt,
            status=draft.status,
            anchor=AnchoredPortResponse(
                direction=draft.anchor.direction,
                name=draft.anchor.name,
                artifact_type=ArtifactTypeKeyResponse(
                    id=draft.anchor.artifact_type.id,
                    schema_version=draft.anchor.artifact_type.schema_version,
                ),
                shape=draft.anchor.shape,
                collection_mode=draft.anchor.collection_mode,
                required=draft.anchor.required,
            ),
            build_attempt_number=draft.build_attempt_number,
            published_revision=draft.published_revision,
            created_at=draft.created_at,
            updated_at=draft.updated_at,
        )


class AgentRunResponse(AgentAuthoringApiModel):
    id: UUID
    thread_id: UUID
    environment_id: UUID
    target_draft_ids: list[UUID]
    status: AgentRunStatus
    attempt: int
    cancellation_requested_at: datetime | None = None
    error: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_run(cls, run: AgentRun) -> Self:
        return cls(
            id=run.id,
            thread_id=run.thread_id,
            environment_id=run.environment_id,
            target_draft_ids=list(run.target_draft_ids),
            status=run.status,
            attempt=run.attempt,
            cancellation_requested_at=run.cancellation_requested_at,
            error=run.terminal_error,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )


class RuntimeLimitsResponse(AgentAuthoringApiModel):
    cpu_millis: int
    memory_megabytes: int
    wall_time_seconds: int
    process_count: int
    thread_count: int
    persistent_disk_bytes: int
    temporary_disk_bytes: int
    input_bytes: int
    output_bytes: int
    outbound_request_count: int
    outbound_response_bytes: int
    outbound_total_bytes: int


class ObjectStoreCapabilityResponse(AgentAuthoringApiModel):
    scope: ObjectStoreAccess
    prefix: str


class CapabilityManifestResponse(AgentAuthoringApiModel):
    outbound_http_origins: list[str]
    secret_refs: list[str]
    object_store: list[ObjectStoreCapabilityResponse]
    runtime: RuntimeLimitsResponse
    digest: str

    @classmethod
    def from_manifest(cls, manifest: CapabilityManifest) -> Self:
        return cls(
            outbound_http_origins=list(manifest.outbound_http_origins),
            secret_refs=list(manifest.secret_refs),
            object_store=[
                ObjectStoreCapabilityResponse(
                    scope=capability.scope,
                    prefix=capability.prefix,
                )
                for capability in manifest.object_store
            ],
            runtime=RuntimeLimitsResponse.model_validate(manifest.runtime),
            digest=manifest.digest,
        )


class RuntimeArtifactReferenceResponse(AgentAuthoringApiModel):
    provider: str
    ref: str
    digest: str

    @classmethod
    def from_reference(cls, reference: RuntimeArtifactReference) -> Self:
        return cls.model_validate(reference)


class BuildArtifactSetResponse(AgentAuthoringApiModel):
    source_digest: str
    lock_digest: str
    tests_digest: str
    build_digest: str
    implementation_digest: str
    runtime_image_digest: str
    profile_digest: str
    runtime_artifact: RuntimeArtifactReferenceResponse
    tests_passed: bool

    @classmethod
    def from_artifacts(cls, artifacts: BuildArtifactSet) -> Self:
        return cls.model_validate(artifacts)


class NodeBuildResponse(AgentAuthoringApiModel):
    id: UUID
    draft_node_id: UUID
    run_id: UUID
    attempt_number: int
    status: NodeBuildStatus
    capabilities: CapabilityManifestResponse | None = None
    artifacts: BuildArtifactSetResponse | None = None
    failure_message: str | None = None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_build(cls, build: NodeBuildAttempt) -> Self:
        return cls(
            id=build.id,
            draft_node_id=build.draft_node_id,
            run_id=build.run_id,
            attempt_number=build.attempt_number,
            status=build.status,
            capabilities=(
                CapabilityManifestResponse.from_manifest(build.capabilities)
                if build.capabilities is not None
                else None
            ),
            artifacts=(
                BuildArtifactSetResponse.from_artifacts(build.artifacts)
                if build.artifacts is not None
                else None
            ),
            failure_message=build.failure_message,
            created_at=build.created_at,
            updated_at=build.updated_at,
        )


class AgentEventResponse(AgentAuthoringApiModel):
    id: UUID
    thread_id: UUID
    run_id: UUID | None = None
    sequence: int
    kind: AgentEventKind
    message: str
    draft_node_id: UUID | None = None
    build_attempt_id: UUID | None = None
    run_status: AgentRunStatus | None = None
    build_status: NodeBuildStatus | None = None
    capability_digest: str | None = None
    release_revision: int | None = None
    created_at: datetime

    @classmethod
    def from_event(cls, event: AgentEvent) -> Self:
        return cls(
            id=event.id,
            thread_id=event.thread_id,
            run_id=event.run_id,
            sequence=event.sequence,
            kind=event.kind,
            message=event.payload.message,
            draft_node_id=event.payload.draft_node_id,
            build_attempt_id=event.payload.build_attempt_id,
            run_status=event.payload.run_status,
            build_status=event.payload.build_status,
            capability_digest=event.payload.capability_digest,
            release_revision=event.payload.release_revision,
            created_at=event.created_at,
        )


class AgentRunDetailResponse(AgentAuthoringApiModel):
    run: AgentRunResponse
    builds: list[NodeBuildResponse]

    @classmethod
    def from_run_and_builds(
        cls,
        run: AgentRun,
        builds: list[NodeBuildAttempt],
    ) -> Self:
        return cls(
            run=AgentRunResponse.from_run(run),
            builds=[NodeBuildResponse.from_build(build) for build in builds],
        )


class AgentFollowUpRunResponse(AgentAuthoringApiModel):
    environment: AgentEnvironmentResponse
    thread: AgentThreadResponse
    run: AgentRunResponse
    builds: list[NodeBuildResponse]
    node_specs: list[NodeSpecResponse]


class BuildReviewFileResponse(AgentAuthoringApiModel):
    path: str
    kind: BuildReviewFileKind
    byte_count: int
    sha256: str

    @classmethod
    def from_file(cls, file: VerifiedBuildReviewFile) -> Self:
        return cls.model_validate(file)


class BuildReviewChangeResponse(AgentAuthoringApiModel):
    path: str
    kind: BuildReviewFileKind
    change: BuildReviewChangeKind
    previous_sha256: str | None
    current_sha256: str | None
    unified_diff: str | None
    diff_truncated: bool

    @classmethod
    def from_change(cls, change: VerifiedBuildReviewChange) -> Self:
        return cls.model_validate(change)


class BuildTestSummaryResponse(AgentAuthoringApiModel):
    passed: bool
    file_count: int
    digest: str


class BuildLockSummaryResponse(AgentAuthoringApiModel):
    path: Literal["uv.lock"] = "uv.lock"
    byte_count: int
    digest: str


class BuildReviewResponse(AgentAuthoringApiModel):
    build: NodeBuildResponse
    node_spec: NodeSpecResponse
    source_digest: str
    archive_byte_count: int
    uncompressed_byte_count: int
    implementation_digest: str
    previous_release_revision: int | None
    lock: BuildLockSummaryResponse
    tests: BuildTestSummaryResponse
    files: list[BuildReviewFileResponse]
    changes: list[BuildReviewChangeResponse]

    @classmethod
    def from_review(
        cls,
        review: VerifiedBuildReview,
        *,
        build: NodeBuildAttempt,
        node_spec: NodeSpecResponse,
    ) -> Self:
        lock_file = next(file for file in review.files if file.path == "uv.lock")
        return cls(
            build=NodeBuildResponse.from_build(build),
            node_spec=node_spec,
            source_digest=review.source_digest,
            archive_byte_count=review.archive_byte_count,
            uncompressed_byte_count=review.uncompressed_byte_count,
            implementation_digest=review.implementation_digest,
            previous_release_revision=review.previous_release_revision,
            lock=BuildLockSummaryResponse(
                byte_count=lock_file.byte_count,
                digest=review.lock_digest,
            ),
            tests=BuildTestSummaryResponse(
                passed=review.tests_passed,
                file_count=sum(file.kind == "test" for file in review.files),
                digest=review.tests_digest,
            ),
            files=[BuildReviewFileResponse.from_file(file) for file in review.files],
            changes=[
                BuildReviewChangeResponse.from_change(change)
                for change in review.changes
            ],
        )


class BuildReviewFileContentResponse(AgentAuthoringApiModel):
    path: str
    kind: BuildReviewFileKind
    byte_count: int
    sha256: str
    content: str

    @classmethod
    def from_content(cls, content: VerifiedBuildReviewContent) -> Self:
        return cls.model_validate(content)


class CapabilityApprovalResponse(AgentAuthoringApiModel):
    id: UUID
    draft_node_id: UUID
    build_attempt_id: UUID
    capability_digest: str
    approved_by_user_id: UUID
    approved_at: datetime

    @classmethod
    def from_approval(cls, approval: CapabilityApproval) -> Self:
        return cls.model_validate(approval)


class NodeReleaseResponse(AgentAuthoringApiModel):
    node_id: UUID
    revision: int
    draft_node_id: UUID
    build_attempt_id: UUID
    thread_id: UUID
    environment_id: UUID
    operator_id: str
    operator_version: int
    capabilities: CapabilityManifestResponse
    artifacts: BuildArtifactSetResponse
    capability_approval_id: UUID
    approved_by_user_id: UUID
    created_at: datetime

    @classmethod
    def from_release(cls, release: NodeRelease) -> Self:
        return cls(
            node_id=release.node_id,
            revision=release.revision,
            draft_node_id=release.draft_node_id,
            build_attempt_id=release.build_attempt_id,
            thread_id=release.thread_id,
            environment_id=release.environment_id,
            operator_id=release.operator_id,
            operator_version=release.operator_version,
            capabilities=CapabilityManifestResponse.from_manifest(
                release.capabilities
            ),
            artifacts=BuildArtifactSetResponse.from_artifacts(release.artifacts),
            capability_approval_id=release.capability_approval_id,
            approved_by_user_id=release.approved_by_user_id,
            created_at=release.created_at,
        )


class PublishBuildResponse(AgentAuthoringApiModel):
    release: NodeReleaseResponse
    node_spec: NodeSpecResponse
    head: CollaborativeHeadResponse | None = None
    receipt: GraphCommandReceiptResponse | None = None

    @classmethod
    def from_release(cls, release: NodeRelease, *, runnable: bool) -> Self:
        return cls(
            release=NodeReleaseResponse.from_release(release),
            node_spec=NodeSpecResponse.from_agent_release(
                release,
                runnable=runnable,
            ),
        )


class AgentDraftDetailResponse(AgentAuthoringApiModel):
    environment: AgentEnvironmentResponse
    thread: AgentThreadResponse
    draft: AgentDraftResponse
    latest_run: AgentRunResponse
    latest_build: NodeBuildResponse
    node_spec: NodeSpecResponse
    release: NodeReleaseResponse | None
    capability_approval: CapabilityApprovalResponse | None


class CreateAgentDraftResponse(AgentAuthoringApiModel):
    environment: AgentEnvironmentResponse
    thread: AgentThreadResponse
    draft: AgentDraftResponse
    run: AgentRunResponse
    build: NodeBuildResponse
    node_spec: NodeSpecResponse
    anchor_port: PortResponse
    head: CollaborativeHeadResponse
    receipt: GraphCommandReceiptResponse


__all__ = [
    "AgentAnchorDirection",
    "AgentAuthoringApiModel",
    "AgentDraftResponse",
    "AgentDraftDetailResponse",
    "AgentEnvironmentListResponse",
    "AgentEnvironmentResponse",
    "AgentEventResponse",
    "AgentRunResponse",
    "AgentRunDetailResponse",
    "AgentFollowUpRunResponse",
    "AgentThreadResponse",
    "AnchoredPortRequest",
    "AnchoredPortResponse",
    "ApproveBuildRequest",
    "BuildArtifactSetResponse",
    "BuildLockSummaryResponse",
    "BuildReviewChangeResponse",
    "BuildReviewFileContentResponse",
    "BuildReviewFileResponse",
    "BuildReviewResponse",
    "BuildTestSummaryResponse",
    "CapabilityApprovalResponse",
    "CapabilityManifestResponse",
    "CreateAgentDraftResponse",
    "CreateAgentDraftRequest",
    "CreateAgentEnvironmentRequest",
    "DraftGraphPlacementRequest",
    "NodeBuildResponse",
    "NodeReleaseResponse",
    "ObjectStoreCapabilityResponse",
    "PortConversionRequest",
    "PortFeedRequest",
    "PublishBuildRequest",
    "PublishBuildResponse",
    "PublishGraphPromotionRequest",
    "QueueAgentFollowUpRequest",
    "RuntimeLimitsResponse",
    "RuntimeArtifactReferenceResponse",
]
