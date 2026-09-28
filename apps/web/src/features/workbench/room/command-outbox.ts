import { createUuid } from "@/features/workbench/model/uuid";

import {
  ROOM_COMMAND_QUEUE_CAP,
  ROOM_PROTOCOL_VERSION,
  type GraphCommandAcceptedMessage,
  type GraphCommandReceiptMessage,
  type GraphCommandRejectedMessage,
  type GraphCommandSubmitMessage,
  type RoomGraphCommand,
} from "./protocol";

export class GraphRoomCommandError extends Error {
  readonly errorCode: string;
  readonly commandId: string;

  constructor(commandId: string, errorCode: string, detail: string) {
    super(detail);
    this.name = "GraphRoomCommandError";
    this.commandId = commandId;
    this.errorCode = errorCode;
  }
}

export interface GraphRoomCommandResult {
  readonly receipt: GraphCommandReceiptMessage;
  readonly accepted: GraphCommandAcceptedMessage | null;
}

/**
 * The part of the confirmed collaborative head that decides whether a command
 * may be sent and whether a receipt is already reflected locally. The outbox
 * reads it and never owns it.
 */
export interface GraphRoomHeadPointer {
  readonly room_epoch: string;
  readonly collaboration_sequence: number;
}

/** A submit frame the driver must write to its transport. */
export interface OutgoingGraphCommand {
  readonly commandId: string;
  readonly message: GraphCommandSubmitMessage;
}

export interface GraphRoomCommandSubmission {
  readonly promise: Promise<GraphRoomCommandResult>;
  readonly sends: readonly OutgoingGraphCommand[];
}

interface QueuedCommand {
  readonly commandId: string;
  readonly command: RoomGraphCommand;
  readonly resolve: (result: GraphRoomCommandResult) => void;
  readonly reject: (error: Error) => void;
  sent: boolean;
  roomEpoch: string | null;
  observedSequence: number | null;
  accepted: GraphCommandAcceptedMessage | null;
  receipt: GraphCommandReceiptMessage | null;
}

export interface GraphRoomCommandOutboxOptions {
  /**
   * Read-only view of the confirmed head. Sending stops while it is null; the
   * driver owns head replacement.
   */
  readonly headPointer?: () => GraphRoomHeadPointer | null;
  /** Gate consulted before every send: policy plus transport readiness. */
  readonly canSend?: () => boolean;
  readonly createCommandId?: () => string;
  readonly onHeadRefreshRequired?: () => void;
  readonly onCommandRejected?: (message: GraphCommandRejectedMessage) => void;
}

/**
 * Correlates outgoing graph commands with the accepted / receipt / rejected
 * messages that come back: the FIFO queue, the single in-flight command, the
 * ids that mark a message as locally originated, and the drain gate that
 * pauses sending until the driver restores a full head snapshot.
 *
 * It never touches a transport, a timer, or the head itself. Each call returns
 * the submit frames the driver should write; the driver reports a write that
 * failed with `sendFailed`.
 */
export class GraphRoomCommandOutbox {
  private readonly headPointer: () => GraphRoomHeadPointer | null;
  private readonly canSend: () => boolean;
  private readonly createCommandId: () => string;
  private readonly onHeadRefreshRequired: (() => void) | undefined;
  private readonly onCommandRejected:
    ((message: GraphCommandRejectedMessage) => void) | undefined;

  private readonly queue: QueuedCommand[] = [];
  private inFlight: QueuedCommand | null = null;
  private readonly localCommandIds = new Set<string>();
  /** When true, do not send queued commands until a full snapshot lands. */
  private awaitingHeadRehydration = false;

  constructor(options: GraphRoomCommandOutboxOptions = {}) {
    this.headPointer = options.headPointer ?? (() => null);
    this.canSend = options.canSend ?? (() => true);
    this.createCommandId = options.createCommandId ?? createUuid;
    this.onHeadRefreshRequired = options.onHeadRefreshRequired;
    this.onCommandRejected = options.onCommandRejected;
  }

