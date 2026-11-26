import {
  artifactInlineContentUrl,
  type ActiveRunSummary,
  type ArtifactRef,
  type NodeRegistry,
  type PlacedLibraryItem,
} from "@/lib/api";
import { imagePath, imageThumbnailUrl } from "@/lib/api/images";
import {
  artifactTypeFor,
  cardArtifactRefs,
  declaredArtifactContentType,
  isImageArtifact,
} from "../artifacts/artifact-card";
import { artifactTypeKey } from "../artifacts/artifact-type-key";
import { formatArtifactTypeLabel } from "../artifacts/artifact-type-label";
import {
  ARTIFACT_CARD_OUTPUT_HANDLE,
  artifactCardConnectionValue,
  type ArtifactCardConnection,
} from "../artifacts/artifact-connections";
import type { ArtifactOriginEdge } from "../artifacts/artifact-origin-edge";
import {
  ARTIFACT_VIEWER_INPUT_HANDLE,
  type ArtifactViewerCanvasState,
  type ArtifactViewerEdge,
  type ArtifactViewerNode,
  type GraphPresentation,
} from "../artifacts/artifact-viewer";
import {
  readTiffWindow,
  type TiffWindow,
  type TiffWindowSelection,
} from "../artifacts/TiffWindowSelector";
import {
  effectivePortShape,
  isServiceProviderNode,
  portArtifactType,
  portMetaForPort,
  resolvedPortArtifactType,
  workflowNodeIsSupported,
  type GraphConnection,
  type WorkflowEdge,
  type WorkflowNode,
  type WorkflowNodeConfig,
} from "../authoring/types";
import {
  formatLibraryByteSize,
  libraryFileDisplayName,
} from "../artifacts/side-panel/library-tree";
import type {
  CellCardMove,
  CellConnectionEnds,
} from "../cell-canvas/CellCanvas";
import type {
  ArtifactCardSurfaceData,
  CellExecutionAppendixOutput,
  CellExecutionAppendixSpec,
  CellNodeLiveProgress,
  CellRemotePeerState,
  CellSelectionSnapshot,
} from "../cell-canvas/cell-contracts";
import { artifactTypeColor } from "../config-ui/nodes.css";
import { appendixExpandedHeightCells } from "../cell-canvas/cell-operator-adapter";
import {
  cellGraphFromAuthoredDocument,
  cellOriginFromWorld,
  graphCommandsFromCellDeleteForDocument,
  graphCommandsFromCellMovesForDocument,
  type CellNodeRunState,
  type CellNodeSecretState,
  type CellOriginLink,
  type CellPipeMetadata,
  type CellViewerImages,
  type CellViewerMetadata,
} from "../cell-canvas/cell-document-adapter";
import {
  DEFAULT_CELL_CLEANUP_PARAMS,
  buildCleanupUndoPlan,
  mergeCleanupUndoSnapshots,
  planCellGraphCleanup,
  type CellCleanupCardSizePreset,
  type CellCleanupParams,
  type CellCleanupPlan,
  type CellCleanupUndoSnapshot,
} from "../cell-canvas/cell-graph-cleanup";
import { CELL_SIZE, cellToWorldOrigin } from "../cell-canvas/cell-model";
import type { AuthoredGraphDocument } from "../authoring/graph-document";
import type { ResolvedGraphSemantics } from "../authoring/graph-semantics";
import { changeOriginCardReferences } from "../artifacts/origin-card-commands";
import {
  instanceKeyText,
  type PresenceParticipant,
  type RoomInstanceState,
} from "../collaboration/protocol";
import { actorColor } from "../collaboration/remote-selection";
import type { CanvasSelection } from "../authoring/workbench-canvas-selection";

function cellNodeStatus(
  node: WorkflowNode,
  instance: RoomInstanceState | undefined,
): Pick<CellNodeRunState, "status" | "statusLabel"> {
  const isProvider = isServiceProviderNode(node.data.spec);
  switch (instance?.state ?? node.data.execution.status) {
    case "running":
    case "cancelling":
      return { status: "working", statusLabel: "Running" };
    case "queued":
      return { status: "working", statusLabel: "Queued" };
    case "failed":
      return { status: "error", statusLabel: "Error" };
    case "succeeded":
    case "fresh":
      return isProvider
        ? { status: "idle" }
        : { status: "done", statusLabel: "Fresh" };
    case "stale":
      return isProvider
        ? { status: "idle" }
        : { status: "idle", statusLabel: "Stale" };
    default:
      if (!instance && node.data.execution.status === "idle" && !isProvider) {
        if (node.data.run?.status === "succeeded")
          return { status: "done", statusLabel: "Fresh" };
        if (node.data.run?.status === "failed")
          return { status: "error", statusLabel: "Error" };
      }
      return { status: "idle" };
  }
}

interface CellLiveProgressEntry {
  readonly sequence: number;
  readonly message: string;
  readonly current: number | null;
  readonly total: number | null;
  readonly fingerprint: string;
}

/** Progress and cancel for the nodes on the open graph and call trail. */
export interface CellLiveRunInput {
  readonly projectId: string;
  readonly graphId: string;
  readonly callPath: readonly string[];
  readonly progress?: {
    get(
      key: string,
    ): { readonly entries: readonly CellLiveProgressEntry[] } | undefined;
  };
  readonly runs: readonly ActiveRunSummary[];
  readonly cancellingRunIds: ReadonlySet<string>;
  readonly canCancelRun: boolean;
  readonly onCancelNodeRun: (nodeId: string) => void;
}

