"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import * as stylex from "@stylexjs/stylex";
import { Toast } from "@base-ui/react/toast";
import {
  NodeToolbar,
  Position,
  type Connection,
  type EdgeChange,
  type IsValidConnection,
  type NodeChange,
  type OnConnect,
  type OnConnectEnd,
  type OnEdgesChange,
  type OnNodesChange,
  type ReactFlowInstance,
} from "@xyflow/react";
import {
  Circle,
  Copy,
  Eye,
  Grid3x3,
  History,
  Layers,
  LoaderCircle,
  Maximize2,
  Package,
  Play,
  Plus,
  Square,
  Trash2,
  Type,
  Upload,
  Workflow,
} from "lucide-react";

import { ExecutionHistoryDrawer } from "./ExecutionHistoryDrawer";
import { WorkbenchSidePanel } from "./side-panel/WorkbenchSidePanel";
import {
  useWorkbenchSidePanel,
  type SidePanelViewId,
} from "./side-panel/workbench-side-panel-state";
import { GraphRoomRecoveryNotice } from "./GraphRoomRecoveryNotice";
import { GlobalIssueToastList, type GlobalIssue } from "./GlobalIssueToastList";
import {
  WorkbenchActivityBar,
  type WorkbenchActivity,
} from "./WorkbenchActivityBar";
import {
  ConnectionRouteDialog,
  type PendingConnectionRoute,
} from "./ConnectionRouteDialog";
import { CanvasGridSettingsPanel } from "./CanvasGridSettingsPanel";
import { workbenchStyles as s } from "./Workbench.styles";
import { NodeSelector } from "./NodeSelector";
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
} from "../canvas/nodes/node-menu-registry";
import {
  ContextualNodeDiscovery,
  type ContextualDiscoverySession,
} from "./ContextualNodeDiscovery";
import type {
  ContextualCandidate,
  ContextualRouteChoice,
} from "../model/node-catalog";
import { PublishModuleDialog } from "./PublishModuleDialog";
import { moduleBoundaries } from "../model/module-boundary";
import { createUuid } from "@/features/workbench/model/uuid";
import { artifactGroupingDisabledReason } from "../model/artifact-grouping";
import { WorkspaceLibraryDialog } from "@/features/workspaces/WorkspaceLibraryDialog";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { usePublishWorkbenchChrome } from "./WorkbenchChromeContext";
import { renameSavedGraphRemote } from "@/features/workspaces/graph-actions";
import type { SavedGraphSummary } from "@/lib/api";
import {
  CanvasGridSettingsProvider,
  useCanvasGridSettings,
} from "../canvas/canvas-grid-settings";
import { validateConfig } from "../canvas/config-schema";
import {
  layoutSnapAxes,
  shouldSnapPosition,
  snapNodeLayout,
  snapPosition,
} from "../canvas/grid-layout";
import {
  DEFAULT_APPENDIX_HEIGHT,
  DEFAULT_NODE_PLACEMENT_HEIGHT,
  DEFAULT_NODE_WIDTH,
} from "../canvas/node-layout";
import { useNodeSecrets } from "./useNodeSecrets";
import {
  useSavedGraphLifecycle,
  type GraphRoomPersistenceAdapter,
} from "./useSavedGraphLifecycle";
import { useRunExecution } from "./useRunExecution";
import {
  shouldBlockAuthoringCommand,
  type AuthoringCommandOptions,
} from "./authoring-command-guard";
import {
  GraphRoomCommandError,
  PRESENCE_CLIENT_MIN_INTERVAL_MS,
  PresenceOverlay,
  graphReadiness,
  remoteSelectionColor,
  shouldReplaceCollaborativeHead,
  toLocalGraphCommand,
  toRoomGraphCommand,
  toRoomReplaceDocumentCommand,
  useGraphRoomSession,
  useRemoteDragPreviews,
  type RoomGraphCommand,
  type TransientNodePosition,
} from "../room";
import {
  checkpointGraph,
  getCollaborativeHead,
  type CollaborativeHead,
} from "@/lib/api";
import {
  WorkflowCanvas,
  applyEdgeChanges,
  applyNodeChanges,
} from "../canvas/WorkflowCanvas";
import {
  addNodeCommand,
  addEdgeCommand,
  graphCommandsFromEdgeChanges,
  graphCommandsFromNodeChanges,
  nodeOverlaysFromNodes,
  reduceWorkbenchAuthoringState,
} from "../canvas/graph-document-adapter";
import {
  ANNOTATION_NODE_TYPE,
  ANNOTATION_Z_INDEX,
  createAnnotationNode,
  type AnnotationKind,
  type AnnotationNode,
} from "../canvas/annotations";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INPUT_HANDLE,
  ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE,
  ARTIFACT_VIEWER_INTERACTION_INPUT_HANDLE,
  ARTIFACT_VIEWER_INTERACTION_OUTPUT_HANDLE,
  ARTIFACT_VIEWER_NODE_TYPE,
  artifactViewersFromPresentation,
  presentationFromArtifactViewers,
  type ArtifactViewerCanvasState,
  type ArtifactViewerEdge,
  type ArtifactViewerInteractionEdge,
  type ArtifactViewerNode,
  type CanvasEdge,
  type CanvasNode,
  type GraphPresentation,
} from "../canvas/artifact-viewer";
import { ARTIFACT_ORIGIN_EDGE_TYPE } from "../canvas/artifact-origin-edge";
import {
  ARTIFACT_CARD_OUTPUT_HANDLE,
  artifactOriginConnections,
  resolveArtifactCardConnection,
} from "../canvas/artifact-connections";
import {
  DEFAULT_ARTIFACT_CARD_WIDTH,
  artifactCardContract,
  artifactCardMediaHeight,
  cardArtifactRefs,
  collectArtifactCardRefs,
  originCarriesCardArtifacts,
} from "../canvas/artifact-card";
import { formatArtifactTypeLabel } from "../canvas/artifact-type-label";
import {
  hydrateAuthoredGraphDocument,
  savedGraphExecutionFingerprint,
} from "../canvas/saved-graph";
import {
  EMPTY_ARTIFACT_KEY_SELECTION,
  targetRowsForBinding,
  type ArtifactInteractionField,
  type ArtifactKeySelection,
  type ArtifactViewerActivity,
  type ArtifactViewerBinding,
} from "../canvas/artifact-interactions";
import {
  canonicalHandleId,
  connectionRouteForSelection,
  connectionRouteMatchesSelection,
  connectionRouteSelection,
  connectionRoutesFor,
  decodedHandleArtifactType,
  decodeHandleId,
  encodeHandleId,
  type ConnectionRoute,
} from "../canvas/handles";
import {
  COLLECTION_PORT,
  collectDisabledReason,
  collectionHoldsArtifacts,
  collectionMembers,
  collectionsWithoutSpare,
  isCollectionNode,
  isCollectionSpec,
  ungroupCollectionDisabledReason,
  type CollectionSource,
} from "../model/collection";
import {
  nodeSecretBindingReady,
  nodeSecretInputs,
} from "../canvas/node-secrets";
import { artifactTypeColor } from "../canvas/nodes.css";
import {
  WORKFLOW_EDGE_TYPE,
  WORKFLOW_NODE_TYPE,
  createWorkflowNodeData,
  effectivePortShape,
  resolvedPortArtifactType,
  type WorkflowEdge,
  type WorkflowEdgeRouteOffset,
  type WorkflowEdgeRouteOption,
  type WorkflowEdgeUpdate,
  type WorkflowArtifactTypeBindings,
  type WorkflowNodeData,
  portMetaForPort,
  workflowNodeIsSupported,
} from "../canvas/types";
import {
  orderFeedRoutes,
  preferredWholeFeedRoute,
  routesForHandleFeed,
} from "../model/connection-feeds";
import {
  artifactDropCommands,
  artifactDropTargetFromRow,
  isArtifactDrop,
  readArtifactDrop,
  readArtifactDropGroups,
} from "../model/artifact-drop";
import {
  collectionModeForConnection,
  inputPlugBindingsForNode,
  isConnectionAccepted,
  mappedInputPortForNode,
  workflowEdgeRouteOption,
} from "../model/graph-authoring";
import {
  createSavedGraphRequest,
  type AuthoredGraphDocument,
  type GraphCommand,
} from "../model/graph-document";
import {
  selectedNodeAndAncestorIds,
  type WorkflowNode,
} from "../model/execution-plan";
import {
  catalogNodeSpecs,
  downstreamCandidatesFromOutput,
  moduleCallUpgradeTarget,
  pluginReleaseUpgradeTarget,
  upstreamCandidatesFromInput,
} from "../model/node-catalog";
import { workbenchGraphPath } from "../routes";
import { useNodeRegistry } from "@/hooks/use-api";
import {
  artifactDropRowAt,
  artifactDropTargetFitsNode,
  canvasAtPoint,
} from "./artifact-drop-hit-test";
import { useWorkbenchFitViewOptions } from "./useWorkbenchFitViewOptions";
import { useArtifactViewerCommands } from "./workbench-artifact-viewers";
import { useNodeCommands } from "./workbench-node-commands";
import {
  artifactCardDropPositions,
  useArtifactCardCommands,
} from "./workbench-artifact-cards";
import {
  type ArtifactTypeKey,
  type NodeSpec,
  type RunEdgeCollectionMode,
} from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";

interface WorkbenchProps {
  workspaceId: string;
  workspaceSlug: string;
  initialGraphId: string | null;
}

interface PendingBoundEdge {
  nodeId: string;
  variable: string;
  artifactType: ArtifactTypeKey;
  edge: WorkflowEdge;
}

interface ActiveArtifactViewerActivity {
  activity: ArtifactViewerActivity;
  revision: number;
}

export function Workbench(props: WorkbenchProps) {
  return (
    <CanvasGridSettingsProvider>
      <WorkbenchBody {...props} />
    </CanvasGridSettingsProvider>
  );
}

