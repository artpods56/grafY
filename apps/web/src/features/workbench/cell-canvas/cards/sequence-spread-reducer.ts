import type { EffectReducer, ExecEffect } from "@/lib/state/effect-reducer";

import type { ArtifactStackItem } from "../cell-contracts";
import type { OpenSequenceSpreadLayout } from "../cell-artifact-stacking";
import { resolveNonOverlappingDelta } from "../cell-group-drag";
import {
  CELL_SIZE,
  type CellCardModel,
  type CellCoord,
  type WorldPoint,
} from "../cell-model";
import {
  createCardSettle,
  retargetCardSettle,
  stepCardSettle,
  type CardSettleState,
} from "../cell-transitions";

/**
 * How many backs a stack draws at most. Matches `STACK_BACKS.length` in
 * `CellArtifactCard.tsx`. Defined here so this module does not import that
 * file: it calls `stylex.create`, and a value import from it fails StyleX.
 */
export const STACK_BACK_COUNT = 2;

/** How far the dashed frame stands outside the plates' cells. */
export const FRAME_OUTSET = 6;
/** Screen pixels a press travels before it becomes a drag. */
const DRAG_THRESHOLD_PX = 4;
/** How long a dragged card rests on a side stack before the window steps. */
export const STACK_HOVER_STEP_MS = 350;
/** Horizontal wheel pixels per step. */
const WHEEL_STEP_PX = 40;

const LANDING_ID = "\u0000sequence-spread-landing";
const FRAME_ID = "\u0000sequence-spread-frame";
const MOVE_ID = "\u0000sequence-spread-move";

const EMPTY_MOTION: ReadonlyMap<string, CardSettleState> = new Map();
const EMPTY_SIBLINGS: ReadonlyMap<number, CardSettleState> = new Map();

export type DragMode = "reorder" | "left" | "right" | "extract" | "none";

export interface ItemDragView {
  from: number;
  /** The slot it was picked up from. */
  slot: number;
  /** Current spring-settled position of the held card inside the spread root. */
  pos: WorldPoint;
  /** Current spring-settled x positions of displaced siblings. */
  siblingX: ReadonlyMap<number, number>;
  mode: DragMode;
  /** Slot the held card currently occupies while reordering. */
  targetSlot: number;
  landing: CellCoord | null;
}

export interface SpreadMoveView {
  offset: WorldPoint;
  landingDelta: CellCoord;
}

/** A card a narrowing resize retired, for as long as it glides away. */
export interface ResizeTuck {
  key: string;
  index: number;
  item: ArtifactStackItem;
}

/** A middle card a multi-slot step retired into the covered side stack. */
export interface StepTuck {
  key: string;
  item: ArtifactStackItem;
  targetX: number;
}

/** Syncs slot 0's collapsed stack backs to the fold glide into `x = 0`. */
export interface FoldBackSync {
  driverKey: string;
  startX: number;
  targetX: number;
}

/**
 * The end-slot card a step covers: it stays put beneath the incoming card
 * until the step settles, while its plate and backs cascade down in depth
 * with the incoming card's glide.
 */
export interface UnderCard {
  side: "left" | "right";
  index: number;
  /** Items in the stack it topped, or 0 when it was an open card. */
  stackCount: number;
  /** Depth layers the covered stack sinks by (1 for a step, 2 for a page jump). */
  shift: number;
  /** Incoming card's spring key and horizontal travel, driving synced depth. */
  coverKey: string;
  coverStartX: number;
  coverTargetX: number;
  /** Opposite side stack uncovered by this step, if any. */
  reveal: { side: "left" | "right"; shift: number } | null;
  /** The list and row it was captured for; a change to either drops it. */
  items: readonly ArtifactStackItem[];
  visibleCount: number;
}

/**
 * Syncs a right-edge stack's backs to the resize glide so backs fan out as
 * cards tuck under or glide out from a resized spread.
 */
export interface ResizeBackSync {
  driverKey: string;
  startX: number;
  targetX: number;
  itemCount: number;
  visibleCount: number;
}

interface ItemDragData {
  pointerId: number;
  from: number;
  slot: number;
  startX: number;
  startY: number;
  /** The pointer's offset in the dragged card's own box, in world units. */
  grab: WorldPoint;
  active: boolean;
  mode: DragMode;
  hoverMode: DragMode;
  targetSlot: number;
  landing: CellCoord | null;
  draggedSettle: CardSettleState;
  siblingSettles: ReadonlyMap<number, CardSettleState>;
}

interface SpreadMoveData {
  pointerId: number;
  startClient: WorldPoint;
  startWorld: WorldPoint;
  active: boolean;
  landingDelta: CellCoord;
  settle: CardSettleState;
}

interface ResizeDragData {
  pointerId: number;
  startX: number;
  startCount: number;
  last: number;
}

export type SequenceSpreadPhase =
  | {
      kind: "idle";
      motionSettles: ReadonlyMap<string, CardSettleState>;
    }
  | {
      kind: "stepping";
      motionSettles: ReadonlyMap<string, CardSettleState>;
      underCard: UnderCard | null;
      stepTucks: readonly StepTuck[];
    }
  | {
      kind: "resizing";
      pointer: ResizeDragData | null;
      motionSettles: ReadonlyMap<string, CardSettleState>;
      resizeTucks: readonly ResizeTuck[];
      resizeBackSync: ResizeBackSync | null;
    }
  | {
      kind: "rewinding";
      motionSettles: ReadonlyMap<string, CardSettleState>;
      underCard: UnderCard | null;
      stepTucks: readonly StepTuck[];
    }
  | {
      kind: "folding";
      motionSettles: ReadonlyMap<string, CardSettleState>;
      foldBackSync: FoldBackSync | null;
    }
  | {
      kind: "draggingItem";
      drag: ItemDragData;
      motionSettles: ReadonlyMap<string, CardSettleState>;
      underCard: UnderCard | null;
      stepTucks: readonly StepTuck[];
      resizeTucks: readonly ResizeTuck[];
      resizeBackSync: ResizeBackSync | null;
    }
  | {
      kind: "movingSpread";
      move: SpreadMoveData;
      motionSettles: ReadonlyMap<string, CardSettleState>;
      underCard: UnderCard | null;
      stepTucks: readonly StepTuck[];
      resizeTucks: readonly ResizeTuck[];
      resizeBackSync: ResizeBackSync | null;
    };

export interface SequenceSpreadState {
  windowStart: number;
  visibleCount: number;
  items: readonly ArtifactStackItem[];
  activeIndex: number | null;
  hoveredIndex: number | null;
  menuIndex: number | null;
  wheelAccumPx: number;
  phase: SequenceSpreadPhase;
}

export interface SequenceSpreadInit {
  items: readonly ArtifactStackItem[];
  layout: OpenSequenceSpreadLayout;
  animateMotion: boolean;
}

/** Geometry a pointer action needs. The shell fills it from the latest props. */
export interface SpreadHitScene {
  originX: number;
  originY: number;
  frameWidth: number;
  cardWidth: number;
  cardHeight: number;
  windowed: boolean;
  layoutStartCol: number;
  layoutRow: number;
  layoutTotalCols: number;
  card: CellCardModel;
  foregroundCards: readonly CellCardModel[];
  canReorder?: boolean;
  canExtract: boolean;
}

interface MotionClock {
  readonly nowMs: number;
  readonly animateMotion: boolean;
  readonly cardWidth: number;
  readonly windowed: boolean;
}

