import type { CollaborativeHead, WorkspaceCapability } from "@/lib/api";

import {
  GraphRoomCommandError,
  GraphRoomCommandOutbox,
  type GraphRoomCommandResult,
  type OutgoingGraphCommand,
} from "./command-outbox";
import { graphRoomWebSocketUrl } from "./graph-room-url";
import {
  ROOM_COMMAND_QUEUE_CAP,
  ROOM_PROTOCOL_VERSION,
  parseServerRoomMessage,
  terminalReasonFromClose,
  type ActiveExecutionSummary,
  type ActorPresentation,
  type ExecutionClearedMessage,
  type GraphCommandAcceptedMessage,
  type GraphCommandRejectedMessage,
  type GraphRoomStatus,
  type GraphRoomFailure,
  type GraphRoomRecoveryReason,
  type GraphRoomTerminalReason,
  type PresenceParticipant,
  type PresenceUpdateSubmit,
  type RoomGraphCommand,
  type RoomReadyMessage,
} from "./protocol";
import { applyRoomCommandToHead } from "./room-command-bridge";

export type { GraphRoomStatus, GraphRoomTerminalReason, RoomGraphCommand };
export type { GraphRoomFailure, GraphRoomRecoveryReason };
export { GraphRoomCommandError } from "./command-outbox";
export type { GraphRoomCommandResult } from "./command-outbox";
export type {
  ActiveExecutionSummary,
  PresenceParticipant,
  PresenceUpdateSubmit,
};
export { ROOM_COMMAND_QUEUE_CAP, graphRoomWebSocketUrl };

export const PRESENCE_CLIENT_MIN_INTERVAL_MS = 50;

const KNOWN_SERVER_MESSAGE_TYPES = new Set([
  "room.ready",
  "room.rehydrate",
  "presence.join",
  "presence.leave",
  "presence.update",
  "execution.active",
  "execution.cleared",
  "graph.command.accepted",
  "graph.command.receipt",
  "graph.command.rejected",
]);

/** True when `incoming` should replace the session's confirmed head snapshot. */
export function shouldReplaceCollaborativeHead(
  current: CollaborativeHead | null | undefined,
  incoming: CollaborativeHead,
): boolean {
  if (!current) return true;
  if (current.room_epoch !== incoming.room_epoch) return true;
  return incoming.collaboration_sequence >= current.collaboration_sequence;
}

export interface GraphRoomAcceptedMeta {
  readonly local: boolean;
}

export interface GraphRoomSessionListeners {
  onStatusChange?: (status: GraphRoomStatus) => void;
  onReady?: (ready: RoomReadyMessage) => void;
  onRehydrate?: (head: CollaborativeHead) => void;
  /** Session paused command drain until replaceHead supplies a full snapshot. */
  onHeadRefreshRequired?: () => void;
  onCommandAccepted?: (
    message: GraphCommandAcceptedMessage,
    meta: GraphRoomAcceptedMeta,
  ) => void;
  onCommandRejected?: (message: GraphCommandRejectedMessage) => void;
  onPresenceChange?: (participants: readonly PresenceParticipant[]) => void;
  onActiveExecution?: (execution: ActiveExecutionSummary | null) => void;
  onExecutionCleared?: (message: ExecutionClearedMessage) => void;
  onFailureChange?: (failure: GraphRoomFailure | null) => void;
  onTerminalClose?: (reason: GraphRoomTerminalReason) => void;
}

export interface GraphRoomSessionOptions extends GraphRoomSessionListeners {
  workspaceId: string;
  graphId: string;
  webSocketFactory?: (url: string) => WebSocket;
  reconnectDelayMs?: number;
  maxReconnectAttempts?: number;
  createCommandId?: () => string;
}

type GraphRoomFailureDetail = Omit<
  GraphRoomFailure,
  "workspaceId" | "graphId" | "graphRoomSessionId"
>;

export class GraphRoomSession {
  readonly workspaceId: string;
  readonly graphId: string;

