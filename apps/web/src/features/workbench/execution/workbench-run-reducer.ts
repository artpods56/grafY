import type { EffectReducer } from "@/lib/state/effect-reducer";

import type { RunScope } from "./execution-plan";

export interface ExecutionHistoryTarget {
  readonly nodeId: string | null;
  readonly executionId: string | null;
}

export interface WorkbenchRunState {
  readonly error: string | null;
  /** Run ids with a cancel request in flight. Two nodes can cancel at once. */
  readonly cancellingRunIds: readonly string[];
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

export function initialWorkbenchRunState(): WorkbenchRunState {
  return {
    error: null,
    cancellingRunIds: [],
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
      if (!action.projectId || state.cancellingRunIds.includes(action.runId)) {
        return state;
      }
      exec({
        kind: "cancelGraphRun",
        projectId: action.projectId,
        runId: action.runId,
      });
      return {
        ...state,
        cancellingRunIds: [...state.cancellingRunIds, action.runId],
      };
    case "cancelRunSucceeded":
    case "cancelRunFailed":
      if (!state.cancellingRunIds.includes(action.runId)) return state;
      return {
        ...state,
        cancellingRunIds: state.cancellingRunIds.filter(
          (runId) => runId !== action.runId,
        ),
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
        state.cancellingRunIds.length === 0 &&
        state.historyTarget === null
      ) {
        return state;
      }
      return {
        ...state,
        error: null,
        cancellingRunIds: [],
        historyTarget: null,
      };
  }
};