function sameCallPath(
  left: readonly string[],
  right: readonly string[],
): boolean {
  return (
    left.length === right.length &&
    left.every((segment, index) => segment === right[index])
  );
}

function newestRun(runs: readonly ActiveRunSummary[]): ActiveRunSummary | null {
  let match: ActiveRunSummary | null = null;
  for (const run of runs) {
    if (!match || run.started_at > match.started_at) match = run;
  }
  return match;
}

/**
 * The run a node may cancel. A node named as a target uses the newest such
 * run. A running node that is only upstream uses the run when it is the only
 * one on this call trail, which is the demand that put it to work.
 */
export function activeRunForNode(
  runs: readonly ActiveRunSummary[],
  nodeId: string,
  callPath: readonly string[],
): ActiveRunSummary | null {
  const targeted: ActiveRunSummary[] = [];
  const onView: ActiveRunSummary[] = [];
  for (const run of runs) {
    if (
      run.targets.some(
        (target) =>
          target.node_id === nodeId && sameCallPath(target.call_path, callPath),
      )
    ) {
      targeted.push(run);
    }
    if (
      run.targets.length === 0 ||
      run.targets.every((target) => sameCallPath(target.call_path, callPath))
    ) {
      onView.push(run);
    }
  }
  const sole = onView.length === 1 ? onView[0] : undefined;
  return newestRun(targeted) ?? sole ?? null;
}

function liveProgressFor(
  liveRun: CellLiveRunInput,
  nodeId: string,
  fingerprint: string,
): CellNodeLiveProgress | null {
  const history = liveRun.progress?.get(
    instanceKeyText({
      project_id: liveRun.projectId,
      graph_id: liveRun.graphId,
      call_path: liveRun.callPath,
      node_id: nodeId,
      map_index: null,
    }),
  );
  const latest = history?.entries[0];
  if (!latest || latest.fingerprint !== fingerprint) return null;
  return {
    latestMessage: latest.message,
    current: latest.current,
    total: latest.total,
    recentMessages: history.entries.map((entry) => ({
      sequence: entry.sequence,
      message: entry.message,
      current: entry.current,
      total: entry.total,
    })),
  };
}

function applyLiveRun(
  scene: ReturnType<typeof cellGraphFromAuthoredDocument>,
  nodeInstanceStates: Readonly<Record<string, RoomInstanceState>>,
  liveRun: CellLiveRunInput,
): ReturnType<typeof cellGraphFromAuthoredDocument> {
  let surfaceById = scene.surfaceById;
  let changed = false;
  for (const card of scene.graph.cards) {
    if (card.status !== "working") continue;
    const surface = surfaceById[card.id];
    if (!surface || surface.kind !== "operator") continue;
    if (!changed) {
      surfaceById = { ...surfaceById };
      changed = true;
    }
    const instance = nodeInstanceStates[card.id];
    const progress = instance
      ? liveProgressFor(liveRun, card.id, instance.fingerprint)
      : null;
    const run = activeRunForNode(liveRun.runs, card.id, liveRun.callPath);
    // Instance state has no cancelling value. The in-flight cancel is the
    // run id the reducer is already sending. Another node's run stays
    // cancellable while this one waits on its own request.
    const cancelling = run !== null && liveRun.cancellingRunIds.has(run.run_id);
    const canCancel =
      !cancelling && liveRun.canCancelRun && run !== null && run.cancellable;
    surfaceById[card.id] = {
      ...surface,
      ...(progress ? { progress } : {}),
      cancelling,
      canCancel,
      ...(canCancel
        ? { onCancelRun: () => liveRun.onCancelNodeRun(card.id) }
        : {}),
    };
  }
  return changed ? { ...scene, surfaceById } : scene;
}

/** Fanned card backs a sequence shows behind its first picture. */
const STACK_PEEK_LIMIT = 2;

/** First-page PNG the fanned backs and the sequence spread show for a TIFF. Pages are 0-based. */
function tiffThumbnailUrl(workspaceId: string, artifactId: string): string {
  return imageThumbnailUrl(imagePath(workspaceId, artifactId), 0);
}

/**
 * The catalog's preview kind when it lists types. `null` means the catalog is
 * empty, so the caller keeps the unit-test fallback. A listed catalog that
 * omits this type is `file`.
 */
function catalogPreviewKind(
  ref: Pick<ArtifactRef, "artifact_type" | "schema_version">,
  registry: NodeRegistry,
): "image" | "tiff" | "tiff-text" | "file" | "other" | null {
  if (registry.artifact_types.length === 0) return null;
  const kind =
    artifactTypeFor(ref, registry.artifact_types)?.preview_kind ?? "file";
  if (
    kind === "image" ||
    kind === "tiff" ||
    kind === "tiff-text" ||
    kind === "file"
  ) {
    return kind;
  }
  return "other";
}

function isTiffRef(ref: ArtifactRef, registry: NodeRegistry): boolean {
  const kind = catalogPreviewKind(ref, registry);
  if (kind !== null) return kind === "tiff";
  return ref.artifact_type === "file.tiff";
}

function isTiffTextRef(ref: ArtifactRef, registry: NodeRegistry): boolean {
  const kind = catalogPreviewKind(ref, registry);
  if (kind !== null) return kind === "tiff-text";
  return (
    ref.artifact_type === "ocr.tiff_text_regions" ||
    ref.artifact_type === "ocr.tiff_recognized_text"
  );
}

