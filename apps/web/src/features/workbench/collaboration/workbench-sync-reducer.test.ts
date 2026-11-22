import { describe, expect, it } from "vitest";

import type { CollaborativeHead, GraphDefinition } from "@/lib/api";
import { runEffectReducer, runEffectSequence } from "@/lib/state";

import type { AuthoredGraphDocument } from "../authoring/graph-document";
import { toInGraphCommand } from "./room-command-bridge";
import {
  GRAPH_SWITCH_BLOCKED_MESSAGE,
  HEAD_REFRESH_RETRY_DELAY_MS,
  initialWorkbenchSyncState,
  nextNewGraphName,
  nextOpenGraphId,
  planRemoteCommandBatch,
  workbenchSyncReducer,
  type WorkbenchSyncAction,
  type WorkbenchSyncState,
} from "./workbench-sync-reducer";

const PROJECT_ID = "99999999-9999-4999-8999-999999999991";
const OTHER_PROJECT_ID = "88888888-8888-4888-8888-888888888888";
const GRAPH_ID = "11111111-1111-4111-8111-111111111111";
const OTHER_GRAPH_ID = "66666666-6666-4666-8666-666666666666";

const EMPTY_PRESENTATION = {
  viewers: [],
  links: [],
  bindings: [],
  annotations: [],
};

function graph(graphId: string, name: string): GraphDefinition {
  return {
    id: graphId,
    name,
    document: {
      schema_version: 7,
      nodes: [],
      edges: [],
      origins: [],
      agents: [],
      presentation: EMPTY_PRESENTATION,
    },
  };
}

function head(
  graphs: readonly GraphDefinition[] = [
    graph(GRAPH_ID, "Demo"),
    graph(OTHER_GRAPH_ID, "Other"),
  ],
  projectId = PROJECT_ID,
): CollaborativeHead {
  return {
    project_id: projectId,
    room_epoch: "22222222-2222-4222-8222-222222222222",
    collaboration_sequence: 3,
    checkpoint_sequence: 3,
    checkpoint_revision: 1,
    name: "Room project",
    updated_at: "2026-08-07T12:00:00Z",
    document: { graphs },
  };
}

const document: AuthoredGraphDocument = {
  name: "Demo",
  nodes: [],
  edges: [],
  origins: [],
  agents: [],
};

function state(
  overrides: Partial<WorkbenchSyncState> = {},
): WorkbenchSyncState {
  return { ...initialWorkbenchSyncState(PROJECT_ID), ...overrides };
}

function step(current: WorkbenchSyncState, action: WorkbenchSyncAction) {
  return runEffectReducer(workbenchSyncReducer, current, action);
}

const fetching = (
  requestId: number,
  errorMessage: string | null = null,
): WorkbenchSyncState["headRefreshPhase"] => ({
  kind: "fetching",
  requestId,
  errorMessage,
});

describe("nextOpenGraphId", () => {
  it("keeps the open Graph when the head still holds it", () => {
    expect(nextOpenGraphId(head(), GRAPH_ID)).toBe(GRAPH_ID);
  });

  it("falls back to the Project's first Graph when the open one is gone", () => {
    expect(nextOpenGraphId(head(), "missing")).toBe(GRAPH_ID);
    expect(nextOpenGraphId(head(), null)).toBe(GRAPH_ID);
    expect(nextOpenGraphId(head([]), GRAPH_ID)).toBeNull();
  });
});

