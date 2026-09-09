import { collaborativeHeadFromLegacy } from "./graph-head";
import { API_BASE, request } from "./client";
import type {
  AppliedNodeSecret,
  ApplyNodeSecretRequest,
  CheckpointGraphRequest,
  CheckpointGraphResponse,
  LegacyCheckpointGraphResponse,
  CollaborativeHead,
  CopyExactHeadRequest,
  CopyExactHeadResponse,
  CreateSavedGraphRequest,
  CreateSavedGraphResponse,
  GraphNodeSecrets,
  GraphExecutionDetail,
  GraphExecutionList,
  GraphExecutionStatus,
  GraphMaterializations,
  GeoFeatureQuery,
  GeoRenderDescriptor,
  RunExecutionEvent,
  RunExecution,
  RunRequest,
  RunResponse,
  SavedGraph,
  SubmitGraphCommandRequest,
  SubmitGraphCommandResponse,
  LegacySubmitGraphCommandResponse,
  TableCell,
  TablePage,
  TableSchema,
  UploadResponse,
  UpdateSavedGraphRequest,
} from "./contract";

export interface RunExecutionEventHandlers {
  onEvent: (event: RunExecutionEvent) => void;
  onError: (error: Event | Error) => void;
  onOpen?: () => void;
}

export interface RunExecutionEventSubscription {
  close: () => void;
}

export type ArtifactInteractionScalar = string | number | boolean | null;

export interface TableExactMatchInput {
  values: Record<string, ArtifactInteractionScalar>;
}

export interface TableExactMatchGroupInput {
  rows: TableExactMatchInput[];
}

export interface TableQueryInput {
  filter_groups: TableExactMatchGroupInput[];
  highlight_groups: TableExactMatchGroupInput[];
  offset: number;
  limit: number;
  column_ids?: string[];
  max_cell_characters: number;
}

export interface GeoFeatureQueryInput {
  rows: TableExactMatchInput[];
}

const RUN_EXECUTION_EVENT_KINDS = [
  "execution.status",
  "node.status",
  "node.progress",
] as const;

const RUN_EXECUTION_STATUSES = new Set([
  "queued",
  "running",
  "cancelling",
  "cancelled",
  "succeeded",
  "failed",
]);

const RUN_EXECUTION_NODE_STATUSES = new Set([
  "running",
  "succeeded",
  "failed",
  "skipped",
]);

const EXECUTION_EVENT_DATE_TIME =
  /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|[+-](\d{2}):(\d{2}))$/;
const EXECUTION_EVENT_UUID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const MAX_EXECUTION_EVENT_PATH_DEPTH = 64;
const MAX_EXECUTION_IDENTIFIER_CHARACTERS = 255;
const MAX_EXECUTION_PROGRESS_MESSAGE_CHARACTERS = 1_000;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validExecutionEventUuid(value: unknown): value is string {
  return typeof value === "string" && EXECUTION_EVENT_UUID.test(value);
}

function nullableExecutionEventUuid(value: unknown): value is string | null {
  return value === null || validExecutionEventUuid(value);
}

function validExecutionIdentifier(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const normalized = value.trim();
  return normalized.length >= 1 &&
    normalized.length <= MAX_EXECUTION_IDENTIFIER_CHARACTERS;
}

function nullableExecutionIdentifier(
  value: unknown,
): value is string | null {
  return value === null || validExecutionIdentifier(value);
}

function nullableNonNegativeInteger(value: unknown): value is number | null {
  return value === null ||
    (typeof value === "number" &&
      Number.isSafeInteger(value) &&
      value >= 0);
}

function validExecutionEventDateTime(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = EXECUTION_EVENT_DATE_TIME.exec(value);
  if (!match) return false;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const offsetHour = match[7] === undefined ? 0 : Number(match[7]);
  const offsetMinute = match[8] === undefined ? 0 : Number(match[8]);
  const leapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [
    31,
    leapYear ? 29 : 28,
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ];
  return month >= 1 &&
    month <= 12 &&
    day >= 1 &&
    day <= (daysInMonth[month - 1] ?? 0) &&
    hour <= 23 &&
    minute <= 59 &&
    second <= 59 &&
    offsetHour <= 23 &&
    offsetMinute <= 59 &&
    !Number.isNaN(Date.parse(value));
}

