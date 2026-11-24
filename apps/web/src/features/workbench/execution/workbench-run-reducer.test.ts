import { describe, expect, it } from "vitest";

import {
  runEffectReducer,
  runEffectSequence,
} from "@/lib/state/effect-reducer";

import {
  initialWorkbenchRunState,
  workbenchRunReducer,
  type WorkbenchRunAction,
  type WorkbenchRunState,
} from "./workbench-run-reducer";

function step(state: WorkbenchRunState, action: WorkbenchRunAction) {
  return runEffectReducer(workbenchRunReducer, state, action);
}

function sequence(...actions: WorkbenchRunAction[]) {
  return runEffectSequence(
    workbenchRunReducer,
    initialWorkbenchRunState(),
    actions,
  );
}

const requestCancel = {
  kind: "requestCancelRun",
  projectId: "project",
  runId: "run-1",
} satisfies WorkbenchRunAction;

const syncRunning = {
  kind: "syncExecution",
  running: true,
  runningScope: "selected",
  announcement: "Run queued",
} satisfies WorkbenchRunAction;

const historyTarget = { nodeId: "node-1", executionId: null };

describe("workbenchRunReducer", () => {
  it("sets and replaces the transient error, preserving identity for the same message", () => {
    const first = step(initialWorkbenchRunState(), {
      kind: "setError",
      message: "First error",
    });
    expect(first.state.error).toBe("First error");
    expect(first.effects).toEqual([]);
    const same = step(first.state, {
      kind: "setError",
      message: "First error",
    });
    expect(same.state).toBe(first.state);
    expect(same.effects).toEqual([]);

    const second = step(same.state, {
      kind: "setError",
      message: "Second error",
    });
    expect(second.state.error).toBe("Second error");
    expect(
      step(second.state, { kind: "setError", message: null }).state.error,
    ).toBeNull();
  });

  it("clears both error channels even when the transient channel is empty", () => {
    const result = sequence(
      { kind: "setError", message: "Run failed" },
      { kind: "clearError" },
    );
    expect(result.state.error).toBeNull();
    expect(result.effects).toEqual([{ kind: "clearAuthoringError" }]);

    const again = step(result.state, { kind: "clearError" });
    expect(again.state).toBe(result.state);
    expect(again.effects).toEqual([{ kind: "clearAuthoringError" }]);
  });

  it("dismisses only the matching transient error and asks the host to match the authoring error", () => {
    const { state } = sequence({ kind: "setError", message: "Latest error" });
    const older = step(state, { kind: "dismissError", message: "Older error" });
    expect(older.state).toBe(state);
    expect(older.effects).toEqual([
      { kind: "clearAuthoringErrorIfMatches", message: "Older error" },
    ]);

    const latest = step(state, {
      kind: "dismissError",
      message: "Latest error",
    });
    expect(latest.state.error).toBeNull();
    expect(latest.effects).toEqual([
      { kind: "clearAuthoringErrorIfMatches", message: "Latest error" },
    ]);
  });

  it("requests the selected nodes while idle and ignores requests while running", () => {
    const idle = initialWorkbenchRunState();
    const requested = step(idle, {
      kind: "requestRun",
      scope: "selected",
      explicitNodeIds: ["node-1"],
    });
    expect(requested.state).toBe(idle);
    expect(requested.effects).toEqual([
      {
        kind: "startRunWorkflow",
        scope: "selected",
        explicitNodeIds: ["node-1"],
      },
    ]);

    expect(step(idle, { kind: "requestRun", scope: "all" }).effects).toEqual([
      { kind: "startRunWorkflow", scope: "all", explicitNodeIds: undefined },
    ]);

    const { state } = sequence(syncRunning);
    const ignored = step(state, { kind: "requestRun", scope: "all" });
    expect(ignored.state).toBe(state);
    expect(ignored.effects).toEqual([]);
  });

  it("synchronizes execution fields and preserves identity on a repeated snapshot", () => {
    const { state, effects } = sequence(
      { kind: "setError", message: "Run error" },
      syncRunning,
    );
    expect(state).toEqual({
      error: "Run error",
      cancelPhase: { kind: "idle" },
      historyTarget: null,
      running: true,
      runningScope: "selected",
      announcement: "Run queued",
    });
    expect(effects).toEqual([]);
    const repeated = step(state, syncRunning);
    expect(repeated.state).toBe(state);
    expect(repeated.effects).toEqual([]);

    const settled = step(state, {
      kind: "syncExecution",
      running: false,
      runningScope: null,
      announcement: "Run finished",
    });
    expect(settled.state).toMatchObject({
      running: false,
      runningScope: null,
      announcement: "Run finished",
    });
  });

  it("requires a project and allows only one cancellation at a time", () => {
    const idle = initialWorkbenchRunState();
    const missingProject = step(idle, { ...requestCancel, projectId: null });
    expect(missingProject.state).toBe(idle);
    expect(missingProject.effects).toEqual([]);

    const requested = step(idle, requestCancel);
    expect(requested.state.cancelPhase).toEqual({
      kind: "cancelling",
      runId: "run-1",
    });
    expect(requested.effects).toEqual([
      { kind: "cancelGraphRun", projectId: "project", runId: "run-1" },
    ]);

    const concurrent = step(requested.state, {
      ...requestCancel,
      runId: "run-2",
    });
    expect(concurrent.state).toBe(requested.state);
    expect(concurrent.effects).toEqual([]);
  });

  it("accepts success only for the pending cancellation and keeps the existing error", () => {
    const { state } = sequence(
      { kind: "setError", message: "Existing error" },
      requestCancel,
    );
    const stale = step(state, {
      kind: "cancelRunSucceeded",
      runId: "older-run",
    });
    expect(stale.state).toBe(state);
    expect(stale.effects).toEqual([]);

    const matched = step(state, { kind: "cancelRunSucceeded", runId: "run-1" });
    expect(matched.state.cancelPhase).toEqual({ kind: "idle" });
    expect(matched.state.error).toBe("Existing error");
    expect(matched.effects).toEqual([]);
    expect(
      step(matched.state, { kind: "cancelRunSucceeded", runId: "run-1" }).state,
    ).toBe(matched.state);
  });

  it("returns to idle with an error only when the pending cancellation fails", () => {
    const { state } = sequence(requestCancel);
    const failed = {
      kind: "cancelRunFailed",
      runId: "run-1",
      message: "Cancellation failed",
    } satisfies WorkbenchRunAction;
    const stale = step(state, { ...failed, runId: "older-run" });
    expect(stale.state).toBe(state);
    expect(stale.effects).toEqual([]);

    const matched = step(state, failed);
    expect(matched.state.cancelPhase).toEqual({ kind: "idle" });
    expect(matched.state.error).toBe("Cancellation failed");
    expect(matched.effects).toEqual([]);
    expect(step(matched.state, failed).state).toBe(matched.state);
  });

  it("opens history and closes the graph browser, then closes history independently", () => {
    const opened = sequence({ kind: "openHistory", target: historyTarget });
    expect(opened.state.historyTarget).toEqual(historyTarget);
    expect(opened.effects).toEqual([{ kind: "closeGraphBrowser" }]);

    const closed = step(opened.state, { kind: "closeHistory" });
    expect(closed.state.historyTarget).toBeNull();
    expect(closed.effects).toEqual([]);
    expect(step(closed.state, { kind: "closeHistory" }).state).toBe(
      closed.state,
    );
  });

  it("resets project-specific state and preserves the execution snapshot", () => {
    const { state } = sequence(
      syncRunning,
      { kind: "setError", message: "Old project error" },
      { kind: "openHistory", target: historyTarget },
      requestCancel,
    );
    const reset = step(state, {
      kind: "resetForProject",
      projectId: "new-project",
    });
    expect(reset).toEqual(sequence(syncRunning));
    expect(
      step(reset.state, { kind: "resetForProject", projectId: null }).state,
    ).toBe(reset.state);
    expect(
      step(reset.state, {
        kind: "cancelRunFailed",
        runId: "run-1",
        message: "Late reply",
      }).state,
    ).toBe(reset.state);
  });
});
