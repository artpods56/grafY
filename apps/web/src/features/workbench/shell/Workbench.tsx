"use client";

import { duplicateArtifactViewers } from "../artifacts/artifact-viewer-edits";

import * as React from "react";
import useSWR, { useSWRConfig } from "swr";
import {
  artifactDownloadUrl,
  artifactInlineContentUrl,
  libraryFoldersApi,
  saveArtifactToLibrary,
  seedStarterSample,
  uploadFile,
  saveUploadedArtifactToLibrary,
  type PlacedLibraryItem,
} from "@/lib/api";
import { triggerArtifactDownload } from "../artifacts/artifact-download";
import {
  artifactDropGroups,
  libraryDragKind,
} from "../artifacts/side-panel/library-drag";
import * as stylex from "@stylexjs/stylex";
import { Toast } from "@base-ui/react/toast";
import {
  Bot,
  Circle,
  Copy,
  FilePlus2,
  History,
  Layers,
  LayoutGrid,
  Plus,
  Square,
  Trash2,
  Type,
} from "lucide-react";

import { ExecutionHistoryDrawer } from "../execution/ExecutionHistoryDrawer";
import { WorkbenchSidePanel } from "../artifacts/side-panel/WorkbenchSidePanel";
import {
  useWorkbenchSidePanel,
  type SidePanelViewId,
} from "../artifacts/side-panel/workbench-side-panel-state";
import { GraphRoomRecoveryNotice } from "../collaboration/GraphRoomRecoveryNotice";
import { CanvasCleanupNotice } from "./CanvasCleanupNotice";
import { CanvasCleanupPopover } from "./CanvasCleanupPopover";
import { EngineConnectNotice } from "./EngineConnectNotice";
import { GlobalIssueToastList, type GlobalIssue } from "./GlobalIssueToastList";
import { LinkedViewActivityToast } from "./LinkedViewActivityToast";
import { useServiceEnginePrompt } from "./use-service-engine-prompt";
import { ArtifactEditorDialog } from "../artifacts/editors/ArtifactEditorDialog";
import { SelectionLinkDialog } from "../artifacts/selection-links/SelectionLinkDialog";
import { SelectionLinksContext } from "../artifacts/selection-links/SelectionLinksContext";
import {
  selectionLinkCapability,
  type SelectionLinkCard,
} from "../artifacts/selection-links/selection-links-reducer";
import { useSelectionLinks } from "../artifacts/selection-links/useSelectionLinks";
import type { ArtifactEditorSession } from "../artifacts/editors/types";
import { ArtifactFolderDropDialog } from "../artifacts/ArtifactFolderDropDialog";
import { ConnectionRouteDialog } from "../authoring/ConnectionRouteDialog";
import { CanvasLabPanel } from "../cell-canvas/CanvasLabPanel";
import { EmptyCanvasStarter } from "./EmptyCanvasStarter";
import {
  advanceDraftSession,
  canvasPlacementTarget,
  mayPlaceOnInitiatingCanvas,
  type CanvasPlacementTarget,
} from "./initiatingGraphPlacement";
import { workbenchStyles as s } from "./Workbench.styles";
import { NodeSelector } from "../config-ui/NodeSelector";
import {
  CanvasContextMenu,
  type CanvasMenuActions,
  type CanvasMenuSelection,
} from "./canvas-menu/CanvasContextMenu";
import type { CanvasMenuRequest } from "./canvas-menu/canvas-menu-target";
import { useCanvasMenuTrigger } from "./canvas-menu/useCanvasMenuTrigger";
import {
  NodeMenuRegistry,
  NodeMenuRegistryContext,
} from "./node-menu-registry";
import {
  CellContextualNodeDiscovery,
  type ContextualDiscoverySession,
} from "../cell-canvas/ContextualNodeDiscovery";
import {
  CellPipeInspector,
  type CellInspectedPipe,
} from "../cell-canvas/CellPipeInspector";
import {
  NodeLivePreviewModal,
  type NodeLivePreviewTarget,
} from "../artifacts/NodeLivePreviewModal";
import type {
  ContextualCandidate,
  ContextualRouteChoice,
} from "../authoring/node-catalog";
import { Button, IconButton } from "@/components/ui/button";
import { phoneTouch } from "@/components/ui/touch-target";
import { createUuid } from "@/features/workbench/authoring/uuid";
import { artifactGroupingDisabledReason } from "../artifacts/artifact-grouping";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { usePublishWorkbenchChrome } from "./WorkbenchChromeContext";
import { renameProjectRemote } from "@/features/workspaces/graph-actions";
import type { Port, SavedGraphSummary } from "@/lib/api";
import {
  CanvasLabProvider,
  useCanvasLab,
} from "../cell-canvas/CanvasLabProvider";
import { validateConfig } from "../config-ui/config-schema";
import { DEFAULT_NODE_PLACEMENT_HEIGHT } from "../authoring/node-layout";
import { useNodeSecrets } from "../execution/useNodeSecrets";
import { useWorkbenchAuthoringReducer } from "../authoring/useWorkbenchAuthoringReducer";
import type { WorkbenchRoomCommandSync } from "../authoring/workbench-authoring-commands";
import {
  PresenceOverlay,
  toRoomRenameProjectCommand,
  type ProjectRoomPresenceStore,
} from "../collaboration";
import {
  useWorkbenchSyncReducer,
  type PresentationRoomSync,
} from "../collaboration/useWorkbenchSyncReducer";
import { savedGraphRunBlockedReason } from "../execution/useRunExecution";
import { useWorkbenchRunReducer } from "../execution/useWorkbenchRunReducer";
import {
  addNodeCommand,
  addEdgeCommand,
  nodeOverlaysFromNodes,
} from "../authoring/graph-document-adapter";
import {
  createAnnotationNode,
  type AnnotationKind,
} from "../authoring/annotations";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INPUT_HANDLE,
  ARTIFACT_VIEWER_NODE_TYPE,
  artifactViewersFromPresentation,
  presentationFromArtifactViewers,
  type ArtifactViewerEdge,
  type ArtifactViewerNode,
  type GraphPresentation,
} from "../artifacts/artifact-viewer";
import {
  ARTIFACT_CARD_OUTPUT_HANDLE,
  artifactCardConnectionValue,
  artifactCardOutputPort,
  outputReleasePlacesArtifactCard,
  artifactOriginConnections,
  resolveArtifactCardConnection,
} from "../artifacts/artifact-connections";
import {
  DEFAULT_ARTIFACT_CARD_WIDTH,
  DEFAULT_ARTIFACT_MAP_CARD_WIDTH,
  DEFAULT_ARTIFACT_TABLE_CARD_WIDTH,
  artifactCardContract,
  cardArtifactRefs,
  collectArtifactCardRefs,
  originBelongsToCard,
  selectionCollectsIntoSequence,
  isGeoMapArtifact,
  isTableArtifact,
} from "../artifacts/artifact-card";
import { formatArtifactTypeLabel } from "../artifacts/artifact-type-label";
import {
  hydrateAuthoredGraphDocument,
  savedGraphExecutionFingerprint,
} from "../authoring/saved-graph";
import { resolveGraphSemantics } from "../authoring/graph-semantics";
import { type ArtifactViewerActivity } from "../artifacts/artifact-interactions";
import {
  connectionRouteForPortSelection,
  connectionRouteMatchesSelection,
  connectionRouteSelection,
  connectionRoutesForPorts,
  portMetaArtifactType,
  type ConnectionRoute,
} from "../authoring/connection-routes";
import {
  COLLECTION_PORT,
  collectDisabledReason,
  collectionsWithoutSpare,
  isCollectionSpec,
  type CollectionSource,
} from "../authoring/collection";
import {
  createWorkflowNodeData,
  portArtifactTypeVariable,
  portMetaForPort,
  resolvedPortArtifactType,
  workflowNodeIsSupported,
  type CanvasFitViewOptions,
  type GraphConnection,
  type PortMeta,
  type WorkflowEdge,
  type WorkflowEdgeRouteOption,
  type WorkflowEdgeUpdate,
  type WorkflowNodeConfig,
  type XYPosition,
} from "../authoring/types";
import {
  orderFeedRoutes,
  preferredWholeFeedRoute,
  routesForHandleFeed,
} from "../authoring/connection-feeds";
import {
  artifactDropPayload,
  artifactDropCommands,
  artifactDropTargetFromRow,
  isArtifactDrop,
  readArtifactDrop,
  readArtifactDropFolder,
  readArtifactDropGroups,
  resolveArtifactDrop,
  type ArtifactDropPayload,
  type ArtifactDropTarget,
} from "../artifacts/artifact-drop";
import {
  collectionModeForConnection,
  isConnectionAccepted,
  resolveConnectionPortMeta,
  workflowEdgeRouteOption,
} from "../authoring/graph-authoring";
import {
  createGraphDraft,
  type AuthoredGraphDocument,
  type GraphCommand,
} from "../authoring/graph-document";
import { type WorkflowNode } from "../execution/execution-plan";
import {
  catalogNodeSpecs,
  downstreamCandidatesFromOutput,
  upstreamCandidatesFromInput,
} from "../authoring/node-catalog";
import { workbenchProjectPath } from "../routes";
import { useNodeRegistry } from "@/hooks/use-api";
import {
  artifactDropRowAt,
  artifactDropTargetFitsNode,
  canvasAtPoint,
} from "../artifacts/artifact-drop-hit-test";
import { GraphSwitcher } from "../authoring/GraphSwitcher";
import {
  useArtifactViewerCommands,
  useArtifactViewerState,
} from "./workbench-artifact-viewers";
import {
  useCanvasSelection,
  withoutPresentationSelection,
} from "../authoring/workbench-canvas-selection";
import {
  CellCanvas,
  type CellCanvasHandle,
  type CellCanvasProps,
} from "../cell-canvas/CellCanvas";
import { CanvasZoomControls } from "../cell-canvas/CanvasZoomControls";
import {
  annotationHexFromToken,
  graphCommandsFromCellResizeForDocument,
} from "../cell-canvas/cell-document-adapter";
import {
  CELL_SIZE,
  cellToWorldOrigin,
  portWorldCenter,
  type WorldPoint,
} from "../cell-canvas/cell-model";
import {
  DEFAULT_CELL_CLEANUP_PARAMS,
  activeRunForNode,
  buildCleanupUndoPlan,
  buildWorkbenchCellScene,
  cellConnectionToWorkbenchConnection,
  cellRemotePeersFromParticipants,
  mergeCleanupUndoSnapshots,
  partitionCellMoves,
  partitionCellRemovals,
  partitionCellSelection,
  planWorkbenchCanvasCleanup,
  resolveCellPortEndpoint,
  type CellCleanupParams,
  type CellCleanupUndoSnapshot,
  type CellResolvedConnection,
} from "./workbench-cell-canvas";
import { useNodeCommands } from "../authoring/workbench-node-commands";
import {
  artifactCardDropPositions,
  useArtifactCardCommands,
} from "./workbench-artifact-cards";
import {
  GRAPH_INPUT_OPERATOR_ID,
  GRAPH_OUTPUT_OPERATOR_ID,
  newNodeKind,
  nextBoundaryName,
  registryWithProjectGraphs,
} from "../authoring/project-graphs";
import {
  type ArtifactRef,
  type GraphDefinition,
  type NodeSpec,
  type RunEdgeCollectionMode,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";

/** What a Project with no Graph in it shows where the canvas would be. */
const emptyProjectStyles = stylex.create({
  panel: {
    position: "absolute",
    zIndex: 20,
    inset: 0,
    display: "flex",
    flexDirection: "column",
    alignItems: "center",
    justifyContent: "center",
    gap: "8px",
    padding: "24px",
    textAlign: "center",
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
  },
  title: { fontSize: "15px", fontWeight: 600 },
  body: {
    fontSize: "13px",
    lineHeight: 1.5,
    maxWidth: "380px",
    color: tokens.colorMuted,
  },
});

const WORKBENCH_FIT_VIEW: CanvasFitViewOptions = {
  padding: 0.25,
  maxZoom: 0.88,
};

interface WorkbenchProps {
  workspaceId: string;
  workspaceSlug: string;
  /**
   * The Project this address names, or null on the `/projects/new` route, where
   * the canvas holds a draft until the first save makes it a Project. The Graphs
   * the person can open are inside the Project, so the address never names one.
   */
  initialProjectId: string | null;
}

interface ActiveArtifactViewerActivity {
  activity: ArtifactViewerActivity;
  revision: number;
}

interface PresenceAwareCellCanvasProps extends Omit<
  CellCanvasProps,
  "remotePeers"
> {
  presenceStore: ProjectRoomPresenceStore;
  localSessionId: string | null;
  graphId: string | null;
}

/** Subscribes to room presence without re-rendering the workbench. */
function PresenceAwareCellCanvas({
  presenceStore,
  localSessionId,
  graphId,
  ...canvasProps
}: PresenceAwareCellCanvasProps) {
  const participants = React.useSyncExternalStore(
    presenceStore.subscribe,
    () => presenceStore.getParticipants(),
    () => presenceStore.getParticipants(),
  );
  const remotePeers = React.useMemo(
    () =>
      cellRemotePeersFromParticipants(participants, localSessionId, graphId),
    [graphId, localSessionId, participants],
  );
  return (
    <CellCanvas
      {...canvasProps}
      remotePeers={remotePeers}
      remoteDragScope={graphId}
    />
  );
}

function isInlineEditableTiffRegions(ref: ArtifactRef): boolean {
  return (
    ref.schema_version === 1 &&
    (ref.artifact_type === "ocr.tiff_text_regions" ||
      ref.artifact_type === "ocr.tiff_recognized_text")
  );
}

export function Workbench(props: WorkbenchProps) {
  return (
    <React.Suspense fallback={null}>
      <CanvasLabProvider>
        <WorkbenchBody {...props} />
      </CanvasLabProvider>
    </React.Suspense>
  );
}

function WorkbenchBody({
  workspaceId,
  workspaceSlug,
  initialProjectId,
}: WorkbenchProps) {
  // The address names a Project; the Graphs live inside it.
  const projectId = initialProjectId;
  const { mutate: mutateCache } = useSWRConfig();
  const [toastManager] = React.useState(() => Toast.createToastManager());
  const {
    data: apiRegistry,
    error: registryError,
    mutate: refreshNodeRegistry,
  } = useNodeRegistry(workspaceId);
  /**
   * What the open Project adds to the node catalog: its boundary operators and
   * one call node per sibling Graph. Nothing here is a registered operator, so
   * the registry the canvas hydrates against is the API's plus this. It is held
   * as state because the Project head is read further down, and it only moves
   * when the catalog entries move, not on every accepted command.
   */
  const [projectCatalog, setProjectCatalog] = React.useState<{
    key: string;
    graphs: readonly GraphDefinition[];
    openGraphId: string | null;
  }>({ key: "", graphs: [], openGraphId: null });
  const registry = React.useMemo(
    () =>
      apiRegistry
        ? registryWithProjectGraphs(
            apiRegistry,
            projectCatalog.graphs,
            projectCatalog.openGraphId,
          )
        : apiRegistry,
    [apiRegistry, projectCatalog],
  );
  const {
    enabled: canvasLabEnabled,
    settings: cellLook,
    routing: cellRouting,
    panelOpen: labPanelOpen,
    setPanelOpen: setLabPanelOpen,
  } = useCanvasLab();
  const { workspace } = useWorkspaceContext();
  const canCreateProject = workspace.capabilities.includes("create_project");
  const managePacksHref = workspace.capabilities.includes("manage_packs")
    ? `/workspaces/${encodeURIComponent(workspaceSlug)}/settings#tool-packs`
    : undefined;
  const canManageSecrets = workspace.capabilities.includes("manage_secrets");
  const canEditProject = workspace.capabilities.includes("edit_project");
  const canStartRun = workspace.capabilities.includes("start_run");
  const canCancelRun = workspace.capabilities.includes("cancel_run");
  const canDeleteProject = workspace.capabilities.includes("delete_project");
  const [executionRunning, setExecutionRunning] = React.useState(false);
  const executionRunningRef = React.useRef<() => boolean>(() => false);
  const isExecutionRunning = React.useCallback(
    () => executionRunningRef.current(),
    [],
  );
  const localAuthoringEnabledRef = React.useRef(
    projectId === null && canCreateProject,
  );
  const draftSessionRef = React.useRef(1);
  const placementProjectIdRef = React.useRef<string | null>(projectId);
  const canvasTargetRef = React.useRef<CanvasPlacementTarget | null>(
    projectId === null ? { kind: "draft", sessionId: "1" } : null,
  );
  const localAuthoringBlockedMessageRef = React.useRef(
    "Editing is unavailable until this Project is synchronized.",
  );
  const roomCommandSyncRef = React.useRef<WorkbenchRoomCommandSync>({
    submitLocal: () => undefined,
  });
  const presentationRoomSyncRef = React.useRef<PresentationRoomSync>({
    submitReplace: () => undefined,
    submitMove: () => undefined,
    submitMoveAnnotations: () => undefined,
  });
  const closeGraphBrowserRef = React.useRef(() => {});
  const onCloseGraphBrowser = React.useCallback(
    () => closeGraphBrowserRef.current(),
    [],
  );
  const [cleanupPanelOpen, setCleanupPanelOpen] = React.useState(false);
  const [cleanupParams, setCleanupParams] = React.useState<CellCleanupParams>(
    DEFAULT_CELL_CLEANUP_PARAMS,
  );
  const cleanupWrapRef = React.useRef<HTMLDivElement | null>(null);
  const closeGridPanel = React.useCallback(() => {
    setLabPanelOpen(false);
    setCleanupPanelOpen(false);
  }, [setCleanupPanelOpen, setLabPanelOpen]);
  const runErrorBridgeRef = React.useRef<{
    set: React.Dispatch<React.SetStateAction<string | null>>;
    clear: () => void;
  }>({ set: () => {}, clear: () => {} });
  const setRunError = React.useCallback<
    React.Dispatch<React.SetStateAction<string | null>>
  >((error) => runErrorBridgeRef.current.set(error), []);
  const clearRunError = React.useCallback(
    () => runErrorBridgeRef.current.clear(),
    [],
  );

  const [artifactViewers, setArtifactViewers, artifactViewersRef] =
    useArtifactViewerState({
      nodes: [],
      edges: [],
      bindings: [],
      annotations: [],
    });
  const authoring = useWorkbenchAuthoringReducer<
    ContextualDiscoverySession,
    CanvasMenuRequest
  >({
    localAuthoringEnabledRef,
    localAuthoringBlockedMessageRef,
    nodeRegistry: registry ?? null,
    roomCommandSyncRef,
    setArtifactViewers,
    setRunError,
    onCloseGraphBrowser,
    onCloseGridPanel: closeGridPanel,
  });
  const {
    authoredDocument,
    authoredDocumentRef,
    nodeOverlays,
    selectedNodeIdSet,
    selectedEdgeIdSet,
    selectedAgentIds,
    positionOverrides,
    setSelectedNodeIdSet,
    setSelectedEdgeIdSet,
    setSelectedAgentIds,
    applyNodesSnapshot,
    replaceDocument: replaceAuthoredDocument,
    applyAuthoringCommands,
    canvasUpload,
    setCanvasUpload,
    collapsedAppendices,
    toggleAppendix,
    configSections,
    setConfigSection,
    fitRevision,
    libraryOpen,
    libraryInsertAt,
    setLibraryOpen,
    toggleLibrary,
    shapesMenuOpen,
    setShapesMenuOpen,
    toggleShapesMenu,
    canvasMenu,
    openContextMenu,
    closeContextMenu,
    contextualDiscovery,
    openContextualDiscovery,
    closeContextualDiscovery,
    inspectedPipe,
    toggleInspectedPipe,
    closeInspectedPipe,
    pruneInspectedPipes,
    closeCanvasPopovers,
    pendingConnectionRoute,
    setPendingConnectionRoute,
    pendingFolderDrop,
    setPendingFolderDrop,
    requestCanvasRefit,
  } = authoring;
  const [samplePending, setSamplePending] = React.useState(false);
  const [artifactEditor, setArtifactEditor] =
    React.useState<ArtifactEditorSession | null>(null);
  const [inlineEditingCardId, setInlineEditingCardId] = React.useState<
    string | null
  >(null);
  const graphSemantics = React.useMemo(
    () => (registry ? resolveGraphSemantics(authoredDocument, registry) : null),
    [authoredDocument, registry],
  );
  const hydratedDocument = React.useMemo(
    () =>
      registry
        ? hydrateAuthoredGraphDocument(
            authoredDocument,
            registry,
            [],
            graphSemantics ?? undefined,
          )
        : { nodes: [], edges: [] },
    [authoredDocument, graphSemantics, registry],
  );
  const nodesRef = React.useRef<WorkflowNode[]>([]);
  const edgesRef = React.useRef<WorkflowEdge[]>([]);
  const nodes = React.useMemo<WorkflowNode[]>(
    () =>
      hydratedDocument.nodes.map((node) => {
        return {
          ...node,
          position: positionOverrides[node.id] ?? node.position,
          selected: selectedNodeIdSet.has(node.id),
          data: {
            ...node.data,
            ...(nodeOverlays[node.id] ?? {}),
            mappedInputPorts:
              graphSemantics?.nodes.get(node.id)?.mappedInputPorts ?? [],
          },
        };
      }),
    [
      graphSemantics,
      hydratedDocument.nodes,
      nodeOverlays,
      positionOverrides,
      selectedNodeIdSet,
    ],
  );
  const edges = React.useMemo<WorkflowEdge[]>(
    () =>
      hydratedDocument.edges.map((edge) => ({
        ...edge,
        selected: selectedEdgeIdSet.has(edge.id),
      })),
    [hydratedDocument.edges, selectedEdgeIdSet],
  );
  React.useLayoutEffect(() => {
    nodesRef.current = nodes;
    edgesRef.current = edges;
  }, [edges, nodes]);
  const setNodes = React.useCallback<
    React.Dispatch<React.SetStateAction<WorkflowNode[]>>
  >(
    (action) => {
      const currentNodes = nodesRef.current;
      const nextNodes =
        typeof action === "function" ? action(currentNodes) : action;
      nodesRef.current = nextNodes;
      const positionOverrides: Record<string, XYPosition> = {};
      const authoredNodesById = new Map(
        authoredDocumentRef.current.nodes.map((node) => [node.id, node]),
      );
      for (const node of nextNodes) {
        const authoredNode = authoredNodesById.get(node.id);
        if (
          authoredNode &&
          (authoredNode.position.x !== node.position.x ||
            authoredNode.position.y !== node.position.y)
        ) {
          positionOverrides[node.id] = { ...node.position };
        }
      }
      applyNodesSnapshot({
        selectedNodeIds: new Set(
          nextNodes.filter((node) => node.selected).map((node) => node.id),
        ),
        positionOverrides,
        nodeOverlays: nodeOverlaysFromNodes(nextNodes),
      });
    },
    [applyNodesSnapshot, authoredDocumentRef],
  );
  // The canvas draws nodes, cards, and annotations out of three stores, and one
  // gesture can hold any mix of them. Anything that moves what is held goes
  // through here so no layer is left holding what the person already let go.
  const canvasSelection = useCanvasSelection({
    setSelectedAgentIds,
    setArtifactViewers,
    setSelectedEdgeIdSet,
    setSelectedNodeIdSet,
  });
  const [nodeMenus] = React.useState(() => new NodeMenuRegistry());
  const canvasSectionRef = React.useRef<HTMLElement>(null);
  const [artifactViewerActivities, setArtifactViewerActivities] =
    React.useState<Record<string, ActiveArtifactViewerActivity>>({});
  const artifactViewerActivityRevisionRef = React.useRef(0);
  const {
    nodeSecretStatuses,
    credentials,
    credentialRowsLoaded,
    refreshCredentialRows,
    refreshCredentials,
    selectCredential,
    verifyCredential,
    refreshNodeSecretStatuses,
    applyConfiguredNodeSecret,
    removeConfiguredNodeSecret,
    clearGraphSecretStatuses,
    forgetNodeSecretStatuses,
  } = useNodeSecrets(workspaceId, nodes);
  const [cellCanvasHandle, setCellCanvasHandle] =
    React.useState<CellCanvasHandle | null>(null);
  const [viewportZoom, setViewportZoom] = React.useState(1);
  const canvasReady = cellCanvasHandle !== null;
  const screenToCanvasPoint = React.useCallback(
    (point: XYPosition) =>
      cellCanvasHandle?.viewportHandle.screenToWorld(point.x, point.y),
    [cellCanvasHandle],
  );
  const fitCanvasView = React.useCallback(
    ({ nodes, padding, maxZoom }: CanvasFitViewOptions) => {
      if (nodes) {
        cellCanvasHandle?.fitCards(
          nodes.map(({ id }) => id),
          padding,
          maxZoom,
        );
      } else {
        cellCanvasHandle?.fitGraph(padding, maxZoom);
      }
    },
    [cellCanvasHandle],
  );
  const sidePanel = useWorkbenchSidePanel();
  const executionHistoryReturnFocusRef = React.useRef<HTMLElement | null>(null);
  const updateConfigPatch = React.useCallback(
    (nodeId: string, patch: WorkflowNodeConfig) => {
      applyAuthoringCommands(
        Object.entries(patch).map(([field, value]) => ({
          kind: "update_node_configuration",
          node_id: nodeId,
          field,
          value,
        })),
      );
    },
    [applyAuthoringCommands],
  );
  const updateConfig = React.useCallback(
    (nodeId: string, name: string, value: unknown) =>
      updateConfigPatch(nodeId, { [name]: value }),
    [updateConfigPatch],
  );

  const {
    commitArtifactViewers,
    removeAnnotation,
    removeArtifactViewer,
    removeArtifactViewerBinding,
    saveArtifactViewerBinding,
    updateAnnotationColor,
    updateAnnotationLayout,
    updateArtifactViewerActivity,
    updateArtifactViewerEdge,
    updateArtifactViewerLayout,
  } = useArtifactViewerCommands({
    artifactViewers,
    artifactViewersRef,
    artifactViewerActivityRevisionRef,
    applyAuthoringCommands,
    authoredDocumentRef,
    localAuthoringBlockedMessageRef,
    localAuthoringEnabledRef,
    presentationRoomSyncRef,
    setArtifactViewerActivities,
    setArtifactViewers,
    setRunError,
  });

  const { addNodeInputPlug, removeNodeInputPlug } = useNodeCommands({
    applyAuthoringCommands,
    edges,
    forgetNodeSecretStatuses,
    nodes,
    setPendingConnectionRoute,
    setRunError,
  });

  const openProjectInNewTab = React.useCallback(() => {
    if (!projectId) return;
    // Internal route: workbenchProjectPath() returns a same-origin path from encoded params.
    // pi-lens-ignore: no-open-redirect
    window.open(
      workbenchProjectPath(workspaceSlug, projectId),
      "_blank",
      "noopener,noreferrer",
    );
  }, [projectId, workspaceSlug]);

  const replaceDocument = React.useCallback(
    (
      nextDocument: AuthoredGraphDocument,
      overlayNodes?: readonly WorkflowNode[],
    ) => {
      const nextNodeIds = new Set(nextDocument.nodes.map((node) => node.id));
      // Run updates can read the replacement before React commits the canvas.
      nodesRef.current =
        overlayNodes === undefined
          ? nodesRef.current.filter((node) => nextNodeIds.has(node.id))
          : [...overlayNodes];
      edgesRef.current = [];
      replaceAuthoredDocument(
        nextDocument,
        overlayNodes === undefined
          ? undefined
          : nodeOverlaysFromNodes(overlayNodes),
      );
    },
    [replaceAuthoredDocument],
  );
  const replacePresentation = React.useCallback(
    (presentation: GraphPresentation) => {
      setArtifactViewers(artifactViewersFromPresentation(presentation));
    },
    [setArtifactViewers],
  );
  /**
   * The artifact-card layer is replaced whole whenever the active graph changes, and both
   * the canvas and the save body read this one value, so they cannot disagree about whose
   * cards are current and a graph opened earlier in the session cannot ride into this
   * save. A presentation that still reached the request holding references the document
   * dropped is filtered in `createGraphDraft`.
   */
  const activeArtifactViewers = artifactViewers;
  const sharedPresentation = React.useMemo(
    () => presentationFromArtifactViewers(activeArtifactViewers),
    [activeArtifactViewers],
  );
  const currentExecutionFingerprint = React.useMemo(
    () =>
      savedGraphExecutionFingerprint(
        createGraphDraft(authoredDocument, sharedPresentation),
      ),
    [authoredDocument, sharedPresentation],
  );
  const updateDocumentName = React.useCallback(
    (name: string) => {
      applyAuthoringCommands([{ kind: "rename_graph", name }]);
    },
    [applyAuthoringCommands],
  );
  const selectedNodeIds = React.useMemo(
    () => [
      ...nodes.flatMap((node) => (node.selected ? [node.id] : [])),
      ...selectedAgentIds,
      ...artifactViewers.nodes.flatMap((node) =>
        node.selected ? [node.id] : [],
      ),
      ...artifactViewers.annotations.flatMap((node) =>
        node.selected ? [node.id] : [],
      ),
    ],
    [
      artifactViewers.annotations,
      artifactViewers.nodes,

      nodes,
      selectedAgentIds,
    ],
  );
  const selectedNodeIdsRef = React.useRef(selectedNodeIds);
  React.useLayoutEffect(() => {
    selectedNodeIdsRef.current = selectedNodeIds;
  }, [selectedNodeIds]);
  const nodeTitles = React.useMemo(
    () =>
      Object.fromEntries(nodes.map((node) => [node.id, node.data.spec.title])),
    [nodes],
  );
  const clearPendingConnectionRoute = React.useCallback(() => {
    setPendingConnectionRoute(null);
  }, [setPendingConnectionRoute]);
  const closeNodeLibrary = React.useCallback(() => {
    setLibraryOpen(false);
  }, [setLibraryOpen]);

  const sync = useWorkbenchSyncReducer({
    workspaceId,
    workspaceSlug,
    projectId,
    registry,
    document: authoredDocument,
    presentation: sharedPresentation,
    executionRunning,
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
    canEditProject,
    canCreateProject,
    canvasReady,
    selectedNodeIds,
    screenToCanvasPoint,
    cellToWorldOrigin,
    roomCommandSyncRef,
    presentationRoomSyncRef,
  });
  const {
    activeGraph,
    graphName,
    setGraphName,
    isDirty,
    saving,
    openingGraphId,
    deletingGraphId,
    persistenceError,
    dismissPersistenceError,
    closeGraphBrowser,
    refreshSavedGraphs,
    saveCurrentGraph,
    removeSavedGraph,
    projectRoom,
    openGraphId,
    projectReadiness,
    projectEditsTrusted,
    projectHasNoGraph,
    localAuthoringEnabled,
    localAuthoringBlockedMessage,
    callTrail,
    addProjectGraph,
    renameProjectGraph,
    removeProjectGraph,
    openProjectGraph,
    openCall,
    backFromCall,
    onCanvasPointerMove,
    onCanvasPointerLeave,
    onDragCardsProgress,
    unsyncedRoomEdits,
  } = sync;
  const canSubmitRoomCommands = projectRoom.canSubmitCommands;
  const submitRoomBatch = projectRoom.submitCommands;
  const savedProjectName = projectRoom.head?.name ?? "";
  const canRunSavedGraph =
    activeGraph !== null && canStartRun && projectEditsTrusted && !isDirty;
  const runBlockedReason = savedGraphRunBlockedReason({
    activeGraph: activeGraph !== null,
    canStartRun,
    projectEditsTrusted,
    hasUnsyncedRoomEdits: unsyncedRoomEdits,
    isDirty,
  });

  const run = useWorkbenchRunReducer({
    workspaceId,
    registryAvailable: Boolean(registry),
    nodes,
    edges,
    origins: authoredDocument.origins,
    projectId,
    activeGraph,
    currentExecutionFingerprint,
    canRunSavedGraph,
    runBlockedReason,
    nodeSecretStatuses,
    roomConnected: projectRoom.status === "ready",
    roomActiveRuns: projectRoom.activeRuns,
    roomRunsRevision: projectRoom.runsRevision,
    roomInstancesRevision: projectRoom.instancesRevision,
    roomInstances: projectRoom.instances,
    openGraphId,
    callTrail,
    setNodes,
    authoringError: authoring.authoringError,
    onClearAuthoringError: authoring.clearAuthoringError,
    onDismissAuthoringError: authoring.dismissAuthoringError,
    onCloseGraphBrowser,
  });
  const {
    running,
    announcement: executionAnnouncement,
    runError,
    dismissRunError,
    runWorkflow,
    nodeInstanceStates,
    openGraphRuns,
    cancellingRunIds,
    cancelGraphRun,
    executionHistoryTarget,
    openExecutionHistory,
    closeExecutionHistory,
  } = run;

  if (sync.projectCatalog.key !== projectCatalog.key) {
    setProjectCatalog(sync.projectCatalog);
  }
  if (running !== executionRunning) {
    setExecutionRunning(running);
  }
  React.useLayoutEffect(() => {
    localAuthoringEnabledRef.current = localAuthoringEnabled;
    const draftSession = advanceDraftSession(
      placementProjectIdRef.current,
      projectId,
      draftSessionRef.current,
    );
    draftSessionRef.current = draftSession;
    placementProjectIdRef.current = projectId;
    canvasTargetRef.current = canvasPlacementTarget({
      projectId,
      graphId: openGraphId,
      draftSessionId: String(draftSession),
    });
    localAuthoringBlockedMessageRef.current = localAuthoringBlockedMessage;
    executionRunningRef.current = run.isExecutionRunning;
    closeGraphBrowserRef.current = closeGraphBrowser;
    runErrorBridgeRef.current = {
      set: run.setRunError,
      clear: run.clearRunError,
    };
  }, [
    closeGraphBrowser,
    localAuthoringBlockedMessage,
    localAuthoringEnabled,
    openGraphId,
    projectId,
    run.clearRunError,
    run.isExecutionRunning,
    run.setRunError,
  ]);

  React.useEffect(() => {
    // Refit when the graph or canvas changes, leaving the camera alone during edits.
    if (!canvasReady) return;
    const frame = window.requestAnimationFrame(() =>
      fitCanvasView(WORKBENCH_FIT_VIEW),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [canvasReady, fitCanvasView, fitRevision]);

  /** The call node a person could step into: exactly one node is selected and it is a call. */
  const selectedCall = React.useMemo(() => {
    const chosen = nodes.filter((node) => node.selected);
    const [only] = chosen;
    if (chosen.length !== 1 || !only) return null;
    if (newNodeKind(only.data.spec) !== "call") return null;
    return {
      nodeId: only.id,
      calleeGraphId: only.data.spec.operator_id,
      calleeName: only.data.spec.title,
    };
  }, [nodes]);

  const selectedNodeCount = selectedNodeIds.length;
  // What the selection permits is a walk over the graph, and a drag re-renders
  // this body sixty times a second without moving the selection. Each derivation
  // below is cached against what it actually reads, so a gesture costs a
  // dependency check instead of a validation pass over every node.
  const selectedNodesAreRunnable = React.useMemo(
    () =>
      nodes.every(
        (node) =>
          !node.selected ||
          (workflowNodeIsSupported(node.data) &&
            validateConfig(node.data.spec.config_schema, node.data.config)
              .length === 0),
      ),
    [nodes],
  );
  const selectedWorkflowCount = React.useMemo(
    () => nodes.filter((node) => node.selected).length,
    [nodes],
  );
  const selectedViewerCount = React.useMemo(
    () => artifactViewers.nodes.filter((node) => node.selected).length,
    [artifactViewers.nodes],
  );
  const selectedArtifactCards = React.useMemo(
    () =>
      artifactViewers.nodes.flatMap((node) => {
        if (!node.selected) return [];
        const value = artifactCardConnectionValue(
          node,
          artifactViewers.edges,
          nodes,
        );
        return value ? [{ node, value }] : [];
      }),
    [artifactViewers.edges, artifactViewers.nodes, nodes],
  );
  const collectedArtifactRefs = React.useMemo(
    () =>
      collectArtifactCardRefs(
        selectedArtifactCards.map(({ node, value }) => ({
          position: node.position,
          value,
        })),
      ),
    [selectedArtifactCards],
  );
  const selectedViewerCards = React.useMemo(
    () => artifactViewers.nodes.filter((node) => node.selected),
    [artifactViewers.nodes],
  );
  const collectCardValues = React.useMemo(
    () =>
      Object.fromEntries(
        selectedArtifactCards.map(({ node, value }) => [node.id, value]),
      ),
    [selectedArtifactCards],
  );
  const collectsIntoSequence = React.useMemo(
    () =>
      selectionCollectsIntoSequence(
        selectedArtifactCards.map(({ value }) => value),
      ),
    [selectedArtifactCards],
  );
  const groupingDisabledReason = React.useMemo(
    () =>
      selectedNodeCount !== selectedViewerCards.length
        ? "Select only artifacts to collect."
        : selectedViewerCards.length > 0 &&
            selectedArtifactCards.length !== selectedViewerCards.length
          ? "Run the producing node first, so its artifact is known."
          : artifactGroupingDisabledReason({
              cards: selectedArtifactCards.map(({ node }) => node),
              state: artifactViewers,
              origins: authoredDocument.origins,
              values: collectCardValues,
              allowProducerFeeds: true,
            }),
    [
      artifactViewers,
      authoredDocument.origins,
      collectCardValues,
      selectedArtifactCards,
      selectedNodeCount,
      selectedViewerCards,
    ],
  );
  // With the collection operator available, "Collect" makes a collection: it
  // can gather Library cards and cards on a node's output alike.
  const collectSpec = React.useMemo(
    () => registry?.nodes.find((spec) => isCollectionSpec(spec)) ?? null,
    [registry],
  );
  const selectedCollectionSources = React.useMemo(
    () =>
      artifactViewers.nodes.flatMap((node): CollectionSource[] => {
        if (!node.selected) return [];
        const feed = artifactViewers.edges.find(
          (edge) =>
            edge.type === ARTIFACT_VIEWER_EDGE_TYPE &&
            edge.target === node.id &&
            edge.targetHandle === ARTIFACT_VIEWER_INPUT_HANDLE,
        );
        if (feed && node.data.mode === "artifact") {
          return [
            {
              kind: "output",
              cardId: node.id,
              position: node.position,
              sourceNodeId: feed.source,
              sourcePortName: feed.data?.sourcePortName ?? "",
            },
          ];
        }
        if (!feed && node.data.artifactRef) {
          return [
            {
              kind: "library",
              cardId: node.id,
              position: node.position,
              value: node.data.artifactRef,
            },
          ];
        }
        return [];
      }),
    [artifactViewers.edges, artifactViewers.nodes],
  );
  const collectionDisabledReason = (() => {
    if (!collectSpec) return null;
    if (selectedNodeCount !== selectedCollectionSources.length) {
      return "Select only artifacts to collect.";
    }
    const cardIds = new Set(
      selectedCollectionSources.map((source) => source.cardId),
    );
    const carried = authoredDocument.origins.some((origin) =>
      selectedCollectionSources.some(
        (source) =>
          source.kind === "library" &&
          originBelongsToCard(origin, source.cardId, source.value),
      ),
    );
    if (
      carried ||
      artifactViewers.bindings.some(
        (binding) =>
          cardIds.has(binding.sourceViewerId) ||
          cardIds.has(binding.targetViewerId),
      )
    ) {
      return "Disconnect what these artifacts feed before collecting them.";
    }
    return collectDisabledReason(selectedCollectionSources, nodes);
  })();

  const runSelectionBusy = !registry || running || selectedWorkflowCount === 0;
  const runSelectedDisabled =
    !canRunSavedGraph || runSelectionBusy || !selectedNodesAreRunnable;
  const globalIssues = React.useMemo<GlobalIssue[]>(() => {
    const issues: GlobalIssue[] = [];
    if (registryError) {
      issues.push({
        id: "registry",
        title: "Registry",
        message:
          registryError instanceof Error
            ? registryError.message
            : "The live node registry is unavailable.",
      });
    }
    if (persistenceError) {
      issues.push({
        // The id is the toast's, whose owner still names this channel "graph".
        id: "graph",
        title: "Save",
        message: persistenceError,
      });
    }
    if (runError) {
      issues.push({
        id: "run",
        title: "Run",
        message: runError,
      });
    }
    return issues;
  }, [persistenceError, registryError, runError]);
  const dismissGlobalIssue = React.useCallback(
    (issue: GlobalIssue) => {
      if (issue.id === "graph") {
        dismissPersistenceError(issue.message);
      }
      if (issue.id === "run") {
        dismissRunError(issue.message);
      }
    },
    [dismissPersistenceError, dismissRunError],
  );
  const artifactOriginCanvasEdges = React.useMemo(
    () =>
      artifactOriginConnections(
        activeArtifactViewers.nodes,
        activeArtifactViewers.edges,
        nodes,
        authoredDocument.origins,
        graphSemantics,
      ).map((edge) => ({
        ...edge,
        selected: selectedEdgeIdSet.has(edge.id),
      })),
    [
      activeArtifactViewers.nodes,
      activeArtifactViewers.edges,
      nodes,
      authoredDocument.origins,
      graphSemantics,
      selectedEdgeIdSet,
    ],
  );

  const updateEdge = React.useCallback(
    (edgeId: string, update: WorkflowEdgeUpdate) => {
      const changedEdge = edges.find((edge) => edge.id === edgeId);
      if (!changedEdge) return;
      applyAuthoringCommands([
        {
          kind: "update_edge",
          edge_id: edgeId,
          update: {
            enabled: update.enabled ?? changedEdge.data?.enabled ?? true,
            collection_mode:
              update.collectionMode ??
              changedEdge.data?.collectionMode ??
              "direct",
            projection: update.route
              ? update.route.projection
                ? { path: [...update.route.projection.path] }
                : null
              : changedEdge.data?.projection
                ? { path: [...changedEdge.data.projection.path] }
                : null,
            conversion_path: update.route
              ? update.route.conversionPath.map((conversion) => ({
                  id: conversion.id,
                  version: conversion.version,
                }))
              : (changedEdge.data?.conversionPath ?? []).map((conversion) => ({
                  id: conversion.id,
                  version: conversion.version,
                })),
          },
        },
      ]);
    },
    [applyAuthoringCommands, edges],
  );

  const {
    addArtifactCard,
    addArtifactCards,
    canMergeArtifactCards,
    collectSelectedArtifacts,
    duplicateArtifactCard,
    extractArtifactCardItem,
    insertArtifactCardIntoSequence,
    mergeArtifactCardRun,
    mergeArtifactCards,
    removeArtifactCardItem,
    reorderArtifactCardItem,
    replaceArtifactCardRef,
    ungroupArtifacts,
  } = useArtifactCardCommands({
    applyAuthoringCommands,
    artifactViewers,
    authoredDocumentRef,
    commitArtifactViewers,
    collection: {
      spec: collectSpec,
      disabledReason: collectionDisabledReason,
      sources: selectedCollectionSources,
      nodes,
      edges,
      onCollected: (collectionId) => {
        canvasSelection.selectOnly({ nodeIds: [collectionId] });
      },
    },
    groupingDisabledReason,
    localAuthoringEnabled,
    resolveCardValue: (node) =>
      artifactCardConnectionValue(node, artifactViewers.edges, nodes),
    selection: canvasSelection,
  });

  // A collection always keeps one spare plug, the one its next member lands
  // on. Filling it (a wire, a card, a Library drop) is followed by a new spare.
  React.useEffect(() => {
    if (!localAuthoringEnabled) return;
    const missing = collectionsWithoutSpare(
      nodes,
      edges,
      authoredDocument.origins,
    );
    if (!missing.length) return;
    applyAuthoringCommands(
      missing.map((nodeId) => ({
        kind: "add_input_plug" as const,
        node_id: nodeId,
        plug: { id: createUuid(), port: COLLECTION_PORT },
      })),
    );
  }, [
    applyAuthoringCommands,
    authoredDocument.origins,
    edges,
    localAuthoringEnabled,
    nodes,
  ]);

  /** One card per group, laid side by side from `point` in one commit. */
  const placeArtifactGroups = React.useCallback(
    (groups: readonly ArtifactDropPayload[], point: XYPosition) => {
      const positions = artifactCardDropPositions(
        point,
        groups.map((group) => ({
          artifactCount: cardArtifactRefs(group.value).length,
          width: isTableArtifact(group.value)
            ? DEFAULT_ARTIFACT_TABLE_CARD_WIDTH
            : isGeoMapArtifact(group.value)
              ? DEFAULT_ARTIFACT_MAP_CARD_WIDTH
              : DEFAULT_ARTIFACT_CARD_WIDTH,
        })),
      );
      addArtifactCards(
        groups.map((group, index) => ({
          value: group.value,
          position: positions[index] ?? point,
        })),
      );
    },
    [addArtifactCards],
  );

  /** Upload files through the Library, then lay them on the canvas as one drop. */
  const uploadFilesOntoCanvas = React.useCallback(
    async (files: readonly File[], point: XYPosition) => {
      if (files.length === 0 || !localAuthoringEnabledRef.current) return;
      const initiating = canvasTargetRef.current;
      const items: PlacedLibraryItem[] = [];
      try {
        for (const [index, file] of files.entries()) {
          setCanvasUpload(`Uploading ${index + 1} of ${files.length}…`);
          const uploaded = await uploadFile(workspaceId, file);
          if (!uploaded.artifact_id) {
            throw new Error(
              `Upload of ${file.name} completed without an artifact.`,
            );
          }
          const item = await saveUploadedArtifactToLibrary(workspaceId, {
            artifact_id: uploaded.artifact_id,
            original_filename: uploaded.filename || file.name,
          });
          items.push({ ...item, folder_id: null });
          void mutateCache(["library-tree", workspaceId]);
        }
      } catch (error) {
        setRunError(error instanceof Error ? error.message : "Upload failed.");
      } finally {
        if (
          items.length &&
          mayPlaceOnInitiatingCanvas({
            authoringEnabled: localAuthoringEnabledRef.current,
            active: canvasTargetRef.current,
            initiating,
          })
        ) {
          placeArtifactGroups(
            artifactDropGroups(items).map(artifactDropPayload),
            point,
          );
        }
        setCanvasUpload(null);
      }
    },
    [
      mutateCache,
      placeArtifactGroups,
      setCanvasUpload,
      setRunError,
      workspaceId,
    ],
  );

  /**
   * Drop the carried artifacts on empty canvas: one card per group they form.
   *
   * A Library drag of several artifacts arrives as one group per artifact type,
   * so a same-type selection lands as one sequence card and a mixed selection as
   * several cards laid side by side. A drop that asks for more than one card and
   * lands on empty canvas is still one drop: one commit places all of them. A
   * whole folder holding several types is the exception: it asks first, because
   * the user dragged one thing and may want only one of its groups.
   */
  const dropArtifactOnCanvas = React.useCallback(
    (event: DragEvent | React.DragEvent<HTMLElement>) => {
      if (!event.dataTransfer || !canvasAtPoint(event.clientX, event.clientY)) {
        return;
      }
      const groups = readArtifactDropGroups(event.dataTransfer);
      if (groups.length === 0) return;
      event.preventDefault();
      const point = screenToCanvasPoint({
        x: event.clientX,
        y: event.clientY,
      }) ?? { x: 0, y: 0 };
      const folder = readArtifactDropFolder(event.dataTransfer);
      if (folder && groups.length > 1) {
        setPendingFolderDrop({
          drop: { folderName: folder.name, groups, canPlaceAll: true },
          destination: { kind: "canvas", point },
        });
        return;
      }
      placeArtifactGroups(groups, point);
    },
    [screenToCanvasPoint, placeArtifactGroups, setPendingFolderDrop],
  );

  /**
   * The card owns the order its artifacts are passed in, and an origin carries
   * what it was handed, so a reorder rewrites the origin beside the card.
   */
  const dragOverArtifactDrop = React.useCallback(
    (event: DragEvent | React.DragEvent<HTMLElement>) => {
      if (!event.dataTransfer) return;
      if (libraryDragKind(event.dataTransfer) === "upload") {
        if (
          canEditProject &&
          localAuthoringEnabled &&
          canvasAtPoint(event.clientX, event.clientY)
        ) {
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
        }
        return;
      }
      if (!isArtifactDrop(event.dataTransfer)) return;
      if (artifactDropRowAt(event.clientX, event.clientY)) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        return;
      }
      if (!canvasAtPoint(event.clientX, event.clientY)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    },
    [canEditProject, localAuthoringEnabled],
  );

  /** Put one artifact value on an input row, or say why the input refuses it. */
  const placeArtifactOnInput = React.useCallback(
    (payload: ArtifactDropPayload, target: ArtifactDropTarget) => {
      // Read the graph at drop time: a drag captures its state when it starts,
      // so acting on that snapshot would miss an earlier drop.
      const node = nodesRef.current.find(
        (candidate) => candidate.id === target.nodeId,
      );
      if (!node || !workflowNodeIsSupported(node.data)) return;
      const port = node.data.spec.inputs.find(
        (candidate) => candidate.name === target.portName,
      );
      if (!port || !artifactDropTargetFitsNode(target, node.data, port)) return;
      const commands = artifactDropCommands(
        payload,
        target,
        port,
        node.data.artifactTypeBindings,
        {
          edges: edgesRef.current,
          origins: authoredDocumentRef.current.origins,
          conversions: registry?.artifact_conversions ?? [],
        },
      );
      if (commands?.length) {
        applyAuthoringCommands(commands);
        return;
      }
      setRunError(
        `That input will not take ${artifactCardContract(payload.value, registry?.artifact_types ?? null)}: the port refuses the type, or two conversions tie.`,
      );
    },
    [
      applyAuthoringCommands,
      authoredDocumentRef,
      registry?.artifact_conversions,
      registry?.artifact_types,
      setRunError,
    ],
  );

  const dropArtifact = React.useCallback(
    (event: DragEvent | React.DragEvent<HTMLElement>) => {
      if (!event.dataTransfer) return;
      if (libraryDragKind(event.dataTransfer) === "upload") {
        if (
          !canEditProject ||
          !localAuthoringEnabled ||
          !canvasAtPoint(event.clientX, event.clientY)
        )
          return;
        const point = screenToCanvasPoint({
          x: event.clientX,
          y: event.clientY,
        });
        if (!point) return;
        event.preventDefault();
        void uploadFilesOntoCanvas(Array.from(event.dataTransfer.files), point);
        return;
      }
      if (!isArtifactDrop(event.dataTransfer)) return;
      const row = artifactDropRowAt(event.clientX, event.clientY);
      if (!row) {
        dropArtifactOnCanvas(event);
        return;
      }
      event.preventDefault();
      const groups = readArtifactDropGroups(event.dataTransfer);
      const target = artifactDropTargetFromRow(row);
      // One input row takes one artifact value. A whole folder of several types
      // asks which group to place; any other drag of several types has no
      // honest reading here — filling the row with the first group and silently
      // dropping the rest would lose what the user picked up — so it is refused
      // and said.
      if (groups.length > 1) {
        const folder = readArtifactDropFolder(event.dataTransfer);
        if (folder && target) {
          setPendingFolderDrop({
            drop: { folderName: folder.name, groups, canPlaceAll: false },
            destination: { kind: "input", target },
          });
          return;
        }
        setRunError(
          `Drop one artifact type at a time onto an input: this drag carries ${groups.length} kinds of artifact.`,
        );
        return;
      }
      const payload = readArtifactDrop(event.dataTransfer);
      if (!payload || !target) return;
      placeArtifactOnInput(payload, target);
    },
    [
      canEditProject,
      localAuthoringEnabled,
      dropArtifactOnCanvas,
      placeArtifactOnInput,
      screenToCanvasPoint,
      setPendingFolderDrop,
      setRunError,
      uploadFilesOntoCanvas,
    ],
  );

  const placeFolderDropGroups = React.useCallback(
    (groups: readonly ArtifactDropPayload[]) => {
      const pending = pendingFolderDrop;
      setPendingFolderDrop(null);
      if (!pending) return;
      if (pending.destination.kind === "canvas") {
        placeArtifactGroups(groups, pending.destination.point);
        return;
      }
      if (groups.length === 1) {
        const [only] = groups;
        if (only) placeArtifactOnInput(only, pending.destination.target);
      }
    },
    [
      pendingFolderDrop,
      placeArtifactGroups,
      placeArtifactOnInput,
      setPendingFolderDrop,
    ],
  );

  React.useEffect(() => {
    const onDragOver = (event: DragEvent) => dragOverArtifactDrop(event);
    const onDrop = (event: DragEvent) => dropArtifact(event);
    document.addEventListener("dragover", onDragOver);
    document.addEventListener("drop", onDrop);
    return () => {
      document.removeEventListener("dragover", onDragOver);
      document.removeEventListener("drop", onDrop);
    };
  }, [dragOverArtifactDrop, dropArtifact]);

  const addWorkflowEdge = React.useCallback(
    (
      connection: GraphConnection,
      collectionMode: RunEdgeCollectionMode,
      route: ConnectionRoute,
    ): string | null => {
      let newlyBoundNodeId: string | null = null;
      const binding = route.artifactTypeBinding;
      if (binding) {
        const nodeId =
          binding.endpoint === "source" ? connection.source : connection.target;
        const portName =
          binding.endpoint === "source"
            ? connection.sourcePort
            : connection.targetPort;
        const node = nodes.find((candidate) => candidate.id === nodeId);
        const port =
          binding.endpoint === "source"
            ? node?.data.spec.outputs.find(
                (candidate) => candidate.name === portName,
              )
            : node?.data.spec.inputs.find(
                (candidate) => candidate.name === portName,
              );
        const existingBinding =
          node?.data.artifactTypeBindings[binding.variable];
        if (
          !node ||
          !port ||
          portArtifactTypeVariable(port) !== binding.variable ||
          (existingBinding &&
            (existingBinding.id !== binding.artifactType.id ||
              existingBinding.schema_version !==
                binding.artifactType.schema_version))
        ) {
          return null;
        }
        if (!existingBinding) newlyBoundNodeId = nodeId;
      }

      const edgeId = `edge-${createUuid()}`;
      const selection = connectionRouteSelection(route);
      const commands: GraphCommand[] = [];
      if (binding && newlyBoundNodeId) {
        // The port and pipe are both derived from the same document update.
        commands.push({
          kind: "bind_artifact_type",
          node_id: newlyBoundNodeId,
          variable: binding.variable,
          artifact_type: binding.artifactType,
        });
      }
      commands.push(
        addEdgeCommand(
          connection,
          {
            enabled: true,
            collectionMode,
            projection: selection.projection
              ? { path: [...selection.projection.path] }
              : undefined,
            conversionPath: selection.conversionPath.map((conversion) => ({
              id: conversion.id,
              version: conversion.version,
            })),
          },
          edgeId,
        ),
      );
      applyAuthoringCommands(commands);
      clearRunError();
      return edgeId;
    },
    [applyAuthoringCommands, clearRunError, nodes],
  );

  const isValidConnection = React.useCallback(
    (candidate: CellResolvedConnection) => {
      if (candidate.kind === "artifact-card") {
        const resolved = resolveArtifactCardConnection(
          candidate,
          activeArtifactViewers.nodes,
          activeArtifactViewers.edges,
          nodes,
          registry?.artifact_conversions ?? [],
        );
        return resolved !== null;
      }
      if (candidate.kind === "artifact-viewer") {
        const sourceNode = nodes.find(
          (node) => node.id === candidate.sourceNodeId,
        );
        return Boolean(
          activeArtifactViewers.nodes.some(
            (node) => node.id === candidate.targetViewerId,
          ) &&
          sourceNode?.data.spec.outputs.some(
            (port) => port.name === candidate.sourcePort,
          ),
        );
      }
      return isConnectionAccepted(
        candidate,
        nodes,
        edges,
        registry?.artifact_types ?? [],
        registry?.artifact_conversions ?? [],
        null,
        authoredDocument.origins,
      );
    },
    [
      authoredDocument.origins,
      activeArtifactViewers.nodes,
      activeArtifactViewers.edges,
      edges,
      nodes,
      registry?.artifact_conversions,
      registry?.artifact_types,
    ],
  );

  const onConnect = React.useCallback(
    (connection: CellResolvedConnection) => {
      if (!isValidConnection(connection)) return;
      if (connection.kind === "artifact-card") {
        const resolved = resolveArtifactCardConnection(
          connection,
          activeArtifactViewers.nodes,
          activeArtifactViewers.edges,
          nodes,
          registry?.artifact_conversions ?? [],
        );
        if (!resolved) {
          return;
        }
        const commands = artifactDropCommands(
          resolved.payload,
          resolved.target,
          resolved.port,
          resolved.bindings,
          {
            edges,
            origins: authoredDocumentRef.current.origins,
            conversions: registry?.artifact_conversions ?? [],
          },
          connection.sourceCardId,
        );
        if (!commands) return;
        if (resolved.binding) {
          commands.unshift({
            kind: "bind_artifact_type",
            node_id: resolved.target.nodeId,
            variable: resolved.binding.variable,
            artifact_type: resolved.binding.artifactType,
          });
        }
        applyAuthoringCommands(commands);
        clearRunError();
        setPendingConnectionRoute(null);
        return;
      }
      if (connection.kind === "artifact-viewer") {
        const edge: ArtifactViewerEdge = {
          id: `artifact-viewer-edge-${createUuid()}`,
          type: ARTIFACT_VIEWER_EDGE_TYPE,
          source: connection.sourceNodeId,
          target: connection.targetViewerId,
          targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
          data: { sourcePortName: connection.sourcePort },
        };
        commitArtifactViewers((current) => ({
          ...current,
          edges: [
            ...current.edges.filter(
              (candidate) => candidate.target !== connection.targetViewerId,
            ),
            edge,
          ],
        }));
        setPendingConnectionRoute(null);
        return;
      }
      const collectionMode = collectionModeForConnection(
        connection,
        nodes,
        edges,
        authoredDocument.origins,
      );
      if (!collectionMode) return;

      const endpoints = resolveConnectionPortMeta(
        connection,
        nodes,
        edges,
        authoredDocument.origins,
      );
      if (!endpoints) return;

      const allCandidates = connectionRoutesForPorts(
        endpoints.source,
        endpoints.target,
        registry?.artifact_types ?? [],
        registry?.artifact_conversions ?? [],
      );
      const candidates = orderFeedRoutes(
        routesForHandleFeed(allCandidates, endpoints.source.feed),
      );
      const preferred = preferredWholeFeedRoute(candidates);
      if (!preferred) return;

      // Connect first with the whole output (or sole route), then offer fields.
      const edgeId = addWorkflowEdge(connection, collectionMode, preferred);
      if (!edgeId || candidates.length <= 1) return;

      const sourceNode = nodes.find((node) => node.id === connection.source);
      const targetNode = nodes.find((node) => node.id === connection.target);
      if (!sourceNode || !targetNode) return;
      const sourceArtifactType = portMetaArtifactType(endpoints.source);
      const targetArtifactType = portMetaArtifactType(endpoints.target);

      const sourcePort = sourceNode.data.spec.outputs.find(
        (port) => port.name === endpoints.source.portName,
      );
      const targetPort = targetNode.data.spec.inputs.find(
        (port) => port.name === endpoints.target.portName,
      );
      setPendingConnectionRoute({
        connection,
        collectionMode,
        candidates,
        refineEdgeId: edgeId,
        preferredProjectionPath:
          endpoints.source.feed?.kind === "projection"
            ? endpoints.source.feed.path
            : undefined,
        source: {
          nodeTitle: sourceNode.data.spec.title,
          portName: sourcePort?.title ?? endpoints.source.portName,
          artifactType: sourceArtifactType
            ? formatArtifactTypeLabel(
                sourceArtifactType,
                registry?.artifact_types ?? null,
              )
            : `Any artifact · ${endpoints.source.artifactTypeVariable}`,
        },
        target: {
          nodeTitle: targetNode.data.spec.title,
          portName: targetPort?.title ?? endpoints.target.portName,
          artifactType: targetArtifactType
            ? formatArtifactTypeLabel(
                targetArtifactType,
                registry?.artifact_types ?? null,
              )
            : `Any artifact · ${endpoints.target.artifactTypeVariable}`,
        },
      });
    },
    [
      authoredDocument.origins,
      authoredDocumentRef,
      activeArtifactViewers.nodes,
      activeArtifactViewers.edges,
      applyAuthoringCommands,
      clearRunError,
      addWorkflowEdge,
      commitArtifactViewers,
      edges,
      isValidConnection,
      nodes,
      registry?.artifact_conversions,
      registry?.artifact_types,
      setPendingConnectionRoute,
    ],
  );

  /**
   * The middle of the canvas, in flow coordinates: where new things land when
   * nothing says where. The canvas, not the window — the rail and the side
   * panel take the window's left.
   */
  const canvasCenter = React.useCallback(
    (fallback: { x: number; y: number }) => {
      const box = canvasSectionRef.current?.getBoundingClientRect();
      const client =
        box && box.width > 0
          ? { x: box.left + box.width / 2, y: box.top + box.height / 2 }
          : { x: window.innerWidth / 2, y: window.innerHeight / 2 };
      return screenToCanvasPoint(client) ?? fallback;
    },
    [screenToCanvasPoint],
  );

  const openCreateArtifact = React.useCallback(
    (position?: { x: number; y: number }) => {
      if (!localAuthoringEnabled) return;
      setArtifactEditor({
        kind: "create",
        position: position ?? canvasCenter({ x: 80, y: 80 }),
      });
    },
    [canvasCenter, localAuthoringEnabled, setArtifactEditor],
  );

  const openEditArtifact = React.useCallback(
    (cardId: string) => {
      const card = artifactViewers.nodes.find((node) => node.id === cardId);
      const refs = cardArtifactRefs(card?.data.artifactRef);
      const sourceRef = refs.length === 1 ? refs[0] : undefined;
      if (!sourceRef) return;
      if (isInlineEditableTiffRegions(sourceRef)) {
        setInlineEditingCardId(cardId);
      } else {
        setArtifactEditor({ kind: "edit", cardId, sourceRef });
      }
    },
    [artifactViewers.nodes, setArtifactEditor, setInlineEditingCardId],
  );

  const openDuplicateArtifact = React.useCallback(
    (cardId: string) => {
      const card = artifactViewers.nodes.find((node) => node.id === cardId);
      if (!card) return;
      const value =
        artifactCardConnectionValue(card, artifactViewers.edges, nodes) ??
        card.data.artifactRef;
      const refs = cardArtifactRefs(value);
      const sourceRef = refs.length === 1 ? refs[0] : undefined;
      if (!sourceRef) return;
      if (isInlineEditableTiffRegions(sourceRef)) {
        const newCardId = duplicateArtifactCard(cardId, sourceRef);
        if (newCardId) setInlineEditingCardId(newCardId);
      } else {
        setArtifactEditor({
          kind: "duplicate",
          sourceCardId: cardId,
          sourceRef,
        });
      }
    },
    [
      artifactViewers.edges,
      artifactViewers.nodes,
      duplicateArtifactCard,
      nodes,
      setArtifactEditor,
      setInlineEditingCardId,
    ],
  );

  const handleInlineArtifactSaved = React.useCallback(
    (cardId: string, nextRef: ArtifactRef) => {
      replaceArtifactCardRef(cardId, nextRef);
      setInlineEditingCardId((current) =>
        current === cardId ? null : current,
      );
    },
    [replaceArtifactCardRef, setInlineEditingCardId],
  );

  const handleArtifactEditorSaved = React.useCallback(
    (ref: ArtifactRef, session: ArtifactEditorSession) => {
      if (session.kind === "create") {
        addArtifactCard(ref, session.position);
      } else if (session.kind === "edit") {
        replaceArtifactCardRef(session.cardId, ref);
      } else {
        duplicateArtifactCard(session.sourceCardId, ref);
      }
      setArtifactEditor(null);
    },
    [
      addArtifactCard,
      duplicateArtifactCard,
      replaceArtifactCardRef,
      setArtifactEditor,
    ],
  );

  const placeStarterSample = React.useCallback(async () => {
    if (samplePending || !localAuthoringEnabledRef.current) return;
    const initiating = canvasTargetRef.current;
    setSamplePending(true);
    try {
      const item = await seedStarterSample(workspaceId);
      void mutateCache(["library-tree", workspaceId]);
      if (
        mayPlaceOnInitiatingCanvas({
          authoringEnabled: localAuthoringEnabledRef.current,
          active: canvasTargetRef.current,
          initiating,
        })
      ) {
        placeArtifactGroups(
          artifactDropGroups([
            { ...item, folder_id: item.folder_id ?? null },
          ]).map(artifactDropPayload),
          canvasCenter({ x: 80, y: 80 }),
        );
      }
    } catch (error) {
      setRunError(
        error instanceof Error
          ? error.message
          : "The sample page could not be added.",
      );
    } finally {
      setSamplePending(false);
    }
  }, [
    canvasCenter,
    mutateCache,
    placeArtifactGroups,
    samplePending,
    setRunError,
    setSamplePending,
    workspaceId,
  ]);

  /**
   * The data a freshly placed catalog node starts with. A Graph's boundary node
   * is addressed by its public name, which must be unique among its siblings, so
   * a new one takes the next free name instead of one every other would share.
   */
  const projectGraphs = projectRoom.head?.document.graphs;
  const newCatalogNodeData = React.useCallback(
    (spec: NodeSpec) => {
      const data = createWorkflowNodeData(spec);
      const graph = projectGraphs?.find(
        (candidate) => candidate.id === openGraphId,
      );
      if (graph && spec.operator_id === GRAPH_INPUT_OPERATOR_ID) {
        data.config = {
          ...data.config,
          public_name: nextBoundaryName(graph, "input"),
        };
      }
      if (graph && spec.operator_id === GRAPH_OUTPUT_OPERATOR_ID) {
        data.config = {
          ...data.config,
          public_name: nextBoundaryName(graph, "output"),
        };
      }
      return data;
    },
    [openGraphId, projectGraphs],
  );

  const {
    notice: engineConnectNotice,
    dismissNotice: dismissEngineConnectNotice,
    undoNotice: undoEngineConnect,
    noteLocalPlacement,
    noteContinuedNode,
    pickEngine,
    chooseProvider,
    closePrompt,
  } = useServiceEnginePrompt({
    workspaceId,
    projectId,
    graphId: openGraphId,
    canEdit: canEditProject && localAuthoringEnabled,
    running,
    documentRef: authoredDocumentRef,
    nodes,
    savedNodes: activeGraph?.nodes ?? null,
    edges,
    origins: authoredDocument.origins,
    registry,
    credentials,
    credentialRowsLoaded,
    refreshCredentialRows,
    nodeSecretStatuses,
    canEditProject,
    applyAuthoringCommands,
    selectNode: (nodeId) => {
      canvasSelection.selectOnly({ nodeIds: [nodeId] });
    },
    refreshCredentials,
    openDiscovery: openContextualDiscovery,
    closeDiscovery: closeContextualDiscovery,
    viewportHandle: cellCanvasHandle?.viewportHandle ?? null,
    onRejected: setRunError,
    clearError: clearRunError,
  });

  /** Adds a node with its corner at `at`, else centred on the canvas. */
  const addCatalogNode = React.useCallback(
    (spec: NodeSpec, at?: XYPosition, promptForEngine = true) => {
      const id = `node-${createUuid()}`;
      const place = at ?? libraryInsertAt;
      const center = canvasCenter({ x: 600, y: 280 });
      const position = place ?? { x: center.x - 140, y: center.y - 110 };
      const data = newCatalogNodeData(spec);
      applyAuthoringCommands([addNodeCommand(id, data, position)]);
      canvasSelection.selectOnly({ nodeIds: [id] });
      if (promptForEngine) {
        noteLocalPlacement({
          id,
          position,
          spec: data.spec,
          satisfiedInputs: [],
        });
      }
      setLibraryOpen(false);
      closeContextualDiscovery();
    },
    [
      applyAuthoringCommands,
      canvasCenter,
      canvasSelection,
      closeContextualDiscovery,
      libraryInsertAt,
      newCatalogNodeData,
      noteLocalPlacement,
      setLibraryOpen,
    ],
  );

  const placeOutputCard = React.useCallback(
    (
      sourceNodeId: string,
      portName: string,
      flowPosition: XYPosition,
      avoidDuplicate = false,
      avoidWorkflowEdges = false,
    ) => {
      const viewerId = `artifact-viewer-${createUuid()}`;
      const link: ArtifactViewerEdge = {
        id: `artifact-viewer-edge-${createUuid()}`,
        type: ARTIFACT_VIEWER_EDGE_TYPE,
        source: sourceNodeId,
        target: viewerId,
        targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
        data: { sourcePortName: portName },
      };
      const placedCard: ArtifactViewerNode = {
        id: viewerId,
        type: ARTIFACT_VIEWER_NODE_TYPE,
        position: flowPosition,
        selected: true,
        data: {
          layout: null,
          mode: "artifact",
          artifactRef: null,
        },
      };
      const committed = commitArtifactViewers((current) => {
        if (
          avoidDuplicate &&
          (current.edges.some((edge) => edge.source === sourceNodeId) ||
            (avoidWorkflowEdges &&
              edgesRef.current.some(
                (edge) =>
                  edge.source === sourceNodeId && edge.data?.enabled !== false,
              )))
        )
          return current;
        const cleared = withoutPresentationSelection(current);
        return {
          ...cleared,
          nodes: [...cleared.nodes, placedCard],
          edges: [...cleared.edges, link],
        };
      });
      // The card the person just pulled out is what they hold next, not the
      // node it came from.
      if (committed) canvasSelection.clearWorkflowSelection();
      setLibraryOpen(false);
      closeContextualDiscovery();
    },
    [
      canvasSelection,
      closeContextualDiscovery,
      commitArtifactViewers,
      setLibraryOpen,
    ],
  );

  const handleConnectionDrop = React.useCallback(
    ({
      fromNode,
      port,
      portName,
      plugId,
      meta,
      clientPoint,
      flowPosition,
    }: {
      fromNode: WorkflowNode;
      port: Port;
      portName: string;
      plugId?: string;
      meta: PortMeta;
      clientPoint: XYPosition;
      flowPosition: XYPosition;
    }) => {
      if (!registry) return;
      const upstream = meta.direction === "input";
      const materializedOutput =
        !upstream && fromNode.data.run?.status === "succeeded"
          ? fromNode.data.run.outputs.find(
              (output) =>
                output.port === port.name && output.artifacts.length > 0,
            )
          : null;
      if (
        !upstream &&
        outputReleasePlacesArtifactCard({
          onCanvas: canvasAtPoint(clientPoint.x, clientPoint.y),
          // The released handle is the ball on screen. A mapped output is a
          // sequence ball even when the stored port shape is still one.
          portShape: meta.shape,
          hasMaterializedArtifacts: Boolean(materializedOutput),
        })
      ) {
        const viewerId = `artifact-viewer-${createUuid()}`;
        const link: ArtifactViewerEdge = {
          id: `artifact-viewer-edge-${createUuid()}`,
          type: ARTIFACT_VIEWER_EDGE_TYPE,
          source: fromNode.id,
          target: viewerId,
          targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
          data: { sourcePortName: port.name },
        };
        const placedCard: ArtifactViewerNode = {
          id: viewerId,
          type: ARTIFACT_VIEWER_NODE_TYPE,
          position: flowPosition,
          selected: true,
          data: {
            layout: null,
            mode: "artifact",
            artifactRef: null,
          },
        };
        const committed = commitArtifactViewers((current) => {
          const cleared = withoutPresentationSelection(current);
          return {
            ...cleared,
            nodes: [...cleared.nodes, placedCard],
            edges: [...cleared.edges, link],
          };
        });
        // The card the person just pulled out is what they hold next, not the
        // node it came from.
        if (committed) canvasSelection.clearWorkflowSelection();
        setLibraryOpen(false);
        return;
      }

      const catalogNodes = catalogNodeSpecs(registry, openGraphId);
      const candidates =
        port.direction === "input"
          ? upstreamCandidatesFromInput({
              targetPort: { ...port, direction: "input" },
              targetMeta: meta,
              registry,
              nodes: catalogNodes,
            })
          : downstreamCandidatesFromOutput({
              sourcePort: {
                ...port,
                shape: meta.shape,
                direction: "output",
              },
              sourceMeta: meta,
              sourceFeed: meta.feed ?? null,
              registry,
              nodes: catalogNodes,
            });
      if (!canvasAtPoint(clientPoint.x, clientPoint.y)) return;
      if (!candidates.length) {
        if (!upstream) placeOutputCard(fromNode.id, port.name, flowPosition);
        return;
      }

      openContextualDiscovery({
        graphId: openGraphId,
        sourceNodeId: fromNode.id,
        sourceEndpoint: {
          kind: "port",
          portName,
          plugId,
          direction: meta.direction,
          meta,
        },
        sourcePortTitle: port.title ?? port.name,
        direction: upstream ? "upstream" : "downstream",
        clientAnchor: clientPoint,
        flowPosition,
        candidates,
      });
    },
    [
      canvasSelection,
      commitArtifactViewers,
      openGraphId,
      openContextualDiscovery,
      setLibraryOpen,
      placeOutputCard,
      registry,
    ],
  );

  const handleArtifactCardConnectionDrop = React.useCallback(
    ({
      cardId,
      clientPoint,
      flowPosition,
    }: {
      cardId: string;
      clientPoint: XYPosition;
      flowPosition: XYPosition;
    }): boolean => {
      if (!registry || !canEditProject || running) return false;
      const card = activeArtifactViewers.nodes.find(
        (node) => node.id === cardId,
      );
      const value =
        card &&
        artifactCardConnectionValue(card, activeArtifactViewers.edges, nodes);
      if (!card || !value || !cardArtifactRefs(value).length) return false;
      const port = artifactCardOutputPort(value);
      const candidates = downstreamCandidatesFromOutput({
        sourcePort: port,
        sourceMeta: portMetaForPort(port, port.shape),
        sourceFeed: null,
        registry,
        nodes: catalogNodeSpecs(registry, openGraphId),
      })
        .map((candidate) => ({
          ...candidate,
          choices: candidate.choices.filter((choice) => {
            if (
              choice.route.kind === "projection" ||
              choice.route.kind === "projection-conversion"
            )
              return false;
            const binding = choice.route.artifactTypeBinding;
            const bindings =
              binding?.endpoint === "target"
                ? { [binding.variable]: binding.artifactType }
                : {};
            const resolution = resolveArtifactDrop(
              artifactDropPayload(value),
              choice.candidatePort,
              bindings,
              registry.artifact_conversions,
            );
            return (
              resolution !== null &&
              resolution.collectionMode === choice.collectionMode &&
              JSON.stringify(resolution.conversionPath) ===
                JSON.stringify(
                  choice.route.conversionPath.map((conversion) => ({
                    id: conversion.key.id,
                    version: conversion.key.version,
                  })),
                )
            );
          }),
        }))
        .filter((candidate) => candidate.choices.length > 0);
      if (!candidates.length) return false;
      openContextualDiscovery({
        graphId: openGraphId,
        sourceNodeId: card.id,
        sourceEndpoint: { kind: "artifact-card" },
        sourcePortTitle: port.title ?? port.name,
        direction: "downstream",
        clientAnchor: clientPoint,
        flowPosition,
        candidates,
      });
      return true;
    },
    [
      activeArtifactViewers.edges,
      activeArtifactViewers.nodes,
      canEditProject,
      nodes,
      openGraphId,
      openContextualDiscovery,
      registry,
      running,
    ],
  );

  const continueFromArtifactCard = React.useCallback(
    (cardId: string, world: XYPosition) => {
      const client =
        cellCanvasHandle?.viewportHandle.worldToScreen(world) ?? world;
      handleArtifactCardConnectionDrop({
        cardId,
        clientPoint: client,
        flowPosition: world,
      });
    },
    [cellCanvasHandle, handleArtifactCardConnectionDrop],
  );

  const confirmContextualDiscovery = React.useCallback(
    (candidate: ContextualCandidate, choice: ContextualRouteChoice) => {
      if (!contextualDiscovery || !registry || !canEditProject || running)
        return;
      // A port prompt places the provider through the engine reducer, which
      // also writes a shared binding and chooses who stays selected.
      if (contextualDiscovery.trigger === "port_prompt") {
        chooseProvider(candidate.spec, choice);
        return;
      }

      const upstream = contextualDiscovery.direction === "upstream";
      const id = `node-${createUuid()}`;
      const data = newCatalogNodeData(candidate.spec);
      const binding = choice.route.artifactTypeBinding;
      // Bind the artifact type variable on whichever endpoint lives on the new node.
      if (
        (upstream && binding?.endpoint === "source") ||
        (!upstream && binding?.endpoint === "target")
      ) {
        data.artifactTypeBindings = {
          ...data.artifactTypeBindings,
          [binding.variable]: binding.artifactType,
        };
      }

      const plugId =
        !upstream && choice.usesInstancePlug
          ? data.inputPlugs.find(
              (plug) => plug.portName === choice.candidatePort.name,
            )?.id
          : undefined;
      if (!upstream && choice.usesInstancePlug && !plugId) return;

      const edgeId = `edge-${createUuid()}`;
      const selection = connectionRouteSelection(choice.route);
      const placedPosition = {
        x: contextualDiscovery.flowPosition.x,
        y:
          contextualDiscovery.flowPosition.y -
          DEFAULT_NODE_PLACEMENT_HEIGHT / 2,
      };
      const nodeCommand = addNodeCommand(id, data, placedPosition);

      if (contextualDiscovery.sourceEndpoint.kind === "artifact-card") {
        const card = activeArtifactViewers.nodes.find(
          (node) => node.id === contextualDiscovery.sourceNodeId,
        );
        const value =
          card &&
          artifactCardConnectionValue(
            card,
            activeArtifactViewers.edges,
            nodesRef.current,
          );
        if (!value) return;
        const commands = artifactDropCommands(
          artifactDropPayload(value),
          {
            nodeId: id,
            portName: choice.candidatePort.name,
            plugId: plugId ?? null,
          },
          choice.candidatePort,
          data.artifactTypeBindings,
          {
            edges: edgesRef.current,
            origins: authoredDocumentRef.current.origins,
            conversions: registry.artifact_conversions,
          },
          card.id,
        );
        if (!commands) return;
        applyAuthoringCommands([nodeCommand, ...commands]);
        canvasSelection.selectOnly({ nodeIds: [id] });
        noteContinuedNode({
          id,
          position: placedPosition,
          spec: data.spec,
          satisfiedInputs: [choice.candidatePort.name],
        });
        closeContextualDiscovery();
        clearRunError();
        return;
      }

      const existingPort = contextualDiscovery.sourceEndpoint;
      const edgeConnection: GraphConnection = upstream
        ? {
            source: id,
            sourcePort: choice.candidatePort.name,
            target: contextualDiscovery.sourceNodeId,
            targetPort: existingPort.portName,
            targetPlug: existingPort.plugId ?? null,
          }
        : {
            source: contextualDiscovery.sourceNodeId,
            sourcePort: existingPort.portName,
            target: id,
            targetPort: choice.candidatePort.name,
            targetPlug: plugId ?? null,
          };

      if (
        !isConnectionAccepted(
          edgeConnection,
          [...nodesRef.current, { id, data }],
          edgesRef.current,
          registry.artifact_types,
          registry.artifact_conversions,
          null,
          authoredDocumentRef.current.origins,
        )
      ) {
        closeContextualDiscovery();
        setRunError(
          "This input is already connected or no longer accepts this connection.",
        );
        return;
      }

      const edgeCommand = addEdgeCommand(
        edgeConnection,
        {
          enabled: true,
          collectionMode: choice.collectionMode,
          projection: selection.projection
            ? { path: [...selection.projection.path] }
            : undefined,
          conversionPath: selection.conversionPath.map((conversion) => ({
            id: conversion.id,
            version: conversion.version,
          })),
        },
        edgeId,
      );

      applyAuthoringCommands([nodeCommand, edgeCommand]);
      canvasSelection.selectOnly({ nodeIds: [id] });
      noteContinuedNode({
        id,
        position: placedPosition,
        spec: data.spec,
        satisfiedInputs: upstream ? [] : [choice.candidatePort.name],
      });
      closeContextualDiscovery();
      clearRunError();
    },
    [
      activeArtifactViewers.nodes,
      activeArtifactViewers.edges,
      applyAuthoringCommands,
      canvasSelection,
      canEditProject,
      authoredDocumentRef,
      chooseProvider,
      clearRunError,
      closeContextualDiscovery,
      contextualDiscovery,
      newCatalogNodeData,
      noteContinuedNode,
      registry,
      running,
      setRunError,
    ],
  );

  const activeContextualDiscovery =
    canEditProject && !running && contextualDiscovery?.graphId === openGraphId
      ? contextualDiscovery
      : null;

  /** Adds an annotation with its corner at `at`, else mid-canvas. */
  const addAnnotation = React.useCallback(
    (kind: AnnotationKind, at?: { x: number; y: number }) => {
      const center = canvasCenter({ x: 480, y: 240 });
      const annotation = createAnnotationNode(
        kind,
        at ?? { x: center.x - 80, y: center.y - 60 },
      );
      const committed = commitArtifactViewers((current) => {
        const cleared = withoutPresentationSelection(current);
        return {
          ...cleared,
          annotations: [...cleared.annotations, annotation],
        };
      });
      if (committed) canvasSelection.clearWorkflowSelection();
      setShapesMenuOpen(false);
      setLibraryOpen(false);
      closeGraphBrowser();
    },
    [
      canvasCenter,
      canvasSelection,
      closeGraphBrowser,
      commitArtifactViewers,
      setLibraryOpen,
      setShapesMenuOpen,
    ],
  );

  const duplicateSelectedNodes = React.useCallback(() => {
    const selectedNodes = nodes.filter((node) => node.selected);
    const selectedViewers = artifactViewers.nodes.filter(
      (node) => node.selected,
    );
    if ((!selectedNodes.length && !selectedViewers.length) || running) return;

    const duplicates = selectedNodes.map((node) => ({
      node,
      id: `node-${createUuid()}`,
    }));
    const duplicatedNodeIds = new Map(
      duplicates.map(({ node, id }) => [node.id, id]),
    );
    const duplicatedNodes = duplicates.flatMap(({ node, id }) => {
      const authoredNode = authoredDocument.nodes.find(
        (candidate) => candidate.id === node.id,
      );
      return authoredNode
        ? [
            {
              ...structuredClone(authoredNode),
              id,
              position: { x: node.position.x + 36, y: node.position.y + 36 },
            },
          ]
        : [];
    });
    const duplicatedEdges = authoredDocument.edges.flatMap((edge) => {
      const source = duplicatedNodeIds.get(edge.from_node);
      const target = duplicatedNodeIds.get(edge.to_node);
      if (!source || !target) return [];
      return [
        {
          ...structuredClone(edge),
          id: `edge-${createUuid()}`,
          from_node: source,
          to_node: target,
        },
      ];
    });
    const commands: GraphCommand[] = [
      ...duplicatedNodes.map((node) => ({
        kind: "add_node" as const,
        node,
      })),
      ...duplicatedEdges.map((edge) => ({
        kind: "add_edge" as const,
        edge,
      })),
    ];
    if (commands.length) applyAuthoringCommands(commands);
    const duplicatedViewerIds = new Map(
      selectedViewers.map((node) => [
        node.id,
        `artifact-viewer-${createUuid()}`,
      ]),
    );
    if (selectedViewers.length) {
      commitArtifactViewers((current) =>
        duplicateArtifactViewers(
          withoutPresentationSelection(current),
          duplicatedViewerIds,
          duplicatedNodeIds,
        ),
      );
    }
    // The copies are what a person holds after duplicating, in whichever layer
    // they were copied from.
    canvasSelection.selectOnly({
      nodeIds: duplicatedNodes.map((node) => node.id),
      viewerIds: [...duplicatedViewerIds.values()],
    });
    setPendingConnectionRoute(null);
    setRunError(null);
  }, [
    applyAuthoringCommands,
    artifactViewers.nodes,
    authoredDocument,
    canvasSelection,
    commitArtifactViewers,
    nodes,
    running,
    setPendingConnectionRoute,
    setRunError,
  ]);

  const removeCellElements = React.useCallback(
    (cardIds: readonly string[], pipeIds: readonly string[]) => {
      if (!localAuthoringEnabled) return;
      pruneInspectedPipes(pipeIds);
      const removals = partitionCellRemovals(
        cardIds,
        pipeIds,
        authoredDocumentRef.current,
        artifactViewers,
        artifactOriginCanvasEdges,
      );
      applyAuthoringCommands(removals.graphCommands);
      for (const id of removals.removedViewerIds) removeArtifactViewer(id);
      for (const id of removals.removedAnnotationIds) removeAnnotation(id);
      if (removals.removedViewerEdgeIds.length) {
        const removed = new Set(removals.removedViewerEdgeIds);
        commitArtifactViewers((current) => {
          const edges = current.edges.filter((edge) => !removed.has(edge.id));
          return edges.length === current.edges.length
            ? current
            : { ...current, edges };
        });
      }
    },
    [
      applyAuthoringCommands,
      artifactOriginCanvasEdges,
      artifactViewers,
      commitArtifactViewers,
      localAuthoringEnabled,
      authoredDocumentRef,
      pruneInspectedPipes,
      removeAnnotation,
      removeArtifactViewer,
    ],
  );

  const deleteSelectedNodes = React.useCallback(() => {
    if (!canvasReady || !selectedNodeIds.length || running) return;
    setPendingConnectionRoute(null);
    setRunError(null);
    removeCellElements(selectedNodeIds, []);
  }, [
    canvasReady,
    removeCellElements,
    running,
    selectedNodeIds,
    setPendingConnectionRoute,
    setRunError,
  ]);

  const canvasEdges = React.useMemo<WorkflowEdge[]>(
    () =>
      edges.map((edge) => {
        const resolvedEdge = graphSemantics?.edges.get(edge.id);
        const sourceNode = graphSemantics?.nodes.get(edge.source);
        const targetNode = graphSemantics?.nodes.get(edge.target);
        const sourceMeta =
          resolvedEdge?.sourcePort && sourceNode
            ? portMetaForPort(
                resolvedEdge.sourcePort,
                resolvedEdge.sourceShape,
                undefined,
                sourceNode.artifactTypeBindings,
              )
            : null;
        const targetMeta =
          resolvedEdge?.targetPort && targetNode
            ? portMetaForPort(
                resolvedEdge.targetPort,
                resolvedEdge.targetPort.shape,
                edge.targetPlug ?? undefined,
                targetNode.artifactTypeBindings,
              )
            : null;
        const activeSelection = {
          projection: edge.data?.projection,
          conversionPath: edge.data?.conversionPath ?? [],
        };
        const routes =
          sourceMeta && targetMeta
            ? connectionRoutesForPorts(
                sourceMeta,
                targetMeta,
                registry?.artifact_types ?? [],
                registry?.artifact_conversions ?? [],
              )
            : [];
        const activeRoute =
          sourceMeta && targetMeta
            ? connectionRouteForPortSelection(
                sourceMeta,
                targetMeta,
                registry?.artifact_types ?? [],
                registry?.artifact_conversions ?? [],
                activeSelection,
              )
            : null;
        if (
          activeRoute &&
          !routes.some((route) =>
            connectionRouteMatchesSelection(route, activeSelection),
          )
        ) {
          routes.push(activeRoute);
        }
        const routeOptions = routes.map(workflowEdgeRouteOption);
        const conversionTitles = activeSelection.conversionPath.map(
          (requestedConversion) =>
            registry?.artifact_conversions.find(
              (conversion) =>
                conversion.key.id === requestedConversion.id &&
                conversion.key.version === requestedConversion.version,
            )?.title ??
            `${requestedConversion.id}@${requestedConversion.version}`,
        );
        const validModes = [...(resolvedEdge?.allowedCollectionModes ?? [])];
        return {
          ...edge,
          data: {
            ...edge.data,
            enabled: edge.data?.enabled ?? true,
            collectionMode: edge.data?.collectionMode ?? "direct",
            conversionTitles,
            routeOptions,
            allowedCollectionModes: edge.data?.compatibilityIssues?.length
              ? []
              : validModes,
          },
        };
      }),
    [
      edges,
      graphSemantics,
      registry?.artifact_conversions,
      registry?.artifact_types,
    ],
  );

  const artifactViewerCanvasEdges = React.useMemo<ArtifactViewerEdge[]>(
    () =>
      activeArtifactViewers.edges.map((edge) => {
        const sourceNode = nodes.find((node) => node.id === edge.source);
        const sourcePort = sourceNode?.data.spec.outputs.find(
          (port) => port.name === edge.data?.sourcePortName,
        );
        const sourceArtifactTypeKey =
          sourceNode && sourcePort
            ? resolvedPortArtifactType(
                sourcePort,
                sourceNode.data.artifactTypeBindings,
              )
            : null;
        const sourceArtifactType = sourceArtifactTypeKey
          ? registry?.artifact_types.find(
              (candidate) =>
                candidate.key.id === sourceArtifactTypeKey.id &&
                candidate.key.schema_version ===
                  sourceArtifactTypeKey.schema_version,
            )
          : undefined;
        const projections = [
          ...(sourceArtifactType?.field_projections ?? []),
        ].sort((left, right) => left.title.localeCompare(right.title));
        const routeOptions: WorkflowEdgeRouteOption[] = [
          { conversionPath: [], conversionTitles: [] },
          ...projections.map((projection) => ({
            projection: { path: [...projection.path] },
            projectionTitle: projection.title,
            conversionPath: [],
            conversionTitles: [],
          })),
        ];
        if (
          edge.data?.projection?.path.length &&
          !routeOptions.some(
            (route) =>
              route.projection?.path.length ===
                edge.data?.projection?.path.length &&
              route.projection?.path.every(
                (segment, index) =>
                  segment === edge.data?.projection?.path[index],
              ),
          )
        ) {
          routeOptions.push({
            projection: { path: [...edge.data.projection.path] },
            conversionPath: [],
            conversionTitles: [],
          });
        }
        const activeProjectionTitle = routeOptions.find(
          (route) =>
            route.projection?.path.length ===
              edge.data?.projection?.path.length &&
            route.projection?.path.every(
              (segment, index) =>
                segment === edge.data?.projection?.path[index],
            ),
        )?.projectionTitle;
        return {
          ...edge,
          type: ARTIFACT_VIEWER_EDGE_TYPE,
          targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
          data: {
            ...edge.data,
            sourcePortName: edge.data?.sourcePortName ?? "",
            projectionTitle: activeProjectionTitle,
            routeOptions,
          },
        };
      }),
    [activeArtifactViewers.edges, nodes, registry?.artifact_types],
  );

  const latestArtifactViewerActivity = React.useMemo(() => {
    let latest: {
      nodeId: string;
      value: ActiveArtifactViewerActivity;
    } | null = null;
    for (const [nodeId, value] of Object.entries(artifactViewerActivities)) {
      if (!latest || value.revision > latest.value.revision) {
        latest = { nodeId, value };
      }
    }
    return latest;
  }, [artifactViewerActivities]);

  const dismissArtifactViewerActivity = React.useCallback(
    (nodeId: string, revision: number) => {
      setArtifactViewerActivities((current) => {
        if (current[nodeId]?.revision !== revision) return current;
        const next = { ...current };
        delete next[nodeId];
        return next;
      });
    },
    [setArtifactViewerActivities],
  );

  React.useEffect(() => {
    if (
      !latestArtifactViewerActivity ||
      latestArtifactViewerActivity.value.activity.state !== "success"
    ) {
      return;
    }
    const { nodeId, value } = latestArtifactViewerActivity;
    const timeout = window.setTimeout(
      () => dismissArtifactViewerActivity(nodeId, value.revision),
      4000,
    );
    return () => window.clearTimeout(timeout);
  }, [dismissArtifactViewerActivity, latestArtifactViewerActivity]);

  // Firefox uses autocomplete to control restored dynamic button state, but
  // React's button typings omit that browser-specific attribute.
  const firefoxDynamicButtonProps: React.ButtonHTMLAttributes<HTMLButtonElement> & {
    autoComplete: "off";
  } = { autoComplete: "off" };
  const viewerActivity = latestArtifactViewerActivity?.value.activity ?? null;
  const dismissLinkedView = React.useCallback(() => {
    if (!latestArtifactViewerActivity) return;
    dismissArtifactViewerActivity(
      latestArtifactViewerActivity.nodeId,
      latestArtifactViewerActivity.value.revision,
    );
  }, [dismissArtifactViewerActivity, latestArtifactViewerActivity]);

  // The Library panel's cached tree names the files artifact cards show.
  const { data: libraryTree } = useSWR(["library-tree", workspaceId], () =>
    libraryFoldersApi.listTree(workspaceId),
  );
  const libraryItemsByArtifactId = React.useMemo(() => {
    const items = new Map<string, PlacedLibraryItem>();
    for (const item of libraryTree?.items ?? []) {
      items.set(item.artifact.artifact_id, item);
    }
    return items;
  }, [libraryTree]);

  const [cellImageNaturalSizes, setCellImageNaturalSizes] = React.useState<
    ReadonlyMap<string, { width: number; height: number }>
  >(() => new Map());
  const onCellArtifactImageLoad = React.useCallback(
    (imageUrl: string, size: { width: number; height: number }) => {
      setCellImageNaturalSizes((current) => {
        const existing = current.get(imageUrl);
        if (
          existing &&
          existing.width === size.width &&
          existing.height === size.height
        ) {
          return current;
        }
        const next = new Map(current);
        next.set(imageUrl, size);
        return next;
      });
    },
    [],
  );

  const callPath = React.useMemo(
    () => callTrail.map((entry) => entry.nodeId),
    [callTrail],
  );
  const onCancelNodeRun = React.useCallback(
    (nodeId: string) => {
      if (!canCancelRun) return;
      const active = activeRunForNode(openGraphRuns, nodeId, callPath);
      if (!active?.cancellable || cancellingRunIds.has(active.run_id)) return;
      cancelGraphRun(active.run_id);
    },
    [callPath, canCancelRun, cancelGraphRun, cancellingRunIds, openGraphRuns],
  );

  const cellScene = React.useMemo(
    () =>
      registry
        ? buildWorkbenchCellScene({
            workspaceId,
            document: authoredDocument,
            registry,
            semantics: graphSemantics,
            presentation: sharedPresentation,
            nodes,
            nodeInstanceStates,
            collapsedAppendices,
            configSections,
            secrets: {
              statuses: nodeSecretStatuses,
              vault: {
                workspaceId,
                canManageShared: canManageSecrets,
                canEditShared: canEditProject,
                canSelectPersonal: canStartRun,
                credentials,
                refreshCredentials,
                selectCredential,
                verifyCredential,
              },
              savedNodes: activeGraph?.nodes ?? null,
              scope: `${openGraphId ?? "unsaved"}:${activeGraph?.roomEpoch ?? "none"}`,
            },
            canRun: canRunSavedGraph && !running,
            runDisabledReason: runBlockedReason ?? undefined,
            canvasEdges,
            artifactViewerEdges: artifactViewerCanvasEdges,
            artifactViewerNodes: activeArtifactViewers.nodes,
            artifactOriginEdges: artifactOriginCanvasEdges,
            libraryItemsByArtifactId,
            imageNaturalSizes: cellImageNaturalSizes,
            engineSettingsHref: managePacksHref,
            onOperatorConfigChange: localAuthoringEnabled
              ? updateConfigPatch
              : undefined,
            liveRun:
              projectId && openGraphId
                ? {
                    projectId,
                    graphId: openGraphId,
                    callPath,
                    progress: projectRoom.nodeProgress,
                    runs: openGraphRuns,
                    cancellingRunIds,
                    canCancelRun,
                    onCancelNodeRun,
                  }
                : undefined,
          })
        : null,
    [
      activeArtifactViewers.nodes,
      activeGraph,
      artifactOriginCanvasEdges,
      artifactViewerCanvasEdges,
      authoredDocument,
      callPath,
      canCancelRun,
      cancellingRunIds,
      canEditProject,
      canManageSecrets,
      canStartRun,
      credentials,
      refreshCredentials,
      selectCredential,
      verifyCredential,
      canvasEdges,
      cellImageNaturalSizes,
      collapsedAppendices,
      configSections,
      graphSemantics,
      libraryItemsByArtifactId,
      localAuthoringEnabled,
      managePacksHref,
      nodeInstanceStates,
      nodeSecretStatuses,
      nodes,
      onCancelNodeRun,
      openGraphId,
      openGraphRuns,
      projectId,
      canRunSavedGraph,
      runBlockedReason,
      projectRoom.nodeProgress,
      registry,
      running,
      sharedPresentation,
      updateConfigPatch,
      workspaceId,
    ],
  );

  const selectionLinkCards = React.useMemo<SelectionLinkCard[]>(() => {
    if (!cellScene) return [];
    return cellScene.graph.cards.flatMap((card) => {
      const surface = cellScene.surfaceById[card.id];
      if (
        surface?.kind !== "artifact" ||
        !surface.artifact ||
        (surface.itemCount ?? 1) > 1
      ) {
        return [];
      }
      const capability = selectionLinkCapability(surface.previewKind);
      if (!capability.source && capability.effects.length === 0) return [];
      // Name the card the way its header does, type then file, so two
      // tables on the canvas read as different targets in the link editor.
      const name =
        surface.filename ?? surface.dimensionsLabel ?? surface.byteSizeLabel;
      return [
        {
          id: card.id,
          title: name ? `${card.title} · ${name}` : card.title,
          capability,
        },
      ];
    });
  }, [cellScene]);
  const selectionLinks = useSelectionLinks({
    cards: selectionLinkCards,
    bindings: activeArtifactViewers.bindings,
    editable: localAuthoringEnabled,
    saveBinding: saveArtifactViewerBinding,
    removeBinding: removeArtifactViewerBinding,
    onActivityChange: updateArtifactViewerActivity,
  });

  const onArtifactDownload = React.useCallback(
    (cardId: string, format: string | null) => {
      const surface = cellScene?.surfaceById[cardId];
      if (surface?.kind !== "artifact" || (surface.itemCount ?? 1) !== 1)
        return;
      const artifactId = surface.artifact?.artifact_id;
      if (!artifactId) return;
      triggerArtifactDownload(
        format
          ? artifactDownloadUrl(workspaceId, artifactId, format)
          : artifactInlineContentUrl(workspaceId, artifactId),
      );
    },
    [cellScene, workspaceId],
  );

  const onArtifactSaveToLibrary = React.useCallback(
    async (cardId: string) => {
      if (!canEditProject) return;
      const surface = cellScene?.surfaceById[cardId];
      if (surface?.kind !== "artifact" || (surface.itemCount ?? 1) !== 1)
        return;
      const artifactId = surface.artifact?.artifact_id;
      if (!artifactId || surface.inLibrary) return;
      const displayName =
        surface.filename?.trim() ||
        `${surface.typeLabel} · ${artifactId.slice(0, 8)}`;
      try {
        const item = await saveArtifactToLibrary(workspaceId, {
          artifact_id: artifactId,
          name: Array.from(displayName).slice(0, 160).join(""),
        });
        void mutateCache(["library-tree", workspaceId]);
        toastManager.add({
          title: "Saved in Library",
          description: item.name,
          type: "success",
        });
      } catch (error) {
        toastManager.add({
          title: "Could not save to Library",
          description: error instanceof Error ? error.message : undefined,
          type: "error",
          priority: "high",
        });
      }
    },
    [canEditProject, cellScene, mutateCache, toastManager, workspaceId],
  );

  const cleanupTargetKey = `${projectId ?? "draft"}:${openGraphId ?? "none"}`;
  const [cleanupHistory, setCleanupHistory] = React.useState<{
    targetKey: string;
    stack: readonly CellCleanupUndoSnapshot[];
    initialSnapshot: CellCleanupUndoSnapshot;
    toast: { key: string; lead: string } | null;
  } | null>(null);
  const activeCleanupHistory =
    cleanupHistory && cleanupHistory.targetKey === cleanupTargetKey
      ? cleanupHistory
      : null;
  const activeCleanupToast =
    activeCleanupHistory?.toast && !engineConnectNotice
      ? activeCleanupHistory.toast
      : null;
  const cleanupUndoCount = activeCleanupHistory?.stack.length ?? 0;
  const selectedForegroundCount =
    selectedWorkflowCount + selectedViewerCount + selectedAgentIds.size;
  const foregroundCardCount =
    authoredDocument.nodes.length +
    authoredDocument.agents.length +
    artifactViewers.nodes.length;
  const canCleanUpCanvas =
    Boolean(registry) &&
    canvasReady &&
    localAuthoringEnabled &&
    !running &&
    foregroundCardCount > 0;
  const canTidySelection =
    Boolean(registry) &&
    canvasReady &&
    localAuthoringEnabled &&
    !running &&
    selectedForegroundCount > 1;

  React.useEffect(() => {
    if (!cleanupPanelOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setCleanupPanelOpen(false);
      }
    };
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && cleanupWrapRef.current?.contains(target)) {
        return;
      }
      setCleanupPanelOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("pointerdown", onPointerDown, true);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("pointerdown", onPointerDown, true);
    };
  }, [cleanupPanelOpen]);

  const runCanvasCleanup = React.useCallback(
    (scope: "all" | "selected", paramsOverride?: CellCleanupParams) => {
      if (!registry || !localAuthoringEnabledRef.current || running) return;
      const selectedIds =
        scope === "selected"
          ? new Set<string>([
              ...selectedNodeIdSet,
              ...selectedAgentIds,
              ...artifactViewersRef.current.nodes
                .filter((node) => node.selected)
                .map((node) => node.id),
            ])
          : undefined;
      if (selectedIds && selectedIds.size < 2) return;
      const currentViewers = artifactViewersRef.current;
      const plan = planWorkbenchCanvasCleanup({
        workspaceId,
        document: authoredDocumentRef.current,
        artifactViewers: currentViewers,
        registry,
        nodes: nodesRef.current,
        nodeInstanceStates,
        collapsedAppendices,
        configSections,
        imageNaturalSizes: cellImageNaturalSizes,
        selectedCardIds: selectedIds,
        params: paramsOverride ?? cleanupParams,
      });
      if (!plan.changed) return;
      if (plan.graphCommands.length > 0) {
        applyAuthoringCommands(plan.graphCommands);
      }
      const presentationChanged =
        plan.nextArtifactViewers.nodes.some(
          (node, index) => node !== currentViewers.nodes[index],
        ) ||
        plan.nextArtifactViewers.edges.some(
          (edge, index) => edge !== currentViewers.edges[index],
        ) ||
        plan.nextArtifactViewers.annotations.some(
          (annotation, index) =>
            annotation !== currentViewers.annotations[index],
        );
      if (presentationChanged) {
        commitArtifactViewers(() => plan.nextArtifactViewers);
      }
      if (plan.bounds && cellCanvasHandle && canvasSectionRef.current) {
        const rect = canvasSectionRef.current.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          const topLeft = cellCanvasHandle.viewportHandle.screenToWorld(
            rect.left,
            rect.top,
          );
          const bottomRight = cellCanvasHandle.viewportHandle.screenToWorld(
            rect.right,
            rect.bottom,
          );
          const visMinX = Math.min(topLeft.x, bottomRight.x);
          const visMaxX = Math.max(topLeft.x, bottomRight.x);
          const visMinY = Math.min(topLeft.y, bottomRight.y);
          const visMaxY = Math.max(topLeft.y, bottomRight.y);
          const planMaxX = plan.bounds.x + plan.bounds.width;
          const planMaxY = plan.bounds.y + plan.bounds.height;
          const intersects =
            planMaxX > visMinX &&
            plan.bounds.x < visMaxX &&
            planMaxY > visMinY &&
            plan.bounds.y < visMaxY;
          if (!intersects) {
            cellCanvasHandle.viewportHandle.fitBounds(plan.bounds, 0.2, 1);
          }
        }
      }
      setPendingConnectionRoute(null);
      dismissEngineConnectNotice();
      const lead =
        scope === "selected"
          ? `Tidied ${plan.affectedCardCount} selected cards`
          : plan.experimentCount > 0
            ? `Cleaned up ${plan.affectedCardCount} cards across ${plan.experimentCount} experiment${plan.experimentCount === 1 ? "" : "s"}`
            : `Cleaned up ${plan.affectedCardCount} card${plan.affectedCardCount === 1 ? "" : "s"}`;
      setCleanupHistory((current) => {
        const sameTarget = current && current.targetKey === cleanupTargetKey;
        const nextStack = sameTarget
          ? [...current.stack, plan.undoSnapshot]
          : [plan.undoSnapshot];
        const nextInitial = sameTarget
          ? mergeCleanupUndoSnapshots(
              current.initialSnapshot,
              plan.undoSnapshot,
            )
          : plan.undoSnapshot;
        return {
          targetKey: cleanupTargetKey,
          stack: nextStack,
          initialSnapshot: nextInitial,
          toast: { key: createUuid(), lead },
        };
      });
    },
    [
      applyAuthoringCommands,
      artifactViewersRef,
      authoredDocumentRef,
      cellCanvasHandle,
      cellImageNaturalSizes,
      cleanupParams,
      cleanupTargetKey,
      collapsedAppendices,
      commitArtifactViewers,
      configSections,
      dismissEngineConnectNotice,
      nodeInstanceStates,
      registry,
      running,
      selectedAgentIds,
      selectedNodeIdSet,
      setPendingConnectionRoute,
      workspaceId,
    ],
  );

  const applyCleanupUndoSnapshot = React.useCallback(
    (snapshot: CellCleanupUndoSnapshot) => {
      const currentViewers = artifactViewersRef.current;
      const undo = buildCleanupUndoPlan(
        authoredDocumentRef.current,
        currentViewers,
        snapshot,
      );
      if (!undo.changed) return;
      if (undo.graphCommands.length > 0) {
        applyAuthoringCommands(undo.graphCommands);
      }
      const presentationChanged =
        undo.nextArtifactViewers.nodes.some(
          (node, index) => node !== currentViewers.nodes[index],
        ) ||
        undo.nextArtifactViewers.edges.some(
          (edge, index) => edge !== currentViewers.edges[index],
        ) ||
        undo.nextArtifactViewers.annotations.some(
          (annotation, index) =>
            annotation !== currentViewers.annotations[index],
        );
      if (presentationChanged) {
        commitArtifactViewers(() => undo.nextArtifactViewers);
      }
    },
    [
      applyAuthoringCommands,
      artifactViewersRef,
      authoredDocumentRef,
      commitArtifactViewers,
    ],
  );

  const undoCanvasCleanup = React.useCallback(() => {
    if (
      !cleanupHistory ||
      cleanupHistory.targetKey !== cleanupTargetKey ||
      cleanupHistory.stack.length === 0 ||
      !localAuthoringEnabledRef.current ||
      running
    ) {
      setCleanupHistory(null);
      return;
    }
    const latest = cleanupHistory.stack[cleanupHistory.stack.length - 1];
    if (!latest) {
      setCleanupHistory(null);
      return;
    }
    const remaining = cleanupHistory.stack.slice(0, -1);
    if (remaining.length === 0) {
      setCleanupHistory(null);
    } else {
      const remainingInitial = remaining.reduce((acc, snap) =>
        mergeCleanupUndoSnapshots(acc, snap),
      );
      setCleanupHistory({
        targetKey: cleanupTargetKey,
        stack: remaining,
        initialSnapshot: remainingInitial,
        toast: {
          key: createUuid(),
          lead:
            remaining.length === 1
              ? "Undid last cleanup · 1 step to initial layout"
              : `Undid last cleanup · ${remaining.length} steps to initial layout`,
        },
      });
    }
    applyCleanupUndoSnapshot(latest);
  }, [applyCleanupUndoSnapshot, cleanupHistory, cleanupTargetKey, running]);

  const revertCanvasCleanupToInitial = React.useCallback(() => {
    if (
      !cleanupHistory ||
      cleanupHistory.targetKey !== cleanupTargetKey ||
      cleanupHistory.stack.length === 0 ||
      !localAuthoringEnabledRef.current ||
      running
    ) {
      setCleanupHistory(null);
      return;
    }
    const initial = cleanupHistory.initialSnapshot;
    setCleanupHistory(null);
    applyCleanupUndoSnapshot(initial);
  }, [applyCleanupUndoSnapshot, cleanupHistory, cleanupTargetKey, running]);

  // --- The canvas right-click menu --------------------------------------------

  const openCanvasMenu = React.useCallback(
    (request: CanvasMenuRequest) => {
      onCloseGraphBrowser();
      closeGridPanel();
      let { target } = request;
      if (target.kind === "node") {
        const nodeId = target.nodeId;
        const selection = selectedNodeIdsRef.current;
        if (selection.length > 1 && selection.includes(nodeId)) {
          target = { kind: "selection" };
        } else {
          canvasSelection.selectOnly(
            partitionCellSelection(
              { cardIds: new Set([nodeId]), pipeIds: new Set() },
              authoredDocumentRef.current,
              artifactViewers,
            ),
          );
        }
      }
      const focused = document.activeElement;
      openContextMenu({
        ...request,
        target,
        returnFocus: focused instanceof HTMLElement ? focused : null,
      });
    },
    [
      artifactViewers,
      authoredDocumentRef,
      canvasSelection,
      closeGridPanel,
      onCloseGraphBrowser,
      openContextMenu,
    ],
  );
  const canvasMenuTrigger = useCanvasMenuTrigger(openCanvasMenu);
  const canvasMenuPoint = canvasMenu
    ? (screenToCanvasPoint(canvasMenu.point) ?? null)
    : null;
  const canvasMenuSelection: CanvasMenuSelection = {
    count: selectedNodeCount,
    workflowCount: selectedWorkflowCount,
    canRun: !runSelectedDisabled,
    canDuplicate:
      Boolean(selectedWorkflowCount || selectedViewerCount) &&
      localAuthoringEnabled,
    canDelete: canvasReady && selectedNodeCount > 0 && localAuthoringEnabled,
    collect: collectSpec
      ? selectedCollectionSources.length > 1
        ? {
            disabled:
              !localAuthoringEnabled || Boolean(collectionDisabledReason),
            title: collectionDisabledReason ?? undefined,
          }
        : null
      : collectsIntoSequence
        ? {
            disabled:
              !collectedArtifactRefs ||
              !localAuthoringEnabled ||
              Boolean(groupingDisabledReason),
            title:
              groupingDisabledReason ??
              (collectedArtifactRefs
                ? selectedArtifactCards.length === 1
                  ? "Put this artifact in a sequence"
                  : `Collect ${selectedArtifactCards.length} selected artifacts into an ordered sequence`
                : "Select artifacts of the same type to collect"),
          }
        : null,
    canTidy: canTidySelection,
    canCleanUpCanvas,
  };
  const canvasMenuActions: CanvasMenuActions = {
    searchNodes: () => setLibraryOpen(true, canvasMenuPoint),
    addNodeHere: (spec) =>
      addCatalogNode(spec, canvasMenuPoint ?? undefined, false),
    addAnnotationHere: (kind) =>
      addAnnotation(kind, canvasMenuPoint ?? undefined),
    createArtifactHere: () => openCreateArtifact(canvasMenuPoint ?? undefined),
    selectAll: () => {
      if (!cellScene) return;
      canvasSelection.selectOnly(
        partitionCellSelection(
          {
            cardIds: new Set(cellScene.graph.cards.map(({ id }) => id)),
            pipeIds: selectedEdgeIdSet,
          },
          authoredDocumentRef.current,
          artifactViewers,
        ),
      );
    },
    cleanUpCanvas: () => runCanvasCleanup("all"),
    fitView: () => fitCanvasView(WORKBENCH_FIT_VIEW),
    openCanvasLab: canvasLabEnabled ? () => setLabPanelOpen(true) : undefined,
    runSelection: () => void runWorkflow("selected"),
    collect: collectSelectedArtifacts,
    tidy: () => runCanvasCleanup("selected"),
    duplicate: duplicateSelectedNodes,
    remove: deleteSelectedNodes,
    fitSelection: () =>
      fitCanvasView({
        nodes: selectedNodeIds.map((id) => ({ id })),
        padding: 0.3,
        maxZoom: 1.2,
      }),
    deleteEdge: (edgeId) => {
      if (!canvasReady || !localAuthoringEnabled || running) return;
      removeCellElements([], [edgeId]);
    },
  };

  const sidePanelView = sidePanel.view;
  const setSidePanelOpen = sidePanel.setOpen;
  const setSidePanelView = sidePanel.setView;
  const sidePanelIsOpen = sidePanel.open;
  const chromeValue = React.useMemo(() => {
    // The rail's item opens its view, or closes the panel when that view is
    // already the one showing.
    const toggleSidePanelView = (view: SidePanelViewId) => {
      closeGraphBrowser();
      setLibraryOpen(false);
      setLabPanelOpen(false);
      if (sidePanelIsOpen && sidePanelView === view) {
        setSidePanelOpen(false);
        return;
      }
      setSidePanelView(view);
      setSidePanelOpen(true);
    };
    return {
      sidePanelOpen: sidePanelIsOpen && sidePanelView === "artifacts",
      toggleSidePanel: () => toggleSidePanelView("artifacts"),
      generatedPanelOpen: sidePanelIsOpen && sidePanelView === "generated",
      toggleGeneratedPanel: () => toggleSidePanelView("generated"),
      activeGraphId: projectId,
      graphName,
      isDirty,
      saving: saving || projectRoom.hasPendingCommands,
      canSave:
        projectId === null &&
        activeGraph === null &&
        localAuthoringEnabled &&
        !saving &&
        !running &&
        !openingGraphId &&
        !deletingGraphId,
      save: async () => {
        if (projectId !== null || activeGraph !== null) return;
        let name = graphName.trim();
        if (!name || name === "Untitled workflow") {
          const next = window.prompt("Name this graph", name || "");
          if (!next?.trim()) return;
          name = next.trim().slice(0, 160);
          setGraphName(name);
        }
        await saveCurrentGraph(name);
      },
      renameGraph: async (graph: SavedGraphSummary, name: string) => {
        // A row in the rail or the browser is a Project. Renaming it is a
        // different act from naming the Graph the canvas shows, which the name
        // field above does with the document.
        if (!canEditProject) {
          throw new Error("You do not have permission to rename Projects.");
        }
        if (graph.id !== projectId || !canSubmitRoomCommands) {
          await renameProjectRemote(workspaceId, graph, name);
          void refreshSavedGraphs();
          return;
        }
        await submitRoomBatch([
          toRoomRenameProjectCommand(name, savedProjectName),
        ]);
        void refreshSavedGraphs();
      },
      deleteGraph: async (graph: SavedGraphSummary) => {
        if (!canDeleteProject) {
          throw new Error("You do not have permission to delete Projects.");
        }
        await removeSavedGraph(graph);
      },
    };
  }, [
    activeGraph,
    canDeleteProject,
    canEditProject,
    canSubmitRoomCommands,
    closeGraphBrowser,
    deletingGraphId,
    graphName,
    isDirty,
    localAuthoringEnabled,
    openingGraphId,
    projectId,
    projectRoom.hasPendingCommands,
    refreshSavedGraphs,
    removeSavedGraph,
    running,
    saveCurrentGraph,
    savedProjectName,
    saving,
    setGraphName,
    setLabPanelOpen,
    setLibraryOpen,
    setSidePanelOpen,
    setSidePanelView,
    sidePanelIsOpen,
    sidePanelView,
    submitRoomBatch,
    workspaceId,
  ]);
  usePublishWorkbenchChrome(chromeValue);

  const cellSelectedCardIds = React.useMemo(
    () => new Set(selectedNodeIds),
    [selectedNodeIds],
  );
  const moveCellCards: NonNullable<CellCanvasProps["onMoveCards"]> = (
    moves,
  ) => {
    if (!localAuthoringEnabledRef.current) return;
    const { graphCommands, viewerPositions, annotationPositions } =
      partitionCellMoves(moves, authoredDocumentRef.current, artifactViewers);
    applyAuthoringCommands(graphCommands);
    if (viewerPositions.length || annotationPositions.length) {
      const viewers = new Map(
        viewerPositions.map(({ viewer_id, x, y }) => [viewer_id, { x, y }]),
      );
      const annotations = new Map(
        annotationPositions.map(({ annotation_id, x, y }) => [
          annotation_id,
          { x, y },
        ]),
      );
      setArtifactViewers((current) => ({
        ...current,
        nodes: current.nodes.map((node) => {
          const position = viewers.get(node.id);
          return position ? { ...node, position } : node;
        }),
        annotations: current.annotations.map((node) => {
          const position = annotations.get(node.id);
          return position ? { ...node, position } : node;
        }),
      }));
      if (viewerPositions.length)
        presentationRoomSyncRef.current.submitMove(viewerPositions);
      if (annotationPositions.length)
        presentationRoomSyncRef.current.submitMoveAnnotations(
          annotationPositions,
        );
    }
  };

  const resizeCellCard: NonNullable<CellCanvasProps["onResizeCard"]> = (
    commit,
  ) => {
    const { cardId, widthCells, heightCells } = commit;
    const width = widthCells * CELL_SIZE;
    const height = heightCells * CELL_SIZE;
    const viewer = artifactViewers.nodes.find((node) => node.id === cardId);
    if (viewer) {
      updateArtifactViewerLayout(cardId, {
        ...viewer.data.layout,
        width,
        bodyHeight: height,
      });
    } else if (artifactViewers.annotations.some((node) => node.id === cardId)) {
      updateAnnotationLayout(cardId, { width, height });
    } else {
      applyAuthoringCommands(
        graphCommandsFromCellResizeForDocument(
          authoredDocumentRef.current,
          commit,
        ),
      );
    }
  };

  const onCellConnectDropEmpty: NonNullable<
    CellCanvasProps["onConnectDropEmpty"]
  > = (event) => {
    closeContextualDiscovery();
    closeInspectedPipe();
    if (!canEditProject || !localAuthoringEnabledRef.current) return;
    const target = document.elementFromPoint(
      event.clientPoint.x,
      event.clientPoint.y,
    );
    if (
      !target?.closest('[data-cell-canvas="true"]') ||
      target.closest(
        '[data-cell-card="true"], [data-cell-canvas-chrome="true"]',
      )
    )
      return;
    if (
      event.direction === "downstream" &&
      event.sourcePortId === ARTIFACT_CARD_OUTPUT_HANDLE
    ) {
      handleArtifactCardConnectionDrop({
        cardId: event.sourceCardId,
        clientPoint: event.clientPoint,
        flowPosition: event.worldPoint,
      });
      return;
    }
    const fromNode = nodes.find((node) => node.id === event.sourceCardId);
    if (!fromNode || !workflowNodeIsSupported(fromNode.data)) return;
    const resolved = resolveCellPortEndpoint(
      fromNode,
      event.sourcePortId,
      event.direction === "upstream" ? "input" : "output",
    );
    if (!resolved) return;
    handleConnectionDrop({
      fromNode,
      ...resolved,
      clientPoint: event.clientPoint,
      flowPosition: event.worldPoint,
    });
  };

  let discoverySourcePoint: XYPosition | null = null;
  if (cellScene && activeContextualDiscovery) {
    const card = cellScene.graph.cards.find(
      ({ id }) => id === activeContextualDiscovery.sourceNodeId,
    );
    if (card) {
      if (activeContextualDiscovery.sourceEndpoint.kind === "artifact-card") {
        const port = card.ports.find(
          ({ id, direction }) =>
            id === ARTIFACT_CARD_OUTPUT_HANDLE && direction === "output",
        );
        if (port) discoverySourcePoint = portWorldCenter(card, port);
      } else {
        const endpoint = activeContextualDiscovery.sourceEndpoint;
        const portId = endpoint.plugId
          ? `${endpoint.portName}::${endpoint.plugId}`
          : endpoint.portName;
        const port = card.ports.find(
          ({ id, direction }) =>
            id === portId && direction === endpoint.direction,
        );
        if (port) discoverySourcePoint = portWorldCenter(card, port);
      }
    }
  }

  const [livePreviewTarget, setLivePreviewTarget] =
    React.useState<NodeLivePreviewTarget | null>(null);

  const activeInspectedPipe = React.useMemo<{
    pipe: CellInspectedPipe;
    anchor: WorldPoint;
  } | null>(() => {
    if (!inspectedPipe || inspectedPipe.graphId !== openGraphId) {
      return null;
    }
    const workflowEdge = canvasEdges.find(
      (edge) => edge.id === inspectedPipe.pipeId,
    );
    if (workflowEdge) {
      return {
        pipe: { kind: "workflow", edge: workflowEdge },
        anchor: inspectedPipe.anchor,
      };
    }
    const originEdge = artifactOriginCanvasEdges.find(
      (edge) => edge.id === inspectedPipe.pipeId,
    );
    if (originEdge) {
      return {
        pipe: { kind: "origin", edge: originEdge },
        anchor: inspectedPipe.anchor,
      };
    }
    const viewerEdge = artifactViewerCanvasEdges.find(
      (edge) => edge.id === inspectedPipe.pipeId,
    );
    if (viewerEdge) {
      return {
        pipe: { kind: "viewer", edge: viewerEdge },
        anchor: inspectedPipe.anchor,
      };
    }
    return null;
  }, [
    artifactOriginCanvasEdges,
    artifactViewerCanvasEdges,
    canvasEdges,

    inspectedPipe,
    openGraphId,
  ]);

  const activeInspectedServicePreview = React.useMemo<{
    readonly providerTitle: string;
    readonly consumerTitle: string;
    readonly target: NodeLivePreviewTarget;
  } | null>(() => {
    if (activeInspectedPipe?.pipe.kind !== "workflow") return null;
    if (!projectId || !openGraphId) return null;
    const edge = activeInspectedPipe.pipe.edge;
    const sourceNode = nodes.find((node) => node.id === edge.source);
    const targetNode = nodes.find((node) => node.id === edge.target);
    if (!sourceNode || !targetNode) return null;
    const targetPort = targetNode.data.spec.inputs.find(
      (port) => port.name === edge.targetPort,
    );
    if (targetPort?.kind !== "service") return null;
    return {
      providerTitle: sourceNode.data.spec.title,
      consumerTitle: targetNode.data.spec.title,
      target: {
        nodeId: targetNode.id,
        nodeTitle: targetNode.data.spec.title,
        subtitle: `${sourceNode.data.spec.title} → ${targetNode.data.spec.title}`,
      },
    };
  }, [activeInspectedPipe, nodes, openGraphId, projectId]);

  // Offered when a dragged output has no compatible node: show its artifacts.
  const placeDiscoveredOutputCard =
    activeContextualDiscovery?.direction === "downstream" &&
    activeContextualDiscovery.sourceEndpoint.kind === "port"
      ? () => {
          if (activeContextualDiscovery.sourceEndpoint.kind === "port") {
            placeOutputCard(
              activeContextualDiscovery.sourceNodeId,
              activeContextualDiscovery.sourceEndpoint.portName,
              activeContextualDiscovery.flowPosition,
            );
          }
        }
      : undefined;

  const showArtifactCollect =
    collectSpec !== null
      ? selectedCollectionSources.length > 1
      : collectsIntoSequence;
  const showTidySelection = selectedForegroundCount > 1;
  const selectionToolbar =
    showArtifactCollect || showTidySelection ? (
      <>
        <span {...stylex.props(s.selectionLabel)}>
          {selectedNodeCount} selected
        </span>
        <span aria-hidden="true" {...stylex.props(s.selectionDivider)} />
        {collectSpec ? (
          selectedCollectionSources.length > 1 ? (
            <Button
              type="button"
              variant="primary"
              size="sm"
              disabled={
                !localAuthoringEnabled || Boolean(collectionDisabledReason)
              }
              title={
                collectionDisabledReason ??
                `Collect ${selectedCollectionSources.length} selected artifacts into one collection`
              }
              xstyle={phoneTouch.rail}
              onClick={collectSelectedArtifacts}
            >
              <Layers size={13} />
              Collect
            </Button>
          ) : null
        ) : collectsIntoSequence ? (
          <Button
            type="button"
            variant="primary"
            size="sm"
            disabled={
              !collectedArtifactRefs ||
              !localAuthoringEnabled ||
              Boolean(groupingDisabledReason)
            }
            title={
              groupingDisabledReason ??
              (collectedArtifactRefs
                ? selectedArtifactCards.length === 1
                  ? "Put this artifact in a sequence"
                  : `Collect ${selectedArtifactCards.length} selected artifacts into an ordered sequence`
                : "Select artifacts of the same type to collect")
            }
            xstyle={phoneTouch.rail}
            onClick={collectSelectedArtifacts}
          >
            <Layers size={13} />
            Collect
          </Button>
        ) : null}
        {showTidySelection ? (
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!canTidySelection}
            title="Resize and arrange the selected cards left to right"
            xstyle={phoneTouch.rail}
            onClick={() => runCanvasCleanup("selected")}
          >
            <LayoutGrid size={13} />
            Tidy up
          </Button>
        ) : null}
      </>
    ) : null;

  return (
    <main {...stylex.props(s.shell)}>
      <span
        role="status"
        aria-live="polite"
        aria-atomic="true"
        {...stylex.props(s.visuallyHidden)}
      >
        {executionAnnouncement}
      </span>
      {projectId ? (
        <GraphRoomRecoveryNotice
          readiness={projectReadiness.state}
          status={projectRoom.status}
          failure={projectRoom.failure}
          terminalReason={projectRoom.terminalReason}
          onRetry={projectRoom.retry}
          onReload={() => window.location.reload()}
        />
      ) : null}
      <section
        ref={canvasSectionRef}
        {...stylex.props(s.canvas)}
        aria-label="Workflow canvas"
        onPointerDownCapture={canvasMenuTrigger.onPointerDownCapture}
        onContextMenu={canvasMenuTrigger.onContextMenu}
        onKeyDown={canvasMenuTrigger.onKeyDown}
        onPointerMove={onCanvasPointerMove}
        onPointerLeave={onCanvasPointerLeave}
      >
        {projectHasNoGraph ? (
          <div role="status" {...stylex.props(emptyProjectStyles.panel)}>
            <p {...stylex.props(emptyProjectStyles.title)}>
              This Project holds no Graphs.
            </p>
            <p {...stylex.props(emptyProjectStyles.body)}>
              A Graph is the canvas of nodes you compute with. Add one to start
              building here.
            </p>
            <Button
              type="button"
              variant="primary"
              size="sm"
              disabled={!canSubmitRoomCommands}
              title={
                canSubmitRoomCommands
                  ? "Add a Graph to this Project"
                  : "Editing is paused until the Project room is ready."
              }
              xstyle={phoneTouch.rail}
              onClick={addProjectGraph}
            >
              <Plus size={13} />
              Add a Graph
            </Button>
          </div>
        ) : null}
        {projectRoom.head && projectRoom.head.document.graphs.length > 0 ? (
          <GraphSwitcher
            graphs={projectRoom.head.document.graphs}
            openGraphId={openGraphId}
            canEdit={canSubmitRoomCommands && !running}
            onOpen={openProjectGraph}
            onAdd={addProjectGraph}
            onRename={renameProjectGraph}
            onDelete={removeProjectGraph}
            selectedCall={selectedCall}
            onOpenCall={openCall}
            callTrail={callTrail}
            onBackFromCall={backFromCall}
          />
        ) : null}
        <NodeMenuRegistryContext.Provider value={nodeMenus}>
          {canEditProject &&
          localAuthoringEnabled &&
          cellScene &&
          cellScene.graph.cards.length === 0 ? (
            <div {...stylex.props(s.emptyCanvas)}>
              <EmptyCanvasStarter
                status={canvasUpload}
                samplePending={samplePending}
                onFiles={(files) => {
                  void uploadFilesOntoCanvas(
                    files,
                    canvasCenter({ x: 80, y: 80 }),
                  );
                }}
                onSample={() => {
                  void placeStarterSample();
                }}
                onBrowseSteps={() => setLibraryOpen(true)}
                onCreateArtifact={() => openCreateArtifact()}
              />
            </div>
          ) : canvasUpload ? (
            <div {...stylex.props(s.emptyCanvas)} role="status">
              {canvasUpload}
            </div>
          ) : null}
          {cellScene && (
            <SelectionLinksContext.Provider value={selectionLinks.context}>
              <PresenceAwareCellCanvas
                presenceStore={projectRoom.presenceStore}
                localSessionId={projectRoom.localSessionId}
                graphId={openGraphId}
                {...cellScene}
                look={cellLook}
                routing={cellRouting}
                editable={localAuthoringEnabled}
                selectedCardIds={cellSelectedCardIds}
                selectedPipeIds={selectedEdgeIdSet}
                inspectedPipeId={activeInspectedPipe?.pipe.edge.id ?? null}
                autoFitOnMount={false}
                exposeDebugApi={process.env.NODE_ENV !== "production"}
                onHandleReady={setCellCanvasHandle}
                onViewportZoomChange={setViewportZoom}
                onMoveCards={moveCellCards}
                onDragCardsProgress={onDragCardsProgress}
                onResizeCard={resizeCellCard}
                onCanConnect={(candidate) => {
                  const connection = cellConnectionToWorkbenchConnection(
                    nodes,
                    artifactViewers.nodes,
                    candidate,
                  );
                  return connection !== null && isValidConnection(connection);
                }}
                onConnect={(candidate) => {
                  const connection = cellConnectionToWorkbenchConnection(
                    nodes,
                    artifactViewers.nodes,
                    candidate,
                  );
                  if (connection) onConnect(connection);
                }}
                onConnectDropEmpty={onCellConnectDropEmpty}
                onArtifactNextStep={
                  localAuthoringEnabled ? continueFromArtifactCard : undefined
                }
                onRemoveCards={(ids) => removeCellElements(ids, [])}
                onRemovePipes={(ids) => removeCellElements([], ids)}
                onSelectionChange={(selection) =>
                  canvasSelection.selectOnly(
                    partitionCellSelection(
                      selection,
                      authoredDocumentRef.current,
                      artifactViewers,
                    ),
                  )
                }
                onPaneClick={() => {
                  onCloseGraphBrowser();
                  closeGridPanel();
                  closeCanvasPopovers(false);
                }}
                onSelectEdgeAttachment={(pipeId, anchor) =>
                  toggleInspectedPipe(
                    openGraphId,
                    pipeId,
                    anchor ?? canvasCenter({ x: 0, y: 0 }),
                  )
                }
                onOperatorRun={(cardId) => {
                  canvasSelection.selectOnly({ nodeIds: [cardId] });
                  void runWorkflow("selected", [cardId]);
                }}
                onOperatorConfigChange={updateConfig}
                onOperatorToggleConfigSection={setConfigSection}
                onOperatorApplySecret={
                  canManageSecrets ? applyConfiguredNodeSecret : undefined
                }
                onOperatorRemoveSecret={
                  canManageSecrets ? removeConfiguredNodeSecret : undefined
                }
                onOperatorAddPlug={addNodeInputPlug}
                onOperatorRemovePlug={(cardId, portName, plugId) =>
                  removeNodeInputPlug(
                    cardId,
                    plugId.startsWith(`${portName}::`)
                      ? plugId.slice(portName.length + 2)
                      : plugId,
                  )
                }
                onOperatorToggleAppendix={toggleAppendix}
                onPickServiceEngine={
                  localAuthoringEnabled ? pickEngine : undefined
                }
                onAnnotationColorChange={(cardId, color) =>
                  updateAnnotationColor(cardId, annotationHexFromToken(color))
                }
                canMergeArtifactCards={canMergeArtifactCards}
                onMergeArtifactCards={mergeArtifactCards}
                onReorderArtifactCardItem={reorderArtifactCardItem}
                onMergeArtifactCardRun={mergeArtifactCardRun}
                onInsertArtifactCardIntoSequence={
                  insertArtifactCardIntoSequence
                }
                onExtractArtifactCardItem={extractArtifactCardItem}
                onRemoveArtifactCardItem={removeArtifactCardItem}
                onUngroupArtifactCard={ungroupArtifacts}
                onArtifactDownload={onArtifactDownload}
                onArtifactSaveToLibrary={
                  canEditProject ? onArtifactSaveToLibrary : undefined
                }
                onArtifactEdit={
                  localAuthoringEnabled ? openEditArtifact : undefined
                }
                onArtifactDuplicateAndEdit={
                  localAuthoringEnabled ? openDuplicateArtifact : undefined
                }
                inlineEditingCardId={inlineEditingCardId}
                onSetInlineEditingCardId={setInlineEditingCardId}
                onInlineArtifactSaved={handleInlineArtifactSaved}
                onArtifactImageLoad={onCellArtifactImageLoad}
                onCollectionRemoveMember={(cardId, memberId) =>
                  removeNodeInputPlug(
                    cardId,
                    memberId.startsWith(`${COLLECTION_PORT}::`)
                      ? memberId.slice(COLLECTION_PORT.length + 2)
                      : memberId,
                  )
                }
              >
                {selectionToolbar ? (
                  <div
                    data-cell-canvas-chrome="true"
                    {...stylex.props(
                      s.selectionToolbar,
                      s.cellSelectionToolbar,
                    )}
                    onPointerDown={(event) => event.stopPropagation()}
                  >
                    {selectionToolbar}
                  </div>
                ) : null}
                {registry && activeContextualDiscovery ? (
                  <CellContextualNodeDiscovery
                    key={`${activeContextualDiscovery.sourceNodeId}:${JSON.stringify(activeContextualDiscovery.sourceEndpoint)}:${activeContextualDiscovery.flowPosition.x}:${activeContextualDiscovery.flowPosition.y}`}
                    session={activeContextualDiscovery}
                    registry={registry}
                    sourcePoint={discoverySourcePoint}
                    canInsert={localAuthoringEnabled}
                    insertDisabledReason={localAuthoringBlockedMessage}
                    onClose={() => {
                      if (activeContextualDiscovery.trigger === "port_prompt") {
                        closePrompt();
                      }
                      closeContextualDiscovery();
                    }}
                    onConfirm={confirmContextualDiscovery}
                    onPlaceOutputCard={placeDiscoveredOutputCard}
                  />
                ) : null}
                {activeInspectedPipe ? (
                  <CellPipeInspector
                    pipe={activeInspectedPipe.pipe}
                    anchor={activeInspectedPipe.anchor}
                    editable={localAuthoringEnabled && !running}
                    servicePreview={
                      activeInspectedServicePreview
                        ? {
                            summary: `${activeInspectedServicePreview.providerTitle} → ${activeInspectedServicePreview.consumerTitle}`,
                            hint: "Stream live frames (contact sheets, crops, or pages) processed by this node.",
                            actionLabel: "Live preview",
                            onInspect: () =>
                              setLivePreviewTarget(
                                activeInspectedServicePreview.target,
                              ),
                          }
                        : null
                    }
                    onClose={closeInspectedPipe}
                    onUpdateWorkflowEdge={updateEdge}
                    onUpdateOriginCollectionMode={(originId, collectionMode) =>
                      applyAuthoringCommands([
                        {
                          kind: "update_origin",
                          origin_id: originId,
                          update: { collection_mode: collectionMode },
                        },
                      ])
                    }
                    onUpdateViewerEdge={updateArtifactViewerEdge}
                    onRemovePipe={(pipeId) => removeCellElements([], [pipeId])}
                  />
                ) : null}
              </PresenceAwareCellCanvas>
            </SelectionLinksContext.Provider>
          )}
          <PresenceOverlay
            store={projectRoom.presenceStore}
            graphId={openGraphId}
          />
        </NodeMenuRegistryContext.Provider>
      </section>

      <LinkedViewActivityToast
        activity={viewerActivity}
        onRetry={viewerActivity?.retry}
        onDismiss={
          viewerActivity &&
          (viewerActivity.state === "warning" ||
            viewerActivity.state === "error")
            ? dismissLinkedView
            : undefined
        }
      />

      {canvasLabEnabled && labPanelOpen && (
        <CanvasLabPanel
          close={() => setLabPanelOpen(false)}
          xstyle={s.canvasLabDock}
        />
      )}

      <aside aria-label="Canvas actions" {...stylex.props(s.toolDock)}>
        <IconButton
          size="lg"
          variant="ghost"
          label="Add node"
          title="Add node"
          aria-pressed={libraryOpen}
          disabled={!registry || !localAuthoringEnabled}
          xstyle={[
            phoneTouch.rail,
            s.dockButton,
            libraryOpen && s.dockButtonActive,
          ]}
          {...firefoxDynamicButtonProps}
          onClick={() => {
            closeGraphBrowser();
            setLabPanelOpen(false);
            toggleLibrary();
          }}
        >
          <Plus size={14} />
        </IconButton>
        <IconButton
          size="lg"
          variant="ghost"
          label="Create artifact"
          title="Create artifact"
          disabled={!localAuthoringEnabled}
          xstyle={[phoneTouch.rail, s.dockButton]}
          {...firefoxDynamicButtonProps}
          onClick={() => {
            closeGraphBrowser();
            setLibraryOpen(false);
            setLabPanelOpen(false);
            openCreateArtifact();
          }}
        >
          <FilePlus2 size={14} />
        </IconButton>
        <div {...stylex.props(s.shapesMenuWrap)}>
          <IconButton
            size="lg"
            variant="ghost"
            label="Add shape or text"
            title="Add documentation shapes"
            aria-pressed={shapesMenuOpen}
            disabled={!localAuthoringEnabled}
            aria-expanded={shapesMenuOpen}
            aria-haspopup="menu"
            xstyle={[
              phoneTouch.rail,
              s.dockButton,
              shapesMenuOpen && s.dockButtonActive,
            ]}
            onClick={() => {
              closeGraphBrowser();
              setLibraryOpen(false);
              setLabPanelOpen(false);
              toggleShapesMenu();
            }}
          >
            <Type size={14} />
          </IconButton>
          {shapesMenuOpen ? (
            <div role="menu" {...stylex.props(s.shapesMenu)}>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                role="menuitem"
                xstyle={s.railMenuButton}
                onClick={() => addAnnotation("text")}
              >
                <Type size={14} />
                Text
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                role="menuitem"
                xstyle={s.railMenuButton}
                onClick={() => addAnnotation("rectangle")}
              >
                <Square size={14} />
                Square
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                role="menuitem"
                xstyle={s.railMenuButton}
                onClick={() => addAnnotation("ellipse")}
              >
                <Circle size={14} />
                Circle
              </Button>
            </div>
          ) : null}
        </div>
        <IconButton
          size="lg"
          variant="ghost"
          label="Add Agent"
          title="Add an Agent to chat with on the canvas"
          disabled={!canEditProject}
          xstyle={[phoneTouch.rail, s.dockButton]}
          {...firefoxDynamicButtonProps}
          onClick={() => {
            const id = createUuid();
            applyAuthoringCommands([
              {
                kind: "add_agent",
                agent: {
                  id,
                  name: "Agent",
                  instructions: "",
                  model: { kind: "deployment" },
                  context: [],
                  tools: [],
                  position: canvasCenter({ x: 480, y: 240 }),
                  width: 360,
                  height: 480,
                },
              },
            ]);
            canvasSelection.selectOnly({ agentIds: [id] });
          }}
        >
          <Bot size={14} />
        </IconButton>
        <span aria-hidden="true" {...stylex.props(s.railDivider)} />
        <IconButton
          size="lg"
          variant="ghost"
          label="Runs"
          title={
            projectId
              ? "Browse this Project's Runs"
              : "Save the Project to browse its Runs"
          }
          disabled={!projectId}
          xstyle={[phoneTouch.rail, s.dockButton]}
          onClick={(event) => {
            setLibraryOpen(false);
            setLabPanelOpen(false);
            executionHistoryReturnFocusRef.current = event.currentTarget;
            openExecutionHistory({ nodeId: null, executionId: null });
          }}
        >
          <History size={14} />
        </IconButton>
        <span aria-hidden="true" {...stylex.props(s.railDivider)} />
        <div ref={cleanupWrapRef} {...stylex.props(s.shapesMenuWrap)}>
          <IconButton
            size="lg"
            variant="ghost"
            label="Clean up canvas"
            title={
              foregroundCardCount
                ? "Configure and run canvas cleanup"
                : "Add cards to clean up the canvas"
            }
            aria-pressed={cleanupPanelOpen}
            aria-expanded={cleanupPanelOpen}
            aria-haspopup="dialog"
            disabled={!canCleanUpCanvas}
            xstyle={[
              phoneTouch.rail,
              s.dockButton,
              cleanupPanelOpen && s.dockButtonActive,
            ]}
            onClick={() => {
              closeGraphBrowser();
              setLibraryOpen(false);
              setLabPanelOpen(false);
              closeCanvasPopovers(false);
              setCleanupPanelOpen((open) => !open);
            }}
          >
            <LayoutGrid size={14} />
          </IconButton>
          {cleanupPanelOpen && canCleanUpCanvas ? (
            <CanvasCleanupPopover
              params={cleanupParams}
              onChange={setCleanupParams}
              onReset={() => setCleanupParams(DEFAULT_CELL_CLEANUP_PARAMS)}
              onApply={(scope) => runCanvasCleanup(scope)}
              onUndo={undoCanvasCleanup}
              onRevertInitial={revertCanvasCleanupToInitial}
              onClose={() => setCleanupPanelOpen(false)}
              selectedCount={selectedForegroundCount}
              canApply={canCleanUpCanvas}
              undoCount={cleanupUndoCount}
            />
          ) : null}
        </div>
        <IconButton
          size="lg"
          variant="ghost"
          label="Duplicate"
          title={
            selectedWorkflowCount || selectedViewerCount
              ? `Duplicate ${selectedWorkflowCount + selectedViewerCount} selected node${selectedWorkflowCount + selectedViewerCount === 1 ? "" : "s"}`
              : "Select one or more nodes to duplicate"
          }
          disabled={
            (!selectedWorkflowCount && !selectedViewerCount) ||
            !localAuthoringEnabled
          }
          xstyle={[phoneTouch.rail, s.dockButton]}
          onClick={duplicateSelectedNodes}
        >
          <Copy size={14} />
        </IconButton>
        <IconButton
          size="lg"
          variant="danger"
          label="Delete"
          title={
            selectedNodeCount
              ? `Delete ${selectedNodeCount} selected node${selectedNodeCount === 1 ? "" : "s"}`
              : "Select one or more nodes to delete"
          }
          disabled={
            !canvasReady || !selectedNodeCount || !localAuthoringEnabled
          }
          xstyle={[phoneTouch.rail, s.dockDangerButton]}
          onClick={deleteSelectedNodes}
        >
          <Trash2 size={14} />
        </IconButton>
      </aside>

      <CanvasZoomControls
        zoom={viewportZoom}
        disabled={!canvasReady}
        onZoomIn={() => cellCanvasHandle?.zoomIn()}
        onZoomOut={() => cellCanvasHandle?.zoomOut()}
        onResetZoom={() => cellCanvasHandle?.resetZoom()}
        onFitView={() => fitCanvasView(WORKBENCH_FIT_VIEW)}
      />

      <Toast.Provider timeout={8000} limit={3} toastManager={toastManager}>
        <GlobalIssueToastList
          issues={globalIssues}
          onDismiss={dismissGlobalIssue}
        />
      </Toast.Provider>
      <EngineConnectNotice
        lead={engineConnectNotice?.lead ?? null}
        onUndo={undoEngineConnect}
        onDismiss={dismissEngineConnectNotice}
      />
      <CanvasCleanupNotice
        noticeKey={activeCleanupToast?.key ?? null}
        lead={activeCleanupToast?.lead ?? null}
        onUndo={undoCanvasCleanup}
        onDismiss={() =>
          setCleanupHistory((current) =>
            current ? { ...current, toast: null } : null,
          )
        }
      />

      {executionHistoryTarget ? (
        <ExecutionHistoryDrawer
          key={`${projectId ?? "unsaved"}:${executionHistoryTarget.nodeId ?? "all"}:${executionHistoryTarget.executionId ?? "latest"}`}
          workspaceId={workspaceId}
          // A Run is a demand inside a Project: without this the drawer's read key
          // never resolves and it can only ever say "open a saved project", which
          // made the way to see Runs unreachable from the product while its own
          // tests kept passing a projectId the caller never sent.
          projectId={projectId}
          graphId={openGraphId}
          returnFocusRef={executionHistoryReturnFocusRef}
          onClose={closeExecutionHistory}
        />
      ) : null}

      <CanvasContextMenu
        request={canvasMenu}
        registry={registry ?? null}
        activeGraphId={openGraphId}
        canEdit={localAuthoringEnabled}
        managePacksHref={managePacksHref}
        selection={canvasMenuSelection}
        nodeMenus={nodeMenus}
        actions={canvasMenuActions}
        onClose={closeContextMenu}
      />

      <WorkbenchSidePanel
        workspaceId={workspaceId}
        sidePanel={sidePanel}
        projectId={projectId}
        graphId={openGraphId}
        nodeTitles={nodeTitles}
        registry={registry ?? null}
        canSave={canEditProject}
        // A stored result belongs to an instance, and the room is what says one
        // landed; that push is the panel's cue to read the list again.
        generatedRefreshToken={projectRoom.instancesRevision}
        onOpenInstance={(graphId) => {
          if (graphId !== openGraphId) {
            // A saved artifact can come from another Graph, and every Graph of
            // this Project lives behind this address.
            openProjectInNewTab();
            return;
          }
          executionHistoryReturnFocusRef.current = null;
          openExecutionHistory({ nodeId: null, executionId: null });
        }}
      />

      {registry ? (
        <NodeSelector
          open={libraryOpen}
          registry={registry}
          activeGraphId={openGraphId}
          canInsert={localAuthoringEnabled}
          insertDisabledReason={localAuthoringBlockedMessage}
          onOpenChange={(open) => setLibraryOpen(open, libraryInsertAt)}
          onAddNode={(spec) => addCatalogNode(spec)}
          managePacksHref={managePacksHref}
        />
      ) : null}

      <ArtifactEditorDialog
        session={artifactEditor}
        workspaceId={workspaceId}
        artifactTypes={registry?.artifact_types ?? []}
        onSaved={handleArtifactEditorSaved}
        onClose={() => setArtifactEditor(null)}
      />

      <SelectionLinkDialog
        editor={selectionLinks.editor}
        cards={selectionLinks.cards}
        fields={selectionLinks.fields}
        dispatch={selectionLinks.dispatch}
      />

      <NodeLivePreviewModal
        open={livePreviewTarget !== null}
        onOpenChange={(nextOpen) => {
          if (!nextOpen) setLivePreviewTarget(null);
        }}
        workspaceId={workspaceId}
        projectId={projectId}
        graphId={openGraphId}
        target={livePreviewTarget}
      />

      <ArtifactFolderDropDialog
        pending={pendingFolderDrop?.drop ?? null}
        onPlaceAll={() =>
          placeFolderDropGroups(pendingFolderDrop?.drop.groups ?? [])
        }
        onPlaceGroup={(group) => placeFolderDropGroups([group])}
        onClose={() => setPendingFolderDrop(null)}
      />

      <ConnectionRouteDialog
        pendingRoute={pendingConnectionRoute}
        onSelect={(route) => {
          if (!pendingConnectionRoute) return;
          const refineEdgeId = pendingConnectionRoute.refineEdgeId;
          if (refineEdgeId) {
            const selection = connectionRouteSelection(route);
            updateEdge(refineEdgeId, {
              route: {
                projection: selection.projection
                  ? { path: [...selection.projection.path] }
                  : undefined,
                conversionPath: selection.conversionPath.map((conversion) => ({
                  id: conversion.id,
                  version: conversion.version,
                })),
              },
            });
            return;
          }
          addWorkflowEdge(
            pendingConnectionRoute.connection,
            pendingConnectionRoute.collectionMode,
            route,
          );
        }}
        onClose={() => setPendingConnectionRoute(null)}
      />
    </main>
  );
}
