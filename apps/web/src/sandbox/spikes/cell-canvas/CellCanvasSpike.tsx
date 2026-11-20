"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { artifactTypeColor } from "@/features/workbench/canvas/nodes.css";
import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  CellCanvasProvider,
  CellViewportLayer,
} from "@/features/workbench/cell-canvas/CellCanvasContext";
import { CellCard } from "@/features/workbench/cell-canvas/CellCard";
import {
  CellDockedBridgeLayer,
  CellEdgeSelectorPill,
  CellMarqueeOverlay,
} from "@/features/workbench/cell-canvas/CellGlassOverlays";
import {
  CellAgentCard,
  CellAnnotationCard,
} from "@/features/workbench/cell-canvas/cards/CellAnnotationAndAgentCards";
import {
  CellArtifactCard,
  CellCollectionCard,
} from "@/features/workbench/cell-canvas/cards/CellArtifactCard";
import { CellOperatorCard } from "@/features/workbench/cell-canvas/cards/CellOperatorCard";
import { computeOperatorCardLayout } from "@/features/workbench/cell-canvas/cell-card-geometry";
import type {
  AnnotationColorToken,
  CellCardSurfaceData,
  CellConnectDropEmptyEvent,
  CellDockedJoin,
  CellResizeEdge,
  CellSelectionSnapshot,
  CellViewportApi,
  OperatorCardSurfaceData,
} from "@/features/workbench/cell-canvas/cell-contracts";
import {
  detectCellDockedJoins,
  findDockSnapCandidate,
} from "@/features/workbench/cell-canvas/cell-docking";
import {
  CellGlassStage,
  type CellGlassLook,
  type LiveConnectionPreview,
  type StagePipe,
  type StageViewport,
  type StageWell,
} from "@/features/workbench/cell-canvas/cell-glass-stage";
import {
  createDemoCellGraph,
  createStressCellGraph,
} from "@/features/workbench/cell-canvas/cell-graphs";
import {
  computeCellResize,
  createGroupDragSession,
  partitionSceneForMovingCards,
  resolveNonOverlappingDelta,
  updateGroupDragSession,
  type GroupDragSession,
} from "@/features/workbench/cell-canvas/cell-group-drag";
import {
  CELL_PIPE_STUB_MIN,
  CELL_SIZE,
  cardWorldRect,
  cellToWorldOrigin,
  portSide,
  portWorldCenter,
  type CellCardModel,
  type CellCoord,
  type CellDir,
  type CellGraph,
  type CellPort,
  type CellRoutingOptions,
  type CellRoutingResult,
  type WorldPoint,
} from "@/features/workbench/cell-canvas/cell-model";
import { solvePipeAttachmentAnchors } from "@/features/workbench/cell-canvas/cell-pipe-attachments";
import { routeCellGraph } from "@/features/workbench/cell-canvas/cell-router";
import {
  cardsInMarqueeRect,
  createCellInteractionStore,
  pipesInMarqueeRect,
} from "@/features/workbench/cell-canvas/cell-store";
import {
  MORPH_DURATION_MS,
  SETTLE_DURATION_MS,
  anchorPipeEndpoints,
  createCardSettle,
  morphPipePoints,
  retargetCardSettle,
  stepCardSettle,
  type CardSettleState,
} from "@/features/workbench/cell-canvas/cell-transitions";
import {
  useCellViewport,
  type WorldBounds,
} from "@/features/workbench/cell-canvas/use-cell-viewport";

import {
  CellLookPanel,
  CellZoomBar,
  type CellGraphKind,
} from "./CellLookPanel";
import { createRealAnatomyShowcaseGraph } from "./cell-showcase-graphs";

/**
 * The cell canvas spike (v2): cards, ports, docked seams, edge projection
 * pills, and underground pipes on a shared 50px cell lattice without React Flow.
 *
 * A drag keeps two scenes apart. The resting scene (every pipe and well not
 * attached to the moving card group) is worked out once at pickup and keeps
 * its identity until the drop, so the resting planes and stationary cards
 * never re-render. Each animation frame rebuilds only the moving scene: the
 * group's visual offset, its attached pipes, and their wells.
 */

