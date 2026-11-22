import type { CollaborativeHead } from "@/lib/api";
import type { EffectReducer, ExecEffect } from "@/lib/state";

import type { GraphPresentation } from "../artifacts/artifact-viewer";
import type {
  AuthoredGraphDocument,
  GraphCommand,
} from "../authoring/graph-document";
import type {
  ProjectRoomStatus,
  ProjectRoomTerminalReason,
} from "./graph-room-session";
import type { ProjectCommandAcceptedMessage } from "./protocol";
import {
  defaultGraphId,
  toLocalGraphCommand,
  type RoomProjectCommand,
} from "./room-command-bridge";

/** Delay before a failed collaborative-head fetch is tried again. */
export const HEAD_REFRESH_RETRY_DELAY_MS = 1000;

export const GRAPH_SWITCH_BLOCKED_MESSAGE =
  "Finish or wait for the current run and sync before switching Graphs.";

const COLLABORATIVE_EDIT_REJECTED = "A collaborative edit was rejected.";

export interface CallTrailEntry {
  readonly graphId: string;
  readonly nodeId: string;
  readonly name: string;
}

export type HeadRefreshPhase =
  | { readonly kind: "idle" }
  | {
      readonly kind: "fetching";
      readonly requestId: number;
      readonly errorMessage: string | null;
    }
  | {
      readonly kind: "retryScheduled";
      readonly retryId: number;
      readonly errorMessage: string | null;
    };

export interface WorkbenchSyncState {
  readonly projectId: string | null;
  readonly openGraphId: string | null;
  readonly unsyncedRoomEdits: boolean;
  readonly roomCommandsPending: boolean;
  readonly replayingCanvasProjectId: string | null;
  readonly headRefreshPhase: HeadRefreshPhase;
  readonly nextRefreshToken: number;
  readonly callTrail: readonly CallTrailEntry[];
}

export type WorkbenchSyncAction =
  | { readonly kind: "setProject"; readonly projectId: string | null }
  | { readonly kind: "syncOpenGraphId"; readonly graphId: string | null }
  | { readonly kind: "roomReady"; readonly head: CollaborativeHead }
  | { readonly kind: "roomRehydrate"; readonly head: CollaborativeHead }
  | {
      readonly kind: "roomPendingCommandsChanged";
      readonly pending: boolean;
      readonly roomStatus: ProjectRoomStatus;
      readonly head: CollaborativeHead | null;
    }
  | {
      readonly kind: "roomCommandAccepted";
      readonly commands: readonly ProjectCommandAcceptedMessage["commands"][number][];
      readonly local: boolean;
      readonly head: CollaborativeHead;
    }
  | {
      readonly kind: "roomCommandRejected";
      readonly errorCode: string | null | undefined;
      readonly detail: string | null | undefined;
    }
  | {
      readonly kind: "roomSubmitFailed";
      readonly errorCode: string | null;
      readonly message: string | null;
      readonly fallback: string;
    }
  | {
      readonly kind: "roomTerminalClosed";
      readonly reason: ProjectRoomTerminalReason;
      readonly workspaceSlug: string;
    }
  | {
      readonly kind: "requestHeadRefresh";
      readonly errorMessage?: string | null;
    }
  | {
      readonly kind: "headRefreshSucceeded";
      readonly requestId: number;
      readonly head: CollaborativeHead;
    }
  | {
      readonly kind: "headRefreshFailed";
      readonly requestId: number;
      readonly message: string;
    }
  | { readonly kind: "headRefreshRetryFired"; readonly retryId: number }
  | {
      readonly kind: "switchGraph";
      readonly targetGraphId: string;
      readonly nextTrail: readonly CallTrailEntry[];
      readonly head: CollaborativeHead | null;
      readonly isExecutionRunning: boolean;
      readonly isDirty: boolean;
    }
  | {
      readonly kind: "openCall";
      readonly nodeId: string;
      readonly calleeGraphId: string;
      readonly head: CollaborativeHead | null;
      readonly isExecutionRunning: boolean;
      readonly isDirty: boolean;
    }
  | {
      readonly kind: "backFromCall";
      readonly head: CollaborativeHead | null;
      readonly isExecutionRunning: boolean;
      readonly isDirty: boolean;
    };

