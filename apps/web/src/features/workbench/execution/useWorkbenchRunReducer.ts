"use client";

import * as React from "react";

import { cancelRun, type ActiveRunSummary } from "@/lib/api";
import { useEffectReducer } from "@/lib/state/use-effect-reducer";

import { instanceKeyText, type RoomInstanceState } from "../collaboration";
import type { RunScope } from "./execution-plan";
import { useRunExecution } from "./useRunExecution";
import {
  initialWorkbenchRunState,
  workbenchRunReducer,
  type ExecutionHistoryTarget,
} from "./workbench-run-reducer";

type RunExecutionOptions = Parameters<typeof useRunExecution>[0];
type StartRunWorkflow = ReturnType<typeof useRunExecution>["runWorkflow"];

type UseWorkbenchRunReducerOptions = Omit<
  RunExecutionOptions,
  "setRunError" | "roomActiveRuns"
> &
  Required<
    Pick<
      RunExecutionOptions,
      "roomConnected" | "roomRunsRevision" | "roomInstancesRevision"
    >
  > & {
    readonly openGraphId: string | null;
    readonly callTrail: readonly { readonly nodeId: string }[];
    readonly roomActiveRuns: readonly ActiveRunSummary[];
    readonly roomInstances: ReadonlyMap<string, RoomInstanceState>;
    readonly authoringError: string | null;
    readonly onClearAuthoringError: () => void;
    readonly onDismissAuthoringError: (message: string) => void;
    readonly onCloseGraphBrowser: () => void;
  };

export function useWorkbenchRunReducer({
  openGraphId,
  callTrail,
  roomInstances,
  authoringError,
  onClearAuthoringError,
  onDismissAuthoringError,
  onCloseGraphBrowser,
  ...executionOptions
}: UseWorkbenchRunReducerOptions) {
  const { workspaceId, projectId, nodes, roomActiveRuns } = executionOptions;
  const startRunWorkflowRef = React.useRef<StartRunWorkflow | null>(null);
  const projectLifetimeRef = React.useRef<symbol | null>(null);
  const errorRef = React.useRef<string | null>(null);
  const runningRef = React.useRef(false);

  const [state, dispatch] = useEffectReducer(
    workbenchRunReducer,
    initialWorkbenchRunState,
    (effect, dispatch) => {
      switch (effect.kind) {
        case "clearAuthoringError":
          onClearAuthoringError();
          break;
        case "clearAuthoringErrorIfMatches":
          if (authoringError === effect.message) {
            onDismissAuthoringError(effect.message);
          }
          break;
        case "startRunWorkflow":
          void startRunWorkflowRef.current?.(
            effect.scope,
            effect.explicitNodeIds,
          );
          break;
        case "cancelGraphRun": {
          const lifetime = projectLifetimeRef.current;
          if (lifetime === null || effect.projectId !== projectId) break;

          const { runId } = effect;
          void cancelRun(workspaceId, effect.projectId, runId).then(
            () => {
              if (projectLifetimeRef.current === lifetime) {
                dispatch({ kind: "cancelRunSucceeded", runId });
              }
            },
            (error: unknown) => {
              if (projectLifetimeRef.current === lifetime) {
                dispatch({
                  kind: "cancelRunFailed",
                  runId,
                  message:
                    error instanceof Error
                      ? error.message
                      : "The Run could not be cancelled.",
                });
              }
            },
          );
          break;
        }
        case "closeGraphBrowser":
          onCloseGraphBrowser();
          break;
      }
    },
  );

  React.useLayoutEffect(() => {
    projectLifetimeRef.current = Symbol();
    dispatch({ kind: "resetForProject", projectId });
    return () => {
      projectLifetimeRef.current = null;
    };
  }, [dispatch, projectId, workspaceId]);

  React.useLayoutEffect(() => {
    errorRef.current = state.error;
  }, [state]);

  const setRunError = React.useCallback<
    React.Dispatch<React.SetStateAction<string | null>>
  >(
    (value) => {
      const message =
        typeof value === "function" ? value(errorRef.current) : value;
      errorRef.current = message;
      dispatch({ kind: "setError", message });
    },
    [dispatch],
  );

  const {
    running,
    runningScope,
    announcement,
    runWorkflow: startRunWorkflow,
    ownRunStatus,
    activeRuns,
    instanceStates,
    resultByNodeId,
    refresh,
  } = useRunExecution({ ...executionOptions, setRunError });

  React.useLayoutEffect(() => {
    startRunWorkflowRef.current = startRunWorkflow;
  }, [startRunWorkflow]);

  React.useLayoutEffect(() => {
    runningRef.current = running;
    dispatch({ kind: "syncExecution", running, runningScope, announcement });
  }, [announcement, dispatch, running, runningScope]);

  const isExecutionRunning = React.useCallback(() => runningRef.current, []);
  const clearRunError = React.useCallback(
    () => dispatch({ kind: "clearError" }),
    [dispatch],
  );
  const dismissRunError = React.useCallback(
    (message: string) => dispatch({ kind: "dismissError", message }),
    [dispatch],
  );
  const runWorkflow = React.useCallback(
    (scope: RunScope, explicitNodeIds?: readonly string[]) =>
      dispatch({ kind: "requestRun", scope, explicitNodeIds }),
    [dispatch],
  );
  const cancelGraphRun = React.useCallback(
    (runId: string) => dispatch({ kind: "requestCancelRun", runId, projectId }),
    [dispatch, projectId],
  );
  const openExecutionHistory = React.useCallback(
    (target: ExecutionHistoryTarget) =>
      dispatch({ kind: "openHistory", target }),
    [dispatch],
  );
  const closeExecutionHistory = React.useCallback(
    () => dispatch({ kind: "closeHistory" }),
    [dispatch],
  );

  const openGraphRuns = React.useMemo(
    () =>
      openGraphId
        ? roomActiveRuns.filter((run) => run.graph_id === openGraphId)
        : [],
    [openGraphId, roomActiveRuns],
  );
  const nodeInstanceStates = React.useMemo(() => {
    const states: Record<string, RoomInstanceState> = {};
    if (openGraphId === null || projectId === null) return states;
    const callPath = callTrail.map((entry) => entry.nodeId);
    for (const node of nodes) {
      const instance = roomInstances.get(
        instanceKeyText({
          project_id: projectId,
          graph_id: openGraphId,
          call_path: callPath,
          node_id: node.id,
          map_index: null,
        }),
      );
      if (instance) states[node.id] = instance;
    }
    return states;
  }, [callTrail, nodes, openGraphId, projectId, roomInstances]);

  const { cancelPhase } = state;
  return {
    state,
    dispatch,
    transientRunError: state.error,
    runError: authoringError ?? state.error,
    setRunError,
    clearRunError,
    dismissRunError,
    running: state.running,
    runningScope: state.runningScope,
    isExecutionRunning,
    announcement: state.announcement,
    runWorkflow,
    cancellingRunId:
      cancelPhase.kind === "cancelling" ? cancelPhase.runId : null,
    cancelGraphRun,
    executionHistoryTarget: state.historyTarget,
    openExecutionHistory,
    closeExecutionHistory,
    openGraphRuns,
    nodeInstanceStates,
    ownRunStatus,
    activeRuns,
    instanceStates,
    resultByNodeId,
    refresh,
  };
}