export type SequenceSpreadAction =
  | ({ readonly kind: "mounted" } & MotionClock)
  | {
      readonly kind: "syncProps";
      readonly items: readonly ArtifactStackItem[];
      readonly windowed: boolean;
      readonly previousWindowed: boolean;
      readonly layoutVisibleCount: number;
    }
  | ({ readonly kind: "step"; readonly by: number } & MotionClock)
  | ({ readonly kind: "wheel"; readonly deltaX: number } & MotionClock)
  | ({ readonly kind: "requestClose" } & MotionClock)
  | { readonly kind: "motionTick"; readonly nowMs: number }
  | { readonly kind: "dragTick"; readonly nowMs: number }
  | { readonly kind: "moveTick"; readonly nowMs: number }
  | {
      readonly kind: "itemPointerDown";
      readonly pointerId: number;
      readonly button: number;
      readonly index: number;
      readonly slot: number;
      readonly clientX: number;
      readonly clientY: number;
      readonly world: WorldPoint;
      readonly editable: boolean;
      readonly originX: number;
      readonly originY: number;
      readonly cardWidth: number;
    }
  | ({
      readonly kind: "itemPointerMove";
      readonly pointerId: number;
      readonly clientX: number;
      readonly clientY: number;
      readonly world: WorldPoint;
      readonly scene: SpreadHitScene;
    } & MotionClock)
  | {
      readonly kind: "itemPointerEnd";
      readonly pointerId: number;
      readonly clientX: number;
      readonly clientY: number;
      readonly world: WorldPoint;
      readonly cancelled: boolean;
      readonly cardId: string;
      readonly scene: SpreadHitScene;
    }
  | ({ readonly kind: "hoverStackTimerFired" } & MotionClock)
  | {
      readonly kind: "movePointerDown";
      readonly pointerId: number;
      readonly button: number;
      readonly clientX: number;
      readonly clientY: number;
      readonly world: WorldPoint;
    }
  | ({
      readonly kind: "movePointerMove";
      readonly pointerId: number;
      readonly clientX: number;
      readonly clientY: number;
      readonly world: WorldPoint;
      readonly scene: SpreadHitScene;
    } & Pick<MotionClock, "nowMs" | "animateMotion">)
  | {
      readonly kind: "movePointerEnd";
      readonly pointerId: number;
      readonly world: WorldPoint;
      readonly cancelled: boolean;
      readonly cardId: string;
      readonly scene: SpreadHitScene;
    }
  | {
      readonly kind: "resizePointerDown";
      readonly pointerId: number;
      readonly button: number;
      readonly startX: number;
    }
  | {
      readonly kind: "resizePointerMove";
      readonly pointerId: number;
      readonly worldX: number;
      readonly nowMs: number;
      readonly animateMotion: boolean;
      readonly cardWidth: number;
      readonly minVisibleCount: number;
      readonly maxVisibleCount: number;
    }
  | { readonly kind: "resizePointerEnd"; readonly pointerId: number }
  | {
      readonly kind: "keyboardReorder";
      readonly direction: -1 | 1;
      readonly cardId: string;
      readonly canReorder: boolean;
    }
  | { readonly kind: "setActiveIndex"; readonly index: number | null }
  | { readonly kind: "setHoveredIndex"; readonly index: number | null }
  | { readonly kind: "setMenuIndex"; readonly index: number | null };

export type SequenceSpreadEffect =
  | { readonly kind: "scheduleMotionFrame" }
  | { readonly kind: "cancelMotionFrame" }
  | { readonly kind: "scheduleDragFrame" }
  | { readonly kind: "cancelDragFrame" }
  | { readonly kind: "scheduleMoveFrame" }
  | { readonly kind: "cancelMoveFrame" }
  | { readonly kind: "armHoverStepTimer" }
  | { readonly kind: "clearHoverStepTimer" }
  | { readonly kind: "notifyWindowStartChange"; readonly windowStart: number }
  | {
      readonly kind: "notifyPreferredVisibleCountChange";
      readonly count: number;
    }
  | { readonly kind: "notifyClose" }
  | {
      readonly kind: "notifyReorder";
      readonly cardId: string;
      readonly fromIndex: number;
      readonly toIndex: number;
    }
  | {
      readonly kind: "notifyExtract";
      readonly cardId: string;
      readonly index: number;
      readonly targetCell: CellCoord;
    }
  | {
      readonly kind: "notifyMove";
      readonly cardId: string;
      readonly col: number;
      readonly row: number;
    };

type Exec = ExecEffect<SequenceSpreadEffect>;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function itemKey(item: ArtifactStackItem, index: number): string {
  return `${item.artifactId}:${index}`;
}

function stepTuckKey(item: ArtifactStackItem, index: number): string {
  return `step-tuck:${item.artifactId}:${index}`;
}

function resizeTuckKey(item: ArtifactStackItem, index: number): string {
  return `resize-tuck:${item.artifactId}:${index}`;
}

export function displayedWindowStart(
  windowStart: number,
  windowed: boolean,
  itemCount: number,
  visibleCount: number,
): number {
  if (!windowed) return 0;
  return clamp(windowStart, 0, Math.max(0, itemCount - visibleCount));
}

function settlesActive(settles: ReadonlyMap<string, CardSettleState>): boolean {
  for (const settle of settles.values()) {
    if (settle.active) return true;
  }
  return false;
}

function motionSettlesOf(
  phase: SequenceSpreadPhase,
): ReadonlyMap<string, CardSettleState> {
  return phase.motionSettles;
}

function underCardOf(phase: SequenceSpreadPhase): UnderCard | null {
  switch (phase.kind) {
    case "stepping":
    case "rewinding":
    case "draggingItem":
    case "movingSpread":
      return phase.underCard;
    case "idle":
    case "resizing":
    case "folding":
      return null;
    default: {
      const exhaustive: never = phase;
      return exhaustive;
    }
  }
}

function stepTucksOf(phase: SequenceSpreadPhase): readonly StepTuck[] {
  switch (phase.kind) {
    case "stepping":
    case "rewinding":
    case "draggingItem":
    case "movingSpread":
      return phase.stepTucks;
    case "idle":
    case "resizing":
    case "folding":
      return [];
    default: {
      const exhaustive: never = phase;
      return exhaustive;
    }
  }
}

function resizeTucksOf(phase: SequenceSpreadPhase): readonly ResizeTuck[] {
  switch (phase.kind) {
    case "resizing":
    case "draggingItem":
    case "movingSpread":
      return phase.resizeTucks;
    case "idle":
    case "stepping":
    case "rewinding":
    case "folding":
      return [];
    default: {
      const exhaustive: never = phase;
      return exhaustive;
    }
  }
}

function resizeBackSyncOf(phase: SequenceSpreadPhase): ResizeBackSync | null {
  switch (phase.kind) {
    case "resizing":
    case "draggingItem":
    case "movingSpread":
      return phase.resizeBackSync;
    case "idle":
    case "stepping":
    case "rewinding":
    case "folding":
      return null;
    default: {
      const exhaustive: never = phase;
      return exhaustive;
    }
  }
}

function retargetSettle(
  current: CardSettleState,
  target: WorldPoint,
  nowMs: number,
  animate: boolean,
): CardSettleState {
  if (!animate) return createCardSettle(target);
  return retargetCardSettle(current, target, nowMs);
}

function sameCell(a: CellCoord | null, b: CellCoord | null): boolean {
  if (a === null || b === null) return a === b;
  return a.col === b.col && a.row === b.row;
}

/**
 * Target sequence index when dropping `from` onto slot `targetSlot`: the card
 * lands exactly in that slot, even when the window stepped mid-drag and `from`
 * now sits in a side stack.
 */
export function reorderDropIndex(
  windowStart: number,
  targetSlot: number,
): number {
  return windowStart + targetSlot;
}

/**
 * Visual slot a sibling glides into while another open card is dragged. A card
 * held from outside the window (it stepped into a side stack mid-drag) parts
 * the row as if it came from just past that edge.
 */
export function visualSlotForSibling(
  naturalSlot: number,
  from: number,
  mode: DragMode,
  targetSlot: number,
  windowStart: number,
  visibleCount: number,
): number {
  if (mode !== "reorder") return naturalSlot;
  const fromSlot = clamp(from - windowStart, -1, visibleCount);
  if (
    fromSlot < targetSlot &&
    naturalSlot > fromSlot &&
    naturalSlot <= targetSlot
  ) {
    return naturalSlot - 1;
  }
  if (
    fromSlot > targetSlot &&
    naturalSlot >= targetSlot &&
    naturalSlot < fromSlot
  ) {
    return naturalSlot + 1;
  }
  return naturalSlot;
}

export function motionXFromPhase(
  phase: SequenceSpreadPhase,
): ReadonlyMap<string, number> {
  const settles = motionSettlesOf(phase);
  if (settles.size === 0) return new Map();
  const next = new Map<string, number>();
  for (const [key, settle] of settles) next.set(key, settle.current.x);
  return next;
}

