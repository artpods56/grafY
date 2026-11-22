"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ChevronDown } from "lucide-react";

import { IconButton } from "@/components/ui/button";
import { artifactTypeColor } from "@/features/workbench/config-ui/nodes.css";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { CellCanvasProvider, CellViewportLayer } from "./CellCanvasContext";
import { CellCard } from "./CellCard";
import {
  CellArtifactMergeSuggestionOverlay,
  CellArtifactMergeTargetOverlay,
  CellDockedBridgeLayer,
  CellEdgeSelectorPill,
  CellLandingOutlines,
  CellMarqueeOverlay,
  CellRemotePresenceLayer,
} from "./CellGlassOverlays";
import {
  CellAgentCard,
  CellAnnotationCard,
} from "./cards/CellAnnotationAndAgentCards";
import { CellArtifactCard, CellCollectionCard } from "./cards/CellArtifactCard";
import { CellArtifactSequenceSpread } from "./cards/CellArtifactSequenceSpread";
import { CellOperatorCard } from "./cards/CellOperatorCard";
import { CellStackTuckLayer, type StackTuck } from "./cards/CellStackTuckLayer";
import {
  artifactCardItemCount,
  computeSequenceSpreadLayout,
  findArtifactMergeSuggestions,
  findArtifactMergeTarget,
  findSpreadInsertTarget,
  type ArtifactMergeOrder,
  type ArtifactMergeSuggestion,
  type OpenSequenceSpreadLayout,
  type SpreadInsertTarget,
} from "./cell-artifact-stacking";
import { plugRowOffset } from "./cell-card-geometry";
import type {
  AnnotationColorToken,
  ArtifactCardSurfaceData,
  CellCardSurfaceData,
  CellConnectDropEmptyEvent,
  CellDockedJoin,
  CellRemotePeerState,
  CellResizeCommit,
  CellResizeEdge,
  CellSelectionSnapshot,
  CellViewportApi,
} from "./cell-contracts";
import { detectCellDockedJoins } from "./cell-docking";
import {
  CellConnectionPreview,
  CellGlassStage,
  type CellGlassLook,
  type LiveConnectionPreview,
  type StagePipe,
  type StageViewport,
  type StageWell,
} from "./cell-glass-stage";
import { DEFAULT_CELL_GLASS_LOOK, DEFAULT_CELL_ROUTING } from "./cell-look";
import {
  computeCellResize,
  createGroupDragSession,
  partitionSceneForMovingCards,
  resolveNonOverlappingDelta,
  updateGroupDragSession,
  type GroupDragSession,
} from "./cell-group-drag";
import {
  ARTIFACT_CARD_OUTPUT_PORT_ID,
  CELL_PIPE_STUB_MIN,
  CELL_SIZE,
  artifactCardOutputRow,
  cardWorldRect,
  cellToWorldOrigin,
  PUNCHED_PORT_INSET,
  portAnchorCenter,
  portSide,
  portWorldCenter,
  punchedPipePoints,
  type CellCardModel,
  type CellCoord,
  type CellDir,
  type CellGraph,
  type CellPort,
  type CellRoutingOptions,
  type CellRoutingResult,
  type WorldPoint,
  cellPortKey,
} from "./cell-model";
import { solvePipeAttachmentAnchors } from "./cell-pipe-attachments";
import { routeCellGraph } from "./cell-router";
import {
  cardsInMarqueeRect,
  createCellInteractionStore,
  pipesInMarqueeRect,
} from "./cell-store";
import {
  MORPH_DURATION_MS,
  anchorPipeEndpoints,
  createCardSettle,
  morphPipePoints,
  retargetCardSettle,
  shouldAnimateMotion,
  stepCardSettle,
  type CardSettleState,
} from "./cell-transitions";
import { useCellViewport, type WorldBounds } from "./use-cell-viewport";
import { useRemoteCellDrag } from "./use-remote-cell-drag";

export interface CellCanvasStats {
  cards: number;
  pipes: number;
  deepCount: number;
  reroutes: number;
  draggedCardId: string | null;
}

export interface CellCanvasDebugApi {
  setViewAt: (
    wx: number,
    wy: number,
    zoom: number,
    sx?: number,
    sy?: number,
  ) => StageViewport;
  getViewport: () => StageViewport;
  getStats: () => CellCanvasStats;
  getSelection: () => CellSelectionSnapshot;
  setSelection: (next: {
    cardIds?: Iterable<string>;
    pipeIds?: Iterable<string>;
  }) => void;
  lastConnectDropEmpty: CellConnectDropEmptyEvent | null;
  fit: () => void;
}

declare global {
  interface Window {
    __cellCanvas?: CellCanvasDebugApi;
  }
}

export interface CellCanvasViewportHandle {
  getViewport(): { x: number; y: number; zoom: number };
  fitBounds(bounds: WorldBounds, paddingRatio?: number, maxZoom?: number): void;
  screenToWorld(clientX: number, clientY: number): WorldPoint;
  worldToScreen(world: WorldPoint): WorldPoint;
  zoomBy(factor: number): void;
}

export interface CellCanvasHandle {
  viewportHandle: CellCanvasViewportHandle;
  fitGraph(paddingRatio?: number, maxZoom?: number): void;
  fitCards(
    cardIds: readonly string[],
    paddingRatio?: number,
    maxZoom?: number,
  ): void;
  zoomAtCenter(nextZoom: number): void;
  zoomBy(factor: number): void;
  viewAt(
    worldX: number,
    worldY: number,
    zoom: number,
    screenX?: number,
    screenY?: number,
  ): StageViewport;
  cancelGesture(): void;
}

export interface CellCardMove {
  cardId: string;
  col: number;
  row: number;
}

export interface CellConnectionEnds {
  sourceCardId: string;
  sourcePortId: string;
  targetCardId: string;
  targetPortId: string;
}

export interface CellCanvasProps {
  graph: CellGraph;
  surfaceById?: Readonly<Record<string, CellCardSurfaceData>>;
  look?: CellGlassLook;
  routing?: CellRoutingOptions;
  editable?: boolean;
  selectedCardIds?: ReadonlySet<string>;
  selectedPipeIds?: ReadonlySet<string>;
  inspectedPipeId?: string | null;
  remotePeers?: readonly CellRemotePeerState[];
  remoteDragScope?: string | null;
  fitLeftClearance?: number;
  autoFitOnMount?: boolean;
  dataGraph?: string;
  exposeDebugApi?: boolean;
  onMoveCards?: (moves: readonly CellCardMove[]) => void;
  onDragCardsProgress?: (positions: readonly CellCardMove[] | null) => void;
  onResizeCard?: (commit: CellResizeCommit) => void;
  onCanConnect?: (candidate: CellConnectionEnds) => boolean;
  onConnect?: (connection: CellConnectionEnds) => void;
  onConnectDropEmpty?: (event: CellConnectDropEmptyEvent) => void;
  onRemoveCards?: (cardIds: readonly string[]) => void;
  onRemovePipes?: (pipeIds: readonly string[]) => void;
  onSelectionChange?: (selection: CellSelectionSnapshot) => void;
  onPaneClick?: () => void;
  onSelectEdgeAttachment?: (pipeId: string, anchor?: WorldPoint) => void;
  onOperatorRun?: (cardId: string) => void;
  onOperatorConfigChange?: (
    cardId: string,
    fieldId: string,
    value: string | number | boolean,
  ) => void;
  onOperatorAddPlug?: (cardId: string, portName: string) => void;
  onOperatorRemovePlug?: (
    cardId: string,
    portName: string,
    plugId: string,
  ) => void;
  onOperatorToggleAppendix?: (cardId: string) => void;
  onAnnotationColorChange?: (
    cardId: string,
    color: AnnotationColorToken,
  ) => void;
  onArtifactInspect?: (cardId: string) => void;
  /** Whether one artifact card's items may join another's sequence. */
  canMergeArtifactCards?: (
    sourceCardId: string,
    targetCardId: string,
  ) => boolean;
  /** Joins the source card's items onto the target's sequence; the source goes. */
  onMergeArtifactCards?: (
    sourceCardId: string,
    targetCardId: string,
    order?: ArtifactMergeOrder,
  ) => void;
  onReorderArtifactCardItem?: (
    cardId: string,
    fromIndex: number,
    toIndex: number,
  ) => void;
  /** Joins a whole flush run onto one card, in the run's visual order. */
  onMergeArtifactCardRun?: (
    cardIds: readonly string[],
    targetCardId: string,
  ) => void;
  /** Inserts a dragged card's items into an open sequence at `insertIndex`. */
  onInsertArtifactCardIntoSequence?: (
    sourceCardId: string,
    targetCardId: string,
    insertIndex: number,
  ) => void;
  /** Pulls one item out of a sequence onto its own card, at `targetCell`. */
  onExtractArtifactCardItem?: (
    cardId: string,
    index: number,
    targetCell?: CellCoord,
  ) => void;
  /** Takes one item out of a sequence and off the canvas. */
  onRemoveArtifactCardItem?: (cardId: string, index: number) => void;
  onUngroupArtifactCard?: (cardId: string) => void;
  /** Reports a decoded image artifact's natural pixel dimensions. */
  onArtifactImageLoad?: (
    imageUrl: string,
    size: { width: number; height: number },
  ) => void;
  onCollectionRemoveMember?: (cardId: string, memberId: string) => void;
  onHandleReady?: (handle: CellCanvasHandle | null) => void;
  onViewportZoomChange?: (zoom: number) => void;
  onStatsChange?: (stats: CellCanvasStats) => void;
  children?: React.ReactNode;
}

/** Screen pixels a pointer travels before a press on a card becomes a drag. */
const DRAG_THRESHOLD_PX = 3;
/** How close, in flow units, the cursor must come to a port to wire to it. */
const WIRE_SNAP_RADIUS = 22;

export { DEFAULT_CELL_GLASS_LOOK, DEFAULT_CELL_ROUTING };

const EMPTY_ID_SET: ReadonlySet<string> = new Set();
const EMPTY_PORT_IDS: ReadonlySet<string> = new Set();
const EMPTY_PIPES: readonly StagePipe[] = [];
const EMPTY_WELLS: readonly StageWell[] = [];
const EMPTY_SURFACES: Readonly<Record<string, CellCardSurfaceData>> = {};
const EMPTY_REMOTE_PEERS: readonly CellRemotePeerState[] = [];

const s = stylex.create({
  root: {
    position: "relative",
    width: "100%",
    height: "100%",
    overflow: "hidden",
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
    cursor: "default",
    touchAction: "none",
  },
  rootPanning: { cursor: "grabbing" },
  world: {
    position: "absolute",
    top: 0,
    left: 0,
    zIndex: 4,
    width: "1px",
    height: "1px",
    overflow: "visible",
    transformOrigin: "0 0",
    pointerEvents: "none",
    willChange: "transform",
  },
  // Cards inherit this; the layer itself has no box to catch the pointer.
  cards: {
    position: "absolute",
    top: 0,
    left: 0,
    pointerEvents: "auto",
  },
});

