/**
 * Query layer for the execution history drawer: the SWR keys and their loaders.
 * Nothing here knows how a run is displayed.
 */

import {
  getGraphExecution,
  listGraphExecutions,
  type GraphExecutionDetail,
  type GraphExecutionList,
} from "@/lib/api";

const PAGE_SIZE = 20;

export type ExecutionHistoryPageKey = readonly [
  "graph-execution-history",
  string,
  string,
  string | null,
  string | null,
];

export async function loadExecutionHistoryPage([
  ,
  workspaceId,
  graphId,
  nodeId,
  cursor,
]: ExecutionHistoryPageKey): Promise<GraphExecutionList> {
  return listGraphExecutions(workspaceId, graphId, {
    limit: PAGE_SIZE,
    cursor: cursor ?? undefined,
    nodeId: nodeId ?? undefined,
  });
}

export type ExecutionDetailKey = readonly [
  "graph-execution-detail",
  string,
  string,
  string,
];

export async function loadExecutionDetail([
  ,
  workspaceId,
  graphId,
  executionId,
]: ExecutionDetailKey): Promise<GraphExecutionDetail> {
  return getGraphExecution(workspaceId, graphId, executionId);
}