export function dragViewFromPhase(
  phase: SequenceSpreadPhase,
): ItemDragView | null {
  if (phase.kind !== "draggingItem" || !phase.drag.active) return null;
  const siblingX = new Map<number, number>();
  for (const [index, settle] of phase.drag.siblingSettles) {
    siblingX.set(index, settle.current.x);
  }
  return {
    from: phase.drag.from,
    slot: phase.drag.slot,
    pos: {
      x: phase.drag.draggedSettle.current.x,
      y: phase.drag.draggedSettle.current.y,
    },
    siblingX,
    mode: phase.drag.mode,
    targetSlot: phase.drag.targetSlot,
    landing: phase.drag.landing,
  };
}

export function moveViewFromPhase(
  phase: SequenceSpreadPhase,
): SpreadMoveView | null {
  if (phase.kind !== "movingSpread" || !phase.move.active) return null;
  return {
    offset: { x: phase.move.settle.current.x, y: phase.move.settle.current.y },
    landingDelta: phase.move.landingDelta,
  };
}

/** True while the resize handle is held. A glide after release stays `resizing` with `pointer: null`. */
export function isResizingPhase(phase: SequenceSpreadPhase): boolean {
  return phase.kind === "resizing" && phase.pointer !== null;
}

export function isClosingPhase(phase: SequenceSpreadPhase): boolean {
  return phase.kind === "rewinding" || phase.kind === "folding";
}

export function isFoldingPhase(phase: SequenceSpreadPhase): boolean {
  return phase.kind === "folding";
}

export function settleProgress(
  motionX: ReadonlyMap<string, number>,
  key: string,
  startX: number,
  targetX: number,
): number {
  const span = Math.abs(targetX - startX);
  if (span < 0.5) return 1;
  const currentX = motionX.get(key);
  if (currentX === undefined) return 1;
  return clamp(1 - Math.abs(targetX - currentX) / span, 0, 1);
}

export function underCardFromState(
  state: SequenceSpreadState,
): UnderCard | null {
  const under = underCardOf(state.phase);
  if (!under) return null;
  if (
    under.items !== state.items ||
    under.visibleCount !== state.visibleCount
  ) {
    return null;
  }
  if (isFoldingPhase(state.phase) || isResizingPhase(state.phase)) return null;
  if (dragViewFromPhase(state.phase) !== null) return null;
  return under;
}

export function stepTucksFromPhase(
  phase: SequenceSpreadPhase,
): readonly StepTuck[] {
  if (isFoldingPhase(phase) || dragViewFromPhase(phase) !== null) return [];
  return stepTucksOf(phase);
}

export function resizeTucksFromPhase(
  phase: SequenceSpreadPhase,
): readonly ResizeTuck[] {
  if (dragViewFromPhase(phase) !== null || isClosingPhase(phase)) return [];
  return resizeTucksOf(phase);
}

export function resizeBackSyncFromState(
  state: SequenceSpreadState,
): ResizeBackSync | null {
  const sync = resizeBackSyncOf(state.phase);
  if (!sync) return null;
  if (
    sync.itemCount !== state.items.length ||
    sync.visibleCount !== state.visibleCount
  ) {
    return null;
  }
  if (dragViewFromPhase(state.phase) !== null || isClosingPhase(state.phase)) {
    return null;
  }
  if (underCardFromState(state) !== null) return null;
  return sync;
}

export function foldBackSyncFromPhase(
  phase: SequenceSpreadPhase,
): FoldBackSync | null {
  if (phase.kind !== "folding") return null;
  return phase.foldBackSync;
}

export function foldProgressFromState(state: SequenceSpreadState): number {
  const sync = foldBackSyncFromPhase(state.phase);
  if (!isFoldingPhase(state.phase) || sync === null) return 0;
  return settleProgress(
    motionXFromPhase(state.phase),
    sync.driverKey,
    sync.startX,
    sync.targetX,
  );
}

export function createInitialSequenceSpreadState(
  ctx: SequenceSpreadInit,
): SequenceSpreadState {
  const visibleCount = Math.min(ctx.layout.visibleCount, ctx.items.length);
  const motionSettles = new Map<string, CardSettleState>();
  if (ctx.animateMotion) {
    for (let slot = 1; slot < visibleCount; slot += 1) {
      const item = ctx.items[slot];
      if (!item) continue;
      motionSettles.set(itemKey(item, slot), createCardSettle({ x: 0, y: 0 }));
    }
  }
  return {
    windowStart: 0,
    visibleCount,
    items: ctx.items,
    activeIndex: null,
    hoveredIndex: null,
    menuIndex: null,
    wheelAccumPx: 0,
    phase: { kind: "idle", motionSettles },
  };
}

function onMounted(
  state: SequenceSpreadState,
  action: MotionClock,
  exec: Exec,
): SequenceSpreadState {
  if (!action.animateMotion || state.phase.kind !== "idle") return state;
  const open = state.visibleCount;
  const start = displayedWindowStart(
    state.windowStart,
    action.windowed,
    state.items.length,
    open,
  );
  const settles = new Map<string, CardSettleState>();
  let anyActive = false;
  for (let slot = 1; slot < open; slot += 1) {
    const item = state.items[start + slot];
    if (!item) continue;
    const settle = retargetCardSettle(
      createCardSettle({ x: 0, y: 0 }),
      { x: slot * action.cardWidth, y: 0 },
      action.nowMs,
    );
    settles.set(itemKey(item, start + slot), settle);
    if (settle.active) anyActive = true;
  }
  if (settles.size === 0) return state;
  if (anyActive) exec({ kind: "scheduleMotionFrame" });
  return { ...state, phase: { kind: "idle", motionSettles: settles } };
}

function reconcilePhase(
  phase: SequenceSpreadPhase,
  items: readonly ArtifactStackItem[],
  visibleCount: number,
): SequenceSpreadPhase {
  switch (phase.kind) {
    case "stepping":
    case "rewinding": {
      const under = phase.underCard;
      const nextUnder =
        under && under.items === items && under.visibleCount === visibleCount
          ? under
          : null;
      if (nextUnder === under) return phase;
      return { ...phase, underCard: nextUnder };
    }
    case "draggingItem":
    case "movingSpread": {
      const under = phase.underCard;
      const nextUnder =
        under && under.items === items && under.visibleCount === visibleCount
          ? under
          : null;
      const sync = phase.resizeBackSync;
      const nextSync =
        sync &&
        sync.itemCount === items.length &&
        sync.visibleCount === visibleCount
          ? sync
          : null;
      if (nextUnder === under && nextSync === sync) return phase;
      return { ...phase, underCard: nextUnder, resizeBackSync: nextSync };
    }
    case "resizing": {
      const sync = phase.resizeBackSync;
      const nextSync =
        sync &&
        sync.itemCount === items.length &&
        sync.visibleCount === visibleCount
          ? sync
          : null;
      if (nextSync === sync) return phase;
      return { ...phase, resizeBackSync: nextSync };
    }
    case "idle":
    case "folding":
      return phase;
    default: {
      const exhaustive: never = phase;
      return exhaustive;
    }
  }
}

function onSyncProps(
  state: SequenceSpreadState,
  action: Extract<SequenceSpreadAction, { kind: "syncProps" }>,
  exec: Exec,
): SequenceSpreadState {
  const visibleCount = Math.min(action.layoutVisibleCount, action.items.length);
  const windowStart = action.windowed
    ? clamp(
        state.windowStart,
        0,
        Math.max(0, action.items.length - visibleCount),
      )
    : 0;
  const oldDisplayed = displayedWindowStart(
    state.windowStart,
    action.previousWindowed,
    state.items.length,
    state.visibleCount,
  );
  const newDisplayed = displayedWindowStart(
    windowStart,
    action.windowed,
    action.items.length,
    visibleCount,
  );
  if (
    action.items === state.items &&
    visibleCount === state.visibleCount &&
    windowStart === state.windowStart &&
    oldDisplayed === newDisplayed
  ) {
    return state;
  }
  if (oldDisplayed !== newDisplayed) {
    exec({ kind: "notifyWindowStartChange", windowStart: newDisplayed });
  }
  const phase = reconcilePhase(state.phase, action.items, visibleCount);
  return { ...state, items: action.items, visibleCount, windowStart, phase };
}

interface StepMotion {
  motionSettles: ReadonlyMap<string, CardSettleState>;
  underCard: UnderCard | null;
  stepTucks: readonly StepTuck[];
  anyActive: boolean;
}

