import type {
  NodeRegistry,
  NodeSpec,
} from "./contract";
import { API_BASE, ApiError, request } from "./client";
import type { components } from "./generated/grafy";

type Schemas = components["schemas"];

export type AgentEnvironmentStatus = Schemas["AgentEnvironmentStatus"];
export type AgentEnvironment = Schemas["AgentEnvironmentResponse"];
export type AgentEnvironmentList = Schemas["AgentEnvironmentListResponse"];
export type CreateAgentEnvironmentRequest =
  Schemas["CreateAgentEnvironmentRequest"];
export type AgentDraftAnchorRequest = Schemas["AnchoredPortRequest"];
export type AgentDraftPlacementRequest = Schemas["DraftGraphPlacementRequest"];
export type CreateAgentDraftRequest = Schemas["CreateAgentDraftRequest"];
export type AgentThread = Schemas["AgentThreadResponse"];
export type AgentDraftStatus = Schemas["DraftNodeStatus"];
export type AgentDraft = Schemas["AgentDraftResponse"];
export type AgentDraftDetail = Schemas["AgentDraftDetailResponse"];
export type AgentRunStatus = Schemas["AgentRunStatus"];
export type AgentRun = Schemas["AgentRunResponse"];
export type NodeBuildStatus = Schemas["NodeBuildStatus"];
export type CapabilityManifest = Schemas["CapabilityManifestResponse"];
export type BuildArtifactSet = Schemas["BuildArtifactSetResponse"];
export type NodeBuild = Schemas["NodeBuildResponse"];
export type CreateAgentDraftResponse = Schemas["CreateAgentDraftResponse"];
export type AgentRunDetail = Schemas["AgentRunDetailResponse"];
export type QueueAgentFollowUpRequest = Schemas["QueueAgentFollowUpRequest"];
export type AgentFollowUpRunResponse = Schemas["AgentFollowUpRunResponse"];

export type AgentEventKind =
  | "run_queued"
  | "run_claimed"
  | "run_status_changed"
  | "build_status_changed"
  | "capabilities_requested"
  | "capabilities_approved"
  | "release_published"
  | "message";

export interface AgentEvent {
  id: string;
  thread_id: string;
  run_id: string | null;
  sequence: number;
  kind: AgentEventKind;
  message: string;
  draft_node_id: string | null;
  build_attempt_id: string | null;
  run_status: AgentRunStatus | null;
  build_status: NodeBuildStatus | null;
  capability_digest: string | null;
  release_revision: number | null;
  created_at: string;
}

export type CapabilityApproval = Schemas["CapabilityApprovalResponse"];
export type NodeRelease = Schemas["NodeReleaseResponse"];
export type PublishAgentBuildResponse = Schemas["PublishBuildResponse"];
export type PublishGraphPromotionRequest =
  Schemas["PublishGraphPromotionRequest"];
export type AgentBuildReview = Schemas["BuildReviewResponse"];
export type AgentBuildReviewFile = Schemas["BuildReviewFileResponse"];
export type AgentBuildReviewFileContent =
  Schemas["BuildReviewFileContentResponse"];

export type AgentDraftProgressState =
  | AgentDraftStatus
  | AgentRunStatus
  | NodeBuildStatus;

/** Runtime authoring detail layered over the durable draft metadata in NodeSpec. */
export interface AgentDraftProgress {
  draftId: string;
  runId: string | null;
  buildId: string | null;
  threadId: string | null;
  environmentId: string | null;
  state: AgentDraftProgressState;
  error: string | null;
  capabilities: CapabilityManifest | null;
  capabilityDigest: string | null;
  capabilityApprovalId: string | null;
  releaseRevision: number | null;
  targetOperatorVersion: number;
  lastEventSequence: number;
}

const AGENT_EVENT_KINDS: readonly AgentEventKind[] = [
  "run_queued",
  "run_claimed",
  "run_status_changed",
  "build_status_changed",
  "capabilities_requested",
  "capabilities_approved",
  "release_published",
  "message",
];

