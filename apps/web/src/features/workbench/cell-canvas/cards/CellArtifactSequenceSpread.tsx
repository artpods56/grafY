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
import { useEffectReducer } from "@/lib/state/use-effect-reducer";
import { tokens } from "@/lib/stylex/tokens.stylex";

import type { OpenSequenceSpreadLayout } from "../cell-artifact-stacking";
import type {
  ArtifactCardSurfaceData,
  ArtifactStackItem,
} from "../cell-contracts";
import { cardPlateFill, cellCornerRadius } from "../cell-glass-stage";
import type {
  CellCorners,
  CellGlassMaterial,
  CellStackStyle,
} from "../cell-glass-stage";
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
import { shouldAnimateMotion } from "../cell-transitions";
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
import {
  createInitialSequenceSpreadState,
  displayedWindowStart,
  dragViewFromPhase,
  foldBackSyncFromPhase,
  FRAME_OUTSET,
  isClosingPhase,
  isFoldingPhase,
  isResizingPhase,
  motionXFromPhase,
  moveViewFromPhase,
  reorderDropIndex,
  resizeBackSyncFromState,
  resizeTucksFromPhase,
  sequenceSpreadReducer,
  STACK_HOVER_STEP_MS,
  stepTucksFromPhase,
  underCardFromState,
  visualSlotForSibling,
  type ResizeTuck,
  type SequenceSpreadAction,
  type SequenceSpreadEffect,
  type SpreadHitScene,
  type StepTuck,
  type UnderCard,
} from "./sequence-spread-reducer";

export { STACK_HOVER_STEP_MS, reorderDropIndex, visualSlotForSibling };

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

/** How the frame, pager and handles follow a resize of the open row. */
const RESIZE_GLIDE_MS = 220;
const RESIZE_GLIDE_EASE = "cubic-bezier(0.22, 1, 0.36, 1)";
/** How far open cards part around an external card's insertion gap. */
const EXTERNAL_GAP_SHIFT = 8;
/** How far every card slides off an edge gap, so the bar clears the frame. */
const EXTERNAL_EDGE_SHIFT = 10;

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