function buildStepMotion(
  state: SequenceSpreadState,
  current: number,
  next: number,
  nowMs: number,
  cardWidth: number,
  held: ItemDragData | null,
): StepMotion {
  const open = state.visibleCount;
  const list = state.items;
  const last = Math.max(0, list.length - open);
  const delta = next - current;
  const previous = motionSettlesOf(state.phase);
  const nextSettles = new Map<string, CardSettleState>();
  let anyActive = false;
  for (let slot = 0; slot < open; slot += 1) {
    const item = list[next + slot];
    if (!item) continue;
    const key = itemKey(item, next + slot);
    const prevSlot = clamp(slot + delta, 0, open - 1);
    const from =
      previous.get(key) ??
      held?.siblingSettles.get(next + slot) ??
      createCardSettle({ x: prevSlot * cardWidth, y: 0 });
    const settle = retargetCardSettle(
      from,
      { x: slot * cardWidth, y: 0 },
      nowMs,
    );
    nextSettles.set(key, settle);
    if (settle.active) anyActive = true;
  }
  const side = delta > 0 ? "left" : "right";
  const underIndex = delta > 0 ? current : current + open - 1;
  const coverSlot = side === "left" ? 0 : open - 1;
  const nextStepTucks: StepTuck[] = [];
  for (let oldSlot = 0; oldSlot < open; oldSlot += 1) {
    const oldIndex = current + oldSlot;
    if (
      (oldIndex >= next && oldIndex < next + open) ||
      oldIndex === underIndex
    ) {
      continue;
    }
    const oldItem = list[oldIndex];
    if (!oldItem) continue;
    const oldKey = itemKey(oldItem, oldIndex);
    const from =
      previous.get(oldKey) ??
      held?.siblingSettles.get(oldIndex) ??
      createCardSettle({ x: oldSlot * cardWidth, y: 0 });
    const tuckKey = stepTuckKey(oldItem, oldIndex);
    const targetX = coverSlot * cardWidth;
    const settle = retargetCardSettle(from, { x: targetX, y: 0 }, nowMs);
    nextSettles.set(tuckKey, settle);
    if (settle.active) anyActive = true;
    nextStepTucks.push({ key: tuckKey, item: oldItem, targetX });
  }
  if (!anyActive) {
    return {
      motionSettles: nextSettles,
      underCard: null,
      stepTucks: [],
      anyActive: false,
    };
  }
  const stackCount =
    delta > 0
      ? current > 0
        ? current + 1
        : 0
      : current < last
        ? list.length - underIndex
        : 0;
  const shift = Math.min(STACK_BACK_COUNT, Math.abs(delta));
  const coverItem = list[next + coverSlot];
  const coverKey = coverItem ? itemKey(coverItem, next + coverSlot) : "";
  const coverSettle = nextSettles.get(coverKey);
  const coverStartX = coverSettle
    ? coverSettle.current.x
    : coverSlot * cardWidth;
  const coverTargetX = coverSlot * cardWidth;
  const hadOppositeStack = delta > 0 ? current < last : current > 0;
  const reveal = hadOppositeStack
    ? {
        side: side === "left" ? ("right" as const) : ("left" as const),
        shift,
      }
    : null;
  return {
    motionSettles: nextSettles,
    underCard: {
      side,
      index: underIndex,
      stackCount,
      shift,
      coverKey,
      coverStartX,
      coverTargetX,
      reveal,
      items: list,
      visibleCount: open,
    },
    stepTucks: nextStepTucks,
    anyActive: true,
  };
}

function restoreMotionPhase(
  motionSettles: ReadonlyMap<string, CardSettleState>,
  underCard: UnderCard | null,
  stepTucks: readonly StepTuck[],
  resizeTucks: readonly ResizeTuck[],
  resizeBackSync: ResizeBackSync | null,
): SequenceSpreadPhase {
  if (motionSettles.size === 0 || !settlesActive(motionSettles)) {
    return { kind: "idle", motionSettles: EMPTY_MOTION };
  }
  if (resizeTucks.length > 0 || resizeBackSync !== null) {
    return {
      kind: "resizing",
      pointer: null,
      motionSettles,
      resizeTucks,
      resizeBackSync,
    };
  }
  if (underCard !== null || stepTucks.length > 0) {
    return { kind: "stepping", motionSettles, underCard, stepTucks };
  }
  return { kind: "idle", motionSettles };
}

function phaseAfterStep(
  previous: SequenceSpreadPhase,
  motionSettles: ReadonlyMap<string, CardSettleState>,
  underCard: UnderCard | null,
  stepTucks: readonly StepTuck[],
  drag: ItemDragData | null,
): SequenceSpreadPhase {
  if (previous.kind === "draggingItem" && drag) {
    return {
      kind: "draggingItem",
      drag,
      motionSettles,
      underCard,
      stepTucks,
      resizeTucks: [],
      resizeBackSync: null,
    };
  }
  if (previous.kind === "rewinding") {
    return { kind: "rewinding", motionSettles, underCard, stepTucks };
  }
  if (underCard || stepTucks.length > 0 || settlesActive(motionSettles)) {
    return { kind: "stepping", motionSettles, underCard, stepTucks };
  }
  return { kind: "idle", motionSettles };
}

function applyStep(
  state: SequenceSpreadState,
  by: number,
  clock: MotionClock,
  exec: Exec,
): SequenceSpreadState {
  const open = state.visibleCount;
  const list = state.items;
  const current = displayedWindowStart(
    state.windowStart,
    clock.windowed,
    list.length,
    open,
  );
  const last = Math.max(0, list.length - open);
  const next = clamp(current + by, 0, last);
  if (next === current) return state;
  const held =
    state.phase.kind === "draggingItem" && state.phase.drag.active
      ? state.phase.drag
      : null;
  exec({ kind: "notifyWindowStartChange", windowStart: next });
  if (!clock.animateMotion) {
    if (state.phase.kind === "draggingItem" && held) {
      return {
        ...state,
        windowStart: next,
        phase: {
          ...state.phase,
          drag: { ...held, siblingSettles: EMPTY_SIBLINGS },
        },
      };
    }
    return { ...state, windowStart: next };
  }
  const built = buildStepMotion(
    state,
    current,
    next,
    clock.nowMs,
    clock.cardWidth,
    held,
  );
  if (built.anyActive) exec({ kind: "scheduleMotionFrame" });
  const drag = held ? { ...held, siblingSettles: EMPTY_SIBLINGS } : null;
  return {
    ...state,
    windowStart: next,
    phase: phaseAfterStep(
      state.phase,
      built.motionSettles,
      built.underCard,
      built.stepTucks,
      drag,
    ),
  };
}

function inferCardWidth(state: SequenceSpreadState): number {
  const settles = motionSettlesOf(state.phase);
  const start = state.windowStart;
  for (let slot = 1; slot < state.visibleCount; slot += 1) {
    const item = state.items[start + slot];
    if (!item) continue;
    const settle = settles.get(itemKey(item, start + slot));
    if (!settle) continue;
    const width = Math.abs(settle.to.x) / slot;
    if (width > 0.5) return width;
  }
  return 0;
}

function startFold(
  state: SequenceSpreadState,
  nowMs: number,
  cardWidth: number,
  exec: Exec,
): SequenceSpreadState {
  const open = state.visibleCount;
  const start = clamp(
    state.windowStart,
    0,
    Math.max(0, state.items.length - open),
  );
  const previous = motionSettlesOf(state.phase);
  const settles = new Map<string, CardSettleState>();
  let anyActive = false;
  let driver: FoldBackSync | null = null;
  for (let slot = 0; slot < open; slot += 1) {
    const item = state.items[start + slot];
    if (!item) continue;
    const key = itemKey(item, start + slot);
    const current =
      previous.get(key) ?? createCardSettle({ x: slot * cardWidth, y: 0 });
    const settle = retargetCardSettle(current, { x: 0, y: 0 }, nowMs);
    settles.set(key, settle);
    if (settle.active) {
      anyActive = true;
      if (slot > 0 && driver === null) {
        driver = { driverKey: key, startX: settle.current.x, targetX: 0 };
      }
    }
  }
  if (!anyActive) {
    exec({ kind: "notifyClose" });
    return { ...state, phase: { kind: "idle", motionSettles: EMPTY_MOTION } };
  }
  exec({ kind: "scheduleMotionFrame" });
  return {
    ...state,
    phase: { kind: "folding", motionSettles: settles, foldBackSync: driver },
  };
}

