import { collaborativeHeadFromLegacy } from "@/lib/api/graph-head";
// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  CLOSE_ACCESS_REVOKED,
  CLOSE_GRAPH_DELETED,
  CLOSE_PERMISSIONS_CHANGED,
  CLOSE_PROTOCOL_ERROR,
  CLOSE_SLOW_CONSUMER,
  ROOM_COMMAND_QUEUE_CAP,
} from "./protocol";
import {
  GraphRoomCommandError,
  GraphRoomSession,
  graphRoomWebSocketUrl,
  shouldReplaceCollaborativeHead,
} from "./graph-room-session";

const WORKSPACE_ID = "00000000-0000-4000-8000-000000000007";
const GRAPH_ID = "11111111-1111-4111-8111-111111111111";
const SESSION_ID = "22222222-2222-4222-8222-222222222222";
const ACTOR_ID = "00000000-0000-4000-8000-000000000001";
const ROOM_EPOCH = "33333333-3333-4333-8333-333333333333";

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readonly sent: string[] = [];
  readyState = FakeWebSocket.CONNECTING;
  close = vi.fn((code?: number, reason?: string) => {
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatch("close", { code: code ?? 1000, reason: reason ?? "" });
  });

  private listeners = new Map<string, Set<(event: unknown) => void>>();

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: (event: unknown) => void): void {
    const bucket = this.listeners.get(type) ?? new Set();
    bucket.add(listener);
    this.listeners.set(type, bucket);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.dispatch("open", {});
  }

  emitMessage(payload: unknown): void {
    this.dispatch("message", { data: JSON.stringify(payload) });
  }

  emitRawMessage(data: string): void {
    this.dispatch("message", { data });
  }

  emitClose(code: number, reason: string): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatch("close", { code, reason });
  }

  private dispatch(type: string, event: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }
}

function roomReady(overrides: Record<string, unknown> = {}) {
  return {
    protocol_version: 1,
    type: "room.ready",
    workspace_id: WORKSPACE_ID,
    graph_id: GRAPH_ID,
    graph_room_session_id: SESSION_ID,
    actor: {
      actor_id: ACTOR_ID,
      display_name: "Owner",
      color: "emerald",
    },
    capabilities: {
      capabilities: [
        "view_graph",
        "edit_graph",
        "join_graph_room",
        "publish_presence",
      ],
      authorization_version: 2,
    },
    head: {
      graph_id: GRAPH_ID,
      room_epoch: ROOM_EPOCH,
      collaboration_sequence: 4,
      checkpoint_sequence: 1,
      checkpoint_revision: 1,
      name: "Room graph",
      updated_at: "2026-08-07T10:00:00Z",
      nodes: [],
      edges: [],
    },
    participants: [
      {
        graph_room_session_id: SESSION_ID,
        actor: {
          actor_id: ACTOR_ID,
          display_name: "Owner",
          color: "emerald",
        },
        presence_sequence: 0,
        cursor: null,
        selected_node_ids: [],
        selected_edge_ids: [],
        activity: null,
        activity_target_ids: [],
        transient_node_positions: [],
      },
    ],
    active_execution: null,
    registry_marker: "builtin",
    ...overrides,
  };
}

function connectReadySession(
  options: ConstructorParameters<typeof GraphRoomSession>[0] = {
    workspaceId: WORKSPACE_ID,
    graphId: GRAPH_ID,
  },
): { session: GraphRoomSession; socket: FakeWebSocket } {
  const session = new GraphRoomSession({
    ...options,
    workspaceId: options.workspaceId ?? WORKSPACE_ID,
    graphId: options.graphId ?? GRAPH_ID,
    webSocketFactory: (url) => new FakeWebSocket(url) as unknown as WebSocket,
    reconnectDelayMs: options.reconnectDelayMs ?? 10_000,
  });
  session.connect();
  const socket = FakeWebSocket.instances.at(-1);
  if (!socket) throw new Error("expected websocket");
  socket.open();
  socket.emitMessage(roomReady());
  return { session, socket };
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("graphRoomWebSocketUrl", () => {
  it("builds a same-origin ws URL under API_BASE", () => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    expect(graphRoomWebSocketUrl(WORKSPACE_ID, GRAPH_ID)).toBe(
      `${protocol}//${window.location.host}/api/v1/workspaces/${WORKSPACE_ID}/graphs/${GRAPH_ID}/room`,
    );
  });
});

describe("shouldReplaceCollaborativeHead", () => {
  const base = collaborativeHeadFromLegacy({
    graph_id: GRAPH_ID,
    room_epoch: ROOM_EPOCH,
    collaboration_sequence: 5,
    checkpoint_sequence: 1,
    checkpoint_revision: 1,
    name: "Room graph",
    updated_at: "2026-08-07T10:00:00Z",
    nodes: [],
    edges: [],
  });

  it("accepts newer same-epoch snapshots and rejects older ones", () => {
    expect(shouldReplaceCollaborativeHead(null, base)).toBe(true);
    expect(
      shouldReplaceCollaborativeHead(base, {
        ...base,
        collaboration_sequence: 6,
      }),
    ).toBe(true);
    expect(
      shouldReplaceCollaborativeHead(base, {
        ...base,
        collaboration_sequence: 4,
        document: { ...base.document, presentation: { viewers: [], links: [], bindings: [], annotations: [] } },
      }),
    ).toBe(false);
  });
});

