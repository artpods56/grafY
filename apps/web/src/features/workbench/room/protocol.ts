import { collaborativeHeadFromLegacy } from "@/lib/api/graph-head";
import type {
  CollaborativeHead,
  LegacyCollaborativeHead,
  SubmitGraphCommandRequest,
  WorkspaceCapability,
} from "@/lib/api";

export const ROOM_PROTOCOL_VERSION = 1;
export const ROOM_COMMAND_QUEUE_CAP = 32;

export const CLOSE_PERMISSIONS_CHANGED = 4003;
export const CLOSE_ACCESS_REVOKED = 4004;
export const CLOSE_PROTOCOL_ERROR = 4008;
export const CLOSE_SLOW_CONSUMER = 4009;
export const CLOSE_GRAPH_DELETED = 4010;

export type RoomGraphCommand = SubmitGraphCommandRequest["command"];

export type GraphRoomTerminalReason =
  | "access_revoked"
  | "graph_deleted"
  | "protocol_incompatible"
  | "reconnect_exhausted";

export type GraphRoomRecoveryReason =
  | "connection_lost"
  | "permissions_changed"
  | "protocol_error"
  | "slow_consumer";

export interface GraphRoomFailure {
  readonly workspaceId: string;
  readonly graphId: string;
  readonly graphRoomSessionId: string | null;
  readonly reason: GraphRoomRecoveryReason | GraphRoomTerminalReason;
  readonly retryable: boolean;
  readonly side: "client" | "server" | "network";
  readonly phase: "connect" | "receive" | "close";
  readonly messageType: string | null;
  readonly protocolVersion: number | null;
  readonly closeCode: number | null;
  readonly detail: string;
}

export type GraphRoomStatus =
  | "idle"
  | "connecting"
  | "ready"
  | "reconnecting"
  | "unsynchronized"
  | "stopped";

export interface ActorPresentation {
  readonly actor_id: string;
  readonly display_name: string;
  readonly color: string;
}

export interface CapabilitySnapshot {
  readonly capabilities: readonly WorkspaceCapability[];
  readonly authorization_version: number;
}

export type PresenceActivityKind =
  | "moving_nodes"
  | "editing_node"
  | "connecting";

export interface PresencePoint {
  readonly x: number;
  readonly y: number;
}

export interface TransientNodePosition {
  readonly node_id: string;
  readonly x: number;
  readonly y: number;
}

export interface PresenceParticipant {
  readonly graph_room_session_id: string;
  readonly actor: ActorPresentation;
  readonly presence_sequence: number;
  readonly cursor: PresencePoint | null;
  readonly selected_node_ids: readonly string[];
  readonly selected_edge_ids: readonly string[];
  readonly activity: PresenceActivityKind | null;
  readonly activity_target_ids: readonly string[];
  readonly transient_node_positions: readonly TransientNodePosition[];
}

export interface PresenceJoinMessage {
  readonly protocol_version: 1;
  readonly type: "presence.join";
  readonly participant: PresenceParticipant;
}

export interface PresenceLeaveMessage {
  readonly protocol_version: 1;
  readonly type: "presence.leave";
  readonly graph_room_session_id: string;
}

export interface PresenceUpdateMessage {
  readonly protocol_version: 1;
  readonly type: "presence.update";
  readonly participant: PresenceParticipant;
}

export interface PresenceUpdateSubmit {
  readonly presence_sequence: number;
  readonly cursor?: PresencePoint | null;
  readonly selected_node_ids?: readonly string[];
  readonly selected_edge_ids?: readonly string[];
  readonly activity?: PresenceActivityKind | null;
  readonly activity_target_ids?: readonly string[];
  readonly transient_node_positions?: readonly TransientNodePosition[];
}

export type ActiveExecutionLifecycleStatus = "queued" | "running" | "cancelling";
export type TerminalExecutionStatus = "cancelled" | "succeeded" | "failed";