  private readonly webSocketFactory: (url: string) => WebSocket;
  private readonly reconnectDelayMs: number;
  private readonly maxReconnectAttempts: number;
  private readonly listeners: GraphRoomSessionListeners;
  /** Correlates submitted commands with the accepted / receipt messages. */
  private readonly outbox: GraphRoomCommandOutbox;

  private socket: WebSocket | null = null;
  private status: GraphRoomStatus = "idle";
  private terminalReason: GraphRoomTerminalReason | null = null;
  private lastFailure: GraphRoomFailure | null = null;
  private intentionallyClosed = false;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempts = 0;
  private generation = 0;

  private ready: RoomReadyMessage | null = null;
  private head: CollaborativeHead | null = null;
  private capabilities: readonly WorkspaceCapability[] = [];
  private authorizationVersion: number | null = null;
  private participants = new Map<string, PresenceParticipant>();
  private presenceSequence = 0;
  private lastPresenceSentAt = 0;
  private activeExecution: ActiveExecutionSummary | null = null;

  constructor(options: GraphRoomSessionOptions) {
    this.workspaceId = options.workspaceId;
    this.graphId = options.graphId;
    this.webSocketFactory =
      options.webSocketFactory ?? ((url) => new WebSocket(url));
    this.reconnectDelayMs = options.reconnectDelayMs ?? 750;
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? 5;
    this.listeners = {
      onStatusChange: options.onStatusChange,
      onReady: options.onReady,
      onRehydrate: options.onRehydrate,
      onCommandAccepted: options.onCommandAccepted,
      onPresenceChange: options.onPresenceChange,
      onActiveExecution: options.onActiveExecution,
      onExecutionCleared: options.onExecutionCleared,
      onFailureChange: options.onFailureChange,
      onTerminalClose: options.onTerminalClose,
    };
    this.outbox = new GraphRoomCommandOutbox({
      createCommandId: options.createCommandId,
      // The outbox reads the confirmed head to stamp and settle commands; the
      // session stays the only owner of head replacement.
      headPointer: () => this.head,
      canSend: () => this.canSendCommand(),
      onHeadRefreshRequired: options.onHeadRefreshRequired,
      onCommandRejected: options.onCommandRejected,
    });
  }

  getStatus(): GraphRoomStatus {
    return this.status;
  }

  getTerminalReason(): GraphRoomTerminalReason | null {
    return this.terminalReason;
  }

