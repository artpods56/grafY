"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  ChevronLeft,
  ChevronRight,
  GripHorizontal,
  GripVertical,
  ImageIcon,
  Layers,
  ScanSearch,
  Trash2,
} from "lucide-react";

import { IconButton } from "@/components/ui/button";
import { tokens } from "@/lib/stylex/tokens.stylex";

import type {
  ArtifactCardSurfaceData,
  ArtifactStackItem,
} from "../cell-contracts";
import type { OpenSequenceSpreadLayout } from "../cell-artifact-stacking";
import { cardPlateFill, cellCornerRadius } from "../cell-glass-stage";
import type {
  CellCorners,
  CellGlassMaterial,
  CellStackStyle,
} from "../cell-glass-stage";
import { resolveNonOverlappingDelta } from "../cell-group-drag";
import {
  CARD_HEADER_HEIGHT,
  CARD_HEADER_TOP,
  CARD_PLATE_BOTTOM_INSET,
  CARD_PLATE_INSET_X,
  CARD_PLATE_TOP,
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
  shouldAnimateMotion,
} from "../cell-transitions";
import {
  ArtifactStackBacks,
  STACK_BACK_COUNT,
  stackDepthTransform,
} from "./CellArtifactCard";
import {
  CellCardMenu,
  cellCardMarks as m,
  stopCardDrag,
  styled,
  type CellCardMenuItem,
} from "./CellOperatorCard";

/**
 * A sequence card laid open in place, always anchored at `card.col` and
 * expanding strictly rightward in whole card widths (`[1][2][3][4*]` ->
 * `[2*][3][4][5*]` -> `[3*][4][5][6]`). Outer slots double as stacks only when
 * they hold 2+ items, so there are never empty docks or 1-item stacks, and the
 * frame and pager never shift while stepping. Expand, collapse, stepping, and
 * in-spread reordering all reuse `cell-transitions.ts` spring settle physics.
 */

const MONO_FONT =
  "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace";

/** How far the dashed frame stands outside the plates' cells. */
const FRAME_OUTSET = 6;
/** Screen pixels a press travels before it becomes a drag. */
const DRAG_THRESHOLD_PX = 4;
/** How long a dragged card rests on a side stack before the window steps. */
export const STACK_HOVER_STEP_MS = 350;
/** Horizontal wheel pixels per step. */
const WHEEL_STEP_PX = 40;
/** How the frame, pager and handles follow a resize of the open row. */
const RESIZE_GLIDE_MS = 220;
const RESIZE_GLIDE_EASE = "cubic-bezier(0.22, 1, 0.36, 1)";
/** How far open cards part around an external card's insertion gap. */
const EXTERNAL_GAP_SHIFT = 8;
/** How far every card slides off an edge gap, so the bar clears the frame. */
const EXTERNAL_EDGE_SHIFT = 10;
/** Synthetic ids for non-overlapping landing resolution. */
const LANDING_ID = "\u0000sequence-spread-landing";
const FRAME_ID = "\u0000sequence-spread-frame";
const MOVE_ID = "\u0000sequence-spread-move";

// StyleX evaluates these at build time, so they are plain strings, not calls.
const IMAGE_HAIRLINE =
  "inset 0 0 0 1px light-dark(color-mix(in srgb, black 9%, transparent), color-mix(in srgb, white 10%, transparent))";
const LIFTED_SHADOW =
  "0 10px 24px -6px light-dark(color-mix(in srgb, black 28%, transparent), color-mix(in srgb, black 60%, transparent))";
const HANDLE_SHADOW =
  "0 1px 3px light-dark(color-mix(in srgb, black 16%, transparent), color-mix(in srgb, black 55%, transparent))";

