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
  Bookmark,
  Circle,
  Copy,
  Eye,
  Grid3x3,
  History,
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
import { LibraryDrawer } from "./LibraryDrawer";
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
  ContextualNodeDiscovery,
  type ContextualDiscoverySession,
} from "./ContextualNodeDiscovery";
import type {
  ContextualCandidate,
  ContextualRouteChoice,
} from "../model/node-catalog";
import {
  PublishModuleDialog,
  type ModuleBoundarySummary,
} from "./PublishModuleDialog";
import { createUuid } from "@/features/workbench/model/uuid";
import { WorkspaceLibraryDialog } from "@/features/workspaces/WorkspaceLibraryDialog";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { usePublishWorkbenchChrome } from "./WorkbenchChromeContext";
import { renameSavedGraphRemote } from "@/features/workspaces/graph-actions";
import type { SavedGraphSummary } from "@/lib/api";
import {
  CanvasGridSettingsProvider,
  useCanvasGridSettings,
} from "../canvas/canvas-grid-settings";
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
import { useNodeFileUploads } from "./useNodeFileUploads";
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
  type AnnotationColor,
  type AnnotationKind,
  type AnnotationLayout,
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
  type ArtifactViewerEdgeUpdate,
  type ArtifactViewerInteractionEdge,
  type ArtifactViewerNode,
  type CanvasEdge,
  type CanvasNode,
  type GraphPresentation,
} from "../canvas/artifact-viewer";
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
import { appendInputPlug } from "../canvas/input-plugs";
import {
  nodeSecretBindingReady,
  nodeSecretInputs,
} from "../canvas/node-secrets";
import { artifactTypeColor } from "../canvas/nodes.css";
import type { ArtifactQueryRelation } from "../canvas/query-artifact-tables";
import type { SchemaBuilderField } from "../canvas/schema-builder";
import {
  isFileUploadOperator,
  WORKFLOW_EDGE_TYPE,
  WORKFLOW_NODE_TYPE,
  createWorkflowNodeData,
  effectivePortShape,
  imageUploads,
  removeImageUpload,
  resolvedPortArtifactType,
  type WorkflowEdge,
  type WorkflowEdgeRouteOffset,
  type WorkflowEdgeRouteOption,
  type WorkflowEdgeUpdate,
  type WorkflowArtifactTypeBindings,
  type WorkflowNodeData,
  type WorkflowInputPlug,
  portMetaForPort,
  workflowNodeIsSupported,
} from "../canvas/types";
import {
  orderFeedRoutes,
  preferredWholeFeedRoute,
  routesForHandleFeed,
} from "../model/connection-feeds";
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
import { useMediaQuery } from "@/hooks/use-media-query";
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

const MOBILE_WORKBENCH_QUERY = "(max-width: 720px)";

