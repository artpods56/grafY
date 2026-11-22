"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import {
  getCollaborativeHead,
  type CollaborativeHead,
  type GraphDefinition,
  type NodeRegistry,
} from "@/lib/api";
import { useEffectReducer } from "@/lib/state";

import {
  presentationFromArtifactViewers,
  type ArtifactViewerCanvasState,
  type GraphPresentation,
} from "../artifacts/artifact-viewer";
import {
  applyGraphCommandNormalized,
  type AuthoredGraphDocument,
  type GraphCommand,
} from "../authoring/graph-document";
import { callableGraphs, graphInterface } from "../authoring/project-graphs";
import { createUuid } from "../authoring/uuid";
import type { WorkbenchRoomCommandSync } from "../authoring/workbench-authoring-commands";
import type { WorkflowNode } from "../execution/execution-plan";
import {
  PRESENCE_CLIENT_MIN_INTERVAL_MS,
  ProjectRoomCommandError,
  type ProjectRoomStatus,
} from "./graph-room-session";
import { graphReadiness } from "./graph-readiness";
import type { TransientNodePosition } from "./protocol";
import {
  toRoomGraphCommand,
  toRoomRenameGraphCommand,
  type RoomGraphBodyCommand,
  type RoomProjectCommand,
} from "./room-command-bridge";
import { useGraphAutosave } from "./useGraphAutosave";
import { useProjectRoomSession } from "./useProjectRoomSession";
import {
  useSavedGraphLifecycle,
  type ActiveSavedGraph,
} from "./useSavedGraphLifecycle";
import {
  initialWorkbenchSyncState,
  nextNewGraphName,
  nextOpenGraphId,
  planRemoteCommandBatch,
  workbenchSyncReducer,
  type WorkbenchSyncAction,
  type WorkbenchSyncEffect,
} from "./workbench-sync-reducer";

const NO_GRAPHS: readonly GraphDefinition[] = [];
const HEAD_REFRESH_ERROR = "The Project head could not be refreshed.";

export interface PresentationRoomSync {
  submitReplace: (state: ArtifactViewerCanvasState) => void;
  submitMove: (
    positions: readonly { viewer_id: string; x: number; y: number }[],
  ) => void;
  submitMoveAnnotations: (
    positions: readonly { annotation_id: string; x: number; y: number }[],
  ) => void;
}

export interface CanvasCardDrag {
  readonly cardId: string;
  readonly col: number;
  readonly row: number;
}

export interface UseWorkbenchSyncReducerOptions {
  readonly workspaceId: string;
  readonly workspaceSlug: string;
  readonly projectId: string | null;
  readonly registry: NodeRegistry | undefined;
  readonly document: AuthoredGraphDocument;
  readonly presentation?: GraphPresentation;
  readonly isExecutionRunning: () => boolean;
  readonly replaceDocument: (
    document: AuthoredGraphDocument,
    overlayNodes?: readonly WorkflowNode[],
  ) => void;
  readonly replacePresentation: (presentation: GraphPresentation) => void;
  readonly updateDocumentName: (name: string) => void;
  readonly refreshNodeSecretStatuses: (
    graph: ActiveSavedGraph,
    nodes: readonly WorkflowNode[],
    signal?: AbortSignal,
  ) => Promise<boolean>;
  readonly clearGraphSecretStatuses: () => void;
  readonly clearPendingConnectionRoute: () => void;
  readonly clearRunError: () => void;
  readonly closeNodeLibrary: () => void;
  readonly requestCanvasRefit: () => void;
  readonly refreshNodeRegistry: () => void | Promise<unknown>;
  readonly applyAuthoringCommands: (
    commands: readonly GraphCommand[],
    options?: { readonly syncRoom?: boolean },
  ) => void;
  readonly setArtifactViewers: React.Dispatch<
    React.SetStateAction<ArtifactViewerCanvasState>
  >;
  readonly authoredDocumentRef: React.RefObject<AuthoredGraphDocument>;
  readonly setRunError: (message: string | null) => void;
  /**
   * True while a Run is in progress. Autosave and the authoring gate read it
   * on this render, so pass the flag from the same render when it is already
   * known.
   */
  readonly executionRunning: boolean;
  readonly canEditProject: boolean;
  readonly canCreateProject: boolean;
  readonly canvasReady: boolean;
  readonly selectedNodeIds: readonly string[];
  readonly screenToCanvasPoint: (point: {
    readonly x: number;
    readonly y: number;
  }) => { x: number; y: number } | null | undefined;
  readonly cellToWorldOrigin: (
    col: number,
    row: number,
  ) => { readonly x: number; readonly y: number };
  readonly roomCommandSyncRef: React.RefObject<WorkbenchRoomCommandSync>;
  readonly presentationRoomSyncRef: React.RefObject<PresentationRoomSync>;
}

