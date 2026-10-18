import type { RunExecution } from "@/lib/api";
import type { RunScope } from "../../model/execution-plan";
import {
  executionStatusIsTerminal,
  type RunTerminalStatus,
  type RunVisibleStatus,
  type VisibleRunExecution,
} from "./state";

/**
 * What the person sees while a run is in flight: the scope they asked for, the
 * status card, and the live-region announcement.
 *
 * Those three are one lifecycle, so they are one value. A run either owns the
 * surface (`running`) or does not (`idle`). There is no state where the Run
 * button spins while the status card is gone, and no status card without a
 * scope. A terminal announcement outlives the run, so it is carried across
 * `running -> idle` instead of being cleared with it.
 */
export type RunLifecycleState =
  | { readonly kind: "idle"; readonly announcement: string }
  | {
      readonly kind: "running";
      readonly announcement: string;
      readonly scope: RunScope;
      readonly visible: VisibleRunExecution;
    };

export const initialRunLifecycle: RunLifecycleState = {
  kind: "idle",
  announcement: "",
};

/**
 * A status report, reduced to what decides the surface. Polls and stream events
 * both produce one, and both the status card and the canvas node overlays are
 * read from the same `observedRunStatus` answer.
 */
export interface RunStatusObservation {
  status: RunExecution["status"];
  /** The node the report named, which a terminal report often omits. */
  reportedActiveNodeId: string | null;
  /** Whether this client asked for cancellation (or the server said cancelling). */
  cancellationRequested: boolean;
  /**
   * A terminal status already delivered by an event, which a late-arriving
   * report must not walk back. A stream event is itself a terminal source, so
   * it reports none.
   */
  supersedingTerminalStatus: RunTerminalStatus | null;
  /** The node named by the previous report. */
  lastActiveNodeId: string | null;
}

export type ObservedRunStatus =
  | { readonly applies: false }
  | {
      readonly applies: true;
      readonly status: RunVisibleStatus;
      readonly activeNodeId: string | null;
    };

/**
 * The single answer to "what status and node does this report show?".
 *
 * A run the person asked to cancel reads as cancelling from the request until a
 * terminal status arrives, whichever source reported which. A terminal report
 * that omits the active node keeps the last one known.
 */
export function shownRunStatus(observation: RunStatusObservation): {
  status: RunVisibleStatus;
  activeNodeId: string | null;
} {
  const terminal = executionStatusIsTerminal(observation.status);
  return {
    status:
      observation.cancellationRequested && !terminal
        ? "cancelling"
        : observation.status,
    activeNodeId:
      observation.reportedActiveNodeId ??
      (terminal ? observation.lastActiveNodeId : null),
  };
}

/**
 * `shownRunStatus`, plus the rule that keeps a run's outcome from moving
 * backwards: a report that arrives after a terminal event, and is not itself
 * terminal, says nothing at all. That is what stops an in-flight poll from
 * turning a succeeded run back into a running one.
 */
export function observedRunStatus(
  observation: RunStatusObservation,
): ObservedRunStatus {
  if (
    observation.supersedingTerminalStatus !== null &&
    !executionStatusIsTerminal(observation.status)
  ) {
    return { applies: false };
  }
  return { applies: true, ...shownRunStatus(observation) };
}

/**
 * A fact the run loop learned, already filtered by the guards that must keep
 * arbitrating synchronously: execution generation, event sequence, graph
 * snapshot, cancellation in flight. The reducer decides what a fact means for
 * the surface. It performs no IO and owns no resource.
 */
export type RunLifecycleEvent =
  /** A local run was submitted, or a shared run was discovered in the room. */
  | {
      type: "run-started";
      generation: number;
      scope: RunScope;
      /** Null while the server has not accepted the run yet. */
      executionId: string | null;
      status: RunVisibleStatus;
      activeNodeId: string | null;
      /** Null keeps the previous announcement. */
      announcement: string | null;
    }
  /** A report from polling the execution (this client's run and shared runs). */
  | {
      type: "polled-status";
      generation: number;
      executionId: string;
      observation: RunStatusObservation;
      queuePosition: number | null;
      statusError: string | null;
    }
  /** A report from this client's own live event stream. */
  | {
      type: "streamed-status";
      generation: number;
      executionId: string;
      observation: RunStatusObservation;
      statusError: string | null;
    }
  /**
   * A status a peer reported, through a room presence update or the shared-run
   * stream. The remote authority already accounts for cancellation, so its
   * status is shown as reported and any notice stays until it reports again.
   */
  | {
      type: "remote-status-observed";
      generation: number;
      executionId: string;
      status: RunExecution["status"];
      reportedActiveNodeId: string | null;
    }
  /** A node started work, so the status card names it. */
  | {
      type: "node-activity";
      generation: number;
      executionId: string;
      activeNodeId: string;
    }
  /** Replace the surfaced status problem (stream trouble, poll trouble, cancellation). */
  | {
      type: "status-notice";
      generation: number;
      executionId: string;
      message: string | null;
    }
  /**
   * Clear or replace a notice this client published earlier, but only while it
   * is still the one showing: a poll problem must not be wiped by a stream that
   * just reconnected.
   */
  | {
      type: "status-notice-replaced";
      generation: number;
      executionId: string;
      previous: string | null;
      message: string | null;
    }
  | { type: "cancellation-requested"; generation: number; executionId: string }
  /**
   * The cancellation request failed, or answered for another execution, so the
   * surface stops claiming the run is cancelling and offers a retry.
   */
  | {
      type: "cancellation-rolled-back";
      generation: number;
      executionId: string;
      status: RunExecution["status"];
      message: string;
    }
  | { type: "announcement"; message: string }
  /** The run that owns the surface is over (terminal, lost, or unmounted). */
  | { type: "run-finished"; generation: number };

