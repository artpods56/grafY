from datetime import datetime
from enum import StrEnum
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from grafy_core.domain.collaboration import ProjectCommand
from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.project_contracts import ProjectHeadResponse


PROTOCOL_VERSION = 1

PRESENCE_MAX_SELECTED_IDS = 64
PRESENCE_MAX_ACTIVITY_TARGET_IDS = 64
PRESENCE_MAX_TRANSIENT_POSITIONS = 64
PRESENCE_ID_MAX_LENGTH = 255

ACTOR_DISPLAY_COLORS = (
    "indigo",
    "emerald",
    "amber",
    "rose",
    "sky",
    "violet",
    "teal",
    "orange",
)


class PresenceActivityKind(StrEnum):
    MOVING_NODES = "moving_nodes"
    EDITING_NODE = "editing_node"
    CONNECTING = "connecting"


class RoomProtocolModel(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(
        extra="forbid",
        allow_inf_nan=False,
    )


class ActorPresentation(RoomProtocolModel):
    actor_id: UUID
    display_name: str = Field(min_length=1, max_length=160)
    color: str = Field(min_length=1, max_length=32)


class CapabilitySnapshot(RoomProtocolModel):
    capabilities: tuple[WorkspaceCapability, ...]
    authorization_version: int = Field(ge=1)


class PresencePoint(RoomProtocolModel):
    x: float
    y: float


class TransientNodePosition(RoomProtocolModel):
    node_id: str = Field(min_length=1, max_length=PRESENCE_ID_MAX_LENGTH)
    x: float
    y: float


def _normalize_presence_ids(value: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in value:
        item_id = raw.strip()
        if item_id == "" or item_id in seen:
            continue
        if len(item_id) > PRESENCE_ID_MAX_LENGTH:
            raise ValueError(
                f"presence id must be at most {PRESENCE_ID_MAX_LENGTH} characters"
            )
        seen.add(item_id)
        normalized.append(item_id)
    return tuple(normalized)


class PresenceParticipant(RoomProtocolModel):
    """Ephemeral collaborator state keyed by graph-room session id."""

    project_room_session_id: UUID
    actor: ActorPresentation
    graph_id: str | None = Field(default=None, min_length=1, max_length=255)
    presence_sequence: int = Field(ge=0)
    cursor: PresencePoint | None = None
    selected_node_ids: tuple[str, ...] = ()
    selected_edge_ids: tuple[str, ...] = ()
    activity: PresenceActivityKind | None = None
    activity_target_ids: tuple[str, ...] = ()
    transient_node_positions: tuple[TransientNodePosition, ...] = ()

    @field_validator("selected_node_ids", "selected_edge_ids", "activity_target_ids")
    @classmethod
    def _normalize_id_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_presence_ids(value)


class PresenceJoinMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["presence.join"] = "presence.join"
    participant: PresenceParticipant


class PresenceLeaveMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["presence.leave"] = "presence.leave"
    project_room_session_id: UUID


class PresenceUpdateMessage(RoomProtocolModel):
    """Server fanout of accepted presence state."""

    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["presence.update"] = "presence.update"
    participant: PresenceParticipant


class PresenceUpdateSubmitMessage(RoomProtocolModel):
    """Client-authored presence update; identity comes from the room session."""

    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["presence.update"] = "presence.update"
    graph_id: str | None = Field(default=None, min_length=1, max_length=255)
    presence_sequence: int = Field(ge=1)
    cursor: PresencePoint | None = None
    selected_node_ids: tuple[str, ...] = Field(
        default=(), max_length=PRESENCE_MAX_SELECTED_IDS
    )
    selected_edge_ids: tuple[str, ...] = Field(
        default=(), max_length=PRESENCE_MAX_SELECTED_IDS
    )
    activity: PresenceActivityKind | None = None
    activity_target_ids: tuple[str, ...] = Field(
        default=(),
        max_length=PRESENCE_MAX_ACTIVITY_TARGET_IDS,
    )
    transient_node_positions: tuple[TransientNodePosition, ...] = Field(
        default=(),
        max_length=PRESENCE_MAX_TRANSIENT_POSITIONS,
    )

    @field_validator("selected_node_ids", "selected_edge_ids", "activity_target_ids")
    @classmethod
    def _normalize_id_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _normalize_presence_ids(value)


InstanceStateName = Literal["fresh", "stale", "queued", "running", "failed"]
RunLifecycleStatus = Literal[
    "running", "succeeded", "failed", "cancelled", "interrupted"
]


class RunTargetSummary(RoomProtocolModel):
    node_id: str = Field(min_length=1, max_length=PRESENCE_ID_MAX_LENGTH)
    call_path: tuple[str, ...] = ()


class ActiveRunSummary(RoomProtocolModel):
    """One active Run of the Project, with who started it (ADR 0020)."""

    run_id: UUID
    graph_id: str = Field(min_length=1, max_length=255)
    targets: tuple[RunTargetSummary, ...] = ()
    starter: ActorPresentation | None = None
    started_at: datetime
    cancellable: bool = True


class InstanceKeyEntry(RoomProtocolModel):
    project_id: UUID
    graph_id: str = Field(min_length=1, max_length=255)
    call_path: tuple[str, ...] = ()
    node_id: str = Field(min_length=1, max_length=PRESENCE_ID_MAX_LENGTH)
    map_index: int | None = Field(default=None, ge=0)


class InstanceStateEntry(InstanceKeyEntry):
    """Derived state addressed by the complete node instance key."""

    state: InstanceStateName
    fingerprint: str
    last_result_fingerprint: str | None = None
    error: str | None = Field(default=None, max_length=2000)


class RunStartedMessage(RoomProtocolModel):
    """A Run became active, or its target set was accepted."""

    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["run.started"] = "run.started"
    run: ActiveRunSummary


class RunFinishedMessage(RoomProtocolModel):
    """A Run left the active list. Its results live on the instances."""

    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["run.finished"] = "run.finished"
    run_id: UUID
    status: RunLifecycleStatus
    error: str | None = Field(default=None, max_length=2000)


class InstancesChangedMessage(RoomProtocolModel):
    """Instance-state deltas. ``removed`` lists instance keys that no longer exist."""

    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["instances.changed"] = "instances.changed"
    changed: tuple[InstanceStateEntry, ...] = ()
    removed: tuple[InstanceKeyEntry, ...] = ()
    head_sequence: int = Field(ge=0)


class RoomReadyMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["room.ready"] = "room.ready"
    workspace_id: UUID
    project_id: UUID
    project_room_session_id: UUID
    actor: ActorPresentation
    capabilities: CapabilitySnapshot
    head: ProjectHeadResponse
    participants: list[PresenceParticipant] = Field(default_factory=list)
    active_runs: tuple[ActiveRunSummary, ...] = ()
    instances: tuple[InstanceStateEntry, ...] = ()
    registry_marker: str = "builtin"


class ProjectCommandSubmitMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["project.command.submit"] = "project.command.submit"
    command_id: UUID
    room_epoch: UUID
    observed_sequence: int = Field(ge=0)
    commands: tuple[ProjectCommand, ...] = Field(min_length=1)


class ProjectCommandAcceptedMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["project.command.accepted"] = "project.command.accepted"
    command_id: UUID
    room_epoch: UUID
    sequence: int = Field(ge=0)
    actor: ActorPresentation
    project_room_session_id: UUID | None = None
    commands: tuple[ProjectCommand, ...] = Field(min_length=1)


class ProjectCommandReceiptMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["project.command.receipt"] = "project.command.receipt"
    command_id: UUID
    outcome: Literal["accepted", "idempotent_replay"]
    accepted_room_epoch: UUID
    accepted_sequence: int = Field(ge=0)
    current_room_epoch: UUID
    current_sequence: int = Field(ge=0)
    deduplicated: bool
    requires_head_rehydration: bool = False


class ProjectCommandRejectedMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["project.command.rejected"] = "project.command.rejected"
    command_id: UUID
    error_code: str = Field(min_length=1, max_length=64)
    detail: str = Field(min_length=1, max_length=500)
    current_room_epoch: UUID | None = None
    current_sequence: int | None = Field(default=None, ge=0)


class RoomRehydrateMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["room.rehydrate"] = "room.rehydrate"
    reason: Literal["epoch_reset"] = "epoch_reset"
    head: ProjectHeadResponse


class RoomHeartbeatMessage(RoomProtocolModel):
    """Server-owned keepalive; also triggers membership revalidation."""

    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["room.heartbeat"] = "room.heartbeat"
    authorization_version: int = Field(ge=1)


ClientRoomMessage = Annotated[
    ProjectCommandSubmitMessage | PresenceUpdateSubmitMessage,
    Field(discriminator="type"),
]

CLIENT_ROOM_MESSAGE_ADAPTER: TypeAdapter[
    ProjectCommandSubmitMessage | PresenceUpdateSubmitMessage
] = TypeAdapter(ClientRoomMessage)


def actor_display_color(user_id: UUID) -> str:
    return ACTOR_DISPLAY_COLORS[user_id.int % len(ACTOR_DISPLAY_COLORS)]


def bounded_display_name(display_name: str | None, email: str) -> str:
    candidate = (display_name or "").strip()
    if candidate == "":
        local, separator, _domain = email.partition("@")
        candidate = local if separator else email
    candidate = candidate.strip() or "collaborator"
    return candidate[:160]


def command_receipt_outcome(
    *,
    deduplicated: bool,
) -> Literal["accepted", "idempotent_replay"]:
    if deduplicated:
        return "idempotent_replay"
    return "accepted"