/**
 * Whether a card paints this artifact's bytes as an image. A TIFF is a scan
 * the browser cannot decode, so its card uses a PNG thumbnail instead.
 */
function paintsInline(ref: ArtifactRef, registry: NodeRegistry): boolean {
  if (isTiffRef(ref, registry)) return false;
  const kind = catalogPreviewKind(ref, registry);
  if (kind === "image") return true;
  if (kind !== null) return false;
  const contentType = declaredArtifactContentType(
    artifactTypeFor(ref, registry.artifact_types),
  );
  if (contentType?.toLowerCase() === "image/tiff") return false;
  return isImageArtifact(ref, contentType);
}

function stackImageUrl(
  ref: ArtifactRef,
  workspaceId: string,
  registry: NodeRegistry,
): string | null {
  if (isTiffRef(ref, registry)) {
    return tiffThumbnailUrl(workspaceId, ref.artifact_id);
  }
  if (!paintsInline(ref, registry)) return null;
  return artifactInlineContentUrl(workspaceId, ref.artifact_id);
}

function viewerImagesFor(
  refs: readonly ArtifactRef[],
  workspaceId: string,
  registry: NodeRegistry,
  imageNaturalSizes?: ReadonlyMap<string, { width: number; height: number }>,
): CellViewerImages {
  const urls: string[] = [];
  for (const ref of refs.slice(0, STACK_PEEK_LIMIT + 1)) {
    if (isTiffRef(ref, registry)) {
      urls.push(tiffThumbnailUrl(workspaceId, ref.artifact_id));
      continue;
    }
    if (!paintsInline(ref, registry)) break;
    urls.push(artifactInlineContentUrl(workspaceId, ref.artifact_id));
  }
  const imageUrl = urls[0] ?? null;
  const lead = refs[0];
  const naturalSize =
    imageUrl == null
      ? null
      : (imageNaturalSizes?.get(imageUrl) ??
        (lead && isTiffRef(lead, registry)
          ? (imageNaturalSizes?.get(lead.artifact_id) ?? null)
          : null));
  return {
    imageUrl,
    stackImageUrls: urls.slice(1),
    itemCount: refs.length,
    naturalSize,
  };
}

type ConfigPatch = (nodeId: string, patch: WorkflowNodeConfig) => void;

function tiffSelectionFor(
  node: WorkflowNode,
  onOperatorConfigChange: ConfigPatch,
): TiffWindowSelection | null {
  if (!workflowNodeIsSupported(node.data)) return null;
  const window = readTiffWindow(node.data.config);
  if (!window) return null;
  const { scope, strategy } = node.data.config;
  return {
    window,
    ...(scope === "Whole TIFF page" ? { wholePage: true } : {}),
    ...(strategy === "Single crop" ? { singleCrop: true } : {}),
    onChange: (next: TiffWindow) => {
      onOperatorConfigChange(node.id, {
        page: next.page,
        col: next.col,
        row: next.row,
        width: next.width,
        height: next.height,
      });
    },
  };
}

/** The one node whose `tiff` input this card feeds, or null when it is not exactly one. */
function singleTiffConsumer(
  cardId: string,
  edges: readonly ArtifactOriginEdge[],
): string | null {
  const targets = new Set<string>();
  for (const edge of edges) {
    if (edge.source !== cardId || edge.targetPort !== "tiff") continue;
    targets.add(edge.target);
  }
  if (targets.size !== 1) return null;
  return [...targets][0] ?? null;
}

function linkedTiffWindow(
  cardId: string,
  edges: readonly ArtifactViewerEdge[],
  nodesById: ReadonlyMap<string, WorkflowNode>,
  document: AuthoredGraphDocument,
  registry: NodeRegistry,
  onOperatorConfigChange: ConfigPatch,
): { artifactId: string; selection: TiffWindowSelection } | undefined {
  const producers = new Set(
    edges.filter((edge) => edge.target === cardId).map((edge) => edge.source),
  );
  if (producers.size !== 1) return undefined;
  const producerId = [...producers][0];
  if (!producerId) return undefined;
  const producer = nodesById.get(producerId);
  if (!producer) return undefined;
  const selection = tiffSelectionFor(producer, onOperatorConfigChange);
  if (!selection) return undefined;
  const origin = document.origins.find(
    (item) => item.to_node === producerId && item.to_port === "tiff",
  );
  const fed = origin ? cardArtifactRefs(origin.value) : [];
  const lead = fed.length === 1 ? fed[0] : undefined;
  if (!lead || !isTiffRef(lead, registry)) return undefined;
  return { artifactId: lead.artifact_id, selection };
}

const APPENDIX_MIN_CELLS = 4;
const APPENDIX_ERROR_MAX_CELLS = 6;

function formatRelativeCompletedAt(
  iso: string | null | undefined,
  nowMs: number,
): string | null {
  if (!iso) return null;
  const timestamp = Date.parse(iso);
  if (!Number.isFinite(timestamp)) return null;
  const diffSeconds = Math.max(0, Math.floor((nowMs - timestamp) / 1000));
  if (diffSeconds < 45) return "Just now";
  if (diffSeconds < 3600) {
    return `${Math.max(1, Math.round(diffSeconds / 60))}m ago`;
  }
  if (diffSeconds < 86400) {
    return `${Math.round(diffSeconds / 3600)}h ago`;
  }
  return `${Math.round(diffSeconds / 86400)}d ago`;
}

