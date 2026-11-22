import type { EffectReducer, ExecEffect } from "@/lib/state/effect-reducer";
import { artifactTypeColor } from "@/features/workbench/config-ui/nodes.css";
import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  artifactCardItemCount,
  findArtifactMergeTarget,
  findSpreadInsertTarget,
  type CanMergeArtifactCards,
  type OpenSequenceSpreadLayout,
  type SpreadInsertTarget,
} from "./cell-artifact-stacking";
import { plugRowOffset } from "./cell-card-geometry";
import type {
  CellCardSurfaceData,
  CellConnectDropEmptyEvent,
  CellMarqueeRect,
  CellResizeCommit,
  CellResizeEdge,
} from "./cell-contracts";
import { detectCellDockedJoins } from "./cell-docking";
import type { StagePipe, StageWell } from "./cell-glass-stage";
import {
  computeCellResize,
  createGroupDragSession,
  partitionSceneForMovingCards,
  resolveNonOverlappingDelta,
  updateGroupDragSession,
  type GroupDragSession,
} from "./cell-group-drag";
import {
  CELL_PIPE_STUB_MIN,
  CELL_SIZE,
  PUNCHED_PORT_INSET,
  cellPortKey,
  cellToWorldOrigin,
  portAnchorCenter,
  portWorldCenter,
  punchedPipePoints,
  type CellCardModel,
  type CellCoord,
  type CellDir,
  type CellGraph,
  type CellPipeModel,
  type CellPort,
  type CellRoutingOptions,
  type CellRoutingResult,
  type RoutedCellPipe,
  type WorldPoint,
} from "./cell-model";
import { routeCellGraph } from "./cell-router";
import { cardsInMarqueeRect, pipesInMarqueeRect } from "./cell-store";
import {
  MORPH_DURATION_MS,
  anchorPipeEndpoints,
  createCardSettle,
  morphPipePoints,
  retargetCardSettle,
  stepCardSettle,
  type CardSettleState,
} from "./cell-transitions";

/** Screen pixels a pointer travels before a press on a card becomes a drag. */
export const DRAG_THRESHOLD_PX = 3;
/** How close, in flow units, the cursor must come to a port to wire to it. */
export const WIRE_SNAP_RADIUS = 22;

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

export interface DragGhostBox {
  cardId: string;
  col: number;
  row: number;
  widthCells: number;
  heightCells: number;
}

export interface DragFrameState {
  anchorCardId: string;
  snappedDelta: CellCoord;
  visualOffset: WorldPoint;
  showGhostCells: boolean;
  ghostBoxes: readonly DragGhostBox[];
  movingPipes: readonly StagePipe[];
  movingWells: readonly StageWell[];
}

export interface GraphIndex {
  cardsById: ReadonlyMap<string, CellCardModel>;
  portsByCardId: ReadonlyMap<string, ReadonlyMap<string, CellPort>>;
  connectedPortIdsByCardId: ReadonlyMap<string, ReadonlySet<string>>;
}

export interface RestingScene {
  pipes: readonly StagePipe[];
  wells: readonly StageWell[];
  /** Keys of the wells the resting scene draws. */
  wellKeys: ReadonlySet<string>;
  /** Pipes attached to the moving card group, which the moving scene draws. */
  attachedPipeIds: ReadonlySet<string>;
}