export type WorkbenchSyncEffect =
  | { readonly kind: "syncCanvasFromHead"; readonly head: CollaborativeHead }
  | {
      readonly kind: "replaceRoomHeadAndSyncCanvas";
      readonly head: CollaborativeHead;
    }
  | {
      readonly kind: "applyRemoteCommandBatch";
      readonly commands: readonly ProjectCommandAcceptedMessage["commands"][number][];
      readonly openGraphId: string | null;
      readonly head: CollaborativeHead;
    }
  | {
      readonly kind: "fetchCollaborativeHead";
      readonly projectId: string;
      readonly requestId: number;
      readonly errorMessage: string | null;
    }
  | { readonly kind: "abortHeadRefresh" }
  | {
      readonly kind: "scheduleHeadRefreshRetry";
      readonly retryId: number;
      readonly delayMs: number;
      readonly errorMessage: string | null;
    }
  | { readonly kind: "cancelHeadRefreshRetry" }
  | { readonly kind: "reportError"; readonly message: string }
  | { readonly kind: "purgeLocalGraphState" }
  | { readonly kind: "navigateToWorkspace"; readonly workspaceSlug: string }
  | {
      readonly kind: "openGraphInProject";
      readonly head: CollaborativeHead;
      readonly graphId: string;
    };

export type RemoteBatchStep =
  | {
      readonly kind: "replacePresentation";
      readonly presentation: GraphPresentation;
    }
  | {
      readonly kind: "moveArtifactViewers";
      readonly positions: readonly {
        readonly viewer_id: string;
        readonly x: number;
        readonly y: number;
      }[];
    }
  | {
      readonly kind: "moveAnnotations";
      readonly positions: readonly {
        readonly annotation_id: string;
        readonly x: number;
        readonly y: number;
      }[];
    }
  | {
      readonly kind: "localGraphCommands";
      readonly commands: readonly GraphCommand[];
    };

export type RemoteCommandPlan =
  | { readonly kind: "needsHeadRefresh" }
  | { readonly kind: "apply"; readonly steps: readonly RemoteBatchStep[] };

type AcceptedCommand = ProjectCommandAcceptedMessage["commands"][number];

const UNSYNCED_SUBMIT_ERRORS = new Set([
  "queue_full",
  "not_ready",
  "send_failed",
  "reconnect_exhausted",
]);

export function initialWorkbenchSyncState(
  projectId: string | null,
): WorkbenchSyncState {
  return {
    projectId,
    openGraphId: null,
    unsyncedRoomEdits: false,
    roomCommandsPending: false,
    replayingCanvasProjectId: null,
    headRefreshPhase: { kind: "idle" },
    nextRefreshToken: 0,
    callTrail: [],
  };
}

/**
 * The Graph the canvas keeps when a head arrives: the one it already shows
 * when that Graph is still in the Project, otherwise the Project's first.
 */
export function nextOpenGraphId(
  head: CollaborativeHead,
  currentOpenGraphId: string | null,
): string | null {
  if (currentOpenGraphId === null) return defaultGraphId(head);
  const stillPresent = head.document.graphs.some(
    (graph) => graph.id === currentOpenGraphId,
  );
  if (stillPresent) return currentOpenGraphId;
  return defaultGraphId(head);
}

/**
 * Turn an accepted remote batch into canvas steps.
 *
 * A command this canvas cannot apply locally asks for a head refresh and
 * drops the rest of the batch: the snapshot is the reconciliation. Commands
 * for another Graph, and Project commands the live head already reflects,
 * are skipped.
 */
export function planRemoteCommandBatch(
  commands: readonly AcceptedCommand[],
  openGraphId: string | null,
  currentDocument: AuthoredGraphDocument,
): RemoteCommandPlan {
  const steps: RemoteBatchStep[] = [];
  const localCommands: GraphCommand[] = [];

  for (const entry of commands) {
    if (entry.kind === "in_graph" && entry.graph_id !== openGraphId) continue;
    if (
      entry.kind === "rename_project" ||
      entry.kind === "add_graph" ||
      entry.kind === "remove_graph" ||
      entry.kind === "refresh_node"
    ) {
      continue;
    }
    if (entry.kind === "rename_graph") {
      if (entry.graph_id !== openGraphId) continue;
      localCommands.push({ kind: "rename_graph", name: entry.name });
      continue;
    }
    if (entry.kind !== "in_graph") return { kind: "needsHeadRefresh" };

    const planned = planInGraphCommand(entry, openGraphId, currentDocument);
    if (planned === "refresh") return { kind: "needsHeadRefresh" };
    for (const step of planned.steps) steps.push(step);
    for (const command of planned.localCommands) localCommands.push(command);
  }

  if (localCommands.length > 0) {
    steps.push({ kind: "localGraphCommands", commands: localCommands });
  }
  return { kind: "apply", steps };
}

/**
 * The name of a Graph added to this Project. The first Graph keeps the
 * document name. Later Graphs take the next free "Graph N".
 */