function estimateErrorAppendixCells(errorText: string): number {
  const lines = errorText.split(/\r?\n/);
  const wrappedLines = lines.reduce(
    (total, line) => total + Math.max(1, Math.ceil(line.length / 42)),
    0,
  );
  if (wrappedLines <= 3) return APPENDIX_MIN_CELLS;
  if (wrappedLines <= 5) return 5;
  return APPENDIX_ERROR_MAX_CELLS;
}

export function buildAppendixSpec({
  node,
  status,
  instance,
  registry,
  nowMs,
}: {
  node: WorkflowNode;
  status?: CellNodeRunState["status"];
  instance?: RoomInstanceState;
  registry?: NodeRegistry | null;
  nowMs?: number;
}): CellExecutionAppendixSpec | undefined {
  const resolvedStatus = status ?? cellNodeStatus(node, instance).status;
  const { run, execution, layout, spec, artifactTypeBindings } = node.data;
  const currentNow = nowMs ?? Date.now();
  const savedAppendixCells =
    (layout?.appendixHeight ?? 0) > 0
      ? Math.max(
          APPENDIX_MIN_CELLS,
          Math.ceil((layout?.appendixHeight ?? 0) / CELL_SIZE),
        )
      : 0;

  if (resolvedStatus === "error") {
    const error =
      instance?.error || execution.error || run?.error || "Execution failed.";
    const completedAtLabel =
      run?.status === "failed" &&
      (!instance?.error || instance.error === run.error)
        ? formatRelativeCompletedAt(run.created_at, currentNow)
        : null;
    return {
      kind: "error",
      title: "Run failed",
      kindBadge: "Error",
      summaryText: error,
      errorText: error,
      completedAtLabel,
      heightCells: Math.max(
        savedAppendixCells,
        estimateErrorAppendixCells(error),
      ),
    };
  }

  const runOutputs = run?.outputs ?? [];
  if (runOutputs.length === 0) return undefined;

  const specOutputs = spec?.outputs ?? [];
  const portOrder = new Map(
    specOutputs.map((port, index) => [port.name, index]),
  );
  const orderedOutputs = [...runOutputs].sort((left, right) => {
    const leftIndex = portOrder.get(left.port) ?? Number.MAX_SAFE_INTEGER;
    const rightIndex = portOrder.get(right.port) ?? Number.MAX_SAFE_INTEGER;
    return leftIndex - rightIndex;
  });
  const catalogTypes = registry?.artifact_types ?? null;

  const outputs: CellExecutionAppendixOutput[] = orderedOutputs.map(
    (output) => {
      const portDef = specOutputs.find(
        (candidate) => candidate.name === output.port,
      );
      const label = portDef?.title?.trim() || output.port;
      const firstArtifact = output.artifacts[0];
      const portType = portDef
        ? resolvedPortArtifactType(portDef, artifactTypeBindings)
        : null;
      const resolvedType = firstArtifact
        ? {
            id: firstArtifact.artifact_type,
            schema_version: firstArtifact.schema_version,
          }
        : output.value
          ? {
              id: output.value.artifact_type,
              schema_version: output.value.schema_version,
            }
          : portType;
      const typeLabel = resolvedType
        ? formatArtifactTypeLabel(resolvedType, catalogTypes)
        : null;
      const typeKey = resolvedType ? artifactTypeKey(resolvedType) : null;
      const colorTypeId =
        portType?.id ??
        portDef?.artifact_type_variable ??
        resolvedType?.id ??
        null;
      const toneColor = colorTypeId
        ? artifactTypeColor(colorTypeId, "") || null
        : null;
      return {
        port: output.port,
        label,
        count: output.artifacts.length,
        kind: output.kind,
        typeLabel,
        typeKey,
        toneColor,
        artifactIds: output.artifacts.map((artifact) => artifact.artifact_id),
      };
    },
  );

  const itemCount = outputs.reduce((count, row) => count + row.count, 0);
  const itemText = `${itemCount} ${itemCount === 1 ? "item" : "items"}`;
  const summaryText =
    outputs.length > 1 ? `${outputs.length} outputs · ${itemText}` : itemText;
  return {
    kind: "output",
    title: "Outputs",
    kindBadge: "Output",
    summaryText,
    previewLines: outputs.map(
      (row) =>
        `${row.label}: ${row.count} ${row.count === 1 ? "item" : "items"}`,
    ),
    itemCount,
    outputs,
    completedAtLabel: formatRelativeCompletedAt(run?.created_at, currentNow),
    heightCells: appendixExpandedHeightCells({
      kind: "output",
      heightCells: savedAppendixCells,
      outputs,
    }),
  };
}

