"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import {
  useProjectSummaryRefresh,
  useWorkspaceProjects,
} from "@/hooks/use-api";
import {
  createProject,
  deleteProject,
  getCollaborativeHead,
  graphFromProjectHead,
  submitProjectCommand,
  type CollaborativeHead,
  type GraphDraft,
  type SavedGraph,
  type NodeRegistry,
  type RunNodeResult,
  type SavedGraphNode,
  type SavedGraphSummary,
} from "@/lib/api";
import { createUuid } from "../model/uuid";
import { loadInstanceSnapshot } from "./run-execution/state";
import {
  nodeSecretDependencyRevision,
  nodeSecretInputs,
} from "../canvas/node-secrets";
import { workflowNodeIsSupported } from "../canvas/types";
import { ApiError } from "@/lib/api/client";
import {
  hydrateAuthoredGraphDocument,
  hydrateSavedGraph,
  savedGraphFingerprint,
} from "../canvas/saved-graph";
import {
  emptyGraphPresentation,
  type GraphPresentation,
} from "../canvas/artifact-viewer";
import {
  createGraphDraft,
  type AuthoredGraphDocument,
} from "../model/graph-document";
import type { WorkflowNodeData } from "../canvas/types";
import type { WorkflowNode } from "../model/execution-plan";
import { NEW_PROJECT_ROUTE_ID, workbenchGraphPath } from "../routes";
import { NEW_GRAPH_NAME, savedGraphDirtiness } from "./saved-graph-dirtiness";

/**
 * The Graph a canvas shows inside a Project: the one it already had open, and
 * otherwise the Project's first Graph. A canvas is one Graph, so the canvas
 * chooses — but a Project opened cold has no earlier choice to honour.
 */
function openGraphOf(
  head: CollaborativeHead,
  preferred: string | null,
): SavedGraph | null {
  const graphs = head.document.graphs;
  const preferredGraph =
    preferred === null
      ? undefined
      : graphs.find((graph) => graph.id === preferred);
  const chosen = preferredGraph ?? graphs[0];
  return chosen === undefined ? null : graphFromProjectHead(head, chosen.id);
}

function activeGraphFrom(
  head: CollaborativeHead,
  graph: SavedGraph,
): ActiveSavedGraph {
  return {
    id: head.project_id,
    graphId: graph.id,
    // Every Graph shares its Project head's collaboration sequence.
    revision: head.collaboration_sequence,
    nodes: graph.document.nodes,
  };
}

/**
 * The authored body of one Graph: its name, its document, and the canvas layout
 * that sits beside it. The wire GraphDocument carries no name (a Graph's name
 * lives on the Graph, not its document) and omits `origins` when empty, while
 * the authoring model expects both fields to be present.
 */
interface DraftGraphDocument extends AuthoredGraphDocument {
  readonly presentation?: GraphPresentation;
}

function documentOfGraph(graph: SavedGraph): DraftGraphDocument {
  return {
    name: graph.name,
    nodes: graph.document.nodes.map((node) => ({ ...node })),
    edges: graph.document.edges.map((edge) => ({ ...edge })),
    origins: graph.document.origins
      ? graph.document.origins.map((origin) => ({ ...origin }))
      : [],
    // An Agent is canvas content, so opening a Graph has to carry it across like a node: a
    // document rebuilt field by field that forgot `agents` would save the canvas without the
    // cards the person was looking at.
    agents: (graph.document.agents ?? []).map((agent) => ({ ...agent })),
    presentation: presentationOf(graph),
  };
}

function presentationOf(graph: SavedGraph): GraphPresentation {
  const presentation = graph.document.presentation;
  return presentation === undefined
    ? emptyGraphPresentation()
    : {
        viewers: [...presentation.viewers],
        links: [...presentation.links],
        bindings: [...presentation.bindings],
        annotations: [...presentation.annotations],
      };
}

async function createProjectWithGraph(
  workspaceId: string,
  draft: GraphDraft,
): Promise<CollaborativeHead> {
  const graphId = createUuid();
  const project = await createProject(workspaceId, {
    name: draft.name,
    graph_id: graphId,
    graph_name: draft.name,
  });
  const head = await getCollaborativeHead(workspaceId, project.id);
  const submitted = await submitProjectCommand(workspaceId, project.id, {
    command_id: createUuid(),
    observed_sequence: head.collaboration_sequence,
    room_epoch: head.room_epoch,
    commands: [
      {
        kind: "in_graph",
        graph_id: graphId,
        command: {
          kind: "replace_document",
          document: { ...draft.document, schema_version: 7 },
        },
      },
    ],
  });
  return submitted.head;
}