export interface PipeMotion {
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

export interface WireTarget {
  cardId: string;
  port: CellPort;
  centre: WorldPoint;
}

export interface WiringState {
  fromCardId: string;
  fromPort: CellPort;
  cursor: WorldPoint;
  target: WireTarget | null;
}

/** The open sequence a drag consults for insert hits and occupied space. */
export interface OpenSpreadSnapshot {
  readonly card: CellCardModel;
  readonly layout: OpenSequenceSpreadLayout;
  readonly windowStart: number;
  readonly itemCount: number;
}

export interface PickupDocking {
  readonly dockedPipeIds: ReadonlySet<string>;
  readonly routablePipes: readonly CellPipeModel[];
}

/** A card sliding under a stack it just joined. The shell plays the tuck. */
export interface StackTuckJoin {
  readonly card: CellCardModel;
  readonly from: WorldPoint;
  readonly target: CellCardModel;
  readonly slot: number;
  readonly surface: CellCardSurfaceData | undefined;
}

export interface DragFrameSource {
  readonly anchorCardId: string;
  readonly session: GroupDragSession;
  readonly cellSettle: CardSettleState;
  readonly landingDelta: CellCoord;
  readonly pointerReleased: boolean;
  readonly restingWellKeys: ReadonlySet<string>;
  readonly pipes: readonly PipeMotion[];
  readonly punched: boolean;
}

interface DraggingCardsPhase {
  readonly kind: "draggingCards";
  readonly pointerId: number;
  readonly anchorCardId: string;
  readonly startClient: WorldPoint;
  readonly movedBeyondClick: boolean;
  readonly pointerReleased: boolean;
  readonly shiftPressed: boolean;
  readonly wasSelectedBefore: boolean;
  readonly draggingFrame: boolean;
  readonly originWorld: WorldPoint;
  readonly session: GroupDragSession;
  readonly cellSettle: CardSettleState;
  readonly landingDelta: CellCoord;
  readonly attachedPipeIds: ReadonlySet<string>;
  readonly restingWellKeys: ReadonlySet<string>;
  readonly pipes: readonly PipeMotion[];
  readonly punched: boolean;
  readonly graphAtPickup: CellGraph;
  readonly surfacesAtPickup: Readonly<Record<string, CellCardSurfaceData>>;
  readonly indexAtPickup: GraphIndex;
  readonly routingAtPickup: CellRoutingOptions;
  readonly dockingAtPickup: PickupDocking;
  readonly layoutAtPickup: CellRoutingResult;
  readonly foregroundAtPickup: readonly CellCardModel[];
  readonly obstacleForegroundAtPickup: readonly CellCardModel[];
  readonly openSpreadAtPickup: OpenSpreadSnapshot | null;
  readonly mergeable: boolean;
  readonly mergeTargetId: string | null;
  readonly mergeItemCount: number;
  readonly spreadInsert: SpreadInsertTarget | null;
  readonly canMergeArtifactCards: CanMergeArtifactCards | null;
  readonly hasMergeCallback: boolean;
  readonly hasInsertCallback: boolean;
}

export type CellCanvasGesturePhase =
  | { readonly kind: "idle" }
  | {
      readonly kind: "panning";
      readonly pointerId: number;
      readonly lastClient: WorldPoint;
    }
  | {
      readonly kind: "marquee";
      readonly pointerId: number;
      readonly start: WorldPoint;
      readonly current: WorldPoint;
    }
  | DraggingCardsPhase
  | {
      readonly kind: "resizingCard";
      readonly cardSnapshot: CellCardModel;
      readonly edge: CellResizeEdge;
      readonly startWorld: WorldPoint;
      readonly preview: CellResizeCommit;
    }
  | {
      readonly kind: "connectingPipe";
      readonly pointerId: number;
      readonly fromCardId: string;
      readonly fromPort: CellPort;
      readonly cursor: WorldPoint;
      readonly target: WireTarget | null;
    };

export interface CellCanvasInteractionState {
  readonly phase: CellCanvasGesturePhase;
  readonly dragFrame: DragFrameState | null;
  readonly lastConnectDropEmpty: CellConnectDropEmptyEvent | null;
  readonly rerouteCount: number;
}

export type CellCanvasInteractionAction =
  | {
      readonly kind: "startPan";
      readonly pointerId: number;
      readonly clientPoint: WorldPoint;
    }
  | {
      readonly kind: "panMove";
      readonly pointerId: number;
      readonly clientPoint: WorldPoint;
    }
  | { readonly kind: "panEnd"; readonly pointerId: number }
  | {
      readonly kind: "startMarquee";
      readonly pointerId: number;
      readonly worldPoint: WorldPoint;
      readonly foregroundCards: readonly CellCardModel[];
      readonly routedPipes: ReadonlyMap<string, RoutedCellPipe>;
    }
  | {
      readonly kind: "marqueeMove";
      readonly pointerId: number;
      readonly worldPoint: WorldPoint;
      readonly foregroundCards: readonly CellCardModel[];
      readonly routedPipes: ReadonlyMap<string, RoutedCellPipe>;
    }
  | { readonly kind: "marqueeEnd"; readonly pointerId: number }
  | {
      readonly kind: "cardPointerDown";
      readonly cardId: string;
      readonly pointerId: number;
      readonly clientPoint: WorldPoint;
      readonly worldPoint: WorldPoint;
      readonly shiftKey: boolean;
      readonly wasSelectedBefore: boolean;
      readonly selectedCardIds: ReadonlySet<string>;
      readonly editable: boolean;
      readonly graph: CellGraph;
      readonly surfaces: Readonly<Record<string, CellCardSurfaceData>>;
      readonly index: GraphIndex;
      readonly routing: CellRoutingOptions;
      readonly docking: PickupDocking;
      readonly layout: CellRoutingResult;
      readonly punched: boolean;
      readonly openSpread: OpenSpreadSnapshot | null;
      readonly canMergeArtifactCards: CanMergeArtifactCards | null;
      readonly hasMergeCallback: boolean;
      readonly hasInsertCallback: boolean;
    }
  | {
      readonly kind: "dragMove";
      readonly pointerId: number;
      readonly clientPoint: WorldPoint;
      readonly worldPoint: WorldPoint;
      readonly now: number;
      readonly openSpread: OpenSpreadSnapshot | null;
    }
  | {
      readonly kind: "dragUp";
      readonly pointerId: number;
      readonly now: number;
    }
  | {
      readonly kind: "dragTick";
      readonly now: number;
      readonly index: GraphIndex;
    }
  | {
      readonly kind: "startResize";
      readonly card: CellCardModel;
      readonly edge: CellResizeEdge;
      readonly startWorld: WorldPoint;
      readonly editable: boolean;
    }
  | {
      readonly kind: "resizeMove";
      readonly cardId: string;
      readonly edge: CellResizeEdge;
      readonly worldPoint: WorldPoint;
    }
  | {
      readonly kind: "resizeEnd";
      readonly cardId: string;
      readonly edge: CellResizeEdge;
      readonly worldPoint: WorldPoint;
    }
  | {
      readonly kind: "startConnect";
      readonly pointerId: number;
      readonly fromCardId: string;
      readonly fromPort: CellPort;
      readonly cursor: WorldPoint;
      readonly cards: readonly CellCardModel[];
      readonly surfaces: Readonly<Record<string, CellCardSurfaceData>>;
      readonly punched: boolean;
      readonly canConnect?: (candidate: CellConnectionEnds) => boolean;
    }
  | {
      readonly kind: "connectMove";
      readonly pointerId: number;
      readonly cursor: WorldPoint;
      readonly cards: readonly CellCardModel[];
      readonly surfaces: Readonly<Record<string, CellCardSurfaceData>>;
      readonly punched: boolean;
      readonly canConnect?: (candidate: CellConnectionEnds) => boolean;
    }
  | {
      readonly kind: "connectEnd";
      readonly pointerId: number;
      readonly clientPoint: WorldPoint;
      readonly isCancel: boolean;
    }
  | { readonly kind: "cancelGesture" };

export type CellCanvasInteractionEffect =
  | {
      readonly kind: "attachWindowGesture";
      readonly gesture: "pan" | "marquee" | "drag" | "connect";
      readonly pointerId: number;
    }
  | { readonly kind: "detachWindowGesture" }
  | { readonly kind: "scheduleDragFrame" }
  | { readonly kind: "cancelDragFrame" }
  | { readonly kind: "panViewportBy"; readonly dx: number; readonly dy: number }
  | { readonly kind: "setStoreMarquee"; readonly rect: CellMarqueeRect | null }
  | {
      readonly kind: "commitSelection";
      readonly selection: {
        readonly cardIds: readonly string[];
        readonly pipeIds: readonly string[];
      };
    }
  | { readonly kind: "toggleCardSelection"; readonly cardId: string }
  | { readonly kind: "clearSelection" }
  | { readonly kind: "invokePaneClick" }
  | {
      readonly kind: "setStoreDraggingCards";
      readonly cardIds: readonly string[];
    }
  | {
      readonly kind: "notifyDragProgress";
      readonly moves: readonly CellCardMove[] | null;
    }
  | {
      readonly kind: "commitMoveCards";
      readonly moves: readonly CellCardMove[];
    }
  | {
      readonly kind: "setMergeTarget";
      readonly target: {
        readonly cardId: string;
        readonly itemCount: number;
      } | null;
    }
  | {
      readonly kind: "setSpreadInsertTarget";
      readonly target: SpreadInsertTarget | null;
    }
  | {
      readonly kind: "startStackTucks";
      readonly joins: readonly StackTuckJoin[];
    }
  | {
      readonly kind: "commitMergeArtifactCards";
      readonly cardId: string;
      readonly targetCardId: string;
    }
  | {
      readonly kind: "commitInsertArtifactCardIntoSequence";
      readonly cardId: string;
      readonly spreadCardId: string;
      readonly insertIndex: number;
    }
  | { readonly kind: "setStoreResizingCard"; readonly cardId: string | null }
  | { readonly kind: "commitResizeCard"; readonly commit: CellResizeCommit }
  | { readonly kind: "setStoreActivePortKey"; readonly key: string | null }
  | { readonly kind: "commitConnect"; readonly ends: CellConnectionEnds }
  | {
      readonly kind: "notifyConnectDropEmpty";
      readonly event: CellConnectDropEmptyEvent;
    };

type Exec = ExecEffect<CellCanvasInteractionEffect>;
type State = CellCanvasInteractionState;

const IDLE_PHASE: CellCanvasGesturePhase = { kind: "idle" };

export function createInitialCellCanvasInteractionState(): CellCanvasInteractionState {
  return {
    phase: IDLE_PHASE,
    dragFrame: null,
    lastConnectDropEmpty: null,
    rerouteCount: 0,
  };
}

interface PortRef {
  card: CellCardModel;
  port: CellPort;
}

export function isUnderCardsFrame(
  cardId: string,
  surfaceById: Readonly<Record<string, CellCardSurfaceData>>,
): boolean {
  const surface = surfaceById[cardId];
  return surface?.kind === "annotation" && surface.variant === "frame";
}

export function resolvePortColor(
  artifactTypeId: string,
  port?: CellPort,
): string {
  if (port?.kind === "service") return tokens.colorAccent;
  return artifactTypeColor(artifactTypeId, tokens.colorMuted);
}

export function portColor(port: CellPort): string {
  return resolvePortColor(port.artifactTypeId, port);
}

export function wellKey(
  cardId: string,
  direction: CellPort["direction"],
  portId: string,
): string {
  return `${cardId}:${cellPortKey(direction, portId)}`;
}

function allCardPorts(
  card: CellCardModel,
  surface: CellCardSurfaceData | undefined,
): readonly CellPort[] {
  if (surface?.kind !== "operator" || !surface.instancePlugGroups?.length) {
    return card.ports;
  }
  const listed = new Set(card.ports.map((port) => port.id));
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

export function indexGraph(
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
      new Map(
        ports.map((port) => [cellPortKey(port.direction, port.id), port]),
      ),
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

/** Adds the port's well unless one is already bored there: one per port. */
function addWell(
  wells: StageWell[],
  keys: Set<string>,
  skip: ReadonlySet<string> | null,
  ref: PortRef,
  centre: WorldPoint,
  exit: CellDir,
  pipeColorValue: string,
  pipeTwin: boolean,
): void {
  const key = wellKey(ref.card.id, ref.port.direction, ref.port.id);
  if (keys.has(key) || skip?.has(key)) return;
  keys.add(key);
  wells.push({
    key,
    centre,
    exit,
    pipeColor: pipeColorValue,
    portColor: portColor(ref.port),
    portSequence: ref.port.shape === "many",
    pipeTwin,
  });
}

export function restingScene(
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
    addWell(
      wells,
      wellKeys,
      null,
      source,
      portWorldCenter(source.card, source.port),
      routed.sourceExit,
      color,
      sequence,
    );
    addWell(
      wells,
      wellKeys,
      null,
      target,
      portWorldCenter(target.card, target.port),
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

function liveCentre(
  drag: DragFrameSource,
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
  drag: DragFrameSource,
  ref: PortRef,
  offset: WorldPoint,
): WorldPoint {
  return drag.session.movingCardIds.has(ref.card.id)
    ? portAnchorCenter(ref.card, ref.port, true, offset)
    : portAnchorCenter(ref.card, ref.port, true);
}

/** Steps every attached pipe to `now` and draws the moving scene. */
export function buildDragFrame(
  drag: DragFrameSource,
  index: GraphIndex,
  now: number,
): { readonly frame: DragFrameState; readonly pipes: readonly PipeMotion[] } {
  const visualOrigin = drag.cellSettle.current;
  const anchorInitial = drag.session.anchorInitialCell;
  const visualOffset = {
    x: visualOrigin.x - anchorInitial.col * CELL_SIZE,
    y: visualOrigin.y - anchorInitial.row * CELL_SIZE,
  };
  const movingPipes: StagePipe[] = [];
  const movingWells: StageWell[] = [];
  const drawnWellKeys = new Set<string>();
  const pipes: PipeMotion[] = [];

  for (const motion of drag.pipes) {
    if (motion.dockedAtCurrentCell) {
      pipes.push(motion);
      continue;
    }
    let basePoints = motion.toPoints;
    let morphing = motion.morphing;
    if (motion.morphing) {
      const progress = (now - motion.morphStartMs) / MORPH_DURATION_MS;
      basePoints = morphPipePoints(
        motion.fromPoints,
        motion.toPoints,
        progress,
      );
      morphing = progress < 1;
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
    if (!sourceCentre || !targetCentre || !source || !target) {
      pipes.push(
        morphing === motion.morphing ? motion : { ...motion, morphing },
      );
      continue;
    }
    const anchored = anchorPipeEndpoints(
      basePoints,
      sourceCentre,
      motion.sourceExit,
      targetCentre,
      motion.targetExit,
    );
    const nextMotion: PipeMotion =
      morphing === motion.morphing && anchored === motion.currentPoints
        ? motion
        : { ...motion, morphing, currentPoints: anchored };
    pipes.push(nextMotion);
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
      drawnWellKeys,
      drag.restingWellKeys,
      source,
      sourceCentre,
      motion.sourceExit,
      motion.color,
      motion.sequence,
    );
    addWell(
      movingWells,
      drawnWellKeys,
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
    frame: {
      anchorCardId: drag.anchorCardId,
      snappedDelta: drag.session.currentDelta,
      visualOffset,
      showGhostCells: !drag.pointerReleased,
      ghostBoxes,
      movingPipes,
      movingWells,
    },
    pipes,
  };
}

export function seedPipeMotions(
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

/**
 * An orthogonal preview from a port: out along its side for at least a stub,
 * across at the halfway line, then on to the end.
 */
export function previewPoints(
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

export function findWireTarget(
  fromCardId: string,
  fromPort: CellPort,
  cursor: WorldPoint,
  cards: readonly CellCardModel[],
  surfaces: Readonly<Record<string, CellCardSurfaceData>>,
  punched: boolean,
  canConnect: ((candidate: CellConnectionEnds) => boolean) | undefined,
): WireTarget | null {
  const wanted = fromPort.direction === "output" ? "input" : "output";
  let target: WireTarget | null = null;
  let nearest = WIRE_SNAP_RADIUS;
  for (const other of cards) {
    if (other.id === fromCardId) continue;
    for (const candidate of allCardPorts(other, surfaces[other.id])) {
      if (candidate.direction !== wanted) continue;
      if (
        canConnect &&
        !canConnect(connectionEnds(fromCardId, fromPort, other.id, candidate))
      ) {
        continue;
      }
      const centre = portAnchorCenter(other, candidate, punched);
      const distance = Math.hypot(centre.x - cursor.x, centre.y - cursor.y);
      if (distance <= nearest) {
        nearest = distance;
        target = { cardId: other.id, port: candidate, centre };
      }
    }
  }
  return target;
}

function connectionEnds(
  fromCardId: string,
  fromPort: CellPort,
  otherCardId: string,
  otherPort: CellPort,
): CellConnectionEnds {
  const fromOutput = fromPort.direction === "output";
  return {
    sourceCardId: fromOutput ? fromCardId : otherCardId,
    sourcePortId: fromOutput ? fromPort.id : otherPort.id,
    targetCardId: fromOutput ? otherCardId : fromCardId,
    targetPortId: fromOutput ? otherPort.id : fromPort.id,
  };
}

function activePortKey(target: WireTarget | null): string | null {
  return target
    ? wellKey(target.cardId, target.port.direction, target.port.id)
    : null;
}

function sameWireTarget(a: WireTarget | null, b: WireTarget | null): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  return (
    a.cardId === b.cardId &&
    a.port.id === b.port.id &&
    a.port.direction === b.port.direction &&
    a.centre.x === b.centre.x &&
    a.centre.y === b.centre.y
  );
}

function selectionAfterPress(
  selected: ReadonlySet<string>,
  cardId: string,
  shiftKey: boolean,
  wasSelectedBefore: boolean,
): ReadonlySet<string> {
  if (shiftKey) {
    const next = new Set(selected);
    if (!next.delete(cardId)) next.add(cardId);
    return next;
  }
  if (!wasSelectedBefore) return new Set([cardId]);
  return selected;
}

function effectiveMovingIds(
  selected: ReadonlySet<string>,
  cardId: string,
  surfaces: Readonly<Record<string, CellCardSurfaceData>>,
  draggingFrame: boolean,
): ReadonlySet<string> {
  if (draggingFrame) return new Set([cardId]);
  const next = new Set<string>();
  for (const id of selected) {
    if (!isUnderCardsFrame(id, surfaces)) next.add(id);
  }
  next.add(cardId);
  return next;
}

function obstacleForeground(
  foreground: readonly CellCardModel[],
  openSpread: OpenSpreadSnapshot | null,
): readonly CellCardModel[] {
  if (!openSpread) return foreground;
  return foreground.map((card) =>
    card.id === openSpread.card.id
      ? {
          ...card,
          col: openSpread.layout.startCol,
          row: openSpread.layout.row,
          widthCells: openSpread.layout.totalCols,
          heightCells: openSpread.layout.heightCells,
        }
      : card,
  );
}

function movesFrom(phase: DraggingCardsPhase): CellCardMove[] {
  const moves: CellCardMove[] = [];
  for (const [cardId, initial] of phase.session.initialCells) {
    moves.push({
      cardId,
      col: initial.col + phase.landingDelta.col,
      row: initial.row + phase.landingDelta.row,
    });
  }
  return moves;
}

function resolveLanding(
  phase: DraggingCardsPhase,
  delta: CellCoord,
): CellCoord {
  if (phase.draggingFrame) return delta;
  return resolveNonOverlappingDelta(
    phase.obstacleForegroundAtPickup,
    phase.session.movingCardIds,
    delta,
  );
}

function sameSpreadInsert(
  current: SpreadInsertTarget | null,
  next: SpreadInsertTarget,
): boolean {
  return (
    current?.spreadCardId === next.spreadCardId &&
    current.slot === next.slot &&
    current.insertIndex === next.insertIndex
  );
}

function cancelDrag(
  state: State,
  phase: DraggingCardsPhase,
  exec: Exec,
): State {
  exec({ kind: "detachWindowGesture" });
  exec({ kind: "cancelDragFrame" });
  if (phase.spreadInsert) {
    exec({ kind: "setSpreadInsertTarget", target: null });
  }
  if (phase.mergeTargetId !== null) {
    exec({ kind: "setMergeTarget", target: null });
  }
  if (phase.movedBeyondClick) {
    exec({ kind: "notifyDragProgress", moves: null });
    exec({ kind: "setStoreDraggingCards", cardIds: [] });
  }
  return { ...state, phase: IDLE_PHASE, dragFrame: null };
}

/** Drops the active gesture and emits its cleanup before the next one starts. */
function cancelActive(state: State, exec: Exec): State {
  switch (state.phase.kind) {
    case "idle":
      return state;
    case "panning":
      exec({ kind: "detachWindowGesture" });
      return { ...state, phase: IDLE_PHASE };
    case "marquee":
      exec({ kind: "detachWindowGesture" });
      exec({ kind: "setStoreMarquee", rect: null });
      return { ...state, phase: IDLE_PHASE };
    case "draggingCards":
      return cancelDrag(state, state.phase, exec);
    case "resizingCard":
      exec({ kind: "setStoreResizingCard", cardId: null });
      return { ...state, phase: IDLE_PHASE };
    case "connectingPipe":
      exec({ kind: "detachWindowGesture" });
      exec({ kind: "setStoreActivePortKey", key: null });
      return { ...state, phase: IDLE_PHASE };
    default: {
      const exhaustive: never = state.phase;
      return exhaustive;
    }
  }
}

function onStartPan(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "startPan" }>,
  exec: Exec,
): State {
  const base = cancelActive(state, exec);
  exec({ kind: "clearSelection" });
  exec({ kind: "invokePaneClick" });
  exec({
    kind: "attachWindowGesture",
    gesture: "pan",
    pointerId: action.pointerId,
  });
  return {
    ...base,
    phase: {
      kind: "panning",
      pointerId: action.pointerId,
      lastClient: action.clientPoint,
    },
  };
}

function onPanMove(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "panMove" }>,
  exec: Exec,
): State {
  if (
    state.phase.kind !== "panning" ||
    state.phase.pointerId !== action.pointerId
  ) {
    return state;
  }
  const dx = action.clientPoint.x - state.phase.lastClient.x;
  const dy = action.clientPoint.y - state.phase.lastClient.y;
  if (dx === 0 && dy === 0) return state;
  exec({ kind: "panViewportBy", dx, dy });
  return {
    ...state,
    phase: { ...state.phase, lastClient: action.clientPoint },
  };
}

function onPanEnd(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "panEnd" }>,
  exec: Exec,
): State {
  if (
    state.phase.kind !== "panning" ||
    state.phase.pointerId !== action.pointerId
  ) {
    return state;
  }
  exec({ kind: "detachWindowGesture" });
  return { ...state, phase: IDLE_PHASE };
}

function onStartMarquee(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "startMarquee" }>,
  exec: Exec,
): State {
  const base = cancelActive(state, exec);
  const rect = { start: action.worldPoint, current: action.worldPoint };
  exec({ kind: "setStoreMarquee", rect });
  exec({
    kind: "attachWindowGesture",
    gesture: "marquee",
    pointerId: action.pointerId,
  });
  return {
    ...base,
    phase: {
      kind: "marquee",
      pointerId: action.pointerId,
      start: action.worldPoint,
      current: action.worldPoint,
    },
  };
}

function onMarqueeMove(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "marqueeMove" }>,
  exec: Exec,
): State {
  if (
    state.phase.kind !== "marquee" ||
    state.phase.pointerId !== action.pointerId
  ) {
    return state;
  }
  const rect = { start: state.phase.start, current: action.worldPoint };
  exec({ kind: "setStoreMarquee", rect });
  exec({
    kind: "commitSelection",
    selection: {
      cardIds: cardsInMarqueeRect(action.foregroundCards, rect),
      pipeIds: pipesInMarqueeRect(action.routedPipes, rect),
    },
  });
  return { ...state, phase: { ...state.phase, current: action.worldPoint } };
}

function onMarqueeEnd(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "marqueeEnd" }>,
  exec: Exec,
): State {
  if (
    state.phase.kind !== "marquee" ||
    state.phase.pointerId !== action.pointerId
  ) {
    return state;
  }
  exec({ kind: "detachWindowGesture" });
  exec({ kind: "setStoreMarquee", rect: null });
  return { ...state, phase: IDLE_PHASE };
}

function applyPressSelection(
  action: Extract<CellCanvasInteractionAction, { kind: "cardPointerDown" }>,
  exec: Exec,
): void {
  if (action.shiftKey) {
    exec({ kind: "toggleCardSelection", cardId: action.cardId });
    return;
  }
  if (!action.wasSelectedBefore) {
    exec({
      kind: "commitSelection",
      selection: { cardIds: [action.cardId], pipeIds: [] },
    });
  }
}

function onCardPointerDown(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "cardPointerDown" }>,
  exec: Exec,
): State {
  const base = cancelActive(state, exec);
  const card = action.index.cardsById.get(action.cardId);
  if (!card) return base;
  applyPressSelection(action, exec);
  if (!action.editable) return base;

  const draggingFrame = isUnderCardsFrame(action.cardId, action.surfaces);
  const selected = selectionAfterPress(
    action.selectedCardIds,
    action.cardId,
    action.shiftKey,
    action.wasSelectedBefore,
  );
  const movingIds = effectiveMovingIds(
    selected,
    action.cardId,
    action.surfaces,
    draggingFrame,
  );
  const foregroundAtPickup = action.graph.cards.filter(
    (item) => !isUnderCardsFrame(item.id, action.surfaces),
  );
  const session = createGroupDragSession(
    action.graph.cards,
    movingIds,
    action.cardId,
    action.worldPoint,
  );
  const canMerge = action.canMergeArtifactCards;
  const mergeable =
    movingIds.size === 1 &&
    canMerge !== null &&
    (action.hasMergeCallback || action.hasInsertCallback) &&
    artifactCardItemCount(action.surfaces[action.cardId]) !== null;

  exec({
    kind: "attachWindowGesture",
    gesture: "drag",
    pointerId: action.pointerId,
  });
  const phase: DraggingCardsPhase = {
    kind: "draggingCards",
    pointerId: action.pointerId,
    anchorCardId: action.cardId,
    startClient: action.clientPoint,
    movedBeyondClick: false,
    pointerReleased: false,
    shiftPressed: action.shiftKey,
    wasSelectedBefore: action.wasSelectedBefore,
    draggingFrame,
    originWorld: cellToWorldOrigin(card.col, card.row),
    session,
    cellSettle: createCardSettle(cellToWorldOrigin(card.col, card.row)),
    landingDelta: { col: 0, row: 0 },
    attachedPipeIds: new Set(),
    restingWellKeys: new Set(),
    pipes: [],
    punched: action.punched,
    graphAtPickup: action.graph,
    surfacesAtPickup: action.surfaces,
    indexAtPickup: action.index,
    routingAtPickup: action.routing,
    dockingAtPickup: action.docking,
    layoutAtPickup: action.layout,
    foregroundAtPickup,
    obstacleForegroundAtPickup: obstacleForeground(
      foregroundAtPickup,
      action.openSpread,
    ),
    openSpreadAtPickup: action.openSpread,
    mergeable,
    mergeTargetId: null,
    mergeItemCount: 0,
    spreadInsert: null,
    canMergeArtifactCards: canMerge,
    hasMergeCallback: action.hasMergeCallback,
    hasInsertCallback: action.hasInsertCallback,
  };
  return { ...base, phase, dragFrame: null };
}

