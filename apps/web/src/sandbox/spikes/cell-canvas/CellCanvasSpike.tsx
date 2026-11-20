"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { artifactTypeColor } from "@/features/workbench/canvas/nodes.css";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { CellCard } from "./CellCard";
import {
  CellLookPanel,
  CellZoomBar,
  type CellGraphKind,
} from "./CellLookPanel";
import {
  CellGlassStage,
  type CellGlassLook,
  type LiveConnectionPreview,
  type StagePipe,
  type StageViewport,
  type StageWell,
} from "./cell-glass-stage";
import { createDemoCellGraph, createStressCellGraph } from "./cell-graphs";
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
  type CellPipeModel,
  type CellPort,
  type CellRoutingOptions,
  type CellRoutingResult,
  type WorldPoint,
} from "./cell-model";
import { routeCellGraph } from "./cell-router";
import {
  MORPH_DURATION_MS,
  SETTLE_DURATION_MS,
  anchorPipeEndpoints,
  createCardSettle,
  magneticTugOffset,
  morphPipePoints,
  retargetCardSettle,
  snapCellWithHysteresis,
  stepCardSettle,
  type CardSettleState,
} from "./cell-transitions";
import { useCellViewport, type WorldBounds } from "./use-cell-viewport";

/**
 * The cell canvas spike: cards, ports and pipes on a square grid, drawn over
 * the glass stage without React Flow.
 *
 * A drag keeps two scenes apart. The resting scene (every pipe and well not
 * attached to the dragged card) is worked out once at pickup and keeps its
 * identity until the drop, so the resting planes and the other cards never
 * re-render. Each animation frame rebuilds only the moving scene: the dragged
 * card's offset, its pipes and their wells.
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

const EMPTY_PORT_IDS: ReadonlySet<string> = new Set();
const EMPTY_PIPES: readonly StagePipe[] = [];
const EMPTY_WELLS: readonly StageWell[] = [];

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

// The panels redraw only when their own props change, not on drag frames.
const LookPanel = React.memo(CellLookPanel);
const ZoomBar = React.memo(CellZoomBar);

// ---------------------------------------------------------------------------
// Pure helpers

interface DragFrameState {
  cardId: string;
  snappedCell: CellCoord;
  visualOffset: WorldPoint;
  /** True while the pointer is held, false during the drop's settle. */
  showGhostCell: boolean;
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
  /** Pipes of the dragged card, which the moving scene draws. */
  attachedPipeIds: ReadonlySet<string>;
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
  // Ports sit in the cell outside each side of a card.
  return {
    x: minX - CELL_SIZE,
    y: minY - CELL_SIZE * 0.5,
    width: maxX - minX + CELL_SIZE * 2,
    height: maxY - minY + CELL_SIZE,
  };
}