function fallbackItems(count: number): ArtifactStackItem[] {
  return Array.from({ length: count }, (_, index) => ({
    artifactId: `item-${index}`,
    label: `Item ${index + 1}`,
  }));
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

interface SpreadLive {
  screenToWorld: (clientX: number, clientY: number) => WorldPoint;
  cardWidth: number;
  cardHeight: number;
  windowed: boolean;
  originX: number;
  originY: number;
  frameWidth: number;
  layoutStartCol: number;
  layoutRow: number;
  layoutTotalCols: number;
  card: CellCardModel;
  foregroundCards: readonly CellCardModel[];
  canExtract: boolean;
  cardId: string;
  onClose: () => void;
  onWindowStartChange?: (windowStart: number) => void;
  onPreferredVisibleCountChange?: (count: number) => void;
  onReorder?: (cardId: string, fromIndex: number, toIndex: number) => void;
  onExtract?: (cardId: string, index: number, targetCell: CellCoord) => void;
  onMove?: (cardId: string, col: number, row: number) => void;
}

function hitScene(live: SpreadLive): SpreadHitScene {
  return {
    originX: live.originX,
    originY: live.originY,
    frameWidth: live.frameWidth,
    cardWidth: live.cardWidth,
    cardHeight: live.cardHeight,
    windowed: live.windowed,
    layoutStartCol: live.layoutStartCol,
    layoutRow: live.layoutRow,
    layoutTotalCols: live.layoutTotalCols,
    card: live.card,
    foregroundCards: live.foregroundCards,
    canExtract: live.canExtract,
  };
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
  const itemList = React.useMemo(
    () => surface.stackItems ?? fallbackItems(surface.itemCount ?? 0),
    [surface.itemCount, surface.stackItems],
  );
  const cardWidth = card.widthCells * CELL_SIZE;
  const cardHeight = card.heightCells * CELL_SIZE;
  const plateHeight = cardHeight - CARD_PLATE_TOP - CARD_PLATE_BOTTOM_INSET;
  const frameWidth = layout.totalCols * CELL_SIZE;
  const originX = layout.startCol * CELL_SIZE;
  const originY = layout.row * CELL_SIZE;

  const rootRef = React.useRef<HTMLDivElement | null>(null);
  const liveRef = React.useRef<SpreadLive | null>(null);
  const previousWindowedRef = React.useRef(layout.windowed);
  const motionFrameRef = React.useRef(0);
  const dragFrameRef = React.useRef(0);
  const moveFrameRef = React.useRef(0);
  const hoverTimerRef = React.useRef<ReturnType<typeof setTimeout> | null>(
    null,
  );

  const runEffect = React.useCallback(
    (
      effect: SequenceSpreadEffect,
      dispatchAction: React.Dispatch<SequenceSpreadAction>,
    ) => {
      switch (effect.kind) {
        case "scheduleMotionFrame": {
          if (motionFrameRef.current !== 0) return;
          motionFrameRef.current = requestAnimationFrame(() => {
            motionFrameRef.current = 0;
            dispatchAction({ kind: "motionTick", nowMs: performance.now() });
          });
          return;
        }
        case "cancelMotionFrame": {
          if (motionFrameRef.current !== 0) {
            cancelAnimationFrame(motionFrameRef.current);
            motionFrameRef.current = 0;
          }
          return;
        }
        case "scheduleDragFrame": {
          if (dragFrameRef.current !== 0) return;
          dragFrameRef.current = requestAnimationFrame(() => {
            dragFrameRef.current = 0;
            dispatchAction({ kind: "dragTick", nowMs: performance.now() });
          });
          return;
        }
        case "cancelDragFrame": {
          if (dragFrameRef.current !== 0) {
            cancelAnimationFrame(dragFrameRef.current);
            dragFrameRef.current = 0;
          }
          return;
        }
        case "scheduleMoveFrame": {
          if (moveFrameRef.current !== 0) return;
          moveFrameRef.current = requestAnimationFrame(() => {
            moveFrameRef.current = 0;
            dispatchAction({ kind: "moveTick", nowMs: performance.now() });
          });
          return;
        }
        case "cancelMoveFrame": {
          if (moveFrameRef.current !== 0) {
            cancelAnimationFrame(moveFrameRef.current);
            moveFrameRef.current = 0;
          }
          return;
        }
        case "armHoverStepTimer": {
          if (hoverTimerRef.current !== null) {
            clearTimeout(hoverTimerRef.current);
          }
          hoverTimerRef.current = setTimeout(() => {
            hoverTimerRef.current = null;
            const live = liveRef.current;
            if (!live) return;
            dispatchAction({
              kind: "hoverStackTimerFired",
              nowMs: performance.now(),
              animateMotion: shouldAnimateMotion(),
              cardWidth: live.cardWidth,
              windowed: live.windowed,
            });
          }, STACK_HOVER_STEP_MS);
          return;
        }
        case "clearHoverStepTimer": {
          if (hoverTimerRef.current !== null) {
            clearTimeout(hoverTimerRef.current);
            hoverTimerRef.current = null;
          }
          return;
        }
        case "notifyWindowStartChange":
          liveRef.current?.onWindowStartChange?.(effect.windowStart);
          return;
        case "notifyPreferredVisibleCountChange":
          liveRef.current?.onPreferredVisibleCountChange?.(effect.count);
          return;
        case "notifyClose":
          liveRef.current?.onClose();
          return;
        case "notifyReorder":
          liveRef.current?.onReorder?.(
            effect.cardId,
            effect.fromIndex,
            effect.toIndex,
          );
          return;
        case "notifyExtract":
          liveRef.current?.onExtract?.(
            effect.cardId,
            effect.index,
            effect.targetCell,
          );
          return;
        case "notifyMove":
          liveRef.current?.onMove?.(effect.cardId, effect.col, effect.row);
          return;
        default: {
          const exhaustive: never = effect;
          return exhaustive;
        }
      }
    },
    [],
  );

  const [state, dispatch] = useEffectReducer(
    sequenceSpreadReducer,
    () =>
      createInitialSequenceSpreadState({
        items: itemList,
        layout,
        animateMotion: shouldAnimateMotion(),
      }),
    runEffect,
  );

  const items = state.items;
  const visibleCount = state.visibleCount;
  const windowStart = displayedWindowStart(
    state.windowStart,
    layout.windowed,
    items.length,
    visibleCount,
  );
  const maxStart = Math.max(0, items.length - visibleCount);
  const hasLeftStack = layout.windowed && windowStart > 0;
  const hasRightStack = layout.windowed && windowStart < maxStart;
  const leftCount = hasLeftStack ? windowStart + 1 : 0;
  const rightCount = hasRightStack
    ? items.length - (windowStart + visibleCount - 1)
    : 0;
  const drag = dragViewFromPhase(state.phase);
  const moveView = moveViewFromPhase(state.phase);
  const resizing = isResizingPhase(state.phase);
  const closing = isClosingPhase(state.phase);
  const folding = isFoldingPhase(state.phase);
  const activeIndex = state.activeIndex;
  const hoveredIndex = state.hoveredIndex;
  const menuIndex = state.menuIndex;
  const editable = Boolean(onReorder || onExtract);
  const underCardState = underCardFromState(state);
  const stepTucks = stepTucksFromPhase(state.phase);
  const resizeTucks = resizeTucksFromPhase(state.phase);
  const resizeBackSyncState = resizeBackSyncFromState(state);
  const foldBackSync = foldBackSyncFromPhase(state.phase);
  const motionX = motionXFromPhase(state.phase);

  React.useLayoutEffect(() => {
    liveRef.current = {
      screenToWorld,
      cardWidth,
      cardHeight,
      windowed: layout.windowed,
      originX,
      originY,
      frameWidth,
      layoutStartCol: layout.startCol,
      layoutRow: layout.row,
      layoutTotalCols: layout.totalCols,
      card,
      foregroundCards,
      canExtract: Boolean(onExtract),
      cardId: card.id,
      onClose,
      onWindowStartChange,
      onPreferredVisibleCountChange,
      onReorder,
      onExtract,
      onMove,
    };
  });

  React.useEffect(() => {
    const previousWindowed = previousWindowedRef.current;
    dispatch({
      kind: "syncProps",
      items: itemList,
      windowed: layout.windowed,
      previousWindowed,
      layoutVisibleCount: layout.visibleCount,
    });
    previousWindowedRef.current = layout.windowed;
  }, [dispatch, itemList, layout.visibleCount, layout.windowed]);

  React.useEffect(() => {
    const live = liveRef.current;
    if (!live) return;
    dispatch({
      kind: "mounted",
      nowMs: performance.now(),
      animateMotion: shouldAnimateMotion(),
      cardWidth: live.cardWidth,
      windowed: live.windowed,
    });
  }, [dispatch]);

  React.useEffect(() => {
    const element = rootRef.current;
    if (!element || !layout.windowed) return;
    const onWheel = (event: WheelEvent) => {
      if (Math.abs(event.deltaX) <= Math.abs(event.deltaY)) return;
      event.preventDefault();
      event.stopPropagation();
      const live = liveRef.current;
      if (!live) return;
      dispatch({
        kind: "wheel",
        deltaX: event.deltaX,
        nowMs: performance.now(),
        animateMotion: shouldAnimateMotion(),
        cardWidth: live.cardWidth,
        windowed: live.windowed,
      });
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [dispatch, layout.windowed]);

  React.useEffect(() => {
    const onPointerMove = (event: PointerEvent) => {
      const live = liveRef.current;
      if (!live) return;
      const world = live.screenToWorld(event.clientX, event.clientY);
      const nowMs = performance.now();
      const scene = hitScene(live);
      const animateMotion = shouldAnimateMotion();
      dispatch({
        kind: "itemPointerMove",
        pointerId: event.pointerId,
        clientX: event.clientX,
        clientY: event.clientY,
        world,
        scene,
        nowMs,
        animateMotion,
        cardWidth: live.cardWidth,
        windowed: live.windowed,
      });
      dispatch({
        kind: "movePointerMove",
        pointerId: event.pointerId,
        clientX: event.clientX,
        clientY: event.clientY,
        world,
        scene,
        nowMs,
        animateMotion,
      });
    };
    const onPointerEnd = (event: PointerEvent) => {
      const live = liveRef.current;
      if (!live) return;
      const world = live.screenToWorld(event.clientX, event.clientY);
      const scene = hitScene(live);
      const cancelled = event.type === "pointercancel";
      dispatch({
        kind: "itemPointerEnd",
        pointerId: event.pointerId,
        clientX: event.clientX,
        clientY: event.clientY,
        world,
        cancelled,
        cardId: live.cardId,
        scene,
      });
      dispatch({
        kind: "movePointerEnd",
        pointerId: event.pointerId,
        world,
        cancelled,
        cardId: live.cardId,
        scene,
      });
    };
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerEnd);
    window.addEventListener("pointercancel", onPointerEnd);
    return () => {
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", onPointerEnd);
      window.removeEventListener("pointercancel", onPointerEnd);
    };
  }, [dispatch]);

  React.useEffect(
    () => () => {
      if (motionFrameRef.current !== 0) {
        cancelAnimationFrame(motionFrameRef.current);
      }
      if (dragFrameRef.current !== 0) {
        cancelAnimationFrame(dragFrameRef.current);
      }
      if (moveFrameRef.current !== 0) {
        cancelAnimationFrame(moveFrameRef.current);
      }
      if (hoverTimerRef.current !== null) {
        clearTimeout(hoverTimerRef.current);
      }
    },
    [],
  );

  const clock = () => ({
    nowMs: performance.now(),
    animateMotion: shouldAnimateMotion(),
    cardWidth,
    windowed: layout.windowed,
  });
  const step = (by: number) => {
    dispatch({ kind: "step", by, ...clock() });
  };
  const requestClose = () => {
    dispatch({ kind: "requestClose", ...clock() });
  };
  const stepBy = (direction: number, page: boolean) => {
    const pageStep = Math.max(1, visibleCount - 2);
    step(direction * (page ? pageStep : 1));
  };
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
      dispatch({
        kind: "keyboardReorder",
        direction,
        cardId: card.id,
        canReorder: true,
      });
      return;
    }
    if (!layout.windowed) return;
    event.preventDefault();
    event.stopPropagation();
    stepBy(direction, event.shiftKey);
  };
  const setActiveIndex = (next: React.SetStateAction<number | null>) => {
    const index = typeof next === "function" ? next(activeIndex) : next;
    dispatch({ kind: "setActiveIndex", index });
  };
  const setHoveredIndex = (next: React.SetStateAction<number | null>) => {
    const index = typeof next === "function" ? next(hoveredIndex) : next;
    dispatch({ kind: "setHoveredIndex", index });
  };
  const setMenuIndex = (next: React.SetStateAction<number | null>) => {
    const index = typeof next === "function" ? next(menuIndex) : next;
    dispatch({ kind: "setMenuIndex", index });
  };
  const onItemPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.stopPropagation();
    const index = Number(event.currentTarget.dataset.sequenceItem);
    const slot = Number(event.currentTarget.dataset.sequenceSlot);
    dispatch({
      kind: "itemPointerDown",
      pointerId: event.pointerId,
      button: event.button,
      index,
      slot,
      clientX: event.clientX,
      clientY: event.clientY,
      world: screenToWorld(event.clientX, event.clientY),
      editable,
      originX,
      originY,
      cardWidth,
    });
  };
  const onMovePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.stopPropagation();
    if (!onMove) return;
    dispatch({
      kind: "movePointerDown",
      pointerId: event.pointerId,
      button: event.button,
      clientX: event.clientX,
      clientY: event.clientY,
      world: screenToWorld(event.clientX, event.clientY),
    });
  };
  const onResizePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.stopPropagation();
    if (event.button !== 0 || closing) return;
    if (
      state.phase.kind === "draggingItem" ||
      state.phase.kind === "movingSpread"
    ) {
      return;
    }
    dispatch({
      kind: "resizePointerDown",
      pointerId: event.pointerId,
      button: event.button,
      startX: screenToWorld(event.clientX, event.clientY).x,
    });
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };
  const onResizePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    dispatch({
      kind: "resizePointerMove",
      pointerId: event.pointerId,
      worldX: screenToWorld(event.clientX, event.clientY).x,
      nowMs: performance.now(),
      animateMotion: shouldAnimateMotion(),
      cardWidth,
      minVisibleCount: layout.minVisibleCount,
      maxVisibleCount: layout.maxVisibleCount,
    });
  };
  const endResize = (event: React.PointerEvent<HTMLDivElement>) => {
    const captured =
      state.phase.kind === "resizing" &&
      state.phase.pointer?.pointerId === event.pointerId;
    dispatch({ kind: "resizePointerEnd", pointerId: event.pointerId });
    if (captured) event.currentTarget.releasePointerCapture?.(event.pointerId);
  };
  const slotLeft = (slot: number) => slot * cardWidth;

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