function activateDrag(phase: DraggingCardsPhase): DraggingCardsPhase {
  const cellSettle = createCardSettle(phase.originWorld);
  const landingDelta = resolveLanding(phase, phase.session.currentDelta);
  const split = restingScene(
    phase.graphAtPickup,
    phase.indexAtPickup,
    phase.layoutAtPickup,
    phase.dockingAtPickup.dockedPipeIds,
    phase.session.movingCardIds,
    phase.punched,
  );
  return {
    ...phase,
    movedBeyondClick: true,
    cellSettle,
    landingDelta,
    attachedPipeIds: split.attachedPipeIds,
    restingWellKeys: split.wellKeys,
    pipes: seedPipeMotions(
      phase.graphAtPickup,
      phase.indexAtPickup,
      phase.layoutAtPickup,
      phase.dockingAtPickup.dockedPipeIds,
      split.attachedPipeIds,
    ),
  };
}

function trackMergeTarget(
  phase: DraggingCardsPhase,
  at: WorldPoint,
  openSpread: OpenSpreadSnapshot | null,
  exec: Exec,
): DraggingCardsPhase {
  if (!phase.mergeable || !phase.canMergeArtifactCards) return phase;
  const canMerge = phase.canMergeArtifactCards;
  const pickup = phase.openSpreadAtPickup;
  if (
    pickup &&
    pickup.card.id !== phase.anchorCardId &&
    phase.hasInsertCallback &&
    canMerge(phase.anchorCardId, pickup.card.id)
  ) {
    const live = openSpread?.card.id === pickup.card.id ? openSpread : pickup;
    const hit = findSpreadInsertTarget({
      spreadCardId: pickup.card.id,
      layout: pickup.layout,
      windowStart: live.windowStart,
      itemCount: live.itemCount,
      cardWidthCells: pickup.card.widthCells,
      point: at,
    });
    if (hit) {
      let next = phase;
      if (phase.mergeTargetId !== null) {
        next = { ...next, mergeTargetId: null, mergeItemCount: 0 };
        exec({ kind: "setMergeTarget", target: null });
      }
      if (!sameSpreadInsert(phase.spreadInsert, hit)) {
        next = { ...next, spreadInsert: hit };
        exec({ kind: "setSpreadInsertTarget", target: hit });
      }
      return next;
    }
  }

  let next = phase;
  if (phase.spreadInsert !== null) {
    next = { ...next, spreadInsert: null };
    exec({ kind: "setSpreadInsertTarget", target: null });
  }
  if (!phase.hasMergeCallback) return next;
  const mergeCandidates = pickup
    ? phase.foregroundAtPickup.filter((card) => card.id !== pickup.card.id)
    : phase.foregroundAtPickup;
  const found = findArtifactMergeTarget(
    mergeCandidates,
    phase.surfacesAtPickup,
    phase.anchorCardId,
    at,
    canMerge,
  );
  if (found === next.mergeTargetId) return next;
  const itemCount = found
    ? (artifactCardItemCount(phase.surfacesAtPickup[phase.anchorCardId]) ?? 1) +
      (artifactCardItemCount(phase.surfacesAtPickup[found]) ?? 1)
    : 0;
  exec({
    kind: "setMergeTarget",
    target: found ? { cardId: found, itemCount } : null,
  });
  return { ...next, mergeTargetId: found, mergeItemCount: itemCount };
}