describe("room snapshots", () => {
  const roomHead = head();

  it("syncs the canvas from room.ready and remembers a replay while commands are pending", () => {
    const pending = state({
      roomCommandsPending: true,
      openGraphId: OTHER_GRAPH_ID,
      unsyncedRoomEdits: true,
    });
    const result = step(pending, { kind: "roomReady", head: roomHead });

    expect(result.state).toMatchObject({
      openGraphId: OTHER_GRAPH_ID,
      unsyncedRoomEdits: false,
      replayingCanvasProjectId: PROJECT_ID,
      roomCommandsPending: true,
    });
    expect(result.effects).toEqual([
      { kind: "syncCanvasFromHead", head: roomHead },
    ]);
  });

  it("does not arm a replay when the outbox is already empty", () => {
    const current = state({
      roomCommandsPending: false,
      openGraphId: null,
      unsyncedRoomEdits: true,
    });
    const ready = step(current, { kind: "roomRehydrate", head: roomHead });
    expect(ready.state.replayingCanvasProjectId).toBeNull();
    expect(ready.state.openGraphId).toBe(GRAPH_ID);
    expect(ready.state.unsyncedRoomEdits).toBe(false);
  });

  it("projects the confirmed head once the pending replay drains", () => {
    const replaying = state({
      roomCommandsPending: true,
      replayingCanvasProjectId: PROJECT_ID,
      openGraphId: "missing",
      unsyncedRoomEdits: true,
    });
    const result = runEffectSequence(workbenchSyncReducer, replaying, [
      {
        kind: "roomPendingCommandsChanged",
        pending: false,
        roomStatus: "ready",
        head: roomHead,
      },
    ]);

    expect(result.state).toMatchObject({
      roomCommandsPending: false,
      replayingCanvasProjectId: null,
      unsyncedRoomEdits: false,
      openGraphId: GRAPH_ID,
    });
    expect(result.effects).toEqual([
      { kind: "syncCanvasFromHead", head: roomHead },
    ]);
  });

  it("does not replay a drain for a different Project, a room that is not ready, or an unchanged flag", () => {
    const replaying = state({
      roomCommandsPending: true,
      replayingCanvasProjectId: PROJECT_ID,
    });
    const otherProject = step(replaying, {
      kind: "roomPendingCommandsChanged",
      pending: false,
      roomStatus: "ready",
      head: head(undefined, OTHER_PROJECT_ID),
    });
    expect(otherProject.effects).toEqual([]);
    expect(otherProject.state.replayingCanvasProjectId).toBe(PROJECT_ID);

    const connecting = step(replaying, {
      kind: "roomPendingCommandsChanged",
      pending: false,
      roomStatus: "connecting",
      head: roomHead,
    });
    expect(connecting.effects).toEqual([]);
    expect(connecting.state.roomCommandsPending).toBe(false);

    const unchanged = state({ roomCommandsPending: false });
    const same = step(unchanged, {
      kind: "roomPendingCommandsChanged",
      pending: false,
      roomStatus: "ready",
      head: roomHead,
    });
    expect(same.state).toBe(unchanged);
    expect(same.effects).toEqual([]);
  });
});

describe("accepted and rejected commands", () => {
  const roomHead = head();

  it("resyncs and clears the call trail when a structural command removes the open Graph", () => {
    const current = state({
      openGraphId: GRAPH_ID,
      unsyncedRoomEdits: true,
      callTrail: [{ graphId: OTHER_GRAPH_ID, nodeId: "call", name: "Other" }],
    });
    const result = step(current, {
      kind: "roomCommandAccepted",
      local: true,
      head: head([graph(OTHER_GRAPH_ID, "Other")]),
      commands: [{ kind: "remove_graph", graph_id: GRAPH_ID }],
    });

    expect(result.state.openGraphId).toBe(OTHER_GRAPH_ID);
    expect(result.state.unsyncedRoomEdits).toBe(false);
    expect(result.state.callTrail).toEqual([]);
    expect(result.effects).toEqual([
      {
        kind: "syncCanvasFromHead",
        head: head([graph(OTHER_GRAPH_ID, "Other")]),
      },
    ]);
  });

  it("leaves a local non-structural acceptance on the canvas that already applied it", () => {
    const current = state({ openGraphId: GRAPH_ID });
    const result = step(current, {
      kind: "roomCommandAccepted",
      local: true,
      head: roomHead,
      commands: [
        toInGraphCommand(GRAPH_ID, {
          kind: "move_nodes",
          positions: [{ node_id: "a", x: 1, y: 2 }],
        }),
      ],
    });
    expect(result.state).toBe(current);
    expect(result.effects).toEqual([]);
  });

  it("hands a remote batch to the open canvas", () => {
    const current = state({ openGraphId: GRAPH_ID });
    const commands = [
      toInGraphCommand(GRAPH_ID, {
        kind: "move_nodes",
        positions: [{ node_id: "a", x: 1, y: 2 }],
      }),
    ];
    const result = step(current, {
      kind: "roomCommandAccepted",
      local: false,
      head: roomHead,
      commands,
    });
    expect(result.state).toBe(current);
    expect(result.effects).toEqual([
      {
        kind: "applyRemoteCommandBatch",
        commands,
        openGraphId: GRAPH_ID,
        head: roomHead,
      },
    ]);
  });

  it("reports a rejection and refreshes, except a head conflict which only refreshes", () => {
    const current = state();
    const conflict = step(current, {
      kind: "roomCommandRejected",
      errorCode: "head_conflict",
      detail: "stale",
    });
    expect(conflict.effects.map((effect) => effect.kind)).toEqual([
      "abortHeadRefresh",
      "fetchCollaborativeHead",
    ]);
    expect(conflict.effects[1]).toMatchObject({
      projectId: PROJECT_ID,
      requestId: 1,
      errorMessage: null,
    });
    expect(conflict.state.headRefreshPhase).toEqual(fetching(1, null));

    const rejected = step(current, {
      kind: "roomCommandRejected",
      errorCode: "invalid",
      detail: "",
    });
    expect(rejected.effects[0]).toEqual({
      kind: "reportError",
      message: "A collaborative edit was rejected.",
    });
    expect(rejected.effects[2]).toMatchObject({
      kind: "fetchCollaborativeHead",
      errorMessage: "A collaborative edit was rejected.",
    });
  });

  it("does not fetch a head when the Workbench has no Project", () => {
    const detached = initialWorkbenchSyncState(null);
    const result = step(detached, {
      kind: "roomCommandRejected",
      errorCode: "invalid",
      detail: "nope",
    });
    expect(result.state).toBe(detached);
    expect(result.effects).toEqual([{ kind: "reportError", message: "nope" }]);
  });
});

