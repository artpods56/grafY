/**
 * Query layer for the Runs drawer: the SWR keys and their loaders. Nothing here
 * knows how a run is displayed.
 *
 * A Run is a demand for freshness on named node instances of one Graph (ADR
 * 0020), so the drawer reads the Project's Runs and nothing else: there is no
 * execution history route, no per-execution detail, and nothing to page
 * through — `GET /projects/{id}/runs` answers the whole list, newest first.
 */

import {
  listRuns,
  listWorkspaceMembers,
  type Run,
  type RunList,
  type WorkspaceMember,
} from "@/lib/api";

export type ProjectRunsKey = readonly ["project-runs", string, string];

/** `null` with no Project: the Run list belongs to a Project, so there is nothing to ask for. */
export function projectRunsKey(
  workspaceId: string,
  projectId: string | null | undefined,
): ProjectRunsKey | null {
  return projectId ? ["project-runs", workspaceId, projectId] : null;
}

export async function loadProjectRuns([
  ,
  workspaceId,
  projectId,
]: ProjectRunsKey): Promise<RunList> {
  return listRuns(workspaceId, projectId);
}

/**
 * A Run records only `started_by_user_id`, and an authoring surface does not
 * print a user id, so the drawer resolves the starter through the Team roster.
 * This is a best-effort lookup: the roster is not the subject of the drawer and
 * its absence costs only a name.
 */
export type RunStartersKey = readonly ["project-run-starters", string];

export function runStartersKey(
  workspaceId: string,
  runs: readonly Run[],
): RunStartersKey | null {
  return runs.some((run) => run.started_by_user_id !== null)
    ? ["project-run-starters", workspaceId]
    : null;
}

export async function loadRunStarters([, workspaceId]: RunStartersKey): Promise<
  readonly WorkspaceMember[]
> {
  return listWorkspaceMembers(workspaceId);
}
