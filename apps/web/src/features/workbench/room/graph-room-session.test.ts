// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ActiveRunSummary,
  CollaborativeHead,
  GraphDefinition,
  SavedGraphDocument,
} from "@/lib/api";

import {
  CLOSE_ACCESS_REVOKED,
  CLOSE_PERMISSIONS_CHANGED,
  CLOSE_PROJECT_DELETED,
  CLOSE_PROTOCOL_ERROR,
  CLOSE_SLOW_CONSUMER,
  ROOM_COMMAND_QUEUE_CAP,
  type RoomInstanceKey,
  type RoomInstanceState,
  type RoomProjectCommand,
} from "./protocol";
import {
  ProjectRoomCommandError,
  ProjectRoomSession,
  projectRoomWebSocketUrl,
  shouldReplaceCollaborativeHead,
  type ProjectRoomSessionOptions,
} from "./graph-room-session";

const WORKSPACE_ID = "00000000-0000-4000-8000-000000000007";
const PROJECT_ID = "99999999-9999-4999-8999-999999999991";
/** The Graph this client has open in the canvas. */
const GRAPH_ID = "11111111-1111-4111-8111-111111111111";
/** Another Graph of the same Project, which this client is not looking at. */
const OTHER_GRAPH_ID = "66666666-6666-4666-8666-666666666666";
/** A Graph this client's head does not hold at all. */
const UNKNOWN_GRAPH_ID = "77777777-7777-4777-8777-777777777777";
const SESSION_ID = "22222222-2222-4222-8222-222222222222";
const ACTOR_ID = "00000000-0000-4000-8000-000000000001";
const ROOM_EPOCH = "33333333-3333-4333-8333-333333333333";
const RESET_EPOCH = "44444444-4444-4444-8444-444444444444";

const ACTOR = {
  actor_id: ACTOR_ID,
  display_name: "Owner",
  color: "emerald",
};

function graphDocument(
  overrides: Partial<SavedGraphDocument> = {},
): SavedGraphDocument {
  return {
    schema_version: 7,
    nodes: [],
    edges: [],
    origins: [],
    presentation: { viewers: [], links: [], bindings: [], annotations: [] },
    ...overrides,
  };
}

function graph(
  graphId: string,
  name: string,
  document: SavedGraphDocument = graphDocument(),
): GraphDefinition {
  return { id: graphId, name, document };
}

/**
 * The head of a Project: every Graph it holds, each with its own document.
 * `name` is the Project's name, which is why a Project-level rename moves it.
 */
function projectHead(
  overrides: Partial<CollaborativeHead> = {},
): CollaborativeHead {
  return {
    project_id: PROJECT_ID,
    room_epoch: ROOM_EPOCH,
    collaboration_sequence: 4,
    checkpoint_sequence: 1,
    checkpoint_revision: 1,
    name: "Room project",
    updated_at: "2026-08-07T10:00:00Z",
    document: {
      graphs: [graph(GRAPH_ID, "Main"), graph(OTHER_GRAPH_ID, "Second")],
    },
    ...overrides,
  };
}

function headGraph(
  head: CollaborativeHead | null,
  graphId: string,
): GraphDefinition | undefined {
  return head?.document.graphs.find((candidate) => candidate.id === graphId);
}

function viewers(head: CollaborativeHead | null, graphId: string) {
  return headGraph(head, graphId)?.document.presentation?.viewers ?? [];
}

/** The Graph this head is showing, used to prove a peer left it alone. */
function openGraphDocument(head: CollaborativeHead | null) {
  return headGraph(head, GRAPH_ID)?.document;
}

function renameProject(
  name: string,
  expectedName = "Room project",
): RoomProjectCommand {
  return { kind: "rename_project", name, expected_name: expectedName };
}

function renameGraph(
  graphId: string,
  name: string,
  expectedName: string,
): RoomProjectCommand {
  return {
    kind: "rename_graph",
    graph_id: graphId,
    name,
    expected_name: expectedName,
  };
}

function replacePresentation(
  graphId: string,
  viewerIds: readonly string[],
): RoomProjectCommand {
  return {
    kind: "in_graph",
    graph_id: graphId,
    command: {
      kind: "replace_presentation",
      presentation: {
        viewers: viewerIds.map((id, index) => ({
          id,
          position: { x: index + 1, y: index + 2 },
          layout: null,
          mode: null,
        })),
        links: [],
        bindings: [],
        annotations: [],
      },
    },
  };
}

function replaceGraphDocument(
  graphId: string,
  document: SavedGraphDocument,
): RoomProjectCommand {
  return {
    kind: "in_graph",
    graph_id: graphId,
    command: { kind: "replace_document", document },
  };
}

function participant(
  sessionId: string,
  displayName: string,
  overrides: Record<string, unknown> = {},
) {
  return {
    project_room_session_id: sessionId,
    actor: {
      actor_id:
        sessionId === SESSION_ID
          ? ACTOR_ID
          : "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      display_name: displayName,
      color: sessionId === SESSION_ID ? "emerald" : "indigo",
    },
    graph_id: GRAPH_ID,
    presence_sequence: 0,
    cursor: null,
    selected_node_ids: [],
    selected_edge_ids: [],
    activity: null,
    activity_target_ids: [],
    transient_node_positions: [],
    ...overrides,
  };
}

/** One of the Project's open Runs, as the room carries it. */
function activeRun(
  runId: string,
  graphId: string,
  overrides: Partial<ActiveRunSummary> = {},
): ActiveRunSummary {
  return {
    run_id: runId,
    graph_id: graphId,
    targets: [{ node_id: "n1", call_path: [] }],
    starter: ACTOR,
    started_at: "2026-08-07T10:00:00Z",
    cancellable: true,
    ...overrides,
  };
}