describe("submit failures", () => {
  const current = state();

  it.each(["not_ready", "send_failed", "reconnect_exhausted"] as const)(
    "marks %s unsynced and reports it",
    (errorCode) => {
      const result = step(current, {
        kind: "roomSubmitFailed",
        errorCode,
        message: null,
        fallback: "Collaborative sync failed.",
      });
      expect(result.state.unsyncedRoomEdits).toBe(true);
      expect(result.state.headRefreshPhase).toEqual({ kind: "idle" });
      expect(result.effects).toEqual([
        { kind: "reportError", message: "Collaborative sync failed." },
      ]);
    },
  );

  it("refreshes after a full queue and still reports the failure", () => {
    const result = step(current, {
      kind: "roomSubmitFailed",
      errorCode: "queue_full",
      message: "Queue full",
      fallback: "Collaborative sync failed.",
    });
    expect(result.state.unsyncedRoomEdits).toBe(true);
    expect(result.state.headRefreshPhase).toEqual(fetching(1, null));
    expect(result.effects.map((effect) => effect.kind)).toEqual([
      "abortHeadRefresh",
      "fetchCollaborativeHead",
      "reportError",
    ]);
    expect(result.effects[2]).toEqual({
      kind: "reportError",
      message: "Queue full",
    });
  });

  it("suppresses superseded and head_conflict submit failures", () => {
    for (const errorCode of ["superseded", "head_conflict"] as const) {
      const result = step(current, {
        kind: "roomSubmitFailed",
        errorCode,
        message: "hidden",
        fallback: "Collaborative sync failed.",
      });
      expect(result.state).toBe(current);
      expect(result.effects).toEqual([]);
    }
  });
});

describe("terminal close", () => {
  it("purges local state and leaves the Workspace when access or the Project is gone", () => {
    const current = state({ headRefreshPhase: fetching(4, "earlier") });
    const result = step(current, {
      kind: "roomTerminalClosed",
      reason: "project_deleted",
      workspaceSlug: "alpha/team",
    });
    expect(result.state.headRefreshPhase).toEqual({ kind: "idle" });
    expect(result.effects).toEqual([
      { kind: "abortHeadRefresh" },
      { kind: "cancelHeadRefreshRetry" },
      { kind: "purgeLocalGraphState" },
      { kind: "navigateToWorkspace", workspaceSlug: "alpha/team" },
    ]);

    const idle = state();
    const revoked = step(idle, {
      kind: "roomTerminalClosed",
      reason: "access_revoked",
      workspaceSlug: "alpha",
    });
    expect(revoked.state).toBe(idle);
    expect(revoked.effects.map((effect) => effect.kind)).toEqual([
      "purgeLocalGraphState",
      "navigateToWorkspace",
    ]);
  });

  it("ignores a recoverable terminal reason", () => {
    const current = state();
    const result = step(current, {
      kind: "roomTerminalClosed",
      reason: "reconnect_exhausted",
      workspaceSlug: "alpha",
    });
    expect(result.state).toBe(current);
    expect(result.effects).toEqual([]);
  });
});