function morphPipesToCell(
  phase: DraggingCardsPhase,
  snappedDelta: CellCoord,
  now: number,
): DraggingCardsPhase {
  const anchorTarget = {
    col: phase.session.anchorInitialCell.col + snappedDelta.col,
    row: phase.session.anchorInitialCell.row + snappedDelta.row,
  };
  const cellSettle = retargetCardSettle(
    phase.cellSettle,
    cellToWorldOrigin(anchorTarget.col, anchorTarget.row),
    now,
  );
  const movedForeground = phase.graphAtPickup.cards
    .map((card) => {
      if (!phase.session.movingCardIds.has(card.id)) return card;
      const initial = phase.session.initialCells.get(card.id);
      if (!initial) return card;
      return {
        ...card,
        col: initial.col + snappedDelta.col,
        row: initial.row + snappedDelta.row,
      };
    })
    .filter((card) => !isUnderCardsFrame(card.id, phase.surfacesAtPickup));
  const movedDocking = detectCellDockedJoins(
    { cards: movedForeground, pipes: phase.graphAtPickup.pipes },
    resolvePortColor,
    { punched: phase.punched },
  );
  const rerouted = routeCellGraph(
    { cards: movedForeground, pipes: movedDocking.routablePipes },
    phase.routingAtPickup,
    phase.attachedPipeIds,
  );
  const pipes = phase.pipes.map((motion) => {
    if (movedDocking.dockedPipeIds.has(motion.id)) {
      return { ...motion, dockedAtCurrentCell: true, morphing: false };
    }
    const routed = rerouted.pipes.get(motion.id);
    if (!routed) return { ...motion, dockedAtCurrentCell: false };
    return {
      ...motion,
      dockedAtCurrentCell: false,
      fromPoints: motion.currentPoints,
      toPoints: routed.points,
      sourceExit: routed.sourceExit,
      targetExit: routed.targetExit,
      depth: routed.depth,
      morphStartMs: now,
      morphing: true,
    };
  });
  return { ...phase, cellSettle, pipes };
}

