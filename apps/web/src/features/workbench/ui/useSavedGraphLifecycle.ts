"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import { useGraphSummaryRefresh, useSavedGraphs } from "@/hooks/use-api";
import {
  createSavedGraph,
  deleteSavedGraph,
  getGraphMaterializations,
  getSavedGraph,
  updateSavedGraph,
  type CollaborativeHead,
  type CreateSavedGraphRequest,
  type NodeRegistry,
  type RunNodeResult,
  type SavedGraphNode,
  type SavedGraphSummary,
} from "@/lib/api";
import { ApiError } from "@/lib/api/client";
import {
  hydrateAuthoredGraphDocument,
  hydrateSavedGraph,
  savedGraphExecutionFingerprint,
  savedGraphFingerprint,
} from "../canvas/saved-graph";
import {
  emptyGraphPresentation,
  presentationFromCollaborativeHead,
  type GraphPresentation,
} from "../canvas/artifact-viewer";
import {
  authoredGraphDocument,
  createSavedGraphRequest,
  type AuthoredGraphDocument,
} from "../model/graph-document";
import type {
  WorkflowNodeData,
} from "../canvas/types";
import type { WorkflowNode } from "../model/execution-plan";
import {
  NEW_GRAPH_ROUTE_ID,
  workbenchGraphPath,
} from "../routes";

export interface ActiveSavedGraph {
  id: string;
  revision: number;
  nodes: readonly SavedGraphNode[];
}

export interface GraphRoomPersistenceResult {
  readonly checkpointHead: CollaborativeHead;
  readonly currentHead: CollaborativeHead;
}

/** Prefer room/command persistence when the graph room can accept edits. */
export interface GraphRoomPersistenceAdapter {
  readonly canPersist: boolean;
  /** Keep the exact checkpoint separate from a newer effective room head. */
  persistDocument: (
    draft: CreateSavedGraphRequest,
  ) => Promise<GraphRoomPersistenceResult>;
}

interface UseSavedGraphLifecycleOptions {
  workspaceId: string;
  workspaceSlug: string;
  initialGraphId: string | null;
  registry: NodeRegistry | undefined;
  document: AuthoredGraphDocument;
  /** Shared Artifact Viewer presentation included in fingerprints and saves. */
  presentation?: GraphPresentation;
  nodes: readonly WorkflowNode[];
  isExecutionRunning: () => boolean;
  uploading: boolean;
  replaceDocument: (
    document: AuthoredGraphDocument,
    overlayNodes?: readonly WorkflowNode[],
  ) => void;
  /** Apply shared presentation from head/checkpoint/save responses. */
  replacePresentation: (
    graphId: string,
    presentation: GraphPresentation,
  ) => void;
  updateDocumentName: (name: string) => void;
  attachNodeCallbacks: (data: WorkflowNodeData) => WorkflowNodeData;
  refreshNodeSecretStatuses: (
    graph: ActiveSavedGraph,
    nodes: readonly WorkflowNode[],
    signal?: AbortSignal,
  ) => Promise<boolean>;
  clearGraphSecretStatuses: () => void;
  clearPendingConnectionRoute: () => void;
  clearRunError: () => void;
  closeNodeLibrary: () => void;
  requestCanvasRefit: () => void;
  refreshNodeRegistry: () => void | Promise<unknown>;
  roomPersistence?: GraphRoomPersistenceAdapter | null;
}