function progressState(
  draft: AgentDraft,
  run: AgentRun,
  build: NodeBuild,
): AgentDraftProgressState {
  if (draft.status === "published" || build.status === "published") {
    return "published";
  }
  if (
    run.status === "failed" ||
    run.status === "cancelling" ||
    run.status === "cancelled" ||
    run.status === "interrupting" ||
    run.status === "interrupted"
  ) {
    return run.status;
  }
  if (run.status === "claimed") return "claimed";
  return build.status;
}

export function agentDraftProgressFromCreate(
  response: CreateAgentDraftResponse,
): AgentDraftProgress {
  return {
    draftId: response.draft.id,
    runId: response.run.id,
    buildId: response.build.id,
    threadId: response.thread.id,
    environmentId: response.environment.id,
    state: progressState(response.draft, response.run, response.build),
    error: response.build.failure_message ?? response.run.error ?? null,
    capabilities: response.build.capabilities ?? null,
    capabilityDigest: response.build.capabilities?.digest ?? null,
    capabilityApprovalId: null,
    releaseRevision:
      response.draft.published_revision > 0
        ? response.draft.published_revision
        : null,
    targetOperatorVersion: response.node_spec.operator_version,
    lastEventSequence: 0,
  };
}

export function agentDraftProgressFromDetail(
  detail: AgentDraftDetail,
): AgentDraftProgress {
  return {
    draftId: detail.draft.id,
    runId: detail.latest_run.id,
    buildId: detail.latest_build.id,
    threadId: detail.thread.id,
    environmentId: detail.environment.id,
    state: progressState(
      detail.draft,
      detail.latest_run,
      detail.latest_build,
    ),
    error:
      detail.latest_build.failure_message ?? detail.latest_run.error ?? null,
    capabilities: detail.latest_build.capabilities ?? null,
    capabilityDigest: detail.latest_build.capabilities?.digest ?? null,
    capabilityApprovalId:
      detail.capability_approval?.id ??
      detail.release?.capability_approval_id ??
      null,
    releaseRevision: detail.release?.revision ??
      (detail.draft.published_revision > 0
        ? detail.draft.published_revision
        : null),
    targetOperatorVersion: detail.node_spec.operator_version,
    lastEventSequence: detail.thread.event_sequence,
  };
}

export function agentDraftProgressFromNodeSpec(
  spec: NodeSpec,
  current?: AgentDraftProgress | null,
): AgentDraftProgress | null {
  const authoring = spec.agent_authoring;
  if (!authoring) return null;
  if (current?.draftId === authoring.draft_node_id) {
    const publishedVersionIsCurrent =
      authoring.runnable &&
      current.targetOperatorVersion <= spec.operator_version;
    const catalogOwnsCurrentRevision =
      current.targetOperatorVersion <= spec.operator_version;
    const catalogIsSettled =
      authoring.status === "awaiting_approval" ||
      authoring.status === "failed" ||
      authoring.status === "cancelled" ||
      authoring.status === "published";
    return {
      ...current,
      state: publishedVersionIsCurrent
        ? "published"
        : catalogOwnsCurrentRevision && catalogIsSettled
          ? authoring.status
          : current.state,
      releaseRevision:
        authoring.release_revision ?? current.releaseRevision,
    };
  }
  return {
    draftId: authoring.draft_node_id,
    runId: null,
    buildId: null,
    threadId: null,
    environmentId: null,
    state: authoring.status,
    error: null,
    capabilities: null,
    capabilityDigest: null,
    capabilityApprovalId: null,
    releaseRevision: authoring.release_revision ?? null,
    targetOperatorVersion: spec.operator_version,
    lastEventSequence: 0,
  };
}

