import { publishAgentRoom } from "../agents/stream";
import type {
  ActiveRunSummary,
  CollaborativeHead,
  WorkspaceCapability,
} from "@/lib/api";
import { ApiError } from "@/lib/api/client";

import {
  ProjectRoomCommandError,
  ProjectRoomCommandOutbox,
  type ProjectRoomCommandResult,
  type OutgoingProjectCommand,
} from "./command-outbox";
import { projectRoomWebSocketUrl } from "./project-room-url";
import { ProjectRoomPresenceStore } from "./presence-store";
import {
  ROOM_COMMAND_QUEUE_CAP,
  ROOM_PROTOCOL_VERSION,
  parseServerRoomMessage,
  terminalReasonFromClose,
  type ActorPresentation,
  type ProjectCommandAcceptedMessage,
  type ProjectCheckpointedMessage,
  type ProjectCommandRejectedMessage,
  type ProjectRoomStatus,
  type ProjectRoomFailure,
  type ProjectRoomRecoveryReason,
  type ProjectRoomTerminalReason,
  type InstancesChangedMessage,
  type NodeProgressMessage,
  type PresenceParticipant,
  type PresenceUpdateSubmit,
  type RoomInstanceState,
  type RoomInstanceKey,
  type RoomProjectCommand,
  type RoomReadyMessage,
  type RunFinishedMessage,
  type RunStartedMessage,
} from "./protocol";
import { applyRoomCommandsToHead } from "./room-command-bridge";
import { instanceKeyText } from "./protocol";

export type {
  ProjectRoomStatus,
  ProjectRoomTerminalReason,
  RoomProjectCommand,
};
export type { ProjectRoomFailure, ProjectRoomRecoveryReason };
export { ProjectRoomCommandError } from "./command-outbox";
export type { ProjectRoomCommandResult } from "./command-outbox";
export type {
  ActiveRunSummary,
  InstancesChangedMessage,
  PresenceParticipant,
  PresenceUpdateSubmit,
  RoomInstanceState,
  RoomInstanceKey,
  RunFinishedMessage,
  RunStartedMessage,
};
export { ROOM_COMMAND_QUEUE_CAP, projectRoomWebSocketUrl };

export const PRESENCE_CLIENT_MIN_INTERVAL_MS = 50;

const KNOWN_SERVER_MESSAGE_TYPES = new Set([
  "room.ready",
  "room.rehydrate",
  "room.heartbeat",
  "presence.join",
  "presence.leave",
  "presence.update",
  "run.started",
  "run.finished",
  "instances.changed",
  "node.progress",
  "project.checkpointed",
  "project.command.accepted",
  "project.command.receipt",
  "project.command.rejected",
]);

/** True when `incoming` should replace the session's confirmed head snapshot. */
export function shouldReplaceCollaborativeHead(
  current: CollaborativeHead | null | undefined,
  incoming: CollaborativeHead,
): boolean {
  if (!current) return true;
  if (current.room_epoch !== incoming.room_epoch) {
    return incoming.checkpoint_revision > current.checkpoint_revision;
  }
  return incoming.collaboration_sequence >= current.collaboration_sequence;
}

export interface ProjectRoomAcceptedMeta {
  readonly local: boolean;
}

export interface ProjectRoomSessionListeners {
  onStatusChange?: (status: ProjectRoomStatus) => void;
  onReady?: (ready: RoomReadyMessage) => void;
  onRehydrate?: (head: CollaborativeHead) => void;
  /** Session paused command drain until replaceHead supplies a full snapshot. */
  onCheckpointed?: (head: CollaborativeHead) => void;
  onPendingCommandsChange?: (pending: boolean) => void;
  onHeadRefreshRequired?: () => void;
  onCommandAccepted?: (
    message: ProjectCommandAcceptedMessage,
    meta: ProjectRoomAcceptedMeta,
  ) => void;
  onCommandRejected?: (message: ProjectCommandRejectedMessage) => void;
  onPresenceChange?: (participants: readonly PresenceParticipant[]) => void;
  /** The Project's active Runs. Many at once: a Run is one demand for freshness. */
  onActiveRunsChange?: (runs: readonly ActiveRunSummary[]) => void;
  /** Derived state deltas for node instances, with the keys that disappeared. */
  onInstancesChange?: (message: InstancesChangedMessage) => void;
  onNodeProgress?: (message: NodeProgressMessage) => void;
  /** A Run left the active list; its results live on the instances. */
  onRunFinished?: (message: RunFinishedMessage) => void;
  onAuthorizationVersionChange?: (authorizationVersion: number) => void;
  onFailureChange?: (failure: ProjectRoomFailure | null) => void;
  onTerminalClose?: (reason: ProjectRoomTerminalReason) => void;
}