export interface UseSavedGraphLifecycleResult {
  activeGraph: ActiveSavedGraph | null;
  graphName: string;
  setGraphName: (name: string) => void;
  currentFingerprint: string;
  isDirty: boolean;
  /** True when workflow topology matches the saved revision (ignores presentation). */
  canMaterializeSavedGraph: boolean;
  saving: boolean;
  openingGraphId: string | null;
  deletingGraphId: string | null;
  persistenceError: string | null;
  clearPersistenceError: () => void;
  dismissPersistenceError: (message: string) => void;
  persistenceOperationBusy: boolean;
  graphBrowserOpen: boolean;
  toggleGraphBrowser: () => void;
  closeGraphBrowser: () => void;
  savedGraphs: readonly SavedGraphSummary[];
  savedGraphsLoading: boolean;
  savedGraphsRefreshing: boolean;
  savedGraphsError: string | null;
  refreshSavedGraphs: () => void;
  requestNewGraph: () => void;
  saveCurrentGraph: (nameOverride?: string) => Promise<void>;
  openSavedGraph: (graphId: string) => Promise<void>;
  removeSavedGraph: (graph: SavedGraphSummary) => Promise<void>;
  syncFromCollaborativeHead: (head: CollaborativeHead) => void;
  purgeLocalGraphState: () => void;
}

const NEW_GRAPH_NAME = "Untitled workflow";