describe("head refresh", () => {
  it("does nothing without a Project", () => {
    const detached = initialWorkbenchSyncState(null);
    const result = step(detached, { kind: "requestHeadRefresh" });
    expect(result.state).toBe(detached);
    expect(result.effects).toEqual([]);
  });

  it("aborts the previous fetch and ignores its result", () => {
    const first = step(state(), {
      kind: "requestHeadRefresh",
      errorMessage: "first",
    });
    const second = step(first.state, { kind: "requestHeadRefresh" });
    expect(second.state.headRefreshPhase).toEqual(fetching(2, null));
    expect(second.state.nextRefreshToken).toBe(2);
    expect(second.effects[0]).toEqual({ kind: "abortHeadRefresh" });

    const stale = step(second.state, {
      kind: "headRefreshSucceeded",
      requestId: 1,
      head: head(),
    });
    expect(stale.state).toBe(second.state);
    expect(stale.effects).toEqual([]);

    const staleFailure = step(second.state, {
      kind: "headRefreshFailed",
      requestId: 1,
      message: "late",
    });
    expect(staleFailure.state).toBe(second.state);
    expect(staleFailure.effects).toEqual([]);
  });

  it("installs a successful head and drops unsynced edits", () => {
    const fetchingState = state({
      headRefreshPhase: fetching(3, "detail"),
      nextRefreshToken: 3,
      unsyncedRoomEdits: true,
      roomCommandsPending: true,
      openGraphId: "missing",
    });
    const result = step(fetchingState, {
      kind: "headRefreshSucceeded",
      requestId: 3,
      head: head(),
    });
    expect(result.state).toMatchObject({
      headRefreshPhase: { kind: "idle" },
      unsyncedRoomEdits: false,
      replayingCanvasProjectId: PROJECT_ID,
      openGraphId: GRAPH_ID,
      nextRefreshToken: 3,
    });
    expect(result.effects).toEqual([
      { kind: "cancelHeadRefreshRetry" },
      { kind: "replaceRoomHeadAndSyncCanvas", head: head() },
    ]);
  });

  it("reports the refresh error and schedules one retry", () => {
    const withDetail = state({
      headRefreshPhase: fetching(2, "kept"),
      nextRefreshToken: 2,
    });
    const failed = step(withDetail, {
      kind: "headRefreshFailed",
      requestId: 2,
      message: "network",
    });
    expect(failed.state.headRefreshPhase).toEqual({
      kind: "retryScheduled",
      retryId: 3,
      errorMessage: "kept",
    });
    expect(failed.state.nextRefreshToken).toBe(3);
    expect(failed.effects).toEqual([
      { kind: "reportError", message: "kept" },
      {
        kind: "scheduleHeadRefreshRetry",
        retryId: 3,
        delayMs: HEAD_REFRESH_RETRY_DELAY_MS,
        errorMessage: "kept",
      },
    ]);

    const withoutDetail = state({
      headRefreshPhase: fetching(1, null),
      nextRefreshToken: 1,
    });
    const fallback = step(withoutDetail, {
      kind: "headRefreshFailed",
      requestId: 1,
      message: "The Project head could not be refreshed.",
    });
    expect(fallback.effects[0]).toEqual({
      kind: "reportError",
      message: "The Project head could not be refreshed.",
    });
  });

  it("ignores a stale or early retry and fetches again when the scheduled one fires", () => {
    const scheduled = state({
      headRefreshPhase: {
        kind: "retryScheduled",
        retryId: 4,
        errorMessage: "kept",
      },
      nextRefreshToken: 4,
    });
    const stale = step(scheduled, {
      kind: "headRefreshRetryFired",
      retryId: 3,
    });
    expect(stale.state).toBe(scheduled);

    const whileFetching = step(
      state({ headRefreshPhase: fetching(4, "kept"), nextRefreshToken: 4 }),
      { kind: "headRefreshRetryFired", retryId: 4 },
    );
    expect(whileFetching.effects).toEqual([]);

    const detached = step(
      {
        ...scheduled,
        projectId: null,
      },
      { kind: "headRefreshRetryFired", retryId: 4 },
    );
    expect(detached.effects).toEqual([]);

    const fired = step(scheduled, {
      kind: "headRefreshRetryFired",
      retryId: 4,
    });
    expect(fired.state.headRefreshPhase).toEqual(fetching(5, "kept"));
    expect(fired.effects).toEqual([
      {
        kind: "fetchCollaborativeHead",
        projectId: PROJECT_ID,
        requestId: 5,
        errorMessage: "kept",
      },
    ]);
  });

  it("walks from failure through a retry to a settled head", () => {
    const result = runEffectSequence(workbenchSyncReducer, state(), [
      { kind: "requestHeadRefresh", errorMessage: "detail" },
      { kind: "headRefreshFailed", requestId: 1, message: "network" },
      { kind: "headRefreshRetryFired", retryId: 2 },
      { kind: "headRefreshSucceeded", requestId: 3, head: head() },
    ]);
    expect(result.state.headRefreshPhase).toEqual({ kind: "idle" });
    expect(result.state.openGraphId).toBe(GRAPH_ID);
    expect(result.state.unsyncedRoomEdits).toBe(false);
    expect(result.effects.map((effect) => effect.kind)).toEqual([
      "abortHeadRefresh",
      "fetchCollaborativeHead",
      "reportError",
      "scheduleHeadRefreshRetry",
      "fetchCollaborativeHead",
      "cancelHeadRefreshRetry",
      "replaceRoomHeadAndSyncCanvas",
    ]);
  });
});

