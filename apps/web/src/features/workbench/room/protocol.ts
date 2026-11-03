import type {
  ActiveRunSummary,
  CollaborativeHead,
  InstanceStateName,
  ProjectCommand,
  RunStatus,
  WorkspaceCapability,
} from "@/lib/api";

export const ROOM_PROTOCOL_VERSION = 1;
export const ROOM_COMMAND_QUEUE_CAP = 32;

export const CLOSE_PERMISSIONS_CHANGED = 4003;
export const CLOSE_ACCESS_REVOKED = 4004;
export const CLOSE_PROTOCOL_ERROR = 4008;
export const CLOSE_SLOW_CONSUMER = 4009;
export const CLOSE_PROJECT_DELETED = 4010;

/** One entry of a Project command batch. */
export type RoomProjectCommand = ProjectCommand;

export type ProjectRoomTerminalReason =
  | "access_revoked"
  | "project_deleted"
  | "protocol_incompatible"
  | "reconnect_exhausted";

export type ProjectRoomRecoveryReason =
  | "connection_lost"
  | "permissions_changed"
  | "protocol_error"
  | "slow_consumer";

export interface ProjectRoomFailure {
  readonly workspaceId: string;
  readonly projectId: string;
  readonly projectRoomSessionId: string | null;
  readonly reason: ProjectRoomRecoveryReason | ProjectRoomTerminalReason;
  readonly retryable: boolean;
  readonly side: "client" | "server" | "network";
  readonly phase: "connect" | "receive" | "close";
  readonly messageType: string | null;
  readonly protocolVersion: number | null;
  readonly closeCode: number | null;
  readonly detail: string;
}

export type ProjectRoomStatus =
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
  "moving_nodes" | "editing_node" | "connecting";

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
  readonly project_room_session_id: string;
  readonly actor: ActorPresentation;
  /** Which Graph of the Project this participant is looking at, if any. */
  readonly graph_id: string | null;
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
  readonly project_room_session_id: string;
}

export interface PresenceUpdateMessage {
  readonly protocol_version: 1;
  readonly type: "presence.update";
  readonly participant: PresenceParticipant;
}

export interface PresenceUpdateSubmit {
  readonly graph_id?: string | null;
  readonly presence_sequence: number;
  readonly cursor?: PresencePoint | null;
  readonly selected_node_ids?: readonly string[];
  readonly selected_edge_ids?: readonly string[];
  readonly activity?: PresenceActivityKind | null;
  readonly activity_target_ids?: readonly string[];
  readonly transient_node_positions?: readonly TransientNodePosition[];
}

// --- Runs and instances on the wire ----------------------------------------
// A Run is a demand for freshness, so the room carries the list of active Runs
// and the derived state of node instances. There is no active execution and no
// active node: many Runs are live in one Project at once, and each node
// instance has its own state.

export type RunLifecycleStatus = RunStatus;
export type ActiveRunLifecycleStatus = "running";
export type TerminalRunStatus =
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";

/** The room's identity for one node instance. */
export interface RoomInstanceKey {
  readonly project_id: string;
  readonly graph_id: string;
  readonly call_path: readonly string[];
  readonly node_id: string;
  readonly map_index: number | null;
}

/** Derived state of one node instance, as the room publishes it. */
export interface RoomInstanceState extends RoomInstanceKey {
  readonly state: InstanceStateName;
  readonly fingerprint: string;
  readonly last_result_fingerprint: string | null;
  readonly error: string | null;
}

export interface RoomReadyMessage {
  readonly protocol_version: 1;
  readonly type: "room.ready";
  readonly workspace_id: string;
  readonly project_id: string;
  readonly project_room_session_id: string;
  readonly actor: ActorPresentation;
  readonly capabilities: CapabilitySnapshot;
  readonly head: CollaborativeHead;
  readonly participants: readonly PresenceParticipant[];
  readonly active_runs: readonly ActiveRunSummary[];
  readonly instances: readonly RoomInstanceState[];
  readonly registry_marker: string;
}

export interface RunStartedMessage {
  readonly protocol_version: 1;
  readonly type: "run.started";
  readonly run: ActiveRunSummary;
}

export interface RunFinishedMessage {
  readonly protocol_version: 1;
  readonly type: "run.finished";
  readonly run_id: string;
  readonly status: TerminalRunStatus;
  readonly error: string | null;
}

/** Instance-state deltas. `removed` names the instances that no longer exist. */
export interface InstancesChangedMessage {
  readonly protocol_version: 1;
  readonly type: "instances.changed";
  readonly changed: readonly RoomInstanceState[];
  readonly removed: readonly RoomInstanceKey[];
  readonly head_sequence: number;
}