interface SafeAreaInsets {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

const ZERO_SAFE_AREA_INSETS: SafeAreaInsets = {
  top: 0,
  right: 0,
  bottom: 0,
  left: 0,
};

const WORKBENCH_DESKTOP_FIT_VIEW_OPTIONS = {
  padding: {
    top: "90px",
    right: "48px",
    bottom: "64px",
    left: "165px",
  },
  maxZoom: 0.88,
} as const;

const WORKBENCH_MOBILE_FIT_PADDING = {
  top: 76,
  right: 20,
  bottom: 96,
  left: 20,
} as const;

function readSafeAreaInsets(): SafeAreaInsets {
  const probe = document.createElement("div");
  probe.style.cssText = [
    "position: fixed",
    "visibility: hidden",
    "pointer-events: none",
    "padding-top: env(safe-area-inset-top, 0px)",
    "padding-right: env(safe-area-inset-right, 0px)",
    "padding-bottom: env(safe-area-inset-bottom, 0px)",
    "padding-left: env(safe-area-inset-left, 0px)",
  ].join(";");
  document.body.append(probe);
  const style = window.getComputedStyle(probe);
  const insets = {
    top: Number.parseFloat(style.paddingTop) || 0,
    right: Number.parseFloat(style.paddingRight) || 0,
    bottom: Number.parseFloat(style.paddingBottom) || 0,
    left: Number.parseFloat(style.paddingLeft) || 0,
  };
  probe.remove();
  return insets;
}

function useSafeAreaInsets(enabled: boolean): SafeAreaInsets {
  const [insets, setInsets] = React.useState(ZERO_SAFE_AREA_INSETS);
  React.useLayoutEffect(() => {
    if (!enabled) return;
    const updateInsets = () => {
      const next = readSafeAreaInsets();
      setInsets((current) =>
        current.top === next.top &&
        current.right === next.right &&
        current.bottom === next.bottom &&
        current.left === next.left
          ? current
          : next,
      );
    };
    updateInsets();
    window.addEventListener("resize", updateInsets);
    window.visualViewport?.addEventListener("resize", updateInsets);
    return () => {
      window.removeEventListener("resize", updateInsets);
      window.visualViewport?.removeEventListener("resize", updateInsets);
    };
  }, [enabled]);
  return insets;
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
  const mobileWorkbench = useMediaQuery(MOBILE_WORKBENCH_QUERY);
  const safeAreaInsets = useSafeAreaInsets(mobileWorkbench);
  const workbenchFitViewOptions = React.useMemo(() => {
    if (!mobileWorkbench) return WORKBENCH_DESKTOP_FIT_VIEW_OPTIONS;
    return {
      padding: {
        top: `${WORKBENCH_MOBILE_FIT_PADDING.top + safeAreaInsets.top}px`,
        right: `${WORKBENCH_MOBILE_FIT_PADDING.right + safeAreaInsets.right}px`,
        bottom: `${WORKBENCH_MOBILE_FIT_PADDING.bottom + safeAreaInsets.bottom}px`,
        left: `${WORKBENCH_MOBILE_FIT_PADDING.left + safeAreaInsets.left}px`,
      },
      maxZoom: 0.88,
    } as const;
  }, [mobileWorkbench, safeAreaInsets]);
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
  const [libraryDrawerOpen, setLibraryDrawerOpen] = React.useState(false);
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
  const moduleBoundarySummaries = React.useMemo<
    readonly ModuleBoundarySummary[]
  >(
    () =>
      nodes.flatMap((node) => {
        const operatorId = node.data.spec.operator_id;
        if (operatorId !== "module.input" && operatorId !== "module.output") {
          return [];
        }
        const direction = operatorId === "module.input" ? "input" : "output";
        const portName = node.data.config.public_name;
        const description = node.data.config.description;
        const artifactType = node.data.artifactTypeBindings.T;
        const connectionCount = edges.filter(
          (edge) =>
            edge.data?.enabled !== false &&
            (direction === "input"
              ? edge.source === node.id
              : edge.target === node.id),
        ).length;
        return [
          {
            id: node.id,
            direction,
            portName: typeof portName === "string" ? portName : null,
            description: typeof description === "string" ? description : null,
            artifactType: artifactType
              ? `${artifactType.id}@${artifactType.schema_version}`
              : null,
            connectionCount,
          },
        ];
      }),
    [edges, nodes],
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
      if (shouldBlockAuthoringCommand(localAuthoringEnabledRef.current, options)) {
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

  const commitArtifactViewers = React.useCallback(
    (
      updater: (
        current: ArtifactViewerCanvasState,
      ) => ArtifactViewerCanvasState,
    ) => {
      if (!localAuthoringEnabledRef.current) {
        setRunError(localAuthoringBlockedMessageRef.current);
        return;
      }
      setArtifactViewers((current) => {
        const next = {
          ...updater(current),
          graphId: artifactViewerGraphIdRef.current,
        };
        queueMicrotask(() => {
          presentationRoomSyncRef.current.submitReplace(next);
        });
        return next;
      });
    },
    [],
  );

  const updateArtifactViewerLayout = React.useCallback(
    (nodeId: string, layout: ArtifactViewerNode["data"]["layout"]) => {
      commitArtifactViewers((current) => ({
        ...current,
        nodes: current.nodes.map((node) =>
          node.id === nodeId
            ? { ...node, data: { ...node.data, layout } }
            : node,
        ),
      }));
    },
    [commitArtifactViewers],
  );

  const updateArtifactViewerEdge = React.useCallback(
    (edgeId: string, update: ArtifactViewerEdgeUpdate) => {
      commitArtifactViewers((current) => ({
        ...current,
        edges: current.edges.map((edge) => {
          if (edge.id !== edgeId) return edge;
          const nextProjection =
            update.projection === undefined
              ? edge.data?.projection
              : (update.projection ?? undefined);
          return {
            ...edge,
            data: {
              ...edge.data,
              sourcePortName: edge.data?.sourcePortName ?? "",
              projection: nextProjection,
            },
          };
        }),
      }));
    },
    [commitArtifactViewers],
  );

  const updateArtifactViewerEdgeRoute = React.useCallback(
    (edgeId: string, routeOffset: WorkflowEdgeRouteOffset) => {
      commitArtifactViewers((current) => ({
        ...current,
        edges: current.edges.map((edge) =>
          edge.id === edgeId
            ? {
                ...edge,
                data: {
                  ...edge.data,
                  sourcePortName: edge.data?.sourcePortName ?? "",
                  routeOffset,
                },
              }
            : edge,
        ),
      }));
    },
    [commitArtifactViewers],
  );

  const updateArtifactViewerMode = React.useCallback(
    (nodeId: string, mode: string) => {
      commitArtifactViewers((current) => ({
        ...current,
        nodes: current.nodes.map((node) =>
          node.id === nodeId ? { ...node, data: { ...node.data, mode } } : node,
        ),
      }));
    },
    [commitArtifactViewers],
  );

  const updateArtifactViewerSelection = React.useCallback(
    (nodeId: string, selection: ArtifactKeySelection) => {
      setArtifactViewerSelections((current) => ({
        ...current,
        [nodeId]: selection,
      }));
    },
    [],
  );

  const updateArtifactViewerFields = React.useCallback(
    (nodeId: string, fields: ArtifactInteractionField[]) => {
      setArtifactViewerFields((current) => {
        if (JSON.stringify(current[nodeId] ?? []) === JSON.stringify(fields)) {
          return current;
        }
        return { ...current, [nodeId]: fields };
      });
    },
    [],
  );

  const updateArtifactViewerActivity = React.useCallback(
    (nodeId: string, activity: ArtifactViewerActivity | null) => {
      if (!activity) {
        setArtifactViewerActivities((current) => {
          if (!current[nodeId]) return current;
          const next = { ...current };
          delete next[nodeId];
          return next;
        });
        return;
      }
      const revision = artifactViewerActivityRevisionRef.current + 1;
      artifactViewerActivityRevisionRef.current = revision;
      setArtifactViewerActivities((current) => {
        return {
          ...current,
          [nodeId]: {
            activity,
            revision,
          },
        };
      });
    },
    [],
  );

  const updateArtifactViewerBinding = React.useCallback(
    (bindingId: string, binding: ArtifactViewerBinding) => {
      commitArtifactViewers((current) => ({
        ...current,
        bindings: current.bindings.map((candidate) =>
          candidate.id === bindingId ? binding : candidate,
        ),
      }));
    },
    [commitArtifactViewers],
  );

  const removeArtifactViewer = React.useCallback(
    (nodeId: string) => {
      commitArtifactViewers((current) => ({
        ...current,
        nodes: current.nodes.filter((node) => node.id !== nodeId),
        edges: current.edges.filter(
          (edge) => edge.source !== nodeId && edge.target !== nodeId,
        ),
        bindings: current.bindings.filter(
          (binding) =>
            binding.sourceViewerId !== nodeId &&
            binding.targetViewerId !== nodeId,
        ),
      }));
      setArtifactViewerSelections((current) => {
        const next = { ...current };
        delete next[nodeId];
        return next;
      });
      setArtifactViewerFields((current) => {
        const next = { ...current };
        delete next[nodeId];
        return next;
      });
      setArtifactViewerActivities((current) => {
        if (!current[nodeId]) return current;
        const next = { ...current };
        delete next[nodeId];
        return next;
      });
    },
    [commitArtifactViewers],
  );

  const updateAnnotationLayout = React.useCallback(
    (nodeId: string, layout: AnnotationLayout) => {
      commitArtifactViewers((current) => ({
        ...current,
        annotations: current.annotations.map((node) =>
          node.id === nodeId
            ? { ...node, data: { ...node.data, layout } }
            : node,
        ),
      }));
    },
    [commitArtifactViewers],
  );

  const updateAnnotationText = React.useCallback(
    (nodeId: string, text: string) => {
      commitArtifactViewers((current) => ({
        ...current,
        annotations: current.annotations.map((node) =>
          node.id === nodeId ? { ...node, data: { ...node.data, text } } : node,
        ),
      }));
    },
    [commitArtifactViewers],
  );

  const updateAnnotationColor = React.useCallback(
    (nodeId: string, color: AnnotationColor) => {
      commitArtifactViewers((current) => ({
        ...current,
        annotations: current.annotations.map((node) =>
          node.id === nodeId
            ? { ...node, data: { ...node.data, color } }
            : node,
        ),
      }));
    },
    [commitArtifactViewers],
  );

  const removeAnnotation = React.useCallback(
    (nodeId: string) => {
      commitArtifactViewers((current) => ({
        ...current,
        annotations: current.annotations.filter((node) => node.id !== nodeId),
      }));
    },
    [commitArtifactViewers],
  );

  const removeNode = React.useCallback(
    (nodeId: string) => {
      applyAuthoringCommands([{ kind: "remove_nodes", node_ids: [nodeId] }]);
      commitArtifactViewers((current) => ({
        ...current,
        edges: current.edges.filter((edge) => edge.source !== nodeId),
      }));
      forgetNodeSecretStatuses(nodeId);
      setPendingConnectionRoute(null);
      setRunError(null);
    },
    [applyAuthoringCommands, commitArtifactViewers, forgetNodeSecretStatuses],
  );

  const handleRemoveImageUpload = React.useCallback(
    (nodeId: string, index: number) => {
      const node = nodes.find((candidate) => candidate.id === nodeId);
      if (!node) return;
      applyAuthoringCommands([
        {
          kind: "update_node_configuration",
          node_id: nodeId,
          field: "uploads",
          value: imageUploads(removeImageUpload(node.data, index)),
        },
      ]);
    },
    [applyAuthoringCommands, nodes],
  );

  const addNodeInputPlug = React.useCallback(
    (nodeId: string, portName: string) => {
      const node = nodes.find((candidate) => candidate.id === nodeId);
      if (!node) return;
      const inputPlugs = appendInputPlug(node.data.inputPlugs, portName);
      const plug = inputPlugs[inputPlugs.length - 1];
      if (!plug) return;
      applyAuthoringCommands([
        {
          kind: "add_input_plug",
          node_id: nodeId,
          plug: { id: plug.id, port: plug.portName },
        },
      ]);
    },
    [applyAuthoringCommands, nodes],
  );

  const removeNodeInputPlug = React.useCallback(
    (nodeId: string, plugId: string) => {
      applyAuthoringCommands([
        {
          kind: "remove_input_plug",
          node_id: nodeId,
          plug_id: plugId,
        },
      ]);
      setPendingConnectionRoute(null);
      setRunError(null);
    },
    [applyAuthoringCommands],
  );

  const reorderNodeInputPlug = React.useCallback(
    (nodeId: string, portName: string, plugId: string, toIndex: number) => {
      applyAuthoringCommands([
        {
          kind: "reorder_input_plug",
          node_id: nodeId,
          port: portName,
          plug_id: plugId,
          to_index: toIndex,
        },
      ]);
    },
    [applyAuthoringCommands],
  );

  const updateSchemaBuilderFields = React.useCallback(
    (
      nodeId: string,
      fields: readonly SchemaBuilderField[],
      inputPlugs: readonly WorkflowInputPlug[],
    ) => {
      const node = nodes.find((candidate) => candidate.id === nodeId);
      if (!node) return;
      applyAuthoringCommands([
        {
          kind: "update_node_configuration_and_input_plugs",
          node_id: nodeId,
          config: { ...node.data.config, fields },
          input_plugs: inputPlugs.map((plug) => ({
            id: plug.id,
            port: plug.portName,
          })),
        },
      ]);
      setPendingConnectionRoute(null);
      setRunError(null);
    },
    [applyAuthoringCommands, nodes],
  );

  const updateArtifactQueryRelations = React.useCallback(
    (
      nodeId: string,
      relations: readonly ArtifactQueryRelation[],
      inputPlugs: readonly WorkflowInputPlug[],
    ) => {
      const node = nodes.find((candidate) => candidate.id === nodeId);
      if (!node) return;
      applyAuthoringCommands([
        {
          kind: "update_node_configuration_and_input_plugs",
          node_id: nodeId,
          config: { ...node.data.config, relations },
          input_plugs: inputPlugs.map((plug) => ({
            id: plug.id,
            port: plug.portName,
          })),
        },
      ]);
      setPendingConnectionRoute(null);
      setRunError(null);
    },
    [applyAuthoringCommands, nodes],
  );

  const { uploading, handleImagesSelected } = useNodeFileUploads({
    workspaceId,
    nodes,
    edges,
    setNodes,
    setRunError,
    applyAuthoringCommands,
  });

  const resetNodeArtifactTypeBinding = React.useCallback(
    (nodeId: string, variable: string) => {
      const hasIncidentEdges = edges.some(
        (edge) => edge.source === nodeId || edge.target === nodeId,
      );
      if (hasIncidentEdges) return;

      applyAuthoringCommands([
        {
          kind: "reset_artifact_type_binding",
          node_id: nodeId,
          variable,
        },
      ]);
      setPendingConnectionRoute(null);
      setRunError(null);
    },
    [applyAuthoringCommands, edges],
  );

  const openGraphInNewTab = React.useCallback(
    (graphId: string) => {
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
          onImagesSelected: undefined,
          onRemoveImageUpload: undefined,
          onAddInputPlug: undefined,
          onRemoveInputPlug: undefined,
          onReorderInputPlug: undefined,
          onSchemaBuilderFieldsChange: undefined,
          onArtifactQueryRelationsChange: undefined,
          onResetArtifactTypeBinding: undefined,
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
        onImagesSelected: isFileUploadOperator(data.spec.operator_id)
          ? handleImagesSelected
          : undefined,
        onRemoveImageUpload: handleRemoveImageUpload,
        onAddInputPlug: addNodeInputPlug,
        onRemoveInputPlug: removeNodeInputPlug,
        onReorderInputPlug: reorderNodeInputPlug,
        onSchemaBuilderFieldsChange: updateSchemaBuilderFields,
        onArtifactQueryRelationsChange: updateArtifactQueryRelations,
        onResetArtifactTypeBinding: resetNodeArtifactTypeBinding,
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
      handleImagesSelected,
      handleNodeHandlesMeasured,
      openGraphInNewTab,
      openNodeExecutionHistory,
      registry,
      removeNode,
      removeNodeInputPlug,
      handleRemoveImageUpload,
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
    refreshNodeRegistry: requestNodeRegistryRefresh,
    roomPersistence,
  });
  const router = useRouter();
  const activeGraphIdRef = React.useRef(activeGraph?.id ?? null);
  React.useEffect(() => {
    activeGraphIdRef.current = activeGraph?.id ?? null;
  }, [activeGraph?.id]);
  const syncFromCollaborativeHeadRef = React.useRef(syncFromCollaborativeHead);
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
          syncFromCollaborativeHeadRef.current(head);
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
  }, [workspaceId]);

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
      syncFromCollaborativeHeadRef.current(ready.head);
    },
    onRehydrate: (head) => {
      syncFromCollaborativeHeadRef.current(head);
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
        if (!canSubmitRoomCommands) return;
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
        if (!canSubmitRoomCommands) return;
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
      ? canEditGraph &&
        graphOperationsTrusted &&
        graphRoom.canSubmitCommands
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
    (node) => !node.selected || workflowNodeIsSupported(node.data),
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
      workflowNodeIsSupported(node.data),
  );
  const selectedWorkflowCount = nodes.filter((node) => node.selected).length;
  const selectedViewerCount = artifactViewers.nodes.filter(
    (node) => node.selected,
  ).length;
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
  const activeArtifactViewers =
    artifactViewers.graphId === (activeGraph?.id ?? null)
      ? artifactViewers
      : {
          graphId: activeGraph?.id ?? null,
          nodes: [],
          edges: [],
          bindings: [],
          annotations: [],
        };

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
      nodes,
      schedulePresenceSnapshot,
      setNodes,
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
            change.item.type !== ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE
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