function indexGraph(graph: CellGraph): GraphIndex {
  const cardsById = new Map<string, CellCardModel>();
  const portsByCardId = new Map<string, Map<string, CellPort>>();
  for (const card of graph.cards) {
    cardsById.set(card.id, card);
    portsByCardId.set(card.id, new Map(card.ports.map((p) => [p.id, p])));
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
  return artifactTypeColor(port.artifactTypeId, tokens.colorMuted);
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

function isAttached(pipe: CellPipeModel, cardId: string | null): boolean {
  return pipe.sourceCardId === cardId || pipe.targetCardId === cardId;
}

function restingScene(
  graph: CellGraph,
  index: GraphIndex,
  layout: CellRoutingResult,
  draggedCardId: string | null,
): RestingScene {
  const pipes: StagePipe[] = [];
  const wells: StageWell[] = [];
  const wellKeys = new Set<string>();
  const attachedPipeIds = new Set<string>();
  for (const pipe of graph.pipes) {
    if (draggedCardId !== null && isAttached(pipe, draggedCardId)) {
      attachedPipeIds.add(pipe.id);
      continue;
    }
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
  return { pipes, wells, wellKeys, attachedPipeIds };
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
// Gesture state, kept in closures and refs so frames never re-render cards

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
}

interface CardDrag {
  cardId: string;
  /** The card as it rests in the graph; offsets are measured from it. */
  originCard: CellCardModel;
  originCell: CellCoord;
  currentCell: CellCoord;
  startClient: WorldPoint;
  grabOffset: WorldPoint;
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

function liveCentre(
  drag: CardDrag,
  index: GraphIndex,
  cardId: string,
  portId: string,
  offset: WorldPoint,
): WorldPoint | null {
  const ref = findPort(index, cardId, portId);
  if (!ref) return null;
  return cardId === drag.cardId
    ? portWorldCenter(drag.originCard, ref.port, offset)
    : portWorldCenter(ref.card, ref.port);
}

/** Steps every attached pipe to `now` and draws the moving scene. */
function buildDragFrame(
  drag: CardDrag,
  index: GraphIndex,
  now: number,
): DragFrameState {
  const settled = drag.cellSettle.current;
  const visualOrigin = drag.pointerReleased
    ? settled
    : { x: settled.x + drag.tug.x, y: settled.y + drag.tug.y };
  const visualOffset = {
    x: visualOrigin.x - drag.originCell.col * CELL_SIZE,
    y: visualOrigin.y - drag.originCell.row * CELL_SIZE,
  };
  const movingPipes: StagePipe[] = [];
  const movingWells: StageWell[] = [];
  const wellKeys = new Set<string>();
  for (const motion of drag.pipes) {
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
  return {
    cardId: drag.cardId,
    snappedCell: drag.currentCell,
    visualOffset,
    showGhostCell: !drag.pointerReleased,
    movingPipes,
    movingWells,
  };
}

function seedPipeMotions(
  graph: CellGraph,
  index: GraphIndex,
  layout: CellRoutingResult,
  attachedPipeIds: ReadonlySet<string>,
): PipeMotion[] {
  const motions: PipeMotion[] = [];
  for (const pipe of graph.pipes) {
    if (!attachedPipeIds.has(pipe.id)) continue;
    const routed = layout.pipes.get(pipe.id);
    const source = findPort(index, pipe.sourceCardId, pipe.sourcePortId);
    if (!routed || !source) continue;
    motions.push({
      id: pipe.id,
      sourceCardId: pipe.sourceCardId,
      targetCardId: pipe.targetCardId,
      sourcePortId: pipe.sourcePortId,
      targetPortId: pipe.targetPortId,
      color: portColor(source.port),
      sequence: source.port.shape === "many",
      fromPoints: routed.points,
      toPoints: routed.points,
      currentPoints: routed.points,
      sourceExit: routed.sourceExit,
      targetExit: routed.targetExit,
      depth: routed.depth,
      morphStartMs: 0,
      morphing: false,
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
    onBackgroundPointerDown,
  } = useCellViewport(containerRef);

  const [graphKind, setGraphKind] = React.useState<CellGraphKind>("demo");
  const [graph, setGraph] = React.useState<CellGraph>(createDemoCellGraph);
  const [look, setLook] = React.useState<CellGlassLook>(DEFAULT_LOOK);
  const [routing, setRouting] =
    React.useState<CellRoutingOptions>(DEFAULT_ROUTING);
  const [selectedCardId, setSelectedCardId] = React.useState<string | null>(
    null,
  );
  const [selectedPipeId, setSelectedPipeId] = React.useState<string | null>(
    null,
  );
  const [hoveredPipeId, setHoveredPipeId] = React.useState<string | null>(null);
  const [rerouteCount, setRerouteCount] = React.useState(0);
  const [draggedCardId, setDraggedCardId] = React.useState<string | null>(null);
  const [dragFrame, setDragFrame] = React.useState<DragFrameState | null>(null);
  const [wiring, setWiring] = React.useState<WiringState | null>(null);
  const fps = useFrameRate();

  const restingLayout = React.useMemo(
    () => routeCellGraph(graph, routing),
    [graph, routing],
  );
  const index = React.useMemo(() => indexGraph(graph), [graph]);
  // Changes at pickup and drop only, never on a drag frame.
  const resting = React.useMemo(
    () => restingScene(graph, index, restingLayout, draggedCardId),
    [graph, index, restingLayout, draggedCardId],
  );

  // Handlers read the latest render through these, so they stay stable.
  const graphRef = React.useRef(graph);
  const indexRef = React.useRef(index);
  const layoutRef = React.useRef(restingLayout);
  const routingRef = React.useRef(routing);
  const viewportRef = React.useRef(viewport);
  const rerouteRef = React.useRef(rerouteCount);
  const draggedRef = React.useRef(draggedCardId);
  React.useLayoutEffect(() => {
    graphRef.current = graph;
    indexRef.current = index;
    layoutRef.current = restingLayout;
    routingRef.current = routing;
    viewportRef.current = viewport;
    rerouteRef.current = rerouteCount;
    draggedRef.current = draggedCardId;
  });

  /** Ends the gesture in flight (card drag or wiring) without committing it. */
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

  const onGraph = React.useCallback(
    (kind: CellGraphKind) => {
      cancelGestureRef.current?.();
      const next =
        kind === "demo" ? createDemoCellGraph() : createStressCellGraph();
      setGraphKind(kind);
      setGraph(next);
      setSelectedCardId(null);
      setSelectedPipeId(null);
      setHoveredPipeId(null);
      setDraggedCardId(null);
      setDragFrame(null);
      setWiring(null);
      setRerouteCount(0);
      fitRect(graphBounds(next.cards));
    },
    [fitRect],
  );

  const onCardPointerDown = React.useCallback(
    (cardId: string, event: React.PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return;
      event.stopPropagation();
      cancelGestureRef.current?.();
      setSelectedCardId(cardId);
      setSelectedPipeId(null);

      const graphAtPickup = graphRef.current;
      const indexAtPickup = indexRef.current;
      const routingAtPickup = routingRef.current;
      const card = indexAtPickup.cardsById.get(cardId);
      if (!card) return;
      const pointerId = event.pointerId;
      const originCell = { col: card.col, row: card.row };
      const originWorld = cellToWorldOrigin(card.col, card.row);
      const pointer = screenToWorld(event.clientX, event.clientY);
      const drag: CardDrag = {
        cardId,
        originCard: card,
        originCell,
        currentCell: originCell,
        startClient: { x: event.clientX, y: event.clientY },
        grabOffset: {
          x: pointer.x - originWorld.x,
          y: pointer.y - originWorld.y,
        },
        movedBeyondClick: false,
        pointerReleased: false,
        cellSettle: createCardSettle(originWorld),
        tug: { x: 0, y: 0 },
        attachedPipeIds: new Set(),
        restingWellKeys: new Set(),
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

      /** Lands the card in its cell and drops the moving scene in one batch. */
      function finish() {
        stop();
        const { col, row } = drag.currentCell;
        if (col !== originCell.col || row !== originCell.row) {
          setGraph((current) => ({
            ...current,
            cards: current.cards.map((other) =>
              other.id === cardId ? { ...other, col, row } : other,
            ),
          }));
        }
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
          cardId,
        );
        drag.attachedPipeIds = split.attachedPipeIds;
        drag.restingWellKeys = split.wellKeys;
        drag.pipes = seedPipeMotions(
          graphAtPickup,
          indexAtPickup,
          layoutRef.current,
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
        const raw = {
          x: at.x - drag.grabOffset.x,
          y: at.y - drag.grabOffset.y,
        };
        const nextCell = snapCellWithHysteresis(raw, drag.currentCell);
        drag.tug = magneticTugOffset(raw, nextCell);
        if (
          nextCell.col !== drag.currentCell.col ||
          nextCell.row !== drag.currentCell.row
        ) {
          drag.currentCell = nextCell;
          setRerouteCount((count) => count + 1);
          drag.cellSettle = retargetCardSettle(
            drag.cellSettle,
            cellToWorldOrigin(nextCell.col, nextCell.row),
            now,
            SETTLE_DURATION_MS,
          );
          const movedCards = graphAtPickup.cards.map((other) =>
            other.id === cardId
              ? { ...other, col: nextCell.col, row: nextCell.row }
              : other,
          );
          const rerouted = routeCellGraph(
            { cards: movedCards, pipes: graphAtPickup.pipes },
            routingAtPickup,
            drag.attachedPipeIds,
          );
          for (const motion of drag.pipes) {
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
          // Pickup: the resting split and the first moving frame land together,
          // so the attached pipes never blink out for a render.
          setDraggedCardId(cardId);
          setDragFrame(buildDragFrame(drag, indexAtPickup, now));
        }
        schedule();
      }

      function onUp(up: PointerEvent) {
        if (up.pointerId !== pointerId || drag.pointerReleased) return;
        if (!drag.movedBeyondClick) {
          stop();
          return;
        }
        const now = performance.now();
        const settled = stepCardSettle(drag.cellSettle, now).current;
        const visual = { x: settled.x + drag.tug.x, y: settled.y + drag.tug.y };
        drag.tug = { x: 0, y: 0 };
        drag.pointerReleased = true;
        drag.cellSettle = retargetCardSettle(
          createCardSettle(visual),
          cellToWorldOrigin(drag.currentCell.col, drag.currentCell.row),
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
          setDraggedCardId(null);
          setDragFrame(null);
        }
      }

      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
      cancelGestureRef.current = cancel;
    },
    [screenToWorld],
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
          for (const candidate of other.ports) {
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
        setWiring(state);
      };

      function onMove(move: PointerEvent) {
        if (move.pointerId === pointerId) track(move.clientX, move.clientY);
      }

      function onUp(up: PointerEvent) {
        if (up.pointerId !== pointerId) return;
        const target = up.type === "pointerup" ? state?.target : null;
        stop();
        if (!target) return;
        const fromOutput = port.direction === "output";
        const ends = {
          sourceCardId: fromOutput ? cardId : target.cardId,
          sourcePortId: fromOutput ? port.id : target.port.id,
          targetCardId: fromOutput ? target.cardId : cardId,
          targetPortId: fromOutput ? target.port.id : port.id,
        };
        setGraph((current) => {
          const duplicate = current.pipes.some(
            (pipe) =>
              pipe.sourceCardId === ends.sourceCardId &&
              pipe.sourcePortId === ends.sourcePortId &&
              pipe.targetCardId === ends.targetCardId &&
              pipe.targetPortId === ends.targetPortId,
          );
          if (duplicate) return current;
          const ids = new Set(current.pipes.map((pipe) => pipe.id));
          let serial = current.pipes.length + 1;
          while (ids.has(`wire-${serial}`)) serial += 1;
          return {
            ...current,
            pipes: [...current.pipes, { id: `wire-${serial}`, ...ends }],
          };
        });
      }

      function stop() {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        window.removeEventListener("pointercancel", onUp);
        if (cancelGestureRef.current === stop) cancelGestureRef.current = null;
        setWiring(null);
      }

      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
      window.addEventListener("pointercancel", onUp);
      cancelGestureRef.current = stop;
      track(event.clientX, event.clientY);
    },
    [screenToWorld],
  );

  const connectionPreview = React.useMemo<LiveConnectionPreview | null>(() => {
    if (!wiring) return null;
    const from = index.cardsById.get(wiring.fromCardId);
    if (!from) return null;
    const start = portWorldCenter(from, wiring.fromPort);
    const end = wiring.target?.centre ?? wiring.cursor;
    // The pipe's source is whichever end is the output.
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

  const onPipeSelect = React.useCallback((id: string) => {
    setSelectedPipeId(id);
    setSelectedCardId(null);
  }, []);

  React.useEffect(() => {
    if (!selectedPipeId) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Backspace" && event.key !== "Delete") return;
      const target = event.target;
      if (
        target instanceof HTMLElement &&
        (target.isContentEditable || target.closest("input, textarea"))
      ) {
        return;
      }
      event.preventDefault();
      setGraph((current) => ({
        ...current,
        pipes: current.pipes.filter((pipe) => pipe.id !== selectedPipeId),
      }));
      setSelectedPipeId(null);
      setHoveredPipeId((hovered) =>
        hovered === selectedPipeId ? null : hovered,
      );
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedPipeId]);

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
      fit,
    };
    window.__cellCanvas = api;
    return () => {
      if (window.__cellCanvas === api) delete window.__cellCanvas;
    };
  }, [viewAt, fit]);

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

  const wipedPipeId = selectedPipeId ?? hoveredPipeId;
  const wipedIntensity = selectedPipeId ? 1 : hoveredPipeId ? 0.5 : 0;
  const hotPortKey = wiring?.target
    ? wellKey(wiring.target.cardId, wiring.target.port.id)
    : null;
  const ghostCard = dragFrame?.showGhostCell
    ? index.cardsById.get(dragFrame.cardId)
    : undefined;

  return (
    <div
      ref={containerRef}
      data-cell-canvas="true"
      data-graph={graphKind}
      {...stylex.props(s.root, panning && s.rootPanning)}
      onPointerDown={(event) => {
        setSelectedCardId(null);
        setSelectedPipeId(null);
        onBackgroundPointerDown(event);
      }}
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
        dragging={draggedCardId !== null || wiring !== null}
        onPipeHover={setHoveredPipeId}
        onPipeSelect={onPipeSelect}
      />
      <div
        data-cell-viewport="true"
        {...stylex.props(s.world)}
        style={{
          transform: `translate3d(${viewport.x}px, ${viewport.y}px, 0) scale(${viewport.zoom})`,
        }}
      >
        {dragFrame && ghostCard ? (
          <div
            aria-hidden="true"
            data-cell-ghost="true"
            {...stylex.props(s.ghostCell)}
            style={{
              left: dragFrame.snappedCell.col * CELL_SIZE,
              top: dragFrame.snappedCell.row * CELL_SIZE,
              width: ghostCard.widthCells * CELL_SIZE,
              height: ghostCard.heightCells * CELL_SIZE,
            }}
          />
        ) : null}
        <div {...stylex.props(s.cards)}>
          {graph.cards.map((card) => (
            <CellCard
              key={card.id}
              card={card}
              visualOffset={
                draggedCardId === card.id ? dragFrame?.visualOffset : undefined
              }
              material={look.material}
              selected={selectedCardId === card.id}
              dragging={draggedCardId === card.id}
              connectedPortIds={
                index.connectedPortIdsByCardId.get(card.id) ?? EMPTY_PORT_IDS
              }
              activePortKey={
                hotPortKey && hotPortKey.startsWith(`${card.id}:`)
                  ? hotPortKey
                  : null
              }
              onCardPointerDown={onCardPointerDown}
              onPortPointerDown={onPortPointerDown}
            />
          ))}
        </div>
      </div>
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
  );
}
