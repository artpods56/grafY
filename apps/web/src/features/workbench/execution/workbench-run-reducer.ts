import type { ActiveRunSummary } from "@/lib/api";
import type { EffectReducer } from "@/lib/state/effect-reducer";

import type { RunScope } from "./execution-plan";

export interface ExecutionHistoryTarget {
  readonly nodeId: string | null;
  readonly executionId: string | null;
}

export type RunCancelPhase =
  | { readonly kind: "idle" }
  | { readonly kind: "cancelling"; readonly runId: string };

export interface WorkbenchRunState {
  readonly error: string | null;
  readonly cancelPhase: RunCancelPhase;
  readonly historyTarget: ExecutionHistoryTarget | null;
  readonly running: boolean;
  readonly runningScope: RunScope | null;
  readonly announcement: string;
}

export type WorkbenchRunAction =
  | { readonly kind: "setError"; readonly message: string | null }
  | { readonly kind: "clearError" }
  | { readonly kind: "dismissError"; readonly message: string }
  | {
      readonly kind: "requestRun";
      readonly scope: RunScope;
      readonly explicitNodeIds?: readonly string[];
    }
  | {
      readonly kind: "syncExecution";
      readonly running: boolean;
      readonly runningScope: RunScope | null;
      readonly announcement: string;
    }
  | {
      readonly kind: "requestCancelRun";
      readonly runId: string;
      readonly projectId: string | null;
    }
  | { readonly kind: "cancelRunSucceeded"; readonly runId: string }
  | {
      readonly kind: "cancelRunFailed";
      readonly runId: string;
      readonly message: string;
    }
  | { readonly kind: "openHistory"; readonly target: ExecutionHistoryTarget }
  | { readonly kind: "closeHistory" }
  | { readonly kind: "resetForProject"; readonly projectId: string | null };

export type WorkbenchRunEffect =
  | { readonly kind: "clearAuthoringError" }
  | { readonly kind: "clearAuthoringErrorIfMatches"; readonly message: string }
  | {
      readonly kind: "startRunWorkflow";
      readonly scope: RunScope;
      readonly explicitNodeIds?: readonly string[];
    }
  | {
      readonly kind: "cancelGraphRun";
      readonly projectId: string;
      readonly runId: string;
    }
  | { readonly kind: "closeGraphBrowser" };

export interface RunActivityDescriptor {
  readonly eyebrow: string;
  readonly title: string;
  readonly message: string;
  readonly tone: "working" | "cancelling";
  readonly cancelAction?: {
    readonly runId: string;
    readonly label: string;
    readonly ariaLabel: string;
    readonly disabled: boolean;
  };
}

export function initialWorkbenchRunState(): WorkbenchRunState {
  return {
    error: null,
    cancelPhase: { kind: "idle" },
    historyTarget: null,
    running: false,
    runningScope: null,
    announcement: "",
  };
}

export const workbenchRunReducer: EffectReducer<
  WorkbenchRunState,
  WorkbenchRunAction,
  WorkbenchRunEffect
> = (state, action, exec) => {
  switch (action.kind) {
    case "setError":
      return state.error === action.message
        ? state
        : { ...state, error: action.message };
    case "clearError":
      exec({ kind: "clearAuthoringError" });
      return state.error === null ? state : { ...state, error: null };
    case "dismissError":
      exec({
        kind: "clearAuthoringErrorIfMatches",
        message: action.message,
      });
      return state.error === action.message ? { ...state, error: null } : state;
    case "requestRun":
      if (state.running) return state;
      exec({
        kind: "startRunWorkflow",
        scope: action.scope,
        explicitNodeIds: action.explicitNodeIds,
      });
      return state;
    case "syncExecution":
      if (
        state.running === action.running &&
        state.runningScope === action.runningScope &&
        state.announcement === action.announcement
      ) {
        return state;
      }
      return {
        ...state,
        running: action.running,
        runningScope: action.runningScope,
        announcement: action.announcement,
      };
    case "requestCancelRun":
      if (!action.projectId || state.cancelPhase.kind === "cancelling") {
        return state;
      }
      exec({
        kind: "cancelGraphRun",
        projectId: action.projectId,
        runId: action.runId,
      });
      return {
        ...state,
        cancelPhase: { kind: "cancelling", runId: action.runId },
      };
    case "cancelRunSucceeded":
    case "cancelRunFailed":
      if (
        state.cancelPhase.kind !== "cancelling" ||
        state.cancelPhase.runId !== action.runId
      ) {
        return state;
      }
      return {
        ...state,
        cancelPhase: { kind: "idle" },
        error: action.kind === "cancelRunFailed" ? action.message : state.error,
      };
    case "openHistory":
      exec({ kind: "closeGraphBrowser" });
      return { ...state, historyTarget: action.target };
    case "closeHistory":
      return state.historyTarget === null
        ? state
        : { ...state, historyTarget: null };
    case "resetForProject":
      void action.projectId;
      if (
        state.error === null &&
        state.cancelPhase.kind === "idle" &&
        state.historyTarget === null
      ) {
        return state;
      }
      return {
        ...state,
        error: null,
        cancelPhase: { kind: "idle" },
        historyTarget: null,
      };
  }
};

export function deriveRunActivity({
  openGraphRuns,
  running,
  runningScope,
  cancelPhase,
  canCancelRun,
  nodeTitles,
}: {
  openGraphRuns: readonly ActiveRunSummary[];
  running: boolean;
  runningScope: RunScope | null;
  cancelPhase: RunCancelPhase;
  canCancelRun: boolean;
  nodeTitles: Readonly<Record<string, string>>;
}): RunActivityDescriptor | null {
  const newestRun = openGraphRuns.at(-1);
  if (!newestRun) {
    if (!running) return null;
    return {
      eyebrow: "Run",
      title: runningScope === "all" ? "The whole graph" : "The selection",
      message: "Starting",
      tone: "working",
    };
  }

  const [firstTarget] = newestRun.targets;
  let newestRunTitle: string | null = null;
  if (firstTarget) {
    const title = Object.hasOwn(nodeTitles, firstTarget.node_id)
      ? nodeTitles[firstTarget.node_id]
      : undefined;
    const firstTitle = title ?? "A node";
    const rest = newestRun.targets.length - 1;
    newestRunTitle = rest > 0 ? `${firstTitle} and ${rest} more` : firstTitle;
  }

  const cancelling =
    cancelPhase.kind === "cancelling" && cancelPhase.runId === newestRun.run_id;
  return {
    eyebrow:
      openGraphRuns.length > 1 ? `Runs · ${openGraphRuns.length}` : "Run",
    title: newestRunTitle ?? "Running",
    message: cancelling
      ? "Waiting for the computation to stop"
      : newestRun.starter
        ? `Started by ${newestRun.starter.display_name}`
        : "Running",
    tone: cancelling ? "cancelling" : "working",
    cancelAction: {
      runId: newestRun.run_id,
      label: cancelling ? "Cancelling" : "Cancel",
      ariaLabel: cancelling
        ? "Cancelling this Run"
        : "Cancel this Run for everyone",
      disabled:
        !canCancelRun ||
        !newestRun.cancellable ||
        cancelPhase.kind === "cancelling",
    },
  };
}
