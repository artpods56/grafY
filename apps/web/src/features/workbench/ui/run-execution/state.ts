import {
  type RunExecution,
  type RunExecutionNodeProgressEvent,
  type RunNodeResult,
} from "@/lib/api";
import { withMaterializedNodeRuns } from "../../canvas/saved-graph";
import type { NodeExecutionStatus } from "../../canvas/types";
import type { WorkflowNode } from "../../model/execution-plan";
import type { ActiveSavedGraph } from "../useSavedGraphLifecycle";

/** A status that ends the run: nothing after it may move it backwards. */
export type RunTerminalStatus = "cancelled" | "succeeded" | "failed";

/** Statuses the status card can show, including the pre-submission window. */
export type RunVisibleStatus = "preparing" | RunExecution["status"];

export interface VisibleRunExecution {
  generation: number;
  executionId: string | null;
  status: RunVisibleStatus;
  activeNodeId: string | null;
  queuePosition: number | null;
  statusError: string | null;
}

/**
 * Synchronous arbitration for one run. This is deliberately a ref and not
 * render state: the run loop, the event stream, and a cancellation request all
 * read and settle these flags in the same tick, before React publishes anything
 * (see the reserved run request in `useRunExecution`). Only the decisions that
 * need that immediacy live here; what the person sees is published through the
 * run lifecycle reducer, which takes these facts as typed events.
 */
export interface RunExecutionGuard {
  generation: number;
  executionId: string | null;
  cancellationRequested: boolean;
  cancelInFlight: boolean;
  lastServerStatus: RunExecution["status"];
  activeNodeId: string | null;
  lastEventSequence: number;
  reconciliationRequested: boolean;
  terminalEventStatus: RunTerminalStatus | null;
  planningActiveGraph: ActiveSavedGraph | null;
  planningFingerprint: string;
  finished: boolean;
}

export interface PendingProgressBatch {
  generation: number;
  executionId: string;
  executionNodeIds: ReadonlySet<string>;
  progressByNode: Map<
    string,
    {
      events: RunExecutionNodeProgressEvent[];
      omittedCount: number;
    }
  >;
}

export const MAX_PROGRESS_EVENTS_PER_NODE = 40;
export const MAX_PROGRESS_MESSAGE_CHARACTERS = 500;

export function nodeExecutionIsTerminal(status: NodeExecutionStatus): boolean {
  return (
    status === "succeeded" ||
    status === "failed" ||
    status === "skipped" ||
    status === "cancelled"
  );
}

/**
 * A workflow status that ends the run. Everything after it may only preserve or
 * restate this outcome, never replace it.
 */
export function executionStatusIsTerminal(
  status: RunExecution["status"],
): status is RunTerminalStatus {
  return (
    status === "cancelled" || status === "succeeded" || status === "failed"
  );
}

/**
 * The canvas after a cancellation attempt is given up: the node left showing
 * `cancelling` returns to what the server last reported for the run, so the
 * person is not left looking at a cancellation that never took.
 */
export function withoutCancellationOverlay(
  nodes: WorkflowNode[],
  guard: Pick<RunExecutionGuard, "activeNodeId" | "lastServerStatus">,
): WorkflowNode[] {
  return nodes.map((node) =>
    node.id === guard.activeNodeId &&
    node.data.execution.status === "cancelling"
      ? {
          ...node,
          data: {
            ...node.data,
            execution: {
              status:
                guard.lastServerStatus === "cancelling"
                  ? "cancelling"
                  : "running",
            },
          },
        }
      : node,
  );
}

export function withCurrentMaterializations(
  nodes: readonly WorkflowNode[],
  nodeRuns: readonly RunNodeResult[],
): WorkflowNode[] {
  const previousNodesById = new Map(nodes.map((node) => [node.id, node]));
  return withMaterializedNodeRuns(nodes, nodeRuns).map((node) => {
    if (node.data.run) return node;

    const previous = previousNodesById.get(node.id);
    if (
      !previous ||
      previous.data.execution.status === "succeeded" ||
      !nodeExecutionIsTerminal(previous.data.execution.status)
    ) {
      return node;
    }
    return {
      ...node,
      data: {
        ...node.data,
        run:
          previous.data.run?.status === "succeeded" ? null : previous.data.run,
        execution: previous.data.execution,
      },
    };
  });
}

export function withSharedExecutionTerminalNodes(
  nodes: readonly WorkflowNode[],
  executionNodeIds: ReadonlySet<string>,
  response: RunExecution,
): WorkflowNode[] {
  if (response.status === "cancelled") {
    return nodes.map((node) => {
      if (
        !executionNodeIds.has(node.id) ||
        nodeExecutionIsTerminal(node.data.execution.status)
      ) {
        return node;
      }
      return {
        ...node,
        data: {
          ...node.data,
          run: null,
          execution: { status: "cancelled" },
        },
      };
    });
  }

  if (response.result) {
    const byNode = new Map(
      response.result.node_runs.map((run) => [run.node_id, run]),
    );
    return nodes.map((node) => {
      if (!executionNodeIds.has(node.id) && !byNode.has(node.id)) {
        return node;
      }
      const run = byNode.get(node.id);
      return {
        ...node,
        data: {
          ...node.data,
          run: run ?? null,
          execution: run
            ? {
                status: run.status,
                error:
                  run.error ??
                  (run.status === "failed"
                    ? "This node failed without error details."
                    : undefined),
              }
            : {
                status: "skipped",
                error: "The server did not return a result for this node.",
              },
        },
      };
    });
  }

  const executionMessage =
    response.error ?? "The execution ended without a workflow result.";
  const failedNodeId = response.active_node_id;
  return nodes.map((node) => {
    if (
      !executionNodeIds.has(node.id) ||
      nodeExecutionIsTerminal(node.data.execution.status)
    ) {
      return node;
    }
    const failed = failedNodeId === null || node.id === failedNodeId;
    return {
      ...node,
      data: {
        ...node.data,
        run: null,
        execution: failed
          ? { status: "failed", error: executionMessage }
          : { status: "idle" },
      },
    };
  });
}