interface RoomView {
  readonly pending: boolean;
  readonly status: ProjectRoomStatus;
  readonly head: CollaborativeHead | null;
}

function submitFailureAction(
  error: unknown,
  fallback: string,
): Extract<WorkbenchSyncAction, { kind: "roomSubmitFailed" }> {
  if (error instanceof ProjectRoomCommandError) {
    return {
      kind: "roomSubmitFailed",
      errorCode: error.errorCode,
      message: error.message,
      fallback,
    };
  }
  return {
    kind: "roomSubmitFailed",
    errorCode: null,
    message: error instanceof Error ? error.message : null,
    fallback,
  };
}

function refreshFailureMessage(
  error: unknown,
  errorMessage: string | null,
): string {
  if (errorMessage !== null) return errorMessage;
  if (error instanceof Error && error.message.length > 0) return error.message;
  return HEAD_REFRESH_ERROR;
}

interface SyncEffectHost {
  readonly workspaceId: string;
  readonly router: { replace: (href: string) => void };
  readonly setRunError: (message: string | null) => void;
  readonly replacePresentation: (presentation: GraphPresentation) => void;
  readonly setArtifactViewers: React.Dispatch<
    React.SetStateAction<ArtifactViewerCanvasState>
  >;
  readonly applyAuthoringCommands: (
    commands: readonly GraphCommand[],
    options?: { readonly syncRoom?: boolean },
  ) => void;
  readonly authoredDocumentRef: React.RefObject<AuthoredGraphDocument>;
  readonly headRefreshControllerRef: React.RefObject<AbortController | null>;
  readonly headRefreshRetryRef: React.RefObject<number | null>;
  readonly clearHeadRefreshRetry: () => void;
  readonly replaceHeadRef: React.RefObject<
    (head: CollaborativeHead) => CollaborativeHead
  >;
  readonly syncFromCollaborativeHeadRef: React.RefObject<
    (head: CollaborativeHead) => void
  >;
  readonly purgeLocalGraphStateRef: React.RefObject<() => void>;
  readonly openGraphInProjectRef: React.RefObject<
    (head: CollaborativeHead, graphId: string) => void
  >;
  readonly openGraphIdRef: React.RefObject<string | null>;
}