export function buildWorkbenchCellScene({
  workspaceId,
  document,
  registry,
  semantics,
  presentation,
  nodes,
  nodeInstanceStates,
  collapsedAppendices,
  configSections,
  secrets,
  engineSettingsHref,
  canRun,
  runDisabledReason,
  canvasEdges,
  artifactViewerEdges,
  artifactViewerNodes,
  artifactOriginEdges,
  libraryItemsByArtifactId,
  imageNaturalSizes,
  onOperatorConfigChange,
  liveRun,
}: {
  /** Names the content route for inline pictures; without it cards stay placeholders. */
  workspaceId?: string | null;
  document: AuthoredGraphDocument;
  registry: NodeRegistry;
  semantics?: ResolvedGraphSemantics | null;
  presentation: GraphPresentation | null;
  nodes: readonly WorkflowNode[];
  nodeInstanceStates: Readonly<Record<string, RoomInstanceState>>;
  collapsedAppendices: ReadonlySet<string>;
  /** Config sections the person opened or closed, by node, then by key. */
  configSections?: Readonly<Record<string, Readonly<Record<string, boolean>>>>;
  /** Key statuses and the saved nodes they are bound to. */
  secrets?: CellNodeSecretState;
  /** Owners' Workspace Settings link for an empty engine port. */
  engineSettingsHref?: string;
  canRun: boolean;
  /** Shown on each operator run control while `canRun` is false. */
  runDisabledReason?: string;
  canvasEdges?: readonly WorkflowEdge[];
  artifactViewerEdges?: readonly ArtifactViewerEdge[];
  artifactViewerNodes?: readonly ArtifactViewerNode[];
  artifactOriginEdges?: readonly ArtifactOriginEdge[];
  /** The Library's files by artifact id, to name a card's single artifact. */
  libraryItemsByArtifactId?: ReadonlyMap<string, PlacedLibraryItem>;
  /** Decoded natural pixel dimensions by image content URL, for auto-fit cards. */
  imageNaturalSizes?: ReadonlyMap<string, { width: number; height: number }>;
  /** Writes the TIFF window fields as one configuration patch. */
  onOperatorConfigChange?: ConfigPatch;
  /** Live progress and per-node cancel for the open graph. */
  liveRun?: CellLiveRunInput;
}) {
  const nodeRunState: Record<string, CellNodeRunState> = {};
  for (const node of nodes) {
    const instance = nodeInstanceStates[node.id];
    const isProvider = isServiceProviderNode(node.data.spec);
    const status = cellNodeStatus(node, instance);
    nodeRunState[node.id] = {
      ...status,
      runDisabled: !canRun || !workflowNodeIsSupported(node.data) || isProvider,
      ...(!canRun && runDisabledReason ? { runDisabledReason } : {}),
      appendix: buildAppendixSpec({
        node,
        status: status.status,
        instance,
        registry,
      }),
    };
  }

  let viewerOutputValues:
    | Map<
        string,
        { artifactTypeId: string; schemaVersion: number; shape: "one" | "many" }
      >
    | undefined;
  let viewerImages: Map<string, CellViewerImages> | undefined;
  let viewerMetadata: Map<string, CellViewerMetadata> | undefined;
  let viewerArtifacts: Map<string, ArtifactRef> | undefined;
  let viewerTiffWindows:
    Map<string, NonNullable<ArtifactCardSurfaceData["tiffWindow"]>> | undefined;
  let viewerTiffTexts:
    Map<string, NonNullable<ArtifactCardSurfaceData["tiffText"]>> | undefined;
  if (artifactViewerNodes) {
    viewerOutputValues = new Map();
    viewerImages = new Map();
    viewerMetadata = new Map();
    viewerArtifacts = new Map();
    viewerTiffWindows = new Map();
    viewerTiffTexts = new Map();
    const nodesById = new Map(nodes.map((node) => [node.id, node]));
    // A text card keeps its scan view while it waits for a result, so every
    // waiting one gets a surface, with or without a linked window.
    const rememberWaitingTiffText = (cardId: string) => {
      if (!workspaceId || !artifactViewerEdges) {
        return;
      }
      const feed = artifactViewerEdges.find((edge) => edge.target === cardId);
      const producer = feed ? nodesById.get(feed.source) : undefined;
      const port = producer?.data.spec.outputs.find(
        (item) => item.name === feed?.data?.sourcePortName,
      );
      const key = port ? portArtifactType(port) : null;
      if (
        !key ||
        !isTiffTextRef(
          {
            artifact_id: "",
            artifact_type: key.id,
            schema_version: key.schema_version,
          },
          registry,
        )
      ) {
        return;
      }
      const linkedWindow = onOperatorConfigChange
        ? linkedTiffWindow(
            cardId,
            artifactViewerEdges,
            nodesById,
            document,
            registry,
            onOperatorConfigChange,
          )
        : undefined;
      viewerTiffTexts?.set(cardId, {
        url: null,
        recognized: key.id === "ocr.tiff_recognized_text",
        ...(linkedWindow ? { linkedWindow } : {}),
      });
      if (!linkedWindow) return;
      const thumb = tiffThumbnailUrl(workspaceId, linkedWindow.artifactId);
      viewerImages?.set(cardId, {
        imageUrl: null,
        stackImageUrls: [],
        itemCount: 0,
        naturalSize:
          imageNaturalSizes?.get(thumb) ??
          imageNaturalSizes?.get(linkedWindow.artifactId) ??
          null,
      });
    };
    for (const card of artifactViewerNodes) {
      // The placed artifact, or the one a following card shows from its run.
      const value = artifactCardConnectionValue(
        card,
        artifactViewerEdges ?? [],
        nodes,
      );
      const refs = cardArtifactRefs(value);
      if (!value || refs.length === 0) {
        rememberWaitingTiffText(card.id);
        continue;
      }
      viewerOutputValues.set(card.id, {
        artifactTypeId: value.artifact_type,
        schemaVersion: value.schema_version,
        shape: "item_refs" in value ? "many" : "one",
      });
      if (workspaceId) {
        viewerImages.set(
          card.id,
          viewerImagesFor(refs, workspaceId, registry, imageNaturalSizes),
        );
        const lead = refs[0];
        if (lead) {
          viewerArtifacts.set(card.id, lead);
          if (
            refs.length === 1 &&
            isTiffRef(lead, registry) &&
            onOperatorConfigChange &&
            artifactOriginEdges
          ) {
            const consumerId = singleTiffConsumer(card.id, artifactOriginEdges);
            const consumer = consumerId ? nodesById.get(consumerId) : undefined;
            const selection = consumer
              ? tiffSelectionFor(consumer, onOperatorConfigChange)
              : null;
            if (selection) {
              viewerTiffWindows.set(card.id, {
                artifactId: lead.artifact_id,
                selection,
              });
            }
          }
          if (isTiffTextRef(lead, registry)) {
            const linkedWindow =
              onOperatorConfigChange && artifactViewerEdges
                ? linkedTiffWindow(
                    card.id,
                    artifactViewerEdges,
                    nodesById,
                    document,
                    registry,
                    onOperatorConfigChange,
                  )
                : undefined;
            viewerTiffTexts.set(card.id, {
              url: artifactInlineContentUrl(workspaceId, lead.artifact_id),
              recognized: lead.artifact_type === "ocr.tiff_recognized_text",
              ...(linkedWindow ? { linkedWindow } : {}),
            });
            if (linkedWindow) {
              const thumb = tiffThumbnailUrl(
                workspaceId,
                linkedWindow.artifactId,
              );
              const images = viewerImages.get(card.id);
              if (images && images.naturalSize == null) {
                viewerImages.set(card.id, {
                  ...images,
                  naturalSize:
                    imageNaturalSizes?.get(thumb) ??
                    imageNaturalSizes?.get(linkedWindow.artifactId) ??
                    null,
                });
              }
            }
          }
        }
      }
      // A sequence has no one file name; its card says its count instead,
      // and its spread names every item.
      if (refs.length > 1) {
        viewerMetadata.set(card.id, {
          stackItems: refs.map((ref, index) => {
            const item = libraryItemsByArtifactId?.get(ref.artifact_id);
            const byteSizeLabel = item
              ? formatLibraryByteSize(item.artifact.byte_size)
              : null;
            return {
              artifactId: ref.artifact_id,
              artifact: ref,
              imageUrl: workspaceId
                ? stackImageUrl(ref, workspaceId, registry)
                : null,
              label: item ? libraryFileDisplayName(item) : `#${index + 1}`,
              ...(byteSizeLabel ? { byteSizeLabel } : {}),
            };
          }),
        });
        continue;
      }
      const libraryItem = refs[0]
        ? libraryItemsByArtifactId?.get(refs[0].artifact_id)
        : undefined;
      if (libraryItem) {
        viewerMetadata.set(card.id, {
          filename: libraryFileDisplayName(libraryItem),
          byteSizeLabel: formatLibraryByteSize(libraryItem.artifact.byte_size),
          inLibrary: true,
          exportFormats: libraryItem.artifact.download_formats,
        });
      }
    }
  }

  const originsById = new Map(
    document.origins.map((origin) => [origin.id, origin]),
  );
  const originLinks: CellOriginLink[] | undefined = artifactOriginEdges
    ? artifactOriginEdges.flatMap((edge): CellOriginLink[] => {
        if (!edge.targetPort) return [];
        const origin = originsById.get(edge.data.originId);
        return [
          {
            id: edge.id,
            originId: edge.data.originId,
            sourceCardId: edge.source,
            targetCardId: edge.target,
            targetPortId: edge.targetPlug
              ? `${edge.targetPort}::${edge.targetPlug}`
              : edge.targetPort,
            collectionMode:
              semantics?.origins.get(edge.data.originId)?.collectionMode ??
              edge.data.collectionMode ??
              "direct",
            conversionCount: origin?.conversion_path.length ?? 0,
          },
        ];
      })
    : undefined;

  let pipeMetadataById: Map<string, CellPipeMetadata> | undefined;
  if (canvasEdges || artifactViewerEdges) {
    pipeMetadataById = new Map();
    for (const edge of canvasEdges ?? []) {
      const projection = edge.data?.projection;
      const activeProjectionTitle = projection
        ? edge.data?.routeOptions?.find(
            (route) =>
              route.projection?.path.length === projection.path.length &&
              route.projection?.path.every(
                (segment, index) => segment === projection.path[index],
              ),
          )?.projectionTitle
        : undefined;
      const projectionLabel = projection
        ? (activeProjectionTitle ?? projection.path.join("."))
        : null;
      const conversionLabel = edge.data?.conversionTitles?.length
        ? edge.data.conversionTitles.join(" → ")
        : edge.data?.conversionPath?.length
          ? `${edge.data.conversionPath.length} conv`
          : null;
      pipeMetadataById.set(edge.id, {
        projectionLabel,
        conversionLabel,
        sourcePortLabel: edge.sourcePort,
        incompatible: Boolean(edge.data?.compatibilityIssues?.length),
      });
    }
    for (const edge of artifactViewerEdges ?? []) {
      const projection = edge.data?.projection;
      pipeMetadataById.set(edge.id, {
        projectionLabel: projection
          ? (edge.data?.projectionTitle ?? projection.path.join("."))
          : null,
        conversionLabel: null,
        sourcePortLabel: edge.data?.sourcePortName,
      });
    }
  }

  const scene = cellGraphFromAuthoredDocument(document, registry, {
    semantics: semantics ?? undefined,
    presentation,
    nodeRunState,
    collapsedAppendices,
    configSections,
    secrets,
    engineSettingsHref,
    originLinks,
    viewerOutputValues,
    pipeMetadataById,
    viewerImages,
    viewerMetadata,
    workspaceId: workspaceId ?? undefined,
    viewerArtifacts,
    viewerTiffWindows,
    viewerTiffTexts,
  });
  return liveRun ? applyLiveRun(scene, nodeInstanceStates, liveRun) : scene;
}