export interface ProjectCommandSubmitMessage {
  readonly protocol_version: 1;
  readonly type: "project.command.submit";
  readonly command_id: string;
  readonly room_epoch: string;
  readonly observed_sequence: number;
  readonly commands: readonly RoomProjectCommand[];
}

export interface ProjectCommandAcceptedMessage {
  readonly protocol_version: 1;
  readonly type: "project.command.accepted";
  readonly command_id: string;
  readonly room_epoch: string;
  readonly sequence: number;
  readonly actor: ActorPresentation;
  readonly project_room_session_id: string | null;
  readonly commands: readonly RoomProjectCommand[];
}

export interface ProjectCommandReceiptMessage {
  readonly protocol_version: 1;
  readonly type: "project.command.receipt";
  readonly command_id: string;
  readonly outcome: "accepted" | "idempotent_replay";
  readonly accepted_room_epoch: string;
  readonly accepted_sequence: number;
  readonly current_room_epoch: string;
  readonly current_sequence: number;
  readonly deduplicated: boolean;
  readonly requires_head_rehydration: boolean;
}

export interface ProjectCommandRejectedMessage {
  readonly protocol_version: 1;
  readonly type: "project.command.rejected";
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

/** Server-owned keepalive; it also revalidates membership. */
export interface RoomHeartbeatMessage {
  readonly protocol_version: 1;
  readonly type: "room.heartbeat";
  readonly authorization_version: number;
}

export type ServerRoomMessage =
  | RoomReadyMessage
  | ProjectCommandAcceptedMessage
  | ProjectCommandReceiptMessage
  | ProjectCommandRejectedMessage
  | RoomRehydrateMessage
  | RoomHeartbeatMessage
  | PresenceJoinMessage
  | PresenceLeaveMessage
  | PresenceUpdateMessage
  | RunStartedMessage
  | RunFinishedMessage
  | InstancesChangedMessage;

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

function isBoolean(value: unknown): value is boolean {
  return typeof value === "boolean";
}

function parseActor(value: unknown): ActorPresentation | null {
  if (!isRecord(value)) return null;
  if (
    !isString(value.actor_id) ||
    !isString(value.display_name) ||
    !isString(value.color)
  ) {
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

function optionalString(value: unknown): string | null | undefined {
  if (value === null) return null;
  return isString(value) ? value : undefined;
}

function parseParticipant(value: unknown): PresenceParticipant | null {
  if (!isRecord(value)) return null;
  const actor = parseActor(value.actor);
  if (!actor || !isString(value.project_room_session_id)) return null;
  if (!isNonNegativeInt(value.presence_sequence)) return null;
  const graphId = optionalString(value.graph_id);
  if (graphId === undefined && value.graph_id !== undefined && value.graph_id !== null) {
    return null;
  }
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
  if (
    value.activity !== null &&
    value.activity !== undefined &&
    activity === null
  ) {
    return null;
  }
  return {
    project_room_session_id: value.project_room_session_id,
    actor,
    graph_id: graphId ?? null,
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
  if (
    !Array.isArray(value.capabilities) ||
    !isPositiveInt(value.authorization_version)
  ) {
    return null;
  }
  if (!value.capabilities.every((item) => isString(item))) return null;
  return {
    capabilities: value.capabilities as WorkspaceCapability[],
    authorization_version: value.authorization_version,
  };
}

/**
 * The head of a Project: the whole Project document, whose `graphs` each hold
 * one Graph document. A flat head, or a document without its Graphs, is a
 * protocol error rather than something to paper over.
 */
function parseHead(value: unknown): CollaborativeHead | null {
  if (!isRecord(value)) return null;
  if (
    "nodes" in value ||
    "edges" in value ||
    "origins" in value ||
    "presentation" in value ||
    "graph_id" in value
  ) {
    return null;
  }
  const document = value.document;
  if (!isRecord(document) || !Array.isArray(document.graphs)) return null;
  for (const graph of document.graphs) {
    if (!isRecord(graph)) return null;
    if (!isString(graph.id) || !isString(graph.name)) return null;
    const graphDocument = graph.document;
    if (
      !isRecord(graphDocument) ||
      !Array.isArray(graphDocument.nodes) ||
      !Array.isArray(graphDocument.edges) ||
      !Array.isArray(graphDocument.origins)
    ) {
      return null;
    }
  }
  if (
    !isString(value.project_id) ||
    !isString(value.room_epoch) ||
    !isNonNegativeInt(value.collaboration_sequence) ||
    !isNonNegativeInt(value.checkpoint_sequence) ||
    !isPositiveInt(value.checkpoint_revision) ||
    !isString(value.name) ||
    !isString(value.updated_at)
  ) {
    return null;
  }
  return value as unknown as CollaborativeHead;
}

function parseInstanceKey(value: unknown): RoomInstanceKey | null {
  if (!isRecord(value)) return null;
  const callPath = parseStringIdList(value.call_path ?? []);
  if (
    callPath === null ||
    !isString(value.project_id) ||
    !isString(value.graph_id) ||
    !isString(value.node_id)
  ) {
    return null;
  }
  if (
    value.map_index !== null &&
    value.map_index !== undefined &&
    !isNonNegativeInt(value.map_index)
  ) {
    return null;
  }
  return {
    project_id: value.project_id,
    graph_id: value.graph_id,
    call_path: callPath,
    node_id: value.node_id,
    map_index: isNonNegativeInt(value.map_index) ? value.map_index : null,
  };
}

function parseInstanceState(value: unknown): RoomInstanceState | null {
  const key = parseInstanceKey(value);
  if (!key || !isRecord(value)) return null;
  const state = value.state;
  if (
    state !== "fresh" &&
    state !== "stale" &&
    state !== "queued" &&
    state !== "running" &&
    state !== "failed"
  ) {
    return null;
  }
  if (!isString(value.fingerprint)) return null;
  const lastResult = optionalString(value.last_result_fingerprint);
  if (lastResult === undefined && value.last_result_fingerprint != null) {
    return null;
  }
  const error = optionalString(value.error);
  if (error === undefined && value.error != null) return null;
  return {
    ...key,
    state,
    fingerprint: value.fingerprint,
    last_result_fingerprint: lastResult ?? null,
    error: error ?? null,
  };
}

function parseRunTargets(value: unknown): readonly { node_id: string; call_path: readonly string[] }[] | null {
  if (!Array.isArray(value)) return null;
  const targets: { node_id: string; call_path: readonly string[] }[] = [];
  for (const item of value) {
    if (!isRecord(item) || !isString(item.node_id)) return null;
    const callPath = parseStringIdList(item.call_path ?? []);
    if (callPath === null) return null;
    targets.push({ node_id: item.node_id, call_path: callPath });
  }
  return targets;
}

function parseActiveRun(value: unknown): ActiveRunSummary | null {
  if (!isRecord(value)) return null;
  const targets = parseRunTargets(value.targets ?? []);
  if (
    targets === null ||
    !isString(value.run_id) ||
    !isString(value.graph_id) ||
    !isString(value.started_at) ||
    !isBoolean(value.cancellable)
  ) {
    return null;
  }
  if (value.starter !== null && value.starter !== undefined) {
    const starter = parseActor(value.starter);
    if (!starter) return null;
    return {
      run_id: value.run_id,
      graph_id: value.graph_id,
      targets,
      starter,
      started_at: value.started_at,
      cancellable: value.cancellable,
    };
  }
  return {
    run_id: value.run_id,
    graph_id: value.graph_id,
    targets,
    starter: null,
    started_at: value.started_at,
    cancellable: value.cancellable,
  };
}

function parseCommandList(value: unknown): readonly RoomProjectCommand[] | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  if (!value.every((command) => isRecord(command) && isString(command.kind))) {
    return null;
  }
  return value as unknown as readonly RoomProjectCommand[];
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
      !isString(raw.project_id) ||
      !isString(raw.project_room_session_id) ||
      !isString(raw.registry_marker)
    ) {
      return null;
    }
    const participants = Array.isArray(raw.participants)
      ? raw.participants.map(parseParticipant)
      : [];
    if (participants.some((item) => item === null)) return null;
    if (!Array.isArray(raw.active_runs) || !Array.isArray(raw.instances)) {
      return null;
    }
    const activeRuns = raw.active_runs.map(parseActiveRun);
    if (activeRuns.some((run) => run === null)) return null;
    const instances = raw.instances.map(parseInstanceState);
    if (instances.some((instance) => instance === null)) return null;
    return {
      protocol_version: 1,
      type: "room.ready",
      workspace_id: raw.workspace_id,
      project_id: raw.project_id,
      project_room_session_id: raw.project_room_session_id,
      actor,
      capabilities,
      head,
      participants: participants as PresenceParticipant[],
      active_runs: activeRuns as ActiveRunSummary[],
      instances: instances as RoomInstanceState[],
      registry_marker: raw.registry_marker,
    };
  }

  if (type === "presence.join" || type === "presence.update") {
    const participant = parseParticipant(raw.participant);
    if (!participant) return null;
    return { protocol_version: 1, type, participant };
  }

  if (type === "presence.leave") {
    if (!isString(raw.project_room_session_id)) return null;
    return {
      protocol_version: 1,
      type: "presence.leave",
      project_room_session_id: raw.project_room_session_id,
    };
  }

  if (type === "run.started") {
    const run = parseActiveRun(raw.run);
    if (!run) return null;
    return { protocol_version: 1, type: "run.started", run };
  }

  if (type === "run.finished") {
    const status = raw.status;
    if (
      !isString(raw.run_id) ||
      (status !== "succeeded" &&
        status !== "failed" &&
        status !== "cancelled" &&
        status !== "interrupted")
    ) {
      return null;
    }
    const error = optionalString(raw.error);
    if (error === undefined && raw.error != null) return null;
    return {
      protocol_version: 1,
      type: "run.finished",
      run_id: raw.run_id,
      status,
      error: error ?? null,
    };
  }

  if (type === "instances.changed") {
    if (!Array.isArray(raw.changed) || !Array.isArray(raw.removed)) {
      return null;
    }
    if (!isNonNegativeInt(raw.head_sequence)) return null;
    const changed = raw.changed.map(parseInstanceState);
    if (changed.some((instance) => instance === null)) return null;
    const removed = raw.removed.map(parseInstanceKey);
    if (removed.some((key) => key === null)) return null;
    return {
      protocol_version: 1,
      type: "instances.changed",
      changed: changed as RoomInstanceState[],
      removed: removed as RoomInstanceKey[],
      head_sequence: raw.head_sequence,
    };
  }

  if (type === "project.command.accepted") {
    const actor = parseActor(raw.actor);
    const commands = parseCommandList(raw.commands);
    if (
      !actor ||
      !commands ||
      !isString(raw.command_id) ||
      !isString(raw.room_epoch) ||
      !isNonNegativeInt(raw.sequence)
    ) {
      return null;
    }
    const sessionId = raw.project_room_session_id;
    if (sessionId !== null && sessionId !== undefined && !isString(sessionId)) {
      return null;
    }
    return {
      protocol_version: 1,
      type: "project.command.accepted",
      command_id: raw.command_id,
      room_epoch: raw.room_epoch,
      sequence: raw.sequence,
      actor,
      project_room_session_id: isString(sessionId) ? sessionId : null,
      commands,
    };
  }

  if (type === "project.command.receipt") {
    if (
      !isString(raw.command_id) ||
      (raw.outcome !== "accepted" && raw.outcome !== "idempotent_replay") ||
      !isString(raw.accepted_room_epoch) ||
      !isNonNegativeInt(raw.accepted_sequence) ||
      !isString(raw.current_room_epoch) ||
      !isNonNegativeInt(raw.current_sequence) ||
      !isBoolean(raw.deduplicated)
    ) {
      return null;
    }
    return {
      protocol_version: 1,
      type: "project.command.receipt",
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

  if (type === "project.command.rejected") {
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
    if (
      sequence !== null &&
      sequence !== undefined &&
      !isNonNegativeInt(sequence)
    ) {
      return null;
    }
    return {
      protocol_version: 1,
      type: "project.command.rejected",
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
      head,
    };
  }

  if (type === "room.heartbeat") {
    if (!isPositiveInt(raw.authorization_version)) return null;
    return {
      protocol_version: 1,
      type: "room.heartbeat",
      authorization_version: raw.authorization_version,
    };
  }

  return null;
}

/** Stable text for one instance key, so a delta can replace what it supersedes. */
export function instanceKeyText(key: RoomInstanceKey): string {
  return [
    key.graph_id,
    key.call_path.join("/"),
    key.node_id,
    key.map_index === null ? "" : String(key.map_index),
  ].join(" ");
}

export type GraphRoomTerminalReason = ProjectRoomTerminalReason;
export type GraphRoomRecoveryReason = ProjectRoomRecoveryReason;
export type GraphRoomStatus = ProjectRoomStatus;
export type GraphRoomFailure = ProjectRoomFailure;
export const CLOSE_GRAPH_DELETED = CLOSE_PROJECT_DELETED;

export function terminalReasonFromClose(
  code: number,
  reason: string,
): ProjectRoomRecoveryReason | ProjectRoomTerminalReason | null {
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
  if (
    code === CLOSE_PROJECT_DELETED ||
    normalized === "project_deleted" ||
    normalized === "graph_deleted"
  ) {
    return "project_deleted";
  }
  if (code === CLOSE_PROTOCOL_ERROR || normalized === "protocol_error") {
    return "protocol_error";
  }
  if (code === CLOSE_SLOW_CONSUMER || normalized === "slow_consumer") {
    return "slow_consumer";
  }
  return null;
}