function runWorkbenchSyncEffect(
  effect: WorkbenchSyncEffect,
  effectDispatch: React.Dispatch<WorkbenchSyncAction>,
  host: SyncEffectHost,
): void {
  switch (effect.kind) {
    case "syncCanvasFromHead":
      host.openGraphIdRef.current = nextOpenGraphId(
        effect.head,
        host.openGraphIdRef.current,
      );
      host.syncFromCollaborativeHeadRef.current(effect.head);
      return;
    case "replaceRoomHeadAndSyncCanvas": {
      let nextHead = effect.head;
      try {
        nextHead = host.replaceHeadRef.current(effect.head);
      } catch {
        nextHead = effect.head;
      }
      host.openGraphIdRef.current = nextOpenGraphId(
        nextHead,
        host.openGraphIdRef.current,
      );
      host.syncFromCollaborativeHeadRef.current(nextHead);
      if (
        nextHead.room_epoch !== effect.head.room_epoch ||
        nextHead.collaboration_sequence !== effect.head.collaboration_sequence
      ) {
        effectDispatch({ kind: "roomRehydrate", head: nextHead });
      }
      return;
    }
    case "applyRemoteCommandBatch":
      applyRemoteBatch(effect, effectDispatch, host);
      return;
    case "fetchCollaborativeHead":
      fetchHead(effect, effectDispatch, host);
      return;
    case "abortHeadRefresh":
      host.headRefreshControllerRef.current?.abort();
      host.headRefreshControllerRef.current = null;
      host.clearHeadRefreshRetry();
      return;
    case "scheduleHeadRefreshRetry":
      host.clearHeadRefreshRetry();
      host.headRefreshRetryRef.current = window.setTimeout(() => {
        host.headRefreshRetryRef.current = null;
        effectDispatch({
          kind: "headRefreshRetryFired",
          retryId: effect.retryId,
        });
      }, effect.delayMs);
      return;
    case "cancelHeadRefreshRetry":
      host.clearHeadRefreshRetry();
      return;
    case "reportError":
      host.setRunError(effect.message);
      return;
    case "purgeLocalGraphState":
      host.purgeLocalGraphStateRef.current();
      return;
    case "navigateToWorkspace":
      host.router.replace(
        `/workspaces/${encodeURIComponent(effect.workspaceSlug)}`,
      );
      return;
    case "openGraphInProject":
      host.openGraphIdRef.current = effect.graphId;
      host.openGraphInProjectRef.current(effect.head, effect.graphId);
      return;
    default: {
      const unexpected: never = effect;
      return unexpected;
    }
  }
}

function fetchHead(
  effect: Extract<WorkbenchSyncEffect, { kind: "fetchCollaborativeHead" }>,
  effectDispatch: React.Dispatch<WorkbenchSyncAction>,
  host: SyncEffectHost,
): void {
  host.headRefreshControllerRef.current?.abort();
  const request = new AbortController();
  host.headRefreshControllerRef.current = request;
  void getCollaborativeHead(host.workspaceId, effect.projectId, request.signal)
    .then((nextHead) => {
      if (request.signal.aborted) return;
      effectDispatch({
        kind: "headRefreshSucceeded",
        requestId: effect.requestId,
        head: nextHead,
      });
    })
    .catch((error: unknown) => {
      if (request.signal.aborted) return;
      effectDispatch({
        kind: "headRefreshFailed",
        requestId: effect.requestId,
        message: refreshFailureMessage(error, effect.errorMessage),
      });
    });
}

function applyRemoteBatch(
  effect: Extract<WorkbenchSyncEffect, { kind: "applyRemoteCommandBatch" }>,
  effectDispatch: React.Dispatch<WorkbenchSyncAction>,
  host: SyncEffectHost,
): void {
  const plan = planRemoteCommandBatch(
    effect.commands,
    effect.openGraphId,
    host.authoredDocumentRef.current,
  );
  if (plan.kind === "needsHeadRefresh") {
    effectDispatch({ kind: "requestHeadRefresh" });
    return;
  }
  for (const planned of plan.steps) {
    if (planned.kind === "replacePresentation") {
      host.replacePresentation(planned.presentation);
      continue;
    }
    if (planned.kind === "moveArtifactViewers") {
      const positions = new Map(
        planned.positions.map((position) => [
          position.viewer_id,
          { x: position.x, y: position.y },
        ]),
      );
      host.setArtifactViewers((current) => ({
        ...current,
        nodes: current.nodes.map((node) => {
          const position = positions.get(node.id);
          return position ? { ...node, position } : node;
        }),
      }));
      continue;
    }
    if (planned.kind === "moveAnnotations") {
      const positions = new Map(
        planned.positions.map((position) => [
          position.annotation_id,
          { x: position.x, y: position.y },
        ]),
      );
      host.setArtifactViewers((current) => ({
        ...current,
        annotations: current.annotations.map((annotation) => {
          const position = positions.get(annotation.id);
          return position ? { ...annotation, position } : annotation;
        }),
      }));
      continue;
    }
    host.applyAuthoringCommands(planned.commands, { syncRoom: false });
  }
}

/**
 * Project room, saved-Graph lifecycle, and the sync decisions around them.
 *
 * The reducer owns the phase of a head refresh, which Graph is open, and the
 * call stack. This hook runs the effects and keeps the room session, autosave,
 * and canvas presence beside that state.
 */