function WorkbenchBody({
  workspaceId,
  workspaceSlug,
  initialGraphId,
}: WorkbenchProps) {
  const workbenchFitViewOptions = useWorkbenchFitViewOptions();
  const {
    data: registry,
    error: registryError,
    mutate: refreshNodeRegistry,
  } = useNodeRegistry(workspaceId);
  const {
    settings: canvasGridSettings,
    bypassSnap,
    panelOpen: gridPanelOpen,
    setPanelOpen: setGridPanelOpen,
  } = useCanvasGridSettings();
  const canvasGridSettingsRef = React.useRef(canvasGridSettings);
  const bypassSnapRef = React.useRef(bypassSnap);
  const [authoringState, dispatchAuthoringState] = React.useReducer(
    reduceWorkbenchAuthoringState,
    {
      document: {
        name: "Untitled workflow",
        nodes: [],
        edges: [],
        origins: [],
      },
      nodeOverlays: {},
      error: null,
    },
  );
  const authoredDocument = authoringState.document;
  const nodeOverlays = authoringState.nodeOverlays;
  const authoredDocumentRef = React.useRef(authoredDocument);
  const nodeOverlaysRef = React.useRef(nodeOverlays);
  React.useLayoutEffect(() => {
    canvasGridSettingsRef.current = canvasGridSettings;
    bypassSnapRef.current = bypassSnap;
    nodeOverlaysRef.current = nodeOverlays;
  }, [bypassSnap, canvasGridSettings, nodeOverlays]);
  const [selectedNodeIdSet, setSelectedNodeIdSet] = React.useState<
    ReadonlySet<string>
  >(new Set());
  const [selectedEdgeIdSet, setSelectedEdgeIdSet] = React.useState<
    ReadonlySet<string>
  >(new Set());
  const [positionOverrides, setPositionOverrides] = React.useState<
    Record<string, { x: number; y: number }>
  >({});
  const [transientNodePositions, setTransientNodePositions] = React.useState<
    Record<string, { x: number; y: number }>
  >({});
  // React Flow keeps nodes at visibility:hidden until measured width/height are
  // present on the controlled node objects. Authored-document hydration never
  // carries those fields, so dimension changes must be stored separately and
  // merged back in — otherwise nodes stay invisible after the first remount.
  const [nodeMeasurements, setNodeMeasurements] = React.useState<
    Readonly<Record<string, { width: number; height: number }>>
  >({});
  const hydratedDocument = React.useMemo(
    () =>
      registry
        ? hydrateAuthoredGraphDocument(authoredDocument, registry)
        : { nodes: [], edges: [] },
    [authoredDocument, registry],
  );
  const nodesRef = React.useRef<WorkflowNode[]>([]);
  const edgesRef = React.useRef<WorkflowEdge[]>([]);
  const nodes = React.useMemo<WorkflowNode[]>(
    () =>
      hydratedDocument.nodes.map((node) => {
        const measured = nodeMeasurements[node.id];
        return {
          ...node,
          ...(measured
            ? { measured, width: measured.width, height: measured.height }
            : {}),
          position: positionOverrides[node.id] ?? node.position,
          selected: selectedNodeIdSet.has(node.id),
          data: {
            ...node.data,
            ...(nodeOverlays[node.id] ?? {}),
          },
        };
      }),
    [
      hydratedDocument.nodes,
      nodeMeasurements,
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
      setSelectedNodeIdSet(
        new Set(
          nextNodes.filter((node) => node.selected).map((node) => node.id),
        ),
      );
      setPositionOverrides(() => {
        const next: Record<string, { x: number; y: number }> = {};
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
            next[node.id] = { x: node.position.x, y: node.position.y };
          }
        }
        return next;
      });
      dispatchAuthoringState({
        kind: "update_overlays",
        update: nodeOverlaysFromNodes(nextNodes),
      });
    },
    [dispatchAuthoringState],
  );
  const setEdges = React.useCallback<
    React.Dispatch<React.SetStateAction<WorkflowEdge[]>>
  >((action) => {
    const currentEdges = edgesRef.current;
    const nextEdges =
      typeof action === "function" ? action(currentEdges) : action;
    edgesRef.current = nextEdges;
    setSelectedEdgeIdSet(
      new Set(nextEdges.filter((edge) => edge.selected).map((edge) => edge.id)),
    );
  }, []);
  const [artifactViewers, setArtifactViewers] =
    React.useState<ArtifactViewerCanvasState>({
      graphId: null,
      nodes: [],
      edges: [],
      bindings: [],
      annotations: [],
    });
  const [shapesMenuOpen, setShapesMenuOpen] = React.useState(false);
  const [canvasMenu, setCanvasMenu] = React.useState<CanvasMenuRequest | null>(
    null,
  );
  const [nodeMenus] = React.useState(() => new NodeMenuRegistry());
  const canvasSectionRef = React.useRef<HTMLElement>(null);
  /** Where the Add node picker inserts when the canvas menu opened it. */
  const pickerInsertAtRef = React.useRef<{ x: number; y: number } | null>(null);
  const [artifactViewerSelections, setArtifactViewerSelections] =
    React.useState<Record<string, ArtifactKeySelection>>({});
  const [artifactViewerFields, setArtifactViewerFields] = React.useState<
    Record<string, ArtifactInteractionField[]>
  >({});
  const [artifactViewerActivities, setArtifactViewerActivities] =
    React.useState<Record<string, ActiveArtifactViewerActivity>>({});
  const artifactViewerActivityRevisionRef = React.useRef(0);
  const artifactViewersInitializedRef = React.useRef(initialGraphId === null);
  const artifactViewerGraphIdRef = React.useRef<string | null>(initialGraphId);
  const {
    nodeSecretStatuses,
    refreshNodeSecretStatuses,
    applyConfiguredNodeSecret,
    removeConfiguredNodeSecret,
    clearGraphSecretStatuses,
    forgetNodeSecretStatuses,
  } = useNodeSecrets(workspaceId, nodes);
  const [flow, setFlow] =
    React.useState<ReactFlowInstance<CanvasNode, CanvasEdge>>();
  const { workspace } = useWorkspaceContext();
  const [libraryOpen, setLibraryOpen] = React.useState(false);
  const sidePanel = useWorkbenchSidePanel();
  const [contextualDiscovery, setContextualDiscovery] =
    React.useState<ContextualDiscoverySession | null>(null);
  const [workspaceLibraryOpen, setWorkspaceLibraryOpen] = React.useState(false);
  const [workspaceLibraryFocusId, setWorkspaceLibraryFocusId] = React.useState<
    string | null
  >(null);
  const [publishModuleOpen, setPublishModuleOpen] = React.useState(false);
  const canPublishModule = workspace.capabilities.includes("publish_module");
  const canCreateGraph = workspace.capabilities.includes("create_graph");
  const canEditGraph = workspace.capabilities.includes("edit_graph");
  const canExecuteGraph = workspace.capabilities.includes("execute_graph");
  const canCancelExecution =
    workspace.capabilities.includes("cancel_execution");
  const canDeleteGraph = workspace.capabilities.includes("delete_graph");
  const canEditModuleSource = workspace.capabilities.includes("edit_graph");
  const localAuthoringEnabledRef = React.useRef(
    initialGraphId === null && canCreateGraph,
  );
  const localAuthoringBlockedMessageRef = React.useRef(
    "Editing is unavailable until this graph is synchronized.",
  );
  const moduleBoundarySummaries = React.useMemo(
    () => moduleBoundaries(nodes, edges, registry?.artifact_types ?? null),
    [edges, nodes, registry],
  );
  const [executionHistoryTarget, setExecutionHistoryTarget] = React.useState<{
    nodeId: string | null;
    executionId: string | null;
  } | null>(null);
  const executionHistoryReturnFocusRef = React.useRef<HTMLElement | null>(null);
  const [transientRunError, setRunError] = React.useState<string | null>(null);
  const runError = authoringState.error ?? transientRunError;
  const clearRunError = React.useCallback(() => {
    setRunError(null);
    dispatchAuthoringState({ kind: "clear_error" });
  }, [dispatchAuthoringState]);
  const dismissRunError = React.useCallback(
    (message: string) => {
      setRunError((current) => (current === message ? null : current));
      if (authoringState.error === message) {
        dispatchAuthoringState({ kind: "clear_error" });
      }
    },
    [authoringState.error, dispatchAuthoringState],
  );
  const [pendingConnectionRoute, setPendingConnectionRoute] =
    React.useState<PendingConnectionRoute | null>(null);
  const [fitRevision, setFitRevision] = React.useState(0);
  const executionRunningRef = React.useRef(false);
  const isExecutionRunning = React.useCallback(
    () => executionRunningRef.current,
    [],
  );
  const pendingBoundEdgesRef = React.useRef<PendingBoundEdge[]>([]);

  const roomCommandSyncRef = React.useRef<{
    submitLocal: (
      commands: readonly GraphCommand[],
      before: AuthoredGraphDocument,
    ) => void;
  }>({ submitLocal: () => undefined });

  const applyAuthoringCommands = React.useCallback(
    (commands: readonly GraphCommand[], options?: AuthoringCommandOptions) => {
      if (!commands.length) return;
      if (
        shouldBlockAuthoringCommand(localAuthoringEnabledRef.current, options)
      ) {
        setRunError(localAuthoringBlockedMessageRef.current);
        return;
      }
      const before = authoredDocumentRef.current;
      dispatchAuthoringState({ kind: "apply_commands", commands });
      setPositionOverrides({});
      setSelectedNodeIdSet(
        (current) =>
          new Set(
            [...current].filter((nodeId) =>
              authoredDocument.nodes.some((node) => node.id === nodeId),
            ),
          ),
      );
      setSelectedEdgeIdSet(
        (current) =>
          new Set(
            [...current].filter((edgeId) =>
              authoredDocument.edges.some((edge) => edge.id === edgeId),
            ),
          ),
      );
      setPendingConnectionRoute(null);
      setRunError(null);
      if (options?.syncRoom !== false) {
        roomCommandSyncRef.current.submitLocal(commands, before);
      }
    },
    [authoredDocument.edges, authoredDocument.nodes, dispatchAuthoringState],
  );

  React.useLayoutEffect(() => {
    authoredDocumentRef.current = authoredDocument;
  }, [authoredDocument]);

  const handleNodeHandlesMeasured = React.useCallback(
    (nodeId: string, artifactTypeBindings: WorkflowArtifactTypeBindings) => {
      const ready: PendingBoundEdge[] = [];
      const waiting: PendingBoundEdge[] = [];
      for (const pending of pendingBoundEdgesRef.current) {
        const measuredBinding = artifactTypeBindings[pending.variable];
        if (
          pending.nodeId === nodeId &&
          measuredBinding?.id === pending.artifactType.id &&
          measuredBinding.schema_version === pending.artifactType.schema_version
        ) {
          ready.push(pending);
        } else {
          waiting.push(pending);
        }
      }
      if (!ready.length) return;

      pendingBoundEdgesRef.current = waiting;
      const commands = ready.map((pending) => {
        const connection: Connection = {
          source: pending.edge.source,
          sourceHandle: pending.edge.sourceHandle ?? null,
          target: pending.edge.target,
          targetHandle: pending.edge.targetHandle ?? null,
        };
        return addEdgeCommand(connection, pending.edge.data, pending.edge.id);
      });
      applyAuthoringCommands(commands);
    },
    [applyAuthoringCommands],
  );

  const updateConfig = React.useCallback(
    (nodeId: string, name: string, value: unknown) => {
      applyAuthoringCommands([
        {
          kind: "update_node_configuration",
          node_id: nodeId,
          field: name,
          value,
        },
      ]);
    },
    [applyAuthoringCommands],
  );

  const updateLayout = React.useCallback(
    (nodeId: string, layout: WorkflowNodeData["layout"]) => {
      applyAuthoringCommands([
        {
          kind: "update_node_layout",
          node_id: nodeId,
          layout,
        },
      ]);
    },
    [applyAuthoringCommands],
  );

  const presentationRoomSyncRef = React.useRef<{
    submitReplace: (state: ArtifactViewerCanvasState) => void;
    submitMove: (
      positions: readonly { viewer_id: string; x: number; y: number }[],
    ) => void;
    submitMoveAnnotations: (
      positions: readonly { annotation_id: string; x: number; y: number }[],
    ) => void;
  }>({
    submitReplace: () => undefined,
    submitMove: () => undefined,
    submitMoveAnnotations: () => undefined,
  });

  const {
    commitArtifactViewers,
    dropOriginsCarriedByCards,
    removeAnnotation,
    removeArtifactViewer,
    updateAnnotationColor,
    updateAnnotationLayout,
    updateAnnotationText,
    updateArtifactViewerActivity,
    updateArtifactViewerBinding,
    updateArtifactViewerEdge,
    updateArtifactViewerEdgeRoute,
    updateArtifactViewerFields,
    updateArtifactViewerLayout,
    updateArtifactViewerMode,
    updateArtifactViewerSelection,
  } = useArtifactViewerCommands({
    artifactViewers,
    artifactViewerActivityRevisionRef,
    artifactViewerGraphIdRef,
    applyAuthoringCommands,
    authoredDocumentRef,
    localAuthoringBlockedMessageRef,
    localAuthoringEnabledRef,
    presentationRoomSyncRef,
    setArtifactViewerActivities,
    setArtifactViewerFields,
    setArtifactViewerSelections,
    setArtifactViewers,
    setRunError,
  });

  const {
    addNodeInputPlug,
    bindNodeArtifactTypeBinding,
    removeNode,
    removeNodeInputPlug,
    reorderNodeInputPlug,
    resetNodeArtifactTypeBinding,
    updateArtifactQueryRelations,
    updateSchemaBuilderFields,
  } = useNodeCommands({
    applyAuthoringCommands,
    commitArtifactViewers,
    edges,
    forgetNodeSecretStatuses,
    nodes,
    setPendingConnectionRoute,
    setRunError,
  });

  const openGraphInNewTab = React.useCallback(
    (graphId: string) => {
      // Internal route: workbenchGraphPath() returns a same-origin path from encoded params.
      // pi-lens-ignore: no-open-redirect
      window.open(
        workbenchGraphPath(workspaceSlug, graphId),
        "_blank",
        "noopener,noreferrer",
      );
    },
    [workspaceSlug],
  );

  const openNodeExecutionHistory = React.useCallback(
    (nodeId: string, executionId?: string) => {
      if (document.activeElement instanceof HTMLElement) {
        executionHistoryReturnFocusRef.current = document.activeElement;
      }
      setLibraryOpen(false);
      setExecutionHistoryTarget({ nodeId, executionId: executionId ?? null });
    },
    [],
  );

  const upgradeModuleCall = React.useCallback(
    (nodeId: string) => {
      if (!registry) return;
      const node = nodesRef.current.find(
        (candidate) => candidate.id === nodeId,
      );
      if (!node || !workflowNodeIsSupported(node.data)) return;
      const target = moduleCallUpgradeTarget(registry, node.data.spec);
      if (!target) return;
      const before = authoredDocumentRef.current;
      const authoredNode = before.nodes.find(
        (candidate) => candidate.id === nodeId,
      );
      if (!authoredNode) return;
      const nextDocument: AuthoredGraphDocument = {
        ...before,
        nodes: before.nodes.map((candidate) =>
          candidate.id === nodeId
            ? {
                ...candidate,
                operator_id: target.operator_id,
                operator_version: target.operator_version,
              }
            : candidate,
        ),
      };
      applyAuthoringCommands([
        { kind: "replace_document", document: nextDocument },
      ]);
      setSelectedNodeIdSet(new Set([nodeId]));
      setSelectedEdgeIdSet(new Set());
      setRunError(null);
    },
    [applyAuthoringCommands, registry],
  );

  const upgradePluginRelease = React.useCallback(
    (nodeId: string) => {
      const node = nodesRef.current.find(
        (candidate) => candidate.id === nodeId,
      );
      if (!node || !workflowNodeIsSupported(node.data)) return;
      const currentPin = pluginReleaseUpgradeTarget(
        node.data.spec,
        node.data.pluginReleasePin,
      );
      if (!currentPin) return;
      applyAuthoringCommands([
        {
          kind: "update_node_plugin_release",
          node_id: nodeId,
          plugin_release: {
            scope: currentPin.scope,
            slug: currentPin.slug,
            revision: currentPin.revision,
          },
        },
      ]);
      setSelectedNodeIdSet(new Set([nodeId]));
      setSelectedEdgeIdSet(new Set());
      setRunError(null);
    },
    [applyAuthoringCommands],
  );

  const attachNodeCallbacks = React.useCallback(
    (data: WorkflowNodeData): WorkflowNodeData => {
      const upgradeTarget =
        registry && workflowNodeIsSupported(data)
          ? moduleCallUpgradeTarget(registry, data.spec)
          : null;
      const pluginUpgradeTarget = pluginReleaseUpgradeTarget(
        data.spec,
        data.pluginReleasePin,
      );
      if (!workflowNodeIsSupported(data)) {
        return {
          ...data,
          onConfigChange: undefined,
          onLayoutChange: updateLayout,
          onRemoveNode: removeNode,
          onAddInputPlug: undefined,
          onRemoveInputPlug: undefined,
          onReorderInputPlug: undefined,
          onSchemaBuilderFieldsChange: undefined,
          onArtifactQueryRelationsChange: undefined,
          onResetArtifactTypeBinding: undefined,
          onBindArtifactTypeBinding: undefined,
          bindableArtifactTypes: undefined,
          onHandlesMeasured: undefined,
          onOpenModuleSource: undefined,
          moduleUpgradeRelease: null,
          onUpgradeModuleCall: undefined,
          pluginUpgradeRelease: null,
          onUpgradePluginRelease: undefined,
          onOpenExecutionHistory: openNodeExecutionHistory,
        };
      }
      return {
        ...data,
        onConfigChange: updateConfig,
        onLayoutChange: updateLayout,
        onRemoveNode: removeNode,
        onAddInputPlug: addNodeInputPlug,
        onRemoveInputPlug: removeNodeInputPlug,
        onReorderInputPlug: reorderNodeInputPlug,
        onSchemaBuilderFieldsChange: updateSchemaBuilderFields,
        onArtifactQueryRelationsChange: updateArtifactQueryRelations,
        onResetArtifactTypeBinding: resetNodeArtifactTypeBinding,
        onBindArtifactTypeBinding: bindNodeArtifactTypeBinding,
        bindableArtifactTypes: registry?.artifact_types.map(
          (artifactType) => artifactType.key,
        ),
        onHandlesMeasured: handleNodeHandlesMeasured,
        onOpenModuleSource: data.spec.module_graph_id
          ? openGraphInNewTab
          : undefined,
        moduleUpgradeRelease: upgradeTarget?.module_graph_revision ?? null,
        onUpgradeModuleCall: upgradeTarget ? upgradeModuleCall : undefined,
        pluginUpgradeRelease: pluginUpgradeTarget?.revision ?? null,
        onUpgradePluginRelease: pluginUpgradeTarget
          ? upgradePluginRelease
          : undefined,
        onOpenExecutionHistory: openNodeExecutionHistory,
      };
    },
    [
      addNodeInputPlug,
      bindNodeArtifactTypeBinding,
      handleNodeHandlesMeasured,
      openGraphInNewTab,
      openNodeExecutionHistory,
      registry,
      removeNode,
      removeNodeInputPlug,
      reorderNodeInputPlug,
      resetNodeArtifactTypeBinding,
      updateConfig,
      updateLayout,
      updateArtifactQueryRelations,
      updateSchemaBuilderFields,
      upgradeModuleCall,
      upgradePluginRelease,
    ],
  );

  const replaceDocument = React.useCallback(
    (
      nextDocument: AuthoredGraphDocument,
      overlayNodes?: readonly WorkflowNode[],
    ) => {
      pendingBoundEdgesRef.current = [];
      authoredDocumentRef.current = nextDocument;
      const nextNodeIds = new Set(nextDocument.nodes.map((node) => node.id));
      const nextOverlays =
        overlayNodes === undefined
          ? Object.fromEntries(
              Object.entries(nodeOverlaysRef.current).filter(([nodeId]) =>
                nextNodeIds.has(nodeId),
              ),
            )
          : nodeOverlaysFromNodes(overlayNodes);
      // Keep nodesRef aligned for callers that read overlays immediately after replace.
      nodesRef.current =
        overlayNodes === undefined
          ? nodesRef.current.filter((node) => nextNodeIds.has(node.id))
          : [...overlayNodes];
      edgesRef.current = [];
      dispatchAuthoringState({
        kind: "replace_document",
        document: nextDocument,
        nodeOverlays: nextOverlays,
      });
      setSelectedNodeIdSet(new Set());
      setSelectedEdgeIdSet(new Set());
      setPositionOverrides({});
      setTransientNodePositions({});
      setNodeMeasurements({});
    },
    [dispatchAuthoringState],
  );
  const replacePresentation = React.useCallback(
    (graphId: string, presentation: GraphPresentation) => {
      artifactViewersInitializedRef.current = true;
      setArtifactViewers(
        artifactViewersFromPresentation(graphId, presentation),
      );
    },
    [],
  );
  const sharedPresentation = React.useMemo(
    () => presentationFromArtifactViewers(artifactViewers),
    [artifactViewers],
  );
  const currentExecutionFingerprint = React.useMemo(
    () =>
      savedGraphExecutionFingerprint(
        createSavedGraphRequest(authoredDocument, sharedPresentation),
      ),
    [authoredDocument, sharedPresentation],
  );
  const updateDocumentName = React.useCallback(
    (name: string) => {
      applyAuthoringCommands([{ kind: "rename_graph", name }]);
    },
    [applyAuthoringCommands],
  );
  const clearPendingConnectionRoute = React.useCallback(() => {
    setPendingConnectionRoute(null);
  }, []);
  const closeNodeLibrary = React.useCallback(() => {
    setLibraryOpen(false);
  }, []);
  const requestCanvasRefit = React.useCallback(() => {
    setFitRevision((current) => current + 1);
  }, []);
  const requestNodeRegistryRefresh = React.useCallback(() => {
    void refreshNodeRegistry();
  }, [refreshNodeRegistry]);
  const roomPersistenceRef = React.useRef<GraphRoomPersistenceAdapter>({
    canPersist: false,
    persistDocument: async () => {
      throw new Error("Graph room is not ready.");
    },
  });
  const roomPersistence = React.useMemo<GraphRoomPersistenceAdapter>(
    () => ({
      get canPersist() {
        return roomPersistenceRef.current.canPersist;
      },
      persistDocument: (draft) =>
        roomPersistenceRef.current.persistDocument(draft),
    }),
    [],
  );
  /**
   * Canvas edits applied while the room would not take commands. They live only
   * in this tab, which is the one case a reload can actually lose work.
   */
  const [unsyncedRoomEdits, setUnsyncedRoomEdits] = React.useState(false);
  const {
    activeGraph,
    graphName,
    setGraphName,
    isDirty,
    canMaterializeSavedGraph,
    saving,
    openingGraphId,
    deletingGraphId,
    persistenceError,
    clearPersistenceError,
    dismissPersistenceError,
    persistenceOperationBusy,
    closeGraphBrowser,
    refreshSavedGraphs,
    saveCurrentGraph,
    removeSavedGraph,
    syncFromCollaborativeHead,
    purgeLocalGraphState,
  } = useSavedGraphLifecycle({
    workspaceId,
    workspaceSlug,
    initialGraphId,
    registry,
    document: authoredDocument,
    presentation: sharedPresentation,
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
    refreshNodeRegistry: requestNodeRegistryRefresh,
    roomPersistence,
    hasUnsyncedRoomEdits: unsyncedRoomEdits,
  });
  const router = useRouter();
  const activeGraphIdRef = React.useRef(activeGraph?.id ?? null);
  React.useEffect(() => {
    activeGraphIdRef.current = activeGraph?.id ?? null;
  }, [activeGraph?.id]);
  const syncFromCollaborativeHeadRef = React.useRef(syncFromCollaborativeHead);
  /**
   * Applying an authoritative head means the room took the commands or
   * reconciled with another writer, so the canvas holds nothing the server
   * does not already have.
   */
  const applyRoomHead = React.useCallback((head: CollaborativeHead) => {
    syncFromCollaborativeHeadRef.current(head);
    setUnsyncedRoomEdits(false);
  }, []);
  const applyAuthoringCommandsRef = React.useRef(applyAuthoringCommands);
  React.useLayoutEffect(() => {
    syncFromCollaborativeHeadRef.current = syncFromCollaborativeHead;
    applyAuthoringCommandsRef.current = applyAuthoringCommands;
  }, [applyAuthoringCommands, syncFromCollaborativeHead]);
  const replaceHeadRef = React.useRef<
    (head: CollaborativeHead) => CollaborativeHead
  >((head) => head);
  const graphRoomHeadRef = React.useRef<CollaborativeHead | null>(null);
  const refreshCollaborativeHeadRef = React.useRef<
    (options?: { errorMessage?: string | null }) => void
  >(() => undefined);
  const headRefreshRetryRef = React.useRef<number | null>(null);
  React.useLayoutEffect(() => {
    refreshCollaborativeHeadRef.current = (options) => {
      const graphId = activeGraphIdRef.current;
      if (!graphId) return;
      void getCollaborativeHead(workspaceId, graphId)
        .then((head) => {
          if (headRefreshRetryRef.current !== null) {
            window.clearTimeout(headRefreshRetryRef.current);
            headRefreshRetryRef.current = null;
          }
          const current = graphRoomHeadRef.current;
          if (!shouldReplaceCollaborativeHead(current, head)) {
            // Late HTTP snapshot lost the race to a newer WebSocket head.
            // Clear the rehydration pause without wiping presentation/UI.
            if (current) replaceHeadRef.current(current);
            return;
          }
          replaceHeadRef.current(head);
          applyRoomHead(head);
        })
        .catch((error: unknown) => {
          const message =
            options?.errorMessage ??
            (error instanceof Error
              ? error.message
              : "Collaborative head could not be refreshed.");
          setRunError(message);
          if (headRefreshRetryRef.current === null) {
            headRefreshRetryRef.current = window.setTimeout(() => {
              headRefreshRetryRef.current = null;
              refreshCollaborativeHeadRef.current({ errorMessage: message });
            }, 1000);
          }
        });
    };
  }, [applyRoomHead, workspaceId]);

  React.useEffect(
    () => () => {
      if (headRefreshRetryRef.current !== null) {
        window.clearTimeout(headRefreshRetryRef.current);
      }
    },
    [],
  );

  const graphRoom = useGraphRoomSession({
    workspaceId,
    graphId: activeGraph?.id ?? null,
    onReady: (ready) => {
      // Durable editing is disabled while disconnected, so reconnect always
      // restores the authoritative room snapshot before authoring resumes.
      applyRoomHead(ready.head);
    },
    onRehydrate: (head) => {
      applyRoomHead(head);
    },
    onHeadRefreshRequired: () => {
      refreshCollaborativeHeadRef.current({ errorMessage: null });
    },
    onCommandAccepted: (message, meta) => {
      if (meta.local) {
        // Local presentation commands already updated artifactViewers optimistically.
        if (
          message.command.kind === "replace_presentation" ||
          message.command.kind === "move_artifact_viewers" ||
          message.command.kind === "move_annotations"
        ) {
          return;
        }
        // Workflow remove_nodes also prunes presentation links on the server.
        if (message.command.kind === "remove_nodes") {
          const removed = new Set(message.command.node_ids);
          setArtifactViewers((current) => ({
            ...current,
            edges: current.edges.filter((edge) => !removed.has(edge.source)),
          }));
        }
        return;
      }
      if (message.command.kind === "replace_presentation") {
        const graphId = activeGraphIdRef.current;
        if (!graphId) return;
        replacePresentation(graphId, message.command.presentation);
        return;
      }
      if (message.command.kind === "move_artifact_viewers") {
        const positions = new Map(
          message.command.positions.map((position) => [
            position.viewer_id,
            { x: position.x, y: position.y },
          ]),
        );
        setArtifactViewers((current) => ({
          ...current,
          nodes: current.nodes.map((node) => {
            const position = positions.get(node.id);
            return position ? { ...node, position } : node;
          }),
        }));
        return;
      }
      if (message.command.kind === "move_annotations") {
        const positions = new Map(
          message.command.positions.map((position) => [
            position.annotation_id,
            { x: position.x, y: position.y },
          ]),
        );
        setArtifactViewers((current) => ({
          ...current,
          annotations: current.annotations.map((node) => {
            const position = positions.get(node.id);
            return position ? { ...node, position } : node;
          }),
        }));
        return;
      }
      const localCommand = toLocalGraphCommand(
        message.command,
        authoredDocumentRef.current,
      );
      if (localCommand) {
        applyAuthoringCommandsRef.current([localCommand], { syncRoom: false });
        if (localCommand.kind === "remove_nodes") {
          const removed = new Set(localCommand.node_ids);
          setArtifactViewers((current) => ({
            ...current,
            edges: current.edges.filter((edge) => !removed.has(edge.source)),
          }));
        }
        if (
          message.command.kind === "replace_document" &&
          message.command.document.presentation
        ) {
          const graphId = activeGraphIdRef.current;
          if (graphId) {
            replacePresentation(graphId, message.command.document.presentation);
          }
        }
        return;
      }
      refreshCollaborativeHeadRef.current();
    },
    onCommandRejected: (message) => {
      const isHeadConflict = message.error_code === "head_conflict";
      if (!isHeadConflict) {
        setRunError(message.detail || "A collaborative edit was rejected.");
      }
      refreshCollaborativeHeadRef.current({
        errorMessage: isHeadConflict
          ? null
          : message.detail || "A collaborative edit was rejected.",
      });
    },
    onTerminalClose: (reason) => {
      if (reason === "access_revoked" || reason === "graph_deleted") {
        purgeLocalGraphState();
        router.replace(`/workspaces/${encodeURIComponent(workspaceSlug)}`);
        return;
      }
    },
  });
  const displayedGraphReadiness = graphReadiness(
    graphRoom.status,
    graphRoom.head !== null,
  );
  const graphOperationsTrusted =
    !activeGraph || displayedGraphReadiness.trusted;
  const canSubmitRoomCommands = graphRoom.canSubmitCommands;
  const submitRoomCommand = graphRoom.submitCommand;
  const reconcileCheckpointHead = graphRoom.reconcileCheckpointHead;
  React.useLayoutEffect(() => {
    replaceHeadRef.current = graphRoom.replaceHead;
    graphRoomHeadRef.current = graphRoom.head;
    artifactViewerGraphIdRef.current = activeGraph?.id ?? null;
  }, [activeGraph?.id, graphRoom.head, graphRoom.replaceHead]);
  React.useEffect(() => {
    roomCommandSyncRef.current = {
      submitLocal: (commands, before) => {
        if (!canSubmitRoomCommands) {
          setUnsyncedRoomEdits(true);
          return;
        }
        for (const command of commands) {
          const roomCommand = toRoomGraphCommand(command, before);
          if (!roomCommand) continue;
          void submitRoomCommand(roomCommand).catch((error: unknown) => {
            if (
              error instanceof GraphRoomCommandError &&
              (error.errorCode === "superseded" ||
                error.errorCode === "head_conflict")
            ) {
              return;
            }
            const detail =
              error instanceof GraphRoomCommandError
                ? error.message
                : error instanceof Error
                  ? error.message
                  : "Collaborative sync failed.";
            setRunError(detail);
          });
        }
      },
    };
  }, [canSubmitRoomCommands, submitRoomCommand]);
  React.useEffect(() => {
    presentationRoomSyncRef.current = {
      submitReplace: (state) => {
        if (!canSubmitRoomCommands) {
          setUnsyncedRoomEdits(true);
          return;
        }
        const command = {
          kind: "replace_presentation",
          presentation: presentationFromArtifactViewers(state),
        } as RoomGraphCommand;
        void submitRoomCommand(command).catch((error: unknown) => {
          if (
            error instanceof GraphRoomCommandError &&
            (error.errorCode === "superseded" ||
              error.errorCode === "head_conflict")
          ) {
            return;
          }
          const detail =
            error instanceof GraphRoomCommandError
              ? error.message
              : error instanceof Error
                ? error.message
                : "Presentation sync failed.";
          setRunError(detail);
        });
      },
      submitMove: (positions) => {
        if (!canSubmitRoomCommands || !positions.length) return;
        const command = {
          kind: "move_artifact_viewers",
          positions: [...positions],
        } as RoomGraphCommand;
        void submitRoomCommand(command).catch((error: unknown) => {
          if (
            error instanceof GraphRoomCommandError &&
            (error.errorCode === "superseded" ||
              error.errorCode === "head_conflict")
          ) {
            return;
          }
          const detail =
            error instanceof GraphRoomCommandError
              ? error.message
              : error instanceof Error
                ? error.message
                : "Presentation sync failed.";
          setRunError(detail);
        });
      },
      submitMoveAnnotations: (positions) => {
        if (!canSubmitRoomCommands || !positions.length) return;
        const command = {
          kind: "move_annotations",
          positions: [...positions],
        } as RoomGraphCommand;
        void submitRoomCommand(command).catch((error: unknown) => {
          if (
            error instanceof GraphRoomCommandError &&
            (error.errorCode === "superseded" ||
              error.errorCode === "head_conflict")
          ) {
            return;
          }
          const detail =
            error instanceof GraphRoomCommandError
              ? error.message
              : error instanceof Error
                ? error.message
                : "Presentation sync failed.";
          setRunError(detail);
        });
      },
    };
  }, [canSubmitRoomCommands, submitRoomCommand]);
  React.useEffect(() => {
    const graphId = activeGraph?.id;
    roomPersistenceRef.current = {
      canPersist: canSubmitRoomCommands && graphId !== undefined,
      persistDocument: async (draft) => {
        if (!graphId) {
          throw new Error("Graph room requires a saved graph id.");
        }
        const command = toRoomReplaceDocumentCommand(draft);
        const { head: replacedHead } = await submitRoomCommand(command);
        const checkpointed = await checkpointGraph(workspaceId, graphId, {
          expected_room_epoch: replacedHead.room_epoch,
          expected_sequence: replacedHead.collaboration_sequence,
        });
        const currentHead = reconcileCheckpointHead(
          checkpointed.head,
          replacedHead.room_epoch,
        );
        return {
          checkpointHead: checkpointed.head,
          currentHead,
        };
      },
    };
  }, [
    activeGraph?.id,
    canSubmitRoomCommands,
    reconcileCheckpointHead,
    submitRoomCommand,
    workspaceId,
  ]);
  const {
    running,
    runningScope,
    visibleExecution,
    announcement: executionAnnouncement,
    runWorkflow,
    cancelCurrentExecution,
  } = useRunExecution({
    workspaceId,
    registryAvailable: Boolean(registry),
    nodes,
    edges,
    origins: authoredDocument.origins,
    activeGraph,
    currentExecutionFingerprint,
    canMaterializeSavedGraph,
    nodeSecretStatuses,
    roomActiveExecution: graphRoom.activeExecution,
    setNodes,
    setRunError,
    onMaterializationsLoaded: clearPersistenceError,
  });
  React.useEffect(() => {
    executionRunningRef.current = running;
  }, [running]);

  const graphOperationBusy = persistenceOperationBusy || running;
  const localAuthoringEnabled =
    !graphOperationBusy &&
    (activeGraph
      ? canEditGraph && graphOperationsTrusted && graphRoom.canSubmitCommands
      : initialGraphId === null && canCreateGraph);
  const localAuthoringBlockedMessage = !(activeGraph
    ? canEditGraph
    : canCreateGraph)
    ? "You do not have permission to edit this graph."
    : graphOperationBusy
      ? "Editing is paused while another graph operation is in progress."
      : "Editing is paused until graph synchronization is ready.";
  React.useLayoutEffect(() => {
    localAuthoringEnabledRef.current = localAuthoringEnabled;
    localAuthoringBlockedMessageRef.current = localAuthoringBlockedMessage;
  }, [localAuthoringBlockedMessage, localAuthoringEnabled]);

  React.useEffect(() => {
    if (executionHistoryTarget) closeGraphBrowser();
  }, [closeGraphBrowser, executionHistoryTarget]);

  React.useEffect(() => {
    // Intentional refits only (graph open / blank / pane ready). Reading node
    // count from the ref avoids depending on nodes.length, which would recenter
    // the camera after duplicate/remove/add.
    if (!flow || !nodesRef.current.length) return;
    const frame = window.requestAnimationFrame(
      () => void flow.fitView(workbenchFitViewOptions),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [fitRevision, flow, workbenchFitViewOptions]);

  const selectedNodeIds = React.useMemo(
    () => [
      ...nodes.flatMap((node) => (node.selected ? [node.id] : [])),
      ...artifactViewers.nodes.flatMap((node) =>
        node.selected ? [node.id] : [],
      ),
      ...artifactViewers.annotations.flatMap((node) =>
        node.selected ? [node.id] : [],
      ),
    ],
    [artifactViewers.annotations, artifactViewers.nodes, nodes],
  );
  const selectedNodeIdsRef = React.useRef(selectedNodeIds);
  React.useLayoutEffect(() => {
    selectedNodeIdsRef.current = selectedNodeIds;
  }, [selectedNodeIds]);
  // Last on-canvas pointer in flow coords. Presence replaces the whole snapshot,
  // so selection/keepalive publishes must resend this or peers see cursor: null.
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
  const localDraggingNodeIdsRef = React.useRef<ReadonlySet<string>>(new Set());
  const presencePublishTimerRef = React.useRef<number | null>(null);
  const lastPresencePublishAtRef = React.useRef(0);
  const canPublishRoomPresence = graphRoom.canPublishPresence;
  const publishRoomPresence = graphRoom.publishPresence;
  const schedulePresenceSnapshot = React.useCallback(() => {
    if (!canPublishRoomPresence) return;
    if (presencePublishTimerRef.current !== null) return;

    const elapsed = Date.now() - lastPresencePublishAtRef.current;
    const delay = Math.max(0, PRESENCE_CLIENT_MIN_INTERVAL_MS - elapsed);
    presencePublishTimerRef.current = window.setTimeout(() => {
      presencePublishTimerRef.current = null;
      if (!canPublishRoomPresence) return;

      const clientPoint = presenceClientPointRef.current;
      if (presenceClientPointDirtyRef.current && clientPoint && flow) {
        presenceCursorRef.current = flow.screenToFlowPosition(clientPoint);
        presenceClientPointDirtyRef.current = false;
      }

      const drag = presenceDragRef.current;
      const published = publishRoomPresence({
        cursor: presenceCursorRef.current,
        selected_node_ids: selectedNodeIdsRef.current,
        activity: drag ? "moving_nodes" : null,
        activity_target_ids: drag?.targetIds ?? [],
        transient_node_positions: drag?.positions ?? [],
      });
      if (published) lastPresencePublishAtRef.current = Date.now();
    }, delay);
  }, [canPublishRoomPresence, flow, publishRoomPresence]);
  React.useEffect(() => {
    if (graphRoom.canPublishPresence) return;
    if (presencePublishTimerRef.current !== null) {
      window.clearTimeout(presencePublishTimerRef.current);
      presencePublishTimerRef.current = null;
    }
    lastPresencePublishAtRef.current = 0;
  }, [graphRoom.canPublishPresence]);
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
  // Server clears idle cursors after ~5s without updates; keepalives while parked.
  React.useEffect(() => {
    if (!graphRoom.canPublishPresence) return;
    const timer = window.setInterval(() => {
      if (!presenceOverCanvasRef.current || !presenceCursorRef.current) return;
      schedulePresenceSnapshot();
    }, 2000);
    return () => window.clearInterval(timer);
  }, [graphRoom.canPublishPresence, schedulePresenceSnapshot]);
  const remoteDragPreviews = useRemoteDragPreviews(
    graphRoom.participants,
    graphRoom.localSessionId,
    localDraggingNodeIdsRef,
  );
  const selectedNodeCount = selectedNodeIds.length;
  const selectedNodesAreRunnable = nodes.every(
    (node) =>
      !node.selected ||
      (workflowNodeIsSupported(node.data) &&
        validateConfig(node.data.spec.config_schema, node.data.config)
          .length === 0),
  );
  const nodeTitles = React.useMemo(
    () =>
      Object.fromEntries(nodes.map((node) => [node.id, node.data.spec.title])),
    [nodes],
  );
  const selectedWithDependencyIds = selectedNodeAndAncestorIds(nodes, edges);
  const selectedWithDependenciesCount = selectedWithDependencyIds.size;
  const selectedWithDependenciesAreRunnable = nodes.every(
    (node) =>
      !selectedWithDependencyIds.has(node.id) ||
      (workflowNodeIsSupported(node.data) &&
        validateConfig(node.data.spec.config_schema, node.data.config)
          .length === 0),
  );
  const selectedWorkflowCount = nodes.filter((node) => node.selected).length;
  const selectedViewerCount = artifactViewers.nodes.filter(
    (node) => node.selected,
  ).length;
  const selectedArtifactCards = React.useMemo(
    () =>
      artifactViewers.nodes.flatMap((node) => {
        const value = node.data.artifactRef;
        if (!node.selected || !value) {
          return [];
        }
        return [{ node, value }];
      }),
    [artifactViewers.nodes],
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
  const groupingDisabledReason =
    selectedNodeCount !== selectedArtifactCards.length
      ? "Select only artifacts to collect."
      : artifactGroupingDisabledReason({
          cards: selectedArtifactCards.map(({ node }) => node),
          state: artifactViewers,
          origins: authoredDocument.origins,
        });
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
          originCarriesCardArtifacts(origin.value, source.value),
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
    !canExecuteGraph ||
    !graphOperationsTrusted ||
    runSelectionBusy ||
    !selectedNodesAreRunnable;
  const runSelectedWithDependenciesDisabled =
    !canExecuteGraph ||
    !graphOperationsTrusted ||
    runSelectionBusy ||
    !selectedWithDependenciesAreRunnable;
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
        id: "graph",
        title: "Graph",
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
  // A viewer state from another graph must not leak into this one, and the empty
  // stand-in has to keep its identity or every presentation memo below it re-runs.
  const activeArtifactViewers = React.useMemo<ArtifactViewerCanvasState>(
    () =>
      artifactViewers.graphId === (activeGraph?.id ?? null)
        ? artifactViewers
        : {
            graphId: activeGraph?.id ?? null,
            nodes: [],
            edges: [],
            bindings: [],
            annotations: [],
          },
    [artifactViewers, activeGraph?.id],
  );

  const onNodesChange: OnNodesChange<CanvasNode> = React.useCallback(
    (changes) => {
      const gridSettings = canvasGridSettingsRef.current;
      const gridBypass = bypassSnapRef.current;
      const draggingPositions = changes.flatMap((change) => {
        if (
          change.type !== "position" ||
          change.dragging !== true ||
          !change.position
        ) {
          return [];
        }
        const position = shouldSnapPosition(gridSettings, {
          dragging: true,
          bypass: gridBypass,
        })
          ? snapPosition(change.position, gridSettings.cellSize)
          : change.position;
        return [{ node_id: change.id, x: position.x, y: position.y }];
      });
      if (draggingPositions.length) {
        const targetIds = draggingPositions.map((position) => position.node_id);
        localDraggingNodeIdsRef.current = new Set(targetIds);
        presenceDragRef.current = {
          positions: draggingPositions,
          targetIds,
        };
        const nextTransientPositions = Object.fromEntries(
          draggingPositions.map((position) => [
            position.node_id,
            { x: position.x, y: position.y },
          ]),
        );
        setTransientNodePositions((current) => {
          const currentIds = Object.keys(current);
          if (
            currentIds.length === targetIds.length &&
            targetIds.every(
              (id) =>
                current[id]?.x === nextTransientPositions[id]?.x &&
                current[id]?.y === nextTransientPositions[id]?.y,
            )
          ) {
            return current;
          }
          return nextTransientPositions;
        });
        schedulePresenceSnapshot();
        if (draggingPositions.length === changes.length) return;
      }
      const snapNodeChangePosition = <
        NodeT extends WorkflowNode | ArtifactViewerNode | AnnotationNode,
      >(
        change: NodeChange<NodeT>,
      ): NodeChange<NodeT> => {
        if (
          change.type !== "position" ||
          !change.position ||
          !shouldSnapPosition(gridSettings, {
            dragging: change.dragging === true,
            bypass: gridBypass,
          })
        ) {
          return change;
        }
        return {
          ...change,
          position: snapPosition(change.position, gridSettings.cellSize),
        };
      };
      const workflowNodeIds = new Set(nodes.map((node) => node.id));
      const artifactViewerIds = new Set(
        artifactViewers.nodes.map((node) => node.id),
      );
      const annotationIds = new Set(
        artifactViewers.annotations.map((node) => node.id),
      );
      const workflowChanges = changes
        .filter((change) =>
          change.type === "add" || change.type === "replace"
            ? change.item.type === WORKFLOW_NODE_TYPE
            : workflowNodeIds.has(change.id),
        )
        .map((change) =>
          snapNodeChangePosition(change as NodeChange<WorkflowNode>),
        ) as NodeChange<WorkflowNode>[];
      const artifactViewerChanges = changes
        .filter((change) =>
          change.type === "add" || change.type === "replace"
            ? change.item.type === ARTIFACT_VIEWER_NODE_TYPE
            : artifactViewerIds.has(change.id),
        )
        .map((change) =>
          snapNodeChangePosition(change as NodeChange<ArtifactViewerNode>),
        ) as NodeChange<ArtifactViewerNode>[];
      const annotationChanges = changes
        .filter((change) =>
          change.type === "add" || change.type === "replace"
            ? change.item.type === ANNOTATION_NODE_TYPE
            : annotationIds.has(change.id),
        )
        .map((change) =>
          snapNodeChangePosition(change as NodeChange<AnnotationNode>),
        ) as NodeChange<AnnotationNode>[];
      const rendererChanges = workflowChanges.filter(
        (change) => change.type === "add" || change.type === "replace",
      );
      if (rendererChanges.length) {
        setNodes((current) => applyNodeChanges(rendererChanges, current));
      }
      const removedArtifactViewerIds = new Set(
        artifactViewerChanges.flatMap((change) =>
          change.type === "remove" ? [change.id] : [],
        ),
      );
      const movedArtifactViewers = artifactViewerChanges.flatMap((change) =>
        change.type === "position" && !change.dragging && change.position
          ? [
              {
                viewer_id: change.id,
                x: change.position.x,
                y: change.position.y,
              },
            ]
          : [],
      );
      // Local-only React Flow bookkeeping. Drag positions stay in the transient
      // canvas overlay below so semantic viewer state remains referentially stable.
      const localArtifactViewerChanges = artifactViewerChanges.filter(
        (change) => change.type === "dimensions" || change.type === "select",
      );
      if (localArtifactViewerChanges.length) {
        setArtifactViewers((current) => ({
          ...current,
          nodes: applyNodeChanges(localArtifactViewerChanges, current.nodes),
        }));
      }
      if (movedArtifactViewers.length) {
        setArtifactViewers((current) => ({
          ...current,
          nodes: applyNodeChanges(
            artifactViewerChanges.filter(
              (change) =>
                change.type === "position" && change.dragging !== true,
            ),
            current.nodes,
          ),
        }));
        presentationRoomSyncRef.current.submitMove(movedArtifactViewers);
      }
      const durableArtifactViewerChanges = artifactViewerChanges.filter(
        (change) =>
          change.type === "remove" ||
          change.type === "add" ||
          change.type === "replace",
      );
      if (
        durableArtifactViewerChanges.length ||
        removedArtifactViewerIds.size
      ) {
        commitArtifactViewers((current) => ({
          ...current,
          nodes: applyNodeChanges(durableArtifactViewerChanges, current.nodes),
          bindings: removedArtifactViewerIds.size
            ? current.bindings.filter(
                (binding) =>
                  !removedArtifactViewerIds.has(binding.sourceViewerId) &&
                  !removedArtifactViewerIds.has(binding.targetViewerId),
              )
            : current.bindings,
        }));
      }
      const removedAnnotationIds = new Set(
        annotationChanges.flatMap((change) =>
          change.type === "remove" ? [change.id] : [],
        ),
      );
      const movedAnnotations = annotationChanges.flatMap((change) =>
        change.type === "position" && !change.dragging && change.position
          ? [
              {
                annotation_id: change.id,
                x: change.position.x,
                y: change.position.y,
              },
            ]
          : [],
      );
      const localAnnotationChanges = annotationChanges.filter(
        (change) => change.type === "dimensions" || change.type === "select",
      );
      if (localAnnotationChanges.length) {
        setArtifactViewers((current) => ({
          ...current,
          annotations: applyNodeChanges(
            localAnnotationChanges,
            current.annotations,
          ),
        }));
      }
      if (movedAnnotations.length) {
        setArtifactViewers((current) => ({
          ...current,
          annotations: applyNodeChanges(
            annotationChanges.filter(
              (change) =>
                change.type === "position" && change.dragging !== true,
            ),
            current.annotations,
          ),
        }));
        presentationRoomSyncRef.current.submitMoveAnnotations(movedAnnotations);
      }
      const durableAnnotationChanges = annotationChanges.filter(
        (change) =>
          change.type === "remove" ||
          change.type === "add" ||
          change.type === "replace",
      );
      if (durableAnnotationChanges.length || removedAnnotationIds.size) {
        commitArtifactViewers((current) => ({
          ...current,
          annotations: applyNodeChanges(
            durableAnnotationChanges,
            current.annotations,
          ),
        }));
      }
      if (removedArtifactViewerIds.size) {
        dropOriginsCarriedByCards(
          [...removedArtifactViewerIds].map((nodeId) =>
            artifactViewers.nodes.find((node) => node.id === nodeId),
          ),
        );
        setArtifactViewerSelections((current) => {
          const next = { ...current };
          for (const nodeId of removedArtifactViewerIds) delete next[nodeId];
          return next;
        });
        setArtifactViewerFields((current) => {
          const next = { ...current };
          for (const nodeId of removedArtifactViewerIds) delete next[nodeId];
          return next;
        });
        setArtifactViewerActivities((current) => {
          const next = { ...current };
          for (const nodeId of removedArtifactViewerIds) delete next[nodeId];
          return next;
        });
      }
      const removedWorkflowNodeIds = new Set(
        workflowChanges.flatMap((change) =>
          change.type === "remove" ? [change.id] : [],
        ),
      );
      if (removedWorkflowNodeIds.size) {
        commitArtifactViewers((current) => ({
          ...current,
          edges: current.edges.filter(
            (edge) => !removedWorkflowNodeIds.has(edge.source),
          ),
        }));
        setNodeMeasurements((current) => {
          let changed = false;
          const next = { ...current };
          for (const nodeId of removedWorkflowNodeIds) {
            if (nodeId in next) {
              delete next[nodeId];
              changed = true;
            }
          }
          return changed ? next : current;
        });
      }
      const measuredUpdates = workflowChanges.flatMap((change) =>
        change.type === "dimensions" &&
        change.dimensions &&
        typeof change.dimensions.width === "number" &&
        typeof change.dimensions.height === "number"
          ? [
              {
                id: change.id,
                width: change.dimensions.width,
                height: change.dimensions.height,
              },
            ]
          : [],
      );
      if (measuredUpdates.length) {
        setNodeMeasurements((current) => {
          let changed = false;
          const next = { ...current };
          for (const update of measuredUpdates) {
            const previous = next[update.id];
            if (
              !previous ||
              previous.width !== update.width ||
              previous.height !== update.height
            ) {
              next[update.id] = {
                width: update.width,
                height: update.height,
              };
              changed = true;
            }
          }
          return changed ? next : current;
        });
      }
      const semanticChanges = graphCommandsFromNodeChanges(workflowChanges);
      // Selection is renderer bookkeeping. The early in-drag path above avoids
      // routing pointer samples through setNodes and rebuilding semantic overlays.
      const selectionChanges = workflowChanges.filter(
        (change) => change.type === "select",
      );
      if (selectionChanges.length) {
        setNodes((current) => applyNodeChanges(selectionChanges, current));
      }
      if (semanticChanges.length) applyAuthoringCommands(semanticChanges);

      const dragEnded =
        workflowChanges.some(
          (change) => change.type === "position" && change.dragging === false,
        ) ||
        artifactViewerChanges.some(
          (change) => change.type === "position" && change.dragging === false,
        ) ||
        annotationChanges.some(
          (change) => change.type === "position" && change.dragging === false,
        );
      if (dragEnded) {
        localDraggingNodeIdsRef.current = new Set();
        presenceDragRef.current = null;
        setTransientNodePositions((current) =>
          Object.keys(current).length ? {} : current,
        );
        schedulePresenceSnapshot();
      }
    },
    [
      applyAuthoringCommands,
      artifactViewers.annotations,
      artifactViewers.nodes,
      commitArtifactViewers,
      dropOriginsCarriedByCards,
      nodes,
      schedulePresenceSnapshot,
      setNodes,
    ],
  );

  const artifactOriginCanvasEdges = React.useMemo(
    () =>
      artifactOriginConnections(
        activeArtifactViewers.nodes,
        activeArtifactViewers.edges,
        nodes,
        authoredDocument.origins,
      ).map((edge) => ({
        ...edge,
        selected: selectedEdgeIdSet.has(edge.id),
        data: {
          ...edge.data,
          onDisconnect: (originId: string) =>
            applyAuthoringCommands([
              { kind: "remove_origins", origin_ids: [originId] },
            ]),
        },
      })),
    [
      activeArtifactViewers.nodes,
      activeArtifactViewers.edges,
      nodes,
      authoredDocument.origins,
      selectedEdgeIdSet,
      applyAuthoringCommands,
    ],
  );

  const onEdgesChange: OnEdgesChange<CanvasEdge> = React.useCallback(
    (changes) => {
      const workflowEdgeIds = new Set(edges.map((edge) => edge.id));
      const artifactViewerEdgeIds = new Set(
        artifactViewers.edges.map((edge) => edge.id),
      );
      const artifactViewerInteractionEdgeIds = new Set(
        artifactViewers.bindings.map((binding) => binding.id),
      );
      const workflowChanges = changes.filter((change) =>
        change.type === "add" || change.type === "replace"
          ? change.item.type !== ARTIFACT_VIEWER_EDGE_TYPE &&
            change.item.type !== ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE &&
            change.item.type !== ARTIFACT_ORIGIN_EDGE_TYPE
          : workflowEdgeIds.has(change.id),
      ) as EdgeChange<WorkflowEdge>[];
      const artifactViewerChanges = changes.filter((change) =>
        change.type === "add" || change.type === "replace"
          ? change.item.type === ARTIFACT_VIEWER_EDGE_TYPE
          : artifactViewerEdgeIds.has(change.id),
      ) as EdgeChange<ArtifactViewerEdge>[];
      const artifactViewerInteractionChanges = changes.filter((change) =>
        change.type === "add" || change.type === "replace"
          ? change.item.type === ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE
          : artifactViewerInteractionEdgeIds.has(change.id),
      ) as EdgeChange<ArtifactViewerInteractionEdge>[];
      if (workflowChanges.length) {
        const semanticChanges = graphCommandsFromEdgeChanges(workflowChanges);
        const transientChanges = workflowChanges.filter(
          (change) => change.type !== "remove",
        );
        if (transientChanges.length) {
          setEdges((current) => applyEdgeChanges(transientChanges, current));
        }
        if (semanticChanges.length) applyAuthoringCommands(semanticChanges);
        else clearRunError();
      }
      const originEdgesById = new Map(
        artifactOriginCanvasEdges.map((edge) => [edge.id, edge]),
      );
      const removedOrigins = changes.flatMap((change) => {
        if (change.type !== "remove") return [];
        const edge = originEdgesById.get(change.id);
        return edge ? [edge.data.originId] : [];
      });
      if (removedOrigins.length) {
        applyAuthoringCommands([
          { kind: "remove_origins", origin_ids: [...new Set(removedOrigins)] },
        ]);
      }
      const selectedOrigins = changes.filter(
        (change) => change.type === "select" && originEdgesById.has(change.id),
      );
      if (selectedOrigins.length) {
        setSelectedEdgeIdSet((current) => {
          const next = new Set(current);
          for (const change of selectedOrigins) {
            if (change.type !== "select") continue;
            if (change.selected) next.add(change.id);
            else next.delete(change.id);
          }
          return next;
        });
      }
      if (artifactViewerChanges.length) {
        commitArtifactViewers((current) => ({
          ...current,
          edges: applyEdgeChanges(artifactViewerChanges, current.edges),
        }));
      }
      if (artifactViewerInteractionChanges.length) {
        const removedBindingIds = new Set(
          artifactViewerInteractionChanges.flatMap((change) =>
            change.type === "remove" ? [change.id] : [],
          ),
        );
        if (removedBindingIds.size) {
          commitArtifactViewers((current) => ({
            ...current,
            bindings: current.bindings.filter(
              (binding) => !removedBindingIds.has(binding.id),
            ),
          }));
        }
      }
    },
    [
      artifactOriginCanvasEdges,
      artifactViewers.bindings,
      artifactViewers.edges,
      applyAuthoringCommands,
      clearRunError,
      commitArtifactViewers,
      edges,
      setEdges,
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

  const updateEdgeRoute = React.useCallback(
    (edgeId: string, routeOffset: WorkflowEdgeRouteOffset) => {
      applyAuthoringCommands([
        {
          kind: "update_edge",
          edge_id: edgeId,
          update: { route_offset: routeOffset },
        },
      ]);
    },
    [applyAuthoringCommands],
  );

  /**
   * An artifact dropped on empty canvas lands on it: a card that presents that
   * artifact and can be passed into any input that takes it. It arrives the
   * same way from the library and from a node's output, because both carry one
   * artifact value.
   */
  const {
    addArtifactCards,
    collectSelectedArtifacts,
    tidySelectedArtifacts,
    ungroupArtifacts,
    ungroupCollection,
    updateArtifactCardRefs,
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
        setSelectedNodeIdSet(new Set([collectionId]));
        setSelectedEdgeIdSet(new Set());
      },
    },
    groupingDisabledReason,
    localAuthoringEnabled,
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

  /**
   * Drop the carried artifacts on empty canvas: one card per group they form.
   *
   * A Library drag of several artifacts arrives as one group per artifact type,
   * so a same-type selection lands as one sequence card and a mixed selection as
   * several cards laid side by side. A drop that asks for more than one card and
   * lands on empty canvas is still one drop: one commit places all of them.
   */
  const dropArtifactOnCanvas = React.useCallback(
    (event: DragEvent | React.DragEvent<HTMLElement>) => {
      if (!event.dataTransfer || !canvasAtPoint(event.clientX, event.clientY)) {
        return;
      }
      const groups = readArtifactDropGroups(event.dataTransfer);
      if (groups.length === 0) return;
      event.preventDefault();
      const point = flow?.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      }) ?? { x: 0, y: 0 };
      const positions = artifactCardDropPositions(
        point,
        groups.map((group) => cardArtifactRefs(group.value).length),
      );
      addArtifactCards(
        groups.map((group, index) => ({
          value: group.value,
          position: positions[index] ?? point,
        })),
      );
    },
    [addArtifactCards, flow],
  );

  /**
   * The card owns the order its artifacts are passed in, and an origin carries
   * what it was handed, so a reorder rewrites the origin beside the card.
   */
  const dragOverArtifactDrop = React.useCallback(
    (event: DragEvent | React.DragEvent<HTMLElement>) => {
      if (!event.dataTransfer || !isArtifactDrop(event.dataTransfer)) return;
      if (artifactDropRowAt(event.clientX, event.clientY)) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
        return;
      }
      if (!canvasAtPoint(event.clientX, event.clientY)) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    },
    [],
  );

  const dropArtifact = React.useCallback(
    (event: DragEvent | React.DragEvent<HTMLElement>) => {
      if (!event.dataTransfer || !isArtifactDrop(event.dataTransfer)) return;
      const row = artifactDropRowAt(event.clientX, event.clientY);
      if (!row) {
        dropArtifactOnCanvas(event);
        return;
      }
      event.preventDefault();
      // One input row takes one artifact value. A drag of several artifact types
      // has no honest reading here — filling the row with the first group and
      // silently dropping the rest would lose what the user picked up — so the
      // drop is refused and said.
      const groups = readArtifactDropGroups(event.dataTransfer);
      if (groups.length > 1) {
        setRunError(
          `Drop one artifact type at a time onto an input: this drag carries ${groups.length} kinds of artifact.`,
        );
        return;
      }
      const payload = readArtifactDrop(event.dataTransfer);
      const target = artifactDropTargetFromRow(row);
      if (!payload || !target) return;
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
      // A collection never repeats a member: an artifact it already gathers
      // stays where it is.
      if (
        isCollectionNode(node) &&
        collectionHoldsArtifacts(
          collectionMembers(
            node,
            nodesRef.current,
            edgesRef.current,
            authoredDocumentRef.current.origins,
          ),
          cardArtifactRefs(payload.value),
        )
      ) {
        return;
      }
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
      dropArtifactOnCanvas,
      registry?.artifact_conversions,
      registry?.artifact_types,
      setRunError,
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
      connection: Connection,
      collectionMode: RunEdgeCollectionMode,
      route: ConnectionRoute,
    ): string | null => {
      let committedConnection = connection;
      let newlyBoundNodeId: string | null = null;
      const binding = route.artifactTypeBinding;
      if (binding) {
        const handleId =
          binding.endpoint === "source"
            ? connection.sourceHandle
            : connection.targetHandle;
        const handle = decodeHandleId(handleId);
        const nodeId =
          binding.endpoint === "source" ? connection.source : connection.target;
        const node = nodes.find((candidate) => candidate.id === nodeId);
        const existingBinding =
          node?.data.artifactTypeBindings[binding.variable];
        if (
          !handle ||
          handle.artifactTypeVariable !== binding.variable ||
          !node ||
          (existingBinding &&
            (existingBinding.id !== binding.artifactType.id ||
              existingBinding.schema_version !==
                binding.artifactType.schema_version))
        ) {
          return null;
        }

        const concreteHandleId = encodeHandleId({
          portName: handle.portName,
          artifactTypeId: binding.artifactType.id,
          schemaVersion: binding.artifactType.schema_version,
          shape: handle.shape,
          direction: handle.direction,
          ...(handle.plugId ? { plugId: handle.plugId } : {}),
        });
        committedConnection =
          binding.endpoint === "source"
            ? { ...connection, sourceHandle: concreteHandleId }
            : { ...connection, targetHandle: concreteHandleId };
        if (!existingBinding) newlyBoundNodeId = nodeId;
      }

      const source = decodeHandleId(committedConnection.sourceHandle);
      const sourceArtifactType = source
        ? decodedHandleArtifactType(source)
        : null;
      const color = sourceArtifactType
        ? artifactTypeColor(sourceArtifactType.id, tokens.colorAccent)
        : tokens.colorAccent;
      const edgeStyle = {
        stroke: color,
        strokeWidth: 2,
      };
      const selection = connectionRouteSelection(route);
      const edge: WorkflowEdge = {
        ...committedConnection,
        id: `edge-${createUuid()}`,
        type: WORKFLOW_EDGE_TYPE,
        animated: false,
        data: {
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
        style: edgeStyle,
      };
      if (binding && newlyBoundNodeId) {
        const bindingNodeId = newlyBoundNodeId;
        // Binding replaces the generic handle ID. Keep the concrete edge pending
        // until WorkflowNode confirms React Flow has measured the replacement.
        pendingBoundEdgesRef.current = [
          ...pendingBoundEdgesRef.current,
          {
            nodeId: bindingNodeId,
            variable: binding.variable,
            artifactType: binding.artifactType,
            edge,
          },
        ];
        applyAuthoringCommands([
          {
            kind: "bind_artifact_type",
            node_id: bindingNodeId,
            variable: binding.variable,
            artifact_type: binding.artifactType,
          },
        ]);
      } else {
        applyAuthoringCommands([
          addEdgeCommand(committedConnection, edge.data, edge.id),
        ]);
      }
      clearRunError();
      return edge.id;
    },
    [applyAuthoringCommands, clearRunError, nodes],
  );

  /** Whether wiring these artifacts into this node would repeat a member. */
  const repeatsCollectionMember = React.useCallback(
    (nodeId: string, refs: ReturnType<typeof cardArtifactRefs>) => {
      const node = nodes.find((candidate) => candidate.id === nodeId);
      return Boolean(
        node &&
        isCollectionNode(node) &&
        collectionHoldsArtifacts(
          collectionMembers(
            node,
            nodes,
            edges,
            authoredDocumentRef.current.origins,
          ),
          refs,
        ),
      );
    },
    [edges, nodes],
  );

  const isValidConnection = React.useCallback<IsValidConnection<CanvasEdge>>(
    (connection) => {
      const candidate: Connection = {
        source: connection.source,
        sourceHandle: connection.sourceHandle ?? null,
        target: connection.target,
        targetHandle: connection.targetHandle ?? null,
      };
      if (candidate.sourceHandle === ARTIFACT_CARD_OUTPUT_HANDLE) {
        const resolved = resolveArtifactCardConnection(
          candidate,
          activeArtifactViewers.nodes,
          activeArtifactViewers.edges,
          nodes,
          registry?.artifact_conversions ?? [],
        );
        return (
          resolved !== null &&
          !repeatsCollectionMember(
            resolved.target.nodeId,
            cardArtifactRefs(resolved.payload.value),
          )
        );
      }
      if (
        candidate.sourceHandle === ARTIFACT_VIEWER_INTERACTION_OUTPUT_HANDLE ||
        candidate.targetHandle === ARTIFACT_VIEWER_INTERACTION_INPUT_HANDLE
      ) {
        return (
          candidate.sourceHandle ===
            ARTIFACT_VIEWER_INTERACTION_OUTPUT_HANDLE &&
          candidate.targetHandle === ARTIFACT_VIEWER_INTERACTION_INPUT_HANDLE &&
          candidate.source !== candidate.target &&
          activeArtifactViewers.nodes.some(
            (node) => node.id === candidate.source,
          ) &&
          activeArtifactViewers.nodes.some(
            (node) => node.id === candidate.target,
          ) &&
          !activeArtifactViewers.bindings.some(
            (binding) =>
              binding.sourceViewerId === candidate.source &&
              binding.targetViewerId === candidate.target,
          )
        );
      }
      if (
        candidate.targetHandle === ARTIFACT_VIEWER_INPUT_HANDLE &&
        activeArtifactViewers.nodes.some((node) => node.id === candidate.target)
      ) {
        const source = decodeHandleId(candidate.sourceHandle);
        const sourceNode = nodes.find((node) => node.id === candidate.source);
        return Boolean(
          source &&
          source.direction === "output" &&
          sourceNode?.data.spec.outputs.some(
            (port) => port.name === source.portName,
          ),
        );
      }
      return isConnectionAccepted(
        candidate,
        nodes,
        edges,
        registry?.artifact_types ?? [],
        registry?.artifact_conversions ?? [],
        "id" in connection ? connection.id : null,
      );
    },
    [
      activeArtifactViewers.nodes,
      activeArtifactViewers.edges,
      activeArtifactViewers.bindings,
      edges,
      nodes,
      repeatsCollectionMember,
      registry?.artifact_conversions,
      registry?.artifact_types,
    ],
  );

  const onConnect: OnConnect = React.useCallback(
    (connection) => {
      if (!isValidConnection(connection)) return;
      if (connection.sourceHandle === ARTIFACT_CARD_OUTPUT_HANDLE) {
        const resolved = resolveArtifactCardConnection(
          connection,
          activeArtifactViewers.nodes,
          activeArtifactViewers.edges,
          nodes,
          registry?.artifact_conversions ?? [],
        );
        if (
          !resolved ||
          repeatsCollectionMember(
            resolved.target.nodeId,
            cardArtifactRefs(resolved.payload.value),
          )
        ) {
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
      if (
        connection.sourceHandle === ARTIFACT_VIEWER_INTERACTION_OUTPUT_HANDLE &&
        connection.targetHandle === ARTIFACT_VIEWER_INTERACTION_INPUT_HANDLE
      ) {
        const binding: ArtifactViewerBinding = {
          id: `artifact-viewer-binding-${createUuid()}`,
          sourceViewerId: connection.source,
          targetViewerId: connection.target,
          mappings: [{ sourceField: "", targetField: "" }],
          effects: ["highlight", "focus"],
          emptySelection: "show_all",
        };
        commitArtifactViewers((current) => ({
          ...current,
          bindings: [...current.bindings, binding],
        }));
        setPendingConnectionRoute(null);
        return;
      }
      if (connection.targetHandle === ARTIFACT_VIEWER_INPUT_HANDLE) {
        const source = decodeHandleId(connection.sourceHandle);
        if (!source || source.direction !== "output") return;
        const edge: ArtifactViewerEdge = {
          id: `artifact-viewer-edge-${createUuid()}`,
          type: ARTIFACT_VIEWER_EDGE_TYPE,
          source: connection.source,
          target: connection.target,
          targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
          data: { sourcePortName: source.portName },
        };
        commitArtifactViewers((current) => ({
          ...current,
          edges: [
            ...current.edges.filter(
              (candidate) => candidate.target !== connection.target,
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
      );
      if (!collectionMode) return;

      const source = decodeHandleId(connection.sourceHandle);
      const target = decodeHandleId(connection.targetHandle);
      const canonicalConnection: Connection = {
        ...connection,
        sourceHandle: canonicalHandleId(connection.sourceHandle),
        targetHandle: canonicalHandleId(connection.targetHandle),
      };
      const allCandidates = connectionRoutesFor(
        canonicalConnection,
        registry?.artifact_types ?? [],
        registry?.artifact_conversions ?? [],
      );
      const candidates = orderFeedRoutes(
        routesForHandleFeed(allCandidates, source?.feed),
      );
      const preferred = preferredWholeFeedRoute(candidates);
      if (!preferred || !source || !target) return;

      // Connect first with the whole output (or sole route), then offer fields.
      const edgeId = addWorkflowEdge(
        canonicalConnection,
        collectionMode,
        preferred,
      );
      if (!edgeId || candidates.length <= 1) return;

      const sourceNode = nodes.find((node) => node.id === connection.source);
      const targetNode = nodes.find((node) => node.id === connection.target);
      if (!sourceNode || !targetNode) return;
      const sourceArtifactType = decodedHandleArtifactType(source);
      const targetArtifactType = decodedHandleArtifactType(target);

      const sourcePort = sourceNode.data.spec.outputs.find(
        (port) => port.name === source.portName,
      );
      const targetPort = targetNode.data.spec.inputs.find(
        (port) => port.name === target.portName,
      );
      setPendingConnectionRoute({
        connection: canonicalConnection,
        collectionMode,
        candidates,
        refineEdgeId: edgeId,
        preferredProjectionPath:
          source?.feed?.kind === "projection" ? source.feed.path : undefined,
        source: {
          nodeTitle: sourceNode.data.spec.title,
          portName: sourcePort?.title ?? source.portName,
          artifactType: sourceArtifactType
            ? formatArtifactTypeLabel(
                sourceArtifactType,
                registry?.artifact_types ?? null,
              )
            : `Any artifact · ${source.artifactTypeVariable}`,
        },
        target: {
          nodeTitle: targetNode.data.spec.title,
          portName: targetPort?.title ?? target.portName,
          artifactType: targetArtifactType
            ? formatArtifactTypeLabel(
                targetArtifactType,
                registry?.artifact_types ?? null,
              )
            : `Any artifact · ${target.artifactTypeVariable}`,
        },
      });
    },
    [
      activeArtifactViewers.nodes,
      activeArtifactViewers.edges,
      applyAuthoringCommands,
      clearRunError,
      addWorkflowEdge,
      repeatsCollectionMember,
      commitArtifactViewers,
      edges,
      isValidConnection,
      nodes,
      registry?.artifact_conversions,
      registry?.artifact_types,
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
      return flow?.screenToFlowPosition(client) ?? fallback;
    },
    [flow],
  );

  /** Adds a node with its corner at `at`, else centred on the canvas. */
  const addCatalogNode = React.useCallback(
    (spec: NodeSpec, at?: { x: number; y: number }) => {
      const id = `node-${createUuid()}`;
      const place = at ?? pickerInsertAtRef.current;
      pickerInsertAtRef.current = null;
      const center = canvasCenter({ x: 600, y: 280 });
      const data = attachNodeCallbacks(createWorkflowNodeData(spec));
      applyAuthoringCommands([
        addNodeCommand(
          id,
          data,
          place ?? { x: center.x - 140, y: center.y - 110 },
        ),
      ]);
      setSelectedNodeIdSet(new Set([id]));
      setSelectedEdgeIdSet(new Set());
      setLibraryOpen(false);
      setContextualDiscovery(null);
    },
    [applyAuthoringCommands, attachNodeCallbacks, canvasCenter],
  );

  const onConnectEnd = React.useCallback<OnConnectEnd>(
    (event, connectionState) => {
      setContextualDiscovery(null);
      if (!registry || !canEditGraph || running) return;
      if (!("fromHandle" in connectionState) || !connectionState.fromHandle) {
        return;
      }
      // Successful connections and drops onto handles/nodes keep existing behavior.
      if (
        connectionState.toHandle ||
        connectionState.toNode ||
        connectionState.isValid
      ) {
        return;
      }

      // An output with artifacts can be pulled onto the canvas. Other drags
      // offer compatible workflow nodes in the discovery menu.
      const upstream = connectionState.fromHandle.type === "target";
      const handleId = connectionState.fromHandle.id;
      if (!handleId) return;
      const decoded = decodeHandleId(handleId);
      if (
        !decoded ||
        (upstream
          ? decoded.direction !== "input"
          : decoded.direction !== "output")
      ) {
        return;
      }

      const fromNode = nodes.find(
        (node) => node.id === connectionState.fromNode?.id,
      );
      if (!fromNode || !workflowNodeIsSupported(fromNode.data)) return;
      const port = upstream
        ? fromNode.data.spec.inputs.find(
            (candidate) => candidate.name === decoded.portName,
          )
        : fromNode.data.spec.outputs.find(
            (candidate) => candidate.name === decoded.portName,
          );
      if (!port) return;

      const clientPoint =
        "changedTouches" in event
          ? {
              x: event.changedTouches[0]?.clientX ?? 0,
              y: event.changedTouches[0]?.clientY ?? 0,
            }
          : { x: event.clientX, y: event.clientY };
      const flowPosition = flow?.screenToFlowPosition(clientPoint) ?? {
        x: upstream
          ? fromNode.position.x
          : fromNode.position.x + DEFAULT_NODE_WIDTH,
        y: connectionState.to?.y ?? fromNode.position.y,
      };

      const materializedOutput =
        !upstream && fromNode.data.run?.status === "succeeded"
          ? fromNode.data.run.outputs.find(
              (output) =>
                output.port === port.name && output.artifacts.length > 0,
            )
          : null;
      if (materializedOutput && canvasAtPoint(clientPoint.x, clientPoint.y)) {
        const viewerId = `artifact-viewer-${createUuid()}`;
        const link: ArtifactViewerEdge = {
          id: `artifact-viewer-edge-${createUuid()}`,
          type: ARTIFACT_VIEWER_EDGE_TYPE,
          source: fromNode.id,
          target: viewerId,
          targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
          data: { sourcePortName: port.name },
        };
        commitArtifactViewers((current) => ({
          ...current,
          nodes: [
            ...current.nodes.map((node) => ({ ...node, selected: false })),
            {
              id: viewerId,
              type: ARTIFACT_VIEWER_NODE_TYPE,
              position: flowPosition,
              selected: true,
              data: {
                layout: null,
                mode: "artifact",
                artifactRef: null,
              },
            },
          ],
          edges: [...current.edges, link],
        }));
        setLibraryOpen(false);
        return;
      }

      const catalogNodes = catalogNodeSpecs(registry, activeGraph?.id ?? null);
      const candidates = upstream
        ? upstreamCandidatesFromInput({
            targetPort: port as typeof port & {
              readonly direction: "input";
            },
            targetHandle: handleId,
            registry,
            nodes: catalogNodes,
          })
        : downstreamCandidatesFromOutput({
            sourcePort: port as typeof port & {
              readonly direction: "output";
            },
            sourceHandle: handleId,
            sourceFeed: decoded.feed ?? null,
            registry,
            nodes: catalogNodes,
          });
      if (!candidates.length) return;

      setLibraryOpen(false);
      setContextualDiscovery({
        graphId: activeGraph?.id ?? null,
        sourceNodeId: fromNode.id,
        sourceHandle: handleId,
        sourcePortTitle: port.title ?? port.name,
        direction: upstream ? "upstream" : "downstream",
        clientAnchor: clientPoint,
        flowPosition,
        candidates,
      });
    },
    [
      activeGraph?.id,
      canEditGraph,
      commitArtifactViewers,
      flow,
      nodes,
      registry,
      running,
    ],
  );

  const confirmContextualDiscovery = React.useCallback(
    (candidate: ContextualCandidate, choice: ContextualRouteChoice) => {
      if (!contextualDiscovery || !registry || !canEditGraph || running) return;

      const upstream = contextualDiscovery.direction === "upstream";
      const id = `node-${createUuid()}`;
      const data = attachNodeCallbacks(createWorkflowNodeData(candidate.spec));
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

      const candidateHandle = encodeHandleId(
        portMetaForPort(
          choice.candidatePort,
          choice.candidatePort.shape,
          upstream ? undefined : plugId,
          data.artifactTypeBindings,
        ),
      );
      const existingHandle = canonicalHandleId(
        contextualDiscovery.sourceHandle,
      );
      const edgeConnection = upstream
        ? {
            source: id,
            sourceHandle: candidateHandle,
            target: contextualDiscovery.sourceNodeId,
            targetHandle: existingHandle,
          }
        : {
            source: contextualDiscovery.sourceNodeId,
            sourceHandle: existingHandle,
            target: id,
            targetHandle: candidateHandle,
          };
      const edgeId = `edge-${createUuid()}`;
      const selection = connectionRouteSelection(choice.route);
      const nodeCommand = addNodeCommand(id, data, {
        x: contextualDiscovery.flowPosition.x,
        y:
          contextualDiscovery.flowPosition.y -
          DEFAULT_NODE_PLACEMENT_HEIGHT / 2,
      });

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
      setSelectedNodeIdSet(new Set([id]));
      setSelectedEdgeIdSet(new Set());
      setContextualDiscovery(null);
      clearRunError();
    },
    [
      applyAuthoringCommands,
      attachNodeCallbacks,
      canEditGraph,
      clearRunError,
      contextualDiscovery,
      registry,
      running,
    ],
  );

  const activeContextualDiscovery =
    canEditGraph &&
    !running &&
    contextualDiscovery?.graphId === (activeGraph?.id ?? null)
      ? contextualDiscovery
      : null;

  /** Adds a viewer at `at`, else beside the selected node or mid-canvas. */
  const addArtifactViewer = React.useCallback(
    (at?: { x: number; y: number }) => {
      const id = `artifact-viewer-${createUuid()}`;
      const center = canvasCenter({ x: 600, y: 280 });
      const selectedSource = at
        ? undefined
        : nodes.find((node) => node.selected);
      const position =
        at ??
        (selectedSource
          ? {
              x: selectedSource.position.x + 380,
              y: selectedSource.position.y - 20,
            }
          : { x: center.x - 260, y: center.y - 180 });
      setNodes((current) =>
        current.map((node) => ({ ...node, selected: false })),
      );
      commitArtifactViewers((current) => ({
        ...current,
        nodes: [
          ...current.nodes.map((node) => ({ ...node, selected: false })),
          {
            id,
            type: ARTIFACT_VIEWER_NODE_TYPE,
            position,
            selected: true,
            data: {
              layout: { width: DEFAULT_NODE_WIDTH },
              mode: null,
            },
          },
        ],
        annotations: current.annotations.map((node) => ({
          ...node,
          selected: false,
        })),
      }));
      setLibraryOpen(false);
      setShapesMenuOpen(false);
      closeGraphBrowser();
      if (flow && selectedSource) {
        window.requestAnimationFrame(() => {
          void flow.fitView({
            nodes: [{ id: selectedSource.id }, { id }],
            padding: 0.22,
            maxZoom: 0.94,
            duration: 220,
          });
        });
      }
    },
    [
      canvasCenter,
      closeGraphBrowser,
      commitArtifactViewers,
      flow,
      nodes,
      setNodes,
    ],
  );

  /** Adds an annotation with its corner at `at`, else mid-canvas. */
  const addAnnotation = React.useCallback(
    (kind: AnnotationKind, at?: { x: number; y: number }) => {
      const center = canvasCenter({ x: 480, y: 240 });
      const annotation = createAnnotationNode(
        kind,
        at ?? { x: center.x - 80, y: center.y - 60 },
      );
      setNodes((current) =>
        current.map((node) => ({ ...node, selected: false })),
      );
      commitArtifactViewers((current) => ({
        ...current,
        nodes: current.nodes.map((node) => ({ ...node, selected: false })),
        annotations: [
          ...current.annotations.map((node) => ({ ...node, selected: false })),
          annotation,
        ],
      }));
      setShapesMenuOpen(false);
      setLibraryOpen(false);
      closeGraphBrowser();
    },
    [canvasCenter, closeGraphBrowser, commitArtifactViewers, setNodes],
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
    const duplicatedNodeIdSet = new Set(duplicatedNodes.map((node) => node.id));
    setSelectedNodeIdSet(duplicatedNodeIdSet);
    setSelectedEdgeIdSet(new Set());
    if (selectedViewers.length) {
      const viewerIds = new Map(
        selectedViewers.map((node) => [
          node.id,
          `artifact-viewer-${createUuid()}`,
        ]),
      );
      commitArtifactViewers((current) => ({
        ...current,
        nodes: [
          ...current.nodes.map((node) => ({ ...node, selected: false })),
          ...selectedViewers.map((node) => ({
            ...node,
            id: viewerIds.get(node.id) ?? node.id,
            position: {
              x: node.position.x + 36,
              y: node.position.y + 36,
            },
            selected: true,
            data: {
              layout: node.data.layout,
              mode: node.data.mode,
              artifactRef: node.data.artifactRef,
            },
          })),
        ],
      }));
    } else {
      commitArtifactViewers((current) => ({
        ...current,
        nodes: current.nodes.map((node) => ({ ...node, selected: false })),
        annotations: current.annotations.map((node) => ({
          ...node,
          selected: false,
        })),
      }));
    }
    setPendingConnectionRoute(null);
    setRunError(null);
  }, [
    applyAuthoringCommands,
    artifactViewers.nodes,
    authoredDocument,
    commitArtifactViewers,
    nodes,
    running,
  ]);

  const deleteSelectedNodes = React.useCallback(() => {
    if (!flow || !selectedNodeIds.length || running) return;
    setPendingConnectionRoute(null);
    setRunError(null);
    void flow.deleteElements({
      nodes: selectedNodeIds.map((id) => ({ id })),
    });
  }, [flow, running, selectedNodeIds]);

  const canvasNodes = React.useMemo(
    () =>
      nodes.map((node) => {
        const savedNode = activeGraph?.nodes.find(
          (candidate) => candidate.id === node.id,
        );
        return {
          ...node,
          data: {
            ...attachNodeCallbacks(node.data),
            historyContext: {
              workspaceId,
              graphId: activeGraph?.id ?? null,
              isDirty,
            },
            secretStatuses: nodeSecretStatuses[node.id] ?? {},
            secretInputReadiness: Object.fromEntries(
              (workflowNodeIsSupported(node.data)
                ? nodeSecretInputs(node.data.spec)
                : []
              ).map((input) => [
                input.name,
                nodeSecretBindingReady(
                  input,
                  {
                    id: node.id,
                    operator_id: node.data.spec.operator_id,
                    operator_version: node.data.spec.operator_version,
                    config: node.data.config,
                  },
                  savedNode,
                ),
              ]),
            ),
            secretInputScope: `${activeGraph?.id ?? "unsaved"}:${activeGraph?.revision ?? "none"}`,
            onApplyNodeSecret: applyConfiguredNodeSecret,
            onRemoveNodeSecret: removeConfiguredNodeSecret,
            mappedInputPort: mappedInputPortForNode(node.id, edges),
            inputPlugBindings: inputPlugBindingsForNode(
              node,
              nodes,
              edges,
              registry?.artifact_conversions ?? [],
              registry?.artifact_types ?? [],
            ),
            ...(isCollectionNode(node)
              ? {
                  collectionMembers: collectionMembers(
                    node,
                    nodes,
                    edges,
                    authoredDocument.origins,
                  ),
                  ungroupDisabledReason: ungroupCollectionDisabledReason(
                    node.id,
                    edges,
                  ),
                  onUngroupCollection: localAuthoringEnabled
                    ? ungroupCollection
                    : undefined,
                }
              : {}),
          },
        };
      }),
    [
      activeGraph,
      authoredDocument.origins,
      localAuthoringEnabled,
      ungroupCollection,
      applyConfiguredNodeSecret,
      attachNodeCallbacks,
      edges,
      isDirty,
      nodeSecretStatuses,
      nodes,
      registry,
      removeConfiguredNodeSecret,
      workspaceId,
    ],
  );

  const canvasEdges = React.useMemo(
    () =>
      edges.map((edge) => {
        const connection: Connection = {
          source: edge.source,
          sourceHandle: edge.sourceHandle ?? null,
          target: edge.target,
          targetHandle: edge.targetHandle ?? null,
        };
        const source = decodeHandleId(edge.sourceHandle);
        const activeSelection = {
          projection: edge.data?.projection,
          conversionPath: edge.data?.conversionPath ?? [],
        };
        const routes = connectionRoutesFor(
          connection,
          registry?.artifact_types ?? [],
          registry?.artifact_conversions ?? [],
        );
        const activeRoute = connectionRouteForSelection(
          connection,
          registry?.artifact_types ?? [],
          registry?.artifact_conversions ?? [],
          activeSelection,
        );
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
        const otherEdges = edges.filter(
          (candidate) => candidate.id !== edge.id,
        );
        const validMode = collectionModeForConnection(
          connection,
          nodes,
          otherEdges,
        );
        return {
          ...edge,
          type: WORKFLOW_EDGE_TYPE,
          data: {
            ...edge.data,
            enabled: edge.data?.enabled ?? true,
            collectionMode: edge.data?.collectionMode ?? "direct",
            sourcePortName: source?.portName ?? edge.data?.sourcePortName,
            conversionTitles,
            routeOptions,
            allowedCollectionModes:
              edge.data?.compatibilityIssues?.length || !validMode
                ? []
                : [validMode],
            onUpdate: edge.data?.compatibilityIssues?.length
              ? undefined
              : (edgeId: string, update: WorkflowEdgeUpdate) => {
                  // React Flow stores this callback and invokes it from edge UI events.
                  // eslint-disable-next-line react-hooks/refs
                  updateEdge(edgeId, update);
                },
            onRouteOffsetChange: (
              edgeId: string,
              routeOffset: WorkflowEdgeRouteOffset,
            ) => {
              // React Flow stores this callback and invokes it from edge UI events.
              // eslint-disable-next-line react-hooks/refs
              updateEdgeRoute(edgeId, routeOffset);
            },
          },
        };
      }),
    [
      edges,
      nodes,
      registry?.artifact_conversions,
      registry?.artifact_types,
      updateEdge,
      updateEdgeRoute,
    ],
  );

  const artifactViewerCanvasNodes = React.useMemo<ArtifactViewerNode[]>(
    () =>
      activeArtifactViewers.nodes.map((node) => {
        const sourceBindings = activeArtifactViewers.bindings.filter(
          (binding) => binding.sourceViewerId === node.id,
        );
        const incomingBindings = activeArtifactViewers.bindings
          .filter((binding) => binding.targetViewerId === node.id)
          .map((binding) => {
            const sourceSelection =
              artifactViewerSelections[binding.sourceViewerId] ??
              EMPTY_ARTIFACT_KEY_SELECTION;
            return {
              bindingId: binding.id,
              effects: binding.effects,
              sourceSelectionCount: sourceSelection.items.length,
              rows: targetRowsForBinding(binding, sourceSelection),
            };
          });
        return {
          ...node,
          data: {
            ...node.data,
            outgoingFields: [
              ...new Set(
                sourceBindings.flatMap((binding) =>
                  binding.mappings.map((mapping) => mapping.sourceField),
                ),
              ),
            ].filter(Boolean),
            selection:
              artifactViewerSelections[node.id] ?? EMPTY_ARTIFACT_KEY_SELECTION,
            incomingBindings,
            fields: artifactViewerFields[node.id] ?? [],
            onLayoutChange: updateArtifactViewerLayout,
            onModeChange: updateArtifactViewerMode,
            onRefsChange: updateArtifactCardRefs,
            onUngroup: ungroupArtifacts,
            ungroupDisabledReason: artifactGroupingDisabledReason({
              cards: [node],
              state: activeArtifactViewers,
              origins: authoredDocument.origins,
            }),
            onSelectionChange: updateArtifactViewerSelection,
            onFieldsChange: updateArtifactViewerFields,
            onActivityChange: updateArtifactViewerActivity,
            onRemoveNode: removeArtifactViewer,
          },
        };
      }),
    [
      activeArtifactViewers,
      authoredDocument.origins,
      ungroupArtifacts,
      artifactViewerFields,
      artifactViewerSelections,
      removeArtifactViewer,
      updateArtifactCardRefs,
      updateArtifactViewerActivity,
      updateArtifactViewerLayout,
      updateArtifactViewerMode,
      updateArtifactViewerFields,
      updateArtifactViewerSelection,
    ],
  );

  const annotationCanvasNodes = React.useMemo<AnnotationNode[]>(
    () =>
      activeArtifactViewers.annotations.map((node) => ({
        ...node,
        // Re-assert on every render so selection elevation never stacks above cards.
        zIndex: ANNOTATION_Z_INDEX,
        data: {
          ...node.data,
          onLayoutChange: updateAnnotationLayout,
          onTextChange: updateAnnotationText,
          onColorChange: updateAnnotationColor,
          onRemoveNode: removeAnnotation,
        },
      })),
    [
      activeArtifactViewers.annotations,
      removeAnnotation,
      updateAnnotationColor,
      updateAnnotationLayout,
      updateAnnotationText,
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
        const sourceHandle =
          sourceNode && sourcePort && workflowNodeIsSupported(sourceNode.data)
            ? encodeHandleId(
                portMetaForPort(
                  sourcePort,
                  effectivePortShape(sourceNode.data, sourcePort),
                  undefined,
                  sourceNode.data.artifactTypeBindings,
                ),
              )
            : null;
        return {
          ...edge,
          type: ARTIFACT_VIEWER_EDGE_TYPE,
          sourceHandle,
          targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
          data: {
            ...edge.data,
            sourcePortName: edge.data?.sourcePortName ?? "",
            projectionTitle: activeProjectionTitle,
            routeOptions,
            onUpdate: updateArtifactViewerEdge,
            onRouteOffsetChange: updateArtifactViewerEdgeRoute,
          },
          style: {
            ...edge.style,
            stroke: sourceArtifactTypeKey
              ? artifactTypeColor(sourceArtifactTypeKey.id, tokens.colorAccent)
              : tokens.colorAccent,
            strokeWidth: 2,
          },
        };
      }),
    [
      activeArtifactViewers.edges,
      nodes,
      registry?.artifact_types,
      updateArtifactViewerEdge,
      updateArtifactViewerEdgeRoute,
    ],
  );

  const artifactViewerInteractionCanvasEdges = React.useMemo<
    ArtifactViewerInteractionEdge[]
  >(
    () =>
      activeArtifactViewers.bindings.map((binding) => ({
        id: binding.id,
        type: ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE,
        source: binding.sourceViewerId,
        sourceHandle: ARTIFACT_VIEWER_INTERACTION_OUTPUT_HANDLE,
        target: binding.targetViewerId,
        targetHandle: ARTIFACT_VIEWER_INTERACTION_INPUT_HANDLE,
        data: {
          binding,
          sourceFields: artifactViewerFields[binding.sourceViewerId] ?? [],
          targetFields: artifactViewerFields[binding.targetViewerId] ?? [],
          onBindingChange: updateArtifactViewerBinding,
        },
        style: {
          stroke: tokens.colorInfo,
          strokeWidth: 2,
        },
      })),
    [
      activeArtifactViewers.bindings,
      artifactViewerFields,
      updateArtifactViewerBinding,
    ],
  );

  const allCanvasNodes = React.useMemo<CanvasNode[]>(() => {
    const combined = [
      ...annotationCanvasNodes,
      ...canvasNodes,
      ...artifactViewerCanvasNodes,
    ];
    const localDragging = new Set(Object.keys(transientNodePositions));
    const alignIdlePosition = shouldSnapPosition(canvasGridSettings, {
      dragging: false,
      bypass: bypassSnap,
    });
    return combined.map((node) => {
      const transientPosition = transientNodePositions[node.id];
      let positioned = transientPosition
        ? {
            ...node,
            position: transientPosition,
            dragging: true,
          }
        : node;
      const preview = !localDragging.has(node.id)
        ? remoteDragPreviews[node.id]
        : undefined;
      if (preview) {
        positioned = {
          ...positioned,
          position: { x: preview.x, y: preview.y },
          style: {
            ...positioned.style,
            // Ease between sparse presence samples without per-frame React writes.
            transition: "transform 70ms linear",
          },
        };
      }
      // Keep idle cards on the lattice even when stored coords predate snapping.
      if (!preview && !localDragging.has(node.id) && alignIdlePosition) {
        const snapped = snapPosition(
          positioned.position,
          canvasGridSettings.cellSize,
        );
        if (
          snapped.x !== positioned.position.x ||
          snapped.y !== positioned.position.y
        ) {
          positioned = { ...positioned, position: snapped };
        }
      }
      const remoteColor = remoteSelectionColor(
        graphRoom.participants,
        graphRoom.localSessionId,
        node.id,
      );
      if ((positioned.data.remoteSelectionColor ?? null) === remoteColor) {
        return positioned;
      }
      return {
        ...positioned,
        data: {
          ...positioned.data,
          remoteSelectionColor: remoteColor,
        },
      } as CanvasNode;
    });
  }, [
    annotationCanvasNodes,
    artifactViewerCanvasNodes,
    bypassSnap,
    canvasGridSettings,
    canvasNodes,
    graphRoom.localSessionId,
    graphRoom.participants,
    remoteDragPreviews,
    transientNodePositions,
  ]);
  const allCanvasEdges = React.useMemo<CanvasEdge[]>(
    () => [
      ...canvasEdges,
      ...artifactViewerCanvasEdges,
      ...artifactViewerInteractionCanvasEdges,
      ...artifactOriginCanvasEdges,
    ],
    [
      artifactViewerCanvasEdges,
      artifactViewerInteractionCanvasEdges,
      artifactOriginCanvasEdges,
      canvasEdges,
    ],
  );

  const snapSelectionToGrid = React.useCallback(() => {
    const settings = canvasGridSettingsRef.current;
    if (!settings.enabled || bypassSnapRef.current) return;
    const selected = allCanvasNodes.filter((node) =>
      selectedNodeIdSet.has(node.id),
    );
    if (!selected.length) return;
    const cellSize = settings.cellSize;

    if (settings.snapPosition) {
      const workflowPositions = selected.flatMap((node) => {
        if (node.type !== WORKFLOW_NODE_TYPE) return [];
        const next = snapPosition(node.position, cellSize);
        return [{ node_id: node.id, x: next.x, y: next.y }];
      });
      if (workflowPositions.length) {
        applyAuthoringCommands([
          {
            kind: "move_nodes",
            positions: workflowPositions,
          },
        ]);
      }
      const viewerPositions = selected.flatMap((node) => {
        if (node.type !== ARTIFACT_VIEWER_NODE_TYPE) return [];
        const next = snapPosition(node.position, cellSize);
        return [{ viewer_id: node.id, x: next.x, y: next.y }];
      });
      if (viewerPositions.length) {
        const byId = new Map(
          viewerPositions.map((position) => [position.viewer_id, position]),
        );
        setArtifactViewers((current) => ({
          ...current,
          nodes: current.nodes.map((node) => {
            const next = byId.get(node.id);
            return next
              ? { ...node, position: { x: next.x, y: next.y } }
              : node;
          }),
        }));
        presentationRoomSyncRef.current.submitMove(viewerPositions);
      }
    }

    if (settings.snapSize) {
      for (const node of selected) {
        if (node.type === WORKFLOW_NODE_TYPE) {
          const current = node.data.layout;
          const seed = {
            width: current?.width ?? DEFAULT_NODE_WIDTH,
            ...(current?.bodyHeight != null
              ? { bodyHeight: current.bodyHeight }
              : {}),
            ...(current?.appendixHeight != null
              ? { appendixHeight: current.appendixHeight }
              : {}),
          };
          const axes = layoutSnapAxes(seed, ["width"]);
          updateLayout(node.id, snapNodeLayout(seed, axes, cellSize));
          continue;
        }
        if (node.type === ARTIFACT_VIEWER_NODE_TYPE) {
          const current = node.data.layout;
          const seed = {
            width: current?.width ?? DEFAULT_NODE_WIDTH,
            bodyHeight:
              current?.bodyHeight ??
              artifactCardMediaHeight(DEFAULT_ARTIFACT_CARD_WIDTH),
            appendixHeight: current?.appendixHeight ?? DEFAULT_APPENDIX_HEIGHT,
          };
          const snapped = snapNodeLayout(
            seed,
            ["width", "bodyHeight", "appendixHeight"],
            cellSize,
          );
          updateArtifactViewerLayout(node.id, snapped);
        }
      }
    }
  }, [
    allCanvasNodes,
    applyAuthoringCommands,
    selectedNodeIdSet,
    updateArtifactViewerLayout,
    updateLayout,
  ]);

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
    [],
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
  const visibleExecutionNodeTitle = visibleExecution?.activeNodeId
    ? nodes.find((node) => node.id === visibleExecution.activeNodeId)?.data.spec
        .title
    : null;
  const executionCancelling = visibleExecution?.status === "cancelling";
  const visibleExecutionTitle =
    visibleExecutionNodeTitle ??
    (executionCancelling ? "Stopping execution…" : "Preparing…");
  const visibleExecutionStatus =
    visibleExecution?.statusError ??
    (executionCancelling
      ? "Waiting for the current node to stop"
      : visibleExecution?.status === "queued"
        ? visibleExecution.queuePosition
          ? `Queue position ${visibleExecution.queuePosition}`
          : "Waiting for a worker"
        : visibleExecution?.status === "running"
          ? "Processing node"
          : "Starting execution");
  const viewerActivity = latestArtifactViewerActivity?.value.activity ?? null;
  let viewerActivityAction: WorkbenchActivity["action"];
  if (latestArtifactViewerActivity && viewerActivity?.retry) {
    viewerActivityAction = {
      kind: "retry",
      label: "Retry",
      ariaLabel: `Retry ${viewerActivity.title}`,
      onInvoke: viewerActivity.retry,
    };
  } else if (
    latestArtifactViewerActivity &&
    (viewerActivity?.state === "warning" || viewerActivity?.state === "error")
  ) {
    viewerActivityAction = {
      kind: "dismiss",
      label: "Dismiss",
      ariaLabel: `Dismiss ${viewerActivity.title}`,
      onInvoke: () =>
        dismissArtifactViewerActivity(
          latestArtifactViewerActivity.nodeId,
          latestArtifactViewerActivity.value.revision,
        ),
    };
  }
  const workbenchActivity: WorkbenchActivity | null = visibleExecution
    ? {
        eyebrow: "Execution",
        title: visibleExecutionTitle,
        message: visibleExecutionStatus,
        tone: executionCancelling
          ? "cancelling"
          : visibleExecution.statusError
            ? "error"
            : "working",
        action: {
          kind: "cancel",
          label: executionCancelling ? "Cancelling" : "Cancel",
          ariaLabel: executionCancelling
            ? "Cancelling execution"
            : "Cancel execution",
          disabled:
            !canCancelExecution ||
            !visibleExecution.executionId ||
            executionCancelling,
          onInvoke: () => void cancelCurrentExecution(),
        },
      }
    : viewerActivity
      ? {
          eyebrow: "Linked view",
          title: viewerActivity.title,
          message: viewerActivity.message,
          tone: viewerActivity.state,
          action: viewerActivityAction,
        }
      : null;

  // --- The canvas right-click menu --------------------------------------------

  const openCanvasMenu = React.useCallback(
    (request: CanvasMenuRequest) => {
      setLibraryOpen(false);
      setShapesMenuOpen(false);
      setGridPanelOpen(false);
      setContextualDiscovery(null);
      closeGraphBrowser();
      let { target } = request;
      if (target.kind === "node") {
        const nodeId = target.nodeId;
        const selection = selectedNodeIdsRef.current;
        if (selection.length > 1 && selection.includes(nodeId)) {
          target = { kind: "selection" };
        } else {
          // The menu speaks about the node under the pointer, so that node
          // becomes the selection, as a left click would make it.
          onNodesChange(
            allCanvasNodes.map((node) => ({
              id: node.id,
              type: "select" as const,
              selected: node.id === nodeId,
            })),
          );
          onEdgesChange(
            allCanvasEdges
              .filter((edge) => edge.selected)
              .map((edge) => ({
                id: edge.id,
                type: "select" as const,
                selected: false,
              })),
          );
        }
      }
      const focused = document.activeElement;
      setCanvasMenu({
        ...request,
        target,
        returnFocus: focused instanceof HTMLElement ? focused : null,
      });
    },
    [
      allCanvasEdges,
      allCanvasNodes,
      closeGraphBrowser,
      onEdgesChange,
      onNodesChange,
      setGridPanelOpen,
    ],
  );
  const canvasMenuTrigger = useCanvasMenuTrigger(openCanvasMenu);
  const canvasMenuPoint =
    canvasMenu && flow ? flow.screenToFlowPosition(canvasMenu.point) : null;
  const canvasMenuSelection: CanvasMenuSelection = {
    count: selectedNodeCount,
    workflowCount: selectedWorkflowCount,
    canRun: !runSelectedDisabled,
    canDuplicate:
      Boolean(selectedWorkflowCount || selectedViewerCount) &&
      localAuthoringEnabled,
    canDelete: Boolean(flow) && selectedNodeCount > 0 && localAuthoringEnabled,
    collect: collectSpec
      ? selectedCollectionSources.length > 1
        ? {
            disabled:
              !localAuthoringEnabled || Boolean(collectionDisabledReason),
            title: collectionDisabledReason ?? undefined,
          }
        : null
      : selectedArtifactCards.length > 1
        ? {
            disabled:
              !collectedArtifactRefs ||
              !localAuthoringEnabled ||
              Boolean(groupingDisabledReason),
            title: groupingDisabledReason ?? undefined,
          }
        : null,
    canTidy:
      !selectedWorkflowCount &&
      selectedArtifactCards.length > 1 &&
      localAuthoringEnabled,
  };
  const canvasMenuActions: CanvasMenuActions = {
    searchNodes: () => {
      pickerInsertAtRef.current = canvasMenuPoint;
      setLibraryOpen(true);
    },
    addNodeHere: (spec) => addCatalogNode(spec, canvasMenuPoint ?? undefined),
    addViewerHere: () => addArtifactViewer(canvasMenuPoint ?? undefined),
    addAnnotationHere: (kind) =>
      addAnnotation(kind, canvasMenuPoint ?? undefined),
    selectAll: () =>
      onNodesChange(
        allCanvasNodes.map((node) => ({
          id: node.id,
          type: "select" as const,
          selected: true,
        })),
      ),
    fitView: () =>
      void flow?.fitView({ ...workbenchFitViewOptions, duration: 220 }),
    openCanvasSettings: () => setGridPanelOpen(true),
    runSelection: () => void runWorkflow("selected"),
    collect: collectSelectedArtifacts,
    tidy: tidySelectedArtifacts,
    duplicate: duplicateSelectedNodes,
    remove: deleteSelectedNodes,
    fitSelection: () =>
      void flow?.fitView({
        nodes: selectedNodeIds.map((id) => ({ id })),
        padding: 0.3,
        maxZoom: 1.2,
        duration: 220,
      }),
    deleteEdge: (edgeId) => {
      if (!flow || !localAuthoringEnabled || running) return;
      void flow.deleteElements({ edges: [{ id: edgeId }] });
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
      setGridPanelOpen(false);
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
      activeGraphId: activeGraph?.id ?? null,
      graphName,
      isDirty,
      saving,
      canSave:
        localAuthoringEnabled &&
        !saving &&
        !running &&
        !openingGraphId &&
        !deletingGraphId &&
        Boolean(activeGraph ? isDirty : true),
      save: async () => {
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
        if (!canEditGraph) {
          throw new Error("You do not have permission to rename graphs.");
        }
        if (activeGraph?.id === graph.id) {
          setGraphName(name);
          await saveCurrentGraph(name);
          return;
        }
        await renameSavedGraphRemote(workspaceId, graph, name);
        void refreshSavedGraphs();
      },
      deleteGraph: async (graph: SavedGraphSummary) => {
        if (!canDeleteGraph) {
          throw new Error("You do not have permission to delete graphs.");
        }
        await removeSavedGraph(graph);
      },
    };
  }, [
    activeGraph,
    canDeleteGraph,
    canEditGraph,
    closeGraphBrowser,
    deletingGraphId,
    graphName,
    isDirty,
    localAuthoringEnabled,
    openingGraphId,
    refreshSavedGraphs,
    removeSavedGraph,
    running,
    saveCurrentGraph,
    saving,
    setGraphName,
    setGridPanelOpen,
    setSidePanelOpen,
    setSidePanelView,
    sidePanelIsOpen,
    sidePanelView,
    workspaceId,
  ]);
  usePublishWorkbenchChrome(chromeValue);

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
      {activeGraph ? (
        <GraphRoomRecoveryNotice
          readiness={displayedGraphReadiness.state}
          status={graphRoom.status}
          failure={graphRoom.failure}
          terminalReason={graphRoom.terminalReason}
          onRetry={graphRoom.retry}
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
        onPointerMove={(event) => {
          if (!graphRoom.canPublishPresence || !flow) return;
          presenceOverCanvasRef.current = true;
          presenceClientPointRef.current = {
            x: event.clientX,
            y: event.clientY,
          };
          presenceClientPointDirtyRef.current = true;
          schedulePresenceSnapshot();
        }}
        onPointerLeave={() => {
          presenceOverCanvasRef.current = false;
          presenceClientPointRef.current = null;
          presenceClientPointDirtyRef.current = false;
          presenceCursorRef.current = null;
          schedulePresenceSnapshot();
        }}
      >
        <NodeMenuRegistryContext.Provider value={nodeMenus}>
          <WorkflowCanvas
            fitViewOptions={workbenchFitViewOptions}
            nodes={allCanvasNodes}
            edges={allCanvasEdges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            onConnectEnd={onConnectEnd}
            isValidConnection={isValidConnection}
            editable={localAuthoringEnabled}
            onPaneReady={setFlow}
            onPaneClick={() => {
              setLibraryOpen(false);
              setContextualDiscovery(null);
              closeGraphBrowser();
              setGridPanelOpen(false);
            }}
            animateEdges={running}
            gridGap={
              canvasGridSettings.showBackground
                ? canvasGridSettings.cellSize
                : null
            }
            onlyRenderVisibleElements={
              canvasGridSettings.onlyRenderVisibleElements
            }
          >
            <PresenceOverlay
              participants={graphRoom.participants}
              localSessionId={graphRoom.localSessionId}
            />
            {selectedWorkflowCount ||
            selectedArtifactCards.length > 1 ||
            selectedCollectionSources.length > 1 ? (
              <NodeToolbar
                nodeId={selectedNodeIds}
                isVisible
                position={Position.Top}
                offset={20}
                className={`grafy-node-detail ${stylex.props(s.selectionToolbar).className}`}
              >
                <span {...stylex.props(s.selectionLabel)}>
                  {selectedNodeCount} selected
                </span>
                <span {...stylex.props(s.selectionDivider)} />
                {collectSpec ? (
                  selectedCollectionSources.length > 1 ? (
                    <button
                      type="button"
                      disabled={
                        !localAuthoringEnabled ||
                        Boolean(collectionDisabledReason)
                      }
                      title={
                        collectionDisabledReason ??
                        `Collect ${selectedCollectionSources.length} selected artifacts into one collection`
                      }
                      {...stylex.props(s.toolButton, s.primaryButton)}
                      onClick={collectSelectedArtifacts}
                    >
                      <Layers size={13} />
                      Collect
                    </button>
                  ) : null
                ) : selectedArtifactCards.length > 1 ? (
                  <button
                    type="button"
                    disabled={
                      !collectedArtifactRefs ||
                      !localAuthoringEnabled ||
                      Boolean(groupingDisabledReason)
                    }
                    title={
                      groupingDisabledReason ??
                      (collectedArtifactRefs
                        ? `Collect ${selectedArtifactCards.length} selected artifacts into an ordered sequence`
                        : "Select artifacts of the same type to collect")
                    }
                    {...stylex.props(s.toolButton, s.primaryButton)}
                    onClick={collectSelectedArtifacts}
                  >
                    <Layers size={13} />
                    Collect
                  </button>
                ) : null}
                {!selectedWorkflowCount && selectedArtifactCards.length > 1 ? (
                  <button
                    type="button"
                    disabled={!localAuthoringEnabled}
                    {...stylex.props(s.toolButton)}
                    onClick={tidySelectedArtifacts}
                  >
                    Tidy-up
                  </button>
                ) : null}
                {selectedWorkflowCount ? (
                  <button
                    type="button"
                    disabled={runSelectedDisabled}
                    title={
                      !graphOperationsTrusted
                        ? "Run is unavailable until the displayed graph is current"
                        : selectedNodesAreRunnable
                          ? "Run only the selected nodes; latest accessible upstream outputs are pinned"
                          : "Unavailable or invalid selected nodes cannot run"
                    }
                    {...stylex.props(s.toolButton, s.primaryButton)}
                    onClick={() => void runWorkflow("selected")}
                  >
                    {runningScope === "selected" ? (
                      <LoaderCircle size={13} {...stylex.props(s.spinner)} />
                    ) : (
                      <Play size={13} />
                    )}
                    {runningScope === "selected" ? "Running…" : "Run"}
                  </button>
                ) : null}
                {selectedWorkflowCount ? (
                  <button
                    type="button"
                    disabled={runSelectedWithDependenciesDisabled}
                    title={
                      !graphOperationsTrusted
                        ? "Run is unavailable until the displayed graph is current"
                        : selectedWithDependenciesAreRunnable
                          ? `Run the selection and every upstream dependency (${selectedWithDependenciesCount} total)`
                          : "Unavailable or invalid upstream dependencies cannot run"
                    }
                    {...stylex.props(s.toolButton)}
                    onClick={() =>
                      void runWorkflow("selected-with-dependencies")
                    }
                  >
                    {runningScope === "selected-with-dependencies" ? (
                      <LoaderCircle size={13} {...stylex.props(s.spinner)} />
                    ) : (
                      <Workflow size={13} />
                    )}
                    {runningScope === "selected-with-dependencies"
                      ? "Running…"
                      : "With dependencies"}
                  </button>
                ) : null}
              </NodeToolbar>
            ) : null}
            {registry && activeContextualDiscovery ? (
              <ContextualNodeDiscovery
                key={`${activeContextualDiscovery.sourceNodeId}:${activeContextualDiscovery.sourceHandle}:${activeContextualDiscovery.flowPosition.x}:${activeContextualDiscovery.flowPosition.y}`}
                session={activeContextualDiscovery}
                registry={registry}
                canInsert={localAuthoringEnabled}
                insertDisabledReason={localAuthoringBlockedMessage}
                onClose={() => setContextualDiscovery(null)}
                onConfirm={confirmContextualDiscovery}
              />
            ) : null}
          </WorkflowCanvas>
        </NodeMenuRegistryContext.Provider>
      </section>

      {workbenchActivity ? (
        <WorkbenchActivityBar activity={workbenchActivity} />
      ) : null}

      <CanvasGridSettingsPanel
        selectedCount={selectedNodeCount}
        onSnapSelection={snapSelectionToGrid}
      />

      <aside aria-label="Canvas actions" {...stylex.props(s.toolDock)}>
        <button
          type="button"
          {...firefoxDynamicButtonProps}
          aria-label="Add node"
          disabled={!registry || !localAuthoringEnabled}
          title="Add node"
          {...stylex.props(s.railButton, s.railPrimary)}
          onClick={() => {
            closeGraphBrowser();
            setGridPanelOpen(false);
            setWorkspaceLibraryOpen(false);
            pickerInsertAtRef.current = null;
            setLibraryOpen((open) => !open);
          }}
        >
          <Plus size={14} />
          <span {...stylex.props(s.railLabel)}>Node</span>
        </button>
        <button
          type="button"
          aria-label="Module library"
          title="Open the Module library"
          {...stylex.props(s.railButton)}
          onClick={() => {
            closeGraphBrowser();
            setGridPanelOpen(false);
            setLibraryOpen(false);
            setWorkspaceLibraryFocusId(null);
            setWorkspaceLibraryOpen(true);
          }}
        >
          <Package size={14} />
          <span {...stylex.props(s.railLabel)}>Library</span>
        </button>
        <button
          type="button"
          aria-label="Module setup"
          title={
            running
              ? "Stop the current execution before opening Module setup"
              : !graphOperationsTrusted
                ? "Module setup is unavailable until the displayed graph is current"
                : "Set up and publish this graph as a Module"
          }
          disabled={running || !graphOperationsTrusted}
          {...stylex.props(s.railButton)}
          onClick={() => {
            closeGraphBrowser();
            setGridPanelOpen(false);
            setLibraryOpen(false);
            setWorkspaceLibraryOpen(false);
            setPublishModuleOpen(true);
          }}
        >
          <Upload size={14} />
          <span {...stylex.props(s.railLabel)}>Module</span>
        </button>
        <button
          type="button"
          aria-label="Add Artifact Viewer"
          title="Add a presentation-only Artifact Viewer"
          disabled={!localAuthoringEnabled}
          {...stylex.props(s.railButton)}
          onClick={() => addArtifactViewer()}
        >
          <Eye size={14} />
          <span {...stylex.props(s.railLabel)}>Viewer</span>
        </button>
        <div {...stylex.props(s.shapesMenuWrap)}>
          <button
            type="button"
            aria-label="Add shape or text"
            aria-expanded={shapesMenuOpen}
            aria-haspopup="menu"
            title="Add documentation shapes"
            disabled={!localAuthoringEnabled}
            {...stylex.props(
              s.railButton,
              shapesMenuOpen ? s.railPrimary : null,
            )}
            onClick={() => {
              closeGraphBrowser();
              setLibraryOpen(false);
              setGridPanelOpen(false);
              setShapesMenuOpen((open) => !open);
            }}
          >
            <Type size={14} />
            <span {...stylex.props(s.railLabel)}>Annotate</span>
          </button>
          {shapesMenuOpen ? (
            <div role="menu" {...stylex.props(s.shapesMenu)}>
              <button
                type="button"
                role="menuitem"
                {...stylex.props(s.railButton, s.railMenuButton)}
                onClick={() => addAnnotation("text")}
              >
                <Type size={14} />
                <span {...stylex.props(s.railLabel, s.railMenuLabel)}>
                  Text
                </span>
              </button>
              <button
                type="button"
                role="menuitem"
                {...stylex.props(s.railButton, s.railMenuButton)}
                onClick={() => addAnnotation("rectangle")}
              >
                <Square size={14} />
                <span {...stylex.props(s.railLabel, s.railMenuLabel)}>
                  Square
                </span>
              </button>
              <button
                type="button"
                role="menuitem"
                {...stylex.props(s.railButton, s.railMenuButton)}
                onClick={() => addAnnotation("ellipse")}
              >
                <Circle size={14} />
                <span {...stylex.props(s.railLabel, s.railMenuLabel)}>
                  Circle
                </span>
              </button>
            </div>
          ) : null}
        </div>
        <button
          type="button"
          {...firefoxDynamicButtonProps}
          disabled={!flow}
          title="Fit workflow"
          {...stylex.props(s.railButton)}
          onClick={() => void flow?.fitView(workbenchFitViewOptions)}
        >
          <Maximize2 size={14} />
          <span {...stylex.props(s.railLabel)}>Fit</span>
        </button>
        <button
          type="button"
          aria-label="Canvas lab"
          aria-pressed={gridPanelOpen}
          title="Experiment with canvas behavior"
          {...stylex.props(s.railButton, gridPanelOpen ? s.railPrimary : null)}
          onClick={() => {
            closeGraphBrowser();
            setLibraryOpen(false);
            setGridPanelOpen((open) => !open);
          }}
        >
          <Grid3x3 size={14} />
          <span {...stylex.props(s.railLabel)}>Canvas</span>
        </button>
        <span {...stylex.props(s.railDivider)} />
        <button
          type="button"
          disabled={!activeGraph}
          title={
            activeGraph
              ? "Browse previous executions"
              : "Save the graph to browse executions"
          }
          {...stylex.props(s.railButton)}
          onClick={(event) => {
            closeGraphBrowser();
            setLibraryOpen(false);
            setGridPanelOpen(false);
            executionHistoryReturnFocusRef.current = event.currentTarget;
            setExecutionHistoryTarget({ nodeId: null, executionId: null });
          }}
        >
          <History size={14} />
          <span {...stylex.props(s.railLabel)}>Runs</span>
        </button>
        <span {...stylex.props(s.railDivider)} />
        <button
          type="button"
          disabled={
            (!selectedWorkflowCount && !selectedViewerCount) ||
            !localAuthoringEnabled
          }
          title={
            selectedWorkflowCount || selectedViewerCount
              ? `Duplicate ${selectedWorkflowCount + selectedViewerCount} selected node${selectedWorkflowCount + selectedViewerCount === 1 ? "" : "s"}`
              : "Select one or more nodes to duplicate"
          }
          {...stylex.props(s.railButton)}
          onClick={duplicateSelectedNodes}
        >
          <Copy size={14} />
          <span {...stylex.props(s.railLabel)}>Duplicate</span>
        </button>
        <button
          type="button"
          disabled={!flow || !selectedNodeCount || !localAuthoringEnabled}
          title={
            selectedNodeCount
              ? `Delete ${selectedNodeCount} selected node${selectedNodeCount === 1 ? "" : "s"}`
              : "Select one or more nodes to delete"
          }
          {...stylex.props(s.railButton, s.railDanger)}
          onClick={deleteSelectedNodes}
        >
          <Trash2 size={14} />
          <span {...stylex.props(s.railLabel)}>Delete</span>
        </button>
      </aside>

      <Toast.Provider timeout={8000} limit={3}>
        <GlobalIssueToastList
          issues={globalIssues}
          onDismiss={dismissGlobalIssue}
        />
      </Toast.Provider>

      {executionHistoryTarget ? (
        <ExecutionHistoryDrawer
          key={`${activeGraph?.id ?? "unsaved"}:${executionHistoryTarget.nodeId ?? "all"}:${executionHistoryTarget.executionId ?? "latest"}`}
          workspaceId={workspaceId}
          graphId={activeGraph?.id ?? null}
          graphName={graphName}
          nodeId={executionHistoryTarget.nodeId}
          initialExecutionId={executionHistoryTarget.executionId}
          nodeTitles={nodeTitles}
          executionRunning={running}
          isDirty={isDirty}
          returnFocusRef={executionHistoryReturnFocusRef}
          onClose={() => setExecutionHistoryTarget(null)}
        />
      ) : null}

      <CanvasContextMenu
        request={canvasMenu}
        registry={registry ?? null}
        activeGraphId={activeGraph?.id ?? null}
        canEdit={localAuthoringEnabled}
        selection={canvasMenuSelection}
        nodeMenus={nodeMenus}
        actions={canvasMenuActions}
        onClose={() => setCanvasMenu(null)}
      />

      <WorkbenchSidePanel
        workspaceId={workspaceId}
        sidePanel={sidePanel}
        graphId={activeGraph?.id ?? null}
        nodeTitles={nodeTitles}
        registry={registry ?? null}
        canSave={canEditGraph}
        executionRunning={running}
        onOpenRun={(graphId, executionId) => {
          if (graphId !== activeGraph?.id) {
            openGraphInNewTab(graphId);
            return;
          }
          executionHistoryReturnFocusRef.current = null;
          setExecutionHistoryTarget({ nodeId: null, executionId });
        }}
      />

      {registry ? (
        <NodeSelector
          open={libraryOpen}
          registry={registry}
          activeGraphId={activeGraph?.id ?? null}
          canInsert={localAuthoringEnabled}
          insertDisabledReason={localAuthoringBlockedMessage}
          onOpenChange={(open) => {
            if (!open) pickerInsertAtRef.current = null;
            setLibraryOpen(open);
          }}
          onAddNode={(spec) => addCatalogNode(spec)}
          onOpenGraph={openGraphInNewTab}
          onOpenWorkspaceLibrary={() => {
            setLibraryOpen(false);
            setWorkspaceLibraryFocusId(null);
            setWorkspaceLibraryOpen(true);
          }}
        />
      ) : null}

      <WorkspaceLibraryDialog
        workspace={workspace}
        open={workspaceLibraryOpen}
        onOpenChange={setWorkspaceLibraryOpen}
        showTrigger={false}
        focusedModuleId={workspaceLibraryFocusId}
        onOpenSourceGraph={openGraphInNewTab}
        onLibraryChanged={() => refreshNodeRegistry()}
      />

      <PublishModuleDialog
        key={`${activeGraph?.id ?? "unsaved"}:${graphName}`}
        open={publishModuleOpen}
        onOpenChange={setPublishModuleOpen}
        workspaceId={workspaceId}
        sourceGraphId={activeGraph?.id ?? null}
        graphName={graphName}
        revision={activeGraph?.revision ?? null}
        isDirty={isDirty}
        canPublish={canPublishModule}
        canEdit={canEditModuleSource}
        boundaries={moduleBoundarySummaries}
        canAddInputBoundary={Boolean(
          registry?.nodes.some((spec) => spec.operator_id === "module.input"),
        )}
        canAddOutputBoundary={Boolean(
          registry?.nodes.some((spec) => spec.operator_id === "module.output"),
        )}
        onAddBoundary={(direction) => {
          const operatorId =
            direction === "input" ? "module.input" : "module.output";
          const spec = registry?.nodes.find(
            (candidate) => candidate.operator_id === operatorId,
          );
          if (spec) addCatalogNode(spec);
        }}
        onSelectBoundary={(nodeId) => {
          setSelectedNodeIdSet(new Set([nodeId]));
          setSelectedEdgeIdSet(new Set());
          void flow?.fitView({
            nodes: [{ id: nodeId }],
            padding: 0.45,
            duration: 220,
          });
        }}
        onViewModule={(moduleId) => {
          setPublishModuleOpen(false);
          setWorkspaceLibraryFocusId(moduleId);
          setWorkspaceLibraryOpen(true);
        }}
        onOpenSourceGraph={openGraphInNewTab}
        onPublished={() => refreshNodeRegistry()}
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
