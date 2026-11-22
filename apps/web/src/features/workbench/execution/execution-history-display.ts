/**
 * How a Run is displayed in the drawer. Separate from the query layer on
 * purpose: these functions read a style object, the loaders do not.
 */

import type {
  Run,
  RunStatus,
  RunTargetInput,
  WorkspaceMember,
} from "@/lib/api";

import { executionHistoryDrawerStyles as s } from "./ExecutionHistoryDrawer.styles";

/**
 * `cancelled` is part of the domain (ADR 0020) and of the Run status the UI has
 * to colour; it is spelled out here because the checked-in OpenAPI schema still
 * omits it. The union is correct either way.
 */
export type RunStatusName = RunStatus | "cancelled";

/** The only status that is not terminal: the demand has not been satisfied yet. */
const ACTIVE_RUN_STATUS = "running";

const MAX_LISTED_TARGETS = 3;
const SHORT_ID_PREFIX = 8;

export function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

/**
 * When the Run asked for freshness. A Run is created at that moment, so
 * `created_at` is its start; there is no separate start timestamp any more.
 */
export function runStartLabel(run: Run): string {
  return formatTimestamp(run.created_at);
}

/** When the Run stopped holding its demand, or `null` while it still holds it. */
export function runFinishLabel(run: Run): string | null {
  return run.finished_at === null ? null : formatTimestamp(run.finished_at);
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function statusStyle(status: RunStatusName) {
  if (status === "succeeded") return s.statusSuccess;
  if (status === "failed") return s.statusFailure;
  if (status === "cancelled" || status === "interrupted") {
    return s.statusCancelled;
  }
  return s.statusActive;
}

export function isActiveRun(run: Run): boolean {
  return run.status === ACTIVE_RUN_STATUS;
}

/** A stable handle on an id, for the ids the person cannot name. */
function shortId(id: string): string {
  return id.length > SHORT_ID_PREFIX && id.includes("-")
    ? id.slice(0, SHORT_ID_PREFIX)
    : id;
}

/** Which Graph the Run demands freshness of, told from the Graph the author has open. */
export function graphLabel(
  graphId: string,
  openGraphId: string | null | undefined,
): string {
  if (openGraphId && graphId === openGraphId) return "this graph";
  return `graph ${shortId(graphId)}`;
}

/**
 * The node instances the Run targets. A target reached through a call node is
 * named by its call path, because that is what makes it a different instance.
 */
export function runTargetsSummary(
  targets: readonly RunTargetInput[],
  limit = MAX_LISTED_TARGETS,
): string {
  if (targets.length === 0) return "no targets";
  const word = targets.length === 1 ? "target" : "targets";
  const listed = targets.slice(0, limit).map(formatTarget);
  const rest = targets.length - listed.length;
  return `${targets.length} ${word}: ${listed.join(", ")}${
    rest > 0 ? ` +${rest} more` : ""
  }`;
}

function formatTarget(target: RunTargetInput): string {
  return target.call_path.length
    ? `${target.node_id} via ${target.call_path.join("/")}`
    : target.node_id;
}

/** User id → the name the Team knows them by. A member without a name is left out. */
export function runStarterNames(
  members: readonly WorkspaceMember[] | undefined,
): ReadonlyMap<string, string> {
  const names = new Map<string, string>();
  for (const member of members ?? []) {
    const name = member.user.display_name;
    if (name) names.set(member.user.id, name);
  }
  return names;
}

/**
 * Who started the Run. Never an id: a Run is a demand one person made of the
 * Project, and an unresolvable person is still a person.
 */
export function starterLabel(
  run: Run,
  names: ReadonlyMap<string, string>,
): string {
  const userId = run.started_by_user_id;
  if (userId === null) return "an unknown member";
  return names.get(userId) ?? "a Team member";
}