/**
 * The canvas' place in the server: one Graph, inside one Project.
 *
 * `id` is the Project the route names and the room is bound to; `graphId` is
 * which Graph of that Project this canvas is showing. A Run needs both, and
 * `revision` is the Project head's collaboration sequence.
 */
export interface ActiveSavedGraph {
  id: string;
  graphId: string;
  revision: number;
  nodes: readonly SavedGraphNode[];
}

interface UseSavedGraphLifecycleOptions {
  workspaceId: string;
  workspaceSlug: string;
  initialGraphId: string | null;
  registry: NodeRegistry | undefined;
  document: AuthoredGraphDocument;
  /** Shared Artifact Viewer presentation included in fingerprints and saves. */
  presentation?: GraphPresentation;
  isExecutionRunning: () => boolean;
  replaceDocument: (
    document: AuthoredGraphDocument,
    overlayNodes?: readonly WorkflowNode[],
  ) => void;
  /**
   * Replace the artifact cards on the canvas with `presentation`. Every change of active
   * graph goes through here, so the cards the canvas draws and the cards the save body
   * sends are one value that moves together with the document.
   */
  replacePresentation: (presentation: GraphPresentation) => void;
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
  roomHead?: CollaborativeHead | null;
  hasPendingRoomCommands?: boolean;
  /**
   * Edits the room refused while it was connecting or reconnecting, which therefore
   * exist only in this tab. Edits that reach the room journal are durable the
   * moment they happen, so an uncheckpointed revision is not a reason to
   * interrupt a reload.
   */
  hasUnsyncedRoomEdits?: boolean;
}

export interface UseSavedGraphLifecycleResult {
  activeGraph: ActiveSavedGraph | null;
  graphName: string;
  setGraphName: (name: string) => void;
  currentFingerprint: string;
  isDirty: boolean;
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
  /** The Graph of the Project the canvas shows; null before the first head. */
  openGraphId: string | null;
  openGraphInProject: (head: CollaborativeHead, graphId: string) => void;
  purgeLocalGraphState: () => void;
}