export function nextNewGraphName(
  graphs: readonly { readonly name: string }[],
  currentDocumentName: string,
): string {
  if (graphs.length === 0) {
    const trimmed = currentDocumentName.trim();
    if (trimmed.length > 0) return trimmed;
    return "Untitled workflow";
  }
  const taken = new Set<string>();
  for (const graph of graphs) taken.add(graph.name.toLowerCase());
  let suffix = graphs.length + 1;
  while (taken.has(`graph ${suffix}`)) suffix += 1;
  return `Graph ${suffix}`;
}

export const workbenchSyncReducer: EffectReducer<
  WorkbenchSyncState,
  WorkbenchSyncAction,
  WorkbenchSyncEffect
> = (state, action, exec) => {
  switch (action.kind) {
    case "setProject":
      return applySetProject(state, action.projectId, exec);
    case "syncOpenGraphId":
      if (state.openGraphId === action.graphId) return state;
      return { ...state, openGraphId: action.graphId };
    case "roomReady":
    case "roomRehydrate":
      return recoverRoomCanvas(state, action.head, exec);
    case "roomPendingCommandsChanged":
      return applyPendingCommands(state, action, exec);
    case "roomCommandAccepted":
      return applyCommandAccepted(state, action, exec);
    case "roomCommandRejected":
      return applyCommandRejected(state, action, exec);
    case "roomSubmitFailed":
      return applySubmitFailed(state, action, exec);
    case "roomTerminalClosed":
      return applyTerminalClosed(state, action, exec);
    case "requestHeadRefresh":
      return beginHeadRefresh(state, action.errorMessage ?? null, exec);
    case "headRefreshSucceeded":
      return applyHeadRefreshSucceeded(state, action, exec);
    case "headRefreshFailed":
      return applyHeadRefreshFailed(state, action, exec);
    case "headRefreshRetryFired":
      return applyHeadRefreshRetryFired(state, action, exec);
    case "switchGraph":
      return applyGraphSwitch(state, action, exec);
    case "openCall":
      return applyOpenCall(state, action, exec);
    case "backFromCall":
      return applyBackFromCall(state, action, exec);
    default: {
      const unexpected: never = action;
      return unexpected;
    }
  }
};

function applySetProject(
  state: WorkbenchSyncState,
  projectId: string | null,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  if (state.projectId === projectId) return state;
  stopHeadRefresh(state, exec);
  return {
    ...state,
    projectId,
    openGraphId: null,
    unsyncedRoomEdits: false,
    roomCommandsPending: false,
    replayingCanvasProjectId: null,
    headRefreshPhase: { kind: "idle" },
    callTrail: [],
  };
}

function recoverRoomCanvas(
  state: WorkbenchSyncState,
  head: CollaborativeHead,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  exec({ kind: "syncCanvasFromHead", head });
  return {
    ...state,
    replayingCanvasProjectId: state.roomCommandsPending
      ? head.project_id
      : null,
    openGraphId: nextOpenGraphId(head, state.openGraphId),
    unsyncedRoomEdits: false,
  };
}

function applyPendingCommands(
  state: WorkbenchSyncState,
  action: Extract<WorkbenchSyncAction, { kind: "roomPendingCommandsChanged" }>,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  const replay =
    !action.pending &&
    action.roomStatus === "ready" &&
    action.head !== null &&
    state.replayingCanvasProjectId === action.head.project_id;
  if (state.roomCommandsPending === action.pending && !replay) return state;

  const withPending = { ...state, roomCommandsPending: action.pending };
  if (!replay || action.head === null) return withPending;

  exec({ kind: "syncCanvasFromHead", head: action.head });
  return {
    ...withPending,
    replayingCanvasProjectId: null,
    unsyncedRoomEdits: false,
    openGraphId: nextOpenGraphId(action.head, state.openGraphId),
  };
}

function applyCommandAccepted(
  state: WorkbenchSyncState,
  action: Extract<WorkbenchSyncAction, { kind: "roomCommandAccepted" }>,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  if (
    changesGraphSet(action.commands) &&
    !action.head.document.graphs.some((graph) => graph.id === state.openGraphId)
  ) {
    exec({ kind: "syncCanvasFromHead", head: action.head });
    return {
      ...state,
      openGraphId: nextOpenGraphId(action.head, state.openGraphId),
      unsyncedRoomEdits: false,
      callTrail: [],
    };
  }
  if (action.local) return state;
  exec({
    kind: "applyRemoteCommandBatch",
    commands: action.commands,
    openGraphId: state.openGraphId,
    head: action.head,
  });
  return state;
}