export interface ProjectRoomSessionOptions extends ProjectRoomSessionListeners {
  workspaceId: string;
  projectId: string;
  webSocketFactory?: (url: string) => WebSocket;
  reconnectDelayMs?: number;
  maxReconnectAttempts?: number;
  createCommandId?: () => string;
  presenceStore?: ProjectRoomPresenceStore;
  /**
   * Confirm the browser session after a lost socket or an access-revoked
   * close. One call per failure episode: further drops while reconnecting do
   * not ask again until the room is ready. Reject with an `ApiError` 401 to
   * stop reconnects. Resolve, or reject with anything else, and recovery
   * continues.
   */
  probeSession?: (signal: AbortSignal) => Promise<void>;
}

type ProjectRoomFailureDetail = Omit<
  ProjectRoomFailure,
  "workspaceId" | "projectId" | "projectRoomSessionId"
>;

export class ProjectRoomSession {
  readonly workspaceId: string;
  readonly projectId: string;

  private readonly webSocketFactory: (url: string) => WebSocket;
  private readonly reconnectDelayMs: number;
  private readonly maxReconnectAttempts: number;
  private readonly listeners: ProjectRoomSessionListeners;
  /** Correlates submitted commands with the accepted / receipt messages. */
  private readonly outbox: ProjectRoomCommandOutbox;

  private socket: WebSocket | null = null;
  private status: ProjectRoomStatus = "idle";
  private terminalReason: ProjectRoomTerminalReason | null = null;
  private lastFailure: ProjectRoomFailure | null = null;
  private intentionallyClosed = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private generation = 0;
  private readonly sessionProbe:
    ((signal: AbortSignal) => Promise<void>) | null;
  private sessionProbeController: AbortController | null = null;
  private sessionProbePending = false;
  /** True after this episode has asked once. Cleared when the room is ready. */
  private sessionProbeConsumedEpisode = false;
  /** A newer episode started while a probe was still in flight. */
  private sessionProbeQueued = false;

  private ready: RoomReadyMessage | null = null;
  private head: CollaborativeHead | null = null;
  private deferredCheckpoint: ProjectCheckpointedMessage | null = null;
  private capabilities: readonly WorkspaceCapability[] = [];
  private authorizationVersion: number | null = null;
  private readonly presenceStore: ProjectRoomPresenceStore;
  private presenceSequence = 0;
  private lastPresenceSentAt = 0;
  private activeRuns = new Map<string, ActiveRunSummary>();
  private instances = new Map<string, RoomInstanceState>();