function cancelGestures(state: SequenceSpreadState, exec: Exec): void {
  if (state.phase.kind === "draggingItem") {
    exec({ kind: "cancelDragFrame" });
    exec({ kind: "clearHoverStepTimer" });
  }
  if (state.phase.kind === "movingSpread") exec({ kind: "cancelMoveFrame" });
}

function onRequestClose(
  state: SequenceSpreadState,
  action: MotionClock,
  exec: Exec,
): SequenceSpreadState {
  if (isClosingPhase(state.phase)) return state;
  cancelGestures(state, exec);
  if (!action.animateMotion) {
    if (motionSettlesOf(state.phase).size > 0) {
      exec({ kind: "cancelMotionFrame" });
    }
    exec({ kind: "notifyClose" });
    return state.phase.kind === "idle"
      ? state
      : { ...state, phase: { kind: "idle", motionSettles: EMPTY_MOTION } };
  }
  const start = displayedWindowStart(
    state.windowStart,
    action.windowed,
    state.items.length,
    state.visibleCount,
  );
  if (start > 0) {
    const rewinding: SequenceSpreadState = {
      ...state,
      phase: {
        kind: "rewinding",
        motionSettles: motionSettlesOf(state.phase),
        underCard: underCardOf(state.phase),
        stepTucks: stepTucksOf(state.phase),
      },
    };
    const stepped = applyStep(rewinding, -start, action, exec);
    if (settlesActive(motionSettlesOf(stepped.phase))) return stepped;
    return startFold(stepped, action.nowMs, action.cardWidth, exec);
  }
  return startFold(state, action.nowMs, action.cardWidth, exec);
}

function finishMotion(
  state: SequenceSpreadState,
  phase: SequenceSpreadPhase,
): SequenceSpreadState {
  switch (phase.kind) {
    case "resizing":
      if (phase.pointer !== null) {
        return {
          ...state,
          phase: {
            kind: "resizing",
            pointer: phase.pointer,
            motionSettles: EMPTY_MOTION,
            resizeTucks: [],
            resizeBackSync: null,
          },
        };
      }
      return { ...state, phase: { kind: "idle", motionSettles: EMPTY_MOTION } };
    case "draggingItem":
      return {
        ...state,
        phase: {
          kind: "draggingItem",
          drag: phase.drag,
          motionSettles: EMPTY_MOTION,
          underCard: null,
          stepTucks: [],
          resizeTucks: [],
          resizeBackSync: null,
        },
      };
    case "movingSpread":
      return {
        ...state,
        phase: {
          kind: "movingSpread",
          move: phase.move,
          motionSettles: EMPTY_MOTION,
          underCard: null,
          stepTucks: [],
          resizeTucks: [],
          resizeBackSync: null,
        },
      };
    case "idle":
    case "stepping":
    case "folding":
      return { ...state, phase: { kind: "idle", motionSettles: EMPTY_MOTION } };
    case "rewinding":
      return state;
    default: {
      const exhaustive: never = phase;
      return exhaustive;
    }
  }
}

function onMotionTick(
  state: SequenceSpreadState,
  nowMs: number,
  exec: Exec,
): SequenceSpreadState {
  const settles = state.phase.motionSettles;
  if (settles.size === 0) {
    if (state.phase.kind === "folding") {
      exec({ kind: "notifyClose" });
      return { ...state, phase: { kind: "idle", motionSettles: EMPTY_MOTION } };
    }
    return state;
  }
  const nextSettles = new Map<string, CardSettleState>();
  let anyActive = false;
  for (const [key, settle] of settles) {
    const stepped = stepCardSettle(settle, nowMs);
    nextSettles.set(key, stepped);
    if (stepped.active) anyActive = true;
  }
  if (anyActive) {
    exec({ kind: "scheduleMotionFrame" });
    return {
      ...state,
      phase: { ...state.phase, motionSettles: nextSettles },
    };
  }
  if (state.phase.kind === "rewinding") {
    const landed: SequenceSpreadState = {
      ...state,
      phase: { ...state.phase, motionSettles: nextSettles },
    };
    return startFold(landed, nowMs, inferCardWidth(landed), exec);
  }
  if (state.phase.kind === "folding") {
    exec({ kind: "notifyClose" });
    return { ...state, phase: { kind: "idle", motionSettles: EMPTY_MOTION } };
  }
  return finishMotion(state, state.phase);
}

function modeAt(
  point: WorldPoint,
  drag: ItemDragData,
  state: SequenceSpreadState,
  scene: SpreadHitScene,
): { mode: DragMode; targetSlot: number; landing: CellCoord | null } {
  const inside =
    point.x >= scene.originX - FRAME_OUTSET &&
    point.x <= scene.originX + scene.frameWidth + FRAME_OUTSET &&
    point.y >= scene.originY - FRAME_OUTSET &&
    point.y <= scene.originY + scene.cardHeight + FRAME_OUTSET;
  const start = displayedWindowStart(
    state.windowStart,
    scene.windowed,
    state.items.length,
    state.visibleCount,
  );
  const open = state.visibleCount;
  const last = Math.max(0, state.items.length - open);
  const leftStackActive = scene.windowed && start > 0;
  const rightStackActive = scene.windowed && start < last;
  if (inside) {
    if (scene.canReorder === false) {
      return { mode: "none", targetSlot: drag.targetSlot, landing: null };
    }
    if (leftStackActive && point.x < scene.originX + scene.cardWidth) {
      return { mode: "left", targetSlot: drag.targetSlot, landing: null };
    }
    if (
      rightStackActive &&
      point.x >= scene.originX + (open - 1) * scene.cardWidth
    ) {
      return { mode: "right", targetSlot: drag.targetSlot, landing: null };
    }
    const firstOpenSlot = leftStackActive ? 1 : 0;
    const lastOpenSlot = rightStackActive ? open - 2 : open - 1;
    const cardCenterX = point.x - drag.grab.x + scene.cardWidth / 2;
    const targetSlot = clamp(
      Math.floor((cardCenterX - scene.originX) / scene.cardWidth),
      firstOpenSlot,
      Math.max(firstOpenSlot, lastOpenSlot),
    );
    return { mode: "reorder", targetSlot, landing: null };
  }
  if (!scene.canExtract) {
    return { mode: "none", targetSlot: drag.targetSlot, landing: null };
  }
  const col = Math.round((point.x - drag.grab.x) / CELL_SIZE);
  const row = Math.round((point.y - drag.grab.y) / CELL_SIZE);
  const landingCard: CellCardModel = {
    ...scene.card,
    id: LANDING_ID,
    col,
    row,
  };
  const frameCard: CellCardModel = {
    ...scene.card,
    id: FRAME_ID,
    col: scene.layoutStartCol,
    row: scene.layoutRow,
    widthCells: scene.layoutTotalCols,
    heightCells: scene.card.heightCells,
  };
  const delta = resolveNonOverlappingDelta(
    [...scene.foregroundCards, frameCard, landingCard],
    new Set([LANDING_ID]),
    { col: 0, row: 0 },
  );
  return {
    mode: "extract",
    targetSlot: drag.targetSlot,
    landing: { col: col + delta.col, row: row + delta.row },
  };
}

function targetPointForDrag(
  mode: DragMode,
  targetSlot: number,
  landing: CellCoord | null,
  fallbackSlot: number,
  scene: SpreadHitScene,
  visibleCount: number,
): WorldPoint {
  if (mode === "reorder") return { x: targetSlot * scene.cardWidth, y: 0 };
  if (mode === "left") return { x: 0, y: 0 };
  if (mode === "right")
    return { x: (visibleCount - 1) * scene.cardWidth, y: 0 };
  if (mode === "extract" && landing) {
    return {
      x: (landing.col - scene.layoutStartCol) * CELL_SIZE,
      y: (landing.row - scene.layoutRow) * CELL_SIZE,
    };
  }
  return { x: fallbackSlot * scene.cardWidth, y: 0 };
}

