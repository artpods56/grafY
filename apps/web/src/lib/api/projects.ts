import { request } from "./client";
import type {
  AppliedNodeSecret,
  ApplyNodeSecretRequest,
  CheckpointProjectRequest,
  CheckpointProjectResponse,
  CollaborativeHead,
  CopyExactHeadRequest,
  CreateProjectRequest,
  GraphDefinition,
  InstanceKey,
  InstanceResult,
  InstanceStateList,
  Project,
  ProjectBrowserList,
  ProjectCheckpoint,
  ProjectCheckpointList,
  ProjectList,
  ProjectNodeSecrets,
  Run,
  RunList,
  StartRunRequest,
  SubmitProjectCommandRequest,
  SubmitProjectCommandResponse,
  SavedGraph,
} from "./contract";

function workspacePath(workspaceId: string, suffix = ""): string {
  return `/v1/workspaces/${encodeURIComponent(workspaceId)}${suffix}`;
}

function projectPath(
  workspaceId: string,
  projectId: string,
  suffix = "",
): string {
  return workspacePath(
    workspaceId,
    `/projects/${encodeURIComponent(projectId)}${suffix}`,
  );
}

/** Every Project this person can reach, across their Workspaces. */
export function listAccessibleProjects(signal?: AbortSignal) {
  return request<ProjectBrowserList>("GET", "/v1/me/projects", { signal });
}

/** The Projects of one Workspace. */
export function listWorkspaceProjects(workspaceId: string) {
  return request<ProjectList>("GET", workspacePath(workspaceId, "/projects"));
}

/**
 * Create a Project with its first Graph. The caller names both: the Project is
 * what a person opens, the Graph is the canvas inside it.
 */
export function createProject(workspaceId: string, body: CreateProjectRequest) {
  return request<Project>("POST", workspacePath(workspaceId, "/projects"), {
    body,
  });
}

export function copyExactHead(
  targetWorkspaceId: string,
  body: CopyExactHeadRequest,
) {
  return request<Project>(
    "POST",
    workspacePath(targetWorkspaceId, "/projects/copies"),
    { body },
  );
}

export function deleteProject(
  workspaceId: string,
  projectId: string,
  options?: {
    expectedRoomEpoch?: string;
    expectedSequence?: number;
  },
) {
  const query = new URLSearchParams();
  if (
    options?.expectedRoomEpoch !== undefined &&
    options.expectedSequence !== undefined
  ) {
    query.set("expected_room_epoch", options.expectedRoomEpoch);
    query.set("expected_sequence", String(options.expectedSequence));
  }
  const suffix = query.size > 0 ? `?${query}` : "";
  return request<undefined>(
    "DELETE",
    projectPath(workspaceId, projectId, suffix),
  );
}

/** The head the author's document is projected from, with the whole Project document. */
export function getCollaborativeHead(
  workspaceId: string,
  projectId: string,
  signal?: AbortSignal,
): Promise<CollaborativeHead> {
  return request<CollaborativeHead>(
    "GET",
    projectPath(workspaceId, projectId, "/head"),
    { signal },
  );
}

/**
 * One Graph of a Project's document, as the canvas sees it.
 *
 * A Project document holds every Graph, so opening a Workbench is a projection,
 * not a request: the revision the canvas saves against is the Project head's
 * collaboration sequence, shared by all of its Graphs.
 */
export function graphFromProjectHead(
  head: CollaborativeHead,
  graphId: string,
): SavedGraph | null {
  const graph = head.document.graphs.find(
    (candidate: GraphDefinition) => candidate.id === graphId,
  );
  if (!graph) return null;
  return {
    id: graph.id,
    name: graph.name,
    revision: head.collaboration_sequence,
    created_at: head.updated_at,
    updated_at: head.updated_at,
    document: graph.document,
  };
}

export function submitProjectCommand(
  workspaceId: string,
  projectId: string,
  requestBody: SubmitProjectCommandRequest,
): Promise<SubmitProjectCommandResponse> {
  return request<SubmitProjectCommandResponse>(
    "POST",
    projectPath(workspaceId, projectId, "/commands"),
    { body: requestBody },
  );
}

export function checkpointProject(
  workspaceId: string,
  projectId: string,
  requestBody: CheckpointProjectRequest,
): Promise<CheckpointProjectResponse> {
  return request<CheckpointProjectResponse>(
    "POST",
    projectPath(workspaceId, projectId, "/checkpoints"),
    { body: requestBody },
  );
}

export function listProjectCheckpoints(workspaceId: string, projectId: string) {
  return request<ProjectCheckpointList>(
    "GET",
    projectPath(workspaceId, projectId, "/checkpoints"),
  );
}

export function getProjectCheckpoint(
  workspaceId: string,
  projectId: string,
  revision: number,
) {
  return request<ProjectCheckpoint>(
    "GET",
    projectPath(
      workspaceId,
      projectId,
      `/checkpoints/${encodeURIComponent(String(revision))}`,
    ),
  );
}