  constructor(options: ProjectRoomSessionOptions) {
    this.workspaceId = options.workspaceId;
    this.projectId = options.projectId;
    this.webSocketFactory =
      options.webSocketFactory ?? ((url) => new WebSocket(url));
    this.reconnectDelayMs = options.reconnectDelayMs ?? 750;
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? 5;
    this.sessionProbe = options.probeSession ?? null;
    this.presenceStore =
      options.presenceStore ??
      new ProjectRoomPresenceStore({
        workspaceId: options.workspaceId,
        projectId: options.projectId,
      });
    this.listeners = {
      onStatusChange: options.onStatusChange,
      onReady: options.onReady,
      onRehydrate: options.onRehydrate,
      onCheckpointed: options.onCheckpointed,
      onCommandAccepted: options.onCommandAccepted,
      onPresenceChange: options.onPresenceChange,
      onActiveRunsChange: options.onActiveRunsChange,
      onInstancesChange: options.onInstancesChange,
      onNodeProgress: options.onNodeProgress,
      onRunFinished: options.onRunFinished,
      onAuthorizationVersionChange: options.onAuthorizationVersionChange,
      onFailureChange: options.onFailureChange,
      onTerminalClose: options.onTerminalClose,
    };
    this.outbox = new ProjectRoomCommandOutbox({
      createCommandId: options.createCommandId,
      // The outbox reads the confirmed head to stamp and settle commands; the
      // session stays the only owner of head replacement.
      headPointer: () => this.head,
      canSend: () => this.canSendCommand(),
      onHeadRefreshRequired: options.onHeadRefreshRequired,
      onPendingCommandsChange: options.onPendingCommandsChange,
      onCommandRejected: options.onCommandRejected,
    });
  }

  getStatus(): ProjectRoomStatus {
    return this.status;
  }

  getTerminalReason(): ProjectRoomTerminalReason | null {
    return this.terminalReason;
  }

  getLastFailure(): ProjectRoomFailure | null {
    return this.lastFailure;
  }

  getHead(): CollaborativeHead | null {
    return this.head;
  }

  getCapabilities(): readonly WorkspaceCapability[] {
    return this.capabilities;
  }

  getAuthorizationVersion(): number | null {
    return this.authorizationVersion;
  }

  getActor(): ActorPresentation | null {
    return this.ready?.actor ?? null;
  }

  getProjectRoomSessionId(): string | null {
    return this.ready?.project_room_session_id ?? null;
  }

  /** The Runs this Project has in flight, in the order the room reported them. */
  getActiveRuns(): readonly ActiveRunSummary[] {
    return [...this.activeRuns.values()];
  }

  /** Derived state for every node instance the room has told us about. */
  getInstances(): readonly RoomInstanceState[] {
    return [...this.instances.values()];
  }

  getParticipants(): readonly PresenceParticipant[] {
    return this.presenceStore.getParticipants();
  }

  getPresenceStore(): ProjectRoomPresenceStore {
    return this.presenceStore;
  }

  getRemoteParticipants(): readonly PresenceParticipant[] {
    const localId = this.getProjectRoomSessionId();
    return this.getParticipants().filter(
      (participant) => participant.project_room_session_id !== localId,
    );
  }

  canPublishPresence(): boolean {
    return (
      this.status === "ready" &&
      this.capabilities.includes("publish_presence") &&
      this.terminalReason === null
    );
  }

  publishPresence(
    update: Omit<PresenceUpdateSubmit, "presence_sequence">,
  ): boolean {
    if (!this.canPublishPresence()) return false;
    const now = Date.now();
    if (
      this.lastPresenceSentAt > 0 &&
      now - this.lastPresenceSentAt < PRESENCE_CLIENT_MIN_INTERVAL_MS
    ) {
      return false;
    }
    const socket = this.socket;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    this.presenceSequence += 1;
    const payload = {
      protocol_version: ROOM_PROTOCOL_VERSION,
      type: "presence.update" as const,
      graph_id: update.graph_id ?? null,
      presence_sequence: this.presenceSequence,
      cursor: update.cursor ?? null,
      selected_node_ids: update.selected_node_ids ?? [],
      selected_edge_ids: update.selected_edge_ids ?? [],
      activity: update.activity ?? null,
      activity_target_ids: update.activity_target_ids ?? [],
      transient_node_positions: update.transient_node_positions ?? [],
    };
    try {
      socket.send(JSON.stringify(payload));
      this.lastPresenceSentAt = now;
      return true;
    } catch {
      return false;
    }
  }

  canSubmitCommands(): boolean {
    return (
      this.status === "ready" &&
      this.head !== null &&
      this.capabilities.includes("edit_project") &&
      this.terminalReason === null
    );
  }

  connect(): void {
    if (this.terminalReason !== null) return;
    this.intentionallyClosed = false;
    this.clearReconnectTimer();
    this.openSocket();
  }