export function useWorkbenchSyncReducer({
  workspaceId,
  workspaceSlug,
  projectId,
  registry,
  document,
  presentation,
  isExecutionRunning,
  replaceDocument,
  replacePresentation,
  updateDocumentName,
  refreshNodeSecretStatuses,
  clearGraphSecretStatuses,
  clearPendingConnectionRoute,
  clearRunError,
  closeNodeLibrary,
  requestCanvasRefit,
  refreshNodeRegistry,
  applyAuthoringCommands,
  setArtifactViewers,
  authoredDocumentRef,
  setRunError,
  executionRunning,
  canEditProject,
  canCreateProject,
  canvasReady,
  selectedNodeIds,
  screenToCanvasPoint,
  cellToWorldOrigin,
  roomCommandSyncRef,
  presentationRoomSyncRef,
}: UseWorkbenchSyncReducerOptions) {
  const router = useRouter();
  const headRefreshControllerRef = React.useRef<AbortController | null>(null);
  const headRefreshRetryRef = React.useRef<number | null>(null);
  const replaceHeadRef = React.useRef<
    (head: CollaborativeHead) => CollaborativeHead
  >((nextHead) => nextHead);
  const syncFromCollaborativeHeadRef = React.useRef<
    (head: CollaborativeHead) => void
  >(() => undefined);
  const purgeLocalGraphStateRef = React.useRef<() => void>(() => undefined);
  const openGraphInProjectRef = React.useRef<
    (head: CollaborativeHead, graphId: string) => void
  >(() => undefined);
  const openGraphIdRef = React.useRef<string | null>(null);
  const selectedNodeIdsRef = React.useRef(selectedNodeIds);
  const applyAuthoringCommandsRef = React.useRef(applyAuthoringCommands);
  const presenceCursorRef = React.useRef<{ x: number; y: number } | null>(null);
  const presenceClientPointRef = React.useRef<{ x: number; y: number } | null>(
    null,
  );
  const presenceClientPointDirtyRef = React.useRef(false);
  const presenceOverCanvasRef = React.useRef(false);
  const presenceDragRef = React.useRef<{
    positions: TransientNodePosition[];
    targetIds: string[];
  } | null>(null);
  const presencePublishTimerRef = React.useRef<number | null>(null);
  const lastPresencePublishAtRef = React.useRef(0);

  const clearHeadRefreshRetry = React.useCallback(() => {
    if (headRefreshRetryRef.current === null) return;
    window.clearTimeout(headRefreshRetryRef.current);
    headRefreshRetryRef.current = null;
  }, []);

  const runEffect = React.useCallback(
    (
      effect: WorkbenchSyncEffect,
      effectDispatch: React.Dispatch<WorkbenchSyncAction>,
    ) => {
      runWorkbenchSyncEffect(effect, effectDispatch, {
        workspaceId,
        router,
        setRunError,
        replacePresentation,
        setArtifactViewers,
        applyAuthoringCommands,
        authoredDocumentRef,
        headRefreshControllerRef,
        headRefreshRetryRef,
        clearHeadRefreshRetry,
        replaceHeadRef,
        syncFromCollaborativeHeadRef,
        purgeLocalGraphStateRef,
        openGraphInProjectRef,
        openGraphIdRef,
      });
    },
    [
      applyAuthoringCommands,
      authoredDocumentRef,
      clearHeadRefreshRetry,
      replacePresentation,
      router,
      setArtifactViewers,
      setRunError,
      workspaceId,
    ],
  );
  const [state, dispatch] = useEffectReducer(
    workbenchSyncReducer,
    () => initialWorkbenchSyncState(projectId),
    runEffect,
  );
  if (state.projectId !== projectId) {
    dispatch({ kind: "setProject", projectId });
  }

  const projectRoom = useProjectRoomSession({
    workspaceId,
    projectId,
    onReady: (ready) => {
      dispatch({ kind: "roomReady", head: ready.head });
    },
    onRehydrate: (nextHead) => {
      dispatch({ kind: "roomRehydrate", head: nextHead });
    },
    onPendingCommandsChange: (pending) => {
      // The outbox can flip this flag in the same turn as room.ready, before
      // React has rendered the head. Record the flag now; replay waits until
      // the rendered head is known.
      dispatch({
        kind: "roomPendingCommandsChanged",
        pending,
        roomStatus: "idle",
        head: null,
      });
    },
    onHeadRefreshRequired: () => {
      dispatch({ kind: "requestHeadRefresh", errorMessage: null });
    },
    onCommandAccepted: (message, meta, nextHead) => {
      dispatch({
        kind: "roomCommandAccepted",
        commands: message.commands,
        local: meta.local,
        head: nextHead,
      });
    },
    onCommandRejected: (message) => {
      dispatch({
        kind: "roomCommandRejected",
        errorCode: message.error_code,
        detail: message.detail,
      });
    },
    onTerminalClose: (reason) => {
      dispatch({
        kind: "roomTerminalClosed",
        reason,
        workspaceSlug,
      });
    },
  });

  const roomView: RoomView = {
    pending: projectRoom.hasPendingCommands,
    status: projectRoom.status,
    head: projectRoom.head,
  };
  const [seenRoomView, setSeenRoomView] = React.useState(roomView);
  if (
    seenRoomView.pending !== roomView.pending ||
    seenRoomView.status !== roomView.status ||
    seenRoomView.head !== roomView.head
  ) {
    setSeenRoomView(roomView);
    dispatch({
      kind: "roomPendingCommandsChanged",
      pending: roomView.pending,
      roomStatus: roomView.status,
      head: roomView.head,
    });
  }

  const lifecycle = useSavedGraphLifecycle({
    workspaceId,
    workspaceSlug,
    initialGraphId: projectId,
    registry,
    document,
    presentation,
    isExecutionRunning,
    replaceDocument,
    replacePresentation,
    updateDocumentName,
    refreshNodeSecretStatuses,
    clearGraphSecretStatuses,
    clearPendingConnectionRoute,
    clearRunError,
    closeNodeLibrary,
    requestCanvasRefit,
    refreshNodeRegistry,
    roomHead:
      projectRoom.terminalReason === "access_revoked" ||
      projectRoom.terminalReason === "project_deleted"
        ? null
        : projectRoom.head,
    roomSessionId: projectRoom.localSessionId,
    hasPendingRoomCommands: projectRoom.hasPendingCommands,
    hasUnsyncedRoomEdits: state.unsyncedRoomEdits,
  });

  const openGraphId = React.useMemo(() => {
    const currentHead = projectRoom.head;
    if (!currentHead) return null;
    const remembered = lifecycle.openGraphId;
    if (
      remembered !== null &&
      currentHead.document.graphs.some((graph) => graph.id === remembered)
    ) {
      return remembered;
    }
    return nextOpenGraphId(currentHead, null);
  }, [lifecycle.openGraphId, projectRoom.head]);

  const projectGraphs = projectRoom.head?.document.graphs ?? NO_GRAPHS;
  const projectCatalogKey = React.useMemo(
    () =>
      JSON.stringify([
        openGraphId,
        projectGraphs.map((graph) => [
          graph.id,
          graph.name,
          graphInterface(graph),
        ]),
        openGraphId === null
          ? []
          : callableGraphs(projectGraphs, openGraphId).map((graph) => graph.id),
      ]),
    [openGraphId, projectGraphs],
  );
  const [projectCatalog, setProjectCatalog] = React.useState<{
    key: string;
    graphs: readonly GraphDefinition[];
    openGraphId: string | null;
  }>({ key: "", graphs: [], openGraphId: null });
  if (projectCatalog.key !== projectCatalogKey) {
    setProjectCatalog({
      key: projectCatalogKey,
      graphs: projectGraphs,
      openGraphId,
    });
  }

  const projectReadiness = graphReadiness(
    projectRoom.status,
    projectRoom.head !== null,
  );
  const projectEditsTrusted = projectId === null || projectReadiness.trusted;
  const graphOperationBusy =
    lifecycle.persistenceOperationBusy || executionRunning;
  const localAuthoringEnabled =
    !graphOperationBusy &&
    (projectId
      ? canEditProject && projectEditsTrusted && projectRoom.canSubmitCommands
      : canCreateProject && lifecycle.activeGraph === null);
  const localAuthoringBlockedMessage = !(projectId
    ? canEditProject
    : canCreateProject)
    ? "You do not have permission to edit this Project."
    : graphOperationBusy
      ? "Editing is paused while another Project operation is in progress."
      : "Editing is paused until the Project room is ready.";
  const projectHasNoGraph =
    projectRoom.head !== null && projectRoom.status === "ready" && !openGraphId;

  useGraphAutosave({
    enabled:
      projectId === null &&
      lifecycle.activeGraph === null &&
      localAuthoringEnabled,
    dirty: lifecycle.isDirty,
    fingerprint: lifecycle.currentFingerprint,
    save: lifecycle.saveCurrentGraph,
  });

  React.useLayoutEffect(() => {
    replaceHeadRef.current = projectRoom.replaceHead;
    syncFromCollaborativeHeadRef.current = lifecycle.syncFromCollaborativeHead;
    purgeLocalGraphStateRef.current = lifecycle.purgeLocalGraphState;
    openGraphInProjectRef.current = lifecycle.openGraphInProject;
    openGraphIdRef.current = openGraphId;
    selectedNodeIdsRef.current = selectedNodeIds;
    applyAuthoringCommandsRef.current = applyAuthoringCommands;
  }, [
    applyAuthoringCommands,
    lifecycle.openGraphInProject,
    lifecycle.purgeLocalGraphState,
    lifecycle.syncFromCollaborativeHead,
    openGraphId,
    projectRoom.replaceHead,
    selectedNodeIds,
  ]);

  React.useEffect(
    () => () => {
      headRefreshControllerRef.current?.abort();
      clearHeadRefreshRetry();
    },
    [clearHeadRefreshRetry],
  );

  const submitRoomBatch = projectRoom.submitCommands;
  const refreshSavedGraphs = lifecycle.refreshSavedGraphs;
  const isDirty = lifecycle.isDirty;
  const submitRoomCommands = React.useCallback(
    (commands: readonly RoomProjectCommand[], fallback: string) => {
      if (projectId === null) return;
      void submitRoomBatch(commands).catch((error: unknown) => {
        dispatch(submitFailureAction(error, fallback));
      });
    },
    [dispatch, projectId, submitRoomBatch],
  );
  const inOpenGraph = React.useCallback(
    (command: RoomGraphBodyCommand): RoomProjectCommand | null => {
      const graphId = openGraphIdRef.current;
      if (graphId === null) return null;
      return { kind: "in_graph", graph_id: graphId, command };
    },
    [],
  );
  const commitProjectBatch = React.useCallback(
    (
      commands: readonly RoomProjectCommand[],
      fallback: string,
      openAfter: string | null = null,
    ) => {
      void submitRoomBatch(commands)
        .then(({ head }) => {
          refreshSavedGraphs();
          if (openAfter !== null) {
            openGraphInProjectRef.current(head, openAfter);
            dispatch({ kind: "syncOpenGraphId", graphId: openAfter });
            return;
          }
          const rename = commands.find(
            (command) => command.kind === "rename_graph",
          );
          if (!rename || rename.graph_id !== openGraphIdRef.current) return;
          const graph = head.document.graphs.find(
            (candidate) => candidate.id === rename.graph_id,
          );
          if (!graph) return;
          applyAuthoringCommandsRef.current(
            [{ kind: "rename_graph", name: graph.name }],
            { syncRoom: false },
          );
        })
        .catch((error: unknown) => {
          setRunError(error instanceof Error ? error.message : fallback);
        });
    },
    [dispatch, refreshSavedGraphs, setRunError, submitRoomBatch],
  );
  const addProjectGraph = React.useCallback(() => {
    const graphs = projectRoom.head?.document.graphs ?? [];
    const name = nextNewGraphName(graphs, authoredDocumentRef.current.name);
    const graphId = createUuid();
    commitProjectBatch(
      [{ kind: "add_graph", graph_id: graphId, name }],
      "The Graph could not be added to this Project.",
      graphId,
    );
  }, [authoredDocumentRef, commitProjectBatch, projectRoom.head]);
  const renameProjectGraph = React.useCallback(
    (graphId: string, name: string) => {
      const current = projectRoom.head?.document.graphs.find(
        (graph) => graph.id === graphId,
      );
      if (!current) return;
      commitProjectBatch(
        [toRoomRenameGraphCommand(graphId, name, current.name)],
        "The Graph could not be renamed.",
      );
    },
    [commitProjectBatch, projectRoom.head],
  );
  const removeProjectGraph = React.useCallback(
    (graphId: string) => {
      commitProjectBatch(
        [{ kind: "remove_graph", graph_id: graphId }],
        "The Graph could not be deleted.",
      );
    },
    [commitProjectBatch],
  );
  const openProjectGraph = React.useCallback(
    (graphId: string) => {
      dispatch({
        kind: "switchGraph",
        targetGraphId: graphId,
        nextTrail: [],
        head: projectRoom.head,
        isExecutionRunning: isExecutionRunning(),
        isDirty,
      });
    },
    [dispatch, isDirty, isExecutionRunning, projectRoom.head],
  );
  const openCall = React.useCallback(
    (nodeId: string, calleeGraphId: string) => {
      dispatch({
        kind: "openCall",
        nodeId,
        calleeGraphId,
        head: projectRoom.head,
        isExecutionRunning: isExecutionRunning(),
        isDirty,
      });
    },
    [dispatch, isDirty, isExecutionRunning, projectRoom.head],
  );
  const backFromCall = React.useCallback(() => {
    dispatch({
      kind: "backFromCall",
      head: projectRoom.head,
      isExecutionRunning: isExecutionRunning(),
      isDirty,
    });
  }, [dispatch, isDirty, isExecutionRunning, projectRoom.head]);

  React.useEffect(() => {
    roomCommandSyncRef.current = {
      submitLocal: (commands, before) => {
        const graphId = openGraphIdRef.current;
        if (graphId === null) return;
        const batch: RoomProjectCommand[] = [];
        let current = before;
        for (const command of commands) {
          const mapped = toRoomGraphCommand(command, current, graphId);
          if (mapped) batch.push(mapped);
          current = applyGraphCommandNormalized(current, command);
        }
        if (batch.length === 0) return;
        submitRoomCommands(batch, "Collaborative sync failed.");
      },
    };
  }, [roomCommandSyncRef, submitRoomCommands]);
  React.useEffect(() => {
    presentationRoomSyncRef.current = {
      submitReplace: (viewers) => {
        const command = inOpenGraph({
          kind: "replace_presentation",
          presentation: presentationFromArtifactViewers(viewers),
        });
        if (!command) return;
        submitRoomCommands([command], "Presentation sync failed.");
      },
      submitMove: (positions) => {
        if (positions.length === 0) return;
        const command = inOpenGraph({
          kind: "move_artifact_viewers",
          positions: [...positions],
        });
        if (!command) return;
        submitRoomCommands([command], "Presentation sync failed.");
      },
      submitMoveAnnotations: (positions) => {
        if (positions.length === 0) return;
        const command = inOpenGraph({
          kind: "move_annotations",
          positions: [...positions],
        });
        if (!command) return;
        submitRoomCommands([command], "Presentation sync failed.");
      },
    };
  }, [inOpenGraph, presentationRoomSyncRef, submitRoomCommands]);

  const canPublishRoomPresence = projectRoom.canPublishPresence;
  const publishRoomPresence = projectRoom.publishPresence;
  const schedulePresenceSnapshot = React.useCallback(() => {
    if (!canPublishRoomPresence) return;
    if (presencePublishTimerRef.current !== null) return;
    const elapsed = Date.now() - lastPresencePublishAtRef.current;
    const delay = Math.max(0, PRESENCE_CLIENT_MIN_INTERVAL_MS - elapsed);
    presencePublishTimerRef.current = window.setTimeout(() => {
      presencePublishTimerRef.current = null;
      if (!canPublishRoomPresence) return;
      const clientPoint = presenceClientPointRef.current;
      if (presenceClientPointDirtyRef.current && clientPoint) {
        presenceCursorRef.current = screenToCanvasPoint(clientPoint) ?? null;
        presenceClientPointDirtyRef.current = false;
      }
      const drag = presenceDragRef.current;
      const published = publishRoomPresence({
        graph_id: openGraphIdRef.current,
        cursor: presenceCursorRef.current,
        selected_node_ids: selectedNodeIdsRef.current,
        activity: drag ? "moving_nodes" : null,
        activity_target_ids: drag?.targetIds ?? [],
        transient_node_positions: drag?.positions ?? [],
      });
      if (published) lastPresencePublishAtRef.current = Date.now();
    }, delay);
  }, [canPublishRoomPresence, publishRoomPresence, screenToCanvasPoint]);

  React.useEffect(() => {
    if (canPublishRoomPresence) return;
    if (presencePublishTimerRef.current !== null) {
      window.clearTimeout(presencePublishTimerRef.current);
      presencePublishTimerRef.current = null;
    }
    lastPresencePublishAtRef.current = 0;
  }, [canPublishRoomPresence]);
  React.useEffect(
    () => () => {
      if (presencePublishTimerRef.current !== null) {
        window.clearTimeout(presencePublishTimerRef.current);
      }
    },
    [],
  );
  const presenceSelectionKey = selectedNodeIds.join("\0");
  React.useEffect(() => {
    schedulePresenceSnapshot();
  }, [presenceSelectionKey, schedulePresenceSnapshot]);
  React.useEffect(() => {
    presenceCursorRef.current = null;
    presenceClientPointDirtyRef.current = true;
    schedulePresenceSnapshot();
  }, [openGraphId, schedulePresenceSnapshot]);
  React.useEffect(() => {
    if (!canPublishRoomPresence) return;
    const timer = window.setInterval(() => {
      if (!presenceOverCanvasRef.current || !presenceCursorRef.current) return;
      schedulePresenceSnapshot();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [canPublishRoomPresence, schedulePresenceSnapshot]);

  const onCanvasPointerMove = React.useCallback(
    (event: { clientX: number; clientY: number }) => {
      if (!canPublishRoomPresence || !canvasReady) return;
      presenceOverCanvasRef.current = true;
      presenceClientPointRef.current = { x: event.clientX, y: event.clientY };
      presenceClientPointDirtyRef.current = true;
      schedulePresenceSnapshot();
    },
    [canPublishRoomPresence, canvasReady, schedulePresenceSnapshot],
  );
  const onCanvasPointerLeave = React.useCallback(() => {
    presenceOverCanvasRef.current = false;
    presenceClientPointRef.current = null;
    presenceClientPointDirtyRef.current = false;
    presenceCursorRef.current = null;
    schedulePresenceSnapshot();
  }, [schedulePresenceSnapshot]);
  const onDragCardsProgress = React.useCallback(
    (moves: readonly CanvasCardDrag[] | null) => {
      presenceDragRef.current =
        moves && moves.length > 0
          ? {
              targetIds: moves.map(({ cardId }) => cardId),
              positions: moves.map(({ cardId, col, row }) => ({
                node_id: cardId,
                ...cellToWorldOrigin(col, row),
              })),
            }
          : null;
      schedulePresenceSnapshot();
    },
    [cellToWorldOrigin, schedulePresenceSnapshot],
  );

  return {
    ...lifecycle,
    projectRoom,
    openGraphId,
    projectCatalog,
    projectReadiness,
    projectEditsTrusted,
    projectHasNoGraph,
    unsyncedRoomEdits: state.unsyncedRoomEdits,
    callTrail: state.callTrail,
    localAuthoringEnabled,
    localAuthoringBlockedMessage,
    graphOperationBusy,
    submitRoomCommands,
    inOpenGraph,
    commitProjectBatch,
    addProjectGraph,
    renameProjectGraph,
    removeProjectGraph,
    openProjectGraph,
    openCall,
    backFromCall,
    schedulePresenceSnapshot,
    onCanvasPointerMove,
    onCanvasPointerLeave,
    onDragCardsProgress,
  };
}
