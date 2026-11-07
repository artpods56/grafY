"use client";

import * as React from "react";
import { useRouter } from "next/navigation";

import {
  useProjectSummaryRefresh,
  useWorkspaceProjects,
} from "@/hooks/use-api";
import {
  checkpointProject,
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
import { ApiError } from "@/lib/api/client";
import {
  hydrateAuthoredGraphDocument,
  hydrateSavedGraph,
  savedGraphExecutionFingerprint,
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
    // The revision a save is compared against belongs to the Project head and
    // is shared by every Graph of the Project; there is no per-Graph counter.
    revision: head.collaboration_sequence,
    nodes: graph.document.nodes,
  };
}

/**
 * The authored body of one Graph: its name, its document, and the canvas layout
 * that sits beside it. The wire GraphDocument carries no name (a Graph's name
 * lives on the Graph, not its document) and omits `origins` when empty, while
 * the save draft and the dirtiness fingerprints expect both to be present — so
 * the projection closes those gaps instead of carrying `undefined` to callers.
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

/**
 * Write one Graph's document into its Project without a room: read the head,
 * submit the document as a command against it, then checkpoint the Project to
 * make it durable. A save that raced another writer surfaces as the same 409
 * the old expected-revision check raised.
 */
async function writeGraphDocument(
  workspaceId: string,
  projectId: string,
  graphId: string,
  draft: GraphSaveDraft,
  signal?: AbortSignal,
): Promise<CollaborativeHead> {
  const head = await getCollaborativeHead(workspaceId, projectId, signal);
  const submitted = await submitProjectCommand(workspaceId, projectId, {
    command_id: createUuid(),
    observed_sequence: head.collaboration_sequence,
    room_epoch: head.room_epoch,
    commands: [
      {
        kind: "in_graph",
        graph_id: graphId,
        // The authored draft carries no schema version: it is what the canvas
        // holds. The wire document is versioned, and the server reads this
        // command by that version.
        command: {
          kind: "replace_document",
          document: { ...draft.document, schema_version: 7 as const },
        },
      },
    ],
  });
  const checkpointed = await checkpointProject(workspaceId, projectId, {
    expected_room_epoch: submitted.head.room_epoch,
    expected_sequence: submitted.receipt.accepted_sequence,
  });
  return checkpointed.head;
}

/**
 * A first save: a new Project holding one Graph, then that Graph's document.
 * The Project is what the route names and the room binds to, so saving a new
 * canvas gives the canvas the Project's address.
 */
async function createProjectWithGraph(
  workspaceId: string,
  draft: GraphSaveDraft,
  signal?: AbortSignal,
): Promise<CollaborativeHead> {
  const graphId = createUuid();
  const project = await createProject(workspaceId, {
    name: draft.name,
    graph_id: graphId,
    graph_name: draft.name,
  });
  return writeGraphDocument(workspaceId, project.id, graphId, draft, signal);
}

/**
 * The canvas' place in the server: one Graph, inside one Project.
 *
 * `id` is the Project the route names and the room is bound to; `graphId` is
 * which Graph of that Project this canvas is showing. A Run is a demand inside
 * the Project and against one Graph, so a caller needs both, and `revision` is
 * the Project head's collaboration sequence — the number a save is compared
 * against, shared by every Graph of the Project.
 */
export interface ActiveSavedGraph {
  id: string;
  graphId: string;
  revision: number;
  nodes: readonly SavedGraphNode[];
}

/** The body a save sends for one Graph: its name and its whole document. */
/**
 * One Graph as a save carries it. This is the same unit the authoring model
 * builds and the room replays; the older name is kept because the persistence
 * adapters and the Workbench already speak it.
 */
export type GraphSaveDraft = GraphDraft;

export interface GraphRoomPersistenceResult {
  readonly checkpointHead: CollaborativeHead;
  readonly currentHead: CollaborativeHead;
}

