// @vitest-environment jsdom

import * as React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import type {
  ActiveRunSummary,
  CollaborativeHead,
  GraphDefinition,
  SavedGraphDocument,
} from "@/lib/api";

import { renderHook } from "../ui/test/renderHook";
import {
  CLOSE_ACCESS_REVOKED,
  CLOSE_PROJECT_DELETED,
  instanceKeyText,
  type InstancesChangedMessage,
  type ProjectRoomTerminalReason,
  type RoomInstanceKey,
  type RoomInstanceState,
  type RoomProjectCommand,
  type RoomReadyMessage,
} from "./protocol";
import { useProjectRoomSession } from "./useProjectRoomSession";

/**
 * The hook is the seam every Workbench surface reads: the head, the capability
 * gates, the open Runs, the instance states and the two revision counters. The
 * session underneath it is tested against the wire; these tests drive the same
 * wire through the hook, because every defect this file pins lived in the
 * translation from session callbacks to returned state, where nothing
 * downstream noticed.
 */

const WORKSPACE_ID = "00000000-0000-4000-8000-000000000007";
const PROJECT_ID = "99999999-9999-4999-8999-999999999991";
/** The Graph this client has open in the canvas. */
const GRAPH_ID = "11111111-1111-4111-8111-111111111111";
/** Another Graph of the same Project, which this client is not looking at. */
const OTHER_GRAPH_ID = "66666666-6666-4666-8666-666666666666";
const ANOTHER_PROJECT_ID = "88888888-8888-4888-8888-888888888881";
const SESSION_ID = "22222222-2222-4222-8222-222222222222";
const PEER_SESSION_ID = "55555555-5555-4555-8555-555555555555";
const ACTOR_ID = "00000000-0000-4000-8000-000000000001";
const ROOM_EPOCH = "33333333-3333-4333-8333-333333333333";
const RUN_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaa01";
/** The collaboration sequence the fixture's head carries, so a test names it. */
const HEAD_SEQUENCE = 4;

const ACTOR = {
  actor_id: ACTOR_ID,
  display_name: "Owner",
  color: "emerald",
};

/**
 * The names the room's gates are keyed on. `start_run` is the API's name for
 * asking for work (`WorkspaceCapability.START_RUN`, and `POST
 * /projects/{id}/runs` in the design doc); the hook types the room's capability
 * list as `string[]`, so a made-up name compiles and only a test catches it.
 */
const CAPABILITY_RUN = "start_run";
const CAPABILITY_EDIT = "edit_project";
const CAPABILITY_PRESENCE = "publish_presence";

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