export function agentDraftProgressFromFollowUp(
  response: AgentFollowUpRunResponse,
  draftId: string,
  previous: AgentDraftProgress,
): AgentDraftProgress {
  const build = response.builds.find(
    (candidate) => candidate.draft_node_id === draftId,
  );
  const spec = response.node_specs.find(
    (candidate) => candidate.agent_authoring?.draft_node_id === draftId,
  );
  if (!build || !spec) {
    throw new Error(`Follow-up run did not include generated draft ${draftId}`);
  }
  return {
    ...previous,
    runId: response.run.id,
    buildId: build.id,
    threadId: response.thread.id,
    environmentId: response.environment.id,
    state: build.status,
    error: build.failure_message ?? response.run.error ?? null,
    capabilities: build.capabilities ?? null,
    capabilityDigest: build.capabilities?.digest ?? null,
    capabilityApprovalId: null,
    targetOperatorVersion: spec.operator_version,
    lastEventSequence: response.thread.event_sequence,
  };
}

export function upsertAgentNodeSpec(
  registry: NodeRegistry,
  nodeSpec: NodeSpec,
): NodeRegistry {
  return {
    ...registry,
    nodes: [
      ...registry.nodes.filter(
        (node) =>
          node.operator_id !== nodeSpec.operator_id ||
          node.operator_version !== nodeSpec.operator_version,
      ),
      nodeSpec,
    ],
  };
}

export function agentDraftProgressFromRunDetail(
  current: AgentDraftProgress,
  detail: AgentRunDetail,
): AgentDraftProgress {
  const builds = detail.builds.filter(
    (build) => build.draft_node_id === current.draftId,
  );
  const build = builds.find((candidate) => candidate.id === current.buildId) ??
    builds.at(-1);
  if (!build) {
    return {
      ...current,
      state: detail.run.status,
      error: detail.run.error ?? current.error,
    };
  }
  const state: AgentDraftProgressState =
    build.status === "published"
      ? "published"
      : detail.run.status === "failed" ||
          detail.run.status === "cancelling" ||
          detail.run.status === "cancelled" ||
          detail.run.status === "interrupting" ||
          detail.run.status === "interrupted"
        ? detail.run.status
        : build.status;
  return {
    ...current,
    runId: detail.run.id,
    buildId: build.id,
    environmentId: detail.run.environment_id,
    state,
    error: build.failure_message ?? detail.run.error ?? current.error,
    capabilities: build.capabilities ?? current.capabilities,
    capabilityDigest:
      build.capabilities?.digest ?? current.capabilityDigest,
  };
}

export function agentDraftProgressFromEvent(
  current: AgentDraftProgress,
  event: AgentEvent,
): AgentDraftProgress {
  if (
    event.sequence <= current.lastEventSequence ||
    (event.draft_node_id !== null && event.draft_node_id !== current.draftId)
  ) {
    return current;
  }
  const state: AgentDraftProgressState =
    event.kind === "release_published"
      ? "published"
      : event.build_status ?? event.run_status ?? current.state;
  const failed =
    state === "failed" ||
    state === "cancelled" ||
    state === "interrupted";
  return {
    ...current,
    buildId: event.build_attempt_id ?? current.buildId,
    state,
    error: failed ? event.message : current.error,
    capabilityDigest:
      event.capability_digest ?? current.capabilityDigest,
    releaseRevision:
      event.release_revision ?? current.releaseRevision,
    lastEventSequence: event.sequence,
  };
}

export async function listAgentEnvironments(
  workspaceId: string,
  signal?: AbortSignal,
): Promise<AgentEnvironmentList> {
  return request<AgentEnvironmentList>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-authoring/environments`,
    { signal },
  );
}

export async function createAgentEnvironment(
  workspaceId: string,
  input: CreateAgentEnvironmentRequest,
  signal?: AbortSignal,
): Promise<AgentEnvironment> {
  return request<AgentEnvironment>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-authoring/environments`,
    { body: input, signal },
  );
}