function parseRunExecutionEvent(
  eventKind: RunExecutionEvent["kind"],
  raw: unknown,
): RunExecutionEvent {
  if (typeof raw !== "string") {
    throw new Error(`${eventKind} event data must be JSON text.`);
  }
  const value: unknown = JSON.parse(raw);
  if (
    !isRecord(value) ||
    value.kind !== eventKind ||
    typeof value.sequence !== "number" ||
    !Number.isSafeInteger(value.sequence) ||
    value.sequence < 1 ||
    !validExecutionEventUuid(value.execution_id) ||
    !validExecutionEventDateTime(value.occurred_at)
  ) {
    throw new Error(`Invalid ${eventKind} execution event payload.`);
  }

  if (eventKind === "execution.status") {
    if (
      typeof value.status !== "string" ||
      !RUN_EXECUTION_STATUSES.has(value.status) ||
      !nullableExecutionIdentifier(value.active_node_id)
    ) {
      throw new Error(`Invalid ${eventKind} execution event payload.`);
    }
    return value as unknown as RunExecutionEvent;
  }

  if (
    !Array.isArray(value.node_path) ||
    value.node_path.length === 0 ||
    value.node_path.length > MAX_EXECUTION_EVENT_PATH_DEPTH ||
    !value.node_path.every(validExecutionIdentifier) ||
    !validExecutionIdentifier(value.node_id) ||
    !nullableExecutionEventUuid(value.node_run_id) ||
    !nullableNonNegativeInteger(value.invocation_index) ||
    !Array.isArray(value.invocation_path) ||
    value.invocation_path.length > MAX_EXECUTION_EVENT_PATH_DEPTH ||
    !value.invocation_path.every(
      (index) =>
        typeof index === "number" &&
        Number.isSafeInteger(index) &&
        index >= 0,
    )
  ) {
    throw new Error(`Invalid ${eventKind} execution event payload.`);
  }

  if (eventKind === "node.status") {
    if (
      typeof value.status !== "string" ||
      !RUN_EXECUTION_NODE_STATUSES.has(value.status)
    ) {
      throw new Error(`Invalid ${eventKind} execution event payload.`);
    }
    return value as unknown as RunExecutionEvent;
  }

  if (
    typeof value.message !== "string" ||
    value.message.trim().length === 0 ||
    value.message.length > MAX_EXECUTION_PROGRESS_MESSAGE_CHARACTERS ||
    !nullableNonNegativeInteger(value.current) ||
    !nullableNonNegativeInteger(value.total) ||
    (value.current !== null &&
      value.total !== null &&
      value.current > value.total)
  ) {
    throw new Error(`Invalid ${eventKind} execution event payload.`);
  }
  return value as unknown as RunExecutionEvent;
}

export interface ListGraphExecutionsOptions {
  limit?: number;
  cursor?: string;
  graphRevision?: number;
  status?: GraphExecutionStatus;
  nodeId?: string;
}

export function getSavedGraph(
  workspaceId: string,
  graphId: string,
  signal?: AbortSignal,
) {
  return request<SavedGraph>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs/${encodeURIComponent(graphId)}`,
    { signal },
  );
}

export function getGraphMaterializations(
  workspaceId: string,
  graphId: string,
  graphRevision: number,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    graph_revision: String(graphRevision),
  });
  return request<GraphMaterializations>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs/${encodeURIComponent(graphId)}/materializations?${query}`,
    { signal },
  );
}

export function listGraphExecutions(
  workspaceId: string,
  graphId: string,
  options: ListGraphExecutionsOptions = {},
  signal?: AbortSignal,
) {
  const query = new URLSearchParams();
  query.set("limit", String(options.limit ?? 20));
  if (options.cursor) query.set("cursor", options.cursor);
  if (options.graphRevision !== undefined) {
    query.set("graph_revision", String(options.graphRevision));
  }
  if (options.status) query.set("status", options.status);
  if (options.nodeId) query.set("node_id", options.nodeId);
  return request<GraphExecutionList>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs/${encodeURIComponent(graphId)}/executions?${query}`,
    { signal },
  );
}

export function getGraphExecution(
  workspaceId: string,
  graphId: string,
  executionId: string,
  signal?: AbortSignal,
) {
  return request<GraphExecutionDetail>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs/${encodeURIComponent(graphId)}/executions/${encodeURIComponent(executionId)}`,
    { signal },
  );
}