// ---------------------------------------------------------------------------
// Pure helpers

interface DragGhostBox {
  cardId: string;
  col: number;
  row: number;
  widthCells: number;
  heightCells: number;
}

interface DragFrameState {
  anchorCardId: string;
  snappedDelta: CellCoord;
  visualOffset: WorldPoint;
  showGhostCells: boolean;
  ghostBoxes: readonly DragGhostBox[];
  movingPipes: readonly StagePipe[];
  movingWells: readonly StageWell[];
}

interface GraphIndex {
  cardsById: ReadonlyMap<string, CellCardModel>;
  portsByCardId: ReadonlyMap<string, ReadonlyMap<string, CellPort>>;
  connectedPortIdsByCardId: ReadonlyMap<string, ReadonlySet<string>>;
}

interface PortRef {
  card: CellCardModel;
  port: CellPort;
}

interface RestingScene {
  pipes: readonly StagePipe[];
  wells: readonly StageWell[];
  /** Keys of the wells the resting scene draws. */
  wellKeys: ReadonlySet<string>;
  /** Pipes attached to the moving card group, which the moving scene draws. */
  attachedPipeIds: ReadonlySet<string>;
}

interface PipeMotion {
  id: string;
  sourceCardId: string;
  targetCardId: string;
  sourcePortId: string;
  targetPortId: string;
  color: string;
  sequence: boolean;
  disabled: boolean;
  fromPoints: WorldPoint[];
  toPoints: WorldPoint[];
  currentPoints: WorldPoint[];
  sourceExit: CellDir;
  targetExit: CellDir;
  depth: number;
  morphStartMs: number;
  morphing: boolean;
  /** True while this pipe's two endpoints remain flush-docked at the current cell delta. */
  dockedAtCurrentCell: boolean;
}

interface GroupCardDrag {
  anchorCardId: string;
  session: GroupDragSession;
  startClient: WorldPoint;
  movedBeyondClick: boolean;
  pointerReleased: boolean;
  cellSettle: CardSettleState;
  /** The delta the group lands on if dropped now: never overlapping a card. */
  landingDelta: CellCoord;
  attachedPipeIds: ReadonlySet<string>;
  restingWellKeys: ReadonlySet<string>;
  pipes: PipeMotion[];
  /** Ports are punched holes in the cards: pipes run on into them. */
  punched: boolean;
}

interface WireTarget {
  cardId: string;
  port: CellPort;
  centre: WorldPoint;
}

interface WiringState {
  fromCardId: string;
  fromPort: CellPort;
  cursor: WorldPoint;
  target: WireTarget | null;
}

interface ResizeSession {
  cardSnapshot: CellCardModel;
  startWorld: WorldPoint;
}

function setsEqual(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  if (a === b) return true;
  if (a.size !== b.size) return false;
  for (const item of a) {
    if (!b.has(item)) return false;
  }
  return true;
}

function isUnderCardsFrame(
  cardId: string,
  surfaceById: Readonly<Record<string, CellCardSurfaceData>>,
): boolean {
  const surface = surfaceById[cardId];
  return surface?.kind === "annotation" && surface.variant === "frame";
}

function resolvePortColor(artifactTypeId: string, port?: CellPort): string {
  if (port?.kind === "service") return tokens.colorAccent;
  return artifactTypeColor(artifactTypeId, tokens.colorMuted);
}

export function cellGraphBounds(cards: readonly CellCardModel[]): WorldBounds {
  if (cards.length === 0) {
    return { x: 0, y: 0, width: CELL_SIZE, height: CELL_SIZE };
  }
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const card of cards) {
    const rect = cardWorldRect(card);
    minX = Math.min(minX, rect.x);
    minY = Math.min(minY, rect.y);
    maxX = Math.max(maxX, rect.x + rect.width);
    maxY = Math.max(maxY, rect.y + rect.height);
  }
  return {
    x: minX - CELL_SIZE,
    y: minY - CELL_SIZE * 0.5,
    width: maxX - minX + CELL_SIZE * 2,
    height: maxY - minY + CELL_SIZE,
  };
}

function allCardPorts(
  card: CellCardModel,
  surface: CellCardSurfaceData | undefined,
): readonly CellPort[] {
  if (surface?.kind !== "operator" || !surface.instancePlugGroups?.length) {
    return card.ports;
  }
  const listed = new Set(card.ports.map((p) => p.id));
  const extra: CellPort[] = [];
  for (const group of surface.instancePlugGroups) {
    group.plugs.forEach((plug, index) => {
      const compositeId = `${group.portName}::${plug.plugId}`;
      if (listed.has(plug.plugId) || listed.has(compositeId)) return;
      extra.push({
        id: compositeId,
        name: plug.label,
        direction: "input",
        rowOffset: plugRowOffset(group, index),
        artifactTypeId: group.artifactTypeId,
        shape: group.shape,
      });
    });
  }
  return extra.length > 0 ? [...card.ports, ...extra] : card.ports;
}

function indexGraph(
  graph: CellGraph,
  surfaceById: Readonly<Record<string, CellCardSurfaceData>>,
): GraphIndex {
  const cardsById = new Map<string, CellCardModel>();
  const portsByCardId = new Map<string, Map<string, CellPort>>();
  for (const card of graph.cards) {
    cardsById.set(card.id, card);
    const ports = allCardPorts(card, surfaceById[card.id]);
    portsByCardId.set(
      card.id,
      new Map(ports.map((p) => [cellPortKey(p.direction, p.id), p])),
    );
  }
  // Keyed by `cellPortKey`: an input and an output may share a bare id.
  const connected = new Map<string, Set<string>>();
  const mark = (cardId: string, key: string) => {
    const ids = connected.get(cardId) ?? new Set<string>();
    ids.add(key);
    connected.set(cardId, ids);
  };
  for (const pipe of graph.pipes) {
    mark(pipe.sourceCardId, cellPortKey("output", pipe.sourcePortId));
    mark(pipe.targetCardId, cellPortKey("input", pipe.targetPortId));
  }
  return { cardsById, portsByCardId, connectedPortIdsByCardId: connected };
}

function findPort(
  index: GraphIndex,
  cardId: string,
  portId: string,
  direction: CellPort["direction"],
): PortRef | null {
  const card = index.cardsById.get(cardId);
  const port = index.portsByCardId
    .get(cardId)
    ?.get(cellPortKey(direction, portId));
  return card && port ? { card, port } : null;
}

function portColor(port: CellPort): string {
  return resolvePortColor(port.artifactTypeId, port);
}

function wellKey(
  cardId: string,
  direction: CellPort["direction"],
  portId: string,
): string {
  return `${cardId}:${cellPortKey(direction, portId)}`;
}

/** Adds the port's well unless one is already bored there: one per port. */
function addWell(
  wells: StageWell[],
  keys: Set<string>,
  skip: ReadonlySet<string> | null,
  ref: PortRef,
  centre: WorldPoint,
  exit: CellDir,
  pipeColor: string,
  pipeTwin: boolean,
): void {
  const key = wellKey(ref.card.id, ref.port.direction, ref.port.id);
  if (keys.has(key) || skip?.has(key)) return;
  keys.add(key);
  wells.push({
    key,
    centre,
    exit,
    pipeColor,
    portColor: portColor(ref.port),
    portSequence: ref.port.shape === "many",
    pipeTwin,
  });
}

function restingScene(
  graph: CellGraph,
  index: GraphIndex,
  layout: CellRoutingResult,
  dockedPipeIds: ReadonlySet<string>,
  movingCardIds: ReadonlySet<string>,
  punched: boolean,
): RestingScene {
  const partition = partitionSceneForMovingCards(graph, movingCardIds);
  const pipes: StagePipe[] = [];
  const wells: StageWell[] = [];
  const wellKeys = new Set<string>();
  for (const pipe of partition.restingPipes) {
    if (dockedPipeIds.has(pipe.id)) continue;
    const routed = layout.pipes.get(pipe.id);
    const source = findPort(
      index,
      pipe.sourceCardId,
      pipe.sourcePortId,
      "output",
    );
    const target = findPort(
      index,
      pipe.targetCardId,
      pipe.targetPortId,
      "input",
    );
    if (!routed || !source || !target) continue;
    const color = portColor(source.port);
    const sequence = source.port.shape === "many";
    pipes.push({
      id: pipe.id,
      points: punched
        ? punchedPipePoints(
            routed.points,
            portAnchorCenter(source.card, source.port, true),
            portAnchorCenter(target.card, target.port, true),
          )
        : routed.points,
      color,
      sequence,
      depth: routed.depth,
      disabled: pipe.enabled === false || pipe.incompatible === true,
    });
    const sourceCentre = portWorldCenter(source.card, source.port);
    const targetCentre = portWorldCenter(target.card, target.port);
    addWell(
      wells,
      wellKeys,
      null,
      source,
      sourceCentre,
      routed.sourceExit,
      color,
      sequence,
    );
    addWell(
      wells,
      wellKeys,
      null,
      target,
      targetCentre,
      routed.targetExit,
      color,
      sequence,
    );
  }
  return {
    pipes,
    wells,
    wellKeys,
    attachedPipeIds: partition.attachedPipeIds,
  };
}

/**
 * An orthogonal preview from a port: out along its side for at least a stub,
 * across at the halfway line, then on to the end.
 */
function previewPoints(
  start: WorldPoint,
  side: CellDir,
  end: WorldPoint,
  punched: boolean,
): WorldPoint[] {
  const out = side === "right" ? 1 : -1;
  const ahead = (end.x - start.x) * out;
  // From a punched hole the stub first runs out from under the card to its
  // gutter cell's centre, then keeps the router's own minimum.
  const stub = punched
    ? PUNCHED_PORT_INSET + CELL_SIZE / 2 + CELL_PIPE_STUB_MIN
    : CELL_PIPE_STUB_MIN;
  if (Math.abs(end.y - start.y) < 0.5 && ahead >= stub) {
    return [start, end];
  }
  const reach = start.x + out * stub;
  const halfway = (start.x + end.x) / 2;
  const x = out > 0 ? Math.max(reach, halfway) : Math.min(reach, halfway);
  return [start, { x, y: start.y }, { x, y: end.y }, end];
}

function liveCentre(
  drag: GroupCardDrag,
  index: GraphIndex,
  cardId: string,
  portId: string,
  direction: CellPort["direction"],
  offset: WorldPoint,
): WorldPoint | null {
  const ref = findPort(index, cardId, portId, direction);
  if (!ref) return null;
  return drag.session.movingCardIds.has(cardId)
    ? portWorldCenter(ref.card, ref.port, offset)
    : portWorldCenter(ref.card, ref.port);
}