function withHoverMode(
  drag: ItemDragData,
  mode: DragMode,
  exec: Exec,
): ItemDragData {
  if (drag.hoverMode === mode) return drag;
  const wasEdge = drag.hoverMode === "left" || drag.hoverMode === "right";
  const edge = mode === "left" || mode === "right";
  if (edge) exec({ kind: "armHoverStepTimer" });
  else if (wasEdge) exec({ kind: "clearHoverStepTimer" });
  return { ...drag, hoverMode: mode };
}

function onItemPointerDown(
  state: SequenceSpreadState,
  action: Extract<SequenceSpreadAction, { kind: "itemPointerDown" }>,
): SequenceSpreadState {
  if (isClosingPhase(state.phase)) return state;
  const withActive =
    state.activeIndex === action.index
      ? state
      : { ...state, activeIndex: action.index };
  if (action.button !== 0 || !action.editable) return withActive;
  if (
    state.phase.kind === "movingSpread" ||
    state.phase.kind === "draggingItem"
  ) {
    return withActive;
  }
  const originX = action.slot * action.cardWidth;
  const drag: ItemDragData = {
    pointerId: action.pointerId,
    from: action.index,
    slot: action.slot,
    startX: action.clientX,
    startY: action.clientY,
    grab: {
      x: action.world.x - (action.originX + originX),
      y: action.world.y - action.originY,
    },
    active: false,
    mode: "reorder",
    hoverMode: "none",
    targetSlot: action.slot,
    landing: null,
    draggedSettle: createCardSettle({ x: originX, y: 0 }),
    siblingSettles: EMPTY_SIBLINGS,
  };
  return {
    ...withActive,
    phase: {
      kind: "draggingItem",
      drag,
      motionSettles: motionSettlesOf(state.phase),
      underCard: underCardOf(state.phase),
      stepTucks: stepTucksOf(state.phase),
      resizeTucks: resizeTucksOf(state.phase),
      resizeBackSync: resizeBackSyncOf(state.phase),
    },
  };
}

function onItemPointerMove(
  state: SequenceSpreadState,
  action: Extract<SequenceSpreadAction, { kind: "itemPointerMove" }>,
  exec: Exec,
): SequenceSpreadState {
  if (state.phase.kind !== "draggingItem") return state;
  if (state.phase.drag.pointerId !== action.pointerId) return state;
  let drag = state.phase.drag;
  let activated = false;
  if (!drag.active) {
    const travelled = Math.hypot(
      action.clientX - drag.startX,
      action.clientY - drag.startY,
    );
    if (travelled < DRAG_THRESHOLD_PX) return state;
    drag = { ...drag, active: true };
    activated = true;
  }
  const at = modeAt(action.world, drag, state, action.scene);
  const freeFollow =
    at.mode === "none" &&
    action.scene.canReorder === false &&
    action.scene.canExtract;
  const changedTarget =
    activated ||
    freeFollow ||
    at.mode !== drag.mode ||
    at.targetSlot !== drag.targetSlot ||
    !sameCell(at.landing, drag.landing);
  if (!changedTarget) return state;
  drag = withHoverMode(
    { ...drag, mode: at.mode, targetSlot: at.targetSlot, landing: at.landing },
    at.mode,
    exec,
  );
  const nextPoint = freeFollow
    ? {
        x: action.world.x - drag.grab.x - action.scene.originX,
        y: action.world.y - drag.grab.y - action.scene.originY,
      }
    : targetPointForDrag(
        at.mode,
        at.targetSlot,
        at.landing,
        drag.slot,
        action.scene,
        state.visibleCount,
      );
  drag = {
    ...drag,
    draggedSettle: retargetSettle(
      drag.draggedSettle,
      nextPoint,
      action.nowMs,
      action.animateMotion,
    ),
  };
  const start = displayedWindowStart(
    state.windowStart,
    action.scene.windowed,
    state.items.length,
    state.visibleCount,
  );
  const open = state.visibleCount;
  const motion = state.phase.motionSettles;
  const siblings = new Map<number, CardSettleState>();
  let anyActive = drag.draggedSettle.active;
  for (let slot = 0; slot < open; slot += 1) {
    const index = start + slot;
    if (index === drag.from) continue;
    const visualSlot = visualSlotForSibling(
      slot,
      drag.from,
      at.mode,
      at.targetSlot,
      start,
      open,
    );
    const existing = drag.siblingSettles.get(index);
    if (!existing && visualSlot === slot) continue;
    const item = state.items[index];
    const stepping = item ? motion.get(itemKey(item, index)) : undefined;
    const nextSibling = retargetSettle(
      existing ??
        stepping ??
        createCardSettle({ x: slot * action.cardWidth, y: 0 }),
      { x: visualSlot * action.cardWidth, y: 0 },
      action.nowMs,
      action.animateMotion,
    );
    siblings.set(index, nextSibling);
    if (nextSibling.active) anyActive = true;
  }
  drag = { ...drag, siblingSettles: siblings };
  if (anyActive) exec({ kind: "scheduleDragFrame" });
  return { ...state, phase: { ...state.phase, drag } };
}

function exitDrag(state: SequenceSpreadState): SequenceSpreadState {
  if (state.phase.kind !== "draggingItem") return state;
  const { motionSettles, underCard, stepTucks, resizeTucks, resizeBackSync } =
    state.phase;
  return {
    ...state,
    phase: restoreMotionPhase(
      motionSettles,
      underCard,
      stepTucks,
      resizeTucks,
      resizeBackSync,
    ),
  };
}

function onItemPointerEnd(
  state: SequenceSpreadState,
  action: Extract<SequenceSpreadAction, { kind: "itemPointerEnd" }>,
  exec: Exec,
): SequenceSpreadState {
  if (state.phase.kind !== "draggingItem") return state;
  if (state.phase.drag.pointerId !== action.pointerId) return state;
  const drag = state.phase.drag;
  exec({ kind: "cancelDragFrame" });
  exec({ kind: "clearHoverStepTimer" });
  if (!drag.active || action.cancelled) return exitDrag(state);
  const at = modeAt(action.world, drag, state, action.scene);
  const start = displayedWindowStart(
    state.windowStart,
    action.scene.windowed,
    state.items.length,
    state.visibleCount,
  );
  const open = state.visibleCount;
  const cleared = exitDrag(state);
  switch (at.mode) {
    case "reorder": {
      const to = reorderDropIndex(start, at.targetSlot);
      if (to !== drag.from) {
        exec({
          kind: "notifyReorder",
          cardId: action.cardId,
          fromIndex: drag.from,
          toIndex: to,
        });
      }
      return cleared;
    }
    case "left": {
      const to = clamp(start, 0, state.items.length - 1);
      if (to !== drag.from) {
        exec({
          kind: "notifyReorder",
          cardId: action.cardId,
          fromIndex: drag.from,
          toIndex: to,
        });
      }
      return cleared;
    }
    case "right": {
      const to = clamp(start + open - 1, 0, state.items.length - 1);
      if (to !== drag.from) {
        exec({
          kind: "notifyReorder",
          cardId: action.cardId,
          fromIndex: drag.from,
          toIndex: to,
        });
      }
      return cleared;
    }
    case "extract":
      if (at.landing) {
        exec({
          kind: "notifyExtract",
          cardId: action.cardId,
          index: drag.from,
          targetCell: at.landing,
        });
      }
      return cleared;
    case "none":
      return cleared;
    default: {
      const exhaustive: never = at.mode;
      return exhaustive;
    }
  }
}

function onHoverStackTimer(
  state: SequenceSpreadState,
  action: MotionClock,
  exec: Exec,
): SequenceSpreadState {
  if (state.phase.kind !== "draggingItem" || !state.phase.drag.active) {
    return state;
  }
  const mode = state.phase.drag.mode;
  if (mode !== "left" && mode !== "right") return state;
  const stepped = applyStep(state, mode === "left" ? -1 : 1, action, exec);
  if (
    stepped.phase.kind === "draggingItem" &&
    (stepped.phase.drag.mode === "left" || stepped.phase.drag.mode === "right")
  ) {
    exec({ kind: "armHoverStepTimer" });
  }
  return stepped;
}

function resolveSpreadMoveDelta(
  scene: SpreadHitScene,
  rawDelta: CellCoord,
): CellCoord {
  const others = scene.foregroundCards.filter(
    (candidate) => candidate.id !== scene.card.id,
  );
  const spreadBox: CellCardModel = {
    ...scene.card,
    id: MOVE_ID,
    col: scene.layoutStartCol,
    row: scene.layoutRow,
    widthCells: scene.layoutTotalCols,
    heightCells: scene.card.heightCells,
  };
  return resolveNonOverlappingDelta(
    [...others, spreadBox],
    new Set([MOVE_ID]),
    rawDelta,
  );
}

