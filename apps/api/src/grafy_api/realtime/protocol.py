from enum import StrEnum
from typing import Annotated, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from grafy_core.domain.collaboration import GraphCommand
from grafy_core.domain.execution_history import GraphExecutionScope
from grafy_core.domain.identity import WorkspaceCapability

from grafy_api.graph_contracts import CollaborativeHeadResponse


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


ActiveExecutionLifecycleStatus = Literal["queued", "running", "cancelling"]
TerminalExecutionStatus = Literal["cancelled", "succeeded", "failed"]


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

    graph_room_session_id: UUID
    actor: ActorPresentation
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
    graph_room_session_id: UUID


class PresenceUpdateMessage(RoomProtocolModel):
    """Server fanout of accepted presence state."""

    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["presence.update"] = "presence.update"
    participant: PresenceParticipant


class PresenceUpdateSubmitMessage(RoomProtocolModel):
    """Client-authored presence update; identity comes from the room session."""

    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["presence.update"] = "presence.update"
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


class ActiveExecutionSummary(RoomProtocolModel):
    """Shared discovery facts for the one active graph execution."""

    execution_id: UUID
    graph_revision: int = Field(ge=1)
    status: ActiveExecutionLifecycleStatus
    scope: GraphExecutionScope = "all"
    requested_node_ids: list[str] = Field(default_factory=list)
    starter: ActorPresentation
    active_node_id: str | None = None
    overlays_compatible: bool = True
    cancellable: bool = True

    @field_validator("requested_node_ids")
    @classmethod
    def _normalize_requested_node_ids(cls, value: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in value:
            node_id = raw.strip()
            if node_id == "" or node_id in seen:
                continue
            if len(node_id) > 255:
                raise ValueError("requested node id must be at most 255 characters")
            seen.add(node_id)
            normalized.append(node_id)
        return normalized


class RoomReadyMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["room.ready"] = "room.ready"
    workspace_id: UUID
    graph_id: UUID
    graph_room_session_id: UUID
    actor: ActorPresentation
    capabilities: CapabilitySnapshot
    head: CollaborativeHeadResponse
    participants: list[PresenceParticipant] = Field(default_factory=list)
    active_execution: ActiveExecutionSummary | None = None
    registry_marker: str = "builtin"


class ExecutionActiveMessage(RoomProtocolModel):
    """Room announcement when an active execution is accepted or changes lifecycle."""

    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["execution.active"] = "execution.active"
    execution: ActiveExecutionSummary


class ExecutionClearedMessage(RoomProtocolModel):
    """Room announcement after durable terminal state and active-slot release."""

    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["execution.cleared"] = "execution.cleared"
    execution_id: UUID
    status: TerminalExecutionStatus
    graph_revision: int = Field(ge=1)
    error: str | None = Field(default=None, max_length=2000)


class GraphCommandSubmitMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["graph.command.submit"] = "graph.command.submit"
    command_id: UUID
    room_epoch: UUID
    observed_sequence: int = Field(ge=0)
    command: GraphCommand


class GraphCommandAcceptedMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["graph.command.accepted"] = "graph.command.accepted"
    command_id: UUID
    room_epoch: UUID
    sequence: int = Field(ge=0)
    actor: ActorPresentation
    graph_room_session_id: UUID | None = None
    command: GraphCommand


class GraphCommandReceiptMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["graph.command.receipt"] = "graph.command.receipt"
    command_id: UUID
    outcome: Literal["accepted", "idempotent_replay"]
    accepted_room_epoch: UUID
    accepted_sequence: int = Field(ge=0)
    current_room_epoch: UUID
    current_sequence: int = Field(ge=0)
    deduplicated: bool
    requires_head_rehydration: bool = False


class GraphCommandRejectedMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["graph.command.rejected"] = "graph.command.rejected"
    command_id: UUID
    error_code: str = Field(min_length=1, max_length=64)
    detail: str = Field(min_length=1, max_length=500)
    current_room_epoch: UUID | None = None
    current_sequence: int | None = Field(default=None, ge=0)


class RoomRehydrateMessage(RoomProtocolModel):
    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["room.rehydrate"] = "room.rehydrate"
    reason: Literal["epoch_reset"] = "epoch_reset"
    head: CollaborativeHeadResponse


class RoomHeartbeatMessage(RoomProtocolModel):
    """Server-owned keepalive; also triggers membership revalidation."""

    protocol_version: Literal[1] = PROTOCOL_VERSION
    type: Literal["room.heartbeat"] = "room.heartbeat"
    authorization_version: int = Field(ge=1)


ClientRoomMessage = Annotated[
    GraphCommandSubmitMessage | PresenceUpdateSubmitMessage,
    Field(discriminator="type"),
]

CLIENT_ROOM_MESSAGE_ADAPTER: TypeAdapter[
    GraphCommandSubmitMessage | PresenceUpdateSubmitMessage
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