  /**
   * Queue a command, replacing unsent snapshot commands of the same kind.
   * The returned promise settles with the command's receipt.
   */
  submit(command: RoomGraphCommand): GraphRoomCommandSubmission {
    this.supersedeQueuedSnapshotCommand(command);
    if (this.queue.length + (this.inFlight ? 1 : 0) >= ROOM_COMMAND_QUEUE_CAP) {
      return {
        promise: Promise.reject(
          new GraphRoomCommandError(
            "",
            "queue_full",
            "Waiting to synchronize. Durable authoring is paused until the queue drains.",
          ),
        ),
        sends: [],
      };
    }

    const commandId = this.createCommandId();
    this.localCommandIds.add(commandId);
    const promise = new Promise<GraphRoomCommandResult>((resolve, reject) => {
      this.queue.push({
        commandId,
        command,
        resolve,
        reject,
        sent: false,
        roomEpoch: null,
        observedSequence: null,
        accepted: null,
        receipt: null,
      });
    });
    return { promise, sends: this.drainQueue() };
  }

  /**
   * Correlate an accepted message and report whether this client submitted the
   * command. The accepted payload is kept for the caller's promise even when
   * the head rejects the sequence, so a later replay receipt still reports it.
   */
  recordAccepted(message: GraphCommandAcceptedMessage): boolean {
    const local = this.localCommandIds.delete(message.command_id);
    if (this.inFlight?.commandId === message.command_id) {
      this.inFlight.accepted = message;
    }
    return local;
  }

  /** Settle the in-flight command once its receipt arrives. */
  applyReceipt(
    message: GraphCommandReceiptMessage,
  ): readonly OutgoingGraphCommand[] {
    const pending = this.inFlight;
    if (!pending || pending.commandId !== message.command_id) {
      return [];
    }
    this.localCommandIds.delete(message.command_id);
    pending.receipt = message;
    if (message.requires_head_rehydration || !this.headCoversReceipt(message)) {
      this.requestHeadRefresh();
      return [];
    }
    this.resolveInFlightReceipt(pending);
    return this.drainQueue();
  }

  /**
   * Re-check a held receipt after the driver applied an accepted command to
   * the head. Only a paused drain with a now-covered receipt is resumed here.
   */
  afterHeadApplied(): readonly OutgoingGraphCommand[] {
    const pendingReceipt = this.inFlight?.receipt;
    if (
      this.awaitingHeadRehydration &&
      pendingReceipt !== null &&
      pendingReceipt !== undefined &&
      this.headCoversReceipt(pendingReceipt)
    ) {
      return this.finishHeadRehydration();
    }
    return [];
  }

  /** A full snapshot landed: settle what it covers and resume the drain. */
  finishHeadRehydration(): readonly OutgoingGraphCommand[] {
    const pending = this.inFlight;
    if (pending?.receipt !== null && pending?.receipt !== undefined) {
      if (!this.headCoversReceipt(pending.receipt)) {
        this.awaitingHeadRehydration = true;
        this.onHeadRefreshRequired?.();
        return [];
      }
      this.resolveInFlightReceipt(pending);
    }
    this.awaitingHeadRehydration = false;
    return this.drainQueue();
  }

  /** Correlate a rejection and reject the caller's promise for it. */
  applyRejected(message: GraphCommandRejectedMessage): void {
    this.localCommandIds.delete(message.command_id);
    const pending = this.inFlight;
    if (!pending || pending.commandId !== message.command_id) {
      this.onCommandRejected?.(message);
      return;
    }
    // Do not advance collaboration_sequence from the rejection alone — that
    // skips applying a peer's accepted command at the same sequence, and lets
    // the queue drain with a document that never received the winner.
    // Pause drain until Workbench replaceHead() restores a full snapshot.
    this.awaitingHeadRehydration = true;
    this.inFlight = null;
    this.onCommandRejected?.(message);
    pending.reject(
      new GraphRoomCommandError(
        message.command_id,
        message.error_code,
        message.detail,
      ),
    );
  }