/** A punched port's centre where it is drawn now, moving with its card or not. */
function liveAnchor(
  drag: GroupCardDrag,
  ref: PortRef,
  offset: WorldPoint,
): WorldPoint {
  return drag.session.movingCardIds.has(ref.card.id)
    ? portAnchorCenter(ref.card, ref.port, true, offset)
    : portAnchorCenter(ref.card, ref.port, true);
}

/** Steps every attached pipe to `now` and draws the moving scene. */
function buildDragFrame(
  drag: GroupCardDrag,
  index: GraphIndex,
  now: number,
): DragFrameState {
  const visualOrigin = drag.cellSettle.current;
  const anchorInitial = drag.session.anchorInitialCell;
  const visualOffset = {
    x: visualOrigin.x - anchorInitial.col * CELL_SIZE,
    y: visualOrigin.y - anchorInitial.row * CELL_SIZE,
  };
  const movingPipes: StagePipe[] = [];
  const movingWells: StageWell[] = [];
  const wellKeys = new Set<string>();
  for (const motion of drag.pipes) {
    if (motion.dockedAtCurrentCell) continue;
    let basePoints = motion.toPoints;
    if (motion.morphing) {
      const progress = (now - motion.morphStartMs) / MORPH_DURATION_MS;
      basePoints = morphPipePoints(
        motion.fromPoints,
        motion.toPoints,
        progress,
      );
      if (progress >= 1) motion.morphing = false;
    }
    const sourceCentre = liveCentre(
      drag,
      index,
      motion.sourceCardId,
      motion.sourcePortId,
      "output",
      visualOffset,
    );
    const targetCentre = liveCentre(
      drag,
      index,
      motion.targetCardId,
      motion.targetPortId,
      "input",
      visualOffset,
    );
    const source = findPort(
      index,
      motion.sourceCardId,
      motion.sourcePortId,
      "output",
    );
    const target = findPort(
      index,
      motion.targetCardId,
      motion.targetPortId,
      "input",
    );
    if (!sourceCentre || !targetCentre || !source || !target) continue;
    const anchored = anchorPipeEndpoints(
      basePoints,
      sourceCentre,
      motion.sourceExit,
      targetCentre,
      motion.targetExit,
    );
    motion.currentPoints = anchored;
    movingPipes.push({
      id: motion.id,
      points: drag.punched
        ? punchedPipePoints(
            anchored,
            liveAnchor(drag, source, visualOffset),
            liveAnchor(drag, target, visualOffset),
          )
        : anchored,
      color: motion.color,
      sequence: motion.sequence,
      depth: motion.depth,
      disabled: motion.disabled,
    });
    addWell(
      movingWells,
      wellKeys,
      drag.restingWellKeys,
      source,
      sourceCentre,
      motion.sourceExit,
      motion.color,
      motion.sequence,
    );
    addWell(
      movingWells,
      wellKeys,
      drag.restingWellKeys,
      target,
      targetCentre,
      motion.targetExit,
      motion.color,
      motion.sequence,
    );
  }

  const ghostBoxes: DragGhostBox[] = [];
  if (!drag.pointerReleased) {
    for (const [cardId, initial] of drag.session.initialCells) {
      const card = index.cardsById.get(cardId);
      if (!card) continue;
      ghostBoxes.push({
        cardId,
        col: initial.col + drag.landingDelta.col,
        row: initial.row + drag.landingDelta.row,
        widthCells: card.widthCells,
        heightCells: card.heightCells,
      });
    }
  }

  return {
    anchorCardId: drag.anchorCardId,
    snappedDelta: drag.session.currentDelta,
    visualOffset,
    showGhostCells: !drag.pointerReleased,
    ghostBoxes,
    movingPipes,
    movingWells,
  };
}

function seedPipeMotions(
  graph: CellGraph,
  index: GraphIndex,
  layout: CellRoutingResult,
  dockedPipeIds: ReadonlySet<string>,
  attachedPipeIds: ReadonlySet<string>,
): PipeMotion[] {
  const motions: PipeMotion[] = [];
  for (const pipe of graph.pipes) {
    if (!attachedPipeIds.has(pipe.id)) continue;
    const source = findPort(
      index,
      pipe.sourceCardId,
      pipe.sourcePortId,
      "output",
    );
    const target = findPort(
      index,
      pipe.targetCardId,
      pipe.targetPortId,
      "input",
    );
    if (!source || !target) continue;
    const routed = layout.pipes.get(pipe.id);
    const fallbackPoints = [
      portWorldCenter(source.card, source.port),
      portWorldCenter(target.card, target.port),
    ];
    const points = routed?.points ?? fallbackPoints;
    motions.push({
      id: pipe.id,
      sourceCardId: pipe.sourceCardId,
      targetCardId: pipe.targetCardId,
      sourcePortId: pipe.sourcePortId,
      targetPortId: pipe.targetPortId,
      color: portColor(source.port),
      sequence: source.port.shape === "many",
      disabled: pipe.enabled === false || pipe.incompatible === true,
      fromPoints: points,
      toPoints: points,
      currentPoints: points,
      sourceExit: routed?.sourceExit ?? "right",
      targetExit: routed?.targetExit ?? "left",
      depth: routed?.depth ?? 0,
      morphStartMs: 0,
      morphing: false,
      dockedAtCurrentCell: dockedPipeIds.has(pipe.id),
    });
  }
  return motions;
}

// ---------------------------------------------------------------------------