export function getGraphNodeSecrets(
  workspaceId: string,
  graphId: string,
  signal?: AbortSignal,
) {
  return request<GraphNodeSecrets>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs/${encodeURIComponent(graphId)}/node-secrets`,
    { signal },
  );
}

export function applyNodeSecret(
  workspaceId: string,
  graphId: string,
  nodeId: string,
  name: string,
  requestBody: ApplyNodeSecretRequest,
) {
  return request<AppliedNodeSecret>(
    "PUT",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs/${encodeURIComponent(graphId)}/nodes/${encodeURIComponent(nodeId)}/secrets/${encodeURIComponent(name)}`,
    { body: requestBody },
  );
}

export function removeNodeSecret(
  workspaceId: string,
  graphId: string,
  nodeId: string,
  name: string,
  expectedGraphRevision: number,
) {
  const query = new URLSearchParams({
    expected_graph_revision: String(expectedGraphRevision),
  });
  return request<undefined>(
    "DELETE",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs/${encodeURIComponent(graphId)}/nodes/${encodeURIComponent(nodeId)}/secrets/${encodeURIComponent(name)}?${query}`,
  );
}

export function createSavedGraph(
  workspaceId: string,
  requestBody: CreateSavedGraphRequest,
) {
  return request<CreateSavedGraphResponse>("POST", `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs`, {
    body: requestBody,
  });
}

export function updateSavedGraph(
  workspaceId: string,
  graphId: string,
  requestBody: UpdateSavedGraphRequest,
) {
  return request<SavedGraph>(
    "PUT",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs/${encodeURIComponent(graphId)}`,
    { body: requestBody },
  );
}

export function getCollaborativeHead(workspaceId: string, graphId: string) {
  return request<CollaborativeHead>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs/${encodeURIComponent(graphId)}/head/document`,
  );
}

export async function submitGraphCommand(
  workspaceId: string,
  graphId: string,
  requestBody: SubmitGraphCommandRequest,
): Promise<SubmitGraphCommandResponse> {
  const response = await request<LegacySubmitGraphCommandResponse>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs/${encodeURIComponent(graphId)}/commands`,
    { body: requestBody },
  );
  return { ...response, head: collaborativeHeadFromLegacy(response.head) };
}

export async function checkpointGraph(
  workspaceId: string,
  graphId: string,
  requestBody: CheckpointGraphRequest,
): Promise<CheckpointGraphResponse> {
  const response = await request<LegacyCheckpointGraphResponse>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs/${encodeURIComponent(graphId)}/checkpoint`,
    { body: requestBody },
  );
  return { ...response, head: collaborativeHeadFromLegacy(response.head) };
}

export function copyExactHead(
  targetWorkspaceId: string,
  requestBody: CopyExactHeadRequest,
) {
  return request<CopyExactHeadResponse>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(targetWorkspaceId)}/graphs/copies`,
    { body: requestBody },
  );
}

export function deleteSavedGraph(
  workspaceId: string,
  graphId: string,
  expectedRevision: number,
  options?: {
    expectedRoomEpoch?: string;
    expectedSequence?: number;
  },
) {
  const query = new URLSearchParams({
    expected_revision: String(expectedRevision),
  });
  if (
    options?.expectedRoomEpoch !== undefined &&
    options.expectedSequence !== undefined
  ) {
    query.set("expected_room_epoch", options.expectedRoomEpoch);
    query.set("expected_sequence", String(options.expectedSequence));
  }
  return request<undefined>(
    "DELETE",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/graphs/${encodeURIComponent(graphId)}?${query}`,
  );
}

export async function uploadFile(
  workspaceId: string,
  file: File,
  signal?: AbortSignal,
): Promise<UploadResponse> {
  const body = new FormData();
  body.append("file", file, file.name);
  return request<UploadResponse>("POST", `/v1/workspaces/${encodeURIComponent(workspaceId)}/uploads`, {
    body,
    signal,
  });
}

export function runGraph(workspaceId: string, requestBody: RunRequest) {
  return request<RunResponse>("POST", `/v1/workspaces/${encodeURIComponent(workspaceId)}/runs`, {
    body: requestBody,
  });
}

export function startRunExecution(
  workspaceId: string,
  requestBody: RunRequest,
) {
  return request<RunExecution>("POST", `/v1/workspaces/${encodeURIComponent(workspaceId)}/executions`, {
    body: requestBody,
  });
}

export function getRunExecution(workspaceId: string, executionId: string) {
  return request<RunExecution>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/executions/${encodeURIComponent(executionId)}`,
  );
}