/** Prefer room/command persistence when the graph room can accept edits. */
export interface GraphRoomPersistenceAdapter {
  readonly canPersist: boolean;
  /**
   * Keep the exact checkpoint separate from a newer effective room head.
   *
   * The Graph is named because a Project holds several of them and the room
   * command is addressed to one: `replace_document` without it would not say
   * which Graph this canvas just changed.
   */
  persistDocument: (
    draft: GraphSaveDraft,
    graphId: string,
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
  roomPersistence?: GraphRoomPersistenceAdapter | null;
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
  presentation = emptyGraphPresentation(),
  nodes,
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
  roomPersistence = null,
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
  const [activeGraph, setActiveGraph] = React.useState<ActiveSavedGraph | null>(
    null,
  );
  const [savedFingerprint, setSavedFingerprint] = React.useState<string | null>(
    null,
  );
  const [savedExecutionFingerprint, setSavedExecutionFingerprint] =
    React.useState<string | null>(null);
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
  const presentationRef = React.useRef(presentation);

  const currentDraft = React.useMemo(
    () => createGraphDraft(document, presentation),
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
  const rememberSavedDraft = React.useCallback((draft: GraphSaveDraft) => {
    setSavedFingerprint(savedGraphFingerprint(draft));
    setSavedExecutionFingerprint(savedGraphExecutionFingerprint(draft));
  }, []);

  React.useEffect(() => {
    currentFingerprintRef.current = currentFingerprint;
    presentationRef.current = presentation;
  }, [currentFingerprint, presentation]);

  const { isDirty, canMaterializeSavedGraph, persistenceOperationBusy } =
    savedGraphDirtiness({
      document,
      presentation,
      hasActiveGraph: activeGraph !== null,
      currentFingerprint,
      savedFingerprint,
      currentExecutionFingerprint,
      savedExecutionFingerprint,
      hasUnsyncedRoomEdits,
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
      // The canvas shows one Graph of this Project: keep the one it had, and
      // take the Project's first Graph when there was none.
      const openedGraph = openGraphOf(head, openGraphIdRef.current);
      if (openedGraph === null) return;
      openGraphIdRef.current = openedGraph.id;
      setOpenGraphId(openedGraph.id);
      const responseDocument = documentOfGraph(openedGraph);
      const responsePresentation = presentationOf(openedGraph);
      const nextActiveGraph = activeGraphFrom(head, openedGraph);
      const headIsCheckpointed =
        head.collaboration_sequence === head.checkpoint_sequence;
      approvedRouteGraphIdRef.current = head.project_id;
      if (headIsCheckpointed) {
        setActiveGraph(nextActiveGraph);
        rememberSavedDraft(
          createGraphDraft(responseDocument, responsePresentation),
        );
      } else {
        // The room journal is authoritative for the canvas but is not durable
        // until its current sequence has been checkpointed.
        setSavedFingerprint(null);
        setSavedExecutionFingerprint(null);
      }
      setPersistenceError(null);
      // Preserve the run overlays: a room sync is a document change, not a new
      // result. Stored results belong to node instances and survive until the
      // next run or Graph open says their fingerprint moved.
      replaceDocument(responseDocument);
      replacePresentation(responsePresentation);
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
    },
    [
      attachNodeCallbacks,
      nodes,
      refreshNodeSecretStatuses,
      registry,
      rememberSavedDraft,
      replaceDocument,
      replacePresentation,
    ],
  );

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
    async (nameOverride?: string) => {
      if (isExecutionRunning() || saving || openingGraphId || deletingGraphId)
        return;
      const submittedDraft = nameOverride?.trim()
        ? { ...currentDraft, name: nameOverride.trim() }
        : currentDraft;
      if (!submittedDraft.name) {
        setPersistenceError("Enter a graph name before saving.");
        return;
      }
      // A save is addressed to one Graph of one Project. Pairing the adapter
      // with that Graph here means every write below carries it, and a canvas
      // with no Graph falls to the draft path rather than guessing.
      const roomSave =
        activeGraph === null || roomPersistence === null
          ? null
          : { adapter: roomPersistence, graphId: activeGraph.graphId };
      if (roomSave !== null && !roomSave.adapter.canPersist) {
        setPersistenceError(
          "Graph synchronization is unavailable while the collaboration room connects or reconnects. Your canvas is unchanged; wait for synchronization to finish, then try saving again.",
        );
        return;
      }
      const documentGeneration = documentGenerationRef.current;
      setSaving(true);
      setPersistenceError(null);
      try {
        const persistenceResult = roomSave
          ? {
              kind: "collaborative" as const,
              result: await roomSave.adapter.persistDocument(
                submittedDraft,
                roomSave.graphId,
              ),
            }
          : {
              kind: "saved" as const,
              // Outside a room there is no journal to accept the document, so
              // the save writes it as a Project command and checkpoints the
              // Project to make it durable. A new canvas becomes a new Project
              // holding one Graph.
              head: activeGraph
                ? await writeGraphDocument(
                    workspaceId,
                    activeGraph.id,
                    activeGraph.graphId,
                    submittedDraft,
                  )
                : await createProjectWithGraph(workspaceId, submittedDraft),
            };
        if (!mountedRef.current) return;
        void refreshGraphSummaries(workspaceId);
        void refreshNodeRegistry();
        if (documentGenerationRef.current !== documentGeneration) {
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
        const savedHead = persistenceResult.head;
        const savedGraph = openGraphOf(savedHead, openGraphIdRef.current);
        if (savedGraph === null) return;
        openGraphIdRef.current = savedGraph.id;
        setOpenGraphId(savedGraph.id);
        const responseDocument = documentOfGraph(savedGraph);
        const responsePresentation = presentationOf(savedGraph);
        const nextActiveGraph = activeGraphFrom(savedHead, savedGraph);
        const createdGraph = activeGraph === null;
        if (createdGraph) {
          approvedRouteGraphIdRef.current = savedHead.project_id;
        }
        setActiveGraph(nextActiveGraph);
        rememberSavedDraft(
          createGraphDraft(responseDocument, responsePresentation),
        );
        replacePresentation(responsePresentation);
        if (createdGraph) {
          router.replace(
            workbenchGraphPath(workspaceSlug, savedHead.project_id),
            {
              scroll: false,
            },
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
            error instanceof Error
              ? error.message
              : "The graph could not be saved.",
          );
        }
      } finally {
        if (mountedRef.current) setSaving(false);
      }
    },
    [
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
    ],
  );

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
        const nextActiveGraph = activeGraphFrom(head, savedGraph);
        setActiveGraph(nextActiveGraph);
        rememberSavedDraft(
          createGraphDraft(responseDocument, responsePresentation),
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
      refreshNodeSecretStatuses,
      registry,
      rememberSavedDraft,
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
    const displayedGraphId = activeGraph?.id ?? NEW_PROJECT_ROUTE_ID;
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
    activeGraph?.id,
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
        await deleteProject(workspaceId, graph.id);
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
            setActiveGraph(null);
            setSavedFingerprint(null);
            setSavedExecutionFingerprint(null);
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