function onDragMove(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "dragMove" }>,
  exec: Exec,
): State {
  if (
    state.phase.kind !== "draggingCards" ||
    state.phase.pointerId !== action.pointerId ||
    state.phase.pointerReleased
  ) {
    return state;
  }
  let next = state.phase;
  let activated = false;
  if (!next.movedBeyondClick) {
    const travelled = Math.hypot(
      action.clientPoint.x - next.startClient.x,
      action.clientPoint.y - next.startClient.y,
    );
    if (travelled < DRAG_THRESHOLD_PX) return state;
    next = activateDrag(next);
    activated = true;
    exec({ kind: "notifyDragProgress", moves: movesFrom(next) });
  }
  next = trackMergeTarget(next, action.worldPoint, action.openSpread, exec);
  const step = updateGroupDragSession(
    next.session,
    next.graphAtPickup.cards,
    action.worldPoint,
  );
  next = { ...next, session: step.session };
  let rerouteCount = state.rerouteCount;
  if (step.changedCell) {
    next = { ...next, landingDelta: resolveLanding(next, step.snappedDelta) };
    exec({ kind: "notifyDragProgress", moves: movesFrom(next) });
    next = morphPipesToCell(next, step.snappedDelta, action.now);
    rerouteCount += 1;
  }
  let dragFrame = state.dragFrame;
  if (activated) {
    exec({
      kind: "setStoreDraggingCards",
      cardIds: [...next.session.movingCardIds],
    });
    const built = buildDragFrame(next, next.indexAtPickup, action.now);
    next = { ...next, pipes: built.pipes };
    dragFrame = built.frame;
  }
  exec({ kind: "scheduleDragFrame" });
  return { ...state, phase: next, dragFrame, rerouteCount };
}