describe("GraphRoomSession", () => {
  it("connects with credentials path, parses room.ready, and tracks capabilities", () => {
    const onReady = vi.fn();
    const onStatusChange = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      onReady,
      onStatusChange,
    });

    expect(socket.url).toBe(graphRoomWebSocketUrl(WORKSPACE_ID, GRAPH_ID));
    expect(session.getStatus()).toBe("ready");
    expect(session.getAuthorizationVersion()).toBe(2);
    expect(session.getCapabilities()).toEqual([
      "view_graph",
      "edit_graph",
      "join_graph_room",
      "publish_presence",
    ]);
    expect(session.getHead()?.collaboration_sequence).toBe(4);
    expect(session.canSubmitCommands()).toBe(true);
    expect(onReady).toHaveBeenCalledOnce();
    expect(onStatusChange).toHaveBeenCalledWith("connecting");
    expect(onStatusChange).toHaveBeenCalledWith("ready");
  });

  it("tracks shared active execution discovery and clear", () => {
    const onActiveExecution = vi.fn();
    const onExecutionCleared = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      onActiveExecution,
      onExecutionCleared,
    });
    expect(session.getActiveExecution()).toBeNull();

    const summary = {
      execution_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      graph_revision: 1,
      status: "running",
      scope: "all",
      requested_node_ids: [],
      starter: {
        actor_id: ACTOR_ID,
        display_name: "Owner",
        color: "emerald",
      },
      active_node_id: null,
      overlays_compatible: true,
      cancellable: true,
    };
    socket.emitMessage({
      protocol_version: 1,
      type: "execution.active",
      execution: summary,
    });
    expect(session.getActiveExecution()).toEqual(summary);
    expect(onActiveExecution).toHaveBeenLastCalledWith(summary);

    socket.emitMessage({
      protocol_version: 1,
      type: "execution.cleared",
      execution_id: summary.execution_id,
      status: "succeeded",
      graph_revision: 1,
      error: null,
    });
    expect(session.getActiveExecution()).toBeNull();
    expect(onActiveExecution).toHaveBeenLastCalledWith(null);
    expect(onExecutionCleared).toHaveBeenCalledOnce();
  });

  it("submits a command and resolves on receipt after accepted", async () => {
    const commandIds = ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"];
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      createCommandId: () => commandIds.shift() ?? crypto.randomUUID(),
    });

    const pending = session.submitCommand({
      kind: "rename_graph",
      name: "Renamed",
      expected_name: "Room graph",
    });

    expect(socket.sent).toHaveLength(1);
    expect(JSON.parse(socket.sent[0]!)).toEqual({
      protocol_version: 1,
      type: "graph.command.submit",
      command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      room_epoch: ROOM_EPOCH,
      observed_sequence: 4,
      command: {
        kind: "rename_graph",
        name: "Renamed",
        expected_name: "Room graph",
      },
    });

    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.accepted",
      command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      room_epoch: ROOM_EPOCH,
      sequence: 5,
      actor: {
        actor_id: ACTOR_ID,
        display_name: "Owner",
        color: "emerald",
      },
      graph_room_session_id: SESSION_ID,
      command: {
        kind: "rename_graph",
        name: "Renamed",
        expected_name: "Room graph",
      },
    });
    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.receipt",
      command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      outcome: "accepted",
      accepted_room_epoch: ROOM_EPOCH,
      accepted_sequence: 5,
      current_room_epoch: ROOM_EPOCH,
      current_sequence: 5,
      deduplicated: false,
      requires_head_rehydration: false,
    });

    const result = await pending;
    expect(result.receipt.accepted_sequence).toBe(5);
    expect(result.accepted?.sequence).toBe(5);
    expect(session.getHead()?.collaboration_sequence).toBe(5);
  });

  it("retries an interrupted command idempotently before draining queued commands", async () => {
    const commandIds = [
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    ];
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      createCommandId: () => commandIds.shift() ?? crypto.randomUUID(),
    });

    const interrupted = session.submitCommand({
      kind: "rename_graph",
      name: "Renamed before disconnect",
      expected_name: "Room graph",
    });
    const queued = session.submitCommand({
      kind: "rename_graph",
      name: "Queued after reconnect",
      expected_name: "Renamed before disconnect",
    });
    const originalSubmission = JSON.parse(socket.sent[0]!);
    let interruptedSettled = false;
    void interrupted.then(
      () => {
        interruptedSettled = true;
      },
      () => {
        interruptedSettled = true;
      },
    );

    // The server may have committed the first submission even though neither
    // its accepted event nor receipt reached this socket.
    socket.emitClose(1006, "connection_lost");
    await Promise.resolve();
    expect(interruptedSettled).toBe(false);
    expect(session.getStatus()).toBe("unsynchronized");

    session.connect();
    const reconnectedSocket = FakeWebSocket.instances.at(-1);
    if (!reconnectedSocket || reconnectedSocket === socket) {
      throw new Error("expected a replacement websocket");
    }
    reconnectedSocket.open();
    const readyAfterCommit = roomReady();
    readyAfterCommit.head = {
      ...readyAfterCommit.head,
      collaboration_sequence: 5,
      name: "Renamed before disconnect",
    };
    reconnectedSocket.emitMessage(readyAfterCommit);

    expect(reconnectedSocket.sent).toHaveLength(1);
    // The HMAC-backed idempotency contract includes epoch and observed
    // sequence, so the retry must preserve the whole original submission.
    expect(JSON.parse(reconnectedSocket.sent[0]!)).toEqual(originalSubmission);

    reconnectedSocket.emitMessage({
      protocol_version: 1,
      type: "graph.command.receipt",
      command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      outcome: "idempotent_replay",
      accepted_room_epoch: ROOM_EPOCH,
      accepted_sequence: 5,
      current_room_epoch: ROOM_EPOCH,
      current_sequence: 5,
      deduplicated: true,
      requires_head_rehydration: false,
    });

    await expect(interrupted).resolves.toMatchObject({
      receipt: {
        command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        deduplicated: true,
      },
      accepted: null,
    });
    expect(reconnectedSocket.sent).toHaveLength(2);
    expect(JSON.parse(reconnectedSocket.sent[1]!)).toMatchObject({
      command_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      room_epoch: ROOM_EPOCH,
      observed_sequence: 5,
      command: {
        name: "Queued after reconnect",
      },
    });

    reconnectedSocket.emitMessage({
      protocol_version: 1,
      type: "graph.command.accepted",
      command_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      room_epoch: ROOM_EPOCH,
      sequence: 6,
      actor: {
        actor_id: ACTOR_ID,
        display_name: "Owner",
        color: "emerald",
      },
      graph_room_session_id: SESSION_ID,
      command: {
        kind: "rename_graph",
        name: "Queued after reconnect",
        expected_name: "Renamed before disconnect",
      },
    });
    reconnectedSocket.emitMessage({
      protocol_version: 1,
      type: "graph.command.receipt",
      command_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      outcome: "accepted",
      accepted_room_epoch: ROOM_EPOCH,
      accepted_sequence: 6,
      current_room_epoch: ROOM_EPOCH,
      current_sequence: 6,
      deduplicated: false,
      requires_head_rehydration: false,
    });
    await expect(queued).resolves.toMatchObject({
      receipt: { accepted_sequence: 6 },
    });
  });

  it("applies a delayed peer command before draining a replay receipt", async () => {
    const commandIds = [
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    ];
    const onHeadRefreshRequired = vi.fn();
    const onCommandAccepted = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      createCommandId: () => commandIds.shift() ?? crypto.randomUUID(),
      onHeadRefreshRequired,
      onCommandAccepted,
    });

    const interrupted = session.submitCommand({
      kind: "rename_graph",
      name: "Committed before disconnect",
      expected_name: "Room graph",
    });
    const queued = session.submitCommand({
      kind: "rename_graph",
      name: "After authoritative refresh",
      expected_name: "Peer rename",
    });
    socket.emitClose(1006, "connection_lost");

    session.connect();
    const reconnectedSocket = FakeWebSocket.instances.at(-1);
    if (!reconnectedSocket || reconnectedSocket === socket) {
      throw new Error("expected a replacement websocket");
    }
    reconnectedSocket.open();
    const readyAfterCommit = roomReady();
    readyAfterCommit.head = {
      ...readyAfterCommit.head,
      collaboration_sequence: 5,
      name: "Committed before disconnect",
    };
    reconnectedSocket.emitMessage(readyAfterCommit);
    expect(reconnectedSocket.sent).toHaveLength(1);

    // A peer commits sequence 6 after room.ready. Its accepted fanout is
    // delayed behind the private idempotent-replay receipt for sequence 5.
    reconnectedSocket.emitMessage({
      protocol_version: 1,
      type: "graph.command.receipt",
      command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      outcome: "idempotent_replay",
      accepted_room_epoch: ROOM_EPOCH,
      accepted_sequence: 5,
      current_room_epoch: ROOM_EPOCH,
      current_sequence: 6,
      deduplicated: true,
      requires_head_rehydration: false,
    });

    let interruptedSettled = false;
    void interrupted.finally(() => {
      interruptedSettled = true;
    });
    await Promise.resolve();
    expect(interruptedSettled).toBe(false);
    expect(session.getHead()?.collaboration_sequence).toBe(5);
    expect(session.getHead()?.name).toBe("Committed before disconnect");
    expect(onHeadRefreshRequired).toHaveBeenCalledOnce();
    expect(reconnectedSocket.sent).toHaveLength(1);

    reconnectedSocket.emitMessage({
      protocol_version: 1,
      type: "graph.command.accepted",
      command_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      room_epoch: ROOM_EPOCH,
      sequence: 6,
      actor: {
        actor_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        display_name: "Peer",
        color: "indigo",
      },
      graph_room_session_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
      command: {
        kind: "rename_graph",
        name: "Peer rename",
        expected_name: "Committed before disconnect",
      },
    });

    expect(session.getHead()?.collaboration_sequence).toBe(6);
    expect(session.getHead()?.name).toBe("Peer rename");
    expect(onCommandAccepted).toHaveBeenLastCalledWith(
      expect.objectContaining({ sequence: 6 }),
      { local: false },
    );
    await expect(interrupted).resolves.toMatchObject({
      receipt: {
        accepted_sequence: 5,
        current_sequence: 6,
      },
    });
    expect(interruptedSettled).toBe(true);
    expect(reconnectedSocket.sent).toHaveLength(2);
    expect(JSON.parse(reconnectedSocket.sent[1]!)).toMatchObject({
      command_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      observed_sequence: 6,
      command: {
        name: "After authoritative refresh",
        expected_name: "Peer rename",
      },
    });
    queued.catch(() => undefined);
    session.disconnect();
  });

  it("pauses command drain and requests a refresh when an accepted sequence has a gap", async () => {
    const onCommandAccepted = vi.fn();
    const onHeadRefreshRequired = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      createCommandId: () => "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      onCommandAccepted,
      onHeadRefreshRequired,
    });
    const headBeforeGap = session.getHead();

    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.accepted",
      command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      room_epoch: ROOM_EPOCH,
      sequence: 6,
      actor: {
        actor_id: ACTOR_ID,
        display_name: "Owner",
        color: "emerald",
      },
      graph_room_session_id: SESSION_ID,
      command: {
        kind: "rename_graph",
        name: "Skipped rename",
        expected_name: "Room graph",
      },
    });

    expect(session.getHead()).toBe(headBeforeGap);
    expect(session.getHead()?.name).toBe("Room graph");
    expect(session.getHead()?.collaboration_sequence).toBe(4);
    expect(onCommandAccepted).not.toHaveBeenCalled();
    expect(onHeadRefreshRequired).toHaveBeenCalledOnce();

    const pending = session.submitCommand({
      kind: "rename_graph",
      name: "Wait for refresh",
      expected_name: "Room graph",
    });
    expect(socket.sent).toHaveLength(0);
    session.disconnect();
    await expect(pending).rejects.toMatchObject({ errorCode: "disconnected" });
  });

  it("ignores a stale accepted command while retaining in-flight correlation", async () => {
    const commandId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
    const onCommandAccepted = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      createCommandId: () => commandId,
      onCommandAccepted,
    });
    const pending = session.submitCommand({
      kind: "rename_graph",
      name: "Local rename",
      expected_name: "Room graph",
    });
    const headBeforeStaleAccept = session.getHead();

    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.accepted",
      command_id: commandId,
      room_epoch: ROOM_EPOCH,
      sequence: 3,
      actor: {
        actor_id: ACTOR_ID,
        display_name: "Owner",
        color: "emerald",
      },
      graph_room_session_id: SESSION_ID,
      command: {
        kind: "rename_graph",
        name: "Stale rename",
        expected_name: "Older graph name",
      },
    });

    expect(session.getHead()).toBe(headBeforeStaleAccept);
    expect(session.getHead()?.name).toBe("Room graph");
    expect(onCommandAccepted).not.toHaveBeenCalled();

    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.receipt",
      command_id: commandId,
      outcome: "idempotent_replay",
      accepted_room_epoch: ROOM_EPOCH,
      accepted_sequence: 3,
      current_room_epoch: ROOM_EPOCH,
      current_sequence: 4,
      deduplicated: true,
      requires_head_rehydration: false,
    });

    const result = await pending;
    expect(result.accepted?.sequence).toBe(3);
    expect(session.getHead()?.name).toBe("Room graph");
    expect(session.getHead()?.collaboration_sequence).toBe(4);
  });

  it("keeps an accepted head when a stale room.ready arrives during reconnect", () => {
    const onReady = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      onReady,
    });

    socket.emitClose(1006, "connection_lost");
    session.connect();
    const reconnectedSocket = FakeWebSocket.instances.at(-1);
    if (!reconnectedSocket || reconnectedSocket === socket) {
      throw new Error("expected a replacement websocket");
    }
    reconnectedSocket.open();
    reconnectedSocket.emitMessage({
      protocol_version: 1,
      type: "graph.command.accepted",
      command_id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      room_epoch: ROOM_EPOCH,
      sequence: 5,
      actor: {
        actor_id: ACTOR_ID,
        display_name: "Owner",
        color: "emerald",
      },
      graph_room_session_id: SESSION_ID,
      command: {
        kind: "rename_graph",
        name: "Accepted during reconnect",
        expected_name: "Room graph",
      },
    });
    reconnectedSocket.emitMessage(roomReady());

    expect(session.getHead()?.name).toBe("Accepted during reconnect");
    expect(session.getHead()?.collaboration_sequence).toBe(5);
    const reconnectReady = onReady.mock.calls.at(-1)?.[0];
    expect(reconnectReady?.head).toBe(session.getHead());
    expect(reconnectReady?.head.name).toBe("Accepted during reconnect");
    expect(reconnectReady?.head.collaboration_sequence).toBe(5);
  });

  it("rejects a command when the server rejects it", async () => {
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      createCommandId: () => "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    });

    const pending = session.submitCommand({
      kind: "rename_graph",
      name: "Nope",
      expected_name: "Wrong",
    });
    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.rejected",
      command_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      error_code: "field_conflict",
      detail: "Name changed elsewhere.",
      current_room_epoch: ROOM_EPOCH,
      current_sequence: 4,
    });

    await expect(pending).rejects.toMatchObject({
      name: "GraphRoomCommandError",
      errorCode: "field_conflict",
    });
  });

  it("ignores stale replaceHead snapshots after a newer WebSocket accept", async () => {
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
    });

    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.accepted",
      command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      room_epoch: ROOM_EPOCH,
      sequence: 5,
      actor: {
        actor_id: ACTOR_ID,
        display_name: "Owner",
        color: "emerald",
      },
      graph_room_session_id: SESSION_ID,
      command: {
        kind: "replace_presentation",
        presentation: {
          viewers: [
            {
              id: "artifact-viewer-1",
              position: { x: 10, y: 20 },
              layout: null,
              mode: null,
            },
          ],
          links: [],
          bindings: [],
          annotations: [],
        },
      },
    });
    expect(session.getHead()?.collaboration_sequence).toBe(5);
    expect(session.getHead()?.document.presentation?.viewers).toHaveLength(1);

    session.replaceHead(collaborativeHeadFromLegacy({
      graph_id: GRAPH_ID,
      room_epoch: ROOM_EPOCH,
      collaboration_sequence: 4,
      checkpoint_sequence: 1,
      checkpoint_revision: 1,
      name: "Room graph",
      updated_at: "2026-08-07T10:00:00Z",
      nodes: [],
      edges: [],
      presentation: { viewers: [], links: [], bindings: [] },
    }));

    expect(session.getHead()?.collaboration_sequence).toBe(5);
    expect(session.getHead()?.document.presentation?.viewers).toHaveLength(1);
  });

  it("keeps a rehydrated epoch when an old-epoch checkpoint response arrives late", async () => {
    const commandId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      createCommandId: () => commandId,
    });
    const command = {
      kind: "replace_document" as const,
      name: "Checkpointed in E1",
      document: {
        schema_version: 7 as const,
        nodes: [],
        edges: [],
        origins: [],
        presentation: {
          viewers: [],
          links: [],
          bindings: [],
          annotations: [],
        },
      },
    };
    const submitted = session.submitCommand(command);
    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.accepted",
      command_id: commandId,
      room_epoch: ROOM_EPOCH,
      sequence: 5,
      actor: {
        actor_id: ACTOR_ID,
        display_name: "Owner",
        color: "emerald",
      },
      graph_room_session_id: SESSION_ID,
      command,
    });
    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.receipt",
      command_id: commandId,
      outcome: "accepted",
      accepted_room_epoch: ROOM_EPOCH,
      accepted_sequence: 5,
      current_room_epoch: ROOM_EPOCH,
      current_sequence: 5,
      deduplicated: false,
      requires_head_rehydration: false,
    });
    await submitted;

    const resetEpoch = "44444444-4444-4444-8444-444444444444";
    const resetHead = {
      graph_id: GRAPH_ID,
      room_epoch: resetEpoch,
      collaboration_sequence: 0,
      checkpoint_sequence: 0,
      checkpoint_revision: 3,
      name: "Authoritative E2",
      updated_at: "2026-08-07T11:00:00Z",
      nodes: [],
      edges: [],
      presentation: {
        viewers: [{
          id: "e2-viewer",
          position: { x: 30, y: 40 },
          layout: null,
          mode: null,
        }],
        links: [],
        bindings: [],
        annotations: [],
      },
    };
    socket.emitMessage({
      protocol_version: 1,
      type: "room.rehydrate",
      reason: "epoch_reset",
      head: resetHead,
    });

    const effectiveHead = session.reconcileCheckpointHead(collaborativeHeadFromLegacy({
      graph_id: GRAPH_ID,
      room_epoch: ROOM_EPOCH,
      collaboration_sequence: 5,
      checkpoint_sequence: 5,
      checkpoint_revision: 2,
      name: "Checkpointed in E1",
      updated_at: "2026-08-07T10:30:00Z",
      nodes: [],
      edges: [],
      presentation: {
        viewers: [],
        links: [],
        bindings: [],
        annotations: [],
      },
    }), ROOM_EPOCH);

    expect(effectiveHead).toEqual(collaborativeHeadFromLegacy(resetHead));
    expect(session.getHead()).toEqual(collaborativeHeadFromLegacy(resetHead));
  });

  it("pauses drain on head_conflict until replaceHead, and still applies peer accept", async () => {
    const commandIds = [
      "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    ];
    const onHeadRefreshRequired = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      createCommandId: () => commandIds.shift() ?? crypto.randomUUID(),
      onHeadRefreshRequired,
    });

    const conflicting = session.submitCommand({
      kind: "replace_presentation",
      presentation: { viewers: [], links: [], bindings: [], annotations: [] },
    });
    expect(socket.sent).toHaveLength(1);

    const queued = session.submitCommand({
      kind: "rename_graph",
      name: "After conflict",
      expected_name: "Room graph",
    });
    expect(socket.sent).toHaveLength(1);

    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.rejected",
      command_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      error_code: "head_conflict",
      detail: "Collaborative head moved: expected sequence 4, actual 5.",
      current_room_epoch: ROOM_EPOCH,
      current_sequence: 5,
    });
    await expect(conflicting).rejects.toMatchObject({
      errorCode: "head_conflict",
    });
    // Rejection alone must not advance the confirmed sequence.
    expect(session.getHead()?.collaboration_sequence).toBe(4);
    expect(socket.sent).toHaveLength(1);

    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.accepted",
      command_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
      room_epoch: ROOM_EPOCH,
      sequence: 5,
      actor: {
        actor_id: ACTOR_ID,
        display_name: "Owner",
        color: "emerald",
      },
      graph_room_session_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
      command: {
        kind: "rename_graph",
        name: "Peer rename",
        expected_name: "Room graph",
      },
    });
    expect(session.getHead()?.collaboration_sequence).toBe(5);
    expect(session.getHead()?.name).toBe("Peer rename");
    // Still paused until a full snapshot lands.
    expect(socket.sent).toHaveLength(1);

    session.replaceHead({
      ...session.getHead()!,
      collaboration_sequence: 5,
      name: "Peer rename",
    });
    expect(socket.sent).toHaveLength(2);
    expect(JSON.parse(socket.sent[1]!)).toMatchObject({
      type: "graph.command.submit",
      observed_sequence: 5,
      command: {
        kind: "rename_graph",
        name: "After conflict",
      },
    });
    queued.catch(() => undefined);
    expect(onHeadRefreshRequired).not.toHaveBeenCalled();
  });

  it("coalesces unsent replace_presentation commands", async () => {
    const commandIds = [
      "ffffffff-ffff-4fff-8fff-ffffffffffff",
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
    ];
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      createCommandId: () => commandIds.shift() ?? crypto.randomUUID(),
    });

    const first = session.submitCommand({
      kind: "replace_presentation",
      presentation: {
        viewers: [{ id: "artifact-viewer-1", position: { x: 1, y: 2 } }],
        links: [],
        bindings: [],
        annotations: [],
      },
    });
    expect(socket.sent).toHaveLength(1);

    const second = session.submitCommand({
      kind: "replace_presentation",
      presentation: {
        viewers: [{ id: "artifact-viewer-2", position: { x: 3, y: 4 } }],
        links: [],
        bindings: [],
        annotations: [],
      },
    });
    const third = session.submitCommand({
      kind: "replace_presentation",
      presentation: {
        viewers: [{ id: "artifact-viewer-3", position: { x: 5, y: 6 } }],
        links: [],
        bindings: [],
        annotations: [],
      },
    });
    await expect(second).rejects.toMatchObject({ errorCode: "superseded" });
    expect(socket.sent).toHaveLength(1);

    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.accepted",
      command_id: "ffffffff-ffff-4fff-8fff-ffffffffffff",
      room_epoch: ROOM_EPOCH,
      sequence: 5,
      actor: {
        actor_id: ACTOR_ID,
        display_name: "Owner",
        color: "emerald",
      },
      graph_room_session_id: SESSION_ID,
      command: {
        kind: "replace_presentation",
        presentation: {
          viewers: [{ id: "artifact-viewer-1", position: { x: 1, y: 2 } }],
          links: [],
          bindings: [],
          annotations: [],
        },
      },
    });
    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.receipt",
      command_id: "ffffffff-ffff-4fff-8fff-ffffffffffff",
      outcome: "accepted",
      accepted_room_epoch: ROOM_EPOCH,
      accepted_sequence: 5,
      current_room_epoch: ROOM_EPOCH,
      current_sequence: 5,
      deduplicated: false,
      requires_head_rehydration: false,
    });
    await first;
    expect(socket.sent).toHaveLength(2);
    expect(JSON.parse(socket.sent[1]!)).toMatchObject({
      observed_sequence: 5,
      command: {
        kind: "replace_presentation",
        presentation: {
          viewers: [{ id: "artifact-viewer-3", position: { x: 5, y: 6 } }],
        },
      },
    });
    third.catch(() => undefined);
  });

  it("does not let a stale same-epoch rehydrate rewind an accepted head", () => {
    const onRehydrate = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      onRehydrate,
    });

    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.accepted",
      command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      room_epoch: ROOM_EPOCH,
      sequence: 5,
      actor: {
        actor_id: ACTOR_ID,
        display_name: "Owner",
        color: "emerald",
      },
      graph_room_session_id: SESSION_ID,
      command: {
        kind: "rename_graph",
        name: "Accepted after snapshot",
        expected_name: "Room graph",
      },
    });
    const acceptedHead = session.getHead();

    socket.emitMessage({
      protocol_version: 1,
      type: "room.rehydrate",
      reason: "epoch_reset",
      head: roomReady().head,
    });

    expect(session.getHead()).toBe(acceptedHead);
    expect(session.getHead()?.collaboration_sequence).toBe(5);
    expect(session.getHead()?.name).toBe("Accepted after snapshot");
    expect(onRehydrate).toHaveBeenCalledWith(acceptedHead);
  });

  it("replaces collaborative head state on room.rehydrate", () => {
    const onRehydrate = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      onRehydrate,
    });
    const nextEpoch = "44444444-4444-4444-8444-444444444444";
    const head = {
      graph_id: GRAPH_ID,
      room_epoch: nextEpoch,
      collaboration_sequence: 1,
      checkpoint_sequence: 2,
      checkpoint_revision: 2,
      name: "Reset",
      updated_at: "2026-08-07T11:00:00Z",
      nodes: [],
      edges: [],
    };

    socket.emitMessage({
      protocol_version: 1,
      type: "room.rehydrate",
      reason: "epoch_reset",
      head,
    });

    expect(session.getHead()).toEqual(collaborativeHeadFromLegacy(head));
    expect(onRehydrate).toHaveBeenCalledWith(collaborativeHeadFromLegacy(head));
  });

  it.each([
    {
      code: CLOSE_ACCESS_REVOKED,
      reason: "access_revoked",
      label: "access_revoked",
    },
    {
      code: CLOSE_GRAPH_DELETED,
      reason: "graph_deleted",
      label: "graph_deleted",
    },
  ] as const)(
    "stops traffic and exposes $label without reconnecting",
    async ({ code, reason, label }) => {
      vi.useFakeTimers();
      const onTerminalClose = vi.fn();
      const { session, socket } = connectReadySession({
        workspaceId: WORKSPACE_ID,
        graphId: GRAPH_ID,
        onTerminalClose,
        createCommandId: () => "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      });

      const pending = session.submitCommand({
        kind: "rename_graph",
        name: "Pending",
        expected_name: "Room graph",
      });
      const socketsBeforeClose = FakeWebSocket.instances.length;
      socket.emitClose(code, reason);

      expect(session.getStatus()).toBe("stopped");
      expect(session.getTerminalReason()).toBe(label);
      expect(session.canSubmitCommands()).toBe(false);
      expect(onTerminalClose).toHaveBeenCalledWith(label);
      await expect(pending).rejects.toBeInstanceOf(GraphRoomCommandError);

      await vi.advanceTimersByTimeAsync(20_000);
      expect(FakeWebSocket.instances.length).toBe(socketsBeforeClose);
      await expect(
        session.submitCommand({
          kind: "rename_graph",
          name: "Again",
          expected_name: "Room graph",
        }),
      ).rejects.toMatchObject({ errorCode: "not_ready" });
    },
  );

  it.each([
    [CLOSE_PERMISSIONS_CHANGED, "permissions_changed"],
    [CLOSE_PROTOCOL_ERROR, "protocol_error"],
    [CLOSE_SLOW_CONSUMER, "slow_consumer"],
  ] as const)("rehydrates after recoverable %s room closure", async (code, reason) => {
    vi.useFakeTimers();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      reconnectDelayMs: 10,
    });

    socket.emitClose(code, reason);

    expect(session.getStatus()).toBe("unsynchronized");
    expect(session.getTerminalReason()).toBeNull();
    expect(session.getHead()?.graph_id).toBe(GRAPH_ID);
    expect(session.canSubmitCommands()).toBe(false);
    expect(session.getLastFailure()).toMatchObject({ reason, retryable: true });

    await vi.advanceTimersByTimeAsync(10);
    const reconnect = FakeWebSocket.instances.at(-1)!;
    reconnect.open();
    reconnect.emitMessage(roomReady({
      head: { ...roomReady().head, collaboration_sequence: 5 },
    }));

    expect(session.getStatus()).toBe("ready");
    expect(session.getLastFailure()).toBeNull();
    expect(session.getHead()?.collaboration_sequence).toBe(5);
  });

  it("ignores unknown additive version-1 server messages", () => {
    const { session, socket } = connectReadySession();

    socket.emitMessage({
      protocol_version: 1,
      type: "room.future_addition",
      value: "ignored",
    });

    expect(session.getStatus()).toBe("ready");
    expect(session.getLastFailure()).toBeNull();
  });

  it("reconnects after malformed known messages but stops for incompatible versions", () => {
    const { session, socket } = connectReadySession();

    socket.emitMessage({ protocol_version: 1, type: "room.ready" });
    expect(session.getStatus()).toBe("unsynchronized");
    expect(session.getLastFailure()).toMatchObject({
      reason: "protocol_error",
      messageType: "room.ready",
    });

    const incompatible = connectReadySession();
    incompatible.socket.emitMessage({ protocol_version: 2, type: "room.ready" });
    expect(incompatible.session.getStatus()).toBe("stopped");
    expect(incompatible.session.getTerminalReason()).toBe("protocol_incompatible");
    expect(incompatible.session.getLastFailure()).toMatchObject({
      retryable: false,
      protocolVersion: 2,
    });
  });

  it("reconnects after malformed JSON without logging the payload", () => {
    const { session, socket } = connectReadySession();

    socket.emitRawMessage('{"protocol_version":1,"type":"room.ready"');

    expect(session.getStatus()).toBe("unsynchronized");
    expect(session.getLastFailure()).toMatchObject({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      graphRoomSessionId: SESSION_ID,
      reason: "protocol_error",
      side: "server",
      phase: "receive",
      messageType: null,
    });
    expect(session.getLastFailure()?.detail).not.toContain("room.ready");
  });

  it("bounds reconnect attempts and allows a manual retry", async () => {
    vi.useFakeTimers();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      reconnectDelayMs: 10,
      maxReconnectAttempts: 2,
    });

    socket.emitClose(1006, "");
    await vi.advanceTimersByTimeAsync(10);
    FakeWebSocket.instances.at(-1)!.emitClose(1006, "");
    await vi.advanceTimersByTimeAsync(20);
    FakeWebSocket.instances.at(-1)!.emitClose(1006, "");

    expect(session.getStatus()).toBe("stopped");
    expect(session.getTerminalReason()).toBe("reconnect_exhausted");
    expect(session.getLastFailure()).toMatchObject({ retryable: true });

    const socketCount = FakeWebSocket.instances.length;
    session.retry();
    expect(session.getStatus()).toBe("reconnecting");
    expect(FakeWebSocket.instances).toHaveLength(socketCount + 1);
  });

  it("caps the in-memory command queue", async () => {
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      createCommandId: () => crypto.randomUUID(),
    });

    const first = session.submitCommand({
      kind: "rename_graph",
      name: "First",
      expected_name: "Room graph",
    });
    expect(socket.sent).toHaveLength(1);

    const queued = Array.from({ length: ROOM_COMMAND_QUEUE_CAP - 1 }, (_, index) =>
      session.submitCommand({
        kind: "rename_graph",
        name: `Queued ${index}`,
        expected_name: "Room graph",
      }),
    );
    await expect(
      session.submitCommand({
        kind: "rename_graph",
        name: "Overflow",
        expected_name: "Room graph",
      }),
    ).rejects.toMatchObject({ errorCode: "queue_full" });

    socket.emitMessage({
      protocol_version: 1,
      type: "graph.command.rejected",
      command_id: JSON.parse(socket.sent[0]!).command_id,
      error_code: "command_rejected",
      detail: "stop first",
      current_room_epoch: ROOM_EPOCH,
      current_sequence: 4,
    });
    await expect(first).rejects.toBeInstanceOf(GraphRoomCommandError);
    for (const item of queued) {
      item.catch(() => undefined);
    }
    session.disconnect();
  });

  it("tracks remote presence join/update/leave and publishes throttled updates", () => {
    const onPresenceChange = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      onPresenceChange,
    });

    expect(session.getParticipants()).toHaveLength(1);
    expect(session.canPublishPresence()).toBe(true);
    expect(session.getRemoteParticipants()).toHaveLength(0);

    const remoteId = "99999999-9999-4999-8999-999999999999";
    socket.emitMessage({
      protocol_version: 1,
      type: "presence.join",
      participant: {
        graph_room_session_id: remoteId,
        actor: {
          actor_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          display_name: "Editor",
          color: "indigo",
        },
        presence_sequence: 0,
        cursor: null,
        selected_node_ids: [],
        selected_edge_ids: [],
        activity: null,
        activity_target_ids: [],
        transient_node_positions: [],
      },
    });
    expect(session.getRemoteParticipants()).toHaveLength(1);

    socket.emitMessage({
      protocol_version: 1,
      type: "presence.update",
      participant: {
        graph_room_session_id: remoteId,
        actor: {
          actor_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
          display_name: "Editor",
          color: "indigo",
        },
        presence_sequence: 3,
        cursor: { x: 10, y: 20 },
        selected_node_ids: ["n1"],
        selected_edge_ids: [],
        activity: "editing_node",
        activity_target_ids: ["n1"],
        transient_node_positions: [],
      },
    });
    expect(session.getRemoteParticipants()[0]?.cursor).toEqual({ x: 10, y: 20 });
    expect(session.getRemoteParticipants()[0]?.selected_node_ids).toEqual(["n1"]);

    expect(session.publishPresence({ cursor: { x: 1, y: 2 } })).toBe(true);
    expect(JSON.parse(socket.sent.at(-1)!)).toMatchObject({
      type: "presence.update",
      presence_sequence: 1,
      cursor: { x: 1, y: 2 },
    });
    expect(session.publishPresence({ cursor: { x: 3, y: 4 } })).toBe(false);

    socket.emitMessage({
      protocol_version: 1,
      type: "presence.leave",
      graph_room_session_id: remoteId,
    });
    expect(session.getRemoteParticipants()).toHaveLength(0);
    expect(onPresenceChange).toHaveBeenCalled();
  });

  it("clears presence on terminal close and ignores heartbeats", () => {
    const onPresenceChange = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      graphId: GRAPH_ID,
      onPresenceChange,
    });
    expect(session.getParticipants()).toHaveLength(1);
    socket.emitMessage({
      protocol_version: 1,
      type: "room.heartbeat",
      authorization_version: 2,
    });
    expect(session.getStatus()).toBe("ready");
    socket.emitClose(CLOSE_ACCESS_REVOKED, "access_revoked");
    expect(session.getStatus()).toBe("stopped");
    expect(session.getParticipants()).toHaveLength(0);
    expect(onPresenceChange).toHaveBeenCalled();
  });
});