function applyCommandRejected(
  state: WorkbenchSyncState,
  action: Extract<WorkbenchSyncAction, { kind: "roomCommandRejected" }>,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  const isHeadConflict = action.errorCode === "head_conflict";
  const detail = action.detail || COLLABORATIVE_EDIT_REJECTED;
  if (!isHeadConflict) exec({ kind: "reportError", message: detail });
  return beginHeadRefresh(state, isHeadConflict ? null : detail, exec);
}

function applySubmitFailed(
  state: WorkbenchSyncState,
  action: Extract<WorkbenchSyncAction, { kind: "roomSubmitFailed" }>,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  let next = state;
  if (
    action.errorCode !== null &&
    UNSYNCED_SUBMIT_ERRORS.has(action.errorCode)
  ) {
    next = { ...next, unsyncedRoomEdits: true };
  }
  if (action.errorCode === "queue_full") {
    next = beginHeadRefresh(next, null, exec);
  }
  if (
    action.errorCode !== "superseded" &&
    action.errorCode !== "head_conflict"
  ) {
    exec({ kind: "reportError", message: action.message ?? action.fallback });
  }
  return next;
}

function applyTerminalClosed(
  state: WorkbenchSyncState,
  action: Extract<WorkbenchSyncAction, { kind: "roomTerminalClosed" }>,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  if (
    action.reason !== "access_revoked" &&
    action.reason !== "project_deleted"
  ) {
    return state;
  }
  stopHeadRefresh(state, exec);
  exec({ kind: "purgeLocalGraphState" });
  exec({ kind: "navigateToWorkspace", workspaceSlug: action.workspaceSlug });
  if (state.headRefreshPhase.kind === "idle") return state;
  return { ...state, headRefreshPhase: { kind: "idle" } };
}

function applyHeadRefreshSucceeded(
  state: WorkbenchSyncState,
  action: Extract<WorkbenchSyncAction, { kind: "headRefreshSucceeded" }>,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  if (!isActiveFetch(state, action.requestId)) return state;
  exec({ kind: "cancelHeadRefreshRetry" });
  exec({ kind: "replaceRoomHeadAndSyncCanvas", head: action.head });
  return {
    ...state,
    headRefreshPhase: { kind: "idle" },
    replayingCanvasProjectId: state.roomCommandsPending
      ? action.head.project_id
      : null,
    openGraphId: nextOpenGraphId(action.head, state.openGraphId),
    unsyncedRoomEdits: false,
  };
}

function applyHeadRefreshFailed(
  state: WorkbenchSyncState,
  action: Extract<WorkbenchSyncAction, { kind: "headRefreshFailed" }>,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  if (!isActiveFetch(state, action.requestId)) return state;
  const phase = state.headRefreshPhase;
  const message =
    phase.kind === "fetching" && phase.errorMessage !== null
      ? phase.errorMessage
      : action.message;
  exec({ kind: "reportError", message });
  const retryId = state.nextRefreshToken + 1;
  exec({
    kind: "scheduleHeadRefreshRetry",
    retryId,
    delayMs: HEAD_REFRESH_RETRY_DELAY_MS,
    errorMessage: message,
  });
  return {
    ...state,
    nextRefreshToken: retryId,
    headRefreshPhase: {
      kind: "retryScheduled",
      retryId,
      errorMessage: message,
    },
  };
}

function applyHeadRefreshRetryFired(
  state: WorkbenchSyncState,
  action: Extract<WorkbenchSyncAction, { kind: "headRefreshRetryFired" }>,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  if (
    state.headRefreshPhase.kind !== "retryScheduled" ||
    state.headRefreshPhase.retryId !== action.retryId ||
    state.projectId === null
  ) {
    return state;
  }
  const requestId = state.nextRefreshToken + 1;
  const errorMessage = state.headRefreshPhase.errorMessage;
  exec({
    kind: "fetchCollaborativeHead",
    projectId: state.projectId,
    requestId,
    errorMessage,
  });
  return {
    ...state,
    nextRefreshToken: requestId,
    headRefreshPhase: { kind: "fetching", requestId, errorMessage },
  };
}

function applyOpenCall(
  state: WorkbenchSyncState,
  action: Extract<WorkbenchSyncAction, { kind: "openCall" }>,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  const callerId = state.openGraphId;
  if (callerId === null || action.head === null) return state;
  const caller = action.head.document.graphs.find(
    (graph) => graph.id === callerId,
  );
  if (!caller) return state;
  return applyGraphSwitch(
    state,
    {
      kind: "switchGraph",
      targetGraphId: action.calleeGraphId,
      nextTrail: [
        ...state.callTrail,
        { graphId: callerId, nodeId: action.nodeId, name: caller.name },
      ],
      head: action.head,
      isExecutionRunning: action.isExecutionRunning,
      isDirty: action.isDirty,
    },
    exec,
  );
}

