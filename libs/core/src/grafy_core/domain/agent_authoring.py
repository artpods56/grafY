"""Durable authoring state for agent-authored Python nodes."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from hashlib import sha256
from ipaddress import ip_address
import json
import re
from typing import ClassVar, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from grafy_core.nodes import PortShape


GENERATED_NODE_OPERATOR_PREFIX = "generated.node."
GENERATED_NODE_OPERATOR_VERSION = 1
MAX_AGENT_PROMPT_LENGTH = 20_000
MAX_AGENT_EVENT_MESSAGE_LENGTH = 4_000


class AgentAuthoringError(ValueError):
    """An agent-authoring invariant would be violated."""


class AgentAuthoringConflictError(AgentAuthoringError):
    """Mutable authoring state no longer permits the requested operation."""


class AgentAuthoringIdempotencyError(AgentAuthoringConflictError):
    """An idempotency key was reused for a different request."""


class GeneratedNodeReferenceError(ValueError):
    """A generated-node operator identity is malformed."""


class AgentEnvironmentStatus(StrEnum):
    PROVISIONING = "provisioning"
    CREATING = "creating"
    READY = "ready"
    SUSPENDED = "suspended"
    FAILED = "failed"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class GeneratedNodeReference:
    node_id: UUID
    revision: int

    operator_prefix: ClassVar[str] = GENERATED_NODE_OPERATOR_PREFIX

    def __post_init__(self) -> None:
        if isinstance(self.revision, bool) or self.revision < 1:
            raise GeneratedNodeReferenceError(
                "Generated node revision must be a positive integer"
            )

    @property
    def operator_id(self) -> str:
        return f"{self.operator_prefix}{self.node_id}"

    @property
    def operator_version(self) -> int:
        return self.revision

    @classmethod
    def from_operator_identity(
        cls,
        operator_id: str,
        operator_version: int,
    ) -> Self:
        if not operator_id.startswith(cls.operator_prefix):
            raise GeneratedNodeReferenceError(
                f"Operator {operator_id!r}@{operator_version} is not an "
                "agent-authored node operator"
            )
        raw_node_id = operator_id.removeprefix(cls.operator_prefix)
        try:
            node_id = UUID(raw_node_id)
        except ValueError as exc:
            raise GeneratedNodeReferenceError(
                f"Generated node operator {operator_id!r}@{operator_version} "
                "contains an invalid node UUID"
            ) from exc
        return cls(node_id=node_id, revision=operator_version)

    @classmethod
    def try_from_operator_identity(
        cls,
        operator_id: str,
        operator_version: int,
    ) -> Self | None:
        if not operator_id.startswith(cls.operator_prefix):
            return None
        return cls.from_operator_identity(operator_id, operator_version)


class AgentPortDirection(StrEnum):
    INPUT = "input"
    OUTPUT = "output"


class DraftNodeStatus(StrEnum):
    DRAFT = "draft"
    AUTHORING = "authoring"
    AWAITING_APPROVAL = "awaiting_approval"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    INTERRUPTING = "interrupting"
    INTERRUPTED = "interrupted"


class NodeBuildStatus(StrEnum):
    QUEUED = "queued"
    PREPARING = "preparing"
    CODING = "coding"
    TESTING = "testing"
    AWAITING_APPROVAL = "awaiting_approval"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SUPERSEDED = "superseded"
    PUBLISHED = "published"


class AgentEventKind(StrEnum):
    RUN_QUEUED = "run_queued"
    RUN_CLAIMED = "run_claimed"
    RUN_STATUS_CHANGED = "run_status_changed"
    BUILD_STATUS_CHANGED = "build_status_changed"
    CAPABILITIES_REQUESTED = "capabilities_requested"
    CAPABILITIES_APPROVED = "capabilities_approved"
    RELEASE_PUBLISHED = "release_published"
    MESSAGE = "message"


class ObjectStoreAccess(StrEnum):
    READ = "read"
    WRITE = "write"
    READ_WRITE = "read_write"


class AgentAuthoringValue(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
    )


def _required_text(value: str, label: str, maximum: int) -> str:
    normalized = value.strip()
    if normalized == "":
        raise AgentAuthoringError(f"{label} must not be blank")
    if len(normalized) > maximum:
        raise AgentAuthoringError(f"{label} must be at most {maximum} characters")
    return normalized


def _aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None:
        raise AgentAuthoringError(f"{label} must be timezone-aware")
    return value


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _sha256(value: str, label: str) -> str:
    normalized = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return normalized


class AgentArtifactType(AgentAuthoringValue):
    id: str = Field(min_length=1, max_length=255)
    schema_version: int = Field(ge=1)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != value:
            raise ValueError("Artifact type id must not contain surrounding whitespace")
        return normalized


class PortConversion(AgentAuthoringValue):
    id: str = Field(min_length=1, max_length=255)
    version: int = Field(ge=1)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != value:
            raise ValueError("Conversion id must not contain surrounding whitespace")
        return normalized


class PortFeed(AgentAuthoringValue):
    projection_path: tuple[str, ...] = ()
    conversion_path: tuple[PortConversion, ...] = ()

    @field_validator("projection_path")
    @classmethod
    def validate_projection_path(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for segment in value:
            if segment.strip() == "" or segment != segment.strip():
                raise ValueError("Projection path segments must be non-blank and trimmed")
            if len(segment) > 255:
                raise ValueError("Projection path segments must be at most 255 characters")
        return value


class AnchoredPortContract(AgentAuthoringValue):
    """The generated port contract already owned by the canvas edge."""

    direction: AgentPortDirection
    name: str = Field(min_length=1, max_length=255)
    artifact_type: AgentArtifactType
    shape: PortShape
    collection_mode: Literal["direct", "map"] = "direct"
    feed: PortFeed = Field(default_factory=PortFeed)
    required: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if re.fullmatch(r"[a-z][a-z0-9_]*", value) is None:
            raise ValueError(
                "Generated port names must start with a lowercase letter and "
                "contain only lowercase letters, digits, and underscores"
            )
        return value


class GeneratedNodePort(AgentAuthoringValue):
    direction: AgentPortDirection
    name: str = Field(min_length=1, max_length=255)
    artifact_type: AgentArtifactType
    shape: PortShape
    accepted_shapes: tuple[PortShape, ...] = ()
    required: bool = True

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        if re.fullmatch(r"[a-z][a-z0-9_]*", value) is None:
            raise ValueError(
                "Generated port names must start with a lowercase letter and "
                "contain only lowercase letters, digits, and underscores"
            )
        return value

    @model_validator(mode="after")
    def validate_direction_contract(self) -> Self:
        if self.direction is AgentPortDirection.INPUT:
            accepted = self.accepted_shapes or (self.shape,)
            if len(accepted) != len(set(accepted)):
                raise ValueError("Generated input accepted shapes must be unique")
            if self.shape not in accepted:
                raise ValueError(
                    "Generated input accepted shapes must include its primary shape"
                )
            object.__setattr__(self, "accepted_shapes", accepted)
        elif self.accepted_shapes:
            raise ValueError("Generated output ports do not declare accepted shapes")
        return self

    @classmethod
    def from_anchor(cls, anchor: AnchoredPortContract) -> Self:
        accepted_shapes: tuple[PortShape, ...] = ()
        if anchor.direction is AgentPortDirection.INPUT:
            accepted_shapes = (anchor.shape,)
        return cls(
            direction=anchor.direction,
            name=anchor.name,
            artifact_type=anchor.artifact_type,
            shape=anchor.shape,
            accepted_shapes=accepted_shapes,
            required=anchor.required,
        )


class GeneratedNodeManifest(AgentAuthoringValue):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=1_000)
    inputs: tuple[GeneratedNodePort, ...] = ()
    outputs: tuple[GeneratedNodePort, ...] = ()

    @field_validator("title", "description")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Generated node manifest text must not be blank")
        return normalized

    @model_validator(mode="after")
    def validate_ports(self) -> Self:
        if not self.inputs and not self.outputs:
            raise ValueError("Generated node manifest must declare at least one port")
        if any(port.direction is not AgentPortDirection.INPUT for port in self.inputs):
            raise ValueError("Generated node manifest inputs must be input ports")
        if any(
            port.direction is not AgentPortDirection.OUTPUT for port in self.outputs
        ):
            raise ValueError("Generated node manifest outputs must be output ports")
        names = [port.name for port in (*self.inputs, *self.outputs)]
        if len(names) != len(set(names)):
            raise ValueError("Generated node port names must be unique")
        return self

    def preserves(self, anchor: AnchoredPortContract) -> bool:
        candidates = (
            self.inputs
            if anchor.direction is AgentPortDirection.INPUT
            else self.outputs
        )
        expected = GeneratedNodePort.from_anchor(anchor)
        return expected in candidates


class ObjectStoreCapability(AgentAuthoringValue):
    scope: ObjectStoreAccess
    prefix: str = Field(min_length=1, max_length=1_024)

    @field_validator("prefix")
    @classmethod
    def validate_prefix(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("Object-store capability prefixes must be relative")
        return normalized


class RuntimeLimits(AgentAuthoringValue):
    cpu_millis: int = Field(default=1_000, ge=100, le=64_000)
    memory_megabytes: int = Field(default=512, ge=64, le=131_072)
    wall_time_seconds: int = Field(default=60, ge=1, le=86_400)
    process_count: int = Field(default=16, ge=1, le=1_024)
    thread_count: int = Field(default=64, ge=1, le=4_096)
    persistent_disk_bytes: int = Field(
        default=1_073_741_824,
        ge=1,
        le=1_099_511_627_776,
    )
    temporary_disk_bytes: int = Field(
        default=1_073_741_824,
        ge=1,
        le=1_099_511_627_776,
    )
    input_bytes: int = Field(default=16_777_216, ge=1, le=1_073_741_824)
    output_bytes: int = Field(default=16_777_216, ge=1, le=1_073_741_824)
    outbound_request_count: int = Field(default=64, ge=0, le=1_000_000)
    outbound_response_bytes: int = Field(
        default=16_777_216,
        ge=0,
        le=1_073_741_824,
    )
    outbound_total_bytes: int = Field(
        default=67_108_864,
        ge=0,
        le=1_099_511_627_776,
    )

    @model_validator(mode="after")
    def validate_outbound_budget(self) -> Self:
        if self.outbound_response_bytes > self.outbound_total_bytes:
            raise ValueError(
                "Per-response outbound bytes must not exceed total outbound bytes"
            )
        return self


def _normalize_http_origin(value: str) -> str:
    raw = value.strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"https", "http"} or parsed.hostname is None:
        raise ValueError(f"Invalid outbound HTTP origin {value!r}")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Outbound HTTP origins must not contain credentials")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("Outbound HTTP capabilities must be origins without paths")
    host = parsed.hostname.lower()
    if parsed.scheme != "https":
        raise ValueError("Outbound HTTP capabilities must use HTTPS")
    if host == "localhost" or host.endswith(".localhost"):
        raise ValueError("Outbound HTTP capabilities must not target localhost")
    try:
        literal_address = ip_address(host)
    except ValueError:
        literal_address = None
    if literal_address is not None and (
        literal_address.is_private
        or literal_address.is_loopback
        or literal_address.is_link_local
        or literal_address.is_multicast
        or literal_address.is_reserved
        or literal_address.is_unspecified
    ):
        raise ValueError(
            "Outbound HTTP capabilities must not target a non-public IP address"
        )
    default_port = 443 if parsed.scheme == "https" else 80
    try:
        port = parsed.port or default_port
    except ValueError as exc:
        raise ValueError(f"Invalid outbound HTTP origin {value!r}") from exc
    rendered_port = "" if port == default_port else f":{port}"
    rendered_host = f"[{host}]" if ":" in host else host
    return f"{parsed.scheme}://{rendered_host}{rendered_port}"


class CapabilityManifest(AgentAuthoringValue):
    outbound_http_origins: tuple[str, ...] = ()
    secret_refs: tuple[str, ...] = ()
    object_store: tuple[ObjectStoreCapability, ...] = ()
    runtime: RuntimeLimits = Field(default_factory=RuntimeLimits)

    @field_validator("outbound_http_origins")
    @classmethod
    def normalize_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted({_normalize_http_origin(origin) for origin in value}))

    @field_validator("secret_refs")
    @classmethod
    def normalize_secret_refs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: set[str] = set()
        for secret_ref in value:
            candidate = secret_ref.strip()
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,254}", candidate) is None:
                raise ValueError(f"Invalid secret reference {secret_ref!r}")
            normalized.add(candidate)
        return tuple(sorted(normalized))

    @field_validator("object_store")
    @classmethod
    def normalize_object_store(
        cls,
        value: tuple[ObjectStoreCapability, ...],
    ) -> tuple[ObjectStoreCapability, ...]:
        unique = {(item.scope.value, item.prefix): item for item in value}
        return tuple(unique[key] for key in sorted(unique))

    @property
    def digest(self) -> str:
        canonical = json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return sha256(canonical).hexdigest()


class RuntimeArtifactReference(AgentAuthoringValue):
    provider: str = Field(min_length=1, max_length=255)
    ref: str = Field(min_length=1, max_length=2_048)
    digest: str

    @field_validator("provider", "ref")
    @classmethod
    def validate_text(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Runtime artifact identity must not be blank")
        return normalized

    @field_validator("digest")
    @classmethod
    def validate_digest(cls, value: str) -> str:
        return _sha256(value, "Runtime artifact digest")


class BuildArtifactSet(AgentAuthoringValue):
    source_bundle_key: str = Field(min_length=1, max_length=2_048)
    source_digest: str
    lock_digest: str
    tests_digest: str
    build_digest: str
    implementation_digest: str
    runtime_image_digest: str
    profile_digest: str
    runtime_artifact: RuntimeArtifactReference
    tests_passed: bool

    @field_validator(
        "source_digest",
        "lock_digest",
        "tests_digest",
        "build_digest",
        "implementation_digest",
        "runtime_image_digest",
        "profile_digest",
    )
    @classmethod
    def validate_digest(cls, value: str) -> str:
        return _sha256(value, "Build artifact digest")

    @field_validator("source_bundle_key")
    @classmethod
    def validate_source_bundle_key(cls, value: str) -> str:
        normalized = value.strip()
        if normalized.startswith("/") or ".." in normalized.split("/"):
            raise ValueError("Source bundle key must be a relative object key")
        return normalized
class AgentEventPayload(AgentAuthoringValue):
    message: str = Field(min_length=1, max_length=MAX_AGENT_EVENT_MESSAGE_LENGTH)
    draft_node_id: UUID | None = None
    build_attempt_id: UUID | None = None
    run_status: AgentRunStatus | None = None
    build_status: NodeBuildStatus | None = None
    capability_digest: str | None = None
    release_revision: int | None = Field(default=None, ge=1)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Agent event message must not be blank")
        return normalized

    @field_validator("capability_digest")
    @classmethod
    def validate_capability_digest(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _sha256(value, "Capability digest")


@dataclass
class AgentEnvironment:
    workspace_id: UUID
    name: str
    profile_id: str
    provider: str
    created_by_user_id: UUID | None = None
    status: AgentEnvironmentStatus = AgentEnvironmentStatus.PROVISIONING
    provider_environment_id: str | None = None
    provisioning_owner: str | None = None
    provisioning_token: UUID | None = field(default=None, repr=False)
    provisioning_expires_at: datetime | None = None
    provisioning_fencing_token: int = 0
    active_run_id: UUID | None = None
    failure_message: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)
    last_used_at: datetime | None = None

    def __post_init__(self) -> None:
        self.name = _required_text(self.name, "Agent environment name", 160)
        self.profile_id = _required_text(
            self.profile_id, "Agent environment profile id", 255
        )
        self.provider = _required_text(
            self.provider, "Agent environment provider", 255
        )
        self.status = AgentEnvironmentStatus(self.status)
        _aware(self.created_at, "Agent environment created_at")
        _aware(self.updated_at, "Agent environment updated_at")
        if self.last_used_at is not None:
            _aware(self.last_used_at, "Agent environment last_used_at")

        if self.provisioning_expires_at is not None:
            _aware(
                self.provisioning_expires_at,
                "Agent environment provisioning_expires_at",
            )
        if (
            isinstance(self.provisioning_fencing_token, bool)
            or self.provisioning_fencing_token < 0
        ):
            raise AgentAuthoringError(
                "Environment provisioning fencing token must not be negative"
            )

    def provisioning_lease_is_expired(self, when: datetime) -> bool:
        _aware(when, "Provisioning lease comparison time")
        return (
            self.provisioning_expires_at is not None
            and self.provisioning_expires_at <= when
        )

    def claim_provisioning(
        self,
        *,
        worker_id: str,
        provisioning_token: UUID,
        provisioning_expires_at: datetime,
        when: datetime | None = None,
    ) -> None:
        timestamp = when or _utc_now()
        reclaiming = (
            self.status is AgentEnvironmentStatus.CREATING
            and self.provisioning_lease_is_expired(timestamp)
        )
        if self.status is not AgentEnvironmentStatus.PROVISIONING and not reclaiming:
            raise AgentAuthoringConflictError(
                f"Environment {self.id} is not currently provisionable"
            )
        _aware(
            provisioning_expires_at,
            "Agent environment provisioning_expires_at",
        )
        if provisioning_expires_at <= timestamp:
            raise AgentAuthoringError(
                "Environment provisioning lease must expire in the future"
            )
        self.status = AgentEnvironmentStatus.CREATING
        self.provisioning_owner = _required_text(
            worker_id,
            "Environment provisioning worker id",
            255,
        )
        self.provisioning_token = provisioning_token
        self.provisioning_expires_at = provisioning_expires_at
        self.provisioning_fencing_token += 1
        self.failure_message = None
        self.updated_at = timestamp

    def heartbeat_provisioning(
        self,
        *,
        provisioning_token: UUID,
        provisioning_fencing_token: int,
        provisioning_expires_at: datetime,
        when: datetime | None = None,
    ) -> None:
        timestamp = when or _utc_now()
        self._require_provisioning_lease(
            provisioning_token,
            provisioning_fencing_token,
            when=timestamp,
        )
        _aware(
            provisioning_expires_at,
            "Agent environment provisioning_expires_at",
        )
        if provisioning_expires_at <= timestamp:
            raise AgentAuthoringError(
                "Environment provisioning lease must expire in the future"
            )
        self.provisioning_expires_at = provisioning_expires_at
        self.updated_at = timestamp

    def complete_provisioning(
        self,
        *,
        provider_environment_id: str,
        provisioning_token: UUID,
        provisioning_fencing_token: int,
        when: datetime | None = None,
    ) -> None:
        timestamp = when or _utc_now()
        self._require_provisioning_lease(
            provisioning_token,
            provisioning_fencing_token,
            when=timestamp,
        )
        self.provider_environment_id = _required_text(
            provider_environment_id,
            "Provider environment id",
            1_024,
        )
        self.status = AgentEnvironmentStatus.READY
        self.failure_message = None
        self._clear_provisioning_lease()
        self.updated_at = timestamp

    def fail_provisioning(
        self,
        *,
        error: str,
        provisioning_token: UUID,
        provisioning_fencing_token: int,
        when: datetime | None = None,
    ) -> None:
        timestamp = when or _utc_now()
        self._require_provisioning_lease(
            provisioning_token,
            provisioning_fencing_token,
            when=timestamp,
        )
        self.status = AgentEnvironmentStatus.FAILED
        self.failure_message = _required_text(
            error,
            "Agent environment failure",
            4_000,
        )
        self._clear_provisioning_lease()
        self.updated_at = timestamp

    def _require_provisioning_lease(
        self,
        provisioning_token: UUID,
        provisioning_fencing_token: int,
        *,
        when: datetime,
    ) -> None:
        if (
            self.status is not AgentEnvironmentStatus.CREATING
            or self.provisioning_token != provisioning_token
            or self.provisioning_fencing_token != provisioning_fencing_token
        ):
            raise AgentAuthoringConflictError(
                f"Environment {self.id} provisioning lease is stale"
            )
        if self.provisioning_lease_is_expired(when):
            raise AgentAuthoringConflictError(
                f"Environment {self.id} provisioning lease expired"
            )

    def _clear_provisioning_lease(self) -> None:
        self.provisioning_owner = None
        self.provisioning_token = None
        self.provisioning_expires_at = None

    def claim_writer(self, run_id: UUID, *, when: datetime | None = None) -> None:
        if self.status is not AgentEnvironmentStatus.READY:
            raise AgentAuthoringConflictError(
                f"Environment {self.id} is not ready for an agent run"
            )
        if self.active_run_id not in {None, run_id}:
            raise AgentAuthoringConflictError(
                f"Environment {self.id} already has active writer {self.active_run_id}"
            )
        timestamp = when or _utc_now()
        self.active_run_id = run_id
        self.last_used_at = timestamp
        self.updated_at = timestamp

    def release_writer(self, run_id: UUID, *, when: datetime | None = None) -> None:
        if self.active_run_id == run_id:
            self.active_run_id = None
            self.updated_at = when or _utc_now()


@dataclass
class AgentThread:
    workspace_id: UUID
    environment_id: UUID
    title: str
    created_by_user_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    event_sequence: int = 0
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.title = _required_text(self.title, "Agent thread title", 160)
        if isinstance(self.event_sequence, bool) or self.event_sequence < 0:
            raise AgentAuthoringError("Agent thread event sequence must not be negative")
        _aware(self.created_at, "Agent thread created_at")
        _aware(self.updated_at, "Agent thread updated_at")

    def record_event(
        self,
        *,
        kind: AgentEventKind,
        payload: AgentEventPayload,
        run_id: UUID | None,
        when: datetime | None = None,
    ) -> "AgentEvent":
        timestamp = when or _utc_now()
        self.event_sequence += 1
        self.updated_at = timestamp
        return AgentEvent(
            workspace_id=self.workspace_id,
            thread_id=self.id,
            sequence=self.event_sequence,
            kind=kind,
            payload=payload,
            run_id=run_id,
            created_at=timestamp,
        )


@dataclass
class DraftNode:
    workspace_id: UUID
    thread_id: UUID
    graph_id: UUID
    title: str
    description: str
    prompt: str
    anchor: AnchoredPortContract
    created_by_user_id: UUID | None = None
    status: DraftNodeStatus = DraftNodeStatus.DRAFT
    id: UUID = field(default_factory=uuid4)
    build_attempt_number: int = 0
    published_revision: int = 0
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.title = _required_text(self.title, "Draft node title", 160)
        self.description = _required_text(
            self.description, "Draft node description", 1_000
        )
        self.prompt = _required_text(self.prompt, "Draft node prompt", MAX_AGENT_PROMPT_LENGTH)
        self.status = DraftNodeStatus(self.status)
        if isinstance(self.build_attempt_number, bool) or self.build_attempt_number < 0:
            raise AgentAuthoringError("Draft build attempt number must not be negative")
        if isinstance(self.published_revision, bool) or self.published_revision < 0:
            raise AgentAuthoringError("Draft published revision must not be negative")
        _aware(self.created_at, "Draft node created_at")
        _aware(self.updated_at, "Draft node updated_at")

    @property
    def operator_id(self) -> str:
        return f"{GENERATED_NODE_OPERATOR_PREFIX}{self.id}"

    @property
    def operator_version(self) -> int:
        return self.published_revision + 1

    @property
    def provisional_manifest(self) -> GeneratedNodeManifest:
        anchor_port = GeneratedNodePort.from_anchor(self.anchor)
        inputs: tuple[GeneratedNodePort, ...] = ()
        outputs: tuple[GeneratedNodePort, ...] = ()
        if self.anchor.direction is AgentPortDirection.INPUT:
            inputs = (anchor_port,)
        else:
            outputs = (anchor_port,)
        return GeneratedNodeManifest(
            title=self.title,
            description=self.description,
            inputs=inputs,
            outputs=outputs,
        )

    def begin_build(self, *, when: datetime | None = None) -> int:
        self.build_attempt_number += 1
        self.status = DraftNodeStatus.AUTHORING
        self.updated_at = when or _utc_now()
        return self.build_attempt_number

    def await_approval(self, *, when: datetime | None = None) -> None:
        self.status = DraftNodeStatus.AWAITING_APPROVAL
        self.updated_at = when or _utc_now()

    def mark_failed(self, *, when: datetime | None = None) -> None:
        if self.status is DraftNodeStatus.PUBLISHED:
            raise AgentAuthoringConflictError("A published node cannot fail as a draft")
        self.status = DraftNodeStatus.FAILED
        self.updated_at = when or _utc_now()

    def cancel(self, *, when: datetime | None = None) -> None:
        if self.status is DraftNodeStatus.PUBLISHED:
            raise AgentAuthoringConflictError("A published node cannot be cancelled")
        self.status = DraftNodeStatus.CANCELLED
        self.updated_at = when or _utc_now()

    def publish(self, revision: int, *, when: datetime | None = None) -> None:
        if self.status is not DraftNodeStatus.AWAITING_APPROVAL:
            raise AgentAuthoringConflictError(
                "Only a draft awaiting approval can be published"
            )
        if revision != self.published_revision + 1:
            raise AgentAuthoringConflictError(
                "Generated node release revisions must increase monotonically"
            )
        self.published_revision = revision
        self.status = DraftNodeStatus.PUBLISHED
        self.updated_at = when or _utc_now()


_RUN_TERMINAL_STATUSES = frozenset(
    {
        AgentRunStatus.COMPLETED,
        AgentRunStatus.FAILED,
        AgentRunStatus.CANCELLED,
        AgentRunStatus.INTERRUPTED,
    }
)


@dataclass(frozen=True)
class RevokedAgentLease:
    owner: str
    token: UUID = field(repr=False)
    fencing_token: int


@dataclass
class AgentRun:
    workspace_id: UUID
    thread_id: UUID
    environment_id: UUID
    target_draft_ids: tuple[UUID, ...]
    instructions: str
    idempotency_key: str
    request_digest: str
    created_by_user_id: UUID | None = None
    continued_from_run_id: UUID | None = None
    status: AgentRunStatus = AgentRunStatus.QUEUED
    id: UUID = field(default_factory=uuid4)
    attempt: int = 0
    lease_owner: str | None = None
    lease_token: UUID | None = field(default=None, repr=False)
    lease_expires_at: datetime | None = None
    lease_heartbeat_at: datetime | None = None
    fencing_token: int = 0
    cancellation_requested_at: datetime | None = None
    terminal_error: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if not self.target_draft_ids:
            raise AgentAuthoringError("Agent run must target at least one draft")
        if len(self.target_draft_ids) != len(set(self.target_draft_ids)):
            raise AgentAuthoringError("Agent run target drafts must be unique")
        self.instructions = _required_text(
            self.instructions, "Agent run instructions", MAX_AGENT_PROMPT_LENGTH
        )
        self.idempotency_key = _required_text(
            self.idempotency_key, "Agent run idempotency key", 255
        )
        self.request_digest = _sha256(self.request_digest, "Agent run request digest")
        self.status = AgentRunStatus(self.status)
        if isinstance(self.attempt, bool) or self.attempt < 0:
            raise AgentAuthoringError("Agent run attempt must not be negative")
        if isinstance(self.fencing_token, bool) or self.fencing_token < 0:
            raise AgentAuthoringError("Agent run fencing token must not be negative")
        _aware(self.created_at, "Agent run created_at")
        _aware(self.updated_at, "Agent run updated_at")
        for value, label in (
            (self.lease_expires_at, "Agent run lease_expires_at"),
            (self.lease_heartbeat_at, "Agent run lease_heartbeat_at"),
            (self.cancellation_requested_at, "Agent run cancellation_requested_at"),
        ):
            if value is not None:
                _aware(value, label)

    @property
    def is_terminal(self) -> bool:
        return self.status in _RUN_TERMINAL_STATUSES

    def lease_is_expired(self, when: datetime) -> bool:
        _aware(when, "Lease comparison time")
        return self.lease_expires_at is not None and self.lease_expires_at <= when

    def claim(
        self,
        *,
        worker_id: str,
        lease_token: UUID,
        lease_expires_at: datetime,
        when: datetime | None = None,
    ) -> None:
        timestamp = when or _utc_now()
        worker = _required_text(worker_id, "Agent worker id", 255)
        _aware(lease_expires_at, "Agent run lease_expires_at")
        reclaiming_expired_claim = (
            self.status is AgentRunStatus.CLAIMED and self.lease_is_expired(timestamp)
        )
        if self.status is not AgentRunStatus.QUEUED and not reclaiming_expired_claim:
            raise AgentAuthoringConflictError(
                f"Agent run {self.id} cannot be claimed from {self.status.value}"
            )
        if lease_expires_at <= timestamp:
            raise AgentAuthoringError("Agent run lease must expire in the future")
        self.status = AgentRunStatus.CLAIMED
        self.attempt += 1
        self.fencing_token += 1
        self.lease_owner = worker
        self.lease_token = lease_token
        self.lease_expires_at = lease_expires_at
        self.lease_heartbeat_at = timestamp
        self.updated_at = timestamp

    def start(self, lease_token: UUID, *, when: datetime | None = None) -> None:
        self._require_lease(lease_token)
        if self.status is not AgentRunStatus.CLAIMED:
            raise AgentAuthoringConflictError("Only a claimed run can start")
        self.status = AgentRunStatus.RUNNING
        self.updated_at = when or _utc_now()

    def heartbeat(
        self,
        lease_token: UUID,
        *,
        lease_expires_at: datetime,
        when: datetime | None = None,
    ) -> None:
        timestamp = when or _utc_now()
        self._require_lease(lease_token)
        if self.status not in {
            AgentRunStatus.CLAIMED,
            AgentRunStatus.RUNNING,
        }:
            raise AgentAuthoringConflictError(
                f"Agent run {self.id} does not hold a renewable lease"
            )
        _aware(lease_expires_at, "Agent run lease_expires_at")
        if lease_expires_at <= timestamp:
            raise AgentAuthoringError("Agent run lease must expire in the future")
        self.lease_expires_at = lease_expires_at
        self.lease_heartbeat_at = timestamp
        self.updated_at = timestamp

    def request_cancellation(
        self,
        *,
        when: datetime | None = None,
    ) -> RevokedAgentLease | None:
        if self.is_terminal:
            return None
        timestamp = when or _utc_now()
        self.cancellation_requested_at = timestamp
        if self.status in {
            AgentRunStatus.QUEUED,
            AgentRunStatus.AWAITING_APPROVAL,
        }:
            self.status = AgentRunStatus.CANCELLED
            self._clear_lease()
            self.updated_at = timestamp
            return None
        if self.status is AgentRunStatus.CANCELLING:
            return None
        if self.status is AgentRunStatus.INTERRUPTING:
            raise AgentAuthoringConflictError(
                "An interrupting run cannot also begin cancellation"
            )
        revoked = self._revoke_lease()
        self.status = AgentRunStatus.CANCELLING
        self.updated_at = timestamp
        return revoked

    def await_approval(self, lease_token: UUID, *, when: datetime | None = None) -> None:
        self._require_lease(lease_token)
        if self.status is not AgentRunStatus.RUNNING:
            raise AgentAuthoringConflictError(
                "Only a running agent run can await approval"
            )
        self.status = AgentRunStatus.AWAITING_APPROVAL
        self._clear_lease()
        self.updated_at = when or _utc_now()

    def complete(self, *, when: datetime | None = None) -> None:
        if self.status is not AgentRunStatus.AWAITING_APPROVAL:
            raise AgentAuthoringConflictError(
                "Only an approval-waiting run can complete"
            )
        self.status = AgentRunStatus.COMPLETED
        self._clear_lease()
        self.updated_at = when or _utc_now()

    def fail(
        self,
        error: str,
        *,
        lease_token: UUID | None = None,
        when: datetime | None = None,
    ) -> None:
        if lease_token is not None:
            self._require_lease(lease_token)
        if self.is_terminal:
            raise AgentAuthoringConflictError("A terminal run cannot fail again")
        self.status = AgentRunStatus.FAILED
        self.terminal_error = _required_text(error, "Agent run terminal error", 4_000)
        self._clear_lease()
        self.updated_at = when or _utc_now()

    def confirm_cancelled(
        self,
        revocation_fencing_token: int,
        *,
        when: datetime | None = None,
    ) -> None:
        if self.status is not AgentRunStatus.CANCELLING:
            raise AgentAuthoringConflictError("Only a cancelling run can be cancelled")
        if self.fencing_token != revocation_fencing_token:
            raise AgentAuthoringConflictError(
                f"Agent run {self.id} cancellation fence is stale"
            )
        self.status = AgentRunStatus.CANCELLED
        self._clear_lease()
        self.updated_at = when or _utc_now()

    def begin_interruption(
        self,
        *,
        when: datetime | None = None,
    ) -> RevokedAgentLease:
        timestamp = when or _utc_now()
        if self.status is not AgentRunStatus.RUNNING or not self.lease_is_expired(
            timestamp
        ):
            raise AgentAuthoringConflictError(
                "Only a running run with an expired lease can be interrupted"
            )
        revoked = self._revoke_lease()
        self.status = AgentRunStatus.INTERRUPTING
        self.terminal_error = "Worker lease expired while the run was executing"
        self.updated_at = timestamp
        return revoked

    def confirm_interrupted(
        self,
        revocation_fencing_token: int,
        *,
        when: datetime | None = None,
    ) -> None:
        if self.status is not AgentRunStatus.INTERRUPTING:
            raise AgentAuthoringConflictError(
                "Only an interrupting run can be confirmed interrupted"
            )
        if self.fencing_token != revocation_fencing_token:
            raise AgentAuthoringConflictError(
                f"Agent run {self.id} interruption fence is stale"
            )
        self.status = AgentRunStatus.INTERRUPTED
        self._clear_lease()
        self.updated_at = when or _utc_now()

    def _require_lease(self, lease_token: UUID) -> None:
        if self.lease_token != lease_token:
            raise AgentAuthoringConflictError(
                f"Agent run {self.id} lease token is stale"
            )

    def _clear_lease(self) -> None:
        self.lease_owner = None
        self.lease_token = None
        self.lease_expires_at = None
        self.lease_heartbeat_at = None

    def _revoke_lease(self) -> RevokedAgentLease:
        if self.lease_owner is None or self.lease_token is None:
            raise AgentAuthoringConflictError(
                f"Agent run {self.id} has no active lease to revoke"
            )
        revoked = RevokedAgentLease(
            owner=self.lease_owner,
            token=self.lease_token,
            fencing_token=self.fencing_token,
        )
        self.fencing_token += 1
        self._clear_lease()
        return revoked


_BUILD_TRANSITIONS: dict[NodeBuildStatus, frozenset[NodeBuildStatus]] = {
    NodeBuildStatus.QUEUED: frozenset(
        {NodeBuildStatus.PREPARING, NodeBuildStatus.CANCELLED, NodeBuildStatus.FAILED}
    ),
    NodeBuildStatus.PREPARING: frozenset(
        {NodeBuildStatus.CODING, NodeBuildStatus.CANCELLED, NodeBuildStatus.FAILED}
    ),
    NodeBuildStatus.CODING: frozenset(
        {NodeBuildStatus.TESTING, NodeBuildStatus.CANCELLED, NodeBuildStatus.FAILED}
    ),
    NodeBuildStatus.TESTING: frozenset(
        {
            NodeBuildStatus.AWAITING_APPROVAL,
            NodeBuildStatus.CANCELLED,
            NodeBuildStatus.FAILED,
        }
    ),
    NodeBuildStatus.AWAITING_APPROVAL: frozenset(
        {NodeBuildStatus.PUBLISHED, NodeBuildStatus.SUPERSEDED}
    ),
    NodeBuildStatus.FAILED: frozenset(),
    NodeBuildStatus.CANCELLED: frozenset(),
    NodeBuildStatus.SUPERSEDED: frozenset(),
    NodeBuildStatus.PUBLISHED: frozenset(),
}


@dataclass
class NodeBuildAttempt:
    workspace_id: UUID
    thread_id: UUID
    draft_node_id: UUID
    run_id: UUID
    attempt_number: int
    prompt: str
    status: NodeBuildStatus = NodeBuildStatus.QUEUED
    manifest: GeneratedNodeManifest | None = None
    capabilities: CapabilityManifest | None = None
    capability_digest: str | None = None
    artifacts: BuildArtifactSet | None = None
    failure_message: str | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if isinstance(self.attempt_number, bool) or self.attempt_number < 1:
            raise AgentAuthoringError("Build attempt number must be positive")
        self.prompt = _required_text(
            self.prompt, "Build attempt prompt", MAX_AGENT_PROMPT_LENGTH
        )
        self.status = NodeBuildStatus(self.status)
        if self.capability_digest is not None:
            self.capability_digest = _sha256(
                self.capability_digest, "Build capability digest"
            )
        if self.capabilities is not None:
            if self.capability_digest != self.capabilities.digest:
                raise AgentAuthoringError(
                    "Build capability digest does not match its manifest"
                )
        _aware(self.created_at, "Build attempt created_at")
        _aware(self.updated_at, "Build attempt updated_at")

    @property
    def is_active(self) -> bool:
        return self.status in {
            NodeBuildStatus.QUEUED,
            NodeBuildStatus.PREPARING,
            NodeBuildStatus.CODING,
            NodeBuildStatus.TESTING,
            NodeBuildStatus.AWAITING_APPROVAL,
        }

    def advance(
        self,
        status: NodeBuildStatus,
        *,
        when: datetime | None = None,
    ) -> None:
        target = NodeBuildStatus(status)
        if target not in _BUILD_TRANSITIONS[self.status]:
            raise AgentAuthoringConflictError(
                f"Build {self.id} cannot move from {self.status.value} to "
                f"{target.value}"
            )
        self.status = target
        self.updated_at = when or _utc_now()

    def request_approval(
        self,
        *,
        anchor: AnchoredPortContract,
        manifest: GeneratedNodeManifest,
        capabilities: CapabilityManifest,
        artifacts: BuildArtifactSet,
        when: datetime | None = None,
    ) -> None:
        if self.status is not NodeBuildStatus.TESTING:
            raise AgentAuthoringConflictError(
                "Only a testing build can request approval"
            )
        if not artifacts.tests_passed:
            raise AgentAuthoringError("A build with failing tests cannot request approval")
        if not manifest.preserves(anchor):
            raise AgentAuthoringError(
                "Generated node manifest changed or removed the connected port"
            )
        self.manifest = manifest
        self.capabilities = capabilities
        self.capability_digest = capabilities.digest
        self.artifacts = artifacts
        self.status = NodeBuildStatus.AWAITING_APPROVAL
        self.updated_at = when or _utc_now()

    def fail(self, error: str, *, when: datetime | None = None) -> None:
        if NodeBuildStatus.FAILED not in _BUILD_TRANSITIONS[self.status]:
            raise AgentAuthoringConflictError("This build can no longer fail")
        self.failure_message = _required_text(error, "Build failure", 4_000)
        self.status = NodeBuildStatus.FAILED
        self.updated_at = when or _utc_now()

    def cancel(self, *, when: datetime | None = None) -> None:
        if self.status is NodeBuildStatus.AWAITING_APPROVAL:
            self.status = NodeBuildStatus.SUPERSEDED
        elif NodeBuildStatus.CANCELLED in _BUILD_TRANSITIONS[self.status]:
            self.status = NodeBuildStatus.CANCELLED
        elif self.status not in {
            NodeBuildStatus.CANCELLED,
            NodeBuildStatus.SUPERSEDED,
        }:
            raise AgentAuthoringConflictError("This build can no longer be cancelled")
        self.updated_at = when or _utc_now()


@dataclass
class AgentEvent:
    workspace_id: UUID
    thread_id: UUID
    sequence: int
    kind: AgentEventKind
    payload: AgentEventPayload
    run_id: UUID | None = None
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if isinstance(self.sequence, bool) or self.sequence < 1:
            raise AgentAuthoringError("Agent event sequence must be positive")
        self.kind = AgentEventKind(self.kind)
        _aware(self.created_at, "Agent event created_at")

    @property
    def is_terminal(self) -> bool:
        return self.payload.run_status in _RUN_TERMINAL_STATUSES


@dataclass
class CapabilityApproval:
    workspace_id: UUID
    draft_node_id: UUID
    build_attempt_id: UUID
    capability_digest: str
    approved_by_user_id: UUID
    id: UUID = field(default_factory=uuid4)
    approved_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        self.capability_digest = _sha256(
            self.capability_digest, "Approved capability digest"
        )
        _aware(self.approved_at, "Capability approval approved_at")


@dataclass
class NodeRelease:
    """Append-only published implementation of a reserved generated node id."""

    workspace_id: UUID
    node_id: UUID
    revision: int
    draft_node_id: UUID
    build_attempt_id: UUID
    thread_id: UUID
    environment_id: UUID
    manifest: GeneratedNodeManifest
    capabilities: CapabilityManifest
    capability_digest: str
    artifacts: BuildArtifactSet
    capability_approval_id: UUID
    approved_by_user_id: UUID
    created_by_user_id: UUID | None = None
    created_at: datetime = field(default_factory=_utc_now)

    def __post_init__(self) -> None:
        if isinstance(self.revision, bool) or self.revision < 1:
            raise AgentAuthoringError("Node release revision must be positive")
        self.capability_digest = _sha256(
            self.capability_digest, "Node release capability digest"
        )
        if self.capability_digest != self.capabilities.digest:
            raise AgentAuthoringError(
                "Node release capability digest does not match its manifest"
            )
        if not self.artifacts.tests_passed:
            raise AgentAuthoringError("Node releases require passing build tests")
        _aware(self.created_at, "Node release created_at")

    @property
    def operator_id(self) -> str:
        return f"{GENERATED_NODE_OPERATOR_PREFIX}{self.node_id}"

    @property
    def operator_version(self) -> int:
        return self.revision


__all__ = [
    "GENERATED_NODE_OPERATOR_PREFIX",
    "GENERATED_NODE_OPERATOR_VERSION",
    "AgentArtifactType",
    "AgentAuthoringConflictError",
    "AgentAuthoringError",
    "AgentAuthoringIdempotencyError",
    "AgentEnvironment",
    "AgentEnvironmentStatus",
    "AgentEvent",
    "AgentEventKind",
    "AgentEventPayload",
    "AgentPortDirection",
    "AgentRun",
    "AgentRunStatus",
    "AgentThread",
    "AnchoredPortContract",
    "BuildArtifactSet",
    "CapabilityApproval",
    "CapabilityManifest",
    "DraftNode",
    "DraftNodeStatus",
    "GeneratedNodeManifest",
    "GeneratedNodePort",
    "GeneratedNodeReference",
    "GeneratedNodeReferenceError",
    "NodeBuildAttempt",
    "NodeBuildStatus",
    "NodeRelease",
    "ObjectStoreAccess",
    "ObjectStoreCapability",
    "PortConversion",
    "PortFeed",
    "RuntimeLimits",
    "RuntimeArtifactReference",
    "RevokedAgentLease",
]