export function useSavedGraphLifecycle({
  workspaceId,
  workspaceSlug,
  initialGraphId,
  registry,
  document,
  presentation,
  isExecutionRunning,
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
  roomHead = null,
  hasPendingRoomCommands = false,
  hasUnsyncedRoomEdits = false,
}: UseSavedGraphLifecycleOptions): UseSavedGraphLifecycleResult {
  const router = useRouter();
  const {
    data: savedGraphList,
    error: savedGraphListError,
    isLoading: savedGraphsLoading,
    isValidating: savedGraphsRefreshing,
  } = useWorkspaceProjects(workspaceId);
  // Saving, deleting, and room rehydration must refresh every discovery
  // surface, not just this workspace's saved-graph list.
  const refreshGraphSummaries = useProjectSummaryRefresh();
  const [openedHead, setOpenedHead] = React.useState<CollaborativeHead | null>(
    null,
  );
  const [saving, setSaving] = React.useState(false);
  const [openingGraphId, setOpeningGraphId] = React.useState<string | null>(
    null,
  );
  const [deletingGraphId, setDeletingGraphId] = React.useState<string | null>(
    null,
  );
  const [persistenceError, setPersistenceError] = React.useState<string | null>(
    null,
  );
  const [graphBrowserOpen, setGraphBrowserOpen] = React.useState(false);
  const approvedRouteGraphIdRef = React.useRef<string | null>(null);
  // Which Graph of the Project the canvas is showing. The route names the
  // Project, so an open has to carry the choice across a head refresh.
  const openGraphIdRef = React.useRef<string | null>(null);
  // The same choice as state, so the canvas chrome re-renders when it moves.
  const [openGraphId, setOpenGraphId] = React.useState<string | null>(null);
  const openRequestRef = React.useRef<AbortController | null>(null);
  const documentGenerationRef = React.useRef(0);
  const mountedRef = React.useRef(true);
  const currentFingerprintRef = React.useRef("");
  const emptyPresentation = React.useMemo(() => emptyGraphPresentation(), []);
  const presentationRef = React.useRef(presentation ?? emptyPresentation);
  const creatingRef = React.useRef(false);
  const secretRefreshRef = React.useRef<{
    key: string;
    request: AbortController;
  } | null>(null);
  const liveHead = roomHead ?? openedHead;
  const activeGraph = React.useMemo(() => {
    if (liveHead === null) return null;
    const graph = openGraphOf(liveHead, openGraphId);
    return graph === null ? null : activeGraphFrom(liveHead, graph);
  }, [liveHead, openGraphId]);

  const currentDraft = React.useMemo(
    () => createGraphDraft(document, presentation),
    [document, presentation],
  );
  const currentFingerprint = React.useMemo(
    () => savedGraphFingerprint(currentDraft),
    [currentDraft],
  );

  React.useLayoutEffect(() => {
    currentFingerprintRef.current = currentFingerprint;
    presentationRef.current = presentation ?? emptyPresentation;
  }, [currentFingerprint, emptyPresentation, presentation]);

  const { isDirty, persistenceOperationBusy } = savedGraphDirtiness({
    document,
    presentation: presentation ?? emptyPresentation,
    hasActiveGraph: initialGraphId !== null || openedHead !== null,
    hasUnsyncedRoomEdits,
    hasPendingRoomCommands,
    saving,
    openingGraphId,
    deletingGraphId,
  });

  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      documentGenerationRef.current += 1;
      openRequestRef.current?.abort();
      secretRefreshRef.current?.request.abort();
      secretRefreshRef.current = null;
    };
  }, []);

  // Leaving a graph used to ask before discarding edits that exist only in
  // this tab. That confirm fired on ordinary page changes and blocked the
  // in-app browser, so navigation proceeds without it.
  const confirmDiscard = React.useCallback(
    (_action: string): boolean => true,
    [],
  );

  const showBlankGraph = React.useCallback(() => {
    documentGenerationRef.current += 1;
    openRequestRef.current?.abort();
    replaceDocument(
      { name: NEW_GRAPH_NAME, nodes: [], edges: [], origins: [], agents: [] },
      [],
    );
    // A blank draft owns no cards. Without this the previous graph's cards stay on the
    // canvas and ride into the new graph's first save.
    replacePresentation(emptyGraphPresentation());
    secretRefreshRef.current?.request.abort();
    secretRefreshRef.current = null;
    clearGraphSecretStatuses();
    openGraphIdRef.current = null;
    setOpenGraphId(null);
    setOpenedHead(null);
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
    replacePresentation,
    requestCanvasRefit,
  ]);

  const requestNewGraph = React.useCallback(() => {
    if (!confirmDiscard("start a new graph")) return;
    setGraphBrowserOpen(false);
    const path = workbenchGraphPath(workspaceSlug, NEW_PROJECT_ROUTE_ID);
    if (window.location.pathname === path) {
      showBlankGraph();
      return;
    }
    documentGenerationRef.current += 1;
    openRequestRef.current?.abort();
    approvedRouteGraphIdRef.current = NEW_PROJECT_ROUTE_ID;
    router.push(path, { scroll: false });
  }, [confirmDiscard, router, showBlankGraph, workspaceSlug]);

  const syncFromCollaborativeHead = React.useCallback(
    (head: CollaborativeHead): void => {
      openRequestRef.current?.abort();
      // The canvas shows one Graph of this Project: keep the one it had, and
      // take the Project's first Graph when there was none.
      const openedGraph = openGraphOf(head, openGraphIdRef.current);
      setOpenedHead(head);
      approvedRouteGraphIdRef.current = head.project_id;
      openGraphIdRef.current = openedGraph?.id ?? null;
      setOpenGraphId(openedGraph?.id ?? null);
      setPersistenceError(null);
      if (openedGraph === null) return;
      // Room snapshots preserve execution overlays. Results belong to instances.
      replaceDocument(documentOfGraph(openedGraph));
      replacePresentation(presentationOf(openedGraph));
    },
    [replaceDocument, replacePresentation],
  );

  // Refresh status only when the accepted bindings change. Positions, unrelated
  // config, and checkpoint metadata leave an existing listing usable.
  const secretSpecs = React.useMemo(
    () =>
      new Map(
        registry?.nodes.map((spec) => [
          JSON.stringify([spec.operator_id, spec.operator_version]),
          nodeSecretInputs(spec),
        ]),
      ),
    [registry],
  );
  const secretBindingKey = React.useMemo(() => {
    if (!activeGraph) return null;
    return JSON.stringify([
      activeGraph.id,
      activeGraph.graphId,
      liveHead?.room_epoch,
      activeGraph.nodes.flatMap((node) => {
        const identity = JSON.stringify([
          node.operator_id,
          node.operator_version,
        ]);
        const inputs = secretSpecs.get(identity);
        if (!inputs?.length) return [];
        return [
          [
            node.id,
            identity,
            inputs.map((input) => [
              input.name,
              nodeSecretDependencyRevision(input, node.config ?? {}),
            ]),
          ],
        ];
      }),
    ]);
  }, [activeGraph, liveHead?.room_epoch, secretSpecs]);

  React.useEffect(() => {
    if (
      !activeGraph ||
      !liveHead ||
      !registry ||
      secretBindingKey === null ||
      secretRefreshRef.current?.key === secretBindingKey
    ) {
      return;
    }
    const graph = graphFromProjectHead(liveHead, activeGraph.graphId);
    if (!graph) return;
    secretRefreshRef.current?.request.abort();
    const request = new AbortController();
    secretRefreshRef.current = { key: secretBindingKey, request };
    const bindingNodes = hydrateAuthoredGraphDocument(
      documentOfGraph(graph),
      registry,
    ).nodes.filter((node) => workflowNodeIsSupported(node.data));
    void refreshNodeSecretStatuses(activeGraph, bindingNodes, request.signal);
  }, [
    activeGraph,
    liveHead,
    refreshNodeSecretStatuses,
    registry,
    secretBindingKey,
  ]);

  /**
   * Show another Graph of this Project. The Project head already holds every
   * Graph, so switching is a projection of that head, not a fetch.
   */
  const openGraphInProject = React.useCallback(
    (head: CollaborativeHead, graphId: string): void => {
      openGraphIdRef.current = graphId;
      syncFromCollaborativeHead(head);
    },
    [syncFromCollaborativeHead],
  );

  const saveCurrentGraph = React.useCallback(
    async (nameOverride?: string): Promise<void> => {
      if (
        initialGraphId !== null ||
        approvedRouteGraphIdRef.current !== null ||
        creatingRef.current ||
        openedHead !== null ||
        isExecutionRunning() ||
        openingGraphId ||
        deletingGraphId
      )
        return;

      const draft = nameOverride?.trim()
        ? { ...currentDraft, name: nameOverride.trim() }
        : currentDraft;
      if (!draft.name) {
        setPersistenceError("Enter a graph name before saving.");
        return;
      }
      const documentGeneration = documentGenerationRef.current;
      creatingRef.current = true;
      setSaving(true);
      setPersistenceError(null);
      try {
        const head = await createProjectWithGraph(workspaceId, draft);
        if (!mountedRef.current) return;
        void refreshGraphSummaries(workspaceId);
        if (documentGenerationRef.current !== documentGeneration) return;

        const graph = openGraphOf(head, null);
        if (graph === null) return;
        approvedRouteGraphIdRef.current = head.project_id;
        openGraphIdRef.current = graph.id;
        setOpenGraphId(graph.id);
        setOpenedHead(head);
        // A first save normally confirms the existing canvas. Rebuild only if
        // the server normalized the draft.
        if (
          savedGraphFingerprint(
            createGraphDraft(documentOfGraph(graph), presentationOf(graph)),
          ) !== savedGraphFingerprint(draft)
        ) {
          replaceDocument(documentOfGraph(graph));
          replacePresentation(presentationOf(graph));
        }
        router.replace(workbenchGraphPath(workspaceSlug, head.project_id), {
          scroll: false,
        });
      } catch (error) {
        if (
          mountedRef.current &&
          documentGenerationRef.current === documentGeneration
        ) {
          setPersistenceError(
            error instanceof Error
              ? error.message
              : "The graph could not be saved.",
          );
        }
      } finally {
        creatingRef.current = false;
        if (mountedRef.current) setSaving(false);
      }
    },
    [
      currentDraft,
      deletingGraphId,
      initialGraphId,
      isExecutionRunning,
      openedHead,
      openingGraphId,
      refreshGraphSummaries,
      replaceDocument,
      replacePresentation,
      router,
      workspaceId,
      workspaceSlug,
    ],
  );

  const purgeLocalGraphState = React.useCallback(() => {
    documentGenerationRef.current += 1;
    openRequestRef.current?.abort();
    openGraphIdRef.current = null;
    setOpenGraphId(null);
    setOpenedHead(null);
    setPersistenceError(null);
    setGraphBrowserOpen(false);
    secretRefreshRef.current?.request.abort();
    secretRefreshRef.current = null;
    clearGraphSecretStatuses();
    clearPendingConnectionRoute();
    clearRunError();
    closeNodeLibrary();
    replaceDocument(
      {
        name: NEW_GRAPH_NAME,
        nodes: [],
        edges: [],
        origins: [],
        agents: [],
      },
      [],
    );
    replacePresentation(emptyGraphPresentation());
  }, [
    clearGraphSecretStatuses,
    clearPendingConnectionRoute,
    clearRunError,
    closeNodeLibrary,
    replaceDocument,
    replacePresentation,
  ]);

  const openSavedGraph = React.useCallback(
    async (graphId: string, confirmBeforeOpen = true, updateAddress = true) => {
      if (!registry) {
        setPersistenceError(
          "The live node registry must load before a graph can open.",
        );
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
            router.push(workbenchGraphPath(workspaceSlug, graphId), {
              scroll: false,
            });
          } catch (error) {
            approvedRouteGraphIdRef.current = null;
            setOpeningGraphId((current) =>
              current === graphId ? null : current,
            );
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
        // The route names a Project; the canvas shows one Graph of it.
        const head = await getCollaborativeHead(
          workspaceId,
          graphId,
          controller.signal,
        );
        const savedGraph = openGraphOf(head, openGraphIdRef.current);
        if (savedGraph === null) {
          setPersistenceError("This project holds no graph to open.");
          return;
        }
        openGraphIdRef.current = savedGraph.id;
        setOpenGraphId(savedGraph.id);
        if (
          controller.signal.aborted ||
          !mountedRef.current ||
          documentGenerationRef.current !== documentGeneration
        ) {
          return;
        }
        // The cards arrive with their Graph's node instances, not with a
        // revision: an open shows what is stored now, and the fingerprints on
        // those results are what say whether a card is still current.
        let storedResultWarning: string | null = null;
        let nodeRuns: RunNodeResult[] = [];
        try {
          const snapshot = await loadInstanceSnapshot(
            workspaceId,
            graphId,
            savedGraph.id,
            { signal: controller.signal },
          );
          nodeRuns = [...snapshot.results];
        } catch (error) {
          if (controller.signal.aborted) return;
          const message =
            error instanceof Error
              ? error.message
              : "Stored results could not be loaded.";
          storedResultWarning = `Graph opened without its stored results: ${message}`;
        }
        const hydrated = hydrateSavedGraph(savedGraph, registry, nodeRuns);
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

        const responseDocument = documentOfGraph(savedGraph);
        const responsePresentation = presentationOf(savedGraph);
        const openedNodes = hydrated.nodes.map((node) => ({
          ...node,
          data: attachNodeCallbacks(node.data),
        }));
        replaceDocument(responseDocument, openedNodes);
        replacePresentation(responsePresentation);
        setOpenedHead(head);
        clearPendingConnectionRoute();
        clearRunError();
        setPersistenceError(storedResultWarning);
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
            error instanceof Error
              ? error.message
              : "The graph could not be opened.",
          );
        }
      } finally {
        if (openRequestRef.current === controller) {
          openRequestRef.current = null;
          if (mountedRef.current) setOpeningGraphId(null);
        }
      }
    },
    [
      activeGraph?.id,
      attachNodeCallbacks,
      clearPendingConnectionRoute,
      clearRunError,
      closeNodeLibrary,
      confirmDiscard,
      currentFingerprint,
      registry,
      replaceDocument,
      replacePresentation,
      requestCanvasRefit,
      router,
      workspaceId,
      workspaceSlug,
    ],
  );

  React.useEffect(() => {
    if (!registry) return;

    const routeGraphId = initialGraphId ?? NEW_PROJECT_ROUTE_ID;
    const displayedGraphId = liveHead?.project_id ?? NEW_PROJECT_ROUTE_ID;
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

    const explicitlyApproved = approvedRouteGraphIdRef.current === routeGraphId;
    approvedRouteGraphIdRef.current = null;
    if (
      !explicitlyApproved &&
      !confirmDiscard("navigate with browser history")
    ) {
      approvedRouteGraphIdRef.current = displayedGraphId;
      router.push(workbenchGraphPath(workspaceSlug, displayedGraphId), {
        scroll: false,
      });
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
    liveHead?.project_id,
    confirmDiscard,
    initialGraphId,
    openSavedGraph,
    registry,
    router,
    showBlankGraph,
    workspaceSlug,
  ]);

  const removeSavedGraph = React.useCallback(
    async (graph: SavedGraphSummary) => {
      const deletingActiveGraph = activeGraph?.id === graph.id;
      const warning =
        deletingActiveGraph && isDirty
          ? `Delete “${graph.name}”? Its unsaved canvas changes will also be discarded.`
          : `Delete “${graph.name}”? This cannot be undone.`;
      if (!window.confirm(warning)) return;

      const deletingFingerprint = currentFingerprint;
      const documentGeneration = documentGenerationRef.current;
      setDeletingGraphId(graph.id);
      setPersistenceError(null);
      try {
        // The whole Project goes: its Graphs, its node instances, and the Run
        // history that produced them.
        const head =
          deletingActiveGraph && liveHead?.project_id === graph.id
            ? liveHead
            : await getCollaborativeHead(workspaceId, graph.id);
        await deleteProject(workspaceId, graph.id, {
          expectedRoomEpoch: head.room_epoch,
          expectedSequence: head.collaboration_sequence,
        });
        if (!mountedRef.current) return;
        void refreshGraphSummaries(workspaceId);
        void refreshNodeRegistry();
        if (documentGenerationRef.current !== documentGeneration) {
          return;
        }
        if (deletingActiveGraph) {
          if (currentFingerprintRef.current === deletingFingerprint) {
            showBlankGraph();
            approvedRouteGraphIdRef.current = NEW_PROJECT_ROUTE_ID;
            router.replace(
              workbenchGraphPath(workspaceSlug, NEW_PROJECT_ROUTE_ID),
              { scroll: false },
            );
          } else {
            setOpenedHead(null);
            secretRefreshRef.current?.request.abort();
            secretRefreshRef.current = null;
            clearGraphSecretStatuses();
            // The kept draft is a new graph, so the cards on it now belong to the draft
            // rather than to the graph that was just deleted. Read them as they are now:
            // this branch runs precisely because something changed during the delete, and
            // local editing is paused, so that change came in from the room.
            replacePresentation(presentationRef.current);
            setPersistenceError(
              "The saved graph was deleted. Changes made while deletion was in progress remain as an unsaved draft.",
            );
            approvedRouteGraphIdRef.current = NEW_PROJECT_ROUTE_ID;
            router.replace(
              workbenchGraphPath(workspaceSlug, NEW_PROJECT_ROUTE_ID),
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
            error instanceof Error
              ? error.message
              : "The graph could not be deleted.",
          );
        }
      } finally {
        if (mountedRef.current) setDeletingGraphId(null);
      }
    },
    [
      activeGraph,
      clearGraphSecretStatuses,
      currentFingerprint,
      isDirty,
      liveHead,
      refreshGraphSummaries,
      refreshNodeRegistry,
      replacePresentation,
      router,
      showBlankGraph,
      workspaceId,
      workspaceSlug,
    ],
  );

  const setGraphName = React.useCallback(
    (name: string) => {
      updateDocumentName(name);
      setPersistenceError(null);
    },
    [updateDocumentName],
  );
  const clearPersistenceError = React.useCallback(() => {
    setPersistenceError(null);
  }, []);
  const dismissPersistenceError = React.useCallback((message: string) => {
    setPersistenceError((current) => (current === message ? null : current));
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
  const savedGraphsError =
    savedGraphListError instanceof Error
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
    savedGraphs: savedGraphList?.projects ?? [],
    savedGraphsLoading,
    savedGraphsRefreshing,
    savedGraphsError,
    refreshSavedGraphs,
    requestNewGraph,
    saveCurrentGraph,
    openSavedGraph,
    removeSavedGraph,
    syncFromCollaborativeHead,
    openGraphId,
    openGraphInProject,
    purgeLocalGraphState,
  };
}