export interface ActiveExecutionSummary {
  readonly execution_id: string;
  readonly graph_revision: number;
  readonly status: ActiveExecutionLifecycleStatus;
  readonly scope: "all" | "selected" | "selected-with-dependencies";
  readonly requested_node_ids: readonly string[];
  readonly starter: ActorPresentation;
  readonly active_node_id: string | null;
  readonly overlays_compatible: boolean;
  readonly cancellable: boolean;
}

/** Parsed client event: the v1 wire head is normalized to a canonical document. */
export interface RoomReadyMessage {
  readonly protocol_version: 1;
  readonly type: "room.ready";
  readonly workspace_id: string;
  readonly graph_id: string;
  readonly graph_room_session_id: string;
  readonly actor: ActorPresentation;
  readonly capabilities: CapabilitySnapshot;
  readonly head: CollaborativeHead;
  readonly participants: readonly PresenceParticipant[];
  readonly active_execution: ActiveExecutionSummary | null;
  readonly registry_marker: string;
}

export interface ExecutionActiveMessage {
  readonly protocol_version: 1;
  readonly type: "execution.active";
  readonly execution: ActiveExecutionSummary;
}

export interface ExecutionClearedMessage {
  readonly protocol_version: 1;
  readonly type: "execution.cleared";
  readonly execution_id: string;
  readonly status: TerminalExecutionStatus;
  readonly graph_revision: number;
  readonly error: string | null;
}

export interface GraphCommandSubmitMessage {
  readonly protocol_version: 1;
  readonly type: "graph.command.submit";
  readonly command_id: string;
  readonly room_epoch: string;
  readonly observed_sequence: number;
  readonly command: RoomGraphCommand;
}

export interface GraphCommandAcceptedMessage {
  readonly protocol_version: 1;
  readonly type: "graph.command.accepted";
  readonly command_id: string;
  readonly room_epoch: string;
  readonly sequence: number;
  readonly actor: ActorPresentation;
  readonly graph_room_session_id: string | null;
  readonly command: RoomGraphCommand;
}

export interface GraphCommandReceiptMessage {
  readonly protocol_version: 1;
  readonly type: "graph.command.receipt";
  readonly command_id: string;
  readonly outcome: "accepted" | "idempotent_replay";
  readonly accepted_room_epoch: string;
  readonly accepted_sequence: number;
  readonly current_room_epoch: string;
  readonly current_sequence: number;
  readonly deduplicated: boolean;
  readonly requires_head_rehydration: boolean;
}

export interface GraphCommandRejectedMessage {
  readonly protocol_version: 1;
  readonly type: "graph.command.rejected";
  readonly command_id: string;
  readonly error_code: string;
  readonly detail: string;
  readonly current_room_epoch: string | null;
  readonly current_sequence: number | null;
}

export interface RoomRehydrateMessage {
  readonly protocol_version: 1;
  readonly type: "room.rehydrate";
  readonly reason: "epoch_reset";
  readonly head: CollaborativeHead;
}

export type ServerRoomMessage =
  | RoomReadyMessage
  | GraphCommandAcceptedMessage
  | GraphCommandReceiptMessage
  | GraphCommandRejectedMessage
  | RoomRehydrateMessage
  | PresenceJoinMessage
  | PresenceLeaveMessage
  | PresenceUpdateMessage
  | ExecutionActiveMessage
  | ExecutionClearedMessage;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isString(value: unknown): value is string {
  return typeof value === "string";
}

function isNonNegativeInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 0;
}

function isPositiveInt(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1;
}