/** Bring a retained checkpoint forward as the current state; history is never rewound. */
export function restoreProjectCheckpoint(
  workspaceId: string,
  projectId: string,
  revision: number,
  requestBody: CheckpointProjectRequest,
) {
  return request<CheckpointProjectResponse>(
    "POST",
    projectPath(
      workspaceId,
      projectId,
      `/checkpoints/${encodeURIComponent(String(revision))}/restore`,
    ),
    { body: requestBody },
  );
}

export function recordProjectOpen(workspaceId: string, projectId: string) {
  return request<undefined>(
    "POST",
    projectPath(workspaceId, projectId, "/opened"),
  );
}

// --- Runs ------------------------------------------------------------------
// A Run is a demand for freshness on named node instances of one Graph. It is
// started, listed, read and cancelled; it is never "executed" or "streamed".

function instanceQuery(params: {
  graph_id: string;
  node_id: string;
  call_path?: readonly string[];
}): string {
  const query = new URLSearchParams({
    graph_id: params.graph_id,
    node_id: params.node_id,
  });
  for (const segment of params.call_path ?? []) {
    query.append("call_path", segment);
  }
  return query.toString();
}

/** Ask for a Graph's targets to become fresh. Returns the Run that holds the demand. */
export function startRun(
  workspaceId: string,
  projectId: string,
  body: StartRunRequest,
) {
  return request<Run>("POST", projectPath(workspaceId, projectId, "/runs"), {
    body,
  });
}

export function listRuns(
  workspaceId: string,
  projectId: string,
  options: { activeOnly?: boolean } = {},
  signal?: AbortSignal,
) {
  const query =
    options.activeOnly === true
      ? "?active=true"
      : options.activeOnly === false
        ? "?active=false"
        : "";
  return request<RunList>(
    "GET",
    projectPath(workspaceId, projectId, `/runs${query}`),
    { signal },
  );
}

export function getRun(
  workspaceId: string,
  projectId: string,
  runId: string,
  signal?: AbortSignal,
) {
  return request<Run>(
    "GET",
    projectPath(workspaceId, projectId, `/runs/${encodeURIComponent(runId)}`),
    { signal },
  );
}

/** Withdraw one Run's demand. A computation another Run still needs goes on. */
export function cancelRun(
  workspaceId: string,
  projectId: string,
  runId: string,
) {
  return request<Run>(
    "POST",
    projectPath(
      workspaceId,
      projectId,
      `/runs/${encodeURIComponent(runId)}/cancel`,
    ),
  );
}

/** Derived state for every instance of one Graph. Nothing here is stored. */
export function listGraphInstances(
  workspaceId: string,
  projectId: string,
  graphId: string,
  signal?: AbortSignal,
) {
  return request<InstanceStateList>(
    "GET",
    projectPath(
      workspaceId,
      projectId,
      `/graphs/${encodeURIComponent(graphId)}/instances`,
    ),
    { signal },
  );
}

/**
 * One instance's state and the last result it produced, which may be stale.
 *
 * A result is addressed by the instance, never by the Run that asked for it,
 * so the caller names the instance: Graph, node, and the call path of the
 * callee for a node reached through a call node.
 */
export function getInstanceResult(
  workspaceId: string,
  projectId: string,
  instance: Pick<InstanceKey, "graph_id" | "node_id"> & {
    call_path?: readonly string[];
  },
  signal?: AbortSignal,
) {
  return request<InstanceResult>(
    "GET",
    projectPath(workspaceId, projectId, "/instance-result") +
      `?${instanceQuery({
        graph_id: instance.graph_id,
        node_id: instance.node_id,
        call_path: instance.call_path,
      })}`,
    { signal },
  );
}

// --- Node secrets ----------------------------------------------------------

export function getProjectNodeSecrets(
  workspaceId: string,
  projectId: string,
  graphId: string,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({ graph_id: graphId });
  return request<ProjectNodeSecrets>(
    "GET",
    `${projectPath(workspaceId, projectId, "/node-secrets")}?${query}`,
    { signal },
  );
}

export function applyNodeSecret(
  workspaceId: string,
  projectId: string,
  graphId: string,
  nodeId: string,
  name: string,
  requestBody: ApplyNodeSecretRequest,
) {
  return request<AppliedNodeSecret>(
    "PUT",
    nodeSecretPath(workspaceId, projectId, graphId, nodeId, name),
    { body: requestBody },
  );
}

export function removeNodeSecret(
  workspaceId: string,
  projectId: string,
  graphId: string,
  nodeId: string,
  name: string,
  expectedHeadSequence: number,
) {
  const query = new URLSearchParams({
    expected_head_sequence: String(expectedHeadSequence),
  });
  return request<undefined>(
    "DELETE",
    `${nodeSecretPath(workspaceId, projectId, graphId, nodeId, name)}?${query}`,
  );
}

function nodeSecretPath(
  workspaceId: string,
  projectId: string,
  graphId: string,
  nodeId: string,
  name: string,
): string {
  return projectPath(
    workspaceId,
    projectId,
    `/graphs/${encodeURIComponent(graphId)}` +
      `/nodes/${encodeURIComponent(nodeId)}` +
      `/secrets/${encodeURIComponent(name)}`,
  );
}