export function useSavedGraphLifecycle({
  workspaceId,
  workspaceSlug,
  initialGraphId,
  registry,
  document,
  presentation = emptyGraphPresentation(),
  nodes,
  isExecutionRunning,
  uploading,
  replaceDocument,
  replacePresentation,
  updateDocumentName,
  attachNodeCallbacks,
  refreshNodeSecretStatuses,
  clearGraphSecretStatuses,
  clearPendingConnectionRoute,
  clearRunError,
  closeNodeLibrary,
  requestCanvasRefit,
  refreshNodeRegistry,
  roomPersistence = null,
}: UseSavedGraphLifecycleOptions): UseSavedGraphLifecycleResult {
  const router = useRouter();
  const {
    data: savedGraphList,
    error: savedGraphListError,
    isLoading: savedGraphsLoading,
    isValidating: savedGraphsRefreshing,
  } = useSavedGraphs(workspaceId);
  // Saving, deleting, and room rehydration must refresh every discovery
  // surface, not just this workspace's saved-graph list.
  const refreshGraphSummaries = useGraphSummaryRefresh();
  const [activeGraph, setActiveGraph] =
    React.useState<ActiveSavedGraph | null>(null);
  const [savedFingerprint, setSavedFingerprint] =
    React.useState<string | null>(null);
  const [savedExecutionFingerprint, setSavedExecutionFingerprint] =
    React.useState<string | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [openingGraphId, setOpeningGraphId] = React.useState<string | null>(null);
  const [deletingGraphId, setDeletingGraphId] = React.useState<string | null>(null);
  const [persistenceError, setPersistenceError] = React.useState<string | null>(null);
  const [graphBrowserOpen, setGraphBrowserOpen] = React.useState(false);
  const approvedRouteGraphIdRef = React.useRef<string | null>(null);
  const openRequestRef = React.useRef<AbortController | null>(null);
  const documentGenerationRef = React.useRef(0);
  const mountedRef = React.useRef(true);
  const currentFingerprintRef = React.useRef("");

  const currentDraft = React.useMemo(
    () => createSavedGraphRequest(document, presentation),
    [document, presentation],
  );
  const currentFingerprint = React.useMemo(
    () => savedGraphFingerprint(currentDraft),
    [currentDraft],
  );
  const currentExecutionFingerprint = React.useMemo(
    () => savedGraphExecutionFingerprint(currentDraft),
    [currentDraft],
  );
  const rememberSavedDraft = React.useCallback((draft: CreateSavedGraphRequest) => {
    setSavedFingerprint(savedGraphFingerprint(draft));
    setSavedExecutionFingerprint(savedGraphExecutionFingerprint(draft));
  }, []);

  React.useEffect(() => {
    currentFingerprintRef.current = currentFingerprint;
  }, [currentFingerprint]);

  const hasUnsavedDraft =
    document.nodes.length > 0 ||
    document.edges.length > 0 ||
    (presentation.viewers?.length ?? 0) > 0 ||
    (presentation.links?.length ?? 0) > 0 ||
    (presentation.bindings?.length ?? 0) > 0 ||
    document.name.trim() !== NEW_GRAPH_NAME;
  const isDirty = activeGraph
    ? savedFingerprint !== currentFingerprint
    : hasUnsavedDraft;
  const canMaterializeSavedGraph = Boolean(
    activeGraph &&
      savedExecutionFingerprint !== null &&
      savedExecutionFingerprint === currentExecutionFingerprint,
  );
  const persistenceOperationBusy = Boolean(
    saving || openingGraphId || deletingGraphId || uploading,
  );

  React.useEffect(() => {
    if (!isDirty) return;
    const warnBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warnBeforeUnload);
    return () => window.removeEventListener("beforeunload", warnBeforeUnload);
  }, [isDirty]);

  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      documentGenerationRef.current += 1;
      openRequestRef.current?.abort();
    };
  }, []);

  const confirmDiscard = React.useCallback(
    (action: string): boolean =>
      !isDirty ||
      window.confirm(
        `“${document.name.trim() || NEW_GRAPH_NAME}” has unsaved changes. Discard them and ${action}?`,
      ),
    [document.name, isDirty],
  );

  const showBlankGraph = React.useCallback(() => {
    documentGenerationRef.current += 1;
    openRequestRef.current?.abort();
    replaceDocument({ name: NEW_GRAPH_NAME, nodes: [], edges: [] }, []);
    clearGraphSecretStatuses();
    setActiveGraph(null);
    setSavedFingerprint(null);
    setSavedExecutionFingerprint(null);
    clearPendingConnectionRoute();
    clearRunError();
    setPersistenceError(null);
    closeNodeLibrary();
    requestCanvasRefit();
  }, [
    clearGraphSecretStatuses,
    clearPendingConnectionRoute,
    clearRunError,
    closeNodeLibrary,
    replaceDocument,
    requestCanvasRefit,
  ]);

  const requestNewGraph = React.useCallback(() => {
    if (!confirmDiscard("start a new graph")) return;
    setGraphBrowserOpen(false);
    const path = workbenchGraphPath(workspaceSlug, NEW_GRAPH_ROUTE_ID);
    if (window.location.pathname === path) {
      showBlankGraph();
      return;
    }
    documentGenerationRef.current += 1;
    openRequestRef.current?.abort();
    approvedRouteGraphIdRef.current = NEW_GRAPH_ROUTE_ID;
    router.push(path, { scroll: false });
  }, [confirmDiscard, router, showBlankGraph, workspaceSlug]);

  const syncFromCollaborativeHead = React.useCallback((
    head: CollaborativeHead,
  ): void => {
    const responseDocument = authoredGraphDocument(head);
    const responsePresentation = presentationFromCollaborativeHead(head);
    const nextActiveGraph = {
      id: head.graph_id,
      revision: head.checkpoint_revision,
      nodes: responseDocument.nodes,
    };
    const headIsCheckpointed =
      head.collaboration_sequence === head.checkpoint_sequence;
    approvedRouteGraphIdRef.current = head.graph_id;
    if (headIsCheckpointed) {
      setActiveGraph(nextActiveGraph);
      rememberSavedDraft(
        createSavedGraphRequest(responseDocument, responsePresentation),
      );
    } else {
      // The room journal is authoritative for the canvas but is not durable
      // until its current sequence has been checkpointed.
      setSavedFingerprint(null);
      setSavedExecutionFingerprint(null);
    }
    setPersistenceError(null);
    // Preserve execution overlays: room sync must not clear materialized pins.
    replaceDocument(responseDocument);
    replacePresentation(head.graph_id, responsePresentation);
    if (headIsCheckpointed) {
      const checkpointNodes = registry
        ? hydrateAuthoredGraphDocument(responseDocument, registry).nodes.map(
            (node) => ({
              ...node,
              data: attachNodeCallbacks(node.data),
            }),
          )
        : nodes;
      void refreshNodeSecretStatuses(nextActiveGraph, checkpointNodes);
    }
  }, [
    attachNodeCallbacks,
    nodes,
    refreshNodeSecretStatuses,
    registry,
    rememberSavedDraft,
    replaceDocument,
    replacePresentation,
  ]);

  const saveCurrentGraph = React.useCallback(async (nameOverride?: string) => {
    if (
      isExecutionRunning() ||
      saving ||
      openingGraphId ||
      deletingGraphId
    ) return;
    const submittedDraft = nameOverride?.trim()
      ? { ...currentDraft, name: nameOverride.trim() }
      : currentDraft;
    if (!submittedDraft.name) {
      setPersistenceError("Enter a graph name before saving.");
      return;
    }
    const activeRoomPersistence = activeGraph === null
      ? null
      : roomPersistence;
    if (
      activeRoomPersistence !== null &&
      !activeRoomPersistence.canPersist
    ) {
      setPersistenceError(
        "Graph synchronization is unavailable while the collaboration room connects or reconnects. Your canvas is unchanged; wait for synchronization to finish, then try saving again.",
      );
      return;
    }
    const documentGeneration = documentGenerationRef.current;
    setSaving(true);
    setPersistenceError(null);
    try {
      const persistenceResult = activeRoomPersistence
        ? {
            kind: "collaborative" as const,
            result: await activeRoomPersistence.persistDocument(submittedDraft),
          }
        : {
            kind: "saved" as const,
            graph: activeGraph
              ? await updateSavedGraph(workspaceId, activeGraph.id, {
                  ...submittedDraft,
                  expected_revision: activeGraph.revision,
                })
              : await createSavedGraph(workspaceId, submittedDraft),
          };
      if (!mountedRef.current) return;
      void refreshGraphSummaries(workspaceId);
      void refreshNodeRegistry();
      if (
        documentGenerationRef.current !== documentGeneration
      ) {
        return;
      }
      if (persistenceResult.kind === "collaborative") {
        const { checkpointHead, currentHead } = persistenceResult.result;
        syncFromCollaborativeHead(checkpointHead);
        if (
          currentHead.room_epoch !== checkpointHead.room_epoch ||
          currentHead.collaboration_sequence !==
            checkpointHead.collaboration_sequence
        ) {
          syncFromCollaborativeHead(currentHead);
        }
        if (
          !mountedRef.current ||
          documentGenerationRef.current !== documentGeneration
        ) {
          return;
        }
        return;
      }
      const savedGraph = persistenceResult.graph;
      const responseDocument = authoredGraphDocument(savedGraph);
      const responsePresentation =
        savedGraph.document.presentation ?? emptyGraphPresentation();
      const nextActiveGraph = {
        id: savedGraph.id,
        revision: savedGraph.revision,
        nodes: savedGraph.document.nodes,
      };
      const createdGraph = activeGraph === null;
      if (createdGraph) {
        approvedRouteGraphIdRef.current = savedGraph.id;
      }
      setActiveGraph(nextActiveGraph);
      rememberSavedDraft(
        createSavedGraphRequest(responseDocument, responsePresentation),
      );
      replacePresentation(savedGraph.id, responsePresentation);
      if (createdGraph) {
        router.replace(
          workbenchGraphPath(workspaceSlug, savedGraph.id),
          { scroll: false },
        );
      }
      await refreshNodeSecretStatuses(nextActiveGraph, nodes);
      if (
        !mountedRef.current ||
        documentGenerationRef.current !== documentGeneration
      ) {
        return;
      }
    } catch (error) {
      if (
        !mountedRef.current ||
        documentGenerationRef.current !== documentGeneration
      ) {
        return;
      }
      if (error instanceof ApiError && error.status === 409) {
        setPersistenceError(
          `Save conflict: ${error.detail}. Your canvas is unchanged; refresh the saved graph list before deciding whether to reopen it.`,
        );
      } else {
        setPersistenceError(
          error instanceof Error ? error.message : "The graph could not be saved.",
        );
      }
    } finally {
      if (mountedRef.current) setSaving(false);
    }
  }, [
    activeGraph,
    currentDraft,
    deletingGraphId,
    isExecutionRunning,
    nodes,
    openingGraphId,
    refreshGraphSummaries,
    refreshNodeRegistry,
    refreshNodeSecretStatuses,
    rememberSavedDraft,
    replacePresentation,
    roomPersistence,
    router,
    saving,
    syncFromCollaborativeHead,
    workspaceId,
    workspaceSlug,
  ]);

  const purgeLocalGraphState = React.useCallback(() => {
    documentGenerationRef.current += 1;
    openRequestRef.current?.abort();
    setActiveGraph(null);
    setSavedFingerprint(null);
    setSavedExecutionFingerprint(null);
    setPersistenceError(null);
    setGraphBrowserOpen(false);
    clearGraphSecretStatuses();
    clearPendingConnectionRoute();
    clearRunError();
    closeNodeLibrary();
    replaceDocument({
      name: NEW_GRAPH_NAME,
      nodes: [],
      edges: [],
    }, []);
    replacePresentation("", emptyGraphPresentation());
  }, [
    clearGraphSecretStatuses,
    clearPendingConnectionRoute,
    clearRunError,
    closeNodeLibrary,
    replaceDocument,
    replacePresentation,
  ]);

  const openSavedGraph = React.useCallback(async (
    graphId: string,
    confirmBeforeOpen = true,
    updateAddress = true,
  ) => {
    if (!registry) {
      setPersistenceError("The live node registry must load before a graph can open.");
      return;
    }
    if (confirmBeforeOpen && !confirmDiscard("open another graph")) return;
    if (updateAddress) {
      setGraphBrowserOpen(false);
      if (activeGraph?.id !== graphId) {
        documentGenerationRef.current += 1;
        openRequestRef.current?.abort();
        approvedRouteGraphIdRef.current = graphId;
        // Lock durable editing before routing. The App Router can retain the
        // old canvas until the new graph route reaches this hook's load path.
        setOpeningGraphId(graphId);
        try {
          router.push(
            workbenchGraphPath(workspaceSlug, graphId),
            { scroll: false },
          );
        } catch (error) {
          approvedRouteGraphIdRef.current = null;
          setOpeningGraphId((current) => current === graphId ? null : current);
          setPersistenceError(
            error instanceof Error
              ? `Could not navigate to the graph: ${error.message}`
              : "Could not navigate to the graph.",
          );
        }
      }
      return;
    }

    const openingFingerprint = currentFingerprint;
    openRequestRef.current?.abort();
    documentGenerationRef.current += 1;
    const documentGeneration = documentGenerationRef.current;
    const controller = new AbortController();
    openRequestRef.current = controller;
    setOpeningGraphId(graphId);
    setPersistenceError(null);
    try {
      const savedGraph = await getSavedGraph(workspaceId, graphId, controller.signal);
      if (
        controller.signal.aborted ||
        !mountedRef.current ||
        documentGenerationRef.current !== documentGeneration
      ) {
        return;
      }
      let materializationWarning: string | null = null;
      let materializedNodeRuns: RunNodeResult[] = [];
      try {
        const materializations = await getGraphMaterializations(
          workspaceId,
          graphId,
          savedGraph.revision,
          controller.signal,
        );
        materializedNodeRuns = [...materializations.node_runs];
      } catch (error) {
        if (controller.signal.aborted) return;
        const message = error instanceof Error
          ? error.message
          : "Latest materialized outputs could not be loaded.";
        materializationWarning =
          `Graph opened without its latest materialized outputs: ${message}`;
      }
      const hydrated = hydrateSavedGraph(
        savedGraph,
        registry,
        materializedNodeRuns,
      );
      if (controller.signal.aborted) return;
      if (
        !mountedRef.current ||
        documentGenerationRef.current !== documentGeneration
      ) {
        return;
      }
      if (currentFingerprintRef.current !== openingFingerprint) {
        setPersistenceError(
          "The canvas changed while the graph was loading. Your newer edits were kept; open the graph again when you are ready to replace them.",
        );
        return;
      }

      const responseDocument = authoredGraphDocument(savedGraph);
      const responsePresentation =
        savedGraph.document.presentation ?? emptyGraphPresentation();
      const openedNodes = hydrated.nodes.map((node) => ({
        ...node,
        data: attachNodeCallbacks(node.data),
      }));
      replaceDocument(responseDocument, openedNodes);
      replacePresentation(savedGraph.id, responsePresentation);
      const nextActiveGraph = {
        id: savedGraph.id,
        revision: savedGraph.revision,
        nodes: savedGraph.document.nodes,
      };
      setActiveGraph(nextActiveGraph);
      rememberSavedDraft(
        createSavedGraphRequest(responseDocument, responsePresentation),
      );
      await refreshNodeSecretStatuses(
        nextActiveGraph,
        openedNodes,
        controller.signal,
      );
      if (
        controller.signal.aborted ||
        !mountedRef.current ||
        documentGenerationRef.current !== documentGeneration
      ) {
        return;
      }
      clearPendingConnectionRoute();
      clearRunError();
      setPersistenceError(materializationWarning);
      closeNodeLibrary();
      setGraphBrowserOpen(false);
      requestCanvasRefit();
    } catch (error) {
      if (
        !controller.signal.aborted &&
        mountedRef.current &&
        documentGenerationRef.current === documentGeneration
      ) {
        setPersistenceError(
          error instanceof Error ? error.message : "The graph could not be opened.",
        );
      }
    } finally {
      if (openRequestRef.current === controller) {
        openRequestRef.current = null;
        if (mountedRef.current) setOpeningGraphId(null);
      }
    }
  }, [
    activeGraph?.id,
    attachNodeCallbacks,
    clearPendingConnectionRoute,
    clearRunError,
    closeNodeLibrary,
    confirmDiscard,
    currentFingerprint,
    refreshNodeSecretStatuses,
    registry,
    rememberSavedDraft,
    replaceDocument,
    replacePresentation,
    requestCanvasRefit,
    router,
    workspaceId,
    workspaceSlug,
  ]);

  React.useEffect(() => {
    if (!registry) return;

    const routeGraphId = initialGraphId ?? NEW_GRAPH_ROUTE_ID;
    const displayedGraphId = activeGraph?.id ?? NEW_GRAPH_ROUTE_ID;
    if (routeGraphId === displayedGraphId) {
      if (approvedRouteGraphIdRef.current === routeGraphId) {
        approvedRouteGraphIdRef.current = null;
      }
      return;
    }

    if (
      approvedRouteGraphIdRef.current !== null &&
      approvedRouteGraphIdRef.current !== routeGraphId
    ) {
      return;
    }

    const explicitlyApproved =
      approvedRouteGraphIdRef.current === routeGraphId;
    approvedRouteGraphIdRef.current = null;
    if (!explicitlyApproved && !confirmDiscard("navigate with browser history")) {
      approvedRouteGraphIdRef.current = displayedGraphId;
      router.push(
        workbenchGraphPath(workspaceSlug, displayedGraphId),
        { scroll: false },
      );
      return;
    }

    if (!initialGraphId) {
      // The App Router retains this workbench so history navigation can be confirmed first.
      // Once accepted, the route change is the boundary that replaces the canvas draft.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      showBlankGraph();
      return;
    }

    void openSavedGraph(initialGraphId, false, false);
  }, [
    activeGraph?.id,
    confirmDiscard,
    initialGraphId,
    openSavedGraph,
    registry,
    router,
    showBlankGraph,
    workspaceSlug,
  ]);

  const removeSavedGraph = React.useCallback(async (
    graph: SavedGraphSummary,
  ) => {
    const deletingActiveGraph = activeGraph?.id === graph.id;
    const warning = deletingActiveGraph && isDirty
      ? `Delete “${graph.name}”? Its unsaved canvas changes will also be discarded.`
      : `Delete “${graph.name}”? This cannot be undone.`;
    if (!window.confirm(warning)) return;

    const expectedRevision = deletingActiveGraph
      ? activeGraph.revision
      : graph.revision;
    const deletingFingerprint = currentFingerprint;
    const documentGeneration = documentGenerationRef.current;
    setDeletingGraphId(graph.id);
    setPersistenceError(null);
    try {
      await deleteSavedGraph(workspaceId, graph.id, expectedRevision);
      if (!mountedRef.current) return;
      void refreshGraphSummaries(workspaceId);
      void refreshNodeRegistry();
      if (
        documentGenerationRef.current !== documentGeneration
      ) {
        return;
      }
      if (deletingActiveGraph) {
        if (currentFingerprintRef.current === deletingFingerprint) {
          showBlankGraph();
          approvedRouteGraphIdRef.current = NEW_GRAPH_ROUTE_ID;
          router.replace(
            workbenchGraphPath(workspaceSlug, NEW_GRAPH_ROUTE_ID),
            { scroll: false },
          );
        } else {
          setActiveGraph(null);
          setSavedFingerprint(null);
          setSavedExecutionFingerprint(null);
          clearGraphSecretStatuses();
          setPersistenceError(
            "The saved graph was deleted. Changes made while deletion was in progress remain as an unsaved draft.",
          );
          approvedRouteGraphIdRef.current = NEW_GRAPH_ROUTE_ID;
          router.replace(
            workbenchGraphPath(workspaceSlug, NEW_GRAPH_ROUTE_ID),
            { scroll: false },
          );
        }
      }
    } catch (error) {
      if (
        !mountedRef.current ||
        documentGenerationRef.current !== documentGeneration
      ) {
        return;
      }
      if (error instanceof ApiError && error.status === 409) {
        setPersistenceError(
          "This graph changed before it could be deleted. Refresh the saved graph list and try again.",
        );
      } else {
        setPersistenceError(
          error instanceof Error ? error.message : "The graph could not be deleted.",
        );
      }
    } finally {
      if (mountedRef.current) setDeletingGraphId(null);
    }
  }, [
    activeGraph,
    clearGraphSecretStatuses,
    currentFingerprint,
    isDirty,
    refreshGraphSummaries,
    refreshNodeRegistry,
    router,
    showBlankGraph,
    workspaceId,
    workspaceSlug,
  ]);

  const setGraphName = React.useCallback((name: string) => {
    updateDocumentName(name);
    setPersistenceError(null);
  }, [updateDocumentName]);
  const clearPersistenceError = React.useCallback(() => {
    setPersistenceError(null);
  }, []);
  const dismissPersistenceError = React.useCallback((message: string) => {
    setPersistenceError((current) => current === message ? null : current);
  }, []);
  const toggleGraphBrowser = React.useCallback(() => {
    closeNodeLibrary();
    setGraphBrowserOpen((open) => !open);
  }, [closeNodeLibrary]);
  const closeGraphBrowser = React.useCallback(() => {
    setGraphBrowserOpen(false);
  }, []);
  const refreshSavedGraphs = React.useCallback(() => {
    void refreshGraphSummaries(workspaceId);
  }, [refreshGraphSummaries, workspaceId]);
  const savedGraphsError = savedGraphListError instanceof Error
    ? savedGraphListError.message
    : savedGraphListError
      ? "Saved graphs are unavailable."
      : null;

  return {
    activeGraph,
    graphName: document.name,
    setGraphName,
    currentFingerprint,
    isDirty,
    canMaterializeSavedGraph,
    saving,
    openingGraphId,
    deletingGraphId,
    persistenceError,
    clearPersistenceError,
    dismissPersistenceError,
    persistenceOperationBusy,
    graphBrowserOpen,
    toggleGraphBrowser,
    closeGraphBrowser,
    savedGraphs: savedGraphList?.graphs ?? [],
    savedGraphsLoading,
    savedGraphsRefreshing,
    savedGraphsError,
    refreshSavedGraphs,
    requestNewGraph,
    saveCurrentGraph,
    openSavedGraph,
    removeSavedGraph,
    syncFromCollaborativeHead,
    purgeLocalGraphState,
  };
}
