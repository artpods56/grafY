export const NEW_PROJECT_ROUTE_ID = "new";

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

/** A Workbench address names a Project; a Project holds the Graphs. */
export function isSupportedWorkbenchProjectRoute(
  _workspaceSlug: string,
  projectId: string,
): boolean {
  return projectId === NEW_PROJECT_ROUTE_ID || UUID_PATTERN.test(projectId);
}

export function workbenchProjectPath(
  workspaceSlug: string,
  projectId: string,
): string {
  return `/workspaces/${encodeURIComponent(workspaceSlug)}/projects/${encodeURIComponent(projectId)}`;
}

/** @deprecated a Workbench address names a Project, not a Graph. */
export const workbenchGraphPath = workbenchProjectPath;
