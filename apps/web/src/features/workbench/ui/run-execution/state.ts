import {
  type RunExecution,
  type RunExecutionNodeProgressEvent,
  type RunNodeResult,
} from "@/lib/api";
import { withMaterializedNodeRuns } from "../../canvas/saved-graph";
import type { NodeExecutionStatus } from "../../canvas/types";
import type { WorkflowNode } from "../../model/execution-plan";
import type { ActiveSavedGraph } from "../useSavedGraphLifecycle";

export interface VisibleRunExecution {
  generation: number;
  executionId: string | null;
  status: "preparing" | RunExecution["status"];
  activeNodeId: string | null;
  queuePosition: number | null;
  statusError: string | null;
}

export interface RunExecutionGuard {
  generation: number;
  executionId: string | null;
  cancellationRequested: boolean;
  cancelInFlight: boolean;
  lastServerStatus: RunExecution["status"];
  activeNodeId: string | null;
  lastEventSequence: number;
  reconciliationRequested: boolean;
  terminalEventStatus: "cancelled" | "succeeded" | "failed" | null;
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
