import { describe, expect, it } from "vitest";

import type { VisibleRunExecution } from "./state";
import {
  initialRunLifecycle,
  reduceRunLifecycle,
  type RunLifecycleEvent,
  type RunLifecycleState,
  type RunStatusObservation,
} from "./lifecycle";

const firstRun = 1;
const nextRun = 2;
const executionId = "00000000-0000-4000-8000-000000000001";
const otherExecutionId = "00000000-0000-4000-8000-000000000002";

function announce(message: string): RunLifecycleEvent {
  return { type: "announcement", message };
}

function observation(
  overrides: Partial<RunStatusObservation> = {},
): RunStatusObservation {
  return {
    status: "running",
    reportedActiveNodeId: "node-1",
    cancellationRequested: false,
    supersedingTerminalStatus: null,
    lastActiveNodeId: null,
    ...overrides,
  };
}

function started(
  overrides: Partial<Extract<RunLifecycleEvent, { type: "run-started" }>> = {},
): RunLifecycleEvent {
  return {
    type: "run-started",
    generation: firstRun,
    scope: "selected",
    executionId: null,
    status: "preparing",
    activeNodeId: null,
    announcement: null,
    ...overrides,
  };
}

function polled(
  overrides: Partial<
    Extract<RunLifecycleEvent, { type: "polled-status" }>
  > = {},
): RunLifecycleEvent {
  return {
    type: "polled-status",
    generation: firstRun,
    executionId,
    observation: observation(),
    queuePosition: null,
    statusError: null,
    ...overrides,
  };
}

function streamed(
  overrides: Partial<
    Extract<RunLifecycleEvent, { type: "streamed-status" }>
  > = {},
): RunLifecycleEvent {
  return {
    type: "streamed-status",
    generation: firstRun,
    executionId,
    observation: observation(),
    statusError: null,
    ...overrides,
  };
}

function notice(message: string | null): RunLifecycleEvent {
  return {
    type: "status-notice",
    generation: firstRun,
    executionId,
    message,
  };
}

function card(state: RunLifecycleState): VisibleRunExecution | null {
  return state.kind === "running" ? state.visible : null;
}

function run(
  state: RunLifecycleState,
  events: readonly RunLifecycleEvent[],
): RunLifecycleState {
  return events.reduce(reduceRunLifecycle, state);
}

