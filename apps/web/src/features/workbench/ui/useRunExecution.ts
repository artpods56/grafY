"use client";

import * as React from "react";

import {
  cancelRun,
  getRun,
  listRuns,
  startRun,
  type ActiveRunSummary,
  type InstanceState,
  type Run,
  type RunNodeResult,
  type RunStatus,
  type RunTargetInput,
  type SavedGraphOrigin,
} from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import {
  nodeSecretBindingReady,
  nodeSecretInputs,
  type WorkflowNodeSecretInput,
} from "../canvas/node-secrets";
import type { WorkflowEdge } from "../canvas/types";
import {
  executionSubgraphFor,
  executionValidationIssue,
  runTargetsFor,
  type RunScope,
  type WorkflowNode,
} from "../model/execution-plan";
import {
  instanceStateByNodeId,
  loadInstanceSnapshot,
  withInstanceResults,
  withInstanceStates,
  type NodeInstanceState,
} from "./run-execution/state";
import type { NodeSecretStatusesByNode } from "./useNodeSecrets";
import type { ActiveSavedGraph } from "./useSavedGraphLifecycle";

/**
 * How often the run surface re-reads the Project when no room is carrying it.
 * A live room push replaces this entirely; the interval is only the fallback.
 */
export const RUN_SURFACE_POLL_INTERVAL_MS = 2_000;

interface UseRunExecutionOptions {
  workspaceId: string;
  /** A Run is a demand inside a Project, so nothing here is addressed by Graph alone. */
  projectId: string | null;
  registryAvailable: boolean;
  nodes: readonly WorkflowNode[];
  edges: readonly WorkflowEdge[];
  origins?: readonly SavedGraphOrigin[];
  activeGraph: ActiveSavedGraph | null;
  currentExecutionFingerprint: string;
  /** The canvas' topology matches the head it was read from, so a Run may start. */
  canRunSavedGraph: boolean;
  nodeSecretStatuses: NodeSecretStatusesByNode;
  /** True while the Project room is connected: its pushes replace all polling. */
  roomConnected?: boolean;
  /** The room's active Runs, straight from `room.ready` / `run.started` / `run.finished`. */
  roomActiveRuns?: readonly ActiveRunSummary[] | null;
  /** Bumped by the room on `run.started` and `run.finished`. */
  roomRunsRevision?: number;
  /** Bumped by the room on `instances.changed`. */
  roomInstancesRevision?: number;
  setNodes: React.Dispatch<React.SetStateAction<WorkflowNode[]>>;
  setRunError: (message: string | null) => void;
}

/** What this tab asked for, while it asked for it. */
export interface OwnRunState {
  runId: string;
  scope: RunScope;
  graphId: string;
  targets: readonly RunTargetInput[];
}

function isTerminalRunStatus(status: RunStatus): boolean {
  return (
    status === "succeeded" ||
    status === "failed" ||
    status === "cancelled" ||
    status === "interrupted"
  );
}

function runFailureMessage(run: Run): string {
  if (run.error) return run.error;
  switch (run.status) {
    case "failed":
      return "The Run failed. Its instances show why.";
    case "cancelled":
      return "The Run was cancelled.";
    case "interrupted":
      return "The Run was interrupted before it finished. Running it again resumes from what is already fresh.";
    default:
      return "The Run ended without making its targets fresh.";
  }
}