export function cellRemotePeersFromParticipants(
  participants: readonly PresenceParticipant[],
  localSessionId: string | null,
  openGraphId: string | null,
): CellRemotePeerState[] {
  if (openGraphId === null) return [];
  return participants
    .filter(
      (peer) =>
        peer.project_room_session_id !== localSessionId &&
        peer.graph_id === openGraphId,
    )
    .map((peer) => ({
      actorId: peer.actor.actor_id,
      sessionId: peer.project_room_session_id,
      displayName: peer.actor.display_name,
      color: actorColor(peer.actor.color),
      cursor: peer.cursor,
      activity: peer.activity ?? "idle",
      selectedCardIds: peer.selected_node_ids,
      draggingCards: Object.fromEntries(
        peer.transient_node_positions.map((position) => [
          position.node_id,
          cellOriginFromWorld(position),
        ]),
      ),
    }));
}

export type CellResolvedConnection =
  | ({ readonly kind: "workflow" } & GraphConnection)
  | ({ readonly kind: "artifact-card" } & ArtifactCardConnection)
  | {
      readonly kind: "artifact-viewer";
      readonly sourceNodeId: string;
      readonly sourcePort: string;
      readonly targetViewerId: string;
    };

export function resolveCellPortEndpoint(
  node: WorkflowNode,
  portId: string,
  direction: "input" | "output",
) {
  const separator = direction === "input" ? portId.indexOf("::") : -1;
  const portName = separator < 0 ? portId : portId.slice(0, separator);
  const plugId = separator < 0 ? undefined : portId.slice(separator + 2);
  const ports =
    direction === "input" ? node.data.spec.inputs : node.data.spec.outputs;
  const port = ports.find((candidate) => candidate.name === portName);
  if (!port || port.direction !== direction) return null;
  const meta = portMetaForPort(
    port,
    direction === "input" ? port.shape : effectivePortShape(node.data, port),
    plugId,
    node.data.artifactTypeBindings,
  );
  return { port, portName, plugId, meta };
}