export async function createAgentDraft(
  workspaceId: string,
  graphId: string,
  input: CreateAgentDraftRequest,
  signal?: AbortSignal,
): Promise<CreateAgentDraftResponse> {
  return request<CreateAgentDraftResponse>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-authoring/graphs/${encodeURIComponent(graphId)}/drafts`,
    { body: input, signal },
  );
}

export async function getAgentDraft(
  workspaceId: string,
  draftId: string,
  signal?: AbortSignal,
): Promise<AgentDraftDetail> {
  return request<AgentDraftDetail>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-authoring/drafts/${encodeURIComponent(draftId)}`,
    { signal },
  );
}

export async function getAgentBuildReview(
  workspaceId: string,
  buildId: string,
  signal?: AbortSignal,
): Promise<AgentBuildReview> {
  return request<AgentBuildReview>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-authoring/builds/${encodeURIComponent(buildId)}/review`,
    { signal },
  );
}

export async function getAgentBuildReviewFile(
  workspaceId: string,
  buildId: string,
  filePath: string,
  signal?: AbortSignal,
): Promise<AgentBuildReviewFileContent> {
  const encodedPath = filePath.split("/").map(encodeURIComponent).join("/");
  return request<AgentBuildReviewFileContent>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-authoring/builds/${encodeURIComponent(buildId)}/review/files/${encodedPath}`,
    { signal },
  );
}

export async function getAgentRun(
  workspaceId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<AgentRunDetail> {
  return request<AgentRunDetail>(
    "GET",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-authoring/runs/${encodeURIComponent(runId)}`,
    { signal },
  );
}

export async function queueAgentFollowUp(
  workspaceId: string,
  threadId: string,
  input: QueueAgentFollowUpRequest,
  signal?: AbortSignal,
): Promise<AgentFollowUpRunResponse> {
  return request<AgentFollowUpRunResponse>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-authoring/threads/${encodeURIComponent(threadId)}/runs`,
    { body: input, signal },
  );
}

export async function cancelAgentRun(
  workspaceId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<AgentRun> {
  return request<AgentRun>(
    "DELETE",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-authoring/runs/${encodeURIComponent(runId)}`,
    { signal },
  );
}

export async function approveAgentBuild(
  workspaceId: string,
  buildId: string,
  capabilityDigest: string,
  signal?: AbortSignal,
): Promise<CapabilityApproval> {
  return request<CapabilityApproval>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-authoring/builds/${encodeURIComponent(buildId)}/approval`,
    { body: { capability_digest: capabilityDigest }, signal },
  );
}

export async function publishAgentBuild(
  workspaceId: string,
  buildId: string,
  capabilityApprovalId: string,
  graphPromotion?: PublishGraphPromotionRequest,
  signal?: AbortSignal,
): Promise<PublishAgentBuildResponse> {
  const body = graphPromotion
    ? {
        capability_approval_id: capabilityApprovalId,
        graph_promotion: graphPromotion,
      }
    : { capability_approval_id: capabilityApprovalId };
  return request<PublishAgentBuildResponse>(
    "POST",
    `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-authoring/builds/${encodeURIComponent(buildId)}/publish`,
    { body, signal },
  );
}

function isAgentEvent(value: unknown): value is AgentEvent {
  if (!value || typeof value !== "object") return false;
  const event = value as Partial<AgentEvent>;
  return (
    typeof event.id === "string" &&
    typeof event.thread_id === "string" &&
    typeof event.sequence === "number" &&
    Number.isSafeInteger(event.sequence) &&
    event.sequence > 0 &&
    typeof event.kind === "string" &&
    AGENT_EVENT_KINDS.includes(event.kind as AgentEventKind) &&
    typeof event.message === "string" &&
    typeof event.created_at === "string"
  );
}

function agentRunIsTerminal(status: AgentRunStatus | null): boolean {
  return status === "completed" ||
    status === "awaiting_approval" ||
    status === "failed" ||
    status === "cancelled" ||
    status === "interrupted";
}

export interface WatchAgentRunOptions {
  workspaceId: string;
  initial: AgentDraftProgress;
  onProgress: (progress: AgentDraftProgress) => void;
  onError?: (error: Error) => void;
  pollingIntervalMs?: number;
}

function parseAgentEventBlock(block: string): AgentEvent | null {
  const data = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!data) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(data);
  } catch {
    throw new Error("Agent run sent an invalid event payload");
  }
  if (!isAgentEvent(parsed)) {
    throw new Error("Agent run sent an invalid event contract");
  }
  return parsed;
}