function finishDrag(
  state: State,
  phase: DraggingCardsPhase,
  exec: Exec,
): State {
  exec({ kind: "detachWindowGesture" });
  exec({ kind: "cancelDragFrame" });
  exec({ kind: "notifyDragProgress", moves: null });
  if (phase.landingDelta.col !== 0 || phase.landingDelta.row !== 0) {
    exec({ kind: "commitMoveCards", moves: movesFrom(phase) });
  }
  exec({ kind: "setStoreDraggingCards", cardIds: [] });
  return { ...state, phase: IDLE_PHASE, dragFrame: null };
}

function onDragUp(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "dragUp" }>,
  exec: Exec,
): State {
  if (
    state.phase.kind !== "draggingCards" ||
    state.phase.pointerId !== action.pointerId ||
    state.phase.pointerReleased
  ) {
    return state;
  }
  const phase = state.phase;
  if (!phase.movedBeyondClick) {
    exec({ kind: "detachWindowGesture" });
    exec({ kind: "cancelDragFrame" });
    if (!phase.shiftPressed && phase.wasSelectedBefore) {
      exec({
        kind: "commitSelection",
        selection: { cardIds: [phase.anchorCardId], pipeIds: [] },
      });
    }
    return { ...state, phase: IDLE_PHASE, dragFrame: null };
  }
  if (phase.spreadInsert) {
    const target = phase.spreadInsert;
    const cleared = cancelDrag(state, phase, exec);
    exec({
      kind: "commitInsertArtifactCardIntoSequence",
      cardId: phase.anchorCardId,
      spreadCardId: target.spreadCardId,
      insertIndex: target.insertIndex,
    });
    return cleared;
  }
  if (phase.mergeTargetId !== null) {
    const targetId = phase.mergeTargetId;
    const draggedCard = phase.indexAtPickup.cardsById.get(phase.anchorCardId);
    const targetCard = phase.indexAtPickup.cardsById.get(targetId);
    if (draggedCard && targetCard) {
      exec({
        kind: "startStackTucks",
        joins: [
          {
            card: draggedCard,
            from: stepCardSettle(phase.cellSettle, action.now).current,
            target: targetCard,
            slot: 0,
            surface: phase.surfacesAtPickup[phase.anchorCardId],
          },
        ],
      });
    }
    const cleared = cancelDrag(state, phase, exec);
    exec({
      kind: "commitMergeArtifactCards",
      cardId: phase.anchorCardId,
      targetCardId: targetId,
    });
    return cleared;
  }
  const anchorTarget = {
    col: phase.session.anchorInitialCell.col + phase.landingDelta.col,
    row: phase.session.anchorInitialCell.row + phase.landingDelta.row,
  };
  exec({ kind: "scheduleDragFrame" });
  return {
    ...state,
    phase: {
      ...phase,
      pointerReleased: true,
      cellSettle: retargetCardSettle(
        phase.cellSettle,
        cellToWorldOrigin(anchorTarget.col, anchorTarget.row),
        action.now,
      ),
    },
  };
}