  getLastFailure(): GraphRoomFailure | null {
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

  getGraphRoomSessionId(): string | null {
    return this.ready?.graph_room_session_id ?? null;
  }

  getActiveExecution(): ActiveExecutionSummary | null {
    return this.activeExecution;
  }

  getParticipants(): readonly PresenceParticipant[] {
    return [...this.participants.values()];
  }

  getRemoteParticipants(): readonly PresenceParticipant[] {
    const localId = this.getGraphRoomSessionId();
    return this.getParticipants().filter(
      (participant) => participant.graph_room_session_id !== localId,
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
      this.capabilities.includes("edit_graph") &&
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
    this.clearReconnectTimer();
    this.openSocket();
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    this.clearReconnectTimer();
    this.generation += 1;
    const socket = this.socket;
    this.socket = null;
    if (socket && socket.readyState < WebSocket.CLOSING) {
      socket.close(1000, "client_disconnect");
    }
    this.outbox.rejectAll(
      new GraphRoomCommandError(
        "",
        "disconnected",
        "Graph room disconnected before the command completed.",
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
   * Replace the cached collaborative head (checkpoint or conflict recovery).
   * Ignores stale same-epoch snapshots so a late HTTP fetch cannot wipe a newer
   * WebSocket-applied head (e.g. a just-accepted presentation).
   */
  replaceHead(head: CollaborativeHead): void {
    if (!shouldReplaceCollaborativeHead(this.head, head)) {
      if (!this.outbox.pendingReceiptIsCovered()) return;
      this.writeSends(this.outbox.finishHeadRehydration());
      return;
    }
    this.head = head;
    this.writeSends(this.outbox.finishHeadRehydration());
  }

  /**
   * Reconcile a checkpoint response against the epoch of its submitted command.
   * A later epoch reset is authoritative and must not be reversed by the old
   * epoch's HTTP continuation.
   */
  reconcileCheckpointHead(
    checkpointHead: CollaborativeHead,
    expectedRoomEpoch: string,
  ): CollaborativeHead {
    const currentHead = this.head;
    if (!currentHead) {
      throw new Error(
        `Graph room head is unavailable while reconciling checkpoint epoch ${expectedRoomEpoch}.`,
      );
    }
    if (currentHead.room_epoch !== expectedRoomEpoch) {
      return currentHead;
    }
    if (checkpointHead.room_epoch !== expectedRoomEpoch) {
      throw new Error(
        `Checkpoint response epoch ${checkpointHead.room_epoch} does not match submitted command epoch ${expectedRoomEpoch}.`,
      );
    }

    this.replaceHead(checkpointHead);
    let effectiveHead = this.head;
    if (!effectiveHead) {
      throw new Error(
        `Graph room head is unavailable after reconciling checkpoint epoch ${expectedRoomEpoch}.`,
      );
    }
    if (
      effectiveHead.collaboration_sequence >
        checkpointHead.collaboration_sequence &&
      checkpointHead.checkpoint_sequence > effectiveHead.checkpoint_sequence
    ) {
      effectiveHead = {
        ...effectiveHead,
        checkpoint_sequence: checkpointHead.checkpoint_sequence,
        checkpoint_revision: checkpointHead.checkpoint_revision,
      };
      this.replaceHead(effectiveHead);
    }
    return effectiveHead;
  }

  submitCommand(command: RoomGraphCommand): Promise<GraphRoomCommandResult> {
    if (!this.canSubmitCommands() || this.head === null) {
      return Promise.reject(
        new GraphRoomCommandError(
          "",
          "not_ready",
          "Graph room is not ready to accept durable commands.",
        ),
      );
    }
    const submission = this.outbox.submit(command);
    this.writeSends(submission.sends);
    return submission.promise;
  }

  /** Write the submit frames the outbox produced, in order. */
  private writeSends(sends: readonly OutgoingGraphCommand[]): void {
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
    const url = graphRoomWebSocketUrl(this.workspaceId, this.graphId);
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
            : "The graph-room connection could not be opened.",
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
        detail: `Expected graph-room protocol ${ROOM_PROTOCOL_VERSION}, received ${protocolVersion ?? "no version"}.`,
      });
      return;
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
      const keptCurrentHead = Boolean(
        this.head && !shouldReplaceCollaborativeHead(this.head, message.head),
      );
      const rehydratedHead = keptCurrentHead ? this.head! : message.head;
      this.head = rehydratedHead;
      this.listeners.onRehydrate?.(rehydratedHead);
      if (keptCurrentHead) return;
      this.writeSends(this.outbox.finishHeadRehydration());
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
      this.removeParticipant(message.graph_room_session_id);
      return;
    }
    if (message.type === "execution.active") {
      this.activeExecution = message.execution;
      this.listeners.onActiveExecution?.(message.execution);
      return;
    }
    if (message.type === "execution.cleared") {
      if (
        this.activeExecution?.execution_id === message.execution_id ||
        this.activeExecution === null
      ) {
        this.activeExecution = null;
        this.listeners.onActiveExecution?.(null);
      }
      this.listeners.onExecutionCleared?.(message);
      return;
    }
    if (message.type === "graph.command.accepted") {
      this.applyAccepted(message);
      return;
    }
    if (message.type === "graph.command.receipt") {
      this.writeSends(this.outbox.applyReceipt(message));
      return;
    }
    if (message.type === "graph.command.rejected") {
      this.outbox.applyRejected(message);
    }
  }

  private applyReady(message: RoomReadyMessage): void {
    if (
      message.workspace_id !== this.workspaceId ||
      message.graph_id !== this.graphId
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
          "The room-ready message identified a different workspace or graph.",
      });
      return;
    }
    let ready = message;
    if (this.head && !shouldReplaceCollaborativeHead(this.head, message.head)) {
      ready = { ...message, head: this.head };
    }
    this.ready = ready;
    this.head = ready.head;
    this.capabilities = message.capabilities.capabilities;
    this.authorizationVersion = message.capabilities.authorization_version;
    this.participants = new Map(
      message.participants.map((participant) => [
        participant.graph_room_session_id,
        participant,
      ]),
    );
    this.presenceSequence = 0;
    this.lastPresenceSentAt = 0;
    this.activeExecution = message.active_execution;
    this.reconnectAttempts = 0;
    this.setFailure(null);
    this.setStatus("ready");
    this.listeners.onReady?.(ready);
    this.listeners.onActiveExecution?.(message.active_execution);
    this.emitPresenceChange();
    this.writeSends(this.outbox.finishHeadRehydration());
  }