describe("project and open Graph", () => {
  it("resets Project-scoped sync state when the Project changes", () => {
    const current = state({
      openGraphId: GRAPH_ID,
      unsyncedRoomEdits: true,
      roomCommandsPending: true,
      replayingCanvasProjectId: PROJECT_ID,
      callTrail: [{ graphId: GRAPH_ID, nodeId: "n", name: "Demo" }],
      headRefreshPhase: fetching(2, "detail"),
      nextRefreshToken: 2,
    });
    const result = step(current, {
      kind: "setProject",
      projectId: OTHER_PROJECT_ID,
    });
    expect(result.state).toMatchObject({
      projectId: OTHER_PROJECT_ID,
      openGraphId: null,
      unsyncedRoomEdits: false,
      roomCommandsPending: false,
      replayingCanvasProjectId: null,
      callTrail: [],
      headRefreshPhase: { kind: "idle" },
      nextRefreshToken: 2,
    });
    expect(result.effects).toEqual([
      { kind: "abortHeadRefresh" },
      { kind: "cancelHeadRefreshRetry" },
    ]);

    const same = step(result.state, {
      kind: "setProject",
      projectId: OTHER_PROJECT_ID,
    });
    expect(same.state).toBe(result.state);
  });

  it("records the Graph a direct open chose", () => {
    const current = state({ openGraphId: GRAPH_ID });
    const result = step(current, {
      kind: "syncOpenGraphId",
      graphId: OTHER_GRAPH_ID,
    });
    expect(result.state.openGraphId).toBe(OTHER_GRAPH_ID);
    expect(
      step(result.state, { kind: "syncOpenGraphId", graphId: OTHER_GRAPH_ID })
        .state,
    ).toBe(result.state);
  });
});