export function CellCanvas({
  graph,
  surfaceById = EMPTY_SURFACES,
  look = DEFAULT_CELL_GLASS_LOOK,
  routing = DEFAULT_CELL_ROUTING,
  editable = true,
  selectedCardIds,
  selectedPipeIds,
  inspectedPipeId = null,
  remotePeers = EMPTY_REMOTE_PEERS,
  remoteDragScope,
  fitLeftClearance = 0,
  autoFitOnMount = true,
  dataGraph,
  exposeDebugApi = false,
  onMoveCards,
  onDragCardsProgress,
  onResizeCard,
  onCanConnect,
  onConnect,
  onConnectDropEmpty,
  onRemoveCards,
  onRemovePipes,
  onSelectionChange,
  onPaneClick,
  onSelectEdgeAttachment,
  onOperatorRun,
  onOperatorConfigChange,
  onOperatorAddPlug,
  onOperatorRemovePlug,
  onOperatorToggleAppendix,
  onAnnotationColorChange,
  onArtifactInspect,
  canMergeArtifactCards,
  onMergeArtifactCards,
  onReorderArtifactCardItem,
  onMergeArtifactCardRun,
  onInsertArtifactCardIntoSequence,
  onExtractArtifactCardItem,
  onRemoveArtifactCardItem,
  onUngroupArtifactCard,
  onArtifactImageLoad,
  onCollectionRemoveMember,
  onHandleReady,
  onViewportZoomChange,
  onStatsChange,
  children,
}: CellCanvasProps) {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
  const punched = look.well === "punched";
  const {
    viewport,
    panning,
    zoomAtCenter,
    zoomBy,
    fitRect,
    viewAt,
    screenToWorld,
    worldToScreen,
    onBackgroundPointerDown,
  } = useCellViewport(containerRef, { fitLeftClearance });

  const [store] = React.useState(createCellInteractionStore);
  const selection = React.useSyncExternalStore(
    store.subscribeSelection,
    store.getSelection,
    store.getSelection,
  );
  const marquee = React.useSyncExternalStore(
    store.subscribeMarquee,
    store.getMarquee,
    store.getMarquee,
  );

  const [hoveredPipeId, setHoveredPipeId] = React.useState<string | null>(null);
  const [rerouteCount, setRerouteCount] = React.useState(0);
  const [movingCardIds, setMovingCardIds] =
    React.useState<ReadonlySet<string>>(EMPTY_ID_SET);
  const [draggedCardId, setDraggedCardId] = React.useState<string | null>(null);
  const [dragFrame, setDragFrame] = React.useState<DragFrameState | null>(null);
  const [resizePreview, setResizePreview] =
    React.useState<CellResizeCommit | null>(null);
  const [wiring, setWiring] = React.useState<WiringState | null>(null);
  const [lastConnectDropEmpty, setLastConnectDropEmpty] =
    React.useState<CellConnectDropEmptyEvent | null>(null);
  /** The artifact card a dragged card joins if released now. */
  const [mergeTarget, setMergeTarget] = React.useState<{
    cardId: string;
    itemCount: number;
  } | null>(null);
  /** Cards sliding under a stack they just joined, drawn until they land. */
  const [stackTucks, setStackTucks] = React.useState<readonly StackTuck[]>([]);
  const stackTuckSeqRef = React.useRef(0);
  /** The open spread slot a dragged canvas card inserts into if released now. */
  const [spreadInsertTarget, setSpreadInsertTarget] =
    React.useState<SpreadInsertTarget | null>(null);
  /** The sequence card laid open in place. */
  const [expandedSequenceId, setExpandedSequenceId] = React.useState<
    string | null
  >(null);
  /** Current step offset of the open spread, for external card drops. */
  const [spreadWindowStart, setSpreadWindowStart] = React.useState(0);
  /** How many cards the open spread shows, once a person resized it. */
  const [spreadVisibleCount, setSpreadVisibleCount] = React.useState<
    number | undefined
  >(undefined);
  /** The visible canvas width in world units when the spread opened. */
  const [spreadViewportWidth, setSpreadViewportWidth] = React.useState<
    number | undefined
  >(undefined);

  const effectiveGraph = React.useMemo<CellGraph>(() => {
    if (!resizePreview) return graph;
    let changed = false;
    const cards = graph.cards.map((card) => {
      if (card.id !== resizePreview.cardId) return card;
      if (
        card.widthCells === resizePreview.widthCells &&
        card.heightCells === resizePreview.heightCells
      ) {
        return card;
      }
      changed = true;
      // An artifact card's output rides its bottom-right corner, so its port
      // and pipe follow the grip while the resize is live.
      const outputRow = artifactCardOutputRow(resizePreview.heightCells);
      return {
        ...card,
        widthCells: resizePreview.widthCells,
        heightCells: resizePreview.heightCells,
        ports:
          card.kind === "artifact"
            ? card.ports.map((port) =>
                port.id === ARTIFACT_CARD_OUTPUT_PORT_ID &&
                port.rowOffset !== outputRow
                  ? { ...port, rowOffset: outputRow }
                  : port,
              )
            : card.ports,
      };
    });
    return changed ? { ...graph, cards } : graph;
  }, [graph, resizePreview]);

  const remoteCardPositions = useRemoteCellDrag(
    effectiveGraph.cards,
    remotePeers,
    movingCardIds,
    remoteDragScope,
  );

  const viewportApi = React.useMemo<CellViewportApi>(
    () => ({
      viewport,
      screenToWorld,
      worldToScreen,
      zoomAtCenter,
      zoomBy,
      fitRect,
      viewAt,
    }),
    [
      viewport,
      screenToWorld,
      worldToScreen,
      zoomAtCenter,
      zoomBy,
      fitRect,
      viewAt,
    ],
  );

  const { underCardsFrames, foregroundCards } = React.useMemo(() => {
    const frames: CellCardModel[] = [];
    const foreground: CellCardModel[] = [];
    for (const card of effectiveGraph.cards) {
      if (isUnderCardsFrame(card.id, surfaceById)) {
        frames.push(card);
      } else {
        foreground.push(card);
      }
    }
    return { underCardsFrames: frames, foregroundCards: foreground };
  }, [effectiveGraph.cards, surfaceById]);

  const docking = React.useMemo(
    () =>
      detectCellDockedJoins(
        { cards: foregroundCards, pipes: effectiveGraph.pipes },
        resolvePortColor,
        { punched },
      ),
    [foregroundCards, effectiveGraph.pipes, punched],
  );

  const restingLayout = React.useMemo(
    () =>
      routeCellGraph(
        { cards: foregroundCards, pipes: docking.routablePipes },
        routing,
      ),
    [foregroundCards, docking.routablePipes, routing],
  );

  const index = React.useMemo(
    () => indexGraph(effectiveGraph, surfaceById),
    [effectiveGraph, surfaceById],
  );

  const resting = React.useMemo(
    () =>
      restingScene(
        effectiveGraph,
        index,
        restingLayout,
        docking.dockedPipeIds,
        movingCardIds,
        punched,
      ),
    [
      effectiveGraph,
      index,
      restingLayout,
      docking.dockedPipeIds,
      movingCardIds,
      punched,
    ],
  );

  const activePipeIds = React.useMemo(() => {
    const ids = new Set<string>(selection.pipeIds);
    if (hoveredPipeId) ids.add(hoveredPipeId);
    if (inspectedPipeId) ids.add(inspectedPipeId);
    return ids;
  }, [hoveredPipeId, inspectedPipeId, selection.pipeIds]);

  const pipeAttachments = React.useMemo(
    () =>
      solvePipeAttachmentAnchors({
        cards: foregroundCards,
        pipes: effectiveGraph.pipes,
        routedPipes: restingLayout.pipes,
        dockedJoins: docking.dockedJoins,
        resolveColor: resolvePortColor,
        activePipeIds,
      }),
    [
      activePipeIds,
      foregroundCards,
      effectiveGraph.pipes,
      restingLayout.pipes,
      docking.dockedJoins,
    ],
  );

  const visibleDockedJoins = React.useMemo<readonly CellDockedJoin[]>(() => {
    if (movingCardIds.size === 0) return docking.dockedJoins;
    return docking.dockedJoins.filter(
      (join) =>
        !movingCardIds.has(join.sourceCardId) &&
        !movingCardIds.has(join.targetCardId),
    );
  }, [docking.dockedJoins, movingCardIds]);

  const visiblePipeAttachments = React.useMemo(() => {
    if (movingCardIds.size === 0) return pipeAttachments;
    return pipeAttachments.filter(
      (att) => !resting.attachedPipeIds.has(att.pipeId),
    );
  }, [pipeAttachments, movingCardIds, resting.attachedPipeIds]);

  // Refs synced in layout effect keep gesture handlers stable and prevent
  // 60fps parent re-renders.
  const graphRef = React.useRef(effectiveGraph);
  const surfaceByIdRef = React.useRef(surfaceById);
  const foregroundCardsRef = React.useRef(foregroundCards);
  const indexRef = React.useRef(index);
  const dockingRef = React.useRef(docking);
  const layoutRef = React.useRef(restingLayout);
  const routingRef = React.useRef(routing);
  const viewportRef = React.useRef(viewport);
  const rerouteRef = React.useRef(rerouteCount);
  const draggedRef = React.useRef(draggedCardId);
  const resizePreviewRef = React.useRef(resizePreview);
  const editableRef = React.useRef(editable);
  const punchedRef = React.useRef(punched);
  const stackLookRef = React.useRef({
    stackStyle: look.stackStyle,
    corners: look.corners,
  });
  const lastDropEmptyRef = React.useRef(lastConnectDropEmpty);
  const resizeSessionRef = React.useRef<ResizeSession | null>(null);

  const onMoveCardsRef = React.useRef(onMoveCards);
  const onDragCardsProgressRef = React.useRef(onDragCardsProgress);
  const onResizeCardRef = React.useRef(onResizeCard);
  const onCanConnectRef = React.useRef(onCanConnect);
  const onConnectRef = React.useRef(onConnect);
  const onConnectDropEmptyRef = React.useRef(onConnectDropEmpty);
  const onRemoveCardsRef = React.useRef(onRemoveCards);
  const onRemovePipesRef = React.useRef(onRemovePipes);
  const onSelectionChangeRef = React.useRef(onSelectionChange);
  const onPaneClickRef = React.useRef(onPaneClick);
  const onSelectEdgeAttachmentRef = React.useRef(onSelectEdgeAttachment);
  const canMergeArtifactCardsRef = React.useRef(canMergeArtifactCards);
  const onMergeArtifactCardsRef = React.useRef(onMergeArtifactCards);
  const onInsertArtifactCardIntoSequenceRef = React.useRef(
    onInsertArtifactCardIntoSequence,
  );
  const expandedSequenceIdRef = React.useRef(expandedSequenceId);
  const openSpreadRef = React.useRef<{
    card: CellCardModel;
    layout: OpenSequenceSpreadLayout;
    windowStart: number;
    itemCount: number;
  } | null>(null);
  const onViewportZoomChangeRef = React.useRef(onViewportZoomChange);
  const onStatsChangeRef = React.useRef(onStatsChange);

  React.useLayoutEffect(() => {
    graphRef.current = effectiveGraph;
    surfaceByIdRef.current = surfaceById;
    foregroundCardsRef.current = foregroundCards;
    indexRef.current = index;
    dockingRef.current = docking;
    layoutRef.current = restingLayout;
    routingRef.current = routing;
    viewportRef.current = viewport;
    rerouteRef.current = rerouteCount;
    draggedRef.current = draggedCardId;
    resizePreviewRef.current = resizePreview;
    editableRef.current = editable;
    punchedRef.current = punched;
    stackLookRef.current = {
      stackStyle: look.stackStyle,
      corners: look.corners,
    };
    lastDropEmptyRef.current = lastConnectDropEmpty;

    onMoveCardsRef.current = onMoveCards;
    onDragCardsProgressRef.current = onDragCardsProgress;
    onResizeCardRef.current = onResizeCard;
    onCanConnectRef.current = onCanConnect;
    onConnectRef.current = onConnect;
    onConnectDropEmptyRef.current = onConnectDropEmpty;
    onRemoveCardsRef.current = onRemoveCards;
    onRemovePipesRef.current = onRemovePipes;
    onSelectionChangeRef.current = onSelectionChange;
    onPaneClickRef.current = onPaneClick;
    onSelectEdgeAttachmentRef.current = onSelectEdgeAttachment;
    canMergeArtifactCardsRef.current = canMergeArtifactCards;
    onMergeArtifactCardsRef.current = onMergeArtifactCards;
    onInsertArtifactCardIntoSequenceRef.current =
      onInsertArtifactCardIntoSequence;
    expandedSequenceIdRef.current = expandedSequenceId;
    onViewportZoomChangeRef.current = onViewportZoomChange;
    onStatsChangeRef.current = onStatsChange;
  });

  const cancelGestureRef = React.useRef<(() => void) | null>(null);
  React.useEffect(() => {
    const gesture = cancelGestureRef;
    return () => gesture.current?.();
  }, []);

  const commitSelection = React.useCallback(
    (next: { cardIds?: Iterable<string>; pipeIds?: Iterable<string> }) => {
      const before = store.getSelection();
      const nextCards = new Set(next.cardIds ?? []);
      const nextPipes = new Set(next.pipeIds ?? []);
      if (
        setsEqual(before.cardIds, nextCards) &&
        setsEqual(before.pipeIds, nextPipes)
      ) {
        return;
      }
      store.setSelection({ cardIds: nextCards, pipeIds: nextPipes });
      onSelectionChangeRef.current?.(store.getSelection());
    },
    [store],
  );

  const toggleCardSelection = React.useCallback(
    (cardId: string) => {
      store.toggleCardSelection(cardId);
      onSelectionChangeRef.current?.(store.getSelection());
    },
    [store],
  );

  const clearSelection = React.useCallback(() => {
    const before = store.getSelection();
    if (before.cardIds.size === 0 && before.pipeIds.size === 0) return;
    store.clearSelection();
    onSelectionChangeRef.current?.(store.getSelection());
  }, [store]);

  // Sync controlled selection props into store without re-emitting onSelectionChange.
  React.useEffect(() => {
    if (selectedCardIds === undefined && selectedPipeIds === undefined) return;
    const current = store.getSelection();
    const nextCards = selectedCardIds ?? current.cardIds;
    const nextPipes = selectedPipeIds ?? current.pipeIds;
    if (
      setsEqual(current.cardIds, nextCards) &&
      setsEqual(current.pipeIds, nextPipes)
    ) {
      return;
    }
    store.setSelection({ cardIds: nextCards, pipeIds: nextPipes });
  }, [selectedCardIds, selectedPipeIds, store]);

  // Sync remote peers into the per-card interaction store.
  React.useEffect(() => {
    store.setRemotePeers(remotePeers);
  }, [remotePeers, store]);

  const fitGraph = React.useCallback(
    (paddingRatio?: number, maxZoom?: number) => {
      fitRect(cellGraphBounds(graphRef.current.cards), paddingRatio, maxZoom);
    },
    [fitRect],
  );

  const fitCards = React.useCallback(
    (cardIds: readonly string[], paddingRatio?: number, maxZoom?: number) => {
      const idSet = new Set(cardIds);
      const subset = graphRef.current.cards.filter((card) =>
        idSet.has(card.id),
      );
      if (subset.length === 0) {
        fitRect(cellGraphBounds(graphRef.current.cards), paddingRatio, maxZoom);
        return;
      }
      fitRect(cellGraphBounds(subset), paddingRatio, maxZoom);
    },
    [fitRect],
  );

  const hasAutoFittedRef = React.useRef(false);
  React.useLayoutEffect(() => {
    if (!autoFitOnMount || hasAutoFittedRef.current) return;
    if (effectiveGraph.cards.length === 0) return;
    hasAutoFittedRef.current = true;
    fitRect(cellGraphBounds(effectiveGraph.cards));
  }, [autoFitOnMount, effectiveGraph.cards, fitRect]);

  const handle = React.useMemo<CellCanvasHandle>(
    () => ({
      viewportHandle: {
        getViewport: () => ({ ...viewportRef.current }),
        fitBounds: (bounds, paddingRatio, maxZoom) =>
          fitRect(bounds, paddingRatio, maxZoom),
        screenToWorld,
        worldToScreen,
        zoomBy,
      },
      fitGraph,
      fitCards,
      zoomAtCenter,
      zoomBy,
      viewAt,
      cancelGesture: () => cancelGestureRef.current?.(),
    }),
    [
      fitCards,
      fitGraph,
      fitRect,
      screenToWorld,
      viewAt,
      worldToScreen,
      zoomAtCenter,
      zoomBy,
    ],
  );

  React.useEffect(() => {
    onHandleReady?.(handle);
    return () => {
      onHandleReady?.(null);
    };
  }, [handle, onHandleReady]);

  React.useEffect(() => {
    onViewportZoomChangeRef.current?.(viewport.zoom);
  }, [viewport.zoom]);

  React.useEffect(() => {
    onStatsChangeRef.current?.({
      cards: effectiveGraph.cards.length,
      pipes: effectiveGraph.pipes.length,
      deepCount: restingLayout.deepCount,
      reroutes: rerouteCount,
      draggedCardId,
    });
  }, [
    effectiveGraph.cards.length,
    effectiveGraph.pipes.length,
    restingLayout.deepCount,
    rerouteCount,
    draggedCardId,
  ]);

  const onPipeHover = React.useCallback(
    (pipeId: string | null) => {
      setHoveredPipeId(pipeId);
      store.setHoveredPipe(pipeId);
    },
    [store],
  );

  const onPipeSelect = React.useCallback(
    (id: string) => {
      commitSelection({ cardIds: [], pipeIds: [id] });
    },
    [commitSelection],
  );

  const onRemovePipeAttachment = React.useCallback(
    (pipeId: string) => {
      if (!editableRef.current) return;
      onRemovePipesRef.current?.([pipeId]);
      const currentPipes = new Set(store.getSelection().pipeIds);
      if (currentPipes.delete(pipeId)) {
        commitSelection({
          cardIds: store.getSelection().cardIds,
          pipeIds: currentPipes,
        });
      }
      setHoveredPipeId((hovered) => (hovered === pipeId ? null : hovered));
      store.setHoveredPipe(null);
    },
    [commitSelection, store],
  );

  const onRemoveSingleCard = React.useCallback(
    (cardId: string) => {
      if (!editableRef.current) return;
      onRemoveCardsRef.current?.([cardId]);
      const currentSelection = store.getSelection();
      const cardIds = new Set(currentSelection.cardIds);
      cardIds.delete(cardId);
      commitSelection({ cardIds, pipeIds: currentSelection.pipeIds });
      store.setHoveredCard(null);
    },
    [commitSelection, store],
  );

  /**
   * Starts a tuck for each card that is joining a stack, when motion is on:
   * each slides from `from` under `target` into back `slot`.
   */
  const startStackTucks = React.useCallback(
    (
      joins: readonly {
        card: CellCardModel;
        from: WorldPoint;
        target: CellCardModel;
        slot: number;
        surface: CellCardSurfaceData | undefined;
      }[],
    ) => {
      if (joins.length === 0 || !shouldAnimateMotion()) return;
      const { stackStyle, corners } = stackLookRef.current;
      const next = joins.map((join): StackTuck => {
        stackTuckSeqRef.current += 1;
        return {
          id: `tuck-${stackTuckSeqRef.current}`,
          cardId: join.card.id,
          from: join.from,
          fromWidthCells: join.card.widthCells,
          fromHeightCells: join.card.heightCells,
          to: cellToWorldOrigin(join.target.col, join.target.row),
          toWidthCells: join.target.widthCells,
          toHeightCells: join.target.heightCells,
          imageUrl:
            join.surface?.kind === "artifact"
              ? (join.surface.imageUrl ?? null)
              : null,
          slot: join.slot,
          stackStyle,
          corners,
        };
      });
      setStackTucks((current) => [...current, ...next]);
    },
    [],
  );
  const onStackTuckSettled = React.useCallback((id: string) => {
    setStackTucks((current) => current.filter((tuck) => tuck.id !== id));
  }, []);
  const tuckingCardIds = React.useMemo(
    () => new Set(stackTucks.map((tuck) => tuck.cardId)),
    [stackTucks],
  );
  /** `Stack N` on a flush run: every card after the first slides under it. */
  const mergeArtifactRun = (chosen: ArtifactMergeSuggestion) => {
    const anchor = index.cardsById.get(chosen.cardIds[0] ?? "");
    if (anchor) {
      const joins = [];
      for (const [position, id] of chosen.cardIds.slice(1).entries()) {
        const card = index.cardsById.get(id);
        if (!card) continue;
        joins.push({
          card,
          from: cellToWorldOrigin(card.col, card.row),
          target: anchor,
          slot: Math.min(position, 1),
          surface: surfaceById[id],
        });
      }
      startStackTucks(joins);
    }
    onMergeArtifactCardRun?.(chosen.cardIds, chosen.targetCardId);
  };

  const onCardPointerDown = React.useCallback(
    (cardId: string, event: React.PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return;
      event.stopPropagation();
      cancelGestureRef.current?.();

      const graphAtPickup = graphRef.current;
      const surfacesAtPickup = surfaceByIdRef.current;
      const indexAtPickup = indexRef.current;
      const routingAtPickup = routingRef.current;
      const dockingAtPickup = dockingRef.current;
      const card = indexAtPickup.cardsById.get(cardId);
      if (!card) return;

      const shiftPressed = event.shiftKey;
      const wasSelectedBefore = store.getSelection().cardIds.has(cardId);
      if (shiftPressed) {
        toggleCardSelection(cardId);
      } else if (!wasSelectedBefore) {
        commitSelection({ cardIds: [cardId], pipeIds: [] });
      }

      if (!editableRef.current) return;

      const draggingFrame = isUnderCardsFrame(cardId, surfacesAtPickup);
      const rawSelected = store.getSelection().cardIds;
      const effectiveSelection = draggingFrame
        ? new Set([cardId])
        : new Set(
            [...rawSelected].filter(
              (id) => !isUnderCardsFrame(id, surfacesAtPickup),
            ),
          );
      if (!effectiveSelection.has(cardId)) {
        effectiveSelection.add(cardId);
      }

      const pointerId = event.pointerId;
      const originWorld = cellToWorldOrigin(card.col, card.row);
      const pointer = screenToWorld(event.clientX, event.clientY);
      const session = createGroupDragSession(
        graphAtPickup.cards,
        effectiveSelection,
        cardId,
        pointer,
      );

      const drag: GroupCardDrag = {
        anchorCardId: cardId,
        session,
        startClient: { x: event.clientX, y: event.clientY },
        movedBeyondClick: false,
        pointerReleased: false,
        cellSettle: createCardSettle(originWorld),
        landingDelta: { col: 0, row: 0 },
        attachedPipeIds: EMPTY_ID_SET,
        restingWellKeys: EMPTY_ID_SET,
        pipes: [],
        punched: punchedRef.current,
      };
      let frame = 0;
      const openSpreadAtPickup = openSpreadRef.current;
      const foregroundAtPickup = graphAtPickup.cards.filter(
        (c) => !isUnderCardsFrame(c.id, surfacesAtPickup),
      );
      // While a sequence is spread open, non-inserting drags treat its full
      // expanded footprint as occupied space so cards never land over it.
      const obstacleForegroundAtPickup = openSpreadAtPickup
        ? foregroundAtPickup.map((c) =>
            c.id === openSpreadAtPickup.card.id
              ? {
                  ...c,
                  col: openSpreadAtPickup.layout.startCol,
                  row: openSpreadAtPickup.layout.row,
                  widthCells: openSpreadAtPickup.layout.totalCols,
                  heightCells: openSpreadAtPickup.layout.heightCells,
                }
              : c,
          )
        : foregroundAtPickup;
      // A lone artifact card may be dropped onto another card or directly into
      // an open sequence spread at a specific slot.
      const canMergeAtPickup = canMergeArtifactCardsRef.current;
      const mergeable =
        effectiveSelection.size === 1 &&
        canMergeAtPickup !== undefined &&
        (onMergeArtifactCardsRef.current !== undefined ||
          onInsertArtifactCardIntoSequenceRef.current !== undefined) &&
        artifactCardItemCount(surfacesAtPickup[cardId]) !== null;
      let mergeTargetId: string | null = null;
      let spreadInsert: SpreadInsertTarget | null = null;

      function trackMergeTarget(at: WorldPoint) {
        if (!mergeable || !canMergeAtPickup) return;
        if (
          openSpreadAtPickup &&
          openSpreadAtPickup.card.id !== cardId &&
          onInsertArtifactCardIntoSequenceRef.current !== undefined &&
          canMergeAtPickup(cardId, openSpreadAtPickup.card.id)
        ) {
          // The spread may page (wheel) mid-drag, so read its live window.
          const current = openSpreadRef.current;
          const live =
            current?.card.id === openSpreadAtPickup.card.id
              ? current
              : openSpreadAtPickup;
          const hit = findSpreadInsertTarget({
            spreadCardId: openSpreadAtPickup.card.id,
            layout: openSpreadAtPickup.layout,
            windowStart: live.windowStart,
            itemCount: live.itemCount,
            cardWidthCells: openSpreadAtPickup.card.widthCells,
            point: at,
          });
          if (hit) {
            if (mergeTargetId !== null) {
              mergeTargetId = null;
              setMergeTarget(null);
            }
            if (
              spreadInsert?.spreadCardId !== hit.spreadCardId ||
              spreadInsert.slot !== hit.slot ||
              spreadInsert.insertIndex !== hit.insertIndex
            ) {
              spreadInsert = hit;
              setSpreadInsertTarget(hit);
            }
            return;
          }
        }
        if (spreadInsert !== null) {
          spreadInsert = null;
          setSpreadInsertTarget(null);
        }
        if (onMergeArtifactCardsRef.current === undefined) return;
        const mergeCandidates = openSpreadAtPickup
          ? foregroundAtPickup.filter(
              (c) => c.id !== openSpreadAtPickup.card.id,
            )
          : foregroundAtPickup;
        const next = findArtifactMergeTarget(
          mergeCandidates,
          surfacesAtPickup,
          cardId,
          at,
          canMergeAtPickup,
        );
        if (next === mergeTargetId) return;
        mergeTargetId = next;
        setMergeTarget(
          next
            ? {
                cardId: next,
                itemCount:
                  (artifactCardItemCount(surfacesAtPickup[cardId]) ?? 1) +
                  (artifactCardItemCount(surfacesAtPickup[next]) ?? 1),
              }
            : null,
        );
      }

      function resolveLanding(delta: CellCoord): CellCoord {
        if (draggingFrame) return delta;
        return resolveNonOverlappingDelta(
          obstacleForegroundAtPickup,
          drag.session.movingCardIds,
          delta,
        );
      }

      function currentMoves(): CellCardMove[] {
        const moves: CellCardMove[] = [];
        for (const [id, initial] of drag.session.initialCells) {
          moves.push({
            cardId: id,
            col: initial.col + drag.landingDelta.col,
            row: initial.row + drag.landingDelta.row,
          });
        }
        return moves;
      }

      const schedule = () => {
        if (frame === 0) frame = requestAnimationFrame(tick);
      };

      function tick() {
        frame = 0;
        const now = performance.now();
        drag.cellSettle = stepCardSettle(drag.cellSettle, now);
        const next = buildDragFrame(drag, indexAtPickup, now);
        const morphing = drag.pipes.some((motion) => motion.morphing);
        if (drag.pointerReleased && !drag.cellSettle.active && !morphing) {
          finish();
          return;
        }
        setDragFrame(next);
        if (drag.pointerReleased || drag.cellSettle.active || morphing) {
          schedule();
        }
      }

      function finish() {
        stop();
        onDragCardsProgressRef.current?.(null);
        const finalDelta = drag.landingDelta;
        if (finalDelta.col !== 0 || finalDelta.row !== 0) {
          onMoveCardsRef.current?.(currentMoves());
        }
        store.setDraggingCards([]);
        setMovingCardIds(EMPTY_ID_SET);
        setDraggedCardId(null);
        setDragFrame(null);
      }

      function activate() {
        drag.movedBeyondClick = true;
        drag.cellSettle = createCardSettle(originWorld);
        drag.landingDelta = resolveLanding(drag.session.currentDelta);
        const split = restingScene(
          graphAtPickup,
          indexAtPickup,
          layoutRef.current,
          dockingAtPickup.dockedPipeIds,
          drag.session.movingCardIds,
          drag.punched,
        );
        drag.attachedPipeIds = split.attachedPipeIds;
        drag.restingWellKeys = split.wellKeys;
        drag.pipes = seedPipeMotions(
          graphAtPickup,
          indexAtPickup,
          layoutRef.current,
          dockingAtPickup.dockedPipeIds,
          split.attachedPipeIds,
        );
        onDragCardsProgressRef.current?.(currentMoves());
      }

      function onMove(move: PointerEvent) {
        if (move.pointerId !== pointerId || drag.pointerReleased) return;
        let activated = false;
        if (!drag.movedBeyondClick) {
          const travelled = Math.hypot(
            move.clientX - drag.startClient.x,
            move.clientY - drag.startClient.y,
          );
          if (travelled < DRAG_THRESHOLD_PX) return;
          activate();
          activated = true;
        }
        const now = performance.now();
        const at = screenToWorld(move.clientX, move.clientY);
        trackMergeTarget(at);
        const step = updateGroupDragSession(
          drag.session,
          graphAtPickup.cards,
          at,
        );
        drag.session = step.session;
        if (step.changedCell) {
          drag.landingDelta = resolveLanding(step.snappedDelta);
          onDragCardsProgressRef.current?.(currentMoves());
          setRerouteCount((count) => count + 1);
          const anchorTarget = {
            col: drag.session.anchorInitialCell.col + step.snappedDelta.col,
            row: drag.session.anchorInitialCell.row + step.snappedDelta.row,
          };
          drag.cellSettle = retargetCardSettle(
            drag.cellSettle,
            cellToWorldOrigin(anchorTarget.col, anchorTarget.row),
            now,
          );
          const movedForeground = step.movedCards.filter(
            (c) => !isUnderCardsFrame(c.id, surfacesAtPickup),
          );
          const movedDocking = detectCellDockedJoins(
            { cards: movedForeground, pipes: graphAtPickup.pipes },
            resolvePortColor,
            { punched: punchedRef.current },
          );
          const rerouted = routeCellGraph(
            { cards: movedForeground, pipes: movedDocking.routablePipes },
            routingAtPickup,
            drag.attachedPipeIds,
          );
          for (const motion of drag.pipes) {
            if (movedDocking.dockedPipeIds.has(motion.id)) {
              motion.dockedAtCurrentCell = true;
              motion.morphing = false;
              continue;
            }
            motion.dockedAtCurrentCell = false;
            const routed = rerouted.pipes.get(motion.id);
            if (!routed) continue;
            motion.fromPoints = motion.currentPoints;
            motion.toPoints = routed.points;
            motion.sourceExit = routed.sourceExit;
            motion.targetExit = routed.targetExit;
            motion.depth = routed.depth;
            motion.morphStartMs = now;
            motion.morphing = true;
          }
        }
        if (activated) {
          store.setDraggingCards(drag.session.movingCardIds);
          setMovingCardIds(drag.session.movingCardIds);
          setDraggedCardId(cardId);
          setDragFrame(buildDragFrame(drag, indexAtPickup, now));
        }
        schedule();
      }

      function onUp(up: PointerEvent) {
        if (up.pointerId !== pointerId || drag.pointerReleased) return;
        if (!drag.movedBeyondClick) {
          stop();
          if (!shiftPressed && wasSelectedBefore) {
            commitSelection({ cardIds: [cardId], pipeIds: [] });
          }
          return;
        }
        if (spreadInsert) {
          // Released over an open spread: insert at the hovered slot index.
          const target = spreadInsert;
          cancel();
          onInsertArtifactCardIntoSequenceRef.current?.(
            cardId,
            target.spreadCardId,
            target.insertIndex,
          );
          return;
        }
        if (mergeTargetId) {
          // Released over a sequence: the card joins it instead of landing,
          // sliding from where it was let go under the stack's top card.
          const target = mergeTargetId;
          const released = stepCardSettle(
            drag.cellSettle,
            performance.now(),
          ).current;
          const draggedCard = indexAtPickup.cardsById.get(cardId);
          const targetCard = indexAtPickup.cardsById.get(target);
          if (draggedCard && targetCard) {
            startStackTucks([
              {
                card: draggedCard,
                from: released,
                target: targetCard,
                slot: 0,
                surface: surfacesAtPickup[cardId],
              },
            ]);
          }
          cancel();
          onMergeArtifactCardsRef.current?.(cardId, target, "target-first");
          return;
        }
        const now = performance.now();
        drag.pointerReleased = true;
        const anchorTarget = {
          col: drag.session.anchorInitialCell.col + drag.landingDelta.col,
          row: drag.session.anchorInitialCell.row + drag.landingDelta.row,
        };
        drag.cellSettle = retargetCardSettle(
          drag.cellSettle,
          cellToWorldOrigin(anchorTarget.col, anchorTarget.row),
          now,
        );
        schedule();
      }

      function stop() {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onUp);
        if (frame !== 0) cancelAnimationFrame(frame);
        frame = 0;
        if (cancelGestureRef.current === cancel) {
          cancelGestureRef.current = null;
        }
      }

      function cancel() {
        stop();
        if (spreadInsert) {
          spreadInsert = null;
          setSpreadInsertTarget(null);
        }
        if (mergeTargetId) {
          mergeTargetId = null;
          setMergeTarget(null);
        }
        if (drag.movedBeyondClick) {
          onDragCardsProgressRef.current?.(null);
          store.setDraggingCards([]);
          setMovingCardIds(EMPTY_ID_SET);
          setDraggedCardId(null);
          setDragFrame(null);
        }
      }

      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
      cancelGestureRef.current = cancel;
    },
    [
      commitSelection,
      screenToWorld,
      startStackTucks,
      store,
      toggleCardSelection,
    ],
  );

  const onPortPointerDown = React.useCallback(
    (
      cardId: string,
      port: CellPort,
      event: React.PointerEvent<HTMLButtonElement>,
    ) => {
      if (event.button !== 0 || !editableRef.current) return;
      event.stopPropagation();
      cancelGestureRef.current?.();
      const pointerId = event.pointerId;
      const wanted = port.direction === "output" ? "input" : "output";
      let state: WiringState | null = null;

      const track = (clientX: number, clientY: number) => {
        const cursor = screenToWorld(clientX, clientY);
        let target: WireTarget | null = null;
        let nearest = WIRE_SNAP_RADIUS;
        for (const other of graphRef.current.cards) {
          if (other.id === cardId) continue;
          const ports = allCardPorts(other, surfaceByIdRef.current[other.id]);
          for (const candidate of ports) {
            if (candidate.direction !== wanted) continue;
            if (onCanConnectRef.current) {
              const fromOutput = port.direction === "output";
              const normalized: CellConnectionEnds = {
                sourceCardId: fromOutput ? cardId : other.id,
                sourcePortId: fromOutput ? port.id : candidate.id,
                targetCardId: fromOutput ? other.id : cardId,
                targetPortId: fromOutput ? candidate.id : port.id,
              };
              if (!onCanConnectRef.current(normalized)) continue;
            }
            const centre = portAnchorCenter(
              other,
              candidate,
              punchedRef.current,
            );
            const distance = Math.hypot(
              centre.x - cursor.x,
              centre.y - cursor.y,
            );
            if (distance <= nearest) {
              nearest = distance;
              target = { cardId: other.id, port: candidate, centre };
            }
          }
        }
        state = { fromCardId: cardId, fromPort: port, cursor, target };
        store.setActivePortKey(
          target
            ? wellKey(target.cardId, target.port.direction, target.port.id)
            : null,
        );
        setWiring(state);
      };

      function onMove(move: PointerEvent) {
        if (move.pointerId === pointerId) track(move.clientX, move.clientY);
      }

      function onUp(up: PointerEvent) {
        if (up.pointerId !== pointerId) return;
        const current = state;
        const target = up.type === "pointerup" ? current?.target : null;
        stop();
        if (!target) {
          if (up.type === "pointerup" && current) {
            const dropEvent: CellConnectDropEmptyEvent = {
              sourceCardId: cardId,
              sourcePortId: port.id,
              direction:
                port.direction === "output" ? "downstream" : "upstream",
              worldPoint: current.cursor,
              targetCell: {
                col: Math.floor(current.cursor.x / CELL_SIZE),
                row: Math.floor(current.cursor.y / CELL_SIZE),
              },
              clientPoint: { x: up.clientX, y: up.clientY },
            };
            lastDropEmptyRef.current = dropEvent;
            setLastConnectDropEmpty(dropEvent);
            if (window.__cellCanvas) {
              window.__cellCanvas.lastConnectDropEmpty = dropEvent;
            }
            onConnectDropEmptyRef.current?.(dropEvent);
          }
          return;
        }
        const fromOutput = port.direction === "output";
        const ends: CellConnectionEnds = {
          sourceCardId: fromOutput ? cardId : target.cardId,
          sourcePortId: fromOutput ? port.id : target.port.id,
          targetCardId: fromOutput ? target.cardId : cardId,
          targetPortId: fromOutput ? target.port.id : port.id,
        };
        onConnectRef.current?.(ends);
      }

      function stop() {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onUp);
        if (cancelGestureRef.current === stop) cancelGestureRef.current = null;
        store.setActivePortKey(null);
        setWiring(null);
      }

      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
      cancelGestureRef.current = stop;
      track(event.clientX, event.clientY);
    },
    [screenToWorld, store],
  );

  const onResizeStart = React.useCallback(
    (
      cardId: string,
      _edge: CellResizeEdge,
      event: React.PointerEvent<HTMLDivElement>,
    ) => {
      if (!editableRef.current) return;
      cancelGestureRef.current?.();
      const card = indexRef.current.cardsById.get(cardId);
      if (!card) return;
      resizeSessionRef.current = {
        cardSnapshot: card,
        startWorld: screenToWorld(event.clientX, event.clientY),
      };
      const initialPreview: CellResizeCommit = {
        cardId,
        widthCells: card.widthCells,
        heightCells: card.heightCells,
      };
      resizePreviewRef.current = initialPreview;
      setResizePreview(initialPreview);
      store.setResizingCard(cardId);
    },
    [screenToWorld, store],
  );

  const onResizeMove = React.useCallback(
    (
      cardId: string,
      edge: CellResizeEdge,
      event: React.PointerEvent<HTMLDivElement>,
    ) => {
      const session = resizeSessionRef.current;
      if (!session || session.cardSnapshot.id !== cardId) return;
      const currentWorld = screenToWorld(event.clientX, event.clientY);
      const commit = computeCellResize(
        session.cardSnapshot,
        edge,
        session.startWorld,
        currentWorld,
      );
      const currentPreview = resizePreviewRef.current;
      if (
        currentPreview &&
        currentPreview.cardId === commit.cardId &&
        currentPreview.widthCells === commit.widthCells &&
        currentPreview.heightCells === commit.heightCells
      ) {
        return;
      }
      setRerouteCount((count) => count + 1);
      resizePreviewRef.current = commit;
      setResizePreview(commit);
    },
    [screenToWorld],
  );

  const onResizeEnd = React.useCallback(
    (
      cardId: string,
      edge: CellResizeEdge,
      event: React.PointerEvent<HTMLDivElement>,
    ) => {
      const session = resizeSessionRef.current;
      resizeSessionRef.current = null;
      resizePreviewRef.current = null;
      setResizePreview(null);
      store.setResizingCard(null);
      if (!session || session.cardSnapshot.id !== cardId) return;
      const currentWorld = screenToWorld(event.clientX, event.clientY);
      const commit = computeCellResize(
        session.cardSnapshot,
        edge,
        session.startWorld,
        currentWorld,
      );
      if (
        commit.widthCells === session.cardSnapshot.widthCells &&
        commit.heightCells === session.cardSnapshot.heightCells
      ) {
        return;
      }
      setRerouteCount((count) => count + 1);
      onResizeCardRef.current?.(commit);
    },
    [screenToWorld, store],
  );

  const onRootPointerDown = React.useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0 && event.button !== 1) return;
      if (event.shiftKey && event.button === 0) {
        event.preventDefault();
        event.stopPropagation();
        cancelGestureRef.current?.();
        const pointerId = event.pointerId;
        const start = screenToWorld(event.clientX, event.clientY);
        store.setMarquee({ start, current: start });

        function onMove(move: PointerEvent) {
          if (move.pointerId !== pointerId) return;
          const current = screenToWorld(move.clientX, move.clientY);
          const rect = { start, current };
          store.setMarquee(rect);
          const cardIds = cardsInMarqueeRect(
            foregroundCardsRef.current,
            rect,
            "intersect",
          );
          const pipeIds = pipesInMarqueeRect(layoutRef.current.pipes, rect);
          commitSelection({ cardIds, pipeIds });
        }

        function stop() {
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", stop);
          window.removeEventListener("pointercancel", stop);
          if (cancelGestureRef.current === stop) {
            cancelGestureRef.current = null;
          }
          store.setMarquee(null);
        }

        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", stop);
        window.addEventListener("pointercancel", stop);
        cancelGestureRef.current = stop;
        return;
      }

      clearSelection();
      onPaneClickRef.current?.();
      onBackgroundPointerDown(event);
    },
    [
      clearSelection,
      commitSelection,
      onBackgroundPointerDown,
      screenToWorld,
      store,
    ],
  );

  const connectionPreview = React.useMemo<LiveConnectionPreview | null>(() => {
    if (!wiring) return null;
    const from = index.cardsById.get(wiring.fromCardId);
    if (!from) return null;
    const start = portAnchorCenter(from, wiring.fromPort, punched);
    const end = wiring.target?.centre ?? wiring.cursor;
    const sourcePort =
      wiring.fromPort.direction === "output"
        ? wiring.fromPort
        : (wiring.target?.port ?? wiring.fromPort);
    return {
      points: previewPoints(start, portSide(wiring.fromPort), end, punched),
      color: portColor(sourcePort),
      sequence: sourcePort.shape === "many",
      cursor: end,
    };
  }, [wiring, index, punched]);

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable || target.closest("input, textarea, select"))
      ) {
        return;
      }
      if (event.key === "Escape") {
        if (expandedSequenceIdRef.current) {
          // The open spread closes first; the card stays held.
          setExpandedSequenceId(null);
          return;
        }
        cancelGestureRef.current?.();
        clearSelection();
        return;
      }
      if (event.key !== "Backspace" && event.key !== "Delete") return;
      if (!editableRef.current) return;
      const current = store.getSelection();
      if (current.pipeIds.size === 0 && current.cardIds.size === 0) return;
      event.preventDefault();
      if (current.pipeIds.size > 0) {
        const pipeIds = [...current.pipeIds];
        const removedSet = new Set(pipeIds);
        onRemovePipesRef.current?.(pipeIds);
        setHoveredPipeId((hovered) =>
          hovered && removedSet.has(hovered) ? null : hovered,
        );
        store.setHoveredPipe(null);
      }
      if (current.cardIds.size > 0) {
        onRemoveCardsRef.current?.([...current.cardIds]);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [clearSelection, store]);

  React.useEffect(() => {
    if (!exposeDebugApi) return;
    const api: CellCanvasDebugApi = {
      setViewAt: (wx, wy, zoom, sx, sy) => viewAt(wx, wy, zoom, sx, sy),
      getViewport: () => viewportRef.current,
      getStats: () => ({
        cards: graphRef.current.cards.length,
        pipes: graphRef.current.pipes.length,
        deepCount: layoutRef.current.deepCount,
        reroutes: rerouteRef.current,
        draggedCardId: draggedRef.current,
      }),
      getSelection: () => store.getSelection(),
      setSelection: (next) => commitSelection(next),
      lastConnectDropEmpty: lastDropEmptyRef.current,
      fit: () => fitGraph(),
    };
    window.__cellCanvas = api;
    return () => {
      if (window.__cellCanvas === api) delete window.__cellCanvas;
    };
  }, [commitSelection, exposeDebugApi, fitGraph, store, viewAt]);

  const firstSelectedPipeId = React.useMemo(() => {
    for (const id of selection.pipeIds) return id;
    return null;
  }, [selection.pipeIds]);

  const wipedPipeId = firstSelectedPipeId ?? hoveredPipeId;
  const wipedIntensity = firstSelectedPipeId ? 1 : hoveredPipeId ? 0.5 : 0;
  const hotPortKey = wiring?.target
    ? wellKey(
        wiring.target.cardId,
        wiring.target.port.direction,
        wiring.target.port.id,
      )
    : null;

  const dropEmptyAttr = lastConnectDropEmpty
    ? `${lastConnectDropEmpty.sourceCardId}:${lastConnectDropEmpty.sourcePortId}@${lastConnectDropEmpty.targetCell.col},${lastConnectDropEmpty.targetCell.row}`
    : undefined;

  const mergeSuggestionsEnabled =
    editable &&
    canMergeArtifactCards !== undefined &&
    onMergeArtifactCardRun !== undefined;
  const mergeSuggestions = React.useMemo<readonly ArtifactMergeSuggestion[]>(
    () =>
      mergeSuggestionsEnabled && canMergeArtifactCards
        ? findArtifactMergeSuggestions(
            foregroundCards,
            surfaceById,
            canMergeArtifactCards,
          )
        : [],
    [
      canMergeArtifactCards,
      foregroundCards,
      mergeSuggestionsEnabled,
      surfaceById,
    ],
  );
  const showMergeSuggestions =
    movingCardIds.size === 0 && resizePreview === null && wiring === null;

  const mergeTargetCard = mergeTarget
    ? index.cardsById.get(mergeTarget.cardId)
    : undefined;

  // Whether each sequence card has the free columns to spread in place.
  const spreadableById = React.useMemo(() => {
    const spreadable = new Map<string, boolean>();
    for (const card of foregroundCards) {
      const surface = surfaceById[card.id];
      if (surface?.kind !== "artifact") continue;
      const itemCount = surface.itemCount ?? 1;
      if (itemCount < 2) continue;
      spreadable.set(
        card.id,
        computeSequenceSpreadLayout({ card, itemCount, foregroundCards })
          .canExpand,
      );
    }
    return spreadable;
  }, [foregroundCards, surfaceById]);

  // The spread closes when its card goes, is left holding one item, or is
  // boxed in.
  const expandedCard = expandedSequenceId
    ? index.cardsById.get(expandedSequenceId)
    : undefined;
  const expandedSurface = expandedSequenceId
    ? surfaceById[expandedSequenceId]
    : undefined;
  const expandedItemCount =
    expandedSurface?.kind === "artifact" ? (expandedSurface.itemCount ?? 1) : 0;
  const expandedLayout = React.useMemo(
    () =>
      expandedCard && expandedItemCount > 1
        ? computeSequenceSpreadLayout({
            card: expandedCard,
            itemCount: expandedItemCount,
            foregroundCards,
            viewportWorldWidth: spreadViewportWidth,
            preferredVisibleCount: spreadVisibleCount,
          })
        : null,
    [
      expandedCard,
      expandedItemCount,
      foregroundCards,
      spreadViewportWidth,
      spreadVisibleCount,
    ],
  );
  const openSequence: {
    card: CellCardModel;
    surface: ArtifactCardSurfaceData;
    layout: OpenSequenceSpreadLayout;
  } | null =
    expandedCard &&
    expandedSurface?.kind === "artifact" &&
    expandedLayout?.canExpand
      ? { card: expandedCard, surface: expandedSurface, layout: expandedLayout }
      : null;
  if (expandedSequenceId !== null && openSequence === null) {
    setExpandedSequenceId(null);
  }
  const spreadOpen =
    openSequence !== null && !movingCardIds.has(openSequence.card.id);

  React.useLayoutEffect(() => {
    openSpreadRef.current =
      spreadOpen && openSequence
        ? {
            card: openSequence.card,
            layout: openSequence.layout,
            windowStart: spreadWindowStart,
            itemCount:
              openSequence.surface.stackItems?.length ??
              openSequence.surface.itemCount ??
              0,
          }
        : null;
  });

  const toggleSequence = React.useCallback(
    (cardId: string) => {
      const width = containerRef.current?.clientWidth ?? 0;
      setSpreadViewportWidth(width > 0 ? width / viewport.zoom : undefined);
      setSpreadVisibleCount(undefined);
      setSpreadWindowStart(0);
      setExpandedSequenceId((current) => (current === cardId ? null : cardId));
    },
    [viewport.zoom],
  );
  const closeSequence = React.useCallback(() => {
    setSpreadInsertTarget(null);
    setExpandedSequenceId(null);
  }, []);
  const moveSpreadSequence = React.useCallback(
    (cardId: string, col: number, row: number) => {
      onMoveCardsRef.current?.([{ cardId, col, row }]);
    },
    [],
  );

  const renderCard = (card: CellCardModel) => {
    const isMoving = movingCardIds.has(card.id);
    const remotePosition = remoteCardPositions.get(card.id);
    let visualOffset = dragFrame?.visualOffset;
    if (!isMoving) {
      visualOffset = remotePosition
        ? {
            x: remotePosition.x - card.col * CELL_SIZE,
            y: remotePosition.y - card.row * CELL_SIZE,
          }
        : undefined;
    }
    const isSelected = selection.cardIds.has(card.id);
    const laidPortIds =
      index.connectedPortIdsByCardId.get(card.id) ?? EMPTY_PORT_IDS;
    // Punched, the port a pipe is being wired from already has its pipe in
    // the hole: the preview runs on from it under the card.
    const connectedPortIds =
      punched && wiring?.fromCardId === card.id
        ? new Set([
            ...laidPortIds,
            cellPortKey(wiring.fromPort.direction, wiring.fromPort.id),
          ])
        : laidPortIds;
    const activePortKey =
      hotPortKey && hotPortKey.startsWith(`${card.id}:`) ? hotPortKey : null;
    const surface = surfaceById[card.id];
    const resolvedCard = editable ? card : { ...card, resizable: false };

    if (!surface) {
      return (
        <CellCard
          key={card.id}
          card={resolvedCard}
          visualOffset={visualOffset}
          material={look.material}
          well={look.well}
          pipe={look.pipe}
          cardFill={look.cardFill}
          selected={isSelected}
          dragging={isMoving}
          connectedPortIds={connectedPortIds}
          activePortKey={activePortKey}
          onCardPointerDown={onCardPointerDown}
          onPortPointerDown={onPortPointerDown}
        />
      );
    }

    const baseProps = {
      card: resolvedCard,
      visualOffset,
      material: look.material,
      corners: look.corners,
      well: look.well,
      pipe: look.pipe,
      cardFill: look.cardFill,
      selected: isSelected,
      dragging: isMoving,
      connectedPortIds,
      activePortKey,
      onCardPointerDown,
      onPortPointerDown: editable ? onPortPointerDown : undefined,
      onResizeStart: editable ? onResizeStart : undefined,
      onResizeMove: editable ? onResizeMove : undefined,
      onResizeEnd: editable ? onResizeEnd : undefined,
      onRemove: editable ? onRemoveSingleCard : undefined,
    };

    switch (surface.kind) {
      case "operator":
        return (
          <CellOperatorCard
            key={card.id}
            {...baseProps}
            surface={surface}
            onRun={onOperatorRun}
            onAddPlug={editable ? onOperatorAddPlug : undefined}
            onRemovePlug={editable ? onOperatorRemovePlug : undefined}
            onConfigChange={editable ? onOperatorConfigChange : undefined}
            onToggleAppendix={onOperatorToggleAppendix}
          />
        );
      case "artifact":
        // While it is spread open, its items stand in for it.
        if (spreadOpen && openSequence?.card.id === card.id) return null;
        // While it slides under the stack it joined, its tuck stands in.
        if (tuckingCardIds.has(card.id)) return null;
        return (
          <CellArtifactCard
            key={card.id}
            {...baseProps}
            surface={surface}
            stackStyle={look.stackStyle}
            mergeHover={mergeTarget?.cardId === card.id}
            merging={mergeTarget !== null && draggedCardId === card.id}
            onInspect={onArtifactInspect}
            onExpandSequence={toggleSequence}
            onUngroup={editable ? onUngroupArtifactCard : undefined}
            onImageLoad={onArtifactImageLoad}
            sequenceExpanded={openSequence?.card.id === card.id}
            canExpandSequence={spreadableById.get(card.id) ?? true}
          />
        );
      case "collection":
        return (
          <CellCollectionCard
            key={card.id}
            {...baseProps}
            surface={surface}
            onRemoveMember={editable ? onCollectionRemoveMember : undefined}
          />
        );
      case "annotation":
        return (
          <CellAnnotationCard
            key={card.id}
            {...baseProps}
            surface={surface}
            onColorChange={editable ? onAnnotationColorChange : undefined}
          />
        );
      case "agent":
        return <CellAgentCard key={card.id} {...baseProps} surface={surface} />;
    }
  };

  return (
    <CellCanvasProvider viewportApi={viewportApi} store={store}>
      <div
        ref={containerRef}
        data-cell-canvas="true"
        data-graph={dataGraph}
        data-editable={editable ? "true" : "false"}
        data-connect-drop-empty={dropEmptyAttr}
        {...stylex.props(s.root, panning && s.rootPanning)}
        onPointerDown={onRootPointerDown}
      >
        <CellGlassStage
          viewport={viewport}
          look={look}
          restingPipes={resting.pipes}
          restingWells={resting.wells}
          movingPipes={dragFrame?.movingPipes ?? EMPTY_PIPES}
          movingWells={dragFrame?.movingWells ?? EMPTY_WELLS}
          wipedPipeId={wipedPipeId}
          wipedIntensity={wipedIntensity}
          cellSize={CELL_SIZE}
          dragging={movingCardIds.size > 0 || wiring !== null}
          onPipeHover={onPipeHover}
          onPipeSelect={onPipeSelect}
        />
        {underCardsFrames.length > 0 ? (
          <CellViewportLayer layer="under-cards" viewport={viewport}>
            {underCardsFrames.map(renderCard)}
          </CellViewportLayer>
        ) : null}
        {/* After the frames, before the cards: a pipe being wired lies over
            the frost and any frame, and slides under every card it crosses. */}
        <CellConnectionPreview
          viewport={viewport}
          look={look}
          preview={connectionPreview}
        />
        <div
          data-cell-viewport="true"
          {...stylex.props(s.world)}
          style={{
            transform: `translate3d(${viewport.x}px, ${viewport.y}px, 0) scale(${viewport.zoom})`,
          }}
        >
          <CellLandingOutlines
            outlines={
              // Over a merge or spread drop target the card joins that
              // sequence, so no grid landing is shown.
              dragFrame?.showGhostCells &&
              mergeTarget === null &&
              spreadInsertTarget === null
                ? dragFrame.ghostBoxes.map((ghost) => ({
                    cardId: ghost.cardId,
                    bounds: ghost,
                  }))
                : []
            }
          />
          <div {...stylex.props(s.cards)}>
            <CellStackTuckLayer
              tucks={stackTucks}
              onSettled={onStackTuckSettled}
            />
            {foregroundCards.map(renderCard)}
          </div>
        </div>
        <CellViewportLayer layer="over-cards" viewport={viewport}>
          <CellDockedBridgeLayer
            joins={visibleDockedJoins}
            punched={punched}
            selectedPipeIds={selection.pipeIds}
            hoveredPipeId={hoveredPipeId}
            onJoinHover={onPipeHover}
            onJoinSelect={(pipeId) => {
              onPipeSelect(pipeId);
              const join = visibleDockedJoins.find(
                (candidate) => candidate.pipeId === pipeId,
              );
              onSelectEdgeAttachmentRef.current?.(pipeId, join?.seamPoint);
            }}
          />
          {visiblePipeAttachments.map((attachment) => (
            <CellEdgeSelectorPill
              key={attachment.pipeId}
              attachment={attachment}
              selected={selection.pipeIds.has(attachment.pipeId)}
              hovered={hoveredPipeId === attachment.pipeId}
              onHover={onPipeHover}
              onSelect={(pipeId) => {
                onPipeSelect(pipeId);
                onSelectEdgeAttachmentRef.current?.(pipeId, attachment.anchor);
              }}
              onRemove={editable ? onRemovePipeAttachment : undefined}
            >
              {onSelectEdgeAttachment ? (
                <IconButton
                  size="2xs"
                  variant="ghost"
                  shape="round"
                  label="Edit connection"
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={(event) => {
                    event.stopPropagation();
                    onPipeSelect(attachment.pipeId);
                    onSelectEdgeAttachmentRef.current?.(
                      attachment.pipeId,
                      attachment.anchor,
                    );
                  }}
                >
                  <ChevronDown size={11} />
                </IconButton>
              ) : null}
            </CellEdgeSelectorPill>
          ))}
          {showMergeSuggestions && onMergeArtifactCardRun
            ? mergeSuggestions.map((suggestion) => (
                <CellArtifactMergeSuggestionOverlay
                  key={suggestion.id}
                  suggestion={suggestion}
                  onMerge={mergeArtifactRun}
                />
              ))
            : null}
          {mergeTarget && mergeTargetCard ? (
            <CellArtifactMergeTargetOverlay
              card={mergeTargetCard}
              itemCount={mergeTarget.itemCount}
            />
          ) : null}
          {spreadOpen && openSequence ? (
            <CellArtifactSequenceSpread
              key={openSequence.card.id}
              card={openSequence.card}
              surface={openSequence.surface}
              layout={openSequence.layout}
              foregroundCards={foregroundCards}
              screenToWorld={screenToWorld}
              material={look.material}
              corners={look.corners}
              stackStyle={look.stackStyle}
              cardFill={look.cardFill}
              externalInsertSlot={
                spreadInsertTarget?.spreadCardId === openSequence.card.id
                  ? spreadInsertTarget.slot
                  : null
              }
              onWindowStartChange={setSpreadWindowStart}
              onClose={closeSequence}
              onPreferredVisibleCountChange={setSpreadVisibleCount}
              onMove={editable && onMoveCards ? moveSpreadSequence : undefined}
              onInspect={onArtifactInspect}
              onReorder={editable ? onReorderArtifactCardItem : undefined}
              onExtract={editable ? onExtractArtifactCardItem : undefined}
              onRemoveItem={editable ? onRemoveArtifactCardItem : undefined}
            />
          ) : null}
          <CellRemotePresenceLayer
            peers={remotePeers}
            cards={foregroundCards}
          />
          <CellMarqueeOverlay marquee={marquee} />
        </CellViewportLayer>
        {children}
      </div>
    </CellCanvasProvider>
  );
}