function onDragTick(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "dragTick" }>,
  exec: Exec,
): State {
  if (state.phase.kind !== "draggingCards") return state;
  const cellSettle = stepCardSettle(state.phase.cellSettle, action.now);
  const built = buildDragFrame(
    { ...state.phase, cellSettle },
    action.index,
    action.now,
  );
  const stepped: DraggingCardsPhase = {
    ...state.phase,
    cellSettle,
    pipes: built.pipes,
  };
  const morphing = built.pipes.some((motion) => motion.morphing);
  if (state.phase.pointerReleased && !cellSettle.active && !morphing) {
    return finishDrag(state, stepped, exec);
  }
  if (state.phase.pointerReleased || cellSettle.active || morphing) {
    exec({ kind: "scheduleDragFrame" });
  }
  return { ...state, phase: stepped, dragFrame: built.frame };
}

function onStartResize(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "startResize" }>,
  exec: Exec,
): State {
  if (!action.editable) return state;
  const base = cancelActive(state, exec);
  const preview: CellResizeCommit = {
    cardId: action.card.id,
    widthCells: action.card.widthCells,
    heightCells: action.card.heightCells,
  };
  exec({ kind: "setStoreResizingCard", cardId: action.card.id });
  return {
    ...base,
    phase: {
      kind: "resizingCard",
      cardSnapshot: action.card,
      edge: action.edge,
      startWorld: action.startWorld,
      preview,
    },
  };
}

function resizeCommit(
  phase: Extract<CellCanvasGesturePhase, { kind: "resizingCard" }>,
  edge: CellResizeEdge,
  worldPoint: WorldPoint,
): CellResizeCommit {
  return computeCellResize(
    phase.cardSnapshot,
    edge,
    phase.startWorld,
    worldPoint,
  );
}