const s = stylex.create({
  root: {
    position: "absolute",
    pointerEvents: "auto",
    touchAction: "none",
    outline: "none",
  },
  content: {
    position: "absolute",
    inset: 0,
    willChange: "transform",
  },
  frame: {
    position: "absolute",
    boxSizing: "border-box",
    borderWidth: "1.5px",
    borderStyle: "dashed",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "14px",
    backgroundColor: `color-mix(in srgb, ${tokens.colorSurfaceSunken} 35%, transparent)`,
    pointerEvents: "none",
    // A resize grows or shrinks the frame smoothly with its cards.
    transitionProperty: "opacity, width",
    transitionDuration: {
      default: `140ms, ${RESIZE_GLIDE_MS}ms`,
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
    transitionTimingFunction: `ease, ${RESIZE_GLIDE_EASE}`,
  },
  fadingOut: {
    opacity: 0,
    pointerEvents: "none",
  },
  moveGhost: {
    position: "absolute",
    boxSizing: "border-box",
    borderWidth: "1.5px",
    borderStyle: "dashed",
    borderColor: tokens.colorAccent,
    borderRadius: "14px",
    backgroundColor: tokens.colorAccentSoft,
    pointerEvents: "none",
  },
  slot: {
    position: "absolute",
    top: 0,
    boxSizing: "border-box",
    color: tokens.colorText,
    userSelect: "none",
    touchAction: "none",
    outline: "none",
    willChange: "transform",
  },
  // Parting around an external insertion gap and settling back are plain
  // transforms; spring-driven motion (stepping, drags) never carries this.
  slotGlide: {
    transitionProperty: "transform",
    transitionDuration: {
      default: "160ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
    transitionTimingFunction: "cubic-bezier(0.2, 0.8, 0.2, 1)",
  },
  slotPulling: {
    opacity: 0.82,
  },
  liftedPlate: {
    boxShadow: LIFTED_SHADOW,
  },
  headerMeta: {
    flexGrow: 1,
    flexShrink: 1,
    flexBasis: 0,
    minWidth: 0,
    overflow: "hidden",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "flex-end",
    gap: "5px",
    paddingInline: "2px 4px",
    color: tokens.colorSubtle,
    fontFamily: MONO_FONT,
    fontSize: "10px",
    whiteSpace: "nowrap",
  },
  grab: {
    cursor: "grab",
  },
  grabbing: {
    cursor: "grabbing",
  },
  checker: {
    position: "absolute",
    inset: 0,
    overflow: "hidden",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    color: tokens.colorSubtle,
    backgroundColor: tokens.colorSurfaceSunken,
    backgroundImage: `repeating-conic-gradient(${tokens.colorSurfaceRaised} 0% 25%, transparent 0% 50%)`,
    backgroundSize: "14px 14px",
  },
  image: {
    position: "absolute",
    inset: 0,
    display: "block",
    width: "100%",
    height: "100%",
    objectFit: "cover",
    pointerEvents: "none",
    userSelect: "none",
  },
  imageFrame: {
    position: "absolute",
    inset: 0,
    borderRadius: "inherit",
    boxShadow: IMAGE_HAIRLINE,
    pointerEvents: "none",
  },
  stack: {
    cursor: "pointer",
  },
  underCard: {
    pointerEvents: "none",
  },
  // Smoothly eases `REST_SHADOW` in/out when a tucked card clears or re-enters
  // another card's footprint so overlapping plates never stack dark halos.
  plateShadowFade: {
    transitionProperty: "box-shadow",
    transitionDuration: {
      default: "140ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
    transitionTimingFunction: "ease",
  },
  plateNoShadow: {
    boxShadow: "none",
  },
  // Matches `s.stackPeek` (`opacity: 0.55` over `colorSurfaceRaised`) at
  // `opacity: 0.45` so a plate sinking into or rising out of back #1 blends
  // seamlessly with `ArtifactStackBacks`.
  depthVeil: {
    position: "absolute",
    inset: 0,
    backgroundColor: tokens.colorSurfaceRaised,
    pointerEvents: "none",
  },
  stackDrop: {
    outline: `2px solid ${tokens.colorAccentBorder}`,
    outlineOffset: "2px",
  },
  externalInsertBar: {
    position: "absolute",
    zIndex: 7,
    width: "4px",
    marginLeft: "-2px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorAccent,
    pointerEvents: "none",
  },
  landing: {
    position: "absolute",
    boxSizing: "border-box",
    borderWidth: "1.5px",
    borderStyle: "dashed",
    borderColor: tokens.colorAccent,
    borderRadius: "10px",
    backgroundColor: tokens.colorAccentSoft,
    pointerEvents: "none",
  },
  pager: {
    position: "absolute",
    display: "flex",
    alignItems: "center",
    gap: "6px",
    transform: "translateX(-50%)",
    color: tokens.colorMuted,
    fontFamily: MONO_FONT,
    fontSize: "10.5px",
    whiteSpace: "nowrap",
    transitionProperty: "opacity, left",
    transitionDuration: {
      default: `140ms, ${RESIZE_GLIDE_MS}ms`,
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
    transitionTimingFunction: `ease, ${RESIZE_GLIDE_EASE}`,
  },
  topControls: {
    position: "absolute",
    zIndex: 8,
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    transform: "translate(-50%, -50%)",
    transitionProperty: "opacity, left",
    transitionDuration: {
      default: `140ms, ${RESIZE_GLIDE_MS}ms`,
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
    transitionTimingFunction: `ease, ${RESIZE_GLIDE_EASE}`,
  },
  handlePill: {
    boxSizing: "border-box",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "4px",
    borderRadius: "9999px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorBorderStrong,
      ":hover:not(:disabled)": tokens.colorAccentBorder,
    },
    backgroundColor: {
      default: tokens.colorChrome,
      ":hover:not(:disabled)": tokens.colorSurfaceRaised,
    },
    color: {
      default: tokens.colorMuted,
      ":hover:not(:disabled)": tokens.colorText,
    },
    boxShadow: HANDLE_SHADOW,
    userSelect: "none",
    touchAction: "none",
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccentBorder}`,
    },
  },
  handlePillActive: {
    borderColor: tokens.colorAccentBorder,
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorText,
  },
  moveHandle: {
    width: "44px",
    height: "16px",
    cursor: "grab",
  },
  moveHandleDragging: {
    cursor: "grabbing",
  },
  collapseButton: {
    height: "20px",
    margin: 0,
    paddingInline: "8px",
    fontSize: "10.5px",
    fontWeight: 500,
    lineHeight: 1,
    whiteSpace: "nowrap",
    cursor: "pointer",
  },
  resizeHandle: {
    position: "absolute",
    zIndex: 8,
    width: "16px",
    height: "44px",
    cursor: "ew-resize",
    transform: "translate(-50%, -50%)",
    // The handle's pill already draws its own colour transitions; `left`
    // follows the frame's edge as the row widens or narrows.
    transitionProperty: "left, opacity",
    transitionDuration: {
      default: `${RESIZE_GLIDE_MS}ms, 140ms`,
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
    transitionTimingFunction: `${RESIZE_GLIDE_EASE}, ease`,
  },
  resizeTuck: {
    pointerEvents: "none",
  },
});

export interface CellArtifactSequenceSpreadProps {
  card: CellCardModel;
  surface: ArtifactCardSurfaceData;
  layout: OpenSequenceSpreadLayout;
  /** Every foreground card: a pulled-out or moved spread lands clear of them. */
  foregroundCards: readonly CellCardModel[];
  /** A client point in world units. */
  screenToWorld: (clientX: number, clientY: number) => WorldPoint;
  material?: CellGlassMaterial;
  corners?: CellCorners;
  /** How the side stacks draw their backs; defaults to `fan`. */
  stackStyle?: CellStackStyle;
  cardFill?: number;
  /** Gap index (0..visibleCount) highlighted while dragging an external card over this spread. */
  externalInsertSlot?: number | null;
  /** Called whenever the active step index (`windowStart`) changes. */
  onWindowStartChange?: (windowStart: number) => void;
  onClose: () => void;
  /** The slot count a person dragged the right edge to. */
  onPreferredVisibleCountChange?: (count: number) => void;
  /** Moves the underlying sequence card when the spread's drag handle moves. */
  onMove?: (cardId: string, col: number, row: number) => void;
  onInspect?: (cardId: string) => void;
  onReorder?: (cardId: string, fromIndex: number, toIndex: number) => void;
  onExtract?: (cardId: string, index: number, targetCell: CellCoord) => void;
  onRemoveItem?: (cardId: string, index: number) => void;
}

type DragMode = "reorder" | "left" | "right" | "extract" | "none";

interface ItemDrag {
  pointerId: number;
  from: number;
  slot: number;
  startX: number;
  startY: number;
  /** The pointer's offset in the dragged card's own box, in world units. */
  grab: WorldPoint;
  active: boolean;
  mode: DragMode;
  targetSlot: number;
  landing: CellCoord | null;
  draggedSettle: CardSettleState;
  siblingSettles: Map<number, CardSettleState>;
}

interface ItemDragView {
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

interface SpreadMoveDrag {
  pointerId: number;
  startClient: WorldPoint;
  startWorld: WorldPoint;
  active: boolean;
  landingDelta: CellCoord;
  settle: CardSettleState;
}

interface SpreadMoveView {
  offset: WorldPoint;
  landingDelta: CellCoord;
}

/** A card a narrowing resize retired, for as long as it glides away. */
interface ResizeTuck {
  key: string;
  index: number;
  item: ArtifactStackItem;
}

/** A middle card a multi-slot step retired into the covered side stack. */
interface StepTuck {
  key: string;
  item: ArtifactStackItem;
  targetX: number;
}

type ClosePhase = "idle" | "rewinding" | "folding";

/** Syncs slot 0's collapsed stack backs to the fold glide into `x = 0`. */
type FoldBackSync = {
  driverKey: string;
  startX: number;
  targetX: number;
};

function fallbackItems(count: number): ArtifactStackItem[] {
  return Array.from({ length: count }, (_, index) => ({
    artifactId: `item-${index}`,
    label: `Item ${index + 1}`,
  }));
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

/**
 * The end-slot card a step covers: it stays put beneath the incoming card
 * until the step settles, while its plate and backs cascade smoothly down in
 * depth in lockstep with the incoming card's glide. When the opposite end also
 * held a stack, `reveal` drives its smooth rise back up on the same spring.
 */
type UnderCard = {
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
};

/**
 * Syncs a right-edge stack's backs to the resize glide so backs fan smoothly
 * out as cards tuck under or glide out from a resized spread.
 */
type ResizeBackSync = {
  driverKey: string;
  startX: number;
  targetX: number;
  itemCount: number;
  visibleCount: number;
};

function snapshotDrag(state: ItemDrag): ItemDragView {
  const siblingX = new Map<number, number>();
  for (const [index, settle] of state.siblingSettles) {
    siblingX.set(index, settle.current.x);
  }
  return {
    from: state.from,
    slot: state.slot,
    pos: { ...state.draggedSettle.current },
    siblingX,
    mode: state.mode,
    targetSlot: state.targetSlot,
    landing: state.landing,
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
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

export function CellArtifactSequenceSpread({
  card,
  surface,
  layout,
  foregroundCards,
  screenToWorld,
  material = "frost",
  corners = "rounded",
  stackStyle = "fan",
  cardFill,
  externalInsertSlot = null,
  onWindowStartChange,
  onClose,
  onPreferredVisibleCountChange,
  onMove,
  onInspect,
  onReorder,
  onExtract,
  onRemoveItem,
}: CellArtifactSequenceSpreadProps) {
  const items = React.useMemo(
    () => surface.stackItems ?? fallbackItems(surface.itemCount ?? 0),
    [surface.itemCount, surface.stackItems],
  );
  const w = card.widthCells;
  const h = card.heightCells;
  const cardWidth = w * CELL_SIZE;
  const cardHeight = h * CELL_SIZE;
  const plateHeight = cardHeight - CARD_PLATE_TOP - CARD_PLATE_BOTTOM_INSET;
  const frameWidth = layout.totalCols * CELL_SIZE;
  const originX = layout.startCol * CELL_SIZE;
  const originY = layout.row * CELL_SIZE;

  const visibleCount = Math.min(layout.visibleCount, items.length);
  const maxStart = Math.max(0, items.length - visibleCount);
  const [windowStartState, setWindowStart] = React.useState(0);
  const windowStart = layout.windowed
    ? clamp(windowStartState, 0, maxStart)
    : 0;
  // Items removed or the spread widened past the window: keep the stored start
  // in range, so a later insert does not jump back to a stale page.
  if (layout.windowed && windowStartState > maxStart) setWindowStart(maxStart);

  const hasLeftStack = layout.windowed && windowStart > 0;
  const hasRightStack = layout.windowed && windowStart < maxStart;
  const leftCount = hasLeftStack ? windowStart + 1 : 0;
  const rightCount = hasRightStack
    ? items.length - (windowStart + visibleCount - 1)
    : 0;

  const rootRef = React.useRef<HTMLDivElement | null>(null);
  const dragRef = React.useRef<ItemDrag | null>(null);
  const dragFrameRef = React.useRef(0);
  const [drag, setDrag] = React.useState<ItemDragView | null>(null);
  const moveRef = React.useRef<SpreadMoveDrag | null>(null);
  const moveFrameRef = React.useRef(0);
  const [moveView, setMoveView] = React.useState<SpreadMoveView | null>(null);
  const [resizing, setResizing] = React.useState(false);
  const [closePhase, setClosePhase] = React.useState<ClosePhase>("idle");
  const closing = closePhase !== "idle";
  const folding = closePhase === "folding";
  const [activeIndex, setActiveIndex] = React.useState<number | null>(null);
  const [hoveredIndex, setHoveredIndex] = React.useState<number | null>(null);
  const [menuIndex, setMenuIndex] = React.useState<number | null>(null);
  const hoverTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );
  const hoverModeRef = React.useRef<DragMode>("none");
  const wheelRef = React.useRef(0);
  const editable = Boolean(onReorder || onExtract);

  // Spring-settled card X offsets for expand, collapse, and <- / -> stepping.
  // Start slots >= 1 at x = 0 on initial mount when motion is enabled so the
  // first frame already sits stacked on `card.col` before fanning rightward.
  const motionSettlesRef = React.useRef<Map<string, CardSettleState>>(
    new Map(),
  );
  const motionFrameRef = React.useRef(0);
  const closePhaseRef = React.useRef<ClosePhase>("idle");
  const startFoldRef = React.useRef<() => void>(() => {});
  const onCloseRef = React.useRef(onClose);
  const [underCardState, setUnderCard] = React.useState<UnderCard | null>(null);
  /** Middle cards a multi-slot step retired into the covered stack. */
  const [stepTucks, setStepTucks] = React.useState<readonly StepTuck[]>([]);
  /** Cards a narrowing resize retired, gliding under the new right stack. */
  const resizeTucksRef = React.useRef<readonly ResizeTuck[]>([]);
  const [resizeTucks, setResizeTucks] = React.useState<readonly ResizeTuck[]>(
    [],
  );
  const [resizeBackSyncState, setResizeBackSync] =
    React.useState<ResizeBackSync | null>(null);
  const [foldBackSync, setFoldBackSync] = React.useState<FoldBackSync | null>(
    null,
  );
  const [motionX, setMotionX] = React.useState<ReadonlyMap<string, number>>(
    () => {
      const initial = new Map<string, number>();
      if (!shouldAnimateMotion()) return initial;
      for (let slot = 1; slot < visibleCount; slot += 1) {
        const item = items[slot];
        if (item) initial.set(`${item.artifactId}:${slot}`, 0);
      }
      return initial;
    },
  );

  // The latest window and item list, for gestures and timers.
  const windowRef = React.useRef({
    windowStart,
    maxStart,
    visibleCount,
    items,
    cardWidth,
  });
  React.useLayoutEffect(() => {
    windowRef.current = {
      windowStart,
      maxStart,
      visibleCount,
      items,
      cardWidth,
    };
    onCloseRef.current = onClose;
  });

  React.useEffect(() => {
    onWindowStartChange?.(windowStart);
  }, [onWindowStartChange, windowStart]);

  const clearHoverTimer = () => {
    if (hoverTimerRef.current !== null) clearTimeout(hoverTimerRef.current);
    hoverTimerRef.current = null;
  };
  const cancelDragFrame = () => {
    if (dragFrameRef.current !== 0) cancelAnimationFrame(dragFrameRef.current);
    dragFrameRef.current = 0;
  };
  const cancelMoveFrame = () => {
    if (moveFrameRef.current !== 0) cancelAnimationFrame(moveFrameRef.current);
    moveFrameRef.current = 0;
  };
  const cancelMotionFrame = () => {
    if (motionFrameRef.current !== 0) {
      cancelAnimationFrame(motionFrameRef.current);
    }
    motionFrameRef.current = 0;
  };

  const snapshotMotion = () => {
    const next = new Map<string, number>();
    for (const [key, settle] of motionSettlesRef.current) {
      next.set(key, settle.current.x);
    }
    return next;
  };

  const scheduleMotionTick = React.useCallback(() => {
    if (motionFrameRef.current !== 0) return;
    const tick = () => {
      motionFrameRef.current = 0;
      const now = performance.now();
      let anyActive = false;
      for (const [key, settle] of motionSettlesRef.current) {
        const stepped = stepCardSettle(settle, now);
        motionSettlesRef.current.set(key, stepped);
        if (stepped.active) anyActive = true;
      }
      setMotionX(snapshotMotion());
      if (anyActive) {
        motionFrameRef.current = requestAnimationFrame(tick);
      } else if (closePhaseRef.current === "rewinding") {
        startFoldRef.current();
      } else if (closePhaseRef.current === "folding") {
        closePhaseRef.current = "idle";
        onCloseRef.current();
      } else {
        motionSettlesRef.current.clear();
        setMotionX(new Map());
        setUnderCard(null);
        setStepTucks([]);
        resizeTucksRef.current = [];
        setResizeTucks([]);
        setResizeBackSync(null);
        setFoldBackSync(null);
      }
    };
    motionFrameRef.current = requestAnimationFrame(tick);
  }, []);

  // Expand transition: cards fan rightward out from `card.col` on mount.
  React.useEffect(() => {
    if (!shouldAnimateMotion()) return;
    const {
      windowStart: start,
      visibleCount: open,
      items: list,
      cardWidth: cw,
    } = windowRef.current;
    const now = performance.now();
    const settles = new Map<string, CardSettleState>();
    let anyActive = false;
    for (let slot = 1; slot < open; slot += 1) {
      const item = list[start + slot];
      if (!item) continue;
      const key = `${item.artifactId}:${start + slot}`;
      const settle = retargetCardSettle(
        createCardSettle({ x: 0, y: 0 }),
        { x: slot * cw, y: 0 },
        now,
      );
      settles.set(key, settle);
      if (settle.active) anyActive = true;
    }
    if (!anyActive) return;
    motionSettlesRef.current = settles;
    scheduleMotionTick();
  }, [scheduleMotionTick]);

  React.useEffect(
    () => () => {
      clearHoverTimer();
      cancelDragFrame();
      cancelMoveFrame();
      cancelMotionFrame();
    },
    [],
  );

  const startFold = React.useCallback(() => {
    const {
      windowStart: start,
      visibleCount: open,
      items: list,
      cardWidth: cw,
    } = windowRef.current;
    const now = performance.now();
    const settles = new Map<string, CardSettleState>();
    let anyActive = false;
    let driver: FoldBackSync | null = null;
    for (let slot = 0; slot < open; slot += 1) {
      const item = list[start + slot];
      if (!item) continue;
      const key = `${item.artifactId}:${start + slot}`;
      const current =
        motionSettlesRef.current.get(key) ??
        createCardSettle({ x: slot * cw, y: 0 });
      const settle = retargetCardSettle(current, { x: 0, y: 0 }, now);
      settles.set(key, settle);
      if (settle.active) {
        anyActive = true;
        if (slot > 0 && driver === null) {
          driver = { driverKey: key, startX: settle.current.x, targetX: 0 };
        }
      }
    }
    if (!anyActive) {
      closePhaseRef.current = "idle";
      setClosePhase("idle");
      onCloseRef.current();
      return;
    }
    closePhaseRef.current = "folding";
    setClosePhase("folding");
    setUnderCard(null);
    setStepTucks([]);
    resizeTucksRef.current = [];
    setResizeTucks([]);
    setResizeBackSync(null);
    setFoldBackSync(driver);
    motionSettlesRef.current = settles;
    setMotionX(snapshotMotion());
    scheduleMotionTick();
  }, [scheduleMotionTick]);

  React.useLayoutEffect(() => {
    startFoldRef.current = startFold;
  }, [startFold]);

  const performStep = React.useCallback(
    (by: number): boolean => {
      const {
        windowStart: current,
        maxStart: last,
        visibleCount: open,
        items: list,
        cardWidth: cw,
      } = windowRef.current;
      const next = clamp(current + by, 0, last);
      if (next === current) return false;
      const delta = next - current;
      windowRef.current = { ...windowRef.current, windowStart: next };
      // A card held over a side stack steps the window mid-drag; its siblings'
      // settles were in the old window's slots, so they hand over to motion.
      const held = dragRef.current?.active ? dragRef.current : null;
      let startedMotion = false;

      if (shouldAnimateMotion()) {
        const now = performance.now();
        const nextSettles = new Map<string, CardSettleState>();
        let anyActive = false;
        for (let slot = 0; slot < open; slot += 1) {
          const item = list[next + slot];
          if (!item) continue;
          const key = `${item.artifactId}:${next + slot}`;
          const prevSlot = clamp(slot + delta, 0, open - 1);
          const from =
            motionSettlesRef.current.get(key) ??
            held?.siblingSettles.get(next + slot) ??
            createCardSettle({ x: prevSlot * cw, y: 0 });
          const settle = retargetCardSettle(from, { x: slot * cw, y: 0 }, now);
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
          const oldKey = `${oldItem.artifactId}:${oldIndex}`;
          const from =
            motionSettlesRef.current.get(oldKey) ??
            held?.siblingSettles.get(oldIndex) ??
            createCardSettle({ x: oldSlot * cw, y: 0 });
          const tuckKey = `step-tuck:${oldItem.artifactId}:${oldIndex}`;
          const targetX = coverSlot * cw;
          const settle = retargetCardSettle(from, { x: targetX, y: 0 }, now);
          nextSettles.set(tuckKey, settle);
          if (settle.active) anyActive = true;
          nextStepTucks.push({ key: tuckKey, item: oldItem, targetX });
        }
        motionSettlesRef.current = nextSettles;
        setMotionX(snapshotMotion());
        resizeTucksRef.current = [];
        setResizeTucks([]);
        setResizeBackSync(null);
        setFoldBackSync(null);
        if (anyActive) {
          startedMotion = true;
          // The end slot the incoming card glides onto keeps its old card
          // beneath until the step lands: slot 0 stepping ->, S-1 stepping <-.
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
          const coverKey = coverItem
            ? `${coverItem.artifactId}:${next + coverSlot}`
            : "";
          const coverSettle = nextSettles.get(coverKey);
          const coverStartX = coverSettle
            ? coverSettle.current.x
            : coverSlot * cw;
          const coverTargetX = coverSlot * cw;
          const hadOppositeStack = delta > 0 ? current < last : current > 0;
          const reveal = hadOppositeStack
            ? {
                side: side === "left" ? ("right" as const) : ("left" as const),
                shift,
              }
            : null;
          setStepTucks(nextStepTucks);
          setUnderCard({
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
          });
          scheduleMotionTick();
        } else {
          setUnderCard(null);
          setStepTucks([]);
        }
      }
      if (held) {
        held.siblingSettles.clear();
        setDrag(snapshotDrag(held));
      }

      setWindowStart(next);
      return startedMotion;
    },
    [scheduleMotionTick],
  );

  const requestClose = React.useCallback(() => {
    if (closePhaseRef.current !== "idle") return;
    if (!shouldAnimateMotion()) {
      onCloseRef.current();
      return;
    }
    const { windowStart: start } = windowRef.current;
    if (start > 0) {
      closePhaseRef.current = "rewinding";
      setClosePhase("rewinding");
      if (performStep(-start)) return;
    }
    startFold();
  }, [performStep, startFold]);

  const step = React.useCallback(
    (by: number) => {
      if (closePhaseRef.current !== "idle") return;
      performStep(by);
    },
    [performStep],
  );

  // A horizontal swipe over the spread pages it instead of panning the
  // canvas; the canvas listens natively, so this must too.
  React.useEffect(() => {
    const element = rootRef.current;
    if (!element || !layout.windowed) return;
    const onWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaX) <= Math.abs(event.deltaY)) return;
      event.preventDefault();
      event.stopPropagation();
      wheelRef.current += event.deltaX;
      while (Math.abs(wheelRef.current) >= WHEEL_STEP_PX) {
        const direction = Math.sign(wheelRef.current);
        step(direction);
        wheelRef.current -= direction * WHEEL_STEP_PX;
      }
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [layout.windowed, step]);

  const slotLeft = (slot: number) => slot * cardWidth;

  const scheduleDragTick = () => {
    if (dragFrameRef.current !== 0) return;
    dragFrameRef.current = requestAnimationFrame(() => {
      dragFrameRef.current = 0;
      const state = dragRef.current;
      if (!state || !state.active) return;
      const now = performance.now();
      state.draggedSettle = stepCardSettle(state.draggedSettle, now);
      let anyActive = state.draggedSettle.active;
      for (const [index, settle] of state.siblingSettles) {
        const stepped = stepCardSettle(settle, now);
        state.siblingSettles.set(index, stepped);
        if (stepped.active) anyActive = true;
      }
      setDrag(snapshotDrag(state));
      if (anyActive) scheduleDragTick();
    });
  };

  const scheduleMoveTick = () => {
    if (moveFrameRef.current !== 0) return;
    moveFrameRef.current = requestAnimationFrame(() => {
      moveFrameRef.current = 0;
      const state = moveRef.current;
      if (!state || !state.active) return;
      const now = performance.now();
      state.settle = stepCardSettle(state.settle, now);
      setMoveView({
        offset: { ...state.settle.current },
        landingDelta: state.landingDelta,
      });
      if (state.settle.active) scheduleMoveTick();
    });
  };

  const modeAt = (point: WorldPoint, state: ItemDrag) => {
    const inside =
      point.x >= originX - FRAME_OUTSET &&
      point.x <= originX + frameWidth + FRAME_OUTSET &&
      point.y >= originY - FRAME_OUTSET &&
      point.y <= originY + cardHeight + FRAME_OUTSET;
    const {
      windowStart: start,
      maxStart: last,
      visibleCount: open,
    } = windowRef.current;
    const leftStackActive = layout.windowed && start > 0;
    const rightStackActive = layout.windowed && start < last;
    if (inside) {
      if (leftStackActive && point.x < originX + cardWidth) {
        return {
          mode: "left" as const,
          targetSlot: state.targetSlot,
          landing: null,
        };
      }
      if (rightStackActive && point.x >= originX + (open - 1) * cardWidth) {
        return {
          mode: "right" as const,
          targetSlot: state.targetSlot,
          landing: null,
        };
      }
      const firstOpenSlot = leftStackActive ? 1 : 0;
      const lastOpenSlot = rightStackActive ? open - 2 : open - 1;
      const cardCenterX = point.x - state.grab.x + cardWidth / 2;
      const targetSlot = clamp(
        Math.floor((cardCenterX - originX) / cardWidth),
        firstOpenSlot,
        Math.max(firstOpenSlot, lastOpenSlot),
      );
      return { mode: "reorder" as const, targetSlot, landing: null };
    }
    if (!onExtract) {
      return {
        mode: "none" as const,
        targetSlot: state.targetSlot,
        landing: null,
      };
    }
    const col = Math.round((point.x - state.grab.x) / CELL_SIZE);
    const row = Math.round((point.y - state.grab.y) / CELL_SIZE);
    const landingCard: CellCardModel = { ...card, id: LANDING_ID, col, row };
    const frameCard: CellCardModel = {
      ...card,
      id: FRAME_ID,
      col: layout.startCol,
      row: layout.row,
      widthCells: layout.totalCols,
      heightCells: h,
    };
    const delta = resolveNonOverlappingDelta(
      [...foregroundCards, frameCard, landingCard],
      new Set([LANDING_ID]),
      { col: 0, row: 0 },
    );
    return {
      mode: "extract" as const,
      targetSlot: state.targetSlot,
      landing: { col: col + delta.col, row: row + delta.row },
    };
  };

  const targetPointForDrag = (
    mode: DragMode,
    targetSlot: number,
    landing: CellCoord | null,
    fallbackSlot: number,
  ): WorldPoint => {
    if (mode === "reorder") return { x: slotLeft(targetSlot), y: 0 };
    if (mode === "left") return { x: 0, y: 0 };
    if (mode === "right") {
      return { x: slotLeft(windowRef.current.visibleCount - 1), y: 0 };
    }
    if (mode === "extract" && landing) {
      return {
        x: (landing.col - layout.startCol) * CELL_SIZE,
        y: (landing.row - layout.row) * CELL_SIZE,
      };
    }
    return { x: slotLeft(fallbackSlot), y: 0 };
  };

  const armHoverStep = (mode: DragMode) => {
    if (mode === hoverModeRef.current) return;
    hoverModeRef.current = mode;
    clearHoverTimer();
    if (mode !== "left" && mode !== "right") return;
    const direction = mode === "left" ? -1 : 1;
    const tick = () => {
      step(direction);
      hoverTimerRef.current = setTimeout(tick, STACK_HOVER_STEP_MS);
    };
    hoverTimerRef.current = setTimeout(tick, STACK_HOVER_STEP_MS);
  };

  const onItemPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.stopPropagation();
    if (closePhaseRef.current !== "idle") return;
    const index = Number(event.currentTarget.dataset.sequenceItem);
    const slot = Number(event.currentTarget.dataset.sequenceSlot);
    setActiveIndex(index);
    if (event.button !== 0 || !editable) return;
    const world = screenToWorld(event.clientX, event.clientY);
    const origin = { x: slotLeft(slot), y: 0 };
    dragRef.current = {
      pointerId: event.pointerId,
      from: index,
      slot,
      startX: event.clientX,
      startY: event.clientY,
      grab: {
        x: world.x - (originX + origin.x),
        y: world.y - originY,
      },
      active: false,
      mode: "reorder",
      targetSlot: slot,
      landing: null,
      draggedSettle: createCardSettle(origin),
      siblingSettles: new Map(),
    };
  };

  const onItemPointerMove = (event: PointerEvent) => {
    const state = dragRef.current;
    if (!state || state.pointerId !== event.pointerId) return;
    let activated = false;
    if (!state.active) {
      const travelled = Math.hypot(
        event.clientX - state.startX,
        event.clientY - state.startY,
      );
      if (travelled < DRAG_THRESHOLD_PX) return;
      state.active = true;
      activated = true;
    }
    const world = screenToWorld(event.clientX, event.clientY);
    const at = modeAt(world, state);
    armHoverStep(at.mode);

    const changedTarget =
      activated ||
      at.mode !== state.mode ||
      at.targetSlot !== state.targetSlot ||
      at.landing?.col !== state.landing?.col ||
      at.landing?.row !== state.landing?.row;

    if (!changedTarget) return;

    state.mode = at.mode;
    state.targetSlot = at.targetSlot;
    state.landing = at.landing;

    const now = performance.now();
    const animate = shouldAnimateMotion();
    const nextPoint = targetPointForDrag(
      at.mode,
      at.targetSlot,
      at.landing,
      state.slot,
    );
    state.draggedSettle = retargetSettle(
      state.draggedSettle,
      nextPoint,
      now,
      animate,
    );

    const {
      windowStart: start,
      visibleCount: open,
      items: list,
    } = windowRef.current;
    let anyActive = state.draggedSettle.active;
    for (let slot = 0; slot < open; slot += 1) {
      const index = start + slot;
      if (index === state.from) continue;
      const visualSlot = visualSlotForSibling(
        slot,
        state.from,
        at.mode,
        at.targetSlot,
        start,
        open,
      );
      const targetPoint = { x: slotLeft(visualSlot), y: 0 };
      const existing = state.siblingSettles.get(index);
      if (!existing && visualSlot === slot) continue;
      // Pick up from wherever a step is still carrying this card.
      const item = list[index];
      const stepping = item
        ? motionSettlesRef.current.get(`${item.artifactId}:${index}`)
        : undefined;
      const nextSibling = retargetSettle(
        existing ?? stepping ?? createCardSettle({ x: slotLeft(slot), y: 0 }),
        targetPoint,
        now,
        animate,
      );
      state.siblingSettles.set(index, nextSibling);
      if (nextSibling.active) anyActive = true;
    }

    setDrag(snapshotDrag(state));
    if (anyActive) scheduleDragTick();
  };

  const endItemDrag = (event: PointerEvent) => {
    const state = dragRef.current;
    if (!state || state.pointerId !== event.pointerId) return;
    dragRef.current = null;
    cancelDragFrame();
    armHoverStep("none");
    setDrag(null);
    if (!state.active || event.type === "pointercancel") return;
    const at = modeAt(screenToWorld(event.clientX, event.clientY), state);
    const { windowStart: start, visibleCount: open } = windowRef.current;
    switch (at.mode) {
      case "reorder": {
        const to = reorderDropIndex(start, at.targetSlot);
        if (to !== state.from) onReorder?.(card.id, state.from, to);
        return;
      }
      case "left": {
        const to = clamp(start, 0, items.length - 1);
        if (to !== state.from) onReorder?.(card.id, state.from, to);
        return;
      }
      case "right": {
        const to = clamp(start + open - 1, 0, items.length - 1);
        if (to !== state.from) onReorder?.(card.id, state.from, to);
        return;
      }
      case "extract":
        if (at.landing) onExtract?.(card.id, state.from, at.landing);
        return;
      case "none":
        return;
    }
  };

  // Top-edge move drag handle: moves the whole spread (and its stack card) on
  // the cell grid using the same settle physics and non-overlapping placement.
  const onMovePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.stopPropagation();
    if (event.button !== 0 || !onMove || closePhaseRef.current !== "idle")
      return;
    const world = screenToWorld(event.clientX, event.clientY);
    moveRef.current = {
      pointerId: event.pointerId,
      startClient: { x: event.clientX, y: event.clientY },
      startWorld: world,
      active: false,
      landingDelta: { col: 0, row: 0 },
      settle: createCardSettle({ x: 0, y: 0 }),
    };
  };

  const resolveSpreadMoveDelta = (rawDelta: CellCoord): CellCoord => {
    const others = foregroundCards.filter(
      (candidate) => candidate.id !== card.id,
    );
    const spreadBox: CellCardModel = {
      ...card,
      id: MOVE_ID,
      col: layout.startCol,
      row: layout.row,
      widthCells: layout.totalCols,
      heightCells: h,
    };
    return resolveNonOverlappingDelta(
      [...others, spreadBox],
      new Set([MOVE_ID]),
      rawDelta,
    );
  };

  const onMovePointerMove = (event: PointerEvent) => {
    const state = moveRef.current;
    if (!state || state.pointerId !== event.pointerId) return;
    let activated = false;
    if (!state.active) {
      const travelled = Math.hypot(
        event.clientX - state.startClient.x,
        event.clientY - state.startClient.y,
      );
      if (travelled < DRAG_THRESHOLD_PX) return;
      state.active = true;
      activated = true;
    }
    const world = screenToWorld(event.clientX, event.clientY);
    const rawDelta: CellCoord = {
      col: Math.round((world.x - state.startWorld.x) / CELL_SIZE),
      row: Math.round((world.y - state.startWorld.y) / CELL_SIZE),
    };
    const landingDelta = resolveSpreadMoveDelta(rawDelta);
    if (
      !activated &&
      landingDelta.col === state.landingDelta.col &&
      landingDelta.row === state.landingDelta.row
    ) {
      return;
    }
    state.landingDelta = landingDelta;
    const now = performance.now();
    const target = {
      x: landingDelta.col * CELL_SIZE,
      y: landingDelta.row * CELL_SIZE,
    };
    state.settle = retargetSettle(
      state.settle,
      target,
      now,
      shouldAnimateMotion(),
    );
    setMoveView({
      offset: { ...state.settle.current },
      landingDelta,
    });
    if (state.settle.active) scheduleMoveTick();
  };

  const endMoveDrag = (event: PointerEvent) => {
    const state = moveRef.current;
    if (!state || state.pointerId !== event.pointerId) return;
    moveRef.current = null;
    cancelMoveFrame();
    setMoveView(null);
    if (!state.active || event.type === "pointercancel") return;
    const world = screenToWorld(event.clientX, event.clientY);
    const rawDelta: CellCoord = {
      col: Math.round((world.x - state.startWorld.x) / CELL_SIZE),
      row: Math.round((world.y - state.startWorld.y) / CELL_SIZE),
    };
    const delta = resolveSpreadMoveDelta(rawDelta);
    if (delta.col !== 0 || delta.row !== 0) {
      onMove?.(card.id, card.col + delta.col, card.row + delta.row);
    }
  };

  const windowDragHandlers = React.useRef({
    itemMove: onItemPointerMove,
    itemEnd: endItemDrag,
    spreadMove: onMovePointerMove,
    spreadEnd: endMoveDrag,
  });
  React.useLayoutEffect(() => {
    windowDragHandlers.current = {
      itemMove: onItemPointerMove,
      itemEnd: endItemDrag,
      spreadMove: onMovePointerMove,
      spreadEnd: endMoveDrag,
    };
  });
  React.useEffect(() => {
    const move = (event: PointerEvent) => {
      windowDragHandlers.current.itemMove(event);
      windowDragHandlers.current.spreadMove(event);
    };
    const end = (event: PointerEvent) => {
      windowDragHandlers.current.itemEnd(event);
      windowDragHandlers.current.spreadEnd(event);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", end);
    window.addEventListener("pointercancel", end);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", end);
      window.removeEventListener("pointercancel", end);
    };
  }, []);

  /** One card, or with Shift a page: the open cards between the stacks. */
  const stepBy = (direction: number, page: boolean) => {
    const pageStep = Math.max(1, windowRef.current.visibleCount - 2);
    step(direction * (page ? pageStep : 1));
  };
  /** A side stack steps toward itself. */
  const onStackClick = (event: React.MouseEvent<HTMLDivElement>) => {
    const direction =
      event.currentTarget.dataset.sequenceStack === "left" ? -1 : 1;
    stepBy(direction, event.shiftKey);
  };
  const onStackKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    const direction =
      event.currentTarget.dataset.sequenceStack === "left" ? -1 : 1;
    stepBy(direction, event.shiftKey);
  };

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      requestClose();
      return;
    }
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
    const direction = event.key === "ArrowLeft" ? -1 : 1;
    if (event.altKey) {
      const index = activeIndex;
      if (index === null || !onReorder) return;
      const to = index + direction;
      if (to < 0 || to >= items.length) return;
      event.preventDefault();
      event.stopPropagation();
      onReorder(card.id, index, to);
      setActiveIndex(to);
      return;
    }
    if (!layout.windowed) return;
    event.preventDefault();
    event.stopPropagation();
    stepBy(direction, event.shiftKey);
  };

  // Resizing the spread by its right edge, in whole card slots.
  const resizeRef = React.useRef<{
    pointerId: number;
    startX: number;
    startCount: number;
    last: number;
  } | null>(null);
  const onResizePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.stopPropagation();
    if (event.button !== 0 || closePhaseRef.current !== "idle") return;
    resizeRef.current = {
      pointerId: event.pointerId,
      startX: screenToWorld(event.clientX, event.clientY).x,
      startCount: visibleCount,
      last: visibleCount,
    };
    setResizing(true);
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };
  // Resize transition: when the open row widens, the cards it reveals glide
  // out from the old right edge; when it narrows, the cards it retires glide
  // in under the new right stack before they go.
  const glideResize = (nextVisibleCount: number) => {
    if (closePhaseRef.current !== "idle" || !shouldAnimateMotion()) return;
    const {
      windowStart: seenStart,
      visibleCount: seenCount,
      items: list,
      cardWidth: cw,
    } = windowRef.current;
    // The window the parent will draw for that count, clamped as above.
    const nextCount = Math.min(nextVisibleCount, list.length);
    const nextStart =
      nextCount < list.length
        ? clamp(seenStart, 0, Math.max(0, list.length - nextCount))
        : 0;
    if (nextCount === seenCount) return;
    const now = performance.now();
    const prevSettles = motionSettlesRef.current;
    const nextSettles = new Map<string, CardSettleState>();
    let anyActive = false;

    const takePreviousSettle = (
      item: ArtifactStackItem,
      index: number,
      fallbackX: number,
    ): CardSettleState =>
      prevSettles.get(`${item.artifactId}:${index}`) ??
      prevSettles.get(`resize-tuck:${item.artifactId}:${index}`) ??
      createCardSettle({ x: fallbackX, y: 0 });

    const glide = (key: string, from: CardSettleState, toX: number) => {
      const settle = retargetCardSettle(from, { x: toX, y: 0 }, now);
      nextSettles.set(key, settle);
      if (settle.active) anyActive = true;
      return settle;
    };

    const nextOpenIndices = new Set<number>();
    // Every card still open comes from where the old row (or an in-flight
    // tuck) drew it: its live settle, its old slot, or the end of the old row.
    for (let slot = 0; slot < nextCount; slot += 1) {
      const index = nextStart + slot;
      const item = list[index];
      if (!item) continue;
      nextOpenIndices.add(index);
      const key = `${item.artifactId}:${index}`;
      const seenSlot = index - seenStart;
      const fromSlot = seenSlot < 0 ? 0 : Math.min(seenSlot, seenCount - 1);
      const hasPrior =
        prevSettles.has(key) ||
        prevSettles.has(`resize-tuck:${item.artifactId}:${index}`);
      if (fromSlot === slot && !hasPrior) continue;
      glide(key, takePreviousSettle(item, index, fromSlot * cw), slot * cw);
    }

    const rightEdgeX = (nextCount - 1) * cw;
    const nextTucksByIndex = new Map<number, ResizeTuck>();
    const newlyRetired: ResizeTuck[] = [];

    // Retire cards leaving the right side of the row into the new right edge.
    for (let slot = nextCount; slot < seenCount; slot += 1) {
      const index = seenStart + slot;
      if (nextOpenIndices.has(index)) continue;
      const item = list[index];
      if (!item) continue;
      const key = `resize-tuck:${item.artifactId}:${index}`;
      const from = takePreviousSettle(item, index, slot * cw);
      glide(key, from, rightEdgeX);
      const tuck: ResizeTuck = { key, index, item };
      nextTucksByIndex.set(index, tuck);
      newlyRetired.push(tuck);
    }

    // Retarget any already-tucking cards to the new right edge so rapid
    // narrowing never strands them outside the frame, and drop any that were
    // re-opened or are already behind the widened right edge.
    if (nextStart + nextCount < list.length) {
      for (const existing of resizeTucksRef.current) {
        if (
          nextOpenIndices.has(existing.index) ||
          nextTucksByIndex.has(existing.index)
        ) {
          continue;
        }
        const live = prevSettles.get(existing.key);
        if (!live || live.current.x <= rightEdgeX + 0.5) continue;
        glide(existing.key, live, rightEdgeX);
        nextTucksByIndex.set(existing.index, existing);
      }
    }

    const nextTucks = [...nextTucksByIndex.values()].sort(
      (a, b) => b.index - a.index,
    );

    windowRef.current = {
      ...windowRef.current,
      windowStart: nextStart,
      visibleCount: nextCount,
    };
    motionSettlesRef.current = nextSettles;
    resizeTucksRef.current = anyActive ? nextTucks : [];
    setUnderCard(null);
    setStepTucks([]);
    setResizeTucks(resizeTucksRef.current);

    if (!anyActive) {
      setMotionX(new Map());
      setResizeBackSync(null);
      return;
    }

    if (newlyRetired.length > 0) {
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
        setResizeBackSync({
          driverKey: driver.key,
          startX: driver.startX,
          targetX: rightEdgeX,
          itemCount: list.length,
          visibleCount: nextCount,
        });
      }
    } else if (nextCount > seenCount && nextStart + nextCount < list.length) {
      const endIndex = nextStart + nextCount - 1;
      const endItem = list[endIndex];
      const driverKey = endItem ? `${endItem.artifactId}:${endIndex}` : "";
      const driverSettle = driverKey ? nextSettles.get(driverKey) : undefined;
      if (driverKey && driverSettle) {
        setResizeBackSync({
          driverKey,
          startX: driverSettle.current.x,
          targetX: rightEdgeX,
          itemCount: list.length,
          visibleCount: nextCount,
        });
      }
    } else {
      setResizeBackSync(null);
    }
    setMotionX(snapshotMotion());
    scheduleMotionTick();
  };
  const onResizePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const state = resizeRef.current;
    if (!state || state.pointerId !== event.pointerId) return;
    const dx = screenToWorld(event.clientX, event.clientY).x - state.startX;
    const next = clamp(
      state.startCount + Math.round(dx / cardWidth),
      layout.minVisibleCount,
      layout.maxVisibleCount,
    );
    if (next === state.last) return;
    state.last = next;
    glideResize(next);
    onPreferredVisibleCountChange?.(next);
  };
  const endResize = (event: React.PointerEvent<HTMLDivElement>) => {
    const state = resizeRef.current;
    if (!state || state.pointerId !== event.pointerId) return;
    resizeRef.current = null;
    setResizing(false);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };

  const plateFill = cardPlateFill(material, cardFill);
  const radius = cellCornerRadius(corners);
  const plateLook = (active: boolean, shadow = true): stylex.StyleXStyles[] => [
    m.plate,
    s.plateShadowFade,
    material === "liquid" ? m.plateLiquid : m.plateFrost,
    active && m.plateActive,
    shadow
      ? material === "liquid"
        ? active
          ? m.liquidShadowActive
          : m.liquidShadow
        : active
          ? m.frostShadowActive
          : m.frostShadow
      : s.plateNoShadow,
  ];
  const headerBoxWithOpacity = (opacity: number): React.CSSProperties =>
    opacity < 0.999
      ? { ...headerBox, opacity: Number(opacity.toFixed(3)) }
      : headerBox;
  /** Fades tucked cards' headers & drop shadows while overlapping slot 0. */
  const tuckedHeaderOpacity = (slot: number, currentX: number) => {
    if (slot === 0) return 1;
    if (!folding && currentX >= cardWidth) return 1;
    return clamp((currentX - cardWidth * 0.25) / (cardWidth * 0.55), 0, 1);
  };
  const tuckedPlateShadow = (
    slot: number,
    currentX: number,
    liftDepth: number,
  ) => {
    if (liftDepth > 0.5) return false;
    if (slot === 0) return true;
    if (folding) return false;
    return currentX >= cardWidth * 0.55;
  };
  const plateBox: React.CSSProperties = {
    height: plateHeight,
    marginInline: CARD_PLATE_INSET_X,
    borderRadius: radius,
    backgroundColor: plateFill,
  };
  const headerBox: React.CSSProperties = {
    marginTop: CARD_HEADER_TOP,
    height: CARD_HEADER_HEIGHT,
    marginBottom: CARD_PLATE_TOP - CARD_HEADER_TOP - CARD_HEADER_HEIGHT,
    paddingInline: CARD_PLATE_INSET_X,
  };

  const renderPicture = (item: ArtifactStackItem | undefined) => (
    <>
      <span {...stylex.props(s.checker)}>
        {item?.imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- artifact bytes have no predictable size for the image optimizer
          <img
            src={item.imageUrl}
            alt={item.label}
            draggable={false}
            {...stylex.props(s.image)}
          />
        ) : (
          <ImageIcon size={18} aria-hidden="true" />
        )}
      </span>
      {item?.imageUrl ? (
        <span aria-hidden="true" {...stylex.props(s.imageFrame)} />
      ) : null}
    </>
  );

  const menuItemsFor = (index: number): CellCardMenuItem[] => {
    const menu: CellCardMenuItem[] = [];
    if (onInspect) {
      menu.push({
        id: "inspect",
        label: "Inspect",
        icon: <ScanSearch size={13} />,
        onSelect: () => onInspect(card.id),
      });
    }
    if (onRemoveItem) {
      menu.push({
        id: "remove",
        label: "Remove",
        icon: <Trash2 size={13} />,
        danger: true,
        onSelect: () => onRemoveItem(card.id, index),
      });
    }
    return menu;
  };

  const externalShiftForSlot = (slot: number): number => {
    if (externalInsertSlot === null) return 0;
    if (externalInsertSlot === 0) return EXTERNAL_EDGE_SHIFT;
    if (externalInsertSlot >= visibleCount) return -EXTERNAL_EDGE_SHIFT;
    return slot < externalInsertSlot ? -EXTERNAL_GAP_SHIFT : EXTERNAL_GAP_SHIFT;
  };
  /** The insertion bar sits mid-gap: at an edge, between frame and plates. */
  const externalBarLeft = (slot: number): number => {
    if (slot <= 0) return EXTERNAL_EDGE_SHIFT / 2;
    if (slot >= visibleCount) return frameWidth - EXTERNAL_EDGE_SHIFT / 2;
    return slotLeft(slot);
  };
  // A drag, a resize, a fold, or a new list or row drops the under-card.
  const underCard =
    underCardState &&
    underCardState.items === items &&
    underCardState.visibleCount === visibleCount &&
    !drag &&
    !resizing &&
    !folding
      ? underCardState
      : null;
  const coveringSlot =
    underCard === null
      ? null
      : underCard.side === "left"
        ? 0
        : visibleCount - 1;

  const progressFor = (key: string, startX: number, targetX: number) => {
    const span = Math.abs(targetX - startX);
    if (span < 0.5) return 1;
    const currentX = motionX.get(key);
    if (currentX === undefined) return 1;
    return clamp(1 - Math.abs(targetX - currentX) / span, 0, 1);
  };

  const stepProgress = underCard
    ? progressFor(
        underCard.coverKey,
        underCard.coverStartX,
        underCard.coverTargetX,
      )
    : 0;

  const resizeBackSync =
    resizeBackSyncState &&
    resizeBackSyncState.itemCount === items.length &&
    resizeBackSyncState.visibleCount === visibleCount &&
    !drag &&
    !closing &&
    underCard === null
      ? resizeBackSyncState
      : null;
  const resizeBackProgress = resizeBackSync
    ? progressFor(
        resizeBackSync.driverKey,
        resizeBackSync.startX,
        resizeBackSync.targetX,
      )
    : 1;
  const foldProgress =
    folding && foldBackSync !== null
      ? progressFor(
          foldBackSync.driverKey,
          foldBackSync.startX,
          foldBackSync.targetX,
        )
      : 0;

  const depthPlateBox = (depth: number): React.CSSProperties =>
    depth > 0.001
      ? { ...plateBox, ...stackDepthTransform(card, stackStyle, depth) }
      : plateBox;
  const renderDepthVeil = (depth: number) =>
    depth > 0.001 ? (
      <span
        aria-hidden="true"
        {...styled(
          { opacity: Number((0.45 * Math.min(1, depth)).toFixed(3)) },
          s.depthVeil,
        )}
      />
    ) : null;

  const renderUnderCard = (under: UnderCard) => {
    const item = items[under.index];
    if (!item) return null;
    const slot = under.side === "left" ? 0 : visibleCount - 1;
    const inward = under.side === "left" ? -1 : 1;
    const stacked = under.stackCount > 0;
    const sinkDepth = under.shift * stepProgress;
    const meta = !stacked
      ? item.label
      : under.side === "left"
        ? `1–${under.index + 1}`
        : `${under.index + 1}–${items.length}`;
    const underHeaderOpacity = clamp(1 - (stepProgress - 0.3) / 0.45, 0, 1);
    return (
      <div
        key={`under:${under.side}`}
        aria-hidden="true"
        data-sequence-under-card={under.side}
        data-sequence-under-card-top={item.artifactId}
        {...styled(
          {
            left: slotLeft(slot),
            width: cardWidth,
            height: cardHeight,
            zIndex: 1,
          },
          s.slot,
          s.underCard,
        )}
      >
        <div
          data-card-header="true"
          {...styled(headerBoxWithOpacity(underHeaderOpacity), m.header)}
        >
          <span data-card-title="rest" {...stylex.props(m.title, m.titleFixed)}>
            {surface.typeLabel}
          </span>
          <span data-card-meta="true" {...stylex.props(s.headerMeta)}>
            <span {...stylex.props(m.ellipsis)}>{meta}</span>
          </span>
        </div>
        {stacked ? (
          <ArtifactStackBacks
            card={card}
            corners={corners}
            punched={false}
            peeks={[
              items[under.index + inward]?.imageUrl ?? "",
              items[under.index + inward * 2]?.imageUrl ?? "",
            ]}
            backs={Math.min(2, under.stackCount - 1)}
            stackStyle={stackStyle}
            depthOffset={sinkDepth}
          />
        ) : null}
        <article
          data-plate-shadow="none"
          {...styled(depthPlateBox(sinkDepth), ...plateLook(false, false))}
        >
          {renderPicture(item)}
          {renderDepthVeil(sinkDepth)}
        </article>
      </div>
    );
  };

  /** A slot glides on CSS only while no spring is carrying it. */
  const glides = (key: string) => !drag && !closing && !motionX.has(key);

  const renderStackSlot = (
    slot: number,
    index: number,
    side: "left" | "right",
  ) => {
    const inward = side === "left" ? -1 : 1;
    // A held card that stepped onto a stack's top leaves the next one showing.
    const held = drag?.from === index;
    const topIndex = held ? index + inward : index;
    const item = items[topIndex];
    if (!item) return null;
    const count = side === "left" ? leftCount : rightCount;
    const peeks = [
      items[topIndex + inward]?.imageUrl ?? "",
      items[topIndex + inward * 2]?.imageUrl ?? "",
    ];
    const rangeLabel =
      side === "left" ? `1–${windowStart + 1}` : `${index + 1}–${items.length}`;
    const dropping = drag?.mode === side;
    const baseLeft = slotLeft(slot);
    const key = `${item.artifactId}:${topIndex}`;
    const animatedX = motionX.get(key);
    const dx =
      (animatedX !== undefined ? animatedX - baseLeft : 0) +
      externalShiftForSlot(slot);
    const transform = dx !== 0 ? `translate3d(${dx}px, 0px, 0)` : undefined;
    const ariaLabel =
      side === "left"
        ? `${count} items (${rangeLabel}), show previous`
        : `${count} items (${rangeLabel}), show next`;

    const liftDepth =
      underCard?.reveal?.side === side
        ? (1 - stepProgress) * underCard.reveal.shift
        : 0;
    const stackDepthScale =
      folding && side === "right"
        ? clamp(1 - foldProgress * 2.5, 0, 1)
        : side === "right" && resizeBackSync !== null && coveringSlot !== slot
          ? resizeBackProgress
          : 1;
    const hideStackBacks =
      coveringSlot === slot ||
      (folding && side === "right" && stackDepthScale <= 0.01);
    const currentX = animatedX ?? baseLeft;
    const stackHeaderOpacity = tuckedHeaderOpacity(slot, currentX);
    const stackShadow = tuckedPlateShadow(slot, currentX, liftDepth);

    return (
      <div
        key={key}
        role="button"
        tabIndex={0}
        data-sequence-stack={side}
        data-sequence-stack-count={count}
        data-sequence-stack-top={item.artifactId}
        data-sequence-stack-drop={dropping ? "true" : undefined}
        data-sequence-slot={slot}
        aria-label={ariaLabel}
        title="Click to step one card, Shift-click to step a page"
        {...styled(
          {
            left: baseLeft,
            width: cardWidth,
            height: cardHeight,
            transform,
            zIndex: folding
              ? visibleCount - slot
              : coveringSlot === slot
                ? 4
                : 2,
          },
          s.slot,
          s.stack,
          glides(key) && s.slotGlide,
        )}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={onStackClick}
        onKeyDown={onStackKeyDown}
      >
        <div
          data-card-header="true"
          {...styled(headerBoxWithOpacity(stackHeaderOpacity), m.header)}
        >
          <span
            data-card-title="rest"
            title={surface.typeLabel}
            {...stylex.props(m.title, m.titleFixed)}
          >
            {surface.typeLabel}
          </span>
          <span
            data-card-meta="true"
            title={`${count} items (${rangeLabel})`}
            {...stylex.props(s.headerMeta)}
          >
            <span {...stylex.props(m.ellipsis)}>{rangeLabel}</span>
          </span>
        </div>
        {/* Its backs wait at the slot until the card lands on them, so
            they never sweep sideways across the row. */}
        {hideStackBacks ? null : (
          <ArtifactStackBacks
            card={card}
            corners={corners}
            punched={false}
            peeks={peeks}
            backs={Math.min(2, count - 1)}
            stackStyle={stackStyle}
            depthOffset={liftDepth}
            depthScale={stackDepthScale}
          />
        )}
        <article
          data-plate-shadow={stackShadow ? "rest" : "none"}
          {...styled(
            depthPlateBox(liftDepth),
            ...plateLook(false, stackShadow),
            dropping && s.stackDrop,
          )}
        >
          {renderPicture(item)}
          {renderDepthVeil(liftDepth)}
        </article>
      </div>
    );
  };

  const renderOpenCard = (slot: number, index: number) => {
    const item = items[index];
    if (!item) return null;
    const lifted = drag?.from === index ? drag : null;
    const active = activeIndex === index || lifted !== null;
    const showMenu =
      (hoveredIndex === index ||
        activeIndex === index ||
        menuIndex === index) &&
      !lifted &&
      !closing;
    const baseLeft = slotLeft(slot);
    const key = `${item.artifactId}:${index}`;
    let translateX = 0;
    let translateY = 0;
    let visualSlot = slot;
    if (lifted) {
      translateX = lifted.pos.x - baseLeft;
      translateY = lifted.pos.y;
      if (lifted.mode === "reorder") visualSlot = lifted.targetSlot;
    } else if (drag) {
      visualSlot = visualSlotForSibling(
        slot,
        drag.from,
        drag.mode,
        drag.targetSlot,
        windowStart,
        visibleCount,
      );
      const settledX = drag.siblingX.get(index) ?? motionX.get(key);
      if (settledX !== undefined) {
        translateX = settledX - baseLeft;
      }
    } else {
      const animatedX = motionX.get(key);
      if (animatedX !== undefined) {
        translateX = animatedX - baseLeft;
      }
      translateX += externalShiftForSlot(slot);
    }
    const transform =
      translateX !== 0 || translateY !== 0
        ? `translate3d(${translateX}px, ${translateY}px, 0)`
        : undefined;

    const reveal = underCard?.reveal ?? null;
    const isUncoveredEdge =
      reveal !== null &&
      ((reveal.side === "left" && slot === 0) ||
        (reveal.side === "right" && slot === visibleCount - 1));
    const liftDepth =
      isUncoveredEdge && reveal !== null
        ? (1 - stepProgress) * reveal.shift
        : 0;
    const currentX = baseLeft + translateX;
    const openHeaderOpacity = lifted ? 1 : tuckedHeaderOpacity(slot, currentX);
    const openShadow = lifted
      ? true
      : tuckedPlateShadow(slot, currentX, liftDepth);

    return (
      <div
        key={key}
        role="listitem"
        tabIndex={0}
        data-sequence-item={index}
        data-sequence-slot={slot}
        data-sequence-visual-slot={visualSlot}
        data-sequence-target-slot={
          lifted?.mode === "reorder" ? lifted.targetSlot : undefined
        }
        data-artifact-id={item.artifactId}
        data-sequence-lifted={lifted ? "true" : undefined}
        aria-label={`Item ${index + 1} of ${items.length}: ${item.label}`}
        {...styled(
          {
            left: baseLeft,
            width: cardWidth,
            height: cardHeight,
            transform,
            zIndex: lifted
              ? 10
              : folding
                ? visibleCount - slot
                : coveringSlot === slot
                  ? 4
                  : isUncoveredEdge
                    ? 2
                    : 3,
          },
          s.slot,
          glides(key) && s.slotGlide,
          editable && (lifted ? s.grabbing : s.grab),
          lifted?.mode === "extract" && s.slotPulling,
        )}
        onPointerEnter={() => setHoveredIndex(index)}
        onPointerLeave={() =>
          setHoveredIndex((current) => (current === index ? null : current))
        }
        onFocus={() => setActiveIndex(index)}
        onPointerDown={onItemPointerDown}
      >
        <div
          data-card-header="true"
          {...styled(headerBoxWithOpacity(openHeaderOpacity), m.header)}
        >
          <span
            data-card-title={active ? "selected" : "rest"}
            title={surface.typeLabel}
            {...stylex.props(m.title, m.titleFixed, active && m.titleSelected)}
          >
            {surface.typeLabel}
          </span>
          <span
            data-card-meta="true"
            title={item.label}
            {...stylex.props(s.headerMeta)}
          >
            <span {...stylex.props(m.ellipsis)}>{item.label}</span>
          </span>
          {showMenu ? (
            <span
              data-card-header-actions="true"
              {...stylex.props(m.headerActions)}
            >
              <span data-card-menu-slot="true" {...stylex.props(m.menuSlot)}>
                <span
                  data-card-menu="true"
                  onPointerDown={stopCardDrag}
                  {...stylex.props(m.menuReveal)}
                >
                  <CellCardMenu
                    title={item.label}
                    detail={surface.typeLabel}
                    items={menuItemsFor(index)}
                    open={menuIndex === index}
                    onOpenChange={(open) =>
                      setMenuIndex((current) =>
                        open ? index : current === index ? null : current,
                      )
                    }
                  />
                </span>
              </span>
            </span>
          ) : null}
        </div>
        {folding && slot === 0 && windowStart === 0 && items.length > 1 ? (
          <ArtifactStackBacks
            card={card}
            corners={corners}
            punched={false}
            peeks={[items[1]?.imageUrl ?? "", items[2]?.imageUrl ?? ""]}
            backs={Math.min(STACK_BACK_COUNT, items.length - 1)}
            stackStyle={stackStyle}
            depthScale={foldProgress}
          />
        ) : null}
        <article
          data-plate-shadow={openShadow ? "rest" : "none"}
          {...styled(
            depthPlateBox(liftDepth),
            ...plateLook(active, openShadow),
            lifted && s.liftedPlate,
          )}
        >
          {renderPicture(item)}
          {renderDepthVeil(liftDepth)}
        </article>
      </div>
    );
  };

  const renderResizeTuck = (tuck: ResizeTuck) => {
    const rawX = motionX.get(tuck.key);
    if (rawX === undefined) return null;
    const minX = (visibleCount - 1) * cardWidth;
    const x = Math.max(minX, rawX);
    const dist = x - minX;
    const tuckHeaderOpacity = clamp(
      (dist - cardWidth * 0.2) / (cardWidth * 0.5),
      0,
      1,
    );
    return (
      <div
        key={tuck.key}
        aria-hidden="true"
        data-sequence-resize-tuck={tuck.item.artifactId}
        {...styled(
          {
            left: 0,
            width: cardWidth,
            height: cardHeight,
            transform: `translate3d(${x}px, 0px, 0)`,
            zIndex: 1,
            pointerEvents: "none",
          },
          s.slot,
          s.resizeTuck,
        )}
      >
        <div
          data-card-header="true"
          {...styled(headerBoxWithOpacity(tuckHeaderOpacity), m.header)}
        >
          <span data-card-title="rest" {...stylex.props(m.title, m.titleFixed)}>
            {surface.typeLabel}
          </span>
          <span data-card-meta="true" {...stylex.props(s.headerMeta)}>
            <span {...stylex.props(m.ellipsis)}>{tuck.item.label}</span>
          </span>
        </div>
        <article
          data-plate-shadow="none"
          {...styled(plateBox, ...plateLook(false, false))}
        >
          {renderPicture(tuck.item)}
        </article>
      </div>
    );
  };

  const renderStepTuck = (tuck: StepTuck) => {
    const x = motionX.get(tuck.key);
    if (x === undefined) return null;
    const dist = Math.abs(x - tuck.targetX);
    const tuckHeaderOpacity = clamp(
      (dist - cardWidth * 0.2) / (cardWidth * 0.5),
      0,
      1,
    );
    return (
      <div
        key={tuck.key}
        aria-hidden="true"
        data-sequence-step-tuck={tuck.item.artifactId}
        {...styled(
          {
            left: 0,
            width: cardWidth,
            height: cardHeight,
            transform: `translate3d(${x}px, 0px, 0)`,
            zIndex: 2,
            pointerEvents: "none",
          },
          s.slot,
          s.resizeTuck,
        )}
      >
        <div
          data-card-header="true"
          {...styled(headerBoxWithOpacity(tuckHeaderOpacity), m.header)}
        >
          <span data-card-title="rest" {...stylex.props(m.title, m.titleFixed)}>
            {surface.typeLabel}
          </span>
          <span data-card-meta="true" {...stylex.props(s.headerMeta)}>
            <span {...stylex.props(m.ellipsis)}>{tuck.item.label}</span>
          </span>
        </div>
        <article
          data-plate-shadow="none"
          {...styled(plateBox, ...plateLook(false, false))}
        >
          {renderPicture(tuck.item)}
        </article>
      </div>
    );
  };

  const renderedSlots: React.ReactNode[] = [];
  if (!closing && !drag) {
    for (const tuck of resizeTucks) renderedSlots.push(renderResizeTuck(tuck));
  }
  if (!folding && !drag) {
    for (const tuck of stepTucks) renderedSlots.push(renderStepTuck(tuck));
  }
  if (underCard) renderedSlots.push(renderUnderCard(underCard));
  for (let slot = 0; slot < visibleCount; slot += 1) {
    const index = windowStart + slot;
    if (hasLeftStack && slot === 0) {
      renderedSlots.push(renderStackSlot(slot, index, "left"));
    } else if (hasRightStack && slot === visibleCount - 1) {
      renderedSlots.push(renderStackSlot(slot, index, "right"));
    } else if (drag?.from !== index) {
      renderedSlots.push(renderOpenCard(slot, index));
    }
  }
  if (drag) renderedSlots.push(renderOpenCard(drag.slot, drag.from));

  const moveTransform =
    moveView && (moveView.offset.x !== 0 || moveView.offset.y !== 0)
      ? `translate3d(${moveView.offset.x}px, ${moveView.offset.y}px, 0)`
      : undefined;

  return (
    <div
      ref={rootRef}
      data-cell-canvas-chrome="true"
      data-artifact-sequence-spread={card.id}
      data-sequence-windowed={layout.windowed ? "true" : "false"}
      data-sequence-visible-count={visibleCount}
      role="list"
      aria-label={`${surface.typeLabel} sequence, ${items.length} items`}
      tabIndex={-1}
      {...styled(
        { left: originX, top: originY, width: frameWidth, height: cardHeight },
        s.root,
      )}
      onPointerDown={(event) => event.stopPropagation()}
      onKeyDown={onKeyDown}
    >
      {moveView ? (
        <span
          aria-hidden="true"
          data-sequence-move-ghost={`${card.col + moveView.landingDelta.col},${card.row + moveView.landingDelta.row}`}
          {...styled(
            {
              left: moveView.landingDelta.col * CELL_SIZE - FRAME_OUTSET,
              top: moveView.landingDelta.row * CELL_SIZE - FRAME_OUTSET,
              width: frameWidth + FRAME_OUTSET * 2,
              height: cardHeight + FRAME_OUTSET * 2,
            },
            s.moveGhost,
          )}
        />
      ) : null}
      <div {...styled({ transform: moveTransform }, s.content)}>
        <span
          aria-hidden="true"
          data-sequence-frame="true"
          {...styled(
            {
              left: -FRAME_OUTSET,
              top: -FRAME_OUTSET,
              width: frameWidth + FRAME_OUTSET * 2,
              height: cardHeight + FRAME_OUTSET * 2,
            },
            s.frame,
            folding && s.fadingOut,
          )}
        />
        <div
          {...styled(
            { left: frameWidth / 2, top: -FRAME_OUTSET },
            s.topControls,
            closing && s.fadingOut,
          )}
        >
          {onMove ? (
            <div
              role="button"
              tabIndex={0}
              aria-label="Move spread sequence"
              title="Drag to move sequence"
              data-sequence-move="true"
              data-sequence-moving={moveView ? "true" : undefined}
              {...stylex.props(
                s.handlePill,
                s.moveHandle,
                moveView !== null && s.handlePillActive,
                moveView !== null && s.moveHandleDragging,
              )}
              onPointerDown={onMovePointerDown}
            >
              <GripHorizontal size={12} aria-hidden="true" />
            </div>
          ) : null}
          <button
            type="button"
            data-sequence-collapse="true"
            aria-label="Collapse sequence"
            title="Collapse back into stack (Esc)"
            {...stylex.props(s.handlePill, s.collapseButton)}
            onPointerDown={(event) => event.stopPropagation()}
            onClick={(event) => {
              event.stopPropagation();
              requestClose();
            }}
          >
            <Layers size={11} aria-hidden="true" />
            Stack
          </button>
        </div>
        {renderedSlots}
        {externalInsertSlot !== null && !closing ? (
          <span
            aria-hidden="true"
            data-sequence-external-insert={externalInsertSlot}
            {...styled(
              {
                left: externalBarLeft(externalInsertSlot),
                top: CARD_PLATE_TOP,
                height: plateHeight,
              },
              s.externalInsertBar,
            )}
          />
        ) : null}
        {drag?.mode === "extract" && drag.landing ? (
          <span
            aria-hidden="true"
            data-sequence-landing={`${drag.landing.col},${drag.landing.row}`}
            {...styled(
              {
                left: (drag.landing.col - layout.startCol) * CELL_SIZE,
                top: (drag.landing.row - layout.row) * CELL_SIZE,
                width: cardWidth,
                height: cardHeight,
              },
              s.landing,
            )}
          />
        ) : null}
        {layout.windowed ? (
          <div
            data-sequence-pager="true"
            {...styled(
              { left: frameWidth / 2, top: cardHeight + FRAME_OUTSET + 6 },
              s.pager,
              closing && s.fadingOut,
            )}
          >
            <IconButton
              size="2xs"
              variant="ghost"
              label="Previous item"
              data-sequence-step="-1"
              disabled={windowStart === 0}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() => step(-1)}
            >
              <ChevronLeft size={12} />
            </IconButton>
            <span data-sequence-range="true">
              {windowStart + 1}–{windowStart + visibleCount} / {items.length}
            </span>
            <IconButton
              size="2xs"
              variant="ghost"
              label="Next item"
              data-sequence-step="1"
              disabled={windowStart >= maxStart}
              onPointerDown={(event) => event.stopPropagation()}
              onClick={() => step(1)}
            >
              <ChevronRight size={12} />
            </IconButton>
          </div>
        ) : null}
        {onPreferredVisibleCountChange &&
        layout.maxVisibleCount > layout.minVisibleCount ? (
          <div
            role="separator"
            tabIndex={0}
            aria-orientation="vertical"
            aria-label="Resize open cards"
            aria-valuemin={layout.minVisibleCount}
            aria-valuemax={layout.maxVisibleCount}
            aria-valuenow={visibleCount}
            title="Drag to widen or narrow spread"
            data-sequence-resize="true"
            data-sequence-resizing={resizing ? "true" : undefined}
            {...styled(
              {
                left: frameWidth + FRAME_OUTSET,
                top: CARD_PLATE_TOP + plateHeight / 2,
              },
              s.handlePill,
              s.resizeHandle,
              resizing && s.handlePillActive,
              // It sits on the right edge, where an end insertion bar draws.
              (closing || externalInsertSlot !== null) && s.fadingOut,
            )}
            onPointerDown={onResizePointerDown}
            onPointerMove={onResizePointerMove}
            onPointerUp={endResize}
            onPointerCancel={endResize}
          >
            <GripVertical size={12} aria-hidden="true" />
          </div>
        ) : null}
      </div>
    </div>
  );
}