function applyBackFromCall(
  state: WorkbenchSyncState,
  action: Extract<WorkbenchSyncAction, { kind: "backFromCall" }>,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  const last = state.callTrail[state.callTrail.length - 1];
  if (!last) return state;
  return applyGraphSwitch(
    state,
    {
      kind: "switchGraph",
      targetGraphId: last.graphId,
      nextTrail: state.callTrail.slice(0, -1),
      head: action.head,
      isExecutionRunning: action.isExecutionRunning,
      isDirty: action.isDirty,
    },
    exec,
  );
}

function applyGraphSwitch(
  state: WorkbenchSyncState,
  action: Extract<WorkbenchSyncAction, { kind: "switchGraph" }>,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  if (action.head === null || action.targetGraphId === state.openGraphId) {
    return state;
  }
  if (action.isExecutionRunning || action.isDirty) {
    exec({ kind: "reportError", message: GRAPH_SWITCH_BLOCKED_MESSAGE });
    return state;
  }
  exec({
    kind: "openGraphInProject",
    head: action.head,
    graphId: action.targetGraphId,
  });
  return {
    ...state,
    openGraphId: action.targetGraphId,
    callTrail: action.nextTrail,
  };
}

function beginHeadRefresh(
  state: WorkbenchSyncState,
  errorMessage: string | null,
  exec: ExecEffect<WorkbenchSyncEffect>,
): WorkbenchSyncState {
  if (state.projectId === null) return state;
  exec({ kind: "abortHeadRefresh" });
  const requestId = state.nextRefreshToken + 1;
  exec({
    kind: "fetchCollaborativeHead",
    projectId: state.projectId,
    requestId,
    errorMessage,
  });
  return {
    ...state,
    nextRefreshToken: requestId,
    headRefreshPhase: { kind: "fetching", requestId, errorMessage },
  };
}

function stopHeadRefresh(
  state: WorkbenchSyncState,
  exec: ExecEffect<WorkbenchSyncEffect>,
): void {
  if (state.headRefreshPhase.kind === "idle") return;
  exec({ kind: "abortHeadRefresh" });
  exec({ kind: "cancelHeadRefreshRetry" });
}

function isActiveFetch(state: WorkbenchSyncState, requestId: number): boolean {
  return (
    state.headRefreshPhase.kind === "fetching" &&
    state.headRefreshPhase.requestId === requestId
  );
}

function changesGraphSet(commands: readonly AcceptedCommand[]): boolean {
  for (const command of commands) {
    if (command.kind === "add_graph" || command.kind === "remove_graph") {
      return true;
    }
  }
  return false;
}

function planInGraphCommand(
  entry: Extract<RoomProjectCommand, { kind: "in_graph" }>,
  openGraphId: string | null,
  currentDocument: AuthoredGraphDocument,
):
  | {
      steps: readonly RemoteBatchStep[];
      localCommands: readonly GraphCommand[];
    }
  | "refresh" {
  const body = entry.command;
  if (body.kind === "replace_presentation") {
    return {
      steps: [{ kind: "replacePresentation", presentation: body.presentation }],
      localCommands: [],
    };
  }
  if (body.kind === "move_artifact_viewers") {
    return {
      steps: [
        {
          kind: "moveArtifactViewers",
          positions: body.positions.map((position) => ({
            viewer_id: position.viewer_id,
            x: position.x,
            y: position.y,
          })),
        },
      ],
      localCommands: [],
    };
  }
  if (body.kind === "move_annotations") {
    return {
      steps: [
        {
          kind: "moveAnnotations",
          positions: body.positions.map((position) => ({
            annotation_id: position.annotation_id,
            x: position.x,
            y: position.y,
          })),
        },
      ],
      localCommands: [],
    };
  }

  const steps: RemoteBatchStep[] = [];
  if (
    body.kind === "replace_document" &&
    body.document.presentation &&
    openGraphId !== null
  ) {
    steps.push({
      kind: "replacePresentation",
      presentation: body.document.presentation,
    });
  }
  const localCommand = toLocalGraphCommand(
    entry,
    currentDocument,
    openGraphId ?? undefined,
  );
  if (!localCommand) return "refresh";
  return { steps, localCommands: [localCommand] };
}