describe("reduceRunLifecycle", () => {
  it("starts a run with its scope, a preparing card, and no notice", () => {
    const state = run(initialRunLifecycle, [
      announce("Something from the last run."),
      started(),
    ]);

    expect(state.kind).toBe("running");
    expect(state.announcement).toBe("Something from the last run.");
    expect(card(state)).toEqual({
      generation: firstRun,
      executionId: null,
      status: "preparing",
      activeNodeId: null,
      queuePosition: null,
      statusError: null,
    });
  });

  it("binds the accepted execution and its queue position from the first poll", () => {
    const state = reduceRunLifecycle(
      reduceRunLifecycle(initialRunLifecycle, started()),
      polled({
        observation: observation({
          status: "queued",
          reportedActiveNodeId: null,
        }),
        queuePosition: 2,
      }),
    );

    expect(card(state)).toMatchObject({
      executionId,
      status: "queued",
      activeNodeId: null,
      queuePosition: 2,
    });
  });

  it("gives the surface back to the person when its own run ends", () => {
    const state = run(initialRunLifecycle, [
      started(),
      polled(),
      announce("Execution completed successfully."),
      { type: "run-finished", generation: firstRun },
    ]);

    // The card and the Run button's scope disappear together; the explanation of
    // how it ended stays for the live region.
    expect(state).toEqual({
      kind: "idle",
      announcement: "Execution completed successfully.",
    });
  });

  it("ignores every report from a run the person has moved past", () => {
    const superseded = run(initialRunLifecycle, [started(), polled()]);

    const state = run(superseded, [
      started({ generation: nextRun, scope: "all" }),
      polled({ observation: observation({ status: "succeeded" }) }),
      polled({
        observation: observation({
          status: "failed",
          supersedingTerminalStatus: "succeeded",
        }),
        statusError: "Execution status is unavailable. Retrying…",
      }),
      {
        type: "node-activity",
        generation: firstRun,
        executionId,
        activeNodeId: "node-9",
      },
      notice("Live progress disconnected."),
      { type: "cancellation-requested", generation: firstRun, executionId },
      { type: "run-finished", generation: firstRun },
    ]);

    expect(state.kind).toBe("running");
    expect(card(state)).toEqual({
      generation: nextRun,
      executionId: null,
      status: "preparing",
      activeNodeId: null,
      queuePosition: null,
      statusError: null,
    });
  });

  it("keeps a terminal status when an older poll resolves", () => {
    const succeeded = run(initialRunLifecycle, [
      started(),
      polled(),
      streamed({ observation: observation({ status: "succeeded" }) }),
    ]);
    expect(card(succeeded)?.status).toBe("succeeded");

    // The poll that was already in flight reports the older, running state and
    // carries the terminal status it must defer to.
    const stalePoll = reduceRunLifecycle(
      succeeded,
      polled({
        observation: observation({
          status: "running",
          supersedingTerminalStatus: "succeeded",
        }),
        statusError: "Execution status is unavailable. Retrying…",
      }),
    );

    expect(stalePoll).toBe(succeeded);
    expect(card(stalePoll)?.status).toBe("succeeded");
    expect(card(stalePoll)?.statusError).toBeNull();
  });

  it("reads as cancelling from the request until a terminal status arrives", () => {
    const requested = reduceRunLifecycle(
      run(initialRunLifecycle, [started(), polled()]),
      { type: "cancellation-requested", generation: firstRun, executionId },
    );
    expect(card(requested)).toMatchObject({
      status: "cancelling",
      statusError: null,
    });

    // The run loop keeps reporting what the server says — still running — while
    // the person's request stands. The card says cancelling regardless.
    const askedToCancel = observation({ cancellationRequested: true });
    const stillRunning = reduceRunLifecycle(
      requested,
      polled({ observation: askedToCancel }),
    );
    expect(card(stillRunning)?.status).toBe("cancelling");

    // A terminal status outranks the overlay: it says what happened, not what
    // was asked for.
    const cancelled = reduceRunLifecycle(
      stillRunning,
      polled({
        observation: { ...askedToCancel, status: "cancelled" },
      }),
    );
    expect(card(cancelled)?.status).toBe("cancelled");
  });

  it("stops claiming cancellation, and invites a retry, when the request fails", () => {
    const requested = run(initialRunLifecycle, [
      started(),
      polled(),
      { type: "cancellation-requested", generation: firstRun, executionId },
    ]);

    const rolledBack = reduceRunLifecycle(requested, {
      type: "cancellation-rolled-back",
      generation: firstRun,
      executionId,
      status: "running",
      message: "Cancellation service unavailable. You can try again.",
    });

    expect(card(rolledBack)).toMatchObject({
      status: "running",
      statusError: "Cancellation service unavailable. You can try again.",
    });

    // A failed request leaves cancellation no longer standing, so the next poll
    // shows the run's own status again, and a second request starts clean.
    const polledAgain = reduceRunLifecycle(
      rolledBack,
      polled({ statusError: null }),
    );
    expect(card(polledAgain)).toMatchObject({
      status: "running",
      statusError: null,
    });

    const requestedAgain = reduceRunLifecycle(polledAgain, {
      type: "cancellation-requested",
      generation: firstRun,
      executionId,
    });
    expect(card(requestedAgain)).toMatchObject({
      status: "cancelling",
      statusError: null,
    });
  });

  it("keeps a poll's problem when a reconnecting stream clears only its own", () => {
    const disconnected = reduceRunLifecycle(
      run(initialRunLifecycle, [started(), polled()]),
      notice("Live progress disconnected. Status polling continues."),
    );
    expect(card(disconnected)?.statusError).toBe(
      "Live progress disconnected. Status polling continues.",
    );

    const reconnected = reduceRunLifecycle(disconnected, {
      type: "status-notice-replaced",
      generation: firstRun,
      executionId,
      previous: "Live progress disconnected. Status polling continues.",
      message: null,
    });
    expect(card(reconnected)?.statusError).toBeNull();

    const pollProblem = reduceRunLifecycle(
      reconnected,
      notice("Execution status is unavailable. Retrying…"),
    );
    const streamReopens = reduceRunLifecycle(pollProblem, {
      type: "status-notice-replaced",
      generation: firstRun,
      executionId,
      previous: "Live progress disconnected. Status polling continues.",
      message: null,
    });
    expect(card(streamReopens)?.statusError).toBe(
      "Execution status is unavailable. Retrying…",
    );
  });

  it("refuses to let another execution move the current run's card", () => {
    const mine = run(initialRunLifecycle, [started(), polled()]);

    const wrongExecution = reduceRunLifecycle(
      mine,
      polled({
        executionId: otherExecutionId,
        observation: observation({ status: "succeeded" }),
      }),
    );
    expect(card(wrongExecution)).toEqual(card(mine));

    const wrongNode = reduceRunLifecycle(mine, {
      type: "node-activity",
      generation: firstRun,
      executionId: otherExecutionId,
      activeNodeId: "node-2",
    });
    expect(card(wrongNode)?.activeNodeId).toBe("node-1");
  });

  it("keeps the queue position a queued event omitted and drops it once work starts", () => {
    const queued = run(initialRunLifecycle, [
      started(),
      polled({
        observation: observation({
          status: "queued",
          reportedActiveNodeId: null,
        }),
        queuePosition: 3,
      }),
    ]);

    const queuedEvent = observation({
      status: "queued",
      reportedActiveNodeId: null,
    });
    const stillQueued = reduceRunLifecycle(
      queued,
      streamed({ observation: queuedEvent }),
    );
    expect(card(stillQueued)?.queuePosition).toBe(3);

    const running = reduceRunLifecycle(
      stillQueued,
      streamed({ observation: observation() }),
    );
    expect(card(running)).toMatchObject({
      status: "running",
      queuePosition: null,
    });
  });

  it("keeps the node named so far when a later report names none", () => {
    const working = run(initialRunLifecycle, [started(), polled()]);

    const finishedBlind = reduceRunLifecycle(
      working,
      streamed({
        observation: observation({
          status: "succeeded",
          reportedActiveNodeId: null,
          lastActiveNodeId: "node-1",
        }),
      }),
    );
    expect(card(finishedBlind)?.activeNodeId).toBe("node-1");

    // A non-terminal report that names no node means nothing is running, so the
    // card stops naming one.
    const queuedBlind = reduceRunLifecycle(
      working,
      streamed({
        observation: observation({
          status: "queued",
          reportedActiveNodeId: null,
          lastActiveNodeId: "node-1",
        }),
      }),
    );
    expect(card(queuedBlind)?.activeNodeId).toBeNull();
  });

  it("shows a peer's status as reported and keeps the notice it did not replace", () => {
    const observing = reduceRunLifecycle(
      reduceRunLifecycle(
        initialRunLifecycle,
        started({
          executionId,
          status: "running",
          activeNodeId: "node-1",
          announcement: "Observing shared execution started by Owner.",
        }),
      ),
      notice("Shared execution status is unavailable. Retrying…"),
    );

    const cancelling = reduceRunLifecycle(observing, {
      type: "remote-status-observed",
      generation: firstRun,
      executionId,
      status: "cancelling",
      reportedActiveNodeId: null,
    });

    // The remote authority already accounts for cancellation, and a report that
    // names no node must not blank the one already shown.
    expect(card(cancelling)).toMatchObject({
      status: "cancelling",
      activeNodeId: "node-1",
      statusError: "Shared execution status is unavailable. Retrying…",
    });

    const nextNode = reduceRunLifecycle(observing, {
      type: "remote-status-observed",
      generation: firstRun,
      executionId,
      status: "running",
      reportedActiveNodeId: "node-2",
    });
    expect(card(nextNode)?.activeNodeId).toBe("node-2");
  });

  it("leaves the previous state untouched", () => {
    const before = run(initialRunLifecycle, [started(), polled()]);
    const snapshot = structuredClone(before);

    run(before, [
      polled({
        observation: observation({ status: "succeeded" }),
        statusError: "Execution status is unavailable. Retrying…",
      }),
      {
        type: "node-activity",
        generation: firstRun,
        executionId,
        activeNodeId: "node-2",
      },
      announce("Execution completed successfully."),
      { type: "run-finished", generation: firstRun },
    ]);

    expect(before).toEqual(snapshot);
  });
});