function projectHead(
  overrides: Partial<CollaborativeHead> = {},
): CollaborativeHead {
  return {
    project_id: PROJECT_ID,
    room_epoch: ROOM_EPOCH,
    collaboration_sequence: HEAD_SEQUENCE,
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

function participant(sessionId: string, displayName: string) {
  return {
    project_room_session_id: sessionId,
    actor:
      sessionId === SESSION_ID
        ? ACTOR
        : {
            actor_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            display_name: displayName,
            color: "indigo",
          },
    graph_id: GRAPH_ID,
    presence_sequence: 0,
    cursor: null,
    selected_node_ids: [],
    selected_edge_ids: [],
    activity: null,
    activity_target_ids: [],
    transient_node_positions: [],
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

/** A `room.ready`, the only message that establishes a room. */
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
        "join_project_room",
        CAPABILITY_EDIT,
        CAPABILITY_PRESENCE,
        CAPABILITY_RUN,
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

/** The room's only signal that instance state moved. */
function instancesChanged(
  changed: readonly RoomInstanceState[],
  removed: readonly RoomInstanceKey[],
  headSequence: number,
) {
  return {
    protocol_version: 1,
    type: "instances.changed",
    changed,
    removed,
    head_sequence: headSequence,
  };
}

function runStarted(run: ActiveRunSummary) {
  return { protocol_version: 1, type: "run.started", run };
}

function runFinished(runId: string) {
  return {
    protocol_version: 1,
    type: "run.finished",
    run_id: runId,
    status: "succeeded",
    error: null,
  };
}

/** The room applying this client's batch at the sequence after its head. */
function commandAccepted(
  commandId: string,
  sequence: number,
  commands: readonly RoomProjectCommand[],
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
  };
}

function commandReceipt(commandId: string, sequence: number) {
  return {
    protocol_version: 1,
    type: "project.command.receipt",
    command_id: commandId,
    outcome: "accepted",
    accepted_room_epoch: ROOM_EPOCH,
    accepted_sequence: sequence,
    current_room_epoch: ROOM_EPOCH,
    current_sequence: sequence,
    deduplicated: false,
    requires_head_rehydration: false,
  };
}

function renameProject(name: string): RoomProjectCommand {
  return {
    kind: "rename_project",
    name,
    expected_name: "Room project",
  };
}

/**
 * The session is built inside the hook with the default WebSocket factory, so
 * the fake socket goes in as the global and the hook stays untouched.
 */
class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  static instances: FakeWebSocket[] = [];

  readonly url: string;
  readonly sent: string[] = [];
  readyState = FakeWebSocket.CONNECTING;

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

  close = (code?: number, reason?: string) => {
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatch("close", { code: code ?? 1000, reason: reason ?? "" });
  };

  open(): void {
    this.readyState = FakeWebSocket.OPEN;
    this.dispatch("open", {});
  }

  emitMessage(payload: unknown): void {
    this.dispatch("message", { data: JSON.stringify(payload) });
  }

  emitClose(code: number, reason: string): void {
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatch("close", { code, reason });
  }

  /** The frames this client wrote, decoded: a room sends no silent frames. */
  sentFrames(): Record<string, unknown>[] {
    return this.sent.map((raw) => JSON.parse(raw) as Record<string, unknown>);
  }

  private dispatch(type: string, event: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }
}

/**
 * The room's callbacks land outside React's own event handling, so every push
 * is wrapped in `act` and drained to the microtask queue. Nothing here waits on
 * a timer to become true; the only clock advanced on purpose is the session's
 * own reconnect backoff, under fake timers.
 */
async function settle(work: () => void): Promise<void> {
  await React.act(async () => {
    work();
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

function latestSocket(): FakeWebSocket {
  const socket = FakeWebSocket.instances.at(-1);
  if (!socket) throw new Error("expected a websocket");
  return socket;
}

type RoomProps = Parameters<typeof useProjectRoomSession>[0];
type RoomResult = ReturnType<typeof useProjectRoomSession>;

interface RenderedRoom {
  readonly result: { readonly current: RoomResult };
  readonly rerender: (props: RoomProps) => Promise<void>;
  readonly unmount: () => Promise<void>;
}

interface RoomCallbacks {
  readonly onReady: Mock<(ready: RoomReadyMessage) => void>;
  readonly onInstancesChange: Mock<(message: InstancesChangedMessage) => void>;
  readonly onTerminalClose: Mock<(reason: ProjectRoomTerminalReason) => void>;
}

interface OpenRoomOptions {
  /** `null` is a canvas with no Project open, which must never open a room. */
  readonly projectId?: string | null;
  /** Overrides merged into `room.ready`; `null` stops at the open socket. */
  readonly ready?: Record<string, unknown> | null;
}

interface RoomHarness {
  readonly hook: RenderedRoom;
  readonly props: RoomProps;
  readonly callbacks: RoomCallbacks;
  readonly socket: FakeWebSocket;
  readonly push: (message: unknown) => Promise<void>;
  readonly close: (code: number, reason: string) => Promise<void>;
  /** Cross the session's backoff and hand back the socket it replaced the old one with. */
  readonly reconnect: () => Promise<FakeWebSocket>;
  /** The hook's answer right now. Read it after every push, never from a snapshot. */
  readonly room: () => RoomResult;
}

/**
 * Mount the hook against a Project and, unless told otherwise, take the room to
 * `ready`. The socket stays in hand so a test says what the room pushed rather
 * than what the hook happens to remember.
 */
async function openRoom(options: OpenRoomOptions = {}): Promise<RoomHarness> {
  const projectId =
    options.projectId === undefined ? PROJECT_ID : options.projectId;
  const callbacks: RoomCallbacks = {
    onReady: vi.fn<(ready: RoomReadyMessage) => void>(),
    onInstancesChange: vi.fn<(message: InstancesChangedMessage) => void>(),
    onTerminalClose: vi.fn<(reason: ProjectRoomTerminalReason) => void>(),
  };
  const props: RoomProps = {
    workspaceId: WORKSPACE_ID,
    projectId,
    onReady: callbacks.onReady,
    onRehydrate: vi.fn(),
    onHeadRefreshRequired: vi.fn(),
    onCommandAccepted: vi.fn(),
    onCommandRejected: vi.fn(),
    onActiveRunsChange: vi.fn(),
    onRunFinished: vi.fn(),
    onInstancesChange: callbacks.onInstancesChange,
    onTerminalClose: callbacks.onTerminalClose,
  };
  const hook = await renderHook(useProjectRoomSession, props);
  const socket = projectId === null ? null : latestSocket();
  if (socket && options.ready !== null) {
    const ready = options.ready ?? {};
    await settle(() => {
      socket.open();
      socket.emitMessage(roomReady(ready));
    });
  }

  const room = () => hook.result.current;

  if (!socket) {
    const nothing = async (): Promise<never> => {
      throw new Error("no room is open here");
    };
    return {
      hook,
      props,
      callbacks,
      socket: null as unknown as FakeWebSocket,
      push: nothing,
      close: nothing,
      reconnect: nothing,
      room,
    };
  }

  const open = socket;
  return {
    hook,
    props,
    callbacks,
    socket: open,
    push: (message) => settle(() => open.emitMessage(message)),
    close: (code, reason) => settle(() => open.emitClose(code, reason)),
    reconnect: async () => {
      await React.act(async () => {
        await vi.advanceTimersByTimeAsync(1_000);
      });
      const next = latestSocket();
      if (next === open) throw new Error("expected a replacement socket");
      await settle(() => next.open());
      return next;
    },
    room,
  };
}

/** The instance keys the hook answers for, in the order it received them. */
function instanceKeys(map: ReadonlyMap<string, RoomInstanceState>) {
  return [...map.keys()];
}

function strictlyIncreasing(values: readonly number[]): boolean {
  return values.every(
    (value, index) => index === 0 || value > (values[index - 1] as number),
  );
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useProjectRoomSession instances", () => {
  it("keeps the instances an `instances.changed` delta did not name", async () => {
    const openFresh = instanceState(GRAPH_ID, "n1", "fresh");
    const otherRunning = instanceState(OTHER_GRAPH_ID, "n2", "running");
    const { room, push } = await openRoom({
      ready: { instances: [openFresh, otherRunning] },
    });

    // The ready snapshot is keyed by instance identity, so the canvas looks a
    // state up by the node it is drawing.
    expect(instanceKeys(room().instances)).toEqual([
      instanceKeyText(openFresh),
      instanceKeyText(otherRunning),
    ]);
    expect(room().instances.get(instanceKeyText(openFresh))).toEqual(openFresh);

    // A delta naming one instance replaces that one and leaves the rest alone.
    const openStale = instanceState(GRAPH_ID, "n1", "stale");
    await push(instancesChanged([openStale], [], 5));
    expect(room().instances.get(instanceKeyText(openStale))).toEqual(openStale);
    expect(room().instances.get(instanceKeyText(otherRunning))).toEqual(
      otherRunning,
    );
    expect(room().instances.size).toBe(2);

    // One mapped item of the same node is another instance.
    const mapped = instanceState(GRAPH_ID, "n1", "running", { map_index: 0 });
    await push(instancesChanged([mapped], [], 6));
    expect(room().instances.size).toBe(3);

    // `removed` is the way out: the named instances go, the others stay.
    await push(
      instancesChanged(
        [],
        [instanceKey(OTHER_GRAPH_ID, "n2"), instanceKey(GRAPH_ID, "n1", 0)],
        7,
      ),
    );
    expect(instanceKeys(room().instances)).toEqual([
      instanceKeyText(openStale),
    ]);
  });

  it("hands the raw delta to the listener while returning the whole map", async () => {
    const first = instanceState(GRAPH_ID, "n1", "running");
    const { room, push, callbacks } = await openRoom();

    await push(instancesChanged([first], [], 5));

    // The listener sees the delta — a surface that diffs pushes must not be
    // handed the accumulated map where the room said what moved.
    expect(callbacks.onInstancesChange).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "instances.changed",
        changed: [first],
        removed: [],
        head_sequence: 5,
      }),
    );
    expect(instanceKeys(room().instances)).toEqual([instanceKeyText(first)]);
  });

  it("treats a fresh room.ready as the authoritative snapshot, not a merge", async () => {
    const before = instanceState(GRAPH_ID, "n1", "stale");
    const { socket, push, reconnect, room } = await openRoom({
      ready: { instances: [before] },
    });

    const dropped = instanceState(GRAPH_ID, "n9", "running");
    await push(instancesChanged([dropped], [], 5));
    expect(room().instances.size).toBe(2);

    // The drop takes the derived state with it...
    await settle(() => socket.emitClose(1006, "connection_lost"));
    expect(room().instances.size).toBe(0);

    // ...and whatever the new snapshot does not report is not kept.
    const reconnectSocket = await reconnect();
    const afterReconnect = instanceState(OTHER_GRAPH_ID, "n2", "fresh");
    await settle(() =>
      reconnectSocket.emitMessage(
        roomReady({
          head: projectHead({ collaboration_sequence: 6 }),
          instances: [afterReconnect],
        }),
      ),
    );

    expect(instanceKeys(room().instances)).toEqual([
      instanceKeyText(afterReconnect),
    ]);
  });
});

describe("useProjectRoomSession capability gates", () => {
  const gates = [
    {
      name: "canRun",
      capability: CAPABILITY_RUN,
      // A name the API's capability list does not contain, standing in for the
      // next invented one.
      impostor: "run_project",
      read: (room: RoomResult) => room.canRun,
    },
    {
      name: "canSubmitCommands",
      capability: CAPABILITY_EDIT,
      impostor: "write_project",
      read: (room: RoomResult) => room.canSubmitCommands,
    },
    {
      name: "canPublishPresence",
      capability: CAPABILITY_PRESENCE,
      impostor: "send_presence",
      read: (room: RoomResult) => room.canPublishPresence,
    },
  ];

  for (const gate of gates) {
    it(`opens ${gate.name} on the API's own capability name`, async () => {
      const { room } = await openRoom();
      expect(gate.read(room())).toBe(true);
    });

    it(`keeps ${gate.name} closed without that capability`, async () => {
      const capabilities = roomReady().capabilities.capabilities.filter(
        (name) => name !== gate.capability,
      );
      const { room } = await openRoom({
        ready: { capabilities: { capabilities, authorization_version: 2 } },
      });
      expect(gate.read(room())).toBe(false);
    });

    it(`keeps ${gate.name} closed when only the impostor name is offered`, async () => {
      const capabilities = roomReady().capabilities.capabilities.map((name) =>
        name === gate.capability ? gate.impostor : name,
      );
      const { room } = await openRoom({
        ready: { capabilities: { capabilities, authorization_version: 2 } },
      });
      expect(gate.read(room())).toBe(false);
    });
  }

  it("hands back the room's capability list untouched", async () => {
    const { room } = await openRoom({
      ready: {
        capabilities: {
          capabilities: ["view_project", "view_runs", CAPABILITY_RUN],
          authorization_version: 7,
        },
      },
    });

    expect(room().capabilities).toEqual([
      "view_project",
      "view_runs",
      CAPABILITY_RUN,
    ]);
    expect(room().authorizationVersion).toBe(7);
  });

  it("keeps every gate closed until the room is ready", async () => {
    const hook = await renderHook(useProjectRoomSession, {
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
    });

    expect(hook.result.current.status).toBe("connecting");
    expect(hook.result.current.head).toBeNull();
    expect(hook.result.current.canRun).toBe(false);
    expect(hook.result.current.canSubmitCommands).toBe(false);
    expect(hook.result.current.canPublishPresence).toBe(false);

    // An open socket is not a ready room: only `room.ready` opens the gates.
    await settle(() => latestSocket().open());
    expect(hook.result.current.status).toBe("connecting");
    expect(hook.result.current.canRun).toBe(false);
  });

  it("answers canRun for a viewer who may watch but not ask for work", async () => {
    const { room } = await openRoom({
      ready: {
        capabilities: {
          capabilities: ["view_project", "view_runs", "join_project_room"],
          authorization_version: 3,
        },
      },
    });

    // Reading the room still works for a viewer; only acting does not.
    expect(room().status).toBe("ready");
    expect(room().head).not.toBeNull();
    expect(room().canRun).toBe(false);
    expect(room().canSubmitCommands).toBe(false);
    expect(room().canPublishPresence).toBe(false);
  });

  it("publishes presence only while the room allows it", async () => {
    const { room, socket } = await openRoom();
    expect(room().publishPresence({ cursor: { x: 1, y: 2 } })).toBe(true);
    expect(socket.sentFrames()).toContainEqual(
      expect.objectContaining({ type: "presence.update" }),
    );

    const viewer = await openRoom({
      ready: {
        capabilities: {
          capabilities: ["view_project", "join_project_room", CAPABILITY_EDIT],
          authorization_version: 2,
        },
      },
    });
    expect(viewer.room().publishPresence({ cursor: { x: 1, y: 2 } })).toBe(
      false,
    );
    expect(viewer.socket.sentFrames()).toEqual([]);
  });

  it("re-authorizes through the close a heartbeat triggers, never through the frame", async () => {
    const { room, push, close, reconnect } = await openRoom();
    expect(room().canRun).toBe(true);
    expect(room().authorizationVersion).toBe(2);

    // A heartbeat is a keepalive as far as this hook is concerned: it widens
    // nothing and does not restate what the room may do.
    await push({
      protocol_version: 1,
      type: "room.heartbeat",
      authorization_version: 9,
    });
    expect(room().authorizationVersion).toBe(2);
    expect(room().canRun).toBe(true);
    expect(room().status).toBe("ready");

    // The server's answer to a stale authorization is the close it triggers, and
    // that is what closes the gates.
    await close(4003, "permissions_changed");
    expect(room().status).toBe("unsynchronized");
    expect(room().terminalReason).toBeNull();
    expect(room().capabilities).toEqual([]);
    expect(room().canRun).toBe(false);

    // The room comes back and says what is allowed now.
    const next = await reconnect();
    await settle(() =>
      next.emitMessage(
        roomReady({
          head: projectHead({ collaboration_sequence: 5 }),
          capabilities: {
            capabilities: ["view_project", "join_project_room"],
            authorization_version: 9,
          },
        }),
      ),
    );

    expect(room().status).toBe("ready");
    expect(room().authorizationVersion).toBe(9);
    expect(room().canRun).toBe(false);
    expect(room().canSubmitCommands).toBe(false);
  });
});

describe("useProjectRoomSession head", () => {
  it("carries the head the room last confirmed, and keeps it when the room ends", async () => {
    const { room, push, close, socket } = await openRoom();
    const commands = [renameProject("Renamed in the room")];

    const submitted = room().submitCommands(commands);
    const [frame] = socket.sentFrames();
    // The batch left stamped with the head this client was looking at.
    expect(frame).toMatchObject({
      type: "project.command.submit",
      room_epoch: ROOM_EPOCH,
      observed_sequence: HEAD_SEQUENCE,
      commands,
    });
    const commandId = frame?.["command_id"];
    expect(typeof commandId).toBe("string");

    // The room applying it moves the hook's head, not just the session's.
    await push(
      commandAccepted(commandId as string, HEAD_SEQUENCE + 1, commands),
    );
    expect(room().head?.collaboration_sequence).toBe(HEAD_SEQUENCE + 1);
    expect(room().head?.name).toBe("Renamed in the room");

    await push(commandReceipt(commandId as string, HEAD_SEQUENCE + 1));
    const result = await submitted;
    expect(result.receipt.command_id).toBe(commandId);
    expect(result.head).toEqual(room().head);

    // What a closed room keeps is the head the room last confirmed, and it
    // confirms nothing further.
    await close(CLOSE_ACCESS_REVOKED, "access_revoked");
    expect(room().head?.collaboration_sequence).toBe(HEAD_SEQUENCE + 1);
    expect(room().canSubmitCommands).toBe(false);
  });
});

describe("useProjectRoomSession revisions", () => {
  it("reports revision 0 for a Project the room was never opened for", async () => {
    const { room } = await openRoom({ projectId: null });

    // The run hook reads 0 as "the room has not spoken yet" and does nothing,
    // so a room that does not exist must never look like it has pushed.
    expect(room().status).toBe("idle");
    expect(room().runsRevision).toBe(0);
    expect(room().instancesRevision).toBe(0);
    expect(room().activeRuns).toEqual([]);
    expect(room().instances.size).toBe(0);
  });

  it("carries a revision with every push, including one that changes nothing", async () => {
    const run = activeRun(RUN_ID, GRAPH_ID);
    const first = instanceState(GRAPH_ID, "n1", "running");
    const { room, push } = await openRoom();

    const runs: number[] = [room().runsRevision];
    const instances: number[] = [room().instancesRevision];
    // A ready room has spoken, whatever it said: both counters left zero.
    expect(runs[0]).toBeGreaterThan(0);
    expect(instances[0]).toBeGreaterThan(0);

    await push(runStarted(run));
    expect(room().activeRuns).toEqual([run]);
    runs.push(room().runsRevision);

    // The same Run announced twice: the list is identical, and a consumer still
    // has to be told to read it again.
    await push(runStarted(run));
    expect(room().activeRuns).toEqual([run]);
    runs.push(room().runsRevision);

    await push(runFinished(RUN_ID));
    expect(room().activeRuns).toEqual([]);
    runs.push(room().runsRevision);

    await push(instancesChanged([first], [], 5));
    expect(instanceKeys(room().instances)).toEqual([instanceKeyText(first)]);
    instances.push(room().instancesRevision);

    // The identical instance push: same key, same state, same map contents.
    await push(instancesChanged([first], [], 5));
    expect(instanceKeys(room().instances)).toEqual([instanceKeyText(first)]);
    expect(room().instances.get(instanceKeyText(first))).toEqual(first);
    instances.push(room().instancesRevision);

    // An empty delta is still a push: the room says something moved.
    await push(instancesChanged([], [], 6));
    expect(instanceKeys(room().instances)).toEqual([instanceKeyText(first)]);
    instances.push(room().instancesRevision);

    expect(strictlyIncreasing(runs)).toBe(true);
    expect(strictlyIncreasing(instances)).toBe(true);
  });

  it("moves both revisions again when the room re-reads after a drop", async () => {
    const run = activeRun(RUN_ID, GRAPH_ID);
    const instance = instanceState(GRAPH_ID, "n1", "running");
    const { socket, room, reconnect } = await openRoom({
      ready: { active_runs: [run], instances: [instance] },
    });

    const runsBefore = room().runsRevision;
    const instancesBefore = room().instancesRevision;

    await settle(() => socket.emitClose(1006, "connection_lost"));
    expect(room().activeRuns).toEqual([]);
    expect(room().instances.size).toBe(0);
    expect(room().status).toBe("unsynchronized");

    const reconnectSocket = await reconnect();
    await settle(() =>
      reconnectSocket.emitMessage(
        roomReady({
          head: projectHead({ collaboration_sequence: 5 }),
          active_runs: [run],
          instances: [instance],
        }),
      ),
    );

    // The snapshot holds the same content the client had before the drop, and
    // the counters moved anyway: a consumer must re-read, not compare.
    expect(room().activeRuns).toEqual([run]);
    expect(instanceKeys(room().instances)).toEqual([instanceKeyText(instance)]);
    expect(room().runsRevision).toBeGreaterThan(runsBefore);
    expect(room().instancesRevision).toBeGreaterThan(instancesBefore);
  });
});

describe("useProjectRoomSession after the room closes", () => {
  it("stops answering for a room whose access was revoked", async () => {
    const run = activeRun(RUN_ID, GRAPH_ID);
    const first = instanceState(GRAPH_ID, "n1", "fresh");
    const second = instanceState(OTHER_GRAPH_ID, "n2", "running");
    const { room, close, socket, callbacks } = await openRoom({
      ready: {
        participants: [
          participant(SESSION_ID, "Owner"),
          participant(PEER_SESSION_ID, "Peer"),
        ],
        active_runs: [run],
        instances: [first, second],
      },
    });

    // Everything the room can hand out, it has handed out.
    expect(room().canRun).toBe(true);
    expect(room().canSubmitCommands).toBe(true);
    expect(room().canPublishPresence).toBe(true);
    expect(room().participants).toHaveLength(2);
    const headBefore = room().head;
    expect(headBefore).not.toBeNull();
    const runsBefore = room().runsRevision;
    const instancesBefore = room().instancesRevision;

    await close(CLOSE_ACCESS_REVOKED, "access_revoked");

    const closed = room();
    expect(closed.status).toBe("stopped");
    expect(closed.terminalReason).toBe("access_revoked");
    expect(closed.failure).toMatchObject({
      reason: "access_revoked",
      retryable: false,
      workspaceId: WORKSPACE_ID,
      projectId: PROJECT_ID,
    });
    // Nothing derived from the room survives it.
    expect(closed.capabilities).toEqual([]);
    expect(closed.authorizationVersion).toBeNull();
    expect(closed.localSessionId).toBeNull();
    expect(closed.participants).toEqual([]);
    expect(closed.activeRuns).toEqual([]);
    expect(closed.instances.size).toBe(0);
    // And nothing derived from it is authorised any more.
    expect(closed.canRun).toBe(false);
    expect(closed.canSubmitCommands).toBe(false);
    expect(closed.canPublishPresence).toBe(false);
    expect(closed.publishPresence({ cursor: { x: 1, y: 2 } })).toBe(false);

    // The head is the one thing the terminal clear leaves in place: the session
    // drops capabilities, presence and authorization on a terminal close, not
    // the last confirmed snapshot, and this hook follows it. Pinned as it
    // stands, because the snapshot has no authority left — every gate that
    // could write with it is closed and the batch is refused before a frame is
    // produced.
    expect(closed.head).toEqual(headBefore);
    await expect(
      room().submitCommands([renameProject("After the door")]),
    ).rejects.toMatchObject({ errorCode: "not_ready" });
    expect(socket.sentFrames()).toEqual([]);

    // The counters never fall back to 0: a stale zero reads as "the room has
    // not spoken yet", which is how a surface ends up doing nothing forever.
    expect(room().runsRevision).toBeGreaterThan(runsBefore);
    expect(room().instancesRevision).toBeGreaterThan(instancesBefore);

    // A revoked room does not come back on retry; only a spent backoff does.
    const sockets = FakeWebSocket.instances.length;
    await settle(() => room().retry());
    expect(FakeWebSocket.instances).toHaveLength(sockets);
    expect(callbacks.onTerminalClose).toHaveBeenCalledWith("access_revoked");
  });

  it("answers nothing for a Project that was deleted under the room", async () => {
    const { room, close } = await openRoom({
      ready: {
        active_runs: [activeRun(RUN_ID, GRAPH_ID)],
        instances: [instanceState(GRAPH_ID, "n1", "fresh")],
      },
    });
    expect(room().instances.size).toBe(1);
    const instancesBefore = room().instancesRevision;

    await close(CLOSE_PROJECT_DELETED, "project_deleted");

    expect(room().status).toBe("stopped");
    expect(room().terminalReason).toBe("project_deleted");
    expect(room().activeRuns).toEqual([]);
    expect(room().instances.size).toBe(0);
    expect(room().capabilities).toEqual([]);
    expect(room().canRun).toBe(false);
    expect(room().instancesRevision).toBeGreaterThan(instancesBefore);
  });

  it("keeps a recoverable drop distinguishable from a terminal close", async () => {
    const { socket, room } = await openRoom({
      ready: { active_runs: [activeRun(RUN_ID, GRAPH_ID)] },
    });

    await settle(() => socket.emitClose(1006, "connection_lost"));

    // Loss of transport is not loss of the room: it is retryable, carries no
    // terminal reason, and the client still believes a room is coming back.
    expect(room().status).toBe("unsynchronized");
    expect(room().terminalReason).toBeNull();
    expect(room().failure).toMatchObject({
      reason: "connection_lost",
      retryable: true,
    });
    expect(room().canRun).toBe(false);
    expect(room().activeRuns).toEqual([]);
  });
});

describe("useProjectRoomSession project identity", () => {
  it("never answers for a room other than the Project in its props", async () => {
    const run = activeRun(RUN_ID, GRAPH_ID);
    const instance = instanceState(GRAPH_ID, "n1", "fresh");
    const { hook, props, room } = await openRoom({
      ready: { active_runs: [run], instances: [instance] },
    });
    expect(room().canRun).toBe(true);

    // Moving to another Project blanks the first one's room rather than
    // carrying its head, capabilities or derived state across the address.
    await hook.rerender({ ...props, projectId: ANOTHER_PROJECT_ID });

    expect(room().status).toBe("connecting");
    expect(room().head).toBeNull();
    expect(room().capabilities).toEqual([]);
    expect(room().participants).toEqual([]);
    expect(room().activeRuns).toEqual([]);
    expect(room().instances.size).toBe(0);
    expect(room().canRun).toBe(false);
    expect(room().localSessionId).toBeNull();

    const secondSocket = latestSocket();
    expect(secondSocket.url).toContain(ANOTHER_PROJECT_ID);
    await settle(() =>
      secondSocket.emitMessage(
        roomReady({
          project_id: ANOTHER_PROJECT_ID,
          head: projectHead({ project_id: ANOTHER_PROJECT_ID }),
        }),
      ),
    );

    expect(room().status).toBe("ready");
    expect(room().head?.project_id).toBe(ANOTHER_PROJECT_ID);
    expect(room().canRun).toBe(true);
  });

  it("blanks the room when the Project goes away", async () => {
    const run = activeRun(RUN_ID, GRAPH_ID);
    const instance = instanceState(GRAPH_ID, "n1", "fresh");
    const { hook, props, room, socket } = await openRoom({
      ready: {
        participants: [
          participant(SESSION_ID, "Owner"),
          participant(PEER_SESSION_ID, "Peer"),
        ],
        active_runs: [run],
        instances: [instance],
      },
    });
    expect(room().head).not.toBeNull();

    await hook.rerender({ ...props, projectId: null });

    // A canvas with no Project answers for no room — including the one it had
    // been holding, whose head and capabilities outlive a disconnect inside the
    // session and would otherwise still read as this canvas's own.
    expect(room().status).toBe("idle");
    expect(room().head).toBeNull();
    expect(room().capabilities).toEqual([]);
    expect(room().participants).toEqual([]);
    expect(room().activeRuns).toEqual([]);
    expect(room().instances.size).toBe(0);
    expect(room().localSessionId).toBeNull();
    expect(room().publishPresence({ cursor: { x: 1, y: 2 } })).toBe(false);
    await expect(
      room().submitCommands([renameProject("To no Project")]),
    ).rejects.toThrow(/not connected/);
    expect(socket.readyState).toBe(FakeWebSocket.CLOSED);
  });

  it("closes the room when the component goes away", async () => {
    const { hook, room, socket } = await openRoom();
    expect(room().status).toBe("ready");

    await hook.unmount();

    expect(socket.readyState).toBe(FakeWebSocket.CLOSED);
    expect(socket.sentFrames()).toEqual([]);
  });
});