export function reduceRunLifecycle(
  state: RunLifecycleState,
  event: RunLifecycleEvent,
): RunLifecycleState {
  switch (event.type) {
    case "announcement":
      return state.announcement === event.message
        ? state
        : { ...state, announcement: event.message };
    case "run-finished":
      // A superseded run loop must not clear the surface a newer run owns.
      if (
        state.kind !== "running" ||
        state.visible.generation !== event.generation
      ) {
        return state;
      }
      return { kind: "idle", announcement: state.announcement };
    case "run-started":
      return {
        kind: "running",
        announcement: event.announcement ?? state.announcement,
        scope: event.scope,
        visible: {
          generation: event.generation,
          executionId: event.executionId,
          status: event.status,
          activeNodeId: event.activeNodeId,
          queuePosition: null,
          statusError: null,
        },
      };
  }

  if (state.kind !== "running") return state;
  const visible = state.visible;
  // Every remaining event names the run that produced it, so a report from a
  // superseded run cannot reach a surface a newer run owns.
  if (visible.generation !== event.generation) return state;

  switch (event.type) {
    case "polled-status": {
      // While preparing, the surface has no execution to compare against and
      // this report is the one that attaches it. After that, only the same
      // execution may move the surface.
      if (
        visible.executionId !== null &&
        visible.executionId !== event.executionId
      ) {
        return state;
      }
      const observed = observedRunStatus(event.observation);
      if (!observed.applies) return state;
      return withVisible(state, {
        executionId: event.executionId,
        status: observed.status,
        activeNodeId: observed.activeNodeId,
        queuePosition: event.queuePosition,
        statusError: event.statusError,
      });
    }
    case "streamed-status": {
      if (visible.executionId !== event.executionId) return state;
      // A stream event is its own terminal source, so it never has to defer to
      // an earlier one.
      const shown = shownRunStatus(event.observation);
      return withVisible(state, {
        status: shown.status,
        activeNodeId: shown.activeNodeId,
        // A queued event carries no position, so keep the one already shown.
        queuePosition:
          event.observation.status === "queued" ? visible.queuePosition : null,
        statusError: event.statusError,
      });
    }
    case "remote-status-observed": {
      if (visible.executionId !== event.executionId) return state;
      return withVisible(state, {
        status: event.status,
        activeNodeId: event.reportedActiveNodeId ?? visible.activeNodeId,
      });
    }
    case "node-activity": {
      if (visible.executionId !== event.executionId) return state;
      return withVisible(state, { activeNodeId: event.activeNodeId });
    }
    case "status-notice": {
      if (visible.executionId !== event.executionId) return state;
      return withVisible(state, { statusError: event.message });
    }
    case "status-notice-replaced": {
      if (
        visible.executionId !== event.executionId ||
        visible.statusError !== event.previous
      ) {
        return state;
      }
      return withVisible(state, { statusError: event.message });
    }
    case "cancellation-requested": {
      if (visible.executionId !== event.executionId) return state;
      return withVisible(state, { status: "cancelling", statusError: null });
    }
    case "cancellation-rolled-back": {
      if (visible.executionId !== event.executionId) return state;
      return withVisible(state, {
        status: event.status,
        statusError: event.message,
      });
    }
  }
  // An event the reducer does not account for must fail the build, not sit
  // silently in a queue the surface never reflects.
  const unhandled: never = event;
  return unhandled;
}

function withVisible(
  state: Extract<RunLifecycleState, { kind: "running" }>,
  changes: Partial<VisibleRunExecution>,
): RunLifecycleState {
  return { ...state, visible: { ...state.visible, ...changes } };
}