export interface CellCanvasDebugApi {
  setViewAt: (
    wx: number,
    wy: number,
    zoom: number,
    sx?: number,
    sy?: number,
  ) => StageViewport;
  getViewport: () => StageViewport;
  getStats: () => {
    cards: number;
    pipes: number;
    deepCount: number;
    reroutes: number;
    draggedCardId: string | null;
  };
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

/** Screen pixels a pointer travels before a press on a card becomes a drag. */
const DRAG_THRESHOLD_PX = 3;
/** How close, in flow units, the cursor must come to a port to wire to it. */
const WIRE_SNAP_RADIUS = 22;
const ZOOM_STEP = 1.2;

const DEFAULT_LOOK: CellGlassLook = {
  material: "liquid",
  well: "recessed",
  pipe: "glass",
  corners: "rounded",
  blur: 0.3,
  frost: 0.5,
  grid: true,
};

const DEFAULT_ROUTING: CellRoutingOptions = {
  exits: "side",
  underCards: "gaps",
  depth: true,
};

const EMPTY_ID_SET: ReadonlySet<string> = new Set();
const EMPTY_PORT_IDS: ReadonlySet<string> = new Set();
const EMPTY_PIPES: readonly StagePipe[] = [];
const EMPTY_WELLS: readonly StageWell[] = [];
const EMPTY_SURFACES: Record<string, CellCardSurfaceData> = {};

const s = stylex.create({
  root: {
    position: "relative",
    width: "100%",
    height: "100svh",
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
  ghostCell: {
    position: "absolute",
    zIndex: 0,
    boxSizing: "border-box",
    borderWidth: "1px",
    borderStyle: "dashed",
    borderColor: tokens.colorAccentBorder,
    borderRadius: tokens.radiusMd,
    pointerEvents: "none",
  },
  lookPanel: {
    position: "absolute",
    top: "16px",
    left: "16px",
    zIndex: 30,
  },
  zoomBar: {
    position: "absolute",
    bottom: "16px",
    left: "16px",
    zIndex: 30,
  },
});

const LookPanel = React.memo(CellLookPanel);
const ZoomBar = React.memo(CellZoomBar);

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

function isUnderCardsFrame(
  cardId: string,
  surfaceById: Readonly<Record<string, CellCardSurfaceData>>,
): boolean {
  const surface = surfaceById[cardId];
  return surface?.kind === "annotation" && surface.variant === "frame";
}

function resolveArtifactColor(artifactTypeId: string): string {
  return artifactTypeColor(artifactTypeId, tokens.colorMuted);
}

function graphBounds(cards: readonly CellCardModel[]): WorldBounds {
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
      if (listed.has(plug.plugId)) return;
      extra.push({
        id: plug.plugId,
        name: plug.label,
        direction: "input",
        rowOffset: group.startRowOffset + index,
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
    portsByCardId.set(card.id, new Map(ports.map((p) => [p.id, p])));
  }
  const connected = new Map<string, Set<string>>();
  const mark = (cardId: string, portId: string) => {
    const ids = connected.get(cardId) ?? new Set<string>();
    ids.add(portId);
    connected.set(cardId, ids);
  };
  for (const pipe of graph.pipes) {
    mark(pipe.sourceCardId, pipe.sourcePortId);
    mark(pipe.targetCardId, pipe.targetPortId);
  }
  return { cardsById, portsByCardId, connectedPortIdsByCardId: connected };
}

function findPort(
  index: GraphIndex,
  cardId: string,
  portId: string,
): PortRef | null {
  const card = index.cardsById.get(cardId);
  const port = index.portsByCardId.get(cardId)?.get(portId);
  return card && port ? { card, port } : null;
}

function portColor(port: CellPort): string {
  return resolveArtifactColor(port.artifactTypeId);
}

function wellKey(cardId: string, portId: string): string {
  return `${cardId}:${portId}`;
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
  const key = wellKey(ref.card.id, ref.port.id);
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
): RestingScene {
  const partition = partitionSceneForMovingCards(graph, movingCardIds);
  const pipes: StagePipe[] = [];
  const wells: StageWell[] = [];
  const wellKeys = new Set<string>();
  for (const pipe of partition.restingPipes) {
    if (dockedPipeIds.has(pipe.id)) continue;
    const routed = layout.pipes.get(pipe.id);
    const source = findPort(index, pipe.sourceCardId, pipe.sourcePortId);
    const target = findPort(index, pipe.targetCardId, pipe.targetPortId);
    if (!routed || !source || !target) continue;
    const color = portColor(source.port);
    const sequence = source.port.shape === "many";
    pipes.push({
      id: pipe.id,
      points: routed.points,
      color,
      sequence,
      depth: routed.depth,
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
): WorldPoint[] {
  const out = side === "right" ? 1 : -1;
  const ahead = (end.x - start.x) * out;
  if (Math.abs(end.y - start.y) < 0.5 && ahead >= CELL_PIPE_STUB_MIN) {
    return [start, end];
  }
  const reach = start.x + out * CELL_PIPE_STUB_MIN;
  const halfway = (start.x + end.x) / 2;
  const x = out > 0 ? Math.max(reach, halfway) : Math.min(reach, halfway);
  return [start, { x, y: start.y }, { x, y: end.y }, end];
}

function useFrameRate(): number | null {
  const [rate, setRate] = React.useState<number | null>(null);
  React.useEffect(() => {
    let frames = 0;
    let since = performance.now();
    let handle = 0;
    const tick = (now: number) => {
      frames += 1;
      if (now - since >= 500) {
        setRate(Math.round((frames * 1000) / (now - since)));
        frames = 0;
        since = now;
      }
      handle = requestAnimationFrame(tick);
    };
    handle = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(handle);
  }, []);
  return rate;
}

// ---------------------------------------------------------------------------
// Gesture state, kept in closures and refs so frames never re-render stationary cards

interface PipeMotion {
  id: string;
  sourceCardId: string;
  targetCardId: string;
  sourcePortId: string;
  targetPortId: string;
  color: string;
  sequence: boolean;
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
  tug: WorldPoint;
  attachedPipeIds: ReadonlySet<string>;
  restingWellKeys: ReadonlySet<string>;
  pipes: PipeMotion[];
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

function liveCentre(
  drag: GroupCardDrag,
  index: GraphIndex,
  cardId: string,
  portId: string,
  offset: WorldPoint,
): WorldPoint | null {
  const ref = findPort(index, cardId, portId);
  if (!ref) return null;
  return drag.session.movingCardIds.has(cardId)
    ? portWorldCenter(ref.card, ref.port, offset)
    : portWorldCenter(ref.card, ref.port);
}

/** Steps every attached pipe to `now` and draws the moving scene. */
function buildDragFrame(
  drag: GroupCardDrag,
  index: GraphIndex,
  now: number,
): DragFrameState {
  const settled = drag.cellSettle.current;
  const visualOrigin = drag.pointerReleased
    ? settled
    : { x: settled.x + drag.tug.x, y: settled.y + drag.tug.y };
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
      visualOffset,
    );
    const targetCentre = liveCentre(
      drag,
      index,
      motion.targetCardId,
      motion.targetPortId,
      visualOffset,
    );
    const source = findPort(index, motion.sourceCardId, motion.sourcePortId);
    const target = findPort(index, motion.targetCardId, motion.targetPortId);
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
      points: anchored,
      color: motion.color,
      sequence: motion.sequence,
      depth: motion.depth,
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
        col: initial.col + drag.session.currentDelta.col,
        row: initial.row + drag.session.currentDelta.row,
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
    const source = findPort(index, pipe.sourceCardId, pipe.sourcePortId);
    const target = findPort(index, pipe.targetCardId, pipe.targetPortId);
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

export function CellCanvasSpike() {
  const containerRef = React.useRef<HTMLDivElement | null>(null);
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
  } = useCellViewport(containerRef);

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

  const [graphKind, setGraphKind] = React.useState<CellGraphKind>("demo");
  const [graph, setGraph] = React.useState<CellGraph>(createDemoCellGraph);
  const [surfaceById, setSurfaceById] =
    React.useState<Record<string, CellCardSurfaceData>>(EMPTY_SURFACES);
  const [look, setLook] = React.useState<CellGlassLook>(DEFAULT_LOOK);
  const [routing, setRouting] =
    React.useState<CellRoutingOptions>(DEFAULT_ROUTING);
  const [hoveredPipeId, setHoveredPipeId] = React.useState<string | null>(null);
  const [rerouteCount, setRerouteCount] = React.useState(0);
  const [movingCardIds, setMovingCardIds] =
    React.useState<ReadonlySet<string>>(EMPTY_ID_SET);
  const [draggedCardId, setDraggedCardId] = React.useState<string | null>(null);
  const [dragFrame, setDragFrame] = React.useState<DragFrameState | null>(null);
  const [wiring, setWiring] = React.useState<WiringState | null>(null);
  const [lastConnectDropEmpty, setLastConnectDropEmpty] =
    React.useState<CellConnectDropEmptyEvent | null>(null);
  const fps = useFrameRate();

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
    for (const card of graph.cards) {
      if (isUnderCardsFrame(card.id, surfaceById)) {
        frames.push(card);
      } else {
        foreground.push(card);
      }
    }
    return { underCardsFrames: frames, foregroundCards: foreground };
  }, [graph.cards, surfaceById]);

  const docking = React.useMemo(
    () =>
      detectCellDockedJoins(
        { cards: foregroundCards, pipes: graph.pipes },
        resolveArtifactColor,
      ),
    [foregroundCards, graph.pipes],
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
    () => indexGraph(graph, surfaceById),
    [graph, surfaceById],
  );

  // Changes at pickup and drop only, never on a drag frame.
  const resting = React.useMemo(
    () =>
      restingScene(
        graph,
        index,
        restingLayout,
        docking.dockedPipeIds,
        movingCardIds,
      ),
    [graph, index, restingLayout, docking.dockedPipeIds, movingCardIds],
  );

  const pipeAttachments = React.useMemo(
    () =>
      solvePipeAttachmentAnchors({
        cards: foregroundCards,
        pipes: graph.pipes,
        routedPipes: restingLayout.pipes,
        dockedJoins: docking.dockedJoins,
        resolveColor: resolveArtifactColor,
      }),
    [foregroundCards, graph.pipes, restingLayout.pipes, docking.dockedJoins],
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

  // Handlers read the latest render through these, so they stay stable.
  const graphRef = React.useRef(graph);
  const surfaceByIdRef = React.useRef(surfaceById);
  const foregroundCardsRef = React.useRef(foregroundCards);
  const indexRef = React.useRef(index);
  const dockingRef = React.useRef(docking);
  const layoutRef = React.useRef(restingLayout);
  const routingRef = React.useRef(routing);
  const viewportRef = React.useRef(viewport);
  const rerouteRef = React.useRef(rerouteCount);
  const draggedRef = React.useRef(draggedCardId);
  const lastDropEmptyRef = React.useRef(lastConnectDropEmpty);
  const resizeSessionRef = React.useRef<ResizeSession | null>(null);

  React.useLayoutEffect(() => {
    graphRef.current = graph;
    surfaceByIdRef.current = surfaceById;
    foregroundCardsRef.current = foregroundCards;
    indexRef.current = index;
    dockingRef.current = docking;
    layoutRef.current = restingLayout;
    routingRef.current = routing;
    viewportRef.current = viewport;
    rerouteRef.current = rerouteCount;
    draggedRef.current = draggedCardId;
    lastDropEmptyRef.current = lastConnectDropEmpty;
  });

  /** Ends the gesture in flight (card drag, marquee, or wiring) without committing it. */
  const cancelGestureRef = React.useRef<(() => void) | null>(null);
  React.useEffect(() => {
    const gesture = cancelGestureRef;
    return () => gesture.current?.();
  }, []);

  const fit = React.useCallback(() => {
    fitRect(graphBounds(graphRef.current.cards));
  }, [fitRect]);

  React.useLayoutEffect(() => {
    fit();
  }, [fit]);

  const onPipeHover = React.useCallback(
    (pipeId: string | null) => {
      setHoveredPipeId(pipeId);
      store.setHoveredPipe(pipeId);
    },
    [store],
  );

  const onPipeSelect = React.useCallback(
    (id: string) => {
      store.setSelection({ cardIds: [], pipeIds: [id] });
    },
    [store],
  );

  const onRemovePipe = React.useCallback(
    (pipeId: string) => {
      setGraph((current) => ({
        ...current,
        pipes: current.pipes.filter((pipe) => pipe.id !== pipeId),
      }));
      const currentPipes = new Set(store.getSelection().pipeIds);
      if (currentPipes.delete(pipeId)) {
        store.setSelection({
          cardIds: store.getSelection().cardIds,
          pipeIds: currentPipes,
        });
      }
      setHoveredPipeId((hovered) => (hovered === pipeId ? null : hovered));
      store.setHoveredPipe(null);
    },
    [store],
  );

  const onGraph = React.useCallback(
    (kind: CellGraphKind) => {
      cancelGestureRef.current?.();
      resizeSessionRef.current = null;
      store.setResizingCard(null);
      store.setMarquee(null);
      store.setDraggingCards([]);
      store.setHoveredPipe(null);
      store.setHoveredCard(null);

      let nextGraph: CellGraph;
      let nextSurfaces: Record<string, CellCardSurfaceData>;
      if (kind === "showcase") {
        const showcase = createRealAnatomyShowcaseGraph();
        nextGraph = showcase.graph;
        nextSurfaces = showcase.surfaceById;
        store.setSelection({ cardIds: ["ocr-extract"], pipeIds: [] });
      } else if (kind === "stress") {
        nextGraph = createStressCellGraph();
        nextSurfaces = EMPTY_SURFACES;
        store.clearSelection();
      } else {
        nextGraph = createDemoCellGraph();
        nextSurfaces = EMPTY_SURFACES;
        store.clearSelection();
      }

      setGraphKind(kind);
      setGraph(nextGraph);
      setSurfaceById(nextSurfaces);
      setHoveredPipeId(null);
      setMovingCardIds(EMPTY_ID_SET);
      setDraggedCardId(null);
      setDragFrame(null);
      setWiring(null);
      setRerouteCount(0);
      fitRect(graphBounds(nextGraph.cards));
    },
    [fitRect, store],
  );

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
      const originCard: CellCardModel = card;

      const shiftPressed = event.shiftKey;
      const wasSelectedBefore = store.getSelection().cardIds.has(cardId);
      if (shiftPressed) {
        store.toggleCardSelection(cardId);
      } else if (!wasSelectedBefore) {
        store.setSelection({ cardIds: [cardId], pipeIds: [] });
      }

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
        tug: { x: 0, y: 0 },
        attachedPipeIds: EMPTY_ID_SET,
        restingWellKeys: EMPTY_ID_SET,
        pipes: [],
      };
      let frame = 0;

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

      /** Lands the group in its final non-overlapping cells and drops the moving scene. */
      function finish() {
        stop();
        let finalDelta = drag.session.currentDelta;
        if (!draggingFrame) {
          const foregroundAtPickup = graphAtPickup.cards.filter(
            (c) => !isUnderCardsFrame(c.id, surfacesAtPickup),
          );
          finalDelta = resolveNonOverlappingDelta(
            foregroundAtPickup,
            drag.session.movingCardIds,
            finalDelta,
          );
          if (drag.session.movingCardIds.size === 1) {
            const initial = drag.session.anchorInitialCell;
            const proposedCard: CellCardModel = {
              ...originCard,
              col: initial.col + finalDelta.col,
              row: initial.row + finalDelta.row,
            };
            const stationary = foregroundAtPickup.filter(
              (c) => c.id !== cardId,
            );
            const dockCandidate = findDockSnapCandidate(
              proposedCard,
              stationary,
              graphAtPickup.pipes,
              1,
            );
            if (dockCandidate) {
              finalDelta = {
                col: dockCandidate.col - initial.col,
                row: dockCandidate.row - initial.row,
              };
            }
          }
        }
        if (finalDelta.col !== 0 || finalDelta.row !== 0) {
          setGraph((current) => ({
            ...current,
            cards: current.cards.map((other) => {
              const initial = drag.session.initialCells.get(other.id);
              if (!initial) return other;
              return {
                ...other,
                col: initial.col + finalDelta.col,
                row: initial.row + finalDelta.row,
              };
            }),
          }));
        }
        store.setDraggingCards([]);
        setMovingCardIds(EMPTY_ID_SET);
        setDraggedCardId(null);
        setDragFrame(null);
      }

      function activate() {
        drag.movedBeyondClick = true;
        drag.cellSettle = createCardSettle(originWorld);
        drag.tug = { x: 0, y: 0 };
        const split = restingScene(
          graphAtPickup,
          indexAtPickup,
          layoutRef.current,
          dockingAtPickup.dockedPipeIds,
          drag.session.movingCardIds,
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
        const step = updateGroupDragSession(
          drag.session,
          graphAtPickup.cards,
          at,
        );
        drag.session = step.session;
        drag.tug = step.visualOffset;
        if (step.changedCell) {
          setRerouteCount((count) => count + 1);
          const anchorTarget = {
            col: drag.session.anchorInitialCell.col + step.snappedDelta.col,
            row: drag.session.anchorInitialCell.row + step.snappedDelta.row,
          };
          drag.cellSettle = retargetCardSettle(
            drag.cellSettle,
            cellToWorldOrigin(anchorTarget.col, anchorTarget.row),
            now,
            SETTLE_DURATION_MS,
          );
          const movedForeground = step.movedCards.filter(
            (c) => !isUnderCardsFrame(c.id, surfacesAtPickup),
          );
          const movedDocking = detectCellDockedJoins(
            { cards: movedForeground, pipes: graphAtPickup.pipes },
            resolveArtifactColor,
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
            store.setSelection({ cardIds: [cardId], pipeIds: [] });
          }
          return;
        }
        const now = performance.now();
        const settled = stepCardSettle(drag.cellSettle, now).current;
        const visual = { x: settled.x + drag.tug.x, y: settled.y + drag.tug.y };
        drag.tug = { x: 0, y: 0 };
        drag.pointerReleased = true;
        const anchorTarget = {
          col:
            drag.session.anchorInitialCell.col + drag.session.currentDelta.col,
          row:
            drag.session.anchorInitialCell.row + drag.session.currentDelta.row,
        };
        drag.cellSettle = retargetCardSettle(
          createCardSettle(visual),
          cellToWorldOrigin(anchorTarget.col, anchorTarget.row),
          now,
          SETTLE_DURATION_MS,
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
        if (drag.movedBeyondClick) {
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
    [screenToWorld, store],
  );

  const onPortPointerDown = React.useCallback(
    (
      cardId: string,
      port: CellPort,
      event: React.PointerEvent<HTMLButtonElement>,
    ) => {
      if (event.button !== 0) return;
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
            const centre = portWorldCenter(other, candidate);
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
          target ? wellKey(target.cardId, target.port.id) : null,
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
          }
          return;
        }
        const fromOutput = port.direction === "output";
        const ends = {
          sourceCardId: fromOutput ? cardId : target.cardId,
          sourcePortId: fromOutput ? port.id : target.port.id,
          targetCardId: fromOutput ? target.cardId : cardId,
          targetPortId: fromOutput ? target.port.id : port.id,
        };
        setGraph((currentGraph) => {
          const duplicate = currentGraph.pipes.some(
            (pipe) =>
              pipe.sourceCardId === ends.sourceCardId &&
              pipe.sourcePortId === ends.sourcePortId &&
              pipe.targetCardId === ends.targetCardId &&
              pipe.targetPortId === ends.targetPortId,
          );
          if (duplicate) return currentGraph;
          const ids = new Set(currentGraph.pipes.map((pipe) => pipe.id));
          let serial = currentGraph.pipes.length + 1;
          while (ids.has(`wire-${serial}`)) serial += 1;
          return {
            ...currentGraph,
            pipes: [
              ...currentGraph.pipes,
              { id: `wire-${serial}`, ...ends, enabled: true },
            ],
          };
        });
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
      cancelGestureRef.current?.();
      const card = indexRef.current.cardsById.get(cardId);
      if (!card) return;
      resizeSessionRef.current = {
        cardSnapshot: card,
        startWorld: screenToWorld(event.clientX, event.clientY),
      };
      store.setResizingCard(cardId);
    },
    [screenToWorld, store],
  );

  const applyResizeAt = React.useCallback(
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
      const live = indexRef.current.cardsById.get(cardId);
      if (
        !live ||
        (live.widthCells === commit.widthCells &&
          live.heightCells === commit.heightCells)
      ) {
        return;
      }
      setRerouteCount((count) => count + 1);
      setGraph((current) => ({
        ...current,
        cards: current.cards.map((c) =>
          c.id === cardId
            ? {
                ...c,
                widthCells: commit.widthCells,
                heightCells: commit.heightCells,
              }
            : c,
        ),
      }));
    },
    [screenToWorld],
  );

  const onResizeMove = React.useCallback(
    (
      cardId: string,
      edge: CellResizeEdge,
      event: React.PointerEvent<HTMLDivElement>,
    ) => {
      applyResizeAt(cardId, edge, event);
    },
    [applyResizeAt],
  );

  const onResizeEnd = React.useCallback(
    (
      cardId: string,
      edge: CellResizeEdge,
      event: React.PointerEvent<HTMLDivElement>,
    ) => {
      applyResizeAt(cardId, edge, event);
      resizeSessionRef.current = null;
      store.setResizingCard(null);
    },
    [applyResizeAt, store],
  );

  const onOperatorConfigChange = React.useCallback(
    (cardId: string, fieldId: string, value: string | number | boolean) => {
      setSurfaceById((current) => {
        const surface = current[cardId];
        if (surface?.kind !== "operator" || !surface.configFields) {
          return current;
        }
        return {
          ...current,
          [cardId]: {
            ...surface,
            configFields: surface.configFields.map((field) =>
              field.id === fieldId ? { ...field, value } : field,
            ),
          },
        };
      });
    },
    [],
  );

  const onOperatorToggleAppendix = React.useCallback((cardId: string) => {
    const surface = surfaceByIdRef.current[cardId];
    const card = indexRef.current.cardsById.get(cardId);
    if (surface?.kind !== "operator" || !surface.appendix || !card) return;
    const nextSurface: OperatorCardSurfaceData = {
      ...surface,
      appendix: {
        ...surface.appendix,
        collapsed: !surface.appendix.collapsed,
      },
    };
    const nextHeight = computeOperatorCardLayout(
      { ...card, heightCells: 2 },
      nextSurface,
    ).totalHeightCells;
    setSurfaceById((current) => ({ ...current, [cardId]: nextSurface }));
    setGraph((current) => ({
      ...current,
      cards: current.cards.map((c) =>
        c.id === cardId ? { ...c, heightCells: nextHeight } : c,
      ),
    }));
  }, []);

  const onOperatorAddPlug = React.useCallback(
    (cardId: string, portName: string) => {
      const surface = surfaceByIdRef.current[cardId];
      const card = indexRef.current.cardsById.get(cardId);
      if (
        surface?.kind !== "operator" ||
        !surface.instancePlugGroups ||
        !card
      ) {
        return;
      }
      let addedPort: CellPort | null = null;
      const nextGroups = surface.instancePlugGroups.map((group) => {
        if (group.portName !== portName) return group;
        const nextIndex = group.plugs.length + 1;
        const plugId = `${portName}::plug-${Date.now()}-${nextIndex}`;
        const label = `Hint ${nextIndex}`;
        const rowOffset = group.startRowOffset + group.plugs.length;
        addedPort = {
          id: plugId,
          name: label,
          direction: "input",
          rowOffset,
          artifactTypeId: group.artifactTypeId,
          shape: group.shape,
        };
        return {
          ...group,
          plugs: [...group.plugs, { plugId, label, connected: false }],
        };
      });
      if (!addedPort) return;
      const nextSurface: OperatorCardSurfaceData = {
        ...surface,
        instancePlugGroups: nextGroups,
      };
      const nextCardBase: CellCardModel = {
        ...card,
        ports: [...card.ports, addedPort],
      };
      const nextHeight = computeOperatorCardLayout(
        { ...nextCardBase, heightCells: 2 },
        nextSurface,
      ).totalHeightCells;
      setSurfaceById((current) => ({ ...current, [cardId]: nextSurface }));
      setGraph((current) => ({
        ...current,
        cards: current.cards.map((c) =>
          c.id === cardId ? { ...nextCardBase, heightCells: nextHeight } : c,
        ),
      }));
    },
    [],
  );

  const onOperatorRemovePlug = React.useCallback(
    (cardId: string, portName: string, plugId: string) => {
      const surface = surfaceByIdRef.current[cardId];
      const card = indexRef.current.cardsById.get(cardId);
      if (
        surface?.kind !== "operator" ||
        !surface.instancePlugGroups ||
        !card
      ) {
        return;
      }
      const nextGroups = surface.instancePlugGroups.map((group) => {
        if (group.portName !== portName) return group;
        return {
          ...group,
          plugs: group.plugs.filter((plug) => plug.plugId !== plugId),
        };
      });
      const nextSurface: OperatorCardSurfaceData = {
        ...surface,
        instancePlugGroups: nextGroups,
      };
      const nextPorts = card.ports.filter((port) => port.id !== plugId);
      const nextCardBase: CellCardModel = { ...card, ports: nextPorts };
      const nextHeight = computeOperatorCardLayout(
        { ...nextCardBase, heightCells: 2 },
        nextSurface,
      ).totalHeightCells;
      setSurfaceById((current) => ({ ...current, [cardId]: nextSurface }));
      setGraph((current) => ({
        ...current,
        cards: current.cards.map((c) =>
          c.id === cardId ? { ...nextCardBase, heightCells: nextHeight } : c,
        ),
        pipes: current.pipes.filter(
          (pipe) =>
            !(pipe.targetCardId === cardId && pipe.targetPortId === plugId),
        ),
      }));
    },
    [],
  );

  const onOperatorRun = React.useCallback((cardId: string) => {
    setGraph((current) => ({
      ...current,
      cards: current.cards.map((c) =>
        c.id === cardId
          ? { ...c, status: c.status === "working" ? "done" : "working" }
          : c,
      ),
    }));
  }, []);

  const onAnnotationColorChange = React.useCallback(
    (cardId: string, color: AnnotationColorToken) => {
      setSurfaceById((current) => {
        const surface = current[cardId];
        if (surface?.kind !== "annotation") return current;
        return { ...current, [cardId]: { ...surface, color } };
      });
    },
    [],
  );

  const onRootPointerDown = React.useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
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
          store.setSelection({ cardIds, pipeIds });
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

      store.clearSelection();
      onBackgroundPointerDown(event);
    },
    [onBackgroundPointerDown, screenToWorld, store],
  );

  const connectionPreview = React.useMemo<LiveConnectionPreview | null>(() => {
    if (!wiring) return null;
    const from = index.cardsById.get(wiring.fromCardId);
    if (!from) return null;
    const start = portWorldCenter(from, wiring.fromPort);
    const end = wiring.target?.centre ?? wiring.cursor;
    const sourcePort =
      wiring.fromPort.direction === "output"
        ? wiring.fromPort
        : (wiring.target?.port ?? wiring.fromPort);
    return {
      points: previewPoints(start, portSide(wiring.fromPort), end),
      color: portColor(sourcePort),
      sequence: sourcePort.shape === "many",
      cursor: end,
    };
  }, [wiring, index]);

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
        cancelGestureRef.current?.();
        store.clearSelection();
        return;
      }
      if (event.key !== "Backspace" && event.key !== "Delete") return;
      const selectedPipes = store.getSelection().pipeIds;
      if (selectedPipes.size === 0) return;
      event.preventDefault();
      const toRemove = new Set(selectedPipes);
      setGraph((current) => ({
        ...current,
        pipes: current.pipes.filter((pipe) => !toRemove.has(pipe.id)),
      }));
      store.setSelection({
        cardIds: store.getSelection().cardIds,
        pipeIds: [],
      });
      setHoveredPipeId((hovered) =>
        hovered && toRemove.has(hovered) ? null : hovered,
      );
      store.setHoveredPipe(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [store]);

  React.useEffect(() => {
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
      setSelection: (next) => store.setSelection(next),
      lastConnectDropEmpty: lastDropEmptyRef.current,
      fit,
    };
    window.__cellCanvas = api;
    return () => {
      if (window.__cellCanvas === api) delete window.__cellCanvas;
    };
  }, [viewAt, fit, store]);