  private upsertParticipant(participant: PresenceParticipant): void {
    this.participants.set(participant.graph_room_session_id, participant);
    this.emitPresenceChange();
  }

  private removeParticipant(sessionId: string): void {
    if (!this.participants.delete(sessionId)) return;
    this.emitPresenceChange();
  }

  private clearPresence(): void {
    if (this.participants.size === 0) return;
    this.participants.clear();
    this.emitPresenceChange();
  }

  private emitPresenceChange(): void {
    this.listeners.onPresenceChange?.(this.getParticipants());
  }

  private applyAccepted(message: GraphCommandAcceptedMessage): void {
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
      this.head = applyRoomCommandToHead(
        head,
        message.command,
        message.sequence,
      );
    } catch {
      this.outbox.requestHeadRefresh();
      return;
    }
    this.listeners.onCommandAccepted?.(message, { local });
    this.writeSends(this.outbox.afterHeadApplied());
  }

  private handleClose(code: number, reason: string): void {
    const classifiedReason = terminalReasonFromClose(code, reason);
    if (
      classifiedReason === "access_revoked" ||
      classifiedReason === "graph_deleted"
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
          reason || `The server closed the graph room (${classifiedReason}).`,
      });
      return;
    }
    if (this.intentionallyClosed) {
      this.setStatus("idle");
      return;
    }
    const recoveryReason: GraphRoomRecoveryReason =
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
      detail: reason || "The graph-room connection closed unexpectedly.",
    });
  }

  private recoverTraffic(failure: GraphRoomFailureDetail): void {
    this.setFailure(this.failureWithContext(failure));
    this.ready = null;
    this.capabilities = [];
    this.authorizationVersion = null;
    this.activeExecution = null;
    this.listeners.onActiveExecution?.(null);
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
  }

  private stopTraffic(
    reason: GraphRoomTerminalReason,
    failure?: GraphRoomFailureDetail,
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
      new GraphRoomCommandError(
        "",
        reason,
        `Graph room closed (${reason}). The displayed graph is not trusted for graph operations.`,
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

  private clearReconnectTimer(): void {
    if (this.reconnectTimer === null) return;
    clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  private setStatus(status: GraphRoomStatus): void {
    if (this.status === status) return;
    this.status = status;
    this.listeners.onStatusChange?.(status);
  }

  private setFailure(failure: GraphRoomFailure | null): void {
    this.lastFailure = failure;
    this.listeners.onFailureChange?.(failure);
  }

  private failureWithContext(
    failure: GraphRoomFailureDetail,
  ): GraphRoomFailure {
    return {
      workspaceId: this.workspaceId,
      graphId: this.graphId,
      graphRoomSessionId:
        this.getGraphRoomSessionId() ??
        this.lastFailure?.graphRoomSessionId ??
        null,
      ...failure,
    };
  }
}