function onMovePointerDown(
  state: SequenceSpreadState,
  action: Extract<SequenceSpreadAction, { kind: "movePointerDown" }>,
): SequenceSpreadState {
  if (action.button !== 0 || isClosingPhase(state.phase)) return state;
  if (
    state.phase.kind === "draggingItem" ||
    state.phase.kind === "movingSpread"
  ) {
    return state;
  }
  return {
    ...state,
    phase: {
      kind: "movingSpread",
      move: {
        pointerId: action.pointerId,
        startClient: { x: action.clientX, y: action.clientY },
        startWorld: { x: action.world.x, y: action.world.y },
        active: false,
        landingDelta: { col: 0, row: 0 },
        settle: createCardSettle({ x: 0, y: 0 }),
      },
      motionSettles: motionSettlesOf(state.phase),
      underCard: underCardOf(state.phase),
      stepTucks: stepTucksOf(state.phase),
      resizeTucks: resizeTucksOf(state.phase),
      resizeBackSync: resizeBackSyncOf(state.phase),
    },
  };
}

function onMovePointerMove(
  state: SequenceSpreadState,
  action: Extract<SequenceSpreadAction, { kind: "movePointerMove" }>,
  exec: Exec,
): SequenceSpreadState {
  if (state.phase.kind !== "movingSpread") return state;
  if (state.phase.move.pointerId !== action.pointerId) return state;
  let move = state.phase.move;
  let activated = false;
  if (!move.active) {
    const travelled = Math.hypot(
      action.clientX - move.startClient.x,
      action.clientY - move.startClient.y,
    );
    if (travelled < DRAG_THRESHOLD_PX) return state;
    move = { ...move, active: true };
    activated = true;
  }
  const rawDelta: CellCoord = {
    col: Math.round((action.world.x - move.startWorld.x) / CELL_SIZE),
    row: Math.round((action.world.y - move.startWorld.y) / CELL_SIZE),
  };
  const landingDelta = resolveSpreadMoveDelta(action.scene, rawDelta);
  if (
    !activated &&
    landingDelta.col === move.landingDelta.col &&
    landingDelta.row === move.landingDelta.row
  ) {
    return state;
  }
  const settle = retargetSettle(
    move.settle,
    { x: landingDelta.col * CELL_SIZE, y: landingDelta.row * CELL_SIZE },
    action.nowMs,
    action.animateMotion,
  );
  if (settle.active) exec({ kind: "scheduleMoveFrame" });
  return {
    ...state,
    phase: {
      ...state.phase,
      move: { ...move, landingDelta, settle },
    },
  };
}

function onMovePointerEnd(
  state: SequenceSpreadState,
  action: Extract<SequenceSpreadAction, { kind: "movePointerEnd" }>,
  exec: Exec,
): SequenceSpreadState {
  if (state.phase.kind !== "movingSpread") return state;
  if (state.phase.move.pointerId !== action.pointerId) return state;
  const {
    move,
    motionSettles,
    underCard,
    stepTucks,
    resizeTucks,
    resizeBackSync,
  } = state.phase;
  exec({ kind: "cancelMoveFrame" });
  const restored: SequenceSpreadState = {
    ...state,
    phase: restoreMotionPhase(
      motionSettles,
      underCard,
      stepTucks,
      resizeTucks,
      resizeBackSync,
    ),
  };
  if (!move.active || action.cancelled) return restored;
  const rawDelta: CellCoord = {
    col: Math.round((action.world.x - move.startWorld.x) / CELL_SIZE),
    row: Math.round((action.world.y - move.startWorld.y) / CELL_SIZE),
  };
  const delta = resolveSpreadMoveDelta(action.scene, rawDelta);
  if (delta.col !== 0 || delta.row !== 0) {
    exec({
      kind: "notifyMove",
      cardId: action.cardId,
      col: action.scene.card.col + delta.col,
      row: action.scene.card.row + delta.row,
    });
  }
  return restored;
}

function onDragTick(
  state: SequenceSpreadState,
  nowMs: number,
  exec: Exec,
): SequenceSpreadState {
  if (state.phase.kind !== "draggingItem" || !state.phase.drag.active) {
    return state;
  }
  const draggedSettle = stepCardSettle(state.phase.drag.draggedSettle, nowMs);
  let anyActive = draggedSettle.active;
  const siblings = new Map<number, CardSettleState>();
  for (const [index, settle] of state.phase.drag.siblingSettles) {
    const stepped = stepCardSettle(settle, nowMs);
    siblings.set(index, stepped);
    if (stepped.active) anyActive = true;
  }
  if (anyActive) exec({ kind: "scheduleDragFrame" });
  return {
    ...state,
    phase: {
      ...state.phase,
      drag: { ...state.phase.drag, draggedSettle, siblingSettles: siblings },
    },
  };
}

function onMoveTick(
  state: SequenceSpreadState,
  nowMs: number,
  exec: Exec,
): SequenceSpreadState {
  if (state.phase.kind !== "movingSpread" || !state.phase.move.active) {
    return state;
  }
  const settle = stepCardSettle(state.phase.move.settle, nowMs);
  if (settle.active) exec({ kind: "scheduleMoveFrame" });
  return {
    ...state,
    phase: { ...state.phase, move: { ...state.phase.move, settle } },
  };
}

function glideResize(
  state: SequenceSpreadState,
  nextVisibleCount: number,
  nowMs: number,
  cardWidth: number,
  exec: Exec,
): SequenceSpreadState {
  if (state.phase.kind !== "resizing") return state;
  const list = state.items;
  const seenCount = state.visibleCount;
  const seenStart = state.windowStart;
  const nextCount = Math.min(nextVisibleCount, list.length);
  if (nextCount === seenCount) return state;
  const nextStart =
    nextCount < list.length
      ? clamp(seenStart, 0, Math.max(0, list.length - nextCount))
      : 0;
  const previous = state.phase.motionSettles;
  const nextSettles = new Map<string, CardSettleState>();
  let anyActive = false;
  const takePreviousSettle = (
    item: ArtifactStackItem,
    index: number,
    fallbackX: number,
  ): CardSettleState =>
    previous.get(itemKey(item, index)) ??
    previous.get(resizeTuckKey(item, index)) ??
    createCardSettle({ x: fallbackX, y: 0 });
  const glide = (key: string, from: CardSettleState, toX: number) => {
    const settle = retargetCardSettle(from, { x: toX, y: 0 }, nowMs);
    nextSettles.set(key, settle);
    if (settle.active) anyActive = true;
    return settle;
  };
  const nextOpenIndices = new Set<number>();
  for (let slot = 0; slot < nextCount; slot += 1) {
    const index = nextStart + slot;
    const item = list[index];
    if (!item) continue;
    nextOpenIndices.add(index);
    const key = itemKey(item, index);
    const seenSlot = index - seenStart;
    const fromSlot = seenSlot < 0 ? 0 : Math.min(seenSlot, seenCount - 1);
    const hasPrior =
      previous.has(key) || previous.has(resizeTuckKey(item, index));
    if (fromSlot === slot && !hasPrior) continue;
    glide(
      key,
      takePreviousSettle(item, index, fromSlot * cardWidth),
      slot * cardWidth,
    );
  }
  const rightEdgeX = (nextCount - 1) * cardWidth;
  const nextTucksByIndex = new Map<number, ResizeTuck>();
  const newlyRetired: ResizeTuck[] = [];
  for (let slot = nextCount; slot < seenCount; slot += 1) {
    const index = seenStart + slot;
    if (nextOpenIndices.has(index)) continue;
    const item = list[index];
    if (!item) continue;
    const key = resizeTuckKey(item, index);
    glide(key, takePreviousSettle(item, index, slot * cardWidth), rightEdgeX);
    const tuck: ResizeTuck = { key, index, item };
    nextTucksByIndex.set(index, tuck);
    newlyRetired.push(tuck);
  }
  if (nextStart + nextCount < list.length) {
    for (const existing of state.phase.resizeTucks) {
      if (
        nextOpenIndices.has(existing.index) ||
        nextTucksByIndex.has(existing.index)
      ) {
        continue;
      }
      const live = previous.get(existing.key);
      if (!live || live.current.x <= rightEdgeX + 0.5) continue;
      glide(existing.key, live, rightEdgeX);
      nextTucksByIndex.set(existing.index, existing);
    }
  }
  const nextTucks = [...nextTucksByIndex.values()].sort(
    (a, b) => b.index - a.index,
  );
  if (nextStart !== state.windowStart) {
    exec({ kind: "notifyWindowStartChange", windowStart: nextStart });
  }
  let resizeBackSync: ResizeBackSync | null = null;
  const keptTucks = anyActive ? nextTucks : [];
  if (anyActive && newlyRetired.length > 0) {
    let driver: { key: string; startX: number; span: number } | null = null;
    for (const tuck of nextTucks) {
      const tuckSettle = nextSettles.get(tuck.key);
      if (!tuckSettle) continue;
      const span = Math.abs(tuckSettle.current.x - rightEdgeX);
      if (!driver || span > driver.span) {
        driver = { key: tuck.key, startX: tuckSettle.current.x, span };
      }
    }
    if (driver) {
      resizeBackSync = {
        driverKey: driver.key,
        startX: driver.startX,
        targetX: rightEdgeX,
        itemCount: list.length,
        visibleCount: nextCount,
      };
    }
  } else if (
    anyActive &&
    nextCount > seenCount &&
    nextStart + nextCount < list.length
  ) {
    const endIndex = nextStart + nextCount - 1;
    const endItem = list[endIndex];
    const driverKey = endItem ? itemKey(endItem, endIndex) : "";
    const driverSettle = driverKey ? nextSettles.get(driverKey) : undefined;
    if (driverKey && driverSettle) {
      resizeBackSync = {
        driverKey,
        startX: driverSettle.current.x,
        targetX: rightEdgeX,
        itemCount: list.length,
        visibleCount: nextCount,
      };
    }
  }
  if (anyActive) exec({ kind: "scheduleMotionFrame" });
  return {
    ...state,
    windowStart: nextStart,
    visibleCount: nextCount,
    phase: {
      kind: "resizing",
      pointer: state.phase.pointer,
      motionSettles: anyActive ? nextSettles : EMPTY_MOTION,
      resizeTucks: keptTucks,
      resizeBackSync,
    },
  };
}