export function cellConnectionToWorkbenchConnection(
  nodes: readonly WorkflowNode[],
  viewers: readonly ArtifactViewerCanvasState["nodes"][number][],
  {
    sourceCardId,
    sourcePortId,
    targetCardId,
    targetPortId,
  }: CellConnectionEnds,
): CellResolvedConnection | null {
  const sourceNode = nodes.find((node) => node.id === sourceCardId);
  const targetNode = nodes.find((node) => node.id === targetCardId);
  const sourceEndpoint = sourceNode
    ? resolveCellPortEndpoint(sourceNode, sourcePortId, "output")
    : null;
  const targetEndpoint = targetNode
    ? resolveCellPortEndpoint(targetNode, targetPortId, "input")
    : null;

  if (sourceEndpoint && targetEndpoint) {
    return {
      kind: "workflow",
      source: sourceCardId,
      sourcePort: sourceEndpoint.portName,
      target: targetCardId,
      targetPort: targetEndpoint.portName,
      targetPlug: targetEndpoint.plugId ?? null,
    };
  }
  if (
    !sourceNode &&
    sourcePortId === ARTIFACT_CARD_OUTPUT_HANDLE &&
    viewers.some((viewer) => viewer.id === sourceCardId) &&
    targetEndpoint
  ) {
    return {
      kind: "artifact-card",
      sourceCardId,
      targetNodeId: targetCardId,
      targetPort: targetEndpoint.portName,
      targetPlug: targetEndpoint.plugId ?? null,
    };
  }
  if (
    sourceEndpoint &&
    !targetNode &&
    targetPortId === ARTIFACT_VIEWER_INPUT_HANDLE &&
    viewers.some((viewer) => viewer.id === targetCardId)
  ) {
    return {
      kind: "artifact-viewer",
      sourceNodeId: sourceCardId,
      sourcePort: sourceEndpoint.portName,
      targetViewerId: targetCardId,
    };
  }
  return null;
}

export function partitionCellSelection(
  { cardIds, pipeIds }: CellSelectionSnapshot,
  document: AuthoredGraphDocument,
  artifactViewers: ArtifactViewerCanvasState,
): CanvasSelection {
  return {
    nodeIds: document.nodes
      .filter(({ id }) => cardIds.has(id))
      .map(({ id }) => id),
    agentIds: document.agents
      .filter(({ id }) => cardIds.has(id))
      .map(({ id }) => id),
    viewerIds: artifactViewers.nodes
      .filter(({ id }) => cardIds.has(id))
      .map(({ id }) => id),
    annotationIds: artifactViewers.annotations
      .filter(({ id }) => cardIds.has(id))
      .map(({ id }) => id),
    edgeIds: [...pipeIds],
  };
}