/** Derived state of one node instance, as the room publishes it. */
function instanceState(
  graphId: string,
  nodeId: string,
  state: RoomInstanceState["state"],
  overrides: Partial<RoomInstanceState> = {},
): RoomInstanceState {
  return {
    project_id: PROJECT_ID,
    graph_id: graphId,
    call_path: [],
    node_id: nodeId,
    map_index: null,
    state,
    fingerprint: `fp-${graphId}-${nodeId}-${state}`,
    last_result_fingerprint: null,
    error: null,
    ...overrides,
  };
}

function instanceKey(
  graphId: string,
  nodeId: string,
  mapIndex: number | null = null,
): RoomInstanceKey {
  return {
    project_id: PROJECT_ID,
    graph_id: graphId,
    call_path: [],
    node_id: nodeId,
    map_index: mapIndex,
  };
}

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

  lastSent(): Record<string, unknown> {
    const raw = this.sent.at(-1);
    if (raw === undefined) throw new Error("expected a sent frame");
    return JSON.parse(raw) as Record<string, unknown>;
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
    project_id: PROJECT_ID,
    project_room_session_id: SESSION_ID,
    actor: ACTOR,
    capabilities: {
      capabilities: [
        "view_project",
        "edit_project",
        "join_project_room",
        "publish_presence",
      ],
      authorization_version: 2,
    },
    head: projectHead(),
    participants: [participant(SESSION_ID, "Owner")],
    active_runs: [],
    instances: [],
    registry_marker: "builtin",
    ...overrides,
  };
}

function accepted(
  commandId: string,
  sequence: number,
  commands: readonly RoomProjectCommand[],
  overrides: Record<string, unknown> = {},
) {
  return {
    protocol_version: 1,
    type: "project.command.accepted",
    command_id: commandId,
    room_epoch: ROOM_EPOCH,
    sequence,
    actor: ACTOR,
    project_room_session_id: SESSION_ID,
    commands,
    ...overrides,
  };
}

function receipt(commandId: string, overrides: Record<string, unknown> = {}) {
  return {
    protocol_version: 1,
    type: "project.command.receipt",
    command_id: commandId,
    outcome: "accepted",
    accepted_room_epoch: ROOM_EPOCH,
    accepted_sequence: 5,
    current_room_epoch: ROOM_EPOCH,
    current_sequence: 5,
    deduplicated: false,
    requires_head_rehydration: false,
    ...overrides,
  };
}

function connectReadySession(
  options: Partial<ProjectRoomSessionOptions> = {},
): { session: ProjectRoomSession; socket: FakeWebSocket } {
  const session = new ProjectRoomSession({
    ...options,
    workspaceId: options.workspaceId ?? WORKSPACE_ID,
    projectId: options.projectId ?? PROJECT_ID,
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

function reconnectedSocket(socket: FakeWebSocket): FakeWebSocket {
  const next = FakeWebSocket.instances.at(-1);
  if (!next || next === socket)
    throw new Error("expected a replacement websocket");
  next.open();
  return next;
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("projectRoomWebSocketUrl", () => {
  it("builds a same-origin ws URL for the Project room under API_BASE", () => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    expect(projectRoomWebSocketUrl(WORKSPACE_ID, PROJECT_ID)).toBe(
      `${protocol}//${window.location.host}/api/v1/workspaces/${WORKSPACE_ID}/projects/${PROJECT_ID}/room`,
    );
  });
});

describe("shouldReplaceCollaborativeHead", () => {
  const base = projectHead({ collaboration_sequence: 5 });

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
        document: {
          graphs: [graph(GRAPH_ID, "Main", graphDocument({ nodes: [] }))],
        },
      }),
    ).toBe(false);
  });
});