function onResizePointerDown(
  state: SequenceSpreadState,
  action: Extract<SequenceSpreadAction, { kind: "resizePointerDown" }>,
): SequenceSpreadState {
  if (action.button !== 0 || isClosingPhase(state.phase)) return state;
  if (
    state.phase.kind === "draggingItem" ||
    state.phase.kind === "movingSpread"
  ) {
    return state;
  }
  const pointer: ResizeDragData = {
    pointerId: action.pointerId,
    startX: action.startX,
    startCount: state.visibleCount,
    last: state.visibleCount,
  };
  if (state.phase.kind === "resizing") {
    return { ...state, phase: { ...state.phase, pointer } };
  }
  return {
    ...state,
    phase: {
      kind: "resizing",
      pointer,
      motionSettles: motionSettlesOf(state.phase),
      resizeTucks: [],
      resizeBackSync: null,
    },
  };
}

function onResizePointerMove(
  state: SequenceSpreadState,
  action: Extract<SequenceSpreadAction, { kind: "resizePointerMove" }>,
  exec: Exec,
): SequenceSpreadState {
  if (state.phase.kind !== "resizing" || state.phase.pointer === null)
    return state;
  if (state.phase.pointer.pointerId !== action.pointerId) return state;
  if (action.cardWidth === 0) return state;
  const dx = action.worldX - state.phase.pointer.startX;
  const next = clamp(
    state.phase.pointer.startCount + Math.round(dx / action.cardWidth),
    action.minVisibleCount,
    action.maxVisibleCount,
  );
  if (next === state.phase.pointer.last) return state;
  const pointed: SequenceSpreadState = {
    ...state,
    phase: {
      ...state.phase,
      pointer: { ...state.phase.pointer, last: next },
    },
  };
  exec({ kind: "notifyPreferredVisibleCountChange", count: next });
  if (!action.animateMotion) return pointed;
  return glideResize(pointed, next, action.nowMs, action.cardWidth, exec);
}

function onResizePointerEnd(
  state: SequenceSpreadState,
  action: Extract<SequenceSpreadAction, { kind: "resizePointerEnd" }>,
): SequenceSpreadState {
  if (state.phase.kind !== "resizing" || state.phase.pointer === null)
    return state;
  if (state.phase.pointer.pointerId !== action.pointerId) return state;
  if (settlesActive(state.phase.motionSettles)) {
    return { ...state, phase: { ...state.phase, pointer: null } };
  }
  return { ...state, phase: { kind: "idle", motionSettles: EMPTY_MOTION } };
}

function onKeyboardReorder(
  state: SequenceSpreadState,
  action: Extract<SequenceSpreadAction, { kind: "keyboardReorder" }>,
  exec: Exec,
): SequenceSpreadState {
  if (!action.canReorder || isClosingPhase(state.phase)) return state;
  const index = state.activeIndex;
  if (index === null) return state;
  const to = index + action.direction;
  if (to < 0 || to >= state.items.length) return state;
  exec({
    kind: "notifyReorder",
    cardId: action.cardId,
    fromIndex: index,
    toIndex: to,
  });
  return { ...state, activeIndex: to };
}

function onWheel(
  state: SequenceSpreadState,
  action: Extract<SequenceSpreadAction, { kind: "wheel" }>,
  exec: Exec,
): SequenceSpreadState {
  if (isClosingPhase(state.phase) || !action.windowed) return state;
  let accum = state.wheelAccumPx + action.deltaX;
  let next = state;
  let stepped = false;
  while (Math.abs(accum) >= WHEEL_STEP_PX) {
    const direction = Math.sign(accum);
    const after = applyStep(next, direction, action, exec);
    if (after !== next) stepped = true;
    next = after;
    accum -= direction * WHEEL_STEP_PX;
  }
  if (!stepped && accum === state.wheelAccumPx) return state;
  if (next.wheelAccumPx === accum) return next;
  return { ...next, wheelAccumPx: accum };
}

export const sequenceSpreadReducer: EffectReducer<
  SequenceSpreadState,
  SequenceSpreadAction,
  SequenceSpreadEffect
> = (state, action, exec) => {
  switch (action.kind) {
    case "mounted":
      return onMounted(state, action, exec);
    case "syncProps":
      return onSyncProps(state, action, exec);
    case "step":
      if (isClosingPhase(state.phase)) return state;
      return applyStep(state, action.by, action, exec);
    case "wheel":
      return onWheel(state, action, exec);
    case "requestClose":
      return onRequestClose(state, action, exec);
    case "motionTick":
      return onMotionTick(state, action.nowMs, exec);
    case "dragTick":
      return onDragTick(state, action.nowMs, exec);
    case "moveTick":
      return onMoveTick(state, action.nowMs, exec);
    case "itemPointerDown":
      return onItemPointerDown(state, action);
    case "itemPointerMove":
      return onItemPointerMove(state, action, exec);
    case "itemPointerEnd":
      return onItemPointerEnd(state, action, exec);
    case "hoverStackTimerFired":
      return onHoverStackTimer(state, action, exec);
    case "movePointerDown":
      return onMovePointerDown(state, action);
    case "movePointerMove":
      return onMovePointerMove(state, action, exec);
    case "movePointerEnd":
      return onMovePointerEnd(state, action, exec);
    case "resizePointerDown":
      return onResizePointerDown(state, action);
    case "resizePointerMove":
      return onResizePointerMove(state, action, exec);
    case "resizePointerEnd":
      return onResizePointerEnd(state, action);
    case "keyboardReorder":
      return onKeyboardReorder(state, action, exec);
    case "setActiveIndex":
      if (state.activeIndex === action.index) return state;
      return { ...state, activeIndex: action.index };
    case "setHoveredIndex":
      if (state.hoveredIndex === action.index) return state;
      return { ...state, hoveredIndex: action.index };
    case "setMenuIndex":
      if (state.menuIndex === action.index) return state;
      return { ...state, menuIndex: action.index };
    default: {
      const exhaustive: never = action;
      return exhaustive;
    }
  }
};