export function partitionCellMoves(
  moves: readonly CellCardMove[],
  document: AuthoredGraphDocument,
  artifactViewers: ArtifactViewerCanvasState,
) {
  const viewerIds = new Set(artifactViewers.nodes.map(({ id }) => id));
  const annotationIds = new Set(
    artifactViewers.annotations.map(({ id }) => id),
  );
  const viewerPositions = moves
    .filter(({ cardId }) => viewerIds.has(cardId))
    .map(({ cardId, col, row }) => ({
      viewer_id: cardId,
      ...cellToWorldOrigin(col, row),
    }));
  const annotationPositions = moves
    .filter(({ cardId }) => annotationIds.has(cardId))
    .map(({ cardId, col, row }) => ({
      annotation_id: cardId,
      ...cellToWorldOrigin(col, row),
    }));
  return {
    graphCommands: graphCommandsFromCellMovesForDocument(document, moves),
    viewerPositions,
    annotationPositions,
  };
}

export function partitionCellRemovals(
  cardIds: readonly string[],
  pipeIds: readonly string[],
  document: AuthoredGraphDocument,
  artifactViewers: ArtifactViewerCanvasState,
  artifactOriginEdges: readonly Pick<
    ArtifactOriginEdge,
    "id" | "source" | "target" | "data"
  >[] = [],
) {
  const cards = new Set(cardIds);
  const pipes = new Set(pipeIds);
  const removedWorkflowNodeIds = document.nodes
    .filter(({ id }) => cards.has(id))
    .map(({ id }) => id);
  const removedViewerIds = artifactViewers.nodes
    .filter(({ id }) => cards.has(id))
    .map(({ id }) => id);
  const removedAnnotationIds = artifactViewers.annotations
    .filter(({ id }) => cards.has(id))
    .map(({ id }) => id);
  const removedViewerEdgeIds = artifactViewers.edges
    .filter(
      ({ id, source, target }) =>
        pipes.has(id) || cards.has(source) || cards.has(target),
    )
    .map(({ id }) => id);
  const originEdgesById = new Map(
    artifactOriginEdges.map((edge) => [edge.id, edge]),
  );
  const removedOriginSources = new Map<string, Set<string>>();
  for (const pipeId of pipes) {
    const edge = originEdgesById.get(pipeId);
    if (!edge || cards.has(edge.source) || cards.has(edge.target)) continue;
    const sources =
      removedOriginSources.get(edge.data.originId) ?? new Set<string>();
    sources.add(edge.source);
    removedOriginSources.set(edge.data.originId, sources);
  }
  const originCommands = document.origins.flatMap((origin) => {
    const sources = removedOriginSources.get(origin.id);
    return sources ? changeOriginCardReferences(origin, sources) : [];
  });
  return {
    graphCommands: [
      ...graphCommandsFromCellDeleteForDocument(document, cardIds, pipeIds),
      ...originCommands,
    ],
    removedWorkflowNodeIds,
    removedViewerIds,
    removedAnnotationIds,
    removedViewerEdgeIds,
  };
}

export function planWorkbenchCanvasCleanup({
  workspaceId,
  document,
  artifactViewers,
  registry,
  nodes,
  nodeInstanceStates,
  collapsedAppendices,
  configSections,
  imageNaturalSizes,
  selectedCardIds,
  resizeCards,
  params,
}: {
  workspaceId?: string | null;
  document: AuthoredGraphDocument;
  artifactViewers: ArtifactViewerCanvasState;
  registry: NodeRegistry;
  nodes: readonly WorkflowNode[];
  nodeInstanceStates: Readonly<Record<string, RoomInstanceState>>;
  collapsedAppendices: ReadonlySet<string>;
  configSections?: Readonly<Record<string, Readonly<Record<string, boolean>>>>;
  imageNaturalSizes?: ReadonlyMap<string, { width: number; height: number }>;
  selectedCardIds?: ReadonlySet<string>;
  resizeCards?: boolean;
  params?: Partial<CellCleanupParams>;
}): CellCleanupPlan {
  const nodeRunState: Record<string, CellNodeRunState> = {};
  for (const node of nodes) {
    const instance = nodeInstanceStates[node.id];
    const status = cellNodeStatus(node, instance);
    nodeRunState[node.id] = {
      ...status,
      appendix: buildAppendixSpec({
        node,
        status: status.status,
        instance,
        registry,
      }),
    };
  }

  const viewerOutputValues = new Map<
    string,
    { artifactTypeId: string; schemaVersion: number; shape: "one" | "many" }
  >();
  const viewerImages = new Map<string, CellViewerImages>();
  for (const card of artifactViewers.nodes) {
    const value = artifactCardConnectionValue(
      card,
      artifactViewers.edges,
      nodes,
    );
    const refs = cardArtifactRefs(value);
    if (!value || refs.length === 0) continue;
    viewerOutputValues.set(card.id, {
      artifactTypeId: value.artifact_type,
      schemaVersion: value.schema_version,
      shape: "item_refs" in value ? "many" : "one",
    });
    if (workspaceId) {
      viewerImages.set(
        card.id,
        viewerImagesFor(refs, workspaceId, registry, imageNaturalSizes),
      );
    }
  }

  return planCellGraphCleanup(document, artifactViewers, registry, {
    selectedCardIds,
    resizeCards,
    params,
    nodeRunState,
    collapsedAppendices,
    configSections,
    viewerImages,
    viewerOutputValues,
  });
}

export {
  DEFAULT_CELL_CLEANUP_PARAMS,
  buildCleanupUndoPlan,
  mergeCleanupUndoSnapshots,
  type CellCleanupCardSizePreset,
  type CellCleanupParams,
  type CellCleanupUndoSnapshot,
};