function sameResize(a: CellResizeCommit, b: CellResizeCommit): boolean {
  return (
    a.cardId === b.cardId &&
    a.widthCells === b.widthCells &&
    a.heightCells === b.heightCells
  );
}

function onResizeMove(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "resizeMove" }>,
): State {
  if (
    state.phase.kind !== "resizingCard" ||
    state.phase.cardSnapshot.id !== action.cardId
  ) {
    return state;
  }
  const commit = resizeCommit(state.phase, action.edge, action.worldPoint);
  if (sameResize(state.phase.preview, commit)) return state;
  return {
    ...state,
    rerouteCount: state.rerouteCount + 1,
    phase: { ...state.phase, edge: action.edge, preview: commit },
  };
}

function onResizeEnd(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "resizeEnd" }>,
  exec: Exec,
): State {
  if (state.phase.kind !== "resizingCard") return state;
  const phase = state.phase;
  exec({ kind: "setStoreResizingCard", cardId: null });
  if (phase.cardSnapshot.id !== action.cardId) {
    return { ...state, phase: IDLE_PHASE };
  }
  const commit = resizeCommit(phase, action.edge, action.worldPoint);
  if (
    commit.widthCells === phase.cardSnapshot.widthCells &&
    commit.heightCells === phase.cardSnapshot.heightCells
  ) {
    return { ...state, phase: IDLE_PHASE };
  }
  exec({ kind: "commitResizeCard", commit });
  return { ...state, phase: IDLE_PHASE, rerouteCount: state.rerouteCount + 1 };
}

function onStartConnect(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "startConnect" }>,
  exec: Exec,
): State {
  const base = cancelActive(state, exec);
  const target = findWireTarget(
    action.fromCardId,
    action.fromPort,
    action.cursor,
    action.cards,
    action.surfaces,
    action.punched,
    action.canConnect,
  );
  exec({ kind: "setStoreActivePortKey", key: activePortKey(target) });
  exec({
    kind: "attachWindowGesture",
    gesture: "connect",
    pointerId: action.pointerId,
  });
  return {
    ...base,
    phase: {
      kind: "connectingPipe",
      pointerId: action.pointerId,
      fromCardId: action.fromCardId,
      fromPort: action.fromPort,
      cursor: action.cursor,
      target,
    },
  };
}

function onConnectMove(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "connectMove" }>,
  exec: Exec,
): State {
  if (
    state.phase.kind !== "connectingPipe" ||
    state.phase.pointerId !== action.pointerId
  ) {
    return state;
  }
  const target = findWireTarget(
    state.phase.fromCardId,
    state.phase.fromPort,
    action.cursor,
    action.cards,
    action.surfaces,
    action.punched,
    action.canConnect,
  );
  if (
    state.phase.cursor.x === action.cursor.x &&
    state.phase.cursor.y === action.cursor.y &&
    sameWireTarget(state.phase.target, target)
  ) {
    return state;
  }
  const previousKey = activePortKey(state.phase.target);
  const nextKey = activePortKey(target);
  if (previousKey !== nextKey) {
    exec({ kind: "setStoreActivePortKey", key: nextKey });
  }
  return {
    ...state,
    phase: { ...state.phase, cursor: action.cursor, target },
  };
}

function onConnectEnd(
  state: State,
  action: Extract<CellCanvasInteractionAction, { kind: "connectEnd" }>,
  exec: Exec,
): State {
  if (
    state.phase.kind !== "connectingPipe" ||
    state.phase.pointerId !== action.pointerId
  ) {
    return state;
  }
  const phase = state.phase;
  exec({ kind: "detachWindowGesture" });
  exec({ kind: "setStoreActivePortKey", key: null });
  if (action.isCancel) return { ...state, phase: IDLE_PHASE };
  if (phase.target === null) {
    const event: CellConnectDropEmptyEvent = {
      sourceCardId: phase.fromCardId,
      sourcePortId: phase.fromPort.id,
      direction:
        phase.fromPort.direction === "output" ? "downstream" : "upstream",
      worldPoint: phase.cursor,
      targetCell: {
        col: Math.floor(phase.cursor.x / CELL_SIZE),
        row: Math.floor(phase.cursor.y / CELL_SIZE),
      },
      clientPoint: action.clientPoint,
    };
    exec({ kind: "notifyConnectDropEmpty", event });
    return { ...state, phase: IDLE_PHASE, lastConnectDropEmpty: event };
  }
  exec({
    kind: "commitConnect",
    ends: connectionEnds(
      phase.fromCardId,
      phase.fromPort,
      phase.target.cardId,
      phase.target.port,
    ),
  });
  return { ...state, phase: IDLE_PHASE };
}

export const cellCanvasInteractionReducer: EffectReducer<
  CellCanvasInteractionState,
  CellCanvasInteractionAction,
  CellCanvasInteractionEffect
> = (state, action, exec) => {
  switch (action.kind) {
    case "startPan":
      return onStartPan(state, action, exec);
    case "panMove":
      return onPanMove(state, action, exec);
    case "panEnd":
      return onPanEnd(state, action, exec);
    case "startMarquee":
      return onStartMarquee(state, action, exec);
    case "marqueeMove":
      return onMarqueeMove(state, action, exec);
    case "marqueeEnd":
      return onMarqueeEnd(state, action, exec);
    case "cardPointerDown":
      return onCardPointerDown(state, action, exec);
    case "dragMove":
      return onDragMove(state, action, exec);
    case "dragUp":
      return onDragUp(state, action, exec);
    case "dragTick":
      return onDragTick(state, action, exec);
    case "startResize":
      return onStartResize(state, action, exec);
    case "resizeMove":
      return onResizeMove(state, action);
    case "resizeEnd":
      return onResizeEnd(state, action, exec);
    case "startConnect":
      return onStartConnect(state, action, exec);
    case "connectMove":
      return onConnectMove(state, action, exec);
    case "connectEnd":
      return onConnectEnd(state, action, exec);
    case "cancelGesture":
      return cancelActive(state, exec);
    default: {
      const exhaustive: never = action;
      return exhaustive;
    }
  }
};