describe("ProjectRoomSession", () => {
  it("connects with credentials path, parses room.ready, and tracks capabilities", () => {
    const onReady = vi.fn();
    const onStatusChange = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      onReady,
      onStatusChange,
    });

    expect(socket.url).toBe(projectRoomWebSocketUrl(WORKSPACE_ID, PROJECT_ID));
    expect(session.getStatus()).toBe("ready");
    expect(session.getAuthorizationVersion()).toBe(2);
    expect(session.getCapabilities()).toEqual([
      "view_project",
      "edit_project",
      "join_project_room",
      "publish_presence",
    ]);
    expect(session.getProjectRoomSessionId()).toBe(SESSION_ID);
    expect(session.getActor()).toEqual(ACTOR);
    expect(session.getHead()?.project_id).toBe(PROJECT_ID);
    expect(session.getHead()?.collaboration_sequence).toBe(4);
    // The ready snapshot is the whole Project: both of its Graphs are there.
    expect(session.getHead()?.document.graphs.map((item) => item.name)).toEqual(
      ["Main", "Second"],
    );
    // A fresh room reports no open Run and no instance state, not a guess.
    expect(session.getActiveRuns()).toEqual([]);
    expect(session.getInstances()).toEqual([]);
    expect(session.canSubmitCommands()).toBe(true);
    expect(onReady).toHaveBeenCalledOnce();
    expect(onStatusChange).toHaveBeenCalledWith("connecting");
    expect(onStatusChange).toHaveBeenCalledWith("ready");
  });

  it("adopts the open Runs and instance state the ready snapshot reports", () => {
    const onActiveRunsChange = vi.fn();
    const run = activeRun("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa01", GRAPH_ID);
    const otherRun = activeRun(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa02",
      OTHER_GRAPH_ID,
    );
    const instance = instanceState(OTHER_GRAPH_ID, "n2", "stale");

    const session = new ProjectRoomSession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      webSocketFactory: (url) => new FakeWebSocket(url) as unknown as WebSocket,
      onActiveRunsChange,
    });
    session.connect();
    const socket = FakeWebSocket.instances.at(-1);
    if (!socket) throw new Error("expected websocket");
    socket.open();
    socket.emitMessage(
      roomReady({ active_runs: [run, otherRun], instances: [instance] }),
    );

    // Nothing ran on this client: the lists come from the server's snapshot.
    expect(session.getStatus()).toBe("ready");
    expect(session.getActiveRuns()).toEqual([run, otherRun]);
    expect(session.getInstances()).toEqual([instance]);
    expect(onActiveRunsChange).toHaveBeenLastCalledWith([run, otherRun]);
  });

  it("tracks many open Runs and the derived state of node instances", () => {
    const onActiveRunsChange = vi.fn();
    const onInstancesChange = vi.fn();
    const onRunFinished = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      onActiveRunsChange,
      onInstancesChange,
      onRunFinished,
    });
    expect(session.getActiveRuns()).toEqual([]);
    expect(session.getInstances()).toEqual([]);

    // A Run is one demand for freshness, and a Project may hold many at once,
    // in different Graphs.
    const firstRun = activeRun(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa01",
      GRAPH_ID,
    );
    socket.emitMessage({
      protocol_version: 1,
      type: "run.started",
      run: firstRun,
    });
    expect(session.getActiveRuns()).toEqual([firstRun]);
    expect(onActiveRunsChange).toHaveBeenLastCalledWith([firstRun]);

    const secondRun = activeRun(
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa02",
      OTHER_GRAPH_ID,
    );
    socket.emitMessage({
      protocol_version: 1,
      type: "run.started",
      run: secondRun,
    });
    expect(session.getActiveRuns()).toEqual([firstRun, secondRun]);

    // A repeated run.started for the same Run replaces it, it does not double up.
    const cancellableOff = { ...firstRun, cancellable: false };
    socket.emitMessage({
      protocol_version: 1,
      type: "run.started",
      run: cancellableOff,
    });
    expect(session.getActiveRuns()).toEqual([cancellableOff, secondRun]);

    // Instance state is keyed by the whole instance: Graph, call path, node and
    // map index, so two Graphs never overwrite each other's nodes.
    const mainRunning = instanceState(GRAPH_ID, "n1", "running");
    const otherRunning = instanceState(OTHER_GRAPH_ID, "n1", "running");
    socket.emitMessage({
      protocol_version: 1,
      type: "instances.changed",
      changed: [mainRunning, otherRunning],
      removed: [],
      head_sequence: 5,
    });
    expect(session.getInstances()).toEqual([mainRunning, otherRunning]);
    expect(onInstancesChange).toHaveBeenLastCalledWith(
      expect.objectContaining({ head_sequence: 5 }),
    );

    // The same instance moving to `fresh` replaces it in place.
    const mainFresh = instanceState(GRAPH_ID, "n1", "fresh", {
      last_result_fingerprint: "fp-result-1",
    });
    socket.emitMessage({
      protocol_version: 1,
      type: "instances.changed",
      changed: [mainFresh],
      removed: [],
      head_sequence: 6,
    });
    expect(session.getInstances()).toEqual([mainFresh, otherRunning]);

    // One mapped item of the same node is a different instance.
    const mapped = instanceState(GRAPH_ID, "n1", "running", { map_index: 0 });
    socket.emitMessage({
      protocol_version: 1,
      type: "instances.changed",
      changed: [mapped],
      removed: [],
      head_sequence: 7,
    });
    expect(session.getInstances()).toEqual([mainFresh, otherRunning, mapped]);

    // `removed` names the instances that no longer exist.
    socket.emitMessage({
      protocol_version: 1,
      type: "instances.changed",
      changed: [],
      removed: [
        instanceKey(GRAPH_ID, "n1", null),
        instanceKey(GRAPH_ID, "n1", 0),
      ],
      head_sequence: 8,
    });
    expect(session.getInstances()).toEqual([otherRunning]);

    // A finished Run leaves the active list; its results live on the instances.
    socket.emitMessage({
      protocol_version: 1,
      type: "run.finished",
      run_id: firstRun.run_id,
      status: "succeeded",
      error: null,
    });
    expect(session.getActiveRuns()).toEqual([secondRun]);
    expect(onRunFinished).toHaveBeenCalledWith(
      expect.objectContaining({ run_id: firstRun.run_id, status: "succeeded" }),
    );

    // A result that never reached this client is a no-op, not a negative length.
    socket.emitMessage({
      protocol_version: 1,
      type: "run.finished",
      run_id: "cccccccc-cccc-4ccc-8ccc-cccccccccc99",
      status: "failed",
      error: "boom",
    });
    expect(session.getActiveRuns()).toEqual([secondRun]);

    socket.emitMessage({
      protocol_version: 1,
      type: "run.finished",
      run_id: secondRun.run_id,
      status: "cancelled",
      error: null,
    });
    expect(session.getActiveRuns()).toEqual([]);
    expect(onActiveRunsChange).toHaveBeenLastCalledWith([]);
  });

  it("restores open Runs and instance state from the server snapshot on resync", () => {
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
    });

    // The client's own idea of what is running, from live traffic.
    socket.emitMessage({
      protocol_version: 1,
      type: "run.started",
      run: activeRun("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa01", GRAPH_ID),
    });
    socket.emitMessage({
      protocol_version: 1,
      type: "instances.changed",
      changed: [instanceState(GRAPH_ID, "n1", "running")],
      removed: [],
      head_sequence: 5,
    });
    expect(session.getActiveRuns()).toHaveLength(1);
    expect(session.getInstances()).toHaveLength(1);

    // Connection loss stops the client claiming anything is running.
    socket.emitClose(1006, "connection_lost");
    expect(session.getStatus()).toBe("unsynchronized");
    expect(session.getActiveRuns()).toEqual([]);

    // The server's snapshot is authoritative: the client's guess is gone, and
    // what it did not report is not kept from before the drop.
    const serverRun = activeRun(
      "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbb02",
      GRAPH_ID,
    );
    const serverInstance = instanceState(OTHER_GRAPH_ID, "n2", "stale");
    session.connect();
    const reconnect = reconnectedSocket(socket);
    reconnect.emitMessage(
      roomReady({
        head: projectHead({ collaboration_sequence: 6 }),
        active_runs: [serverRun],
        instances: [serverInstance],
      }),
    );

    expect(session.getActiveRuns()).toEqual([serverRun]);
    expect(session.getInstances()).toEqual([serverInstance]);

    // A snapshot that reports nothing clears the guess rather than merging.
    reconnect.emitClose(1006, "connection_lost");
    expect(session.getActiveRuns()).toEqual([]);
    session.connect();
    const secondReconnect = reconnectedSocket(reconnect);
    secondReconnect.emitMessage(
      roomReady({
        head: projectHead({ collaboration_sequence: 7 }),
        active_runs: [],
        instances: [],
      }),
    );
    expect(session.getActiveRuns()).toEqual([]);
    expect(session.getInstances()).toEqual([]);
  });

  it("rejects a ready snapshot that names another workspace or Project", () => {
    const { session, socket } = connectReadySession();

    socket.emitMessage(
      roomReady({ project_id: "88888888-8888-4888-8888-888888888888" }),
    );

    expect(session.getStatus()).toBe("unsynchronized");
    expect(session.getLastFailure()).toMatchObject({
      reason: "protocol_error",
      messageType: "room.ready",
      detail:
        "The room-ready message identified a different workspace or Project.",
    });
  });

  it("submits a command batch and resolves on receipt after accepted", async () => {
    const commandIds = ["aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"];
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      createCommandId: () => commandIds.shift() ?? crypto.randomUUID(),
    });

    const commands = [
      renameGraph(GRAPH_ID, "Renamed graph", "Main"),
      replacePresentation(GRAPH_ID, ["artifact-viewer-1"]),
    ];
    const pending = session.submitCommands(commands);

    expect(socket.sent).toHaveLength(1);
    // One batch is one frame: the whole sequence travels together.
    expect(JSON.parse(socket.sent[0]!)).toEqual({
      protocol_version: 1,
      type: "project.command.submit",
      command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      room_epoch: ROOM_EPOCH,
      observed_sequence: 4,
      commands,
    });

    socket.emitMessage(
      accepted("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 5, commands),
    );
    socket.emitMessage(receipt("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"));

    const result = await pending;
    expect(result.receipt.accepted_sequence).toBe(5);
    expect(result.accepted?.sequence).toBe(5);
    expect(session.getHead()?.collaboration_sequence).toBe(5);
    // The batch advanced the Project once and renamed only the Graph it named.
    expect(headGraph(session.getHead(), GRAPH_ID)?.name).toBe("Renamed graph");
    expect(viewers(session.getHead(), GRAPH_ID)).toHaveLength(1);
    expect(headGraph(session.getHead(), OTHER_GRAPH_ID)?.name).toBe("Second");
    expect(session.getHead()?.name).toBe("Room project");
  });

  it("retries an interrupted batch idempotently before draining queued batches", async () => {
    const commandIds = [
      "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    ];
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      createCommandId: () => commandIds.shift() ?? crypto.randomUUID(),
    });

    const interrupted = session.submitCommands([
      renameProject("Renamed before disconnect"),
    ]);
    const queued = session.submitCommands([
      renameProject("Queued after reconnect", "Renamed before disconnect"),
    ]);
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
    const reconnect = reconnectedSocket(socket);
    reconnect.emitMessage(
      roomReady({
        head: projectHead({
          collaboration_sequence: 5,
          name: "Renamed before disconnect",
        }),
      }),
    );

    expect(reconnect.sent).toHaveLength(1);
    // The HMAC-backed idempotency contract includes epoch, observed sequence
    // and the whole batch, so the retry must preserve all of it.
    expect(JSON.parse(reconnect.sent[0]!)).toEqual(originalSubmission);

    reconnect.emitMessage(
      receipt("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", {
        outcome: "idempotent_replay",
        accepted_sequence: 5,
        current_sequence: 5,
        deduplicated: true,
      }),
    );

    await expect(interrupted).resolves.toMatchObject({
      receipt: {
        command_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        deduplicated: true,
      },
      accepted: null,
    });
    expect(reconnect.sent).toHaveLength(2);
    expect(JSON.parse(reconnect.sent[1]!)).toMatchObject({
      command_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      room_epoch: ROOM_EPOCH,
      observed_sequence: 5,
      commands: [{ name: "Queued after reconnect" }],
    });

    const queuedCommands = [
      renameProject("Queued after reconnect", "Renamed before disconnect"),
    ];
    reconnect.emitMessage(
      accepted("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", 6, queuedCommands),
    );
    reconnect.emitMessage(
      receipt("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", {
        accepted_sequence: 6,
        current_sequence: 6,
      }),
    );
    await expect(queued).resolves.toMatchObject({
      receipt: { accepted_sequence: 6 },
    });
    expect(session.getHead()?.name).toBe("Queued after reconnect");
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
      projectId: PROJECT_ID,
      createCommandId: () => commandIds.shift() ?? crypto.randomUUID(),
      onHeadRefreshRequired,
      onCommandAccepted,
    });

    const interrupted = session.submitCommands([
      renameProject("Committed before disconnect"),
    ]);
    const queued = session.submitCommands([
      renameProject("After authoritative refresh", "Peer rename"),
    ]);
    socket.emitClose(1006, "connection_lost");

    session.connect();
    const reconnect = reconnectedSocket(socket);
    reconnect.emitMessage(
      roomReady({
        head: projectHead({
          collaboration_sequence: 5,
          name: "Committed before disconnect",
        }),
      }),
    );
    expect(reconnect.sent).toHaveLength(1);

    // A peer commits sequence 6 after room.ready. Its accepted fanout is
    // delayed behind the private idempotent-replay receipt for sequence 5.
    reconnect.emitMessage(
      receipt("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", {
        outcome: "idempotent_replay",
        accepted_sequence: 5,
        current_sequence: 6,
        deduplicated: true,
      }),
    );

    let interruptedSettled = false;
    void interrupted.finally(() => {
      interruptedSettled = true;
    });
    await Promise.resolve();
    expect(interruptedSettled).toBe(false);
    expect(session.getHead()?.collaboration_sequence).toBe(5);
    expect(session.getHead()?.name).toBe("Committed before disconnect");
    expect(onHeadRefreshRequired).toHaveBeenCalledOnce();
    expect(reconnect.sent).toHaveLength(1);

    const peerCommands = [
      renameProject("Peer rename", "Committed before disconnect"),
    ];
    reconnect.emitMessage(
      accepted("cccccccc-cccc-4ccc-8ccc-cccccccccccc", 6, peerCommands, {
        actor: {
          actor_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
          display_name: "Peer",
          color: "indigo",
        },
        project_room_session_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
      }),
    );

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
    expect(reconnect.sent).toHaveLength(2);
    expect(JSON.parse(reconnect.sent[1]!)).toMatchObject({
      command_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      observed_sequence: 6,
      commands: [
        {
          kind: "rename_project",
          name: "After authoritative refresh",
          expected_name: "Peer rename",
        },
      ],
    });
    queued.catch(() => undefined);
    session.disconnect();
  });

  it("pauses command drain and requests a refresh when an accepted sequence has a gap", async () => {
    const onCommandAccepted = vi.fn();
    const onHeadRefreshRequired = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      createCommandId: () => "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      onCommandAccepted,
      onHeadRefreshRequired,
    });
    const headBeforeGap = session.getHead();

    socket.emitMessage(
      accepted("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 6, [
        renameProject("Skipped rename"),
      ]),
    );

    expect(session.getHead()).toBe(headBeforeGap);
    expect(session.getHead()?.name).toBe("Room project");
    expect(session.getHead()?.collaboration_sequence).toBe(4);
    expect(onCommandAccepted).not.toHaveBeenCalled();
    expect(onHeadRefreshRequired).toHaveBeenCalledOnce();

    const pending = session.submitCommands([renameProject("Wait for refresh")]);
    expect(socket.sent).toHaveLength(0);
    session.disconnect();
    await expect(pending).rejects.toMatchObject({ errorCode: "disconnected" });
  });

  it("ignores a stale accepted command while retaining in-flight correlation", async () => {
    const commandId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
    const onCommandAccepted = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      createCommandId: () => commandId,
      onCommandAccepted,
    });
    const pending = session.submitCommands([renameProject("Local rename")]);
    const headBeforeStaleAccept = session.getHead();

    socket.emitMessage(
      accepted(commandId, 3, [
        renameProject("Stale rename", "Older project name"),
      ]),
    );

    expect(session.getHead()).toBe(headBeforeStaleAccept);
    expect(session.getHead()?.name).toBe("Room project");
    expect(onCommandAccepted).not.toHaveBeenCalled();

    socket.emitMessage(
      receipt(commandId, {
        outcome: "idempotent_replay",
        accepted_sequence: 3,
        current_sequence: 4,
        deduplicated: true,
      }),
    );

    const result = await pending;
    expect(result.accepted?.sequence).toBe(3);
    expect(session.getHead()?.name).toBe("Room project");
    expect(session.getHead()?.collaboration_sequence).toBe(4);
  });

  it("keeps an accepted head when a stale room.ready arrives during reconnect", () => {
    const onReady = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      onReady,
    });

    socket.emitClose(1006, "connection_lost");
    session.connect();
    const reconnect = reconnectedSocket(socket);
    const peerCommands = [renameProject("Accepted during reconnect")];
    reconnect.emitMessage(
      accepted("cccccccc-cccc-4ccc-8ccc-cccccccccccc", 5, peerCommands),
    );
    reconnect.emitMessage(roomReady());

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
      projectId: PROJECT_ID,
      createCommandId: () => "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    });

    const pending = session.submitCommands([renameProject("Nope", "Wrong")]);
    socket.emitMessage({
      protocol_version: 1,
      type: "project.command.rejected",
      command_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      error_code: "field_conflict",
      detail: "Name changed elsewhere.",
      current_room_epoch: ROOM_EPOCH,
      current_sequence: 4,
    });

    await expect(pending).rejects.toMatchObject({
      name: "ProjectRoomCommandError",
      errorCode: "field_conflict",
    });
  });

  it("ignores stale replaceHead snapshots after a newer WebSocket accept", () => {
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
    });
    const otherGraphBefore = headGraph(session.getHead(), OTHER_GRAPH_ID);

    socket.emitMessage(
      accepted("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 5, [
        replacePresentation(GRAPH_ID, ["artifact-viewer-1"]),
      ]),
    );
    expect(session.getHead()?.collaboration_sequence).toBe(5);
    expect(viewers(session.getHead(), GRAPH_ID)).toHaveLength(1);
    // An accepted command only ever touches the Graph it was addressed to.
    expect(headGraph(session.getHead(), OTHER_GRAPH_ID)).toBe(otherGraphBefore);
    expect(viewers(session.getHead(), OTHER_GRAPH_ID)).toEqual([]);

    session.replaceHead(
      projectHead({
        collaboration_sequence: 4,
        name: "Room project",
      }),
    );

    expect(session.getHead()?.collaboration_sequence).toBe(5);
    expect(viewers(session.getHead(), GRAPH_ID)).toHaveLength(1);
  });

  it("applies a peer's accepted command to the Graph it addresses, not the open one", () => {
    const onCommandAccepted = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      onCommandAccepted,
    });
    const openDocumentBefore = openGraphDocument(session.getHead());

    // The peer rearranged a Graph this client is not looking at.
    socket.emitMessage(
      accepted("dddddddd-dddd-4ddd-8ddd-dddddddddddd", 5, [
        replacePresentation(OTHER_GRAPH_ID, ["artifact-viewer-9"]),
      ]),
    );

    // The sequence still advances, because the head is the shared Project fact.
    expect(session.getHead()?.collaboration_sequence).toBe(5);
    expect(onCommandAccepted).toHaveBeenLastCalledWith(
      expect.objectContaining({ sequence: 5 }),
      { local: false },
    );
    expect(viewers(session.getHead(), OTHER_GRAPH_ID)).toHaveLength(1);
    // The Graph the client has open is byte-for-byte the document it had.
    expect(openGraphDocument(session.getHead())).toBe(openDocumentBefore);
  });

  it("leaves every Graph untouched by a command for a Graph this head lacks", () => {
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
    });
    const graphsBefore = session.getHead()?.document.graphs;
    const openDocumentBefore = openGraphDocument(session.getHead());

    // A peer edited inside a Graph this head has never seen: inventing it would
    // be worse than waiting for the snapshot, so nothing is created and every
    // Graph stays exactly as it was — but the sequence still moves, which is
    // what lets the next accepted command apply instead of stalling forever.
    socket.emitMessage(
      accepted("dddddddd-dddd-4ddd-8ddd-dddddddddddd", 5, [
        replacePresentation(UNKNOWN_GRAPH_ID, ["artifact-viewer-9"]),
      ]),
    );

    expect(session.getHead()?.collaboration_sequence).toBe(5);
    expect(session.getHead()?.document.graphs).toBe(graphsBefore);
    expect(openGraphDocument(session.getHead())).toBe(openDocumentBefore);

    // The same holds for the Project-level command addressed by Graph id.
    socket.emitMessage(
      accepted("dddddddd-dddd-4ddd-8ddd-ddddddddddde", 6, [
        renameGraph(UNKNOWN_GRAPH_ID, "Ghost graph", "Whatever"),
      ]),
    );

    expect(session.getHead()?.collaboration_sequence).toBe(6);
    expect(session.getHead()?.document.graphs.map((item) => item.name)).toEqual(
      ["Main", "Second"],
    );
    expect(session.getHead()?.document.graphs[0]).toBe(graphsBefore?.[0]);
  });

  it("keeps a rehydrated epoch when an old-epoch checkpoint response arrives late", async () => {
    const commandId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      createCommandId: () => commandId,
    });
    const commands = [
      replaceGraphDocument(GRAPH_ID, graphDocument({ nodes: [] })),
    ];
    const submitted = session.submitCommands(commands);
    socket.emitMessage(accepted(commandId, 5, commands));
    socket.emitMessage(receipt(commandId));
    await submitted;

    const resetHead = projectHead({
      room_epoch: RESET_EPOCH,
      collaboration_sequence: 0,
      checkpoint_sequence: 0,
      checkpoint_revision: 3,
      name: "Authoritative E2",
      updated_at: "2026-08-07T11:00:00Z",
      document: {
        graphs: [
          graph(
            GRAPH_ID,
            "Main",
            graphDocument({
              presentation: {
                viewers: [
                  {
                    id: "e2-viewer",
                    position: { x: 30, y: 40 },
                    layout: null,
                    mode: null,
                  },
                ],
                links: [],
                bindings: [],
                annotations: [],
              },
            }),
          ),
        ],
      },
    });
    socket.emitMessage({
      protocol_version: 1,
      type: "room.rehydrate",
      reason: "epoch_reset",
      head: resetHead,
    });

    const effectiveHead = session.reconcileCheckpointHead(
      projectHead({
        collaboration_sequence: 5,
        checkpoint_sequence: 5,
        checkpoint_revision: 2,
        name: "Checkpointed in E1",
        updated_at: "2026-08-07T10:30:00Z",
      }),
      ROOM_EPOCH,
    );

    expect(effectiveHead).toEqual(resetHead);
    expect(session.getHead()).toEqual(resetHead);
  });

  it("pauses drain on head_conflict until replaceHead, and still applies peer accept", async () => {
    const commandIds = [
      "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
      "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    ];
    const onHeadRefreshRequired = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      createCommandId: () => commandIds.shift() ?? crypto.randomUUID(),
      onHeadRefreshRequired,
    });

    const conflicting = session.submitCommands([
      replacePresentation(GRAPH_ID, []),
    ]);
    expect(socket.sent).toHaveLength(1);

    const queued = session.submitCommands([
      renameGraph(GRAPH_ID, "After conflict", "Main"),
    ]);
    expect(socket.sent).toHaveLength(1);

    socket.emitMessage({
      protocol_version: 1,
      type: "project.command.rejected",
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

    socket.emitMessage(
      accepted(
        "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
        5,
        [renameGraph(GRAPH_ID, "Peer rename", "Main")],
        {
          project_room_session_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
        },
      ),
    );
    expect(session.getHead()?.collaboration_sequence).toBe(5);
    expect(headGraph(session.getHead(), GRAPH_ID)?.name).toBe("Peer rename");
    // Still paused until a full snapshot lands.
    expect(socket.sent).toHaveLength(1);

    session.replaceHead(projectHead({ collaboration_sequence: 5 }));
    expect(socket.sent).toHaveLength(2);
    expect(JSON.parse(socket.sent[1]!)).toMatchObject({
      type: "project.command.submit",
      observed_sequence: 5,
      commands: [
        {
          kind: "rename_graph",
          graph_id: GRAPH_ID,
          name: "After conflict",
        },
      ],
    });
    queued.catch(() => undefined);
    expect(onHeadRefreshRequired).not.toHaveBeenCalled();
  });

  it("coalesces unsent replace_presentation batches for the same Graph", async () => {
    const commandIds = [
      "ffffffff-ffff-4fff-8fff-ffffffffffff",
      "11111111-1111-4111-8111-111111111111",
      "22222222-2222-4222-8222-222222222222",
    ];
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      createCommandId: () => commandIds.shift() ?? crypto.randomUUID(),
    });

    const first = session.submitCommands([
      replacePresentation(GRAPH_ID, ["artifact-viewer-1"]),
    ]);
    expect(socket.sent).toHaveLength(1);

    const second = session.submitCommands([
      replacePresentation(GRAPH_ID, ["artifact-viewer-2"]),
    ]);
    const third = session.submitCommands([
      replacePresentation(GRAPH_ID, ["artifact-viewer-3"]),
    ]);
    await expect(second).rejects.toMatchObject({ errorCode: "superseded" });
    expect(socket.sent).toHaveLength(1);

    socket.emitMessage(
      accepted("ffffffff-ffff-4fff-8fff-ffffffffffff", 5, [
        replacePresentation(GRAPH_ID, ["artifact-viewer-1"]),
      ]),
    );
    socket.emitMessage(receipt("ffffffff-ffff-4fff-8fff-ffffffffffff"));
    await first;
    expect(socket.sent).toHaveLength(2);
    const drainedFrame = JSON.parse(socket.sent[1]!) as Record<string, unknown>;
    expect(drainedFrame.observed_sequence).toBe(5);
    expect(drainedFrame.commands).toEqual([
      replacePresentation(GRAPH_ID, ["artifact-viewer-3"]),
    ]);
    third.catch(() => undefined);
  });

  it("does not let a stale same-epoch rehydrate rewind an accepted head", () => {
    const onRehydrate = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      onRehydrate,
    });

    socket.emitMessage(
      accepted("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", 5, [
        renameGraph(GRAPH_ID, "Accepted after snapshot", "Main"),
      ]),
    );
    const acceptedHead = session.getHead();

    socket.emitMessage({
      protocol_version: 1,
      type: "room.rehydrate",
      reason: "epoch_reset",
      head: roomReady().head,
    });

    expect(session.getHead()).toBe(acceptedHead);
    expect(session.getHead()?.collaboration_sequence).toBe(5);
    expect(headGraph(session.getHead(), GRAPH_ID)?.name).toBe(
      "Accepted after snapshot",
    );
    expect(onRehydrate).toHaveBeenCalledWith(acceptedHead);
  });

  it("replaces collaborative head state on room.rehydrate", () => {
    const onRehydrate = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      onRehydrate,
    });
    const head = projectHead({
      room_epoch: RESET_EPOCH,
      collaboration_sequence: 1,
      checkpoint_sequence: 2,
      checkpoint_revision: 2,
      name: "Reset",
      updated_at: "2026-08-07T11:00:00Z",
      document: { graphs: [graph(GRAPH_ID, "Only")] },
    });

    socket.emitMessage({
      protocol_version: 1,
      type: "room.rehydrate",
      reason: "epoch_reset",
      head,
    });

    expect(session.getHead()).toEqual(head);
    expect(onRehydrate).toHaveBeenCalledWith(head);
  });

  it.each([
    {
      code: CLOSE_ACCESS_REVOKED,
      reason: "access_revoked",
      label: "access_revoked",
    },
    {
      code: CLOSE_PROJECT_DELETED,
      reason: "project_deleted",
      label: "project_deleted",
    },
  ] as const)(
    "stops traffic and exposes $label without reconnecting",
    async ({ code, reason, label }) => {
      vi.useFakeTimers();
      const onTerminalClose = vi.fn();
      const { session, socket } = connectReadySession({
        workspaceId: WORKSPACE_ID,
        projectId: PROJECT_ID,
        onTerminalClose,
        createCommandId: () => "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
      });

      const pending = session.submitCommands([renameProject("Pending")]);
      const socketsBeforeClose = FakeWebSocket.instances.length;
      socket.emitClose(code, reason);

      expect(session.getStatus()).toBe("stopped");
      expect(session.getTerminalReason()).toBe(label);
      expect(session.canSubmitCommands()).toBe(false);
      expect(onTerminalClose).toHaveBeenCalledWith(label);
      await expect(pending).rejects.toBeInstanceOf(ProjectRoomCommandError);

      await vi.advanceTimersByTimeAsync(20_000);
      expect(FakeWebSocket.instances.length).toBe(socketsBeforeClose);
      await expect(
        session.submitCommands([renameProject("Again")]),
      ).rejects.toMatchObject({ errorCode: "not_ready" });
    },
  );

  it.each([
    [CLOSE_PERMISSIONS_CHANGED, "permissions_changed"],
    [CLOSE_PROTOCOL_ERROR, "protocol_error"],
    [CLOSE_SLOW_CONSUMER, "slow_consumer"],
  ] as const)(
    "rehydrates after recoverable %s room closure",
    async (code, reason) => {
      vi.useFakeTimers();
      const { session, socket } = connectReadySession({
        workspaceId: WORKSPACE_ID,
        projectId: PROJECT_ID,
        reconnectDelayMs: 10,
      });

      socket.emitClose(code, reason);

      expect(session.getStatus()).toBe("unsynchronized");
      expect(session.getTerminalReason()).toBeNull();
      expect(session.getHead()?.project_id).toBe(PROJECT_ID);
      expect(session.canSubmitCommands()).toBe(false);
      expect(session.getLastFailure()).toMatchObject({
        reason,
        retryable: true,
      });

      await vi.advanceTimersByTimeAsync(10);
      const reconnect = FakeWebSocket.instances.at(-1)!;
      reconnect.open();
      reconnect.emitMessage(
        roomReady({
          head: projectHead({ collaboration_sequence: 5 }),
        }),
      );

      expect(session.getStatus()).toBe("ready");
      expect(session.getLastFailure()).toBeNull();
      expect(session.getHead()?.collaboration_sequence).toBe(5);
    },
  );

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

    // A Run event without its Run is a protocol fault too: the client cannot
    // guess which Run the Project started.
    const runless = connectReadySession();
    runless.socket.emitMessage({ protocol_version: 1, type: "run.started" });
    expect(runless.session.getStatus()).toBe("unsynchronized");
    expect(runless.session.getLastFailure()).toMatchObject({
      reason: "protocol_error",
      messageType: "run.started",
    });

    const incompatible = connectReadySession();
    incompatible.socket.emitMessage({
      protocol_version: 2,
      type: "room.ready",
    });
    expect(incompatible.session.getStatus()).toBe("stopped");
    expect(incompatible.session.getTerminalReason()).toBe(
      "protocol_incompatible",
    );
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
      projectId: PROJECT_ID,
      projectRoomSessionId: SESSION_ID,
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
      projectId: PROJECT_ID,
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
      projectId: PROJECT_ID,
      createCommandId: () => crypto.randomUUID(),
    });

    const first = session.submitCommands([renameProject("First")]);
    expect(socket.sent).toHaveLength(1);

    const queued = Array.from(
      { length: ROOM_COMMAND_QUEUE_CAP - 1 },
      (_, index) => session.submitCommands([renameProject(`Queued ${index}`)]),
    );
    await expect(
      session.submitCommands([renameProject("Overflow")]),
    ).rejects.toMatchObject({ errorCode: "queue_full" });

    socket.emitMessage({
      protocol_version: 1,
      type: "project.command.rejected",
      command_id: JSON.parse(socket.sent[0]!).command_id,
      error_code: "command_rejected",
      detail: "stop first",
      current_room_epoch: ROOM_EPOCH,
      current_sequence: 4,
    });
    await expect(first).rejects.toBeInstanceOf(ProjectRoomCommandError);
    for (const item of queued) {
      item.catch(() => undefined);
    }
    session.disconnect();
  });

  it("tracks remote presence join/update/leave and publishes throttled updates", () => {
    const onPresenceChange = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      onPresenceChange,
    });

    expect(session.getParticipants()).toHaveLength(1);
    expect(session.canPublishPresence()).toBe(true);
    expect(session.getRemoteParticipants()).toHaveLength(0);

    const remoteId = "99999999-9999-4999-8999-999999999999";
    socket.emitMessage({
      protocol_version: 1,
      type: "presence.join",
      participant: participant(remoteId, "Editor", {
        cursor: null,
        presence_sequence: 0,
      }),
    });
    expect(session.getRemoteParticipants()).toHaveLength(1);
    // A participant says which Graph of the Project they are on.
    expect(session.getRemoteParticipants()[0]?.graph_id).toBe(GRAPH_ID);

    socket.emitMessage({
      protocol_version: 1,
      type: "presence.update",
      participant: participant(remoteId, "Editor", {
        graph_id: OTHER_GRAPH_ID,
        presence_sequence: 3,
        cursor: { x: 10, y: 20 },
        selected_node_ids: ["n1"],
        activity: "editing_node",
        activity_target_ids: ["n1"],
      }),
    });
    expect(session.getRemoteParticipants()[0]?.cursor).toEqual({
      x: 10,
      y: 20,
    });
    expect(session.getRemoteParticipants()[0]?.selected_node_ids).toEqual([
      "n1",
    ]);
    expect(session.getRemoteParticipants()[0]?.graph_id).toBe(OTHER_GRAPH_ID);

    // Publishing names the Graph this client is showing, so two people in two
    // Graphs of one Project do not appear to share a cursor.
    expect(
      session.publishPresence({ graph_id: GRAPH_ID, cursor: { x: 1, y: 2 } }),
    ).toBe(true);
    expect(socket.lastSent()).toMatchObject({
      type: "presence.update",
      graph_id: GRAPH_ID,
      presence_sequence: 1,
      cursor: { x: 1, y: 2 },
    });
    expect(
      session.publishPresence({ graph_id: GRAPH_ID, cursor: { x: 3, y: 4 } }),
    ).toBe(false);

    socket.emitMessage({
      protocol_version: 1,
      type: "presence.leave",
      project_room_session_id: remoteId,
    });
    expect(session.getRemoteParticipants()).toHaveLength(0);
    expect(onPresenceChange).toHaveBeenCalled();
  });

  it("clears presence on terminal close and keeps the server keepalive inert", () => {
    const onPresenceChange = vi.fn();
    const { session, socket } = connectReadySession({
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
      onPresenceChange,
    });
    expect(session.getParticipants()).toHaveLength(1);
    socket.emitMessage({
      protocol_version: 1,
      type: "room.heartbeat",
      authorization_version: 2,
    });
    expect(session.getStatus()).toBe("ready");
    // The keepalive is not an authorization signal the client acts on: the
    // room.ready snapshot is what set the version, and it stays there.
    expect(session.getAuthorizationVersion()).toBe(2);
    socket.emitClose(CLOSE_ACCESS_REVOKED, "access_revoked");
    expect(session.getStatus()).toBe("stopped");
    expect(session.getParticipants()).toHaveLength(0);
    expect(onPresenceChange).toHaveBeenCalled();
  });
});