  retry(): void {
    if (this.terminalReason !== "reconnect_exhausted") return;
    this.terminalReason = null;
    this.intentionallyClosed = false;
    this.reconnectAttempts = 0;
    this.sessionProbeConsumedEpisode = false;
    this.clearReconnectTimer();
    this.openSocket();
  }

  disconnect(): void {
    this.abortSessionProbe();
    this.intentionallyClosed = true;
    this.clearReconnectTimer();
    this.generation += 1;
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) {
      socket.close(1000, "client_disconnect");
    }
    this.outbox.rejectAll(
      new ProjectRoomCommandError(
        "",
        "disconnected",
        "The Project room disconnected before the command completed.",
      ),
    );
    this.outbox.clearLocalCommands();
    this.reconnectAttempts = 0;
    this.setFailure(null);
    this.setStatus("idle");
    this.ready = null;
    this.clearPresence();
  }

  /**
   * Replace the cached head during conflict recovery. Ignore stale snapshots
   * so a late HTTP fetch cannot wipe a newer WebSocket-applied head.
   */
  replaceHead(head: CollaborativeHead): void {
    if (shouldReplaceCollaborativeHead(this.head, head)) {
      this.installHead(head);
    }
    this.writeSends(this.outbox.finishHeadRehydration());
  }

  private installHead(head: CollaborativeHead): void {
    const current = this.head;
    if (
      current?.room_epoch === head.room_epoch &&
      current.checkpoint_sequence > head.checkpoint_sequence
    ) {
      head = {
        ...head,
        checkpoint_sequence: current.checkpoint_sequence,
        checkpoint_revision: current.checkpoint_revision,
      };
    }
    if (current?.room_epoch !== head.room_epoch) this.deferredCheckpoint = null;
    this.head = head;
    this.applyDeferredCheckpoint();
  }

  private applyDeferredCheckpoint(): void {
    const message = this.deferredCheckpoint;
    const head = this.head;
    if (
      !message ||
      !head ||
      message.checkpoint_sequence > head.collaboration_sequence
    ) {
      return;
    }
    this.deferredCheckpoint = null;
    if (
      message.checkpoint_sequence < head.checkpoint_sequence ||
      message.checkpoint_revision <= head.checkpoint_revision
    ) {
      return;
    }
    this.head = {
      ...head,
      checkpoint_sequence: message.checkpoint_sequence,
      checkpoint_revision: message.checkpoint_revision,
    };
    this.listeners.onCheckpointed?.(this.head);
  }

  /**
   * Submit one command batch. A batch is a Project-level command or a
   * sequence of commands addressed to one Graph of this Project.
   */
  submitCommands(
    commands: readonly RoomProjectCommand[],
  ): Promise<ProjectRoomCommandResult> {
    if (!this.canSubmitCommands() || this.head === null) {
      return Promise.reject(
        new ProjectRoomCommandError(
          "",
          "not_ready",
          "The Project room is not ready to accept durable commands.",
        ),
      );
    }
    const submission = this.outbox.submit(commands);
    this.writeSends(submission.sends);
    return submission.promise;
  }

  /** Write the submit frames the outbox produced, in order. */
  private writeSends(sends: readonly OutgoingProjectCommand[]): void {
    for (const send of sends) {
      const socket = this.socket;
      // `canSendCommand` held when the frame was produced. A transport that
      // vanished in between leaves the command in flight, and the next close
      // puts it back at the front of the queue for replay.
      if (!socket) continue;
      try {
        socket.send(JSON.stringify(send.message));
      } catch (error) {
        this.outbox.sendFailed(send.commandId, error);
      }
    }
  }

  private canSendCommand(): boolean {
    const socket = this.socket;
    return (
      this.canSubmitCommands() &&
      socket !== null &&
      socket.readyState === WebSocket.OPEN
    );
  }

  private openSocket(): void {
    if (this.intentionallyClosed || this.terminalReason !== null) return;

    this.generation += 1;
    const generation = this.generation;
    const url = projectRoomWebSocketUrl(this.workspaceId, this.projectId);
    this.setStatus(this.head ? "reconnecting" : "connecting");

    let socket: WebSocket;
    try {
      socket = this.webSocketFactory(url);
    } catch (error) {
      this.recoverTraffic({
        reason: "connection_lost",
        retryable: true,
        side: "network",
        phase: "connect",
        messageType: null,
        protocolVersion: ROOM_PROTOCOL_VERSION,
        closeCode: null,
        detail:
          error instanceof Error
            ? error.message
            : "The Project room connection could not be opened.",
      });
      return;
    }

    this.socket = socket;
    socket.addEventListener("open", () => {
      if (generation !== this.generation || this.socket !== socket) return;
      // Cookies are sent automatically for same-origin WebSockets.
      // Wait for room.ready before accepting commands.
    });
    socket.addEventListener("message", (event) => {
      if (generation !== this.generation || this.socket !== socket) return;
      this.handleMessage(event.data);
    });
    socket.addEventListener("close", (event) => {
      if (generation !== this.generation || this.socket !== socket) return;
      this.socket = null;
      this.handleClose(event.code, event.reason ?? "");
    });
    socket.addEventListener("error", () => {
      if (generation !== this.generation || this.socket !== socket) return;
      // close follows; mark unsynchronized until then
      if (this.status === "ready") {
        this.setStatus("unsynchronized");
      }
    });
  }

  private handleMessage(data: unknown): void {
    let raw: unknown = data;
    if (typeof data === "string") {
      try {
        raw = JSON.parse(data) as unknown;
      } catch (error) {
        this.recoverTraffic({
          reason: "protocol_error",
          retryable: true,
          side: "server",
          phase: "receive",
          messageType: null,
          protocolVersion: null,
          closeCode: null,
          detail:
            error instanceof Error
              ? error.message
              : "The server sent malformed JSON.",
        });
        return;
      }
    }
    if (
      typeof raw === "object" &&
      raw !== null &&
      "type" in raw &&
      (raw as { type?: unknown }).type === "room.heartbeat"
    ) {
      return;
    }
    const messageType =
      typeof raw === "object" &&
      raw !== null &&
      "type" in raw &&
      typeof (raw as { type?: unknown }).type === "string"
        ? (raw as { type: string }).type
        : null;
    const protocolVersion =
      typeof raw === "object" &&
      raw !== null &&
      "protocol_version" in raw &&
      typeof (raw as { protocol_version?: unknown }).protocol_version ===
        "number"
        ? (raw as { protocol_version: number }).protocol_version
        : null;
    if (protocolVersion !== ROOM_PROTOCOL_VERSION) {
      this.stopTraffic("protocol_incompatible", {
        reason: "protocol_incompatible",
        retryable: false,
        side: "client",
        phase: "receive",
        messageType,
        protocolVersion,
        closeCode: null,
        detail: `Expected Project-room protocol ${ROOM_PROTOCOL_VERSION}, received ${protocolVersion ?? "no version"}.`,
      });
      return;
    }
    if (messageType?.startsWith("agent.") || messageType === "room.ready") {
      publishAgentRoom({
        workspaceId: this.workspaceId,
        projectId: this.projectId,
        raw,
      });
      if (messageType.startsWith("agent.")) return;
    }
    if (messageType !== null && !KNOWN_SERVER_MESSAGE_TYPES.has(messageType)) {
      return;
    }
    const message = parseServerRoomMessage(raw);
    if (message === null) {
      this.recoverTraffic({
        reason: "protocol_error",
        retryable: true,
        side: "server",
        phase: "receive",
        messageType,
        protocolVersion,
        closeCode: null,
        detail: messageType
          ? `The server sent a malformed ${messageType} message.`
          : "The server sent a message without a valid type.",
      });
      return;
    }

    if (message.type === "room.ready") {
      this.applyReady(message);
      return;
    }
    if (message.type === "room.rehydrate") {
      if (shouldReplaceCollaborativeHead(this.head, message.head)) {
        this.installHead(message.head);
        this.listeners.onRehydrate?.(this.head ?? message.head);
        this.writeSends(this.outbox.finishHeadRehydration());
      }
      return;
    }
    if (message.type === "project.checkpointed") {
      // An explicit HTTP checkpoint can commit before the command's publication
      // reaches this socket. Apply its metadata after the matching batch arrives.
      if (
        message.room_epoch === this.head?.room_epoch &&
        message.checkpoint_revision >
          (this.deferredCheckpoint?.checkpoint_revision ??
            this.head.checkpoint_revision)
      ) {
        this.deferredCheckpoint = message;
        this.applyDeferredCheckpoint();
      }
      return;
    }
    if (
      message.type === "presence.join" ||
      message.type === "presence.update"
    ) {
      this.upsertParticipant(message.participant);
      return;
    }
    if (message.type === "presence.leave") {
      this.removeParticipant(message.project_room_session_id);
      return;
    }
    if (message.type === "run.started") {
      this.activeRuns.set(message.run.run_id, message.run);
      this.emitActiveRunsChange();
      return;
    }
    if (message.type === "run.finished") {
      this.activeRuns.delete(message.run_id);
      this.emitActiveRunsChange();
      this.listeners.onRunFinished?.(message);
      return;
    }
    if (message.type === "node.progress") {
      if (message.instance.project_id === this.projectId) {
        this.listeners.onNodeProgress?.(message);
      }
      return;
    }
    if (message.type === "instances.changed") {
      for (const key of message.removed) {
        this.instances.delete(instanceKeyText(key));
      }
      for (const instance of message.changed) {
        this.instances.set(instanceKeyText(instance), instance);
      }
      this.listeners.onInstancesChange?.(message);
      return;
    }
    if (message.type === "room.heartbeat") {
      this.authorizationVersion = message.authorization_version;
      this.listeners.onAuthorizationVersionChange?.(
        message.authorization_version,
      );
      return;
    }
    if (message.type === "project.command.accepted") {
      this.applyAccepted(message);
      return;
    }
    if (message.type === "project.command.receipt") {
      this.writeSends(this.outbox.applyReceipt(message));
      return;
    }
    if (message.type === "project.command.rejected") {
      this.outbox.applyRejected(message);
    }
  }

  private applyReady(message: RoomReadyMessage): void {
    if (
      message.workspace_id !== this.workspaceId ||
      message.project_id !== this.projectId
    ) {
      this.recoverTraffic({
        reason: "protocol_error",
        retryable: true,
        side: "server",
        phase: "receive",
        messageType: message.type,
        protocolVersion: message.protocol_version,
        closeCode: null,
        detail:
          "The room-ready message identified a different workspace or Project.",
      });
      return;
    }
    let ready = message;
    if (this.head && !shouldReplaceCollaborativeHead(this.head, message.head)) {
      ready = { ...message, head: this.head };
    }
    this.installHead(ready.head);
    ready = { ...ready, head: this.head ?? ready.head };
    this.ready = ready;
    this.capabilities = message.capabilities.capabilities;
    this.authorizationVersion = message.capabilities.authorization_version;
    this.presenceStore.replaceParticipants(
      message.participants,
      message.project_room_session_id,
    );
    this.presenceSequence = 0;
    this.lastPresenceSentAt = 0;
    // The room is authoritative for what is running and what is fresh: a
    // reconnect replaces both lists rather than merging into them.
    this.activeRuns = new Map(
      message.active_runs.map((run) => [run.run_id, run]),
    );
    this.instances = new Map(
      message.instances.map((instance) => [
        instanceKeyText(instance),
        instance,
      ]),
    );
    this.reconnectAttempts = 0;
    this.sessionProbeConsumedEpisode = false;
    this.setFailure(null);
    this.setStatus("ready");
    this.listeners.onReady?.(ready);
    this.emitActiveRunsChange();
    this.emitPresenceChange();
    this.writeSends(this.outbox.finishHeadRehydration());
  }

  private upsertParticipant(participant: PresenceParticipant): void {
    this.presenceStore.upsertParticipant(participant);
    this.emitPresenceChange();
  }

  private removeParticipant(sessionId: string): void {
    if (!this.presenceStore.removeParticipant(sessionId)) return;
    this.emitPresenceChange();
  }

  private clearPresence(): void {
    if (!this.presenceStore.clear()) return;
    this.emitPresenceChange();
  }

  private emitPresenceChange(): void {
    this.listeners.onPresenceChange?.(this.getParticipants());
  }

  private emitActiveRunsChange(): void {
    this.listeners.onActiveRunsChange?.(this.getActiveRuns());
  }

  private applyAccepted(message: ProjectCommandAcceptedMessage): void {
    const local = this.outbox.recordAccepted(message);

    const head = this.head;
    if (!head || message.room_epoch !== head.room_epoch) {
      this.outbox.requestHeadRefresh();
      return;
    }
    if (message.sequence <= head.collaboration_sequence) {
      return;
    }
    if (message.sequence !== head.collaboration_sequence + 1) {
      this.outbox.requestHeadRefresh();
      return;
    }

    try {
      this.head = applyRoomCommandsToHead(
        head,
        message.commands,
        message.sequence,
      );
    } catch {
      this.outbox.requestHeadRefresh();
      return;
    }
    this.applyDeferredCheckpoint();
    this.listeners.onCommandAccepted?.(message, { local });
    this.writeSends(this.outbox.afterHeadApplied());
  }

  private handleClose(code: number, reason: string): void {
    const classifiedReason = terminalReasonFromClose(code, reason);
    if (
      classifiedReason === "access_revoked" ||
      classifiedReason === "project_deleted"
    ) {
      this.stopTraffic(classifiedReason, {
        reason: classifiedReason,
        retryable: false,
        side: "server",
        phase: "close",
        messageType: null,
        protocolVersion: ROOM_PROTOCOL_VERSION,
        closeCode: code,
        detail:
          reason || `The server closed the Project room (${classifiedReason}).`,
      });
      if (classifiedReason === "access_revoked") {
        this.considerSessionProbe();
      }
      return;
    }
    if (this.intentionallyClosed) {
      this.setStatus("idle");
      return;
    }
    const recoveryReason: ProjectRoomRecoveryReason =
      classifiedReason === "permissions_changed" ||
      classifiedReason === "protocol_error" ||
      classifiedReason === "slow_consumer"
        ? classifiedReason
        : "connection_lost";
    this.recoverTraffic({
      reason: recoveryReason,
      retryable: true,
      side: classifiedReason === null ? "network" : "server",
      phase: "close",
      messageType: null,
      protocolVersion: ROOM_PROTOCOL_VERSION,
      closeCode: code,
      detail: reason || "The Project room connection closed unexpectedly.",
    });
  }

  private recoverTraffic(failure: ProjectRoomFailureDetail): void {
    this.setFailure(this.failureWithContext(failure));
    this.ready = null;
    this.capabilities = [];
    this.authorizationVersion = null;
    this.activeRuns = new Map();
    this.listeners.onActiveRunsChange?.([]);
    this.clearPresence();
    this.outbox.interruptInFlight();
    this.generation += 1;
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) {
      socket.close();
    }
    this.setStatus("unsynchronized");
    this.scheduleReconnect();
    if (failure.reason === "connection_lost") {
      this.considerSessionProbe();
    }
  }

  private stopTraffic(
    reason: ProjectRoomTerminalReason,
    failure?: ProjectRoomFailureDetail,
  ): void {
    this.intentionallyClosed = true;
    this.clearReconnectTimer();
    this.terminalReason = reason;
    if (failure) this.setFailure(this.failureWithContext(failure));
    this.ready = null;
    this.capabilities = [];
    this.authorizationVersion = null;
    this.clearPresence();
    this.generation += 1;
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) {
      socket.close();
    }
    this.outbox.rejectAll(
      new ProjectRoomCommandError(
        "",
        reason,
        `The Project room closed (${reason}). The displayed Project is not trusted for durable commands.`,
      ),
    );
    this.setStatus("stopped");
    this.listeners.onTerminalClose?.(reason);
  }

  private scheduleReconnect(): void {
    if (this.intentionallyClosed || this.terminalReason !== null) return;
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      const priorFailure = this.lastFailure;
      this.stopTraffic("reconnect_exhausted", {
        reason: "reconnect_exhausted",
        retryable: true,
        side: priorFailure?.side ?? "network",
        phase: priorFailure?.phase ?? "connect",
        messageType: priorFailure?.messageType ?? null,
        protocolVersion: priorFailure?.protocolVersion ?? ROOM_PROTOCOL_VERSION,
        closeCode: priorFailure?.closeCode ?? null,
        detail: `Automatic reconnection stopped after ${this.maxReconnectAttempts} attempts.`,
      });
      return;
    }
    this.clearReconnectTimer();
    const delay = Math.min(
      this.reconnectDelayMs * 2 ** this.reconnectAttempts,
      10_000,
    );
    this.reconnectAttempts += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      if (this.intentionallyClosed || this.terminalReason !== null) return;
      this.openSocket();
    }, delay);
  }

  /**
   * A failed handshake hides its HTTP status, and a reconnect loop would
   * otherwise keep opening sockets for an expired cookie. Ask once per
   * episode. A 401 stops the loop; a live session or a non-401 failure does
   * not.
   */
  private considerSessionProbe(): void {
    if (this.sessionProbe === null) return;
    if (this.sessionProbePending) {
      if (!this.sessionProbeConsumedEpisode) this.sessionProbeQueued = true;
      return;
    }
    if (this.sessionProbeConsumedEpisode) return;
    this.startSessionProbe();
  }

  private startSessionProbe(): void {
    const probe = this.sessionProbe;
    if (probe === null) return;
    this.sessionProbePending = true;
    this.sessionProbeConsumedEpisode = true;
    this.sessionProbeQueued = false;
    const controller = new AbortController();
    this.sessionProbeController = controller;
    void Promise.resolve()
      .then(() => probe(controller.signal))
      .then(() => undefined)
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        if (!isUnauthorizedSession(error)) return;
        this.haltReconnectForExpiredSession();
      })
      .finally(() => {
        if (this.sessionProbeController !== controller) return;
        this.sessionProbePending = false;
        this.sessionProbeController = null;
        if (
          this.sessionProbeQueued &&
          !this.sessionProbeConsumedEpisode &&
          !this.intentionallyClosed
        ) {
          this.sessionProbeQueued = false;
          this.considerSessionProbe();
          return;
        }
        this.sessionProbeQueued = false;
      });
  }

  private abortSessionProbe(): void {
    const controller = this.sessionProbeController;
    this.sessionProbeController = null;
    this.sessionProbePending = false;
    this.sessionProbeQueued = false;
    this.sessionProbeConsumedEpisode = false;
    controller?.abort();
  }

  /** Drop a reconnect that can only fail again once the session is gone. */
  private haltReconnectForExpiredSession(): void {
    this.clearReconnectTimer();
    this.intentionallyClosed = true;
    if (this.terminalReason !== null) return;
    this.generation += 1;
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) {
      socket.close();
    }
    this.outbox.rejectAll(
      new ProjectRoomCommandError(
        "",
        "disconnected",
        "The Project room disconnected before the command completed.",
      ),
    );
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer === null) return;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  private setStatus(status: ProjectRoomStatus): void {
    if (this.status === status) return;
    this.status = status;
    this.listeners.onStatusChange?.(status);
  }

  private setFailure(failure: ProjectRoomFailure | null): void {
    this.lastFailure = failure;
    this.listeners.onFailureChange?.(failure);
  }

  private failureWithContext(
    failure: ProjectRoomFailureDetail,
  ): ProjectRoomFailure {
    return {
      workspaceId: this.workspaceId,
      projectId: this.projectId,
      projectRoomSessionId:
        this.getProjectRoomSessionId() ??
        this.lastFailure?.projectRoomSessionId ??
        null,
      ...failure,
    };
  }
}

function isUnauthorizedSession(error: unknown): boolean {
  return error instanceof ApiError && error.status === 401;
}