describe("graph switching and the call stack", () => {
  const roomHead = head();
  const idle = {
    head: roomHead,
    isExecutionRunning: false,
    isDirty: false,
  };

  it("opens another Graph and replaces the call trail", () => {
    const current = state({
      openGraphId: GRAPH_ID,
      callTrail: [{ graphId: "old", nodeId: "old", name: "Old" }],
    });
    const trail = [{ graphId: GRAPH_ID, nodeId: "n", name: "Demo" }];
    const result = step(current, {
      kind: "switchGraph",
      targetGraphId: OTHER_GRAPH_ID,
      nextTrail: trail,
      ...idle,
    });
    expect(result.state.openGraphId).toBe(OTHER_GRAPH_ID);
    expect(result.state.callTrail).toEqual(trail);
    expect(result.effects).toEqual([
      {
        kind: "openGraphInProject",
        head: roomHead,
        graphId: OTHER_GRAPH_ID,
      },
    ]);
  });

  it("refuses to switch while a run is open or the canvas is dirty", () => {
    const current = state({ openGraphId: GRAPH_ID });
    for (const flag of ["isExecutionRunning", "isDirty"] as const) {
      const result = step(current, {
        kind: "switchGraph",
        targetGraphId: OTHER_GRAPH_ID,
        nextTrail: [],
        head: roomHead,
        isExecutionRunning: flag === "isExecutionRunning",
        isDirty: flag === "isDirty",
      });
      expect(result.state).toBe(current);
      expect(result.effects).toEqual([
        { kind: "reportError", message: GRAPH_SWITCH_BLOCKED_MESSAGE },
      ]);
    }
  });

  it("no-ops when the target is already open or there is no head", () => {
    const current = state({ openGraphId: GRAPH_ID });
    const same = step(current, {
      kind: "switchGraph",
      targetGraphId: GRAPH_ID,
      nextTrail: [],
      ...idle,
      isDirty: true,
    });
    expect(same.state).toBe(current);
    expect(same.effects).toEqual([]);

    const missing = step(current, {
      kind: "switchGraph",
      targetGraphId: OTHER_GRAPH_ID,
      nextTrail: [],
      head: null,
      isExecutionRunning: false,
      isDirty: false,
    });
    expect(missing.state).toBe(current);
    expect(missing.effects).toEqual([]);
  });

  it("pushes the caller onto the trail when a call opens", () => {
    const current = state({ openGraphId: GRAPH_ID, callTrail: [] });
    const result = step(current, {
      kind: "openCall",
      nodeId: "call-1",
      calleeGraphId: OTHER_GRAPH_ID,
      ...idle,
    });
    expect(result.state.openGraphId).toBe(OTHER_GRAPH_ID);
    expect(result.state.callTrail).toEqual([
      { graphId: GRAPH_ID, nodeId: "call-1", name: "Demo" },
    ]);
    expect(result.effects).toEqual([
      {
        kind: "openGraphInProject",
        head: roomHead,
        graphId: OTHER_GRAPH_ID,
      },
    ]);
  });

  it("does not push a call when the caller is missing or the switch is blocked", () => {
    const noCaller = step(state({ openGraphId: null }), {
      kind: "openCall",
      nodeId: "call-1",
      calleeGraphId: OTHER_GRAPH_ID,
      ...idle,
    });
    expect(noCaller.effects).toEqual([]);

    const unknown = step(state({ openGraphId: "missing" }), {
      kind: "openCall",
      nodeId: "call-1",
      calleeGraphId: OTHER_GRAPH_ID,
      ...idle,
    });
    expect(unknown.effects).toEqual([]);

    const dirty = state({ openGraphId: GRAPH_ID });
    const blocked = step(dirty, {
      kind: "openCall",
      nodeId: "call-1",
      calleeGraphId: OTHER_GRAPH_ID,
      head: roomHead,
      isExecutionRunning: false,
      isDirty: true,
    });
    expect(blocked.state).toBe(dirty);
    expect(blocked.state.callTrail).toEqual([]);
  });

  it("pops the call trail when stepping back", () => {
    const trail = [
      { graphId: GRAPH_ID, nodeId: "call-1", name: "Demo" },
      { graphId: OTHER_GRAPH_ID, nodeId: "call-2", name: "Other" },
    ];
    const current = state({ openGraphId: "inner", callTrail: trail });
    const result = step(current, { kind: "backFromCall", ...idle });
    expect(result.state.openGraphId).toBe(OTHER_GRAPH_ID);
    expect(result.state.callTrail).toEqual([trail[0]]);

    const top = step(state({ openGraphId: GRAPH_ID, callTrail: [] }), {
      kind: "backFromCall",
      ...idle,
    });
    expect(top.effects).toEqual([]);
  });
});