  const counts = React.useMemo(
    () => ({
      cards: graph.cards.length,
      pipes: graph.pipes.length,
      deepCount: restingLayout.deepCount,
      reroutes: rerouteCount,
    }),
    [graph, restingLayout, rerouteCount],
  );
  const onZoomIn = React.useCallback(() => zoomBy(ZOOM_STEP), [zoomBy]);
  const onZoomOut = React.useCallback(() => zoomBy(1 / ZOOM_STEP), [zoomBy]);

  const firstSelectedPipeId = React.useMemo(() => {
    for (const id of selection.pipeIds) return id;
    return null;
  }, [selection.pipeIds]);

  const wipedPipeId = firstSelectedPipeId ?? hoveredPipeId;
  const wipedIntensity = firstSelectedPipeId ? 1 : hoveredPipeId ? 0.5 : 0;
  const hotPortKey = wiring?.target
    ? wellKey(wiring.target.cardId, wiring.target.port.id)
    : null;

  const dropEmptyAttr = lastConnectDropEmpty
    ? `${lastConnectDropEmpty.sourceCardId}:${lastConnectDropEmpty.sourcePortId}@${lastConnectDropEmpty.targetCell.col},${lastConnectDropEmpty.targetCell.row}`
    : undefined;

  const renderCard = (card: CellCardModel) => {
    const isMoving = movingCardIds.has(card.id);
    const visualOffset = isMoving ? dragFrame?.visualOffset : undefined;
    const isSelected = selection.cardIds.has(card.id);
    const connectedPortIds =
      index.connectedPortIdsByCardId.get(card.id) ?? EMPTY_PORT_IDS;
    const activePortKey =
      hotPortKey && hotPortKey.startsWith(`${card.id}:`) ? hotPortKey : null;
    const surface = surfaceById[card.id];

    if (!surface) {
      return (
        <CellCard
          key={card.id}
          card={card}
          visualOffset={visualOffset}
          material={look.material}
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
      card,
      visualOffset,
      material: look.material,
      corners: look.corners,
      selected: isSelected,
      dragging: isMoving,
      connectedPortIds,
      activePortKey,
      onCardPointerDown,
      onPortPointerDown,
      onResizeStart,
      onResizeMove,
      onResizeEnd,
    };

    switch (surface.kind) {
      case "operator":
        return (
          <CellOperatorCard
            key={card.id}
            {...baseProps}
            surface={surface}
            onRun={onOperatorRun}
            onAddPlug={onOperatorAddPlug}
            onRemovePlug={onOperatorRemovePlug}
            onConfigChange={onOperatorConfigChange}
            onToggleAppendix={onOperatorToggleAppendix}
          />
        );
      case "artifact":
        return (
          <CellArtifactCard key={card.id} {...baseProps} surface={surface} />
        );
      case "collection":
        return (
          <CellCollectionCard key={card.id} {...baseProps} surface={surface} />
        );
      case "annotation":
        return (
          <CellAnnotationCard
            key={card.id}
            {...baseProps}
            surface={surface}
            onColorChange={onAnnotationColorChange}
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
        data-graph={graphKind}
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
          connectionPreview={connectionPreview}
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
        <div
          data-cell-viewport="true"
          {...stylex.props(s.world)}
          style={{
            transform: `translate3d(${viewport.x}px, ${viewport.y}px, 0) scale(${viewport.zoom})`,
          }}
        >
          {dragFrame?.showGhostCells
            ? dragFrame.ghostBoxes.map((ghost) => (
                <div
                  key={ghost.cardId}
                  aria-hidden="true"
                  data-cell-ghost={ghost.cardId}
                  {...stylex.props(s.ghostCell)}
                  style={{
                    left: ghost.col * CELL_SIZE,
                    top: ghost.row * CELL_SIZE,
                    width: ghost.widthCells * CELL_SIZE,
                    height: ghost.heightCells * CELL_SIZE,
                  }}
                />
              ))
            : null}
          <div {...stylex.props(s.cards)}>
            {foregroundCards.map(renderCard)}
          </div>
        </div>
        <CellViewportLayer layer="over-cards" viewport={viewport}>
          <CellDockedBridgeLayer
            joins={visibleDockedJoins}
            selectedPipeIds={selection.pipeIds}
            hoveredPipeId={hoveredPipeId}
            onJoinHover={onPipeHover}
            onJoinSelect={(pipeId) => onPipeSelect(pipeId)}
          />
          {visiblePipeAttachments.map((attachment) => (
            <CellEdgeSelectorPill
              key={attachment.pipeId}
              attachment={attachment}
              selected={selection.pipeIds.has(attachment.pipeId)}
              hovered={hoveredPipeId === attachment.pipeId}
              onHover={onPipeHover}
              onSelect={(pipeId) => onPipeSelect(pipeId)}
              onRemove={onRemovePipe}
            />
          ))}
          <CellMarqueeOverlay marquee={marquee} />
        </CellViewportLayer>
        <div {...stylex.props(s.lookPanel)}>
          <LookPanel
            graph={graphKind}
            onGraph={onGraph}
            counts={counts}
            fps={fps}
            look={look}
            onLook={setLook}
            routing={routing}
            onRouting={setRouting}
          />
        </div>
        <div {...stylex.props(s.zoomBar)}>
          <ZoomBar
            zoom={viewport.zoom}
            onZoomIn={onZoomIn}
            onZoomOut={onZoomOut}
            onZoomPreset={zoomAtCenter}
            onFit={fit}
          />
        </div>
      </div>
    </CellCanvasProvider>
  );
}