  /** Pause the drain and ask the driver for a full snapshot. */
  requestHeadRefresh(): void {
    this.awaitingHeadRehydration = true;
    this.onHeadRefreshRequired?.();
  }

  /** True when the held receipt is already reflected in the current head. */
  pendingReceiptIsCovered(): boolean {
    const pendingReceipt = this.inFlight?.receipt;
    if (pendingReceipt === null || pendingReceipt === undefined) return false;
    return this.headCoversReceipt(pendingReceipt);
  }

  /**
   * Put an interrupted in-flight command back at the front of the queue. Its
   * original epoch and observed sequence stay attached so the retry replays the
   * same submission under the server's idempotency contract.
   */
  interruptInFlight(): void {
    if (!this.inFlight) return;
    const interrupted = this.inFlight;
    this.inFlight = null;
    this.queue.unshift(interrupted);
  }

  /** Report that a returned frame could not be written; drop it from flight. */
  sendFailed(commandId: string, error: unknown): void {
    const pending = this.inFlight;
    if (!pending || pending.commandId !== commandId) return;
    this.inFlight = null;
    pending.reject(
      error instanceof Error
        ? error
        : new GraphRoomCommandError(
            commandId,
            "send_failed",
            "Failed to send graph command.",
          ),
    );
  }

  /** Reject every held command, in flight first. */
  rejectAll(error: Error): void {
    const interrupted = this.inFlight;
    this.inFlight = null;
    if (interrupted) {
      interrupted.reject(error);
    }
    const queued = this.queue.splice(0, this.queue.length);
    for (const item of queued) {
      item.reject(error);
    }
  }

  /** Forget which command ids were locally originated. */
  clearLocalCommands(): void {
    this.localCommandIds.clear();
  }

  private headCoversReceipt(message: GraphCommandReceiptMessage): boolean {
    const head = this.headPointer();
    return (
      head !== null &&
      head.room_epoch === message.current_room_epoch &&
      head.collaboration_sequence >= message.current_sequence
    );
  }

  private resolveInFlightReceipt(pending: QueuedCommand): void {
    const receipt = pending.receipt;
    if (this.inFlight !== pending || receipt === null) return;
    this.inFlight = null;
    pending.resolve({
      receipt,
      accepted: pending.accepted,
    });
  }

  private supersedeQueuedSnapshotCommand(command: RoomGraphCommand): void {
    if (
      command.kind !== "replace_presentation" &&
      command.kind !== "replace_document"
    ) {
      return;
    }
    for (let index = this.queue.length - 1; index >= 0; index -= 1) {
      const item = this.queue[index];
      if (!item || item.sent || item.command.kind !== command.kind) continue;
      this.queue.splice(index, 1);
      this.localCommandIds.delete(item.commandId);
      item.reject(
        new GraphRoomCommandError(
          item.commandId,
          "superseded",
          "A newer snapshot command replaced this queued command.",
        ),
      );
    }
  }

  private drainQueue(): readonly OutgoingGraphCommand[] {
    if (this.inFlight || this.awaitingHeadRehydration || !this.canSend()) {
      return [];
    }
    const head = this.headPointer();
    if (head === null) return [];
    const next = this.queue.shift();
    if (!next) return [];

    const roomEpoch = next.roomEpoch ?? head.room_epoch;
    const observedSequence =
      next.observedSequence ?? head.collaboration_sequence;
    this.inFlight = next;
    next.sent = true;
    next.roomEpoch = roomEpoch;
    next.observedSequence = observedSequence;
    const message: GraphCommandSubmitMessage = {
      protocol_version: ROOM_PROTOCOL_VERSION,
      type: "graph.command.submit",
      command_id: next.commandId,
      room_epoch: roomEpoch,
      observed_sequence: observedSequence,
      command: next.command,
    };
    return [{ commandId: next.commandId, message }];
  }
}