export function useRunExecution({
  workspaceId,
  projectId,
  registryAvailable,
  nodes,
  edges,
  origins = [],
  activeGraph,
  currentExecutionFingerprint,
  canRunSavedGraph,
  nodeSecretStatuses,
  roomConnected = false,
  roomActiveRuns = null,
  roomRunsRevision = 0,
  roomInstancesRevision = 0,
  setNodes,
  setRunError,
}: UseRunExecutionOptions) {
  // This tab's own demand. It is a ref because the loop below and a cancellation
  // request have to agree on it in the same tick, before React publishes anything.
  const ownRunRef = React.useRef<OwnRunState | null>(null);
  const generationRef = React.useRef(0);
  const mountedRef = React.useRef(true);
  /** The fingerprint the canvas held when this tab's Run was started. */
  const startedFingerprintRef = React.useRef("");
  const snapshotRef = React.useRef({
    activeGraph,
    fingerprint: currentExecutionFingerprint,
  });
  React.useLayoutEffect(() => {
    snapshotRef.current = {
      activeGraph,
      fingerprint: currentExecutionFingerprint,
    };
  }, [activeGraph, currentExecutionFingerprint]);

  const [ownRun, setOwnRun] = React.useState<OwnRunState | null>(null);
  const [ownRunStatus, setOwnRunStatus] = React.useState<RunStatus | null>(
    null,
  );
  const [announcement, setAnnouncement] = React.useState("");
  const [activeRuns, setActiveRuns] = React.useState<readonly Run[]>([]);
  const [instanceStates, setInstanceStates] = React.useState<
    Readonly<Record<string, NodeInstanceState>>
  >({});
  const [resultByNodeId, setResultByNodeId] = React.useState<
    Readonly<Record<string, RunNodeResult>>
  >({});

  /** Fingerprint each node's stored result was read under. */
  const loadedFingerprintsRef = React.useRef(new Map<string, string>());
  // The published results as a ref, so a refresh that moves one node does not
  // rebuild the map from whatever React happens to have rendered.
  const resultByNodeIdRef = React.useRef<Record<string, RunNodeResult>>({});
  const inFlightRefreshRef = React.useRef<Promise<void> | null>(null);

  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      // The tab gives up its demand from here: the Run itself stays where it is,
      // and another tab, or the same person later, can still cancel it by id.
      ownRunRef.current = null;
    };
  }, []);

  // What this surface is reading: a Graph, inside a Project. Both halves matter,
  // because a Project holds several Graphs and their instances are separate.
  const graphKey =
    projectId && activeGraph
      ? `${projectId}\u0000${activeGraph.graphId}`
      : null;

  const publishInstances = React.useCallback(
    async (options: { onlyNodeIds?: ReadonlySet<string> } = {}) => {
      if (!projectId || !activeGraph) return;
      const requestGraph = activeGraph;
      const generation = generationRef.current;
      const stillCurrent = () =>
        mountedRef.current &&
        generation === generationRef.current &&
        snapshotRef.current.activeGraph?.graphId === requestGraph.graphId &&
        snapshotRef.current.activeGraph?.revision === requestGraph.revision;

      const loaded = loadedFingerprintsRef.current;
      // The state list is read first and tells us which results moved, so a room
      // push about an unchanged fingerprint costs nothing extra.
      const snapshot = await loadInstanceSnapshot(
        workspaceId,
        projectId,
        requestGraph.graphId,
        // The fingerprints already held are always offered: a refresh that finds
        // an instance pointing at the result it pointed at last time has nothing
        // new to show, and re-reading it would make the surface's read rate grow
        // with how often it is refreshed.
        {
          onlyNodeIds: options.onlyNodeIds,
          loadedFingerprints: loaded,
        },
      ).catch((error: unknown) => {
        if (mountedRef.current && generation === generationRef.current) {
          setRunError(
            error instanceof Error
              ? error.message
              : "Node instance state is unavailable.",
          );
        }
        return null;
      });
      if (!snapshot || !stillCurrent()) return;

      const states: Record<string, NodeInstanceState> = {};
      const fingerprints = new Map(loaded);
      const byNodeId = instanceStateByNodeId(snapshot.instances);
      for (const [nodeId, instance] of byNodeId) {
        states[nodeId] = instance.state;
        if (instance.last_result_fingerprint) {
          fingerprints.set(nodeId, instance.last_result_fingerprint);
        } else {
          fingerprints.delete(nodeId);
        }
      }
      loadedFingerprintsRef.current = fingerprints;

      const results = new Map<string, RunNodeResult>(
        Object.entries(resultByNodeIdRef.current),
      );
      for (const result of snapshot.results) {
        results.set(result.node_id, result);
      }
      const resultsByNodeId = Object.fromEntries(results);
      resultByNodeIdRef.current = resultsByNodeId;

      setInstanceStates(states);
      setResultByNodeId(resultsByNodeId);
      // Overlays and stored results move together, in one publish, so a node
      // cannot be shown as fresh while still carrying the outputs of an older
      // fingerprint.
      setNodes((current) =>
        withInstanceResults(withInstanceStates(current, byNodeId), results),
      );
    },
    [projectId, activeGraph, setNodes, setRunError, workspaceId],
  );

  const refreshActiveRuns = React.useCallback(async () => {
    if (!projectId) return;
    try {
      const listed = await listRuns(workspaceId, projectId, {
        activeOnly: true,
      });
      if (!mountedRef.current) return;
      setActiveRuns(listed.runs);
    } catch {
      // A failed read of the Run list is not worth an error banner: the room, or
      // the next poll, answers again.
    }
  }, [projectId, workspaceId]);

  /**
   * Read this tab's own Run and say what it did.
   *
   * It is read by id and not picked out of a list: a list that trims finished
   * Runs, or has not caught up yet, would leave a card showing a Run that ended
   * minutes ago. And the room says only that *a* Run finished, so the answer to
   * "was it mine?" is always a read of mine.
   */
  const settleOwnRun = React.useCallback(async () => {
    const pending = ownRunRef.current;
    if (!pending || !projectId) return;
    let run: Run;
    try {
      run = await getRun(workspaceId, projectId, pending.runId);
    } catch {
      // A read that failed answers again on the next poll or room push; a
      // transient failure is not a reason to tell someone their Run vanished.
      return;
    }
    if (!mountedRef.current || ownRunRef.current?.runId !== pending.runId) {
      return;
    }
    if (!isTerminalRunStatus(run.status)) {
      setOwnRunStatus(run.status);
      return;
    }
    const documentMoved =
      snapshotRef.current.fingerprint !== startedFingerprintRef.current;
    ownRunRef.current = null;
    setOwnRun(null);
    setOwnRunStatus(null);
    await publishInstances();
    if (!mountedRef.current) return;
    if (documentMoved) {
      // The Run finished, but not into the canvas this person is looking at.
      // Saying "fresh" here would be the lie: the document moved under it, so
      // what the cards hold is whatever that move left standing.
      setRunError(
        run.status === "cancelled"
          ? "The Run was cancelled. The graph had already moved, so its nodes show the state that move left them in."
          : "The graph changed while the Run was going. Its results are stored, and the nodes it touched read as stale.",
      );
      setAnnouncement(`Run ${run.status}, and the graph had already moved.`);
      return;
    }
    if (run.status === "succeeded") {
      setAnnouncement("Run made its targets fresh.");
    } else {
      setRunError(runFailureMessage(run));
      setAnnouncement(`Run ${run.status}.`);
    }
  }, [projectId, publishInstances, setRunError, workspaceId]);

  const refresh = React.useCallback(() => {
    const work = Promise.all([
      publishInstances(),
      refreshActiveRuns(),
      settleOwnRun(),
    ]).then(() => undefined);
    inFlightRefreshRef.current = work;
    void work.finally(() => {
      if (inFlightRefreshRef.current === work) {
        inFlightRefreshRef.current = null;
      }
    });
    return work;
  }, [publishInstances, refreshActiveRuns, settleOwnRun]);

  // Opening a Project's Graph reads what its instances already hold, whether or
  // not anyone here has run anything. That is what lets a node show the result
  // its instance stored before this tab asked for anything.
  React.useEffect(() => {
    generationRef.current += 1;
    loadedFingerprintsRef.current = new Map();
    resultByNodeIdRef.current = {};
    // Moving to another Graph, or out of the Project entirely, ends the previous
    // canvas' state before anything is read for the new one. A card that kept
    // another Graph's fresh badge, or another Project's stored result, while the
    // first read was in flight would be a lie about work nobody asked for.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setInstanceStates({});
    setResultByNodeId({});
    setActiveRuns([]);
    if (!graphKey) return;
    void publishInstances();
    void refreshActiveRuns();
    // `graphKey` is the whole identity of what to read.
  }, [graphKey, publishInstances, refreshActiveRuns]);

  // The room's `instances.changed` is an event to wait on, so it replaces both
  // the poll and a guess about which nodes moved.
  React.useEffect(() => {
    if (!roomConnected || roomInstancesRevision === 0 || !graphKey) return;
    void publishInstances();
  }, [graphKey, publishInstances, roomConnected, roomInstancesRevision]);

  React.useEffect(() => {
    if (!roomConnected || roomRunsRevision === 0) return;
    // The room's push is the event; this is the read it asks for.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshActiveRuns();
  }, [refreshActiveRuns, roomConnected, roomRunsRevision]);

  // Without a room the surface falls back to polling, and only while something
  // could still move: this tab's Run, or a Run somebody else has open.
  const pollingNeeded =
    !roomConnected && (ownRun !== null || activeRuns.length > 0);
  React.useEffect(() => {
    if (!pollingNeeded) return;
    const timer = window.setInterval(() => {
      void refresh();
    }, RUN_SURFACE_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [pollingNeeded, refresh]);

  // This tab's demand is settled when the room says a Run moved, and by the
  // poll below while there is no room.
  React.useEffect(() => {
    if (!ownRun) return;
    void settleOwnRun();
  }, [ownRun, roomRunsRevision, settleOwnRun]);

  const runWorkflow = React.useCallback(
    async (scope: RunScope) => {
      if (!registryAvailable || ownRunRef.current !== null) return;
      if (!projectId || !activeGraph) {
        setRunError("Save the graph before running it.");
        return;
      }
      const execution = executionSubgraphFor(scope, nodes, edges);
      const validationIssue = executionValidationIssue(
        scope,
        execution.nodes,
        execution.edges,
        origins,
      );
      if (validationIssue) {
        if (validationIssue.nodeId) {
          setRunError(null);
          setNodes((current) =>
            current.map((node: WorkflowNode) =>
              node.id === validationIssue.nodeId
                ? {
                    ...node,
                    data: {
                      ...node.data,
                      execution: {
                        status: "failed",
                        error: validationIssue.message,
                      },
                    },
                  }
                : node,
            ),
          );
        } else {
          setRunError(validationIssue.message);
        }
        return;
      }

      const secretBackedNodes = execution.nodes
        .map((node: WorkflowNode) => ({
          node,
          inputs: nodeSecretInputs(node.data.spec),
        }))
        .filter(({ inputs }) => inputs.length > 0);
      if (secretBackedNodes.length && !canRunSavedGraph) {
        setRunError(
          "Save the graph before running nodes that use stored secrets.",
        );
        return;
      }
      for (const { node, inputs } of secretBackedNodes) {
        const savedNode = activeGraph.nodes.find(
          (candidate) => candidate.id === node.id,
        );
        const changedInput = inputs.find(
          (input: WorkflowNodeSecretInput) =>
            !nodeSecretBindingReady(
              input,
              {
                id: node.id,
                operator_id: node.data.spec.operator_id,
                operator_version: node.data.spec.operator_version,
                config: node.data.config,
              },
              savedNode,
            ),
        );
        if (changedInput) {
          setRunError(
            `Save the graph before running ${node.data.spec.title}: its ${changedInput.title} binding is new or changed.`,
          );
          return;
        }
      }
      const unavailableSecret = secretBackedNodes.find(({ node, inputs }) =>
        inputs.some(
          (input: WorkflowNodeSecretInput) =>
            nodeSecretStatuses[node.id]?.[input.name]?.state !== "configured",
        ),
      );
      if (unavailableSecret) {
        setRunError(
          `Configure every required secret for ${unavailableSecret.node.data.spec.title} before running.`,
        );
        return;
      }

      const targets = runTargetsFor(execution);
      const startedAt = activeGraph;
      setRunError(null);
      setAnnouncement("");
      let run: Run;
      try {
        run = await startRun(workspaceId, projectId, {
          graph_id: startedAt.graphId,
          targets,
        });
      } catch (error) {
        if (!mountedRef.current) return;
        setRunError(
          error instanceof ApiError
            ? runRejectionMessage(error)
            : error instanceof Error
              ? error.message
              : "The Run could not be started.",
        );
        return;
      }
      if (!mountedRef.current) return;

      const pending: OwnRunState = {
        runId: run.id,
        scope,
        graphId: run.graph_id,
        targets: run.targets,
      };
      generationRef.current += 1;
      startedFingerprintRef.current = snapshotRef.current.fingerprint;
      ownRunRef.current = pending;
      setOwnRun(pending);
      setOwnRunStatus(run.status);
      await publishInstances();
    },
    [
      activeGraph,
      canRunSavedGraph,
      edges,
      nodeSecretStatuses,
      nodes,
      origins,
      projectId,
      publishInstances,
      registryAvailable,
      setNodes,
      setRunError,
      workspaceId,
    ],
  );

  /**
   * Withdraw this tab's own demand.
   *
   * Only the Run this browser started, and only by its id: a computation another
   * Run still needs goes on, which is exactly why nothing here reaches for
   * "the" active Run.
   */
  const cancelCurrentRun = React.useCallback(async () => {
    const pending = ownRunRef.current;
    if (!pending || !projectId) return;
    try {
      const cancelled = await cancelRun(workspaceId, projectId, pending.runId);
      if (!mountedRef.current) return;
      setOwnRunStatus(cancelled.status);
      setAnnouncement("Cancelling this Run.");
      void refreshActiveRuns();
    } catch (error) {
      if (!mountedRef.current) return;
      setRunError(
        error instanceof Error
          ? error.message
          : "The Run could not be cancelled.",
      );
    }
  }, [projectId, refreshActiveRuns, setRunError, workspaceId]);

  const running = ownRun !== null;
  const runningScope = ownRun?.scope ?? null;
  /** Every active Run in this Project, this tab's first: there is never one "the" Run. */
  const visibleActiveRuns: readonly ActiveRunSummary[] = React.useMemo(() => {
    const summaries = new Map<string, ActiveRunSummary>();
    for (const run of roomActiveRuns ?? []) {
      summaries.set(run.run_id, run);
    }
    for (const run of activeRuns) {
      if (summaries.has(run.id)) continue;
      summaries.set(run.id, {
        run_id: run.id,
        graph_id: run.graph_id,
        targets: run.targets,
        starter: null,
        started_at: run.created_at,
        cancellable: true,
      });
    }
    const pending = ownRun;
    if (pending && !summaries.has(pending.runId)) {
      summaries.set(pending.runId, {
        run_id: pending.runId,
        graph_id: pending.graphId,
        targets: pending.targets,
        starter: null,
        started_at: new Date().toISOString(),
        cancellable: true,
      });
    }
    return [...summaries.values()];
  }, [activeRuns, ownRun, roomActiveRuns]);

  return {
    running,
    runningScope,
    /**
     * This tab's Run as last read: `queued` until a worker takes it, then
     * `running`. It is this tab's own Run only — there is no "the" active Run to
     * read a status off, and another tab's demand has its own.
     */
    ownRunStatus,
    ownRun,
    activeRuns: visibleActiveRuns,
    instanceStateByNodeId,
    instanceStates,
    resultByNodeId,
    /** Re-read the Project after a change the room did not announce. */
    refresh,
    announcement,
    runWorkflow,
    cancelCurrentRun,
  };
}

/**
 * A rejected Run, in the words a person can act on.
 *
 * The `code` is the stable half — the server's detail sentence is prose it may
 * rewrite — so the codes a caller can do something about get their own sentence,
 * and the rest fall back to what the server actually said.
 */
export function runRejectionMessage(error: ApiError): string {
  const code = typeof error.code === "string" ? error.code : null;
  const message = error.detail ? error.detail : null;
  switch (code) {
    case "unknown_graph":
      return "This Graph is no longer in the Project. Reload it before running.";
    case "unknown_target":
      return "A node this Run was asked for is no longer on the canvas. Select the nodes again.";
    case "unknown_operator":
      return message ?? "A node in this Run is not in the live node registry.";
    case "invalid_document":
      return message ?? "The Graph cannot be run as it is saved.";
    default:
      return message ?? error.message;
  }
}

export type { InstanceState };