export function subscribeRunExecutionEvents(
  workspaceId: string,
  executionId: string,
  handlers: RunExecutionEventHandlers,
): RunExecutionEventSubscription {
  let source: EventSource;
  try {
    source = new EventSource(
      `${API_BASE}/v1/workspaces/${encodeURIComponent(workspaceId)}/executions/${encodeURIComponent(executionId)}/events`,
    );
  } catch (error) {
    handlers.onError(
      error instanceof Error
        ? error
        : new Error("Live execution events are unavailable."),
    );
    return { close() {} };
  }
  const eventListeners = RUN_EXECUTION_EVENT_KINDS.map((eventKind) => {
    const listener: EventListener = (event) => {
      try {
        const raw = "data" in event ? event.data : undefined;
        handlers.onEvent(parseRunExecutionEvent(eventKind, raw));
      } catch (error) {
        handlers.onError(
          error instanceof Error
            ? error
            : new Error(`Could not read ${eventKind} execution event.`),
        );
      }
    };
    source.addEventListener(eventKind, listener);
    return { eventKind, listener };
  });
  const openListener: EventListener = () => handlers.onOpen?.();
  const errorListener: EventListener = (event) => handlers.onError(event);
  source.addEventListener("open", openListener);
  source.addEventListener("error", errorListener);

  let closed = false;
  return {
    close() {
      if (closed) return;
      closed = true;
      for (const { eventKind, listener } of eventListeners) {
        source.removeEventListener(eventKind, listener);
      }
      source.removeEventListener("open", openListener);
      source.removeEventListener("error", errorListener);
      source.close();
    },
  };
}

export function cancelRunExecution(workspaceId: string, executionId: string) {
  return request<RunExecution>(
    "DELETE",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/executions/${encodeURIComponent(executionId)}`,
  );
}

export function artifactContentUrl(
  workspaceId: string,
  contentUrl: string | null | undefined,
): string | null {
  if (!contentUrl) return null;

  if (/^[a-z][a-z\d+.-]*:/i.test(contentUrl)) return contentUrl;
  if (contentUrl.startsWith("/api/")) return contentUrl;
  if (contentUrl.startsWith("/v1/")) return `${API_BASE}${contentUrl}`;

  const resolved = new URL(
    contentUrl,
    `https://grafy.invalid/api/v1/workspaces/${encodeURIComponent(workspaceId)}/`,
  );
  return `${resolved.pathname}${resolved.search}${resolved.hash}`;
}

/**
 * Resolve the download URL for an artifact in the given format. The artifact
 * summary carries `download_formats`; the caller picks one format and builds
 * the relative `/download` URL.
 */
export function artifactDownloadUrl(
  workspaceId: string,
  artifactId: string,
  format: string,
): string {
  return artifactContentUrl(
    workspaceId,
    `./artifacts/${encodeURIComponent(artifactId)}/download?format=${encodeURIComponent(format)}`,
  ) as string;
}

export function getArtifactTablePage(
  workspaceId: string,
  artifactId: string,
  offset: number,
  limit: number,
  columnIds: readonly string[],
  maxCellCharacters: number,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    offset: String(offset),
    limit: String(limit),
    max_cell_characters: String(maxCellCharacters),
  });
  for (const columnId of columnIds) {
    query.append("column_ids", columnId);
  }
  return request<TablePage>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/table/page?${query}`,
    { signal },
  );
}

export function getArtifactTableSchema(
  workspaceId: string,
  artifactId: string,
  signal?: AbortSignal,
) {
  return request<TableSchema>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/table/schema`,
    { signal },
  );
}

export function queryArtifactTablePage(
  workspaceId: string,
  artifactId: string,
  query: TableQueryInput,
  signal?: AbortSignal,
) {
  return request<TablePage>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/table/query`,
    { body: query, signal },
  );
}

export function getArtifactGeoRender(
  workspaceId: string,
  artifactId: string,
  signal?: AbortSignal,
) {
  return request<GeoRenderDescriptor>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/geo/render`,
    { signal },
  );
}

export function queryArtifactGeoFeatures(
  workspaceId: string,
  artifactId: string,
  query: GeoFeatureQueryInput,
  signal?: AbortSignal,
) {
  return request<GeoFeatureQuery>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/geo/query`,
    { body: query, signal },
  );
}

export function getArtifactTableCell(
  workspaceId: string,
  artifactId: string,
  rowIndex: number,
  columnId: string,
  signal?: AbortSignal,
) {
  const query = new URLSearchParams({
    row_index: String(rowIndex),
    column_id: columnId,
  });
  return request<TableCell>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/artifacts/${encodeURIComponent(artifactId)}/table/cell?${query}`,
    { signal },
  );
}