function parseActor(value: unknown): ActorPresentation | null {
  if (!isRecord(value)) return null;
  if (!isString(value.actor_id) || !isString(value.display_name) || !isString(value.color)) {
    return null;
  }
  return {
    actor_id: value.actor_id,
    display_name: value.display_name,
    color: value.color,
  };
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function parsePresencePoint(value: unknown): PresencePoint | null {
  if (value === null) return null;
  if (!isRecord(value) || !isFiniteNumber(value.x) || !isFiniteNumber(value.y)) {
    return null;
  }
  return { x: value.x, y: value.y };
}

function parseStringIdList(value: unknown): readonly string[] | null {
  if (!Array.isArray(value)) return null;
  if (!value.every((item) => isString(item))) return null;
  return value;
}

function parseTransientPositions(
  value: unknown,
): readonly TransientNodePosition[] | null {
  if (!Array.isArray(value)) return null;
  const positions: TransientNodePosition[] = [];
  for (const item of value) {
    if (!isRecord(item) || !isString(item.node_id)) return null;
    if (!isFiniteNumber(item.x) || !isFiniteNumber(item.y)) return null;
    positions.push({ node_id: item.node_id, x: item.x, y: item.y });
  }
  return positions;
}

function parsePresenceActivity(value: unknown): PresenceActivityKind | null {
  if (value === null || value === undefined) return null;
  if (
    value === "moving_nodes" ||
    value === "editing_node" ||
    value === "connecting"
  ) {
    return value;
  }
  return null;
}

function parseParticipant(value: unknown): PresenceParticipant | null {
  if (!isRecord(value)) return null;
  const actor = parseActor(value.actor);
  if (!actor || !isString(value.graph_room_session_id)) return null;
  if (!isNonNegativeInt(value.presence_sequence)) return null;
  const cursor =
    value.cursor === null || value.cursor === undefined
      ? null
      : parsePresencePoint(value.cursor);
  if (value.cursor !== null && value.cursor !== undefined && cursor === null) {
    return null;
  }
  const selectedNodeIds = parseStringIdList(value.selected_node_ids ?? []);
  const selectedEdgeIds = parseStringIdList(value.selected_edge_ids ?? []);
  const activityTargets = parseStringIdList(value.activity_target_ids ?? []);
  const transient = parseTransientPositions(
    value.transient_node_positions ?? [],
  );
  if (
    selectedNodeIds === null ||
    selectedEdgeIds === null ||
    activityTargets === null ||
    transient === null
  ) {
    return null;
  }
  const activity =
    value.activity === null || value.activity === undefined
      ? null
      : parsePresenceActivity(value.activity);
  if (value.activity !== null && value.activity !== undefined && activity === null) {
    return null;
  }
  return {
    graph_room_session_id: value.graph_room_session_id,
    actor,
    presence_sequence: value.presence_sequence,
    cursor,
    selected_node_ids: selectedNodeIds,
    selected_edge_ids: selectedEdgeIds,
    activity,
    activity_target_ids: activityTargets,
    transient_node_positions: transient,
  };
}

function parseCapabilities(value: unknown): CapabilitySnapshot | null {
  if (!isRecord(value)) return null;
  if (!Array.isArray(value.capabilities) || !isPositiveInt(value.authorization_version)) {
    return null;
  }
  if (!value.capabilities.every((item) => isString(item))) return null;
  return {
    capabilities: value.capabilities as WorkspaceCapability[],
    authorization_version: value.authorization_version,
  };
}

function parseHead(value: unknown): LegacyCollaborativeHead | null {
  if (!isRecord(value)) return null;
  if (
    !isString(value.graph_id) ||
    !isString(value.room_epoch) ||
    !isNonNegativeInt(value.collaboration_sequence) ||
    !isNonNegativeInt(value.checkpoint_sequence) ||
    !isPositiveInt(value.checkpoint_revision) ||
    !isString(value.name) ||
    !isString(value.updated_at) ||
    !Array.isArray(value.nodes) ||
    !Array.isArray(value.edges) ||
    !value.nodes.every((node) => isRecord(node) && !Array.isArray(node)) ||
    !value.edges.every((edge) => isRecord(edge) && !Array.isArray(edge))
  ) {
    return null;
  }
  return value as LegacyCollaborativeHead;
}

function parseActiveExecution(value: unknown): ActiveExecutionSummary | null {
  if (value === null) return null;
  if (!isRecord(value)) return null;
  const starter = parseActor(value.starter);
  if (
    !starter ||
    !isString(value.execution_id) ||
    !isPositiveInt(value.graph_revision) ||
    (value.status !== "queued" &&
      value.status !== "running" &&
      value.status !== "cancelling") ||
    (value.scope !== "all" &&
      value.scope !== "selected" &&
      value.scope !== "selected-with-dependencies") ||
    !Array.isArray(value.requested_node_ids) ||
    !value.requested_node_ids.every((item) => isString(item)) ||
    typeof value.overlays_compatible !== "boolean" ||
    typeof value.cancellable !== "boolean"
  ) {
    return null;
  }
  if (
    value.active_node_id !== null &&
    value.active_node_id !== undefined &&
    !isString(value.active_node_id)
  ) {
    return null;
  }
  return {
    execution_id: value.execution_id,
    graph_revision: value.graph_revision,
    status: value.status,
    scope: value.scope,
    requested_node_ids: value.requested_node_ids,
    starter,
    active_node_id: isString(value.active_node_id) ? value.active_node_id : null,
    overlays_compatible: value.overlays_compatible,
    cancellable: value.cancellable,
  };
}

export function parseServerRoomMessage(raw: unknown): ServerRoomMessage | null {
  if (!isRecord(raw) || raw.protocol_version !== ROOM_PROTOCOL_VERSION) {
    return null;
  }
  const type = raw.type;
  if (type === "room.ready") {
    const actor = parseActor(raw.actor);
    const capabilities = parseCapabilities(raw.capabilities);
    const head = parseHead(raw.head);
    if (
      !actor ||
      !capabilities ||
      !head ||
      !isString(raw.workspace_id) ||
      !isString(raw.graph_id) ||
      !isString(raw.graph_room_session_id) ||
      !isString(raw.registry_marker)
    ) {
      return null;
    }
    const participants = Array.isArray(raw.participants)
      ? raw.participants.map(parseParticipant)
      : [];
    if (participants.some((item) => item === null)) return null;
    const activeExecution =
      raw.active_execution === null || raw.active_execution === undefined
        ? null
        : parseActiveExecution(raw.active_execution);
    if (raw.active_execution != null && activeExecution === null) return null;
    return {
      protocol_version: 1,
      type: "room.ready",
      workspace_id: raw.workspace_id,
      graph_id: raw.graph_id,
      graph_room_session_id: raw.graph_room_session_id,
      actor,
      capabilities,
      head: collaborativeHeadFromLegacy(head),
      participants: participants as PresenceParticipant[],
      active_execution: activeExecution,
      registry_marker: raw.registry_marker,
    };
  }
  if (type === "presence.join" || type === "presence.update") {
    const participant = parseParticipant(raw.participant);
    if (!participant) return null;
    return {
      protocol_version: 1,
      type,
      participant,
    };
  }
  if (type === "presence.leave") {
    if (!isString(raw.graph_room_session_id)) return null;
    return {
      protocol_version: 1,
      type: "presence.leave",
      graph_room_session_id: raw.graph_room_session_id,
    };
  }
  if (type === "graph.command.accepted") {
    const actor = parseActor(raw.actor);
    if (
      !actor ||
      !isString(raw.command_id) ||
      !isString(raw.room_epoch) ||
      !isNonNegativeInt(raw.sequence) ||
      !isRecord(raw.command)
    ) {
      return null;
    }
    const sessionId = raw.graph_room_session_id;
    if (sessionId !== null && sessionId !== undefined && !isString(sessionId)) {
      return null;
    }
    return {
      protocol_version: 1,
      type: "graph.command.accepted",
      command_id: raw.command_id,
      room_epoch: raw.room_epoch,
      sequence: raw.sequence,
      actor,
      graph_room_session_id: isString(sessionId) ? sessionId : null,
      command: raw.command as RoomGraphCommand,
    };
  }
  if (type === "graph.command.receipt") {
    if (
      !isString(raw.command_id) ||
      (raw.outcome !== "accepted" && raw.outcome !== "idempotent_replay") ||
      !isString(raw.accepted_room_epoch) ||
      !isNonNegativeInt(raw.accepted_sequence) ||
      !isString(raw.current_room_epoch) ||
      !isNonNegativeInt(raw.current_sequence) ||
      typeof raw.deduplicated !== "boolean"
    ) {
      return null;
    }
    return {
      protocol_version: 1,
      type: "graph.command.receipt",
      command_id: raw.command_id,
      outcome: raw.outcome,
      accepted_room_epoch: raw.accepted_room_epoch,
      accepted_sequence: raw.accepted_sequence,
      current_room_epoch: raw.current_room_epoch,
      current_sequence: raw.current_sequence,
      deduplicated: raw.deduplicated,
      requires_head_rehydration: raw.requires_head_rehydration === true,
    };
  }
  if (type === "graph.command.rejected") {
    if (
      !isString(raw.command_id) ||
      !isString(raw.error_code) ||
      !isString(raw.detail)
    ) {
      return null;
    }
    const epoch = raw.current_room_epoch;
    const sequence = raw.current_sequence;
    if (epoch !== null && epoch !== undefined && !isString(epoch)) return null;
    if (sequence !== null && sequence !== undefined && !isNonNegativeInt(sequence)) {
      return null;
    }
    return {
      protocol_version: 1,
      type: "graph.command.rejected",
      command_id: raw.command_id,
      error_code: raw.error_code,
      detail: raw.detail,
      current_room_epoch: isString(epoch) ? epoch : null,
      current_sequence: isNonNegativeInt(sequence) ? sequence : null,
    };
  }
  if (type === "room.rehydrate") {
    const head = parseHead(raw.head);
    if (!head || raw.reason !== "epoch_reset") return null;
    return {
      protocol_version: 1,
      type: "room.rehydrate",
      reason: "epoch_reset",
      head: collaborativeHeadFromLegacy(head),
    };
  }
  if (type === "execution.active") {
    const execution = parseActiveExecution(raw.execution);
    if (!execution) return null;
    return {
      protocol_version: 1,
      type: "execution.active",
      execution,
    };
  }
  if (type === "execution.cleared") {
    if (
      !isString(raw.execution_id) ||
      (raw.status !== "cancelled" &&
        raw.status !== "succeeded" &&
        raw.status !== "failed") ||
      !isPositiveInt(raw.graph_revision)
    ) {
      return null;
    }
    if (raw.error !== null && raw.error !== undefined && !isString(raw.error)) {
      return null;
    }
    return {
      protocol_version: 1,
      type: "execution.cleared",
      execution_id: raw.execution_id,
      status: raw.status,
      graph_revision: raw.graph_revision,
      error: isString(raw.error) ? raw.error : null,
    };
  }
  return null;
}

export function terminalReasonFromClose(
  code: number,
  reason: string,
): GraphRoomRecoveryReason | GraphRoomTerminalReason | null {
  const normalized = reason.trim();
  if (
    code === CLOSE_PERMISSIONS_CHANGED ||
    normalized === "permissions_changed"
  ) {
    return "permissions_changed";
  }
  if (code === CLOSE_ACCESS_REVOKED || normalized === "access_revoked") {
    return "access_revoked";
  }
  if (code === CLOSE_GRAPH_DELETED || normalized === "graph_deleted") {
    return "graph_deleted";
  }
  if (code === CLOSE_PROTOCOL_ERROR || normalized === "protocol_error") {
    return "protocol_error";
  }
  if (code === CLOSE_SLOW_CONSUMER || normalized === "slow_consumer") {
    return "slow_consumer";
  }
  return null;
}