  const isValidConnection = React.useCallback<IsValidConnection<CanvasEdge>>(
    (connection) => {
      const candidate: Connection = {
        source: connection.source,
        sourceHandle: connection.sourceHandle ?? null,
        target: connection.target,
        targetHandle: connection.targetHandle ?? null,
      };
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
      activeArtifactViewers.bindings,
      edges,
      nodes,
      registry?.artifact_conversions,
      registry?.artifact_types,
    ],
  );

  const onConnect: OnConnect = React.useCallback(
    (connection) => {
      if (!isValidConnection(connection)) return;
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
            ? `${sourceArtifactType.id}@${sourceArtifactType.schema_version}`
            : `Any artifact · ${source.artifactTypeVariable}`,
        },
        target: {
          nodeTitle: targetNode.data.spec.title,
          portName: targetPort?.title ?? target.portName,
          artifactType: targetArtifactType
            ? `${targetArtifactType.id}@${targetArtifactType.schema_version}`
            : `Any artifact · ${target.artifactTypeVariable}`,
        },
      });
    },
    [
      addWorkflowEdge,
      commitArtifactViewers,
      edges,
      isValidConnection,
      nodes,
      registry?.artifact_conversions,
      registry?.artifact_types,
    ],
  );

  const addCatalogNode = React.useCallback(
    (spec: NodeSpec) => {
      const id = `node-${createUuid()}`;
      const center = flow?.screenToFlowPosition({
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
      }) ?? { x: 600, y: 280 };
      const data = attachNodeCallbacks(createWorkflowNodeData(spec));
      applyAuthoringCommands([
        addNodeCommand(
          id,
          data,
          { x: center.x - 140, y: center.y - 110 },
        ),
      ]);
      setSelectedNodeIdSet(new Set([id]));
      setSelectedEdgeIdSet(new Set());
      setLibraryOpen(false);
      setContextualDiscovery(null);
    },
    [applyAuthoringCommands, attachNodeCallbacks, flow],
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

      // Dragging from an output port offers downstream nodes; dragging from an
      // input port offers upstream nodes whose outputs can feed it.
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
    [activeGraph?.id, canEditGraph, flow, nodes, registry, running],
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
      const nodeCommand = addNodeCommand(
        id,
        data,
        {
          x: contextualDiscovery.flowPosition.x,
          y:
            contextualDiscovery.flowPosition.y -
            DEFAULT_NODE_PLACEMENT_HEIGHT / 2,
        },
      );

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

      applyAuthoringCommands([
        nodeCommand,
        edgeCommand,
      ]);
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

  const addArtifactViewer = React.useCallback(() => {
    const id = `artifact-viewer-${createUuid()}`;
    const center = flow?.screenToFlowPosition({
      x: window.innerWidth / 2,
      y: window.innerHeight / 2,
    }) ?? { x: 600, y: 280 };
    const selectedSource = nodes.find((node) => node.selected);
    const position = selectedSource
      ? {
          x: selectedSource.position.x + 380,
          y: selectedSource.position.y - 20,
        }
      : { x: center.x - 260, y: center.y - 180 };
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
  }, [closeGraphBrowser, commitArtifactViewers, flow, nodes, setNodes]);

  const addAnnotation = React.useCallback(
    (kind: AnnotationKind) => {
      const center = flow?.screenToFlowPosition({
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
      }) ?? { x: 480, y: 240 };
      const annotation = createAnnotationNode(kind, {
        x: center.x - 80,
        y: center.y - 60,
      });
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
    [closeGraphBrowser, commitArtifactViewers, flow, setNodes],
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
          },
        };
      }),
    [
      activeGraph,
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
            onSelectionChange: updateArtifactViewerSelection,
            onFieldsChange: updateArtifactViewerFields,
            onActivityChange: updateArtifactViewerActivity,
            onRemoveNode: removeArtifactViewer,
          },
        };
      }),
    [
      activeArtifactViewers.bindings,
      activeArtifactViewers.nodes,
      artifactViewerFields,
      artifactViewerSelections,
      removeArtifactViewer,
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
            // React Flow stores these callbacks and invokes them from edge UI events.
            // eslint-disable-next-line react-hooks/refs
            onUpdate: updateArtifactViewerEdge,
            // eslint-disable-next-line react-hooks/refs
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
    ],
    [
      artifactViewerCanvasEdges,
      artifactViewerInteractionCanvasEdges,
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
            appendixHeight: current?.appendixHeight ?? DEFAULT_APPENDIX_HEIGHT,
          };
          const snapped = snapNodeLayout(
            seed,
            ["width", "appendixHeight"],
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

  const chromeValue = React.useMemo(
    () => ({
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
    }),
    [
      activeGraph,
      canDeleteGraph,
      canEditGraph,
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
      workspaceId,
    ],
  );
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
        {...stylex.props(s.canvas)}
        aria-label="Workflow canvas"
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
          {selectedNodeIds.length ? (
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
                onClick={() => void runWorkflow("selected-with-dependencies")}
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
          onClick={addArtifactViewer}
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
        <button
          type="button"
          aria-label="Saved artifacts"
          title="Saved artifacts and where they came from"
          {...stylex.props(s.railButton, libraryDrawerOpen ? s.railPrimary : null)}
          onClick={() => {
            closeGraphBrowser();
            setLibraryOpen(false);
            setGridPanelOpen(false);
            setLibraryDrawerOpen((open) => !open);
          }}
        >
          <Bookmark size={14} />
          <span {...stylex.props(s.railLabel)}>Saved</span>
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

      {libraryDrawerOpen ? (
        <LibraryDrawer
          workspaceId={workspaceId}
          onClose={() => setLibraryDrawerOpen(false)}
          onOpenRun={(graphId, executionId) => {
            setLibraryDrawerOpen(false);
            if (graphId !== activeGraph?.id) {
              openGraphInNewTab(graphId);
              return;
            }
            executionHistoryReturnFocusRef.current = null;
            setExecutionHistoryTarget({ nodeId: null, executionId });
          }}
        />
      ) : null}

      {registry ? (
        <NodeSelector
          open={libraryOpen}
          registry={registry}
          activeGraphId={activeGraph?.id ?? null}
          canInsert={localAuthoringEnabled}
          insertDisabledReason={localAuthoringBlockedMessage}
          onOpenChange={setLibraryOpen}
          onAddNode={addCatalogNode}
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
