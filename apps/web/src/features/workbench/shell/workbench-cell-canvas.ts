import {
  artifactInlineContentUrl,
  type ArtifactRef,
  type NodeRegistry,
  type PlacedLibraryItem,
} from "@/lib/api";
import {
  artifactTypeFor,
  cardArtifactRefs,
  declaredArtifactContentType,
  isImageArtifact,
} from "../artifacts/artifact-card";
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
  effectivePortShape,
  isServiceProviderNode,
  portMetaForPort,
  workflowNodeIsSupported,
  type GraphConnection,
  type WorkflowEdge,
  type WorkflowNode,
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
  CellRemotePeerState,
  CellSelectionSnapshot,
} from "../cell-canvas/cell-contracts";
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
import { CELL_SIZE, cellToWorldOrigin } from "../cell-canvas/cell-model";
import type { AuthoredGraphDocument } from "../authoring/graph-document";
import type { ResolvedGraphSemantics } from "../authoring/graph-semantics";
import { changeOriginCardReferences } from "../artifacts/origin-card-commands";
import type {
  PresenceParticipant,
  RoomInstanceState,
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

/** Fanned card backs a sequence shows behind its first picture. */
const STACK_PEEK_LIMIT = 2;

/**
 * Whether a card paints this artifact inline. TIFF is an image the browser
 * cannot decode, so it keeps the placeholder until the canvas renders it.
 */
function paintsInline(ref: ArtifactRef, registry: NodeRegistry): boolean {
  const contentType = declaredArtifactContentType(
    artifactTypeFor(ref, registry.artifact_types),
  );
  if (ref.artifact_type === "file.tiff") return false;
  if (contentType?.toLowerCase() === "image/tiff") return false;
  return isImageArtifact(ref, contentType);
}

function viewerImagesFor(
  refs: readonly ArtifactRef[],
  workspaceId: string,
  registry: NodeRegistry,
  imageNaturalSizes?: ReadonlyMap<string, { width: number; height: number }>,
): CellViewerImages {
  const urls: string[] = [];
  for (const ref of refs.slice(0, STACK_PEEK_LIMIT + 1)) {
    if (!paintsInline(ref, registry)) break;
    urls.push(artifactInlineContentUrl(workspaceId, ref.artifact_id));
  }
  const imageUrl = urls[0] ?? null;
  return {
    imageUrl,
    stackImageUrls: urls.slice(1),
    itemCount: refs.length,
    naturalSize: imageUrl ? (imageNaturalSizes?.get(imageUrl) ?? null) : null,
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
  canRun,
  canvasEdges,
  artifactViewerEdges,
  artifactViewerNodes,
  artifactOriginEdges,
  libraryItemsByArtifactId,
  imageNaturalSizes,
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
  canRun: boolean;
  canvasEdges?: readonly WorkflowEdge[];
  artifactViewerEdges?: readonly ArtifactViewerEdge[];
  artifactViewerNodes?: readonly ArtifactViewerNode[];
  artifactOriginEdges?: readonly ArtifactOriginEdge[];
  /** The Library's files by artifact id, to name a card's single artifact. */
  libraryItemsByArtifactId?: ReadonlyMap<string, PlacedLibraryItem>;
  /** Decoded natural pixel dimensions by image content URL, for auto-fit cards. */
  imageNaturalSizes?: ReadonlyMap<string, { width: number; height: number }>;
}) {
  const nodeRunState: Record<string, CellNodeRunState> = {};
  for (const node of nodes) {
    const instance = nodeInstanceStates[node.id];
    const { run, execution, layout } = node.data;
    const isProvider = isServiceProviderNode(node.data.spec);
    const status = cellNodeStatus(node, instance);
    const error =
      status.status === "error"
        ? instance?.error ||
          execution.error ||
          run?.error ||
          "Execution failed."
        : null;
    const outputs = run?.outputs ?? [];
    const itemCount = outputs.reduce(
      (count, output) => count + output.artifacts.length,
      0,
    );
    const heightCells = Math.max(
      4,
      Math.ceil((layout?.appendixHeight ?? 0) / CELL_SIZE),
    );
    nodeRunState[node.id] = {
      ...status,
      runDisabled: !canRun || !workflowNodeIsSupported(node.data) || isProvider,
      appendix: error
        ? {
            title: "Execution error",
            kindBadge: "Error",
            summaryText: error,
            heightCells,
          }
        : outputs.length
          ? {
              title: "Execution output",
              kindBadge: "Output",
              summaryText: `${outputs.length} output port${outputs.length === 1 ? "" : "s"}`,
              previewLines: outputs.map(
                ({ port, artifacts }) =>
                  `${port}: ${artifacts.length} artifact${artifacts.length === 1 ? "" : "s"}`,
              ),
              itemCount,
              heightCells,
            }
          : undefined,
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
  if (artifactViewerNodes) {
    viewerOutputValues = new Map();
    viewerImages = new Map();
    viewerMetadata = new Map();
    for (const card of artifactViewerNodes) {
      // The placed artifact, or the one a following card shows from its run.
      const value = artifactCardConnectionValue(
        card,
        artifactViewerEdges ?? [],
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
      // A sequence has no one file name; its card says its count instead,
      // and its spread names every item.
      if (refs.length > 1) {
        viewerMetadata.set(card.id, {
          stackItems: refs.map((ref, index) => {
            const item = libraryItemsByArtifactId?.get(ref.artifact_id);
            return {
              artifactId: ref.artifact_id,
              imageUrl:
                workspaceId && paintsInline(ref, registry)
                  ? artifactInlineContentUrl(workspaceId, ref.artifact_id)
                  : null,
              label: item ? libraryFileDisplayName(item) : `#${index + 1}`,
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

  return cellGraphFromAuthoredDocument(document, registry, {
    semantics: semantics ?? undefined,
    presentation,
    nodeRunState,
    collapsedAppendices,
    configSections,
    secrets,
    originLinks,
    viewerOutputValues,
    pipeMetadataById,
    viewerImages,
    viewerMetadata,
  });
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
