/**
 * How an execution is displayed in the history drawer. Separate from the query
 * layer on purpose: these functions read a style object, the loaders do not.
 */

import type { GraphExecutionStatus, GraphExecutionSummary } from "@/lib/api";

import { executionHistoryDrawerStyles as s } from "./ExecutionHistoryDrawer.styles";

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function executionTimestamp(execution: GraphExecutionSummary): string {
  const value =
    execution.finished_at ?? execution.started_at ?? execution.created_at;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function statusStyle(status: GraphExecutionStatus) {
  if (status === "succeeded") return s.statusSuccess;
  if (status === "failed") return s.statusFailure;
  if (status === "cancelled" || status === "cancelling") {
    return s.statusCancelled;
  }
  return s.statusActive;
}