describe("planRemoteCommandBatch", () => {
  const presentation = {
    viewers: [
      {
        id: "viewer-1",
        position: { x: 1, y: 2 },
        layout: null,
        mode: null,
      },
    ],
    links: [],
    bindings: [],
    annotations: [],
  };

  it("maps the open Graph's commands and skips the rest of the Project", () => {
    const plan = planRemoteCommandBatch(
      [
        toInGraphCommand(OTHER_GRAPH_ID, {
          kind: "move_nodes",
          positions: [{ node_id: "a", x: 9, y: 9 }],
        }),
        { kind: "rename_project", name: "Next", expected_name: "Room project" },
        { kind: "add_graph", graph_id: "new", name: "Added" },
        {
          kind: "refresh_node",
          graph_id: GRAPH_ID,
          node_id: "a",
          expected_generation: 1,
        },
        {
          kind: "rename_graph",
          graph_id: OTHER_GRAPH_ID,
          name: "Else",
          expected_name: "Other",
        },
        {
          kind: "rename_graph",
          graph_id: GRAPH_ID,
          name: "Renamed",
          expected_name: "Demo",
        },
        toInGraphCommand(GRAPH_ID, {
          kind: "replace_presentation",
          presentation,
        }),
        toInGraphCommand(GRAPH_ID, {
          kind: "move_artifact_viewers",
          positions: [{ viewer_id: "viewer-1", x: 4, y: 5 }],
        }),
        toInGraphCommand(GRAPH_ID, {
          kind: "move_annotations",
          positions: [{ annotation_id: "note-1", x: 6, y: 7 }],
        }),
        toInGraphCommand(GRAPH_ID, {
          kind: "move_nodes",
          positions: [{ node_id: "a", x: 8, y: 9 }],
        }),
      ],
      GRAPH_ID,
      document,
    );

    expect(plan).toEqual({
      kind: "apply",
      steps: [
        { kind: "replacePresentation", presentation },
        {
          kind: "moveArtifactViewers",
          positions: [{ viewer_id: "viewer-1", x: 4, y: 5 }],
        },
        {
          kind: "moveAnnotations",
          positions: [{ annotation_id: "note-1", x: 6, y: 7 }],
        },
        {
          kind: "localGraphCommands",
          commands: [
            { kind: "rename_graph", name: "Renamed" },
            {
              kind: "move_nodes",
              positions: [{ node_id: "a", x: 8, y: 9 }],
            },
          ],
        },
      ],
    });
  });

  it("carries a document rewrite's presentation and its local command", () => {
    const plan = planRemoteCommandBatch(
      [
        toInGraphCommand(GRAPH_ID, {
          kind: "replace_document",
          document: {
            schema_version: 7,
            nodes: [],
            edges: [],
            origins: [],
            agents: [],
            presentation,
          },
        }),
      ],
      GRAPH_ID,
      document,
    );
    expect(plan.kind).toBe("apply");
    if (plan.kind !== "apply") return;
    expect(plan.steps[0]).toEqual({
      kind: "replacePresentation",
      presentation,
    });
    expect(plan.steps[1]).toMatchObject({
      kind: "localGraphCommands",
      commands: [{ kind: "replace_document" }],
    });
  });

  it("asks for a head refresh when a command needs Project hydration", () => {
    const call = planRemoteCommandBatch(
      [
        toInGraphCommand(GRAPH_ID, {
          kind: "move_nodes",
          positions: [{ node_id: "a", x: 1, y: 2 }],
        }),
        {
          kind: "add_call_node",
          graph_id: GRAPH_ID,
          node_id: "call-1",
          callee_graph_id: OTHER_GRAPH_ID,
          position: { x: 1, y: 2 },
        },
      ],
      GRAPH_ID,
      document,
    );
    expect(call).toEqual({ kind: "needsHeadRefresh" });

    const unmapped = planRemoteCommandBatch(
      [
        toInGraphCommand(GRAPH_ID, {
          kind: "set_node_input_plugs",
          node_id: "missing",
          input_plugs: [],
          expected_plug_ids: [],
        }),
      ],
      GRAPH_ID,
      document,
    );
    expect(unmapped).toEqual({ kind: "needsHeadRefresh" });
  });

  it("returns an empty apply when every command belongs to another Graph", () => {
    const plan = planRemoteCommandBatch(
      [
        toInGraphCommand(OTHER_GRAPH_ID, {
          kind: "move_nodes",
          positions: [{ node_id: "a", x: 1, y: 2 }],
        }),
      ],
      null,
      document,
    );
    expect(plan).toEqual({ kind: "apply", steps: [] });
  });
});

describe("nextNewGraphName", () => {
  it("keeps the document name for the first Graph", () => {
    expect(nextNewGraphName([], "  Draft  ")).toBe("Draft");
    expect(nextNewGraphName([], "   ")).toBe("Untitled workflow");
  });

  it("picks the next free Graph N", () => {
    expect(nextNewGraphName([{ name: "Demo" }], "Demo")).toBe("Graph 2");
    expect(
      nextNewGraphName(
        [{ name: "Demo" }, { name: "Graph 2" }, { name: "GRAPH 3" }],
        "Demo",
      ),
    ).toBe("Graph 4");
  });
});