/** Watches one durable run with cursor-based SSE replay and polling fallback. */
export function watchAgentRun({
  workspaceId,
  initial,
  onProgress,
  onError,
  pollingIntervalMs = 1_000,
}: WatchAgentRunOptions): () => void {
  let current = initial;
  let pollTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;
  let streaming = false;
  let consecutiveStreamFailures = 0;
  const requestController = new AbortController();

  const emit = (next: AgentDraftProgress) => {
    if (closed || next === current) return;
    current = next;
    onProgress(next);
  };

  const refresh = async () => {
    if (closed || current.runId === null) return;
    try {
      const detail = await getAgentRun(
        workspaceId,
        current.runId,
        requestController.signal,
      );
      emit(agentDraftProgressFromRunDetail(current, detail));
      if (agentRunIsTerminal(detail.run.status)) {
        return;
      }
    } catch (error) {
      if (!requestController.signal.aborted) {
        onError?.(
          error instanceof Error ? error : new Error("Could not refresh agent run"),
        );
      }
    }
    if (!closed && !streaming) {
      pollTimer = setTimeout(() => void refresh(), pollingIntervalMs);
    }
  };

  const startPolling = () => {
    streaming = false;
    if (reconnectTimer !== null) clearTimeout(reconnectTimer);
    reconnectTimer = null;
    if (pollTimer === null) void refresh();
  };

  const stream = async () => {
    if (closed || current.runId === null) return;
    streaming = true;
    const cursor = current.lastEventSequence;
    const path =
      `/v1/workspaces/${encodeURIComponent(workspaceId)}/agent-authoring/runs/${encodeURIComponent(current.runId)}/events?after_sequence=${cursor}`;
    try {
      const response = await fetch(`${API_BASE}${path}`, {
        method: "GET",
        headers: {
          Accept: "text/event-stream",
          "Last-Event-ID": String(cursor),
        },
        credentials: "same-origin",
        signal: requestController.signal,
      });
      if (!response.ok) {
        throw new ApiError(
          response.status,
          `${response.status} ${response.statusText}`,
        );
      }
      if (!response.body) {
        throw new Error("Agent run event stream has no response body");
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (!closed) {
        const result = await reader.read();
        buffer += decoder.decode(result.value, { stream: !result.done });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() ?? "";
        for (const block of blocks) {
          const event = parseAgentEventBlock(block);
          if (!event) continue;
          consecutiveStreamFailures = 0;
          emit(agentDraftProgressFromEvent(current, event));
          if (event.kind === "capabilities_requested") void refresh();
          if (agentRunIsTerminal(event.run_status)) return;
        }
        if (result.done) break;
      }
      if (buffer.trim()) {
        const event = parseAgentEventBlock(buffer);
        if (event) emit(agentDraftProgressFromEvent(current, event));
      }
      if (!closed) {
        streaming = false;
        reconnectTimer = setTimeout(() => void stream(), pollingIntervalMs);
      }
    } catch (error) {
      if (requestController.signal.aborted) return;
      streaming = false;
      consecutiveStreamFailures += 1;
      onError?.(
        error instanceof Error ? error : new Error("Could not watch agent run"),
      );
      if (consecutiveStreamFailures >= 2) {
        startPolling();
      } else {
        reconnectTimer = setTimeout(() => void stream(), pollingIntervalMs);
      }
    }
  };

  if (initial.runId !== null) void stream();

  return () => {
    closed = true;
    if (pollTimer !== null) clearTimeout(pollTimer);
    if (reconnectTimer !== null) clearTimeout(reconnectTimer);
    requestController.abort();
  };
}
