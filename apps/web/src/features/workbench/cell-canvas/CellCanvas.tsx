"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ChevronDown } from "lucide-react";

import { IconButton } from "@/components/ui/button";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { useEffectReducer } from "@/lib/state/use-effect-reducer";

import { CellCanvasProvider, CellViewportLayer } from "./CellCanvasContext";
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
  computeSequenceSpreadLayout,
  findArtifactMergeSuggestions,
  type ArtifactMergeOrder,
  type ArtifactMergeSuggestion,
  type OpenSequenceSpreadLayout,
} from "./cell-artifact-stacking";
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
import {
  cellCanvasInteractionReducer,
  createInitialCellCanvasInteractionState,
  indexGraph,
  isUnderCardsFrame,
  portColor,
  previewPoints,
  resolvePortColor,
  restingScene,
  wellKey,
  type CellCanvasInteractionAction,
  type CellCanvasInteractionEffect,
  type CellCardMove,
  type CellConnectionEnds,
  type GraphIndex,
  type OpenSpreadSnapshot,
  type StackTuckJoin,
} from "./cell-canvas-interaction-reducer";
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
  ARTIFACT_CARD_OUTPUT_PORT_ID,
  CELL_SIZE,
  artifactCardOutputRow,
  cardWorldRect,
  cellToWorldOrigin,
  portAnchorCenter,
  portSide,
  type CellCardModel,
  type CellCoord,
  type CellGraph,
  type CellPort,
  type CellRoutingOptions,
  type CellRoutingResult,
  type WorldPoint,
  cellPortKey,
} from "./cell-model";
import { solvePipeAttachmentAnchors } from "./cell-pipe-attachments";
import { routeCellGraph } from "./cell-router";
import { createCellInteractionStore } from "./cell-store";
import { shouldAnimateMotion } from "./cell-transitions";
import { useCellViewport, type WorldBounds } from "./use-cell-viewport";
import { useRemoteCellDrag } from "./use-remote-cell-drag";

export type { CellCardMove, CellConnectionEnds };

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

export interface CellCanvasProps {
  graph: CellGraph;
  surfaceById: Readonly<Record<string, CellCardSurfaceData>>;
  /** A port to light in a render fixture, using the same key as a wiring target. */
  previewPortKey?: string | null;
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
  /** A field's new value: a primitive, or a whole object or list. */
  onOperatorConfigChange?: (
    cardId: string,
    fieldId: string,
    value: unknown,
  ) => void;
  /** Opens or closes one config section of a card. */
  onOperatorToggleConfigSection?: (
    cardId: string,
    sectionKey: string,
    open: boolean,
  ) => void;
  onOperatorApplySecret?: (
    cardId: string,
    name: string,
    value: string,
  ) => Promise<boolean>;
  onOperatorRemoveSecret?: (cardId: string, name: string) => Promise<boolean>;
  onOperatorAddPlug?: (cardId: string, portName: string) => void;
  onOperatorRemovePlug?: (
    cardId: string,
    portName: string,
    plugId: string,
  ) => void;
  onOperatorToggleAppendix?: (cardId: string) => void;
  /** Opens the engine picker for an empty required service input. */
  onPickServiceEngine?: (cardId: string, portName: string) => void;
  onAnnotationColorChange?: (
    cardId: string,
    color: AnnotationColorToken,
  ) => void;
  onArtifactInspect?: (cardId: string) => void;
  /**
   * Opens downstream discovery from an artifact card that has one output.
   * The point sits just to the right of that card.
   */
  onArtifactNextStep?: (cardId: string, world: WorldPoint) => void;
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

export { DEFAULT_CELL_GLASS_LOOK, DEFAULT_CELL_ROUTING };

const EMPTY_ID_SET: ReadonlySet<string> = new Set();
const EMPTY_PORT_IDS: ReadonlySet<string> = new Set();
const EMPTY_PIPES: readonly StagePipe[] = [];
const EMPTY_WELLS: readonly StageWell[] = [];
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

function setsEqual(a: ReadonlySet<string>, b: ReadonlySet<string>): boolean {
  if (a === b) return true;
  if (a.size !== b.size) return false;
  for (const item of a) {
    if (!b.has(item)) return false;
  }
  return true;
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

// ---------------------------------------------------------------------------

type GestureListeners = {
  move: (event: PointerEvent) => void;
  up: (event: PointerEvent) => void;
};

function detachGestureListeners(slot: {
  current: GestureListeners | null;
}): void {
  const listeners = slot.current;
  if (!listeners) return;
  window.removeEventListener("pointermove", listeners.move);
  window.removeEventListener("pointerup", listeners.up);
  window.removeEventListener("pointercancel", listeners.up);
  slot.current = null;
}

function cancelDragFrame(frameRef: { current: number }): void {
  if (frameRef.current === 0) return;
  cancelAnimationFrame(frameRef.current);
  frameRef.current = 0;
}

export function CellCanvas({
  graph,
  surfaceById,
  previewPortKey = null,
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
  onOperatorToggleConfigSection,
  onOperatorApplySecret,
  onOperatorRemoveSecret,
  onOperatorAddPlug,
  onOperatorRemovePlug,
  onOperatorToggleAppendix,
  onPickServiceEngine,
  onAnnotationColorChange,
  onArtifactInspect,
  onArtifactNextStep,
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
    panBy,
    flushPan,
    zoomAtCenter,
    zoomBy,
    fitRect,
    viewAt,
    screenToWorld,
    worldToScreen,
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
  /** Cards sliding under a stack they just joined, drawn until they land. */
  const [stackTucks, setStackTucks] = React.useState<readonly StackTuck[]>([]);
  const stackTuckSeqRef = React.useRef(0);
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

  const graphRef = React.useRef(graph);
  const surfaceByIdRef = React.useRef(surfaceById);
  const foregroundCardsRef = React.useRef<readonly CellCardModel[]>(
    graph.cards,
  );
  const indexRef = React.useRef<GraphIndex | null>(null);
  const dockingRef = React.useRef<ReturnType<
    typeof detectCellDockedJoins
  > | null>(null);
  const layoutRef = React.useRef<CellRoutingResult | null>(null);
  const routingRef = React.useRef(routing);
  const viewportRef = React.useRef(viewport);
  const rerouteRef = React.useRef(0);
  const draggedRef = React.useRef<string | null>(null);
  const editableRef = React.useRef(editable);
  const punchedRef = React.useRef(punched);
  const stackLookRef = React.useRef({
    stackStyle: look.stackStyle,
    corners: look.corners,
  });
  const lastDropEmptyRef = React.useRef<CellConnectDropEmptyEvent | null>(null);
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
  const openSpreadRef = React.useRef<OpenSpreadSnapshot | null>(null);
  const onViewportZoomChangeRef = React.useRef(onViewportZoomChange);
  const onStatsChangeRef = React.useRef(onStatsChange);
  const panByRef = React.useRef(panBy);
  const flushPanRef = React.useRef(flushPan);
  const dragProgressActiveRef = React.useRef(false);
  const screenToWorldRef = React.useRef(screenToWorld);
  const commitSelectionRef = React.useRef<
    (next: { cardIds?: Iterable<string>; pipeIds?: Iterable<string> }) => void
  >(() => {});
  const toggleCardSelectionRef = React.useRef<(cardId: string) => void>(
    () => {},
  );
  const clearSelectionRef = React.useRef<() => void>(() => {});
  const startStackTucksRef = React.useRef<
    (joins: readonly StackTuckJoin[]) => void
  >(() => {});
  const gestureListenersRef = React.useRef<GestureListeners | null>(null);
  const dragFrameRef = React.useRef(0);
  const mountedRef = React.useRef(true);

  const runEffect = React.useCallback(
    (
      effect: CellCanvasInteractionEffect,
      dispatchAction: React.Dispatch<CellCanvasInteractionAction>,
    ) => {
      switch (effect.kind) {
        case "attachWindowGesture": {
          detachGestureListeners(gestureListenersRef);
          const pointerId = effect.pointerId;
          const move = (event: PointerEvent) => {
            if (event.pointerId !== pointerId) return;
            const clientPoint = { x: event.clientX, y: event.clientY };
            if (effect.gesture === "pan") {
              dispatchAction({ kind: "panMove", pointerId, clientPoint });
              return;
            }
            const worldPoint = screenToWorldRef.current(
              event.clientX,
              event.clientY,
            );
            if (effect.gesture === "marquee") {
              const layout = layoutRef.current;
              if (!layout) return;
              dispatchAction({
                kind: "marqueeMove",
                pointerId,
                worldPoint,
                foregroundCards: foregroundCardsRef.current,
                routedPipes: layout.pipes,
              });
              return;
            }
            if (effect.gesture === "drag") {
              dispatchAction({
                kind: "dragMove",
                pointerId,
                clientPoint,
                worldPoint,
                now: performance.now(),
                openSpread: openSpreadRef.current,
              });
              return;
            }
            dispatchAction({
              kind: "connectMove",
              pointerId,
              cursor: worldPoint,
              cards: graphRef.current.cards,
              surfaces: surfaceByIdRef.current,
              punched: punchedRef.current,
              canConnect: onCanConnectRef.current,
            });
          };
          const up = (event: PointerEvent) => {
            if (event.pointerId !== pointerId) return;
            if (effect.gesture === "pan") {
              dispatchAction({ kind: "panEnd", pointerId });
              return;
            }
            if (effect.gesture === "marquee") {
              dispatchAction({ kind: "marqueeEnd", pointerId });
              return;
            }
            if (effect.gesture === "drag") {
              if (event.type === "pointercancel") {
                dispatchAction({ kind: "cancelGesture" });
                return;
              }
              dispatchAction({
                kind: "dragUp",
                pointerId,
                now: performance.now(),
              });
              return;
            }
            dispatchAction({
              kind: "connectEnd",
              pointerId,
              clientPoint: { x: event.clientX, y: event.clientY },
              isCancel: event.type === "pointercancel",
            });
          };
          gestureListenersRef.current = { move, up };
          window.addEventListener("pointermove", move);
          window.addEventListener("pointerup", up);
          window.addEventListener("pointercancel", up);
          return;
        }
        case "detachWindowGesture":
          detachGestureListeners(gestureListenersRef);
          flushPanRef.current(true);
          return;
        case "scheduleDragFrame": {
          if (dragFrameRef.current !== 0) return;
          dragFrameRef.current = requestAnimationFrame(() => {
            dragFrameRef.current = 0;
            if (!mountedRef.current) return;
            const index = indexRef.current;
            if (!index) return;
            dispatchAction({
              kind: "dragTick",
              now: performance.now(),
              index,
            });
          });
          return;
        }
        case "cancelDragFrame":
          cancelDragFrame(dragFrameRef);
          return;
        case "panViewportBy":
          panByRef.current(effect.dx, effect.dy);
          return;
        case "setStoreMarquee":
          store.setMarquee(effect.rect);
          return;
        case "commitSelection":
          commitSelectionRef.current(effect.selection);
          return;
        case "toggleCardSelection":
          toggleCardSelectionRef.current(effect.cardId);
          return;
        case "clearSelection":
          clearSelectionRef.current();
          return;
        case "invokePaneClick":
          onPaneClickRef.current?.();
          return;
        case "setStoreDraggingCards":
          store.setDraggingCards(effect.cardIds);
          return;
        case "notifyDragProgress":
          dragProgressActiveRef.current = effect.moves !== null;
          onDragCardsProgressRef.current?.(effect.moves);
          return;
        case "commitMoveCards":
          onMoveCardsRef.current?.(effect.moves);
          return;
        case "setMergeTarget":
        case "setSpreadInsertTarget":
          return;
        case "startStackTucks":
          startStackTucksRef.current(effect.joins);
          return;
        case "commitMergeArtifactCards":
          onMergeArtifactCardsRef.current?.(
            effect.cardId,
            effect.targetCardId,
            "target-first",
          );
          return;
        case "commitInsertArtifactCardIntoSequence":
          onInsertArtifactCardIntoSequenceRef.current?.(
            effect.cardId,
            effect.spreadCardId,
            effect.insertIndex,
          );
          return;
        case "setStoreResizingCard":
          store.setResizingCard(effect.cardId);
          return;
        case "commitResizeCard":
          onResizeCardRef.current?.(effect.commit);
          return;
        case "setStoreActivePortKey":
          store.setActivePortKey(effect.key);
          return;
        case "commitConnect":
          onConnectRef.current?.(effect.ends);
          return;
        case "notifyConnectDropEmpty":
          lastDropEmptyRef.current = effect.event;
          if (window.__cellCanvas) {
            window.__cellCanvas.lastConnectDropEmpty = effect.event;
          }
          onConnectDropEmptyRef.current?.(effect.event);
          return;
        default: {
          const exhaustive: never = effect;
          return exhaustive;
        }
      }
    },
    [store],
  );

  const [interaction, dispatch] = useEffectReducer(
    cellCanvasInteractionReducer,
    createInitialCellCanvasInteractionState,
    runEffect,
    { flush: "sync" },
  );

  const phase = interaction.phase;
  const resizePreview = phase.kind === "resizingCard" ? phase.preview : null;
  const movingCardIds =
    phase.kind === "draggingCards" && phase.movedBeyondClick
      ? phase.session.movingCardIds
      : EMPTY_ID_SET;
  const draggedCardId =
    phase.kind === "draggingCards" && phase.movedBeyondClick
      ? phase.anchorCardId
      : null;
  const dragFrame = interaction.dragFrame;
  const wiring = React.useMemo(
    () =>
      phase.kind === "connectingPipe"
        ? {
            fromCardId: phase.fromCardId,
            fromPort: phase.fromPort,
            cursor: phase.cursor,
            target: phase.target,
          }
        : null,
    [phase],
  );
  const mergeTarget =
    phase.kind === "draggingCards" && phase.mergeTargetId !== null
      ? { cardId: phase.mergeTargetId, itemCount: phase.mergeItemCount }
      : null;
  const spreadInsertTarget =
    phase.kind === "draggingCards" ? phase.spreadInsert : null;
  const rerouteCount = interaction.rerouteCount;
  const lastConnectDropEmpty = interaction.lastConnectDropEmpty;
  const panning = phase.kind === "panning";

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
    editableRef.current = editable;
    punchedRef.current = punched;
    stackLookRef.current = {
      stackStyle: look.stackStyle,
      corners: look.corners,
    };
    lastDropEmptyRef.current = lastConnectDropEmpty;
    panByRef.current = panBy;
    flushPanRef.current = flushPan;
    screenToWorldRef.current = screenToWorld;

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

  React.useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      detachGestureListeners(gestureListenersRef);
      flushPanRef.current(false);
      cancelDragFrame(dragFrameRef);
      if (dragProgressActiveRef.current) {
        dragProgressActiveRef.current = false;
        onDragCardsProgressRef.current?.(null);
      }
    };
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
      cancelGesture: () => dispatch({ kind: "cancelGesture" }),
    }),
    [
      dispatch,
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

  React.useLayoutEffect(() => {
    commitSelectionRef.current = commitSelection;
    toggleCardSelectionRef.current = toggleCardSelection;
    clearSelectionRef.current = clearSelection;
    startStackTucksRef.current = startStackTucks;
  });

  const onCardPointerDown = React.useCallback(
    (cardId: string, event: React.PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0) return;
      event.stopPropagation();
      const indexAtPickup = indexRef.current;
      const docking = dockingRef.current;
      const layout = layoutRef.current;
      if (!indexAtPickup || !docking || !layout) return;
      const selectedCardIds = store.getSelection().cardIds;
      dispatch({
        kind: "cardPointerDown",
        cardId,
        pointerId: event.pointerId,
        clientPoint: { x: event.clientX, y: event.clientY },
        worldPoint: screenToWorld(event.clientX, event.clientY),
        shiftKey: event.shiftKey,
        wasSelectedBefore: selectedCardIds.has(cardId),
        selectedCardIds,
        editable: editableRef.current,
        graph: graphRef.current,
        surfaces: surfaceByIdRef.current,
        index: indexAtPickup,
        routing: routingRef.current,
        docking: {
          dockedPipeIds: docking.dockedPipeIds,
          routablePipes: docking.routablePipes,
        },
        layout,
        punched: punchedRef.current,
        openSpread: openSpreadRef.current,
        canMergeArtifactCards: canMergeArtifactCardsRef.current ?? null,
        hasMergeCallback: onMergeArtifactCardsRef.current !== undefined,
        hasInsertCallback:
          onInsertArtifactCardIntoSequenceRef.current !== undefined,
      });
    },
    [dispatch, screenToWorld, store],
  );

  const onPortPointerDown = React.useCallback(
    (
      cardId: string,
      port: CellPort,
      event: React.PointerEvent<HTMLButtonElement>,
    ) => {
      if (event.button !== 0 || !editableRef.current) return;
      event.stopPropagation();
      dispatch({
        kind: "startConnect",
        pointerId: event.pointerId,
        fromCardId: cardId,
        fromPort: port,
        cursor: screenToWorld(event.clientX, event.clientY),
        cards: graphRef.current.cards,
        surfaces: surfaceByIdRef.current,
        punched: punchedRef.current,
        canConnect: onCanConnectRef.current,
      });
    },
    [dispatch, screenToWorld],
  );

  const onResizeStart = React.useCallback(
    (
      cardId: string,
      edge: CellResizeEdge,
      event: React.PointerEvent<HTMLDivElement>,
    ) => {
      if (!editableRef.current) return;
      const card = indexRef.current?.cardsById.get(cardId);
      if (!card) {
        dispatch({ kind: "cancelGesture" });
        return;
      }
      dispatch({
        kind: "startResize",
        card,
        edge,
        startWorld: screenToWorld(event.clientX, event.clientY),
        editable: true,
      });
    },
    [dispatch, screenToWorld],
  );

  const onResizeMove = React.useCallback(
    (
      cardId: string,
      edge: CellResizeEdge,
      event: React.PointerEvent<HTMLDivElement>,
    ) => {
      dispatch({
        kind: "resizeMove",
        cardId,
        edge,
        worldPoint: screenToWorld(event.clientX, event.clientY),
      });
    },
    [dispatch, screenToWorld],
  );

  const onResizeEnd = React.useCallback(
    (
      cardId: string,
      edge: CellResizeEdge,
      event: React.PointerEvent<HTMLDivElement>,
    ) => {
      if (event.type === "pointercancel") {
        dispatch({ kind: "cancelGesture" });
        return;
      }
      dispatch({
        kind: "resizeEnd",
        cardId,
        edge,
        worldPoint: screenToWorld(event.clientX, event.clientY),
      });
    },
    [dispatch, screenToWorld],
  );

  const onRootPointerDown = React.useCallback(
    (event: React.PointerEvent<HTMLDivElement>) => {
      if (event.button !== 0 && event.button !== 1) return;
      if (event.button === 1) event.preventDefault();
      if (event.shiftKey && event.button === 0) {
        event.preventDefault();
        event.stopPropagation();
        const layout = layoutRef.current;
        if (!layout) return;
        dispatch({
          kind: "startMarquee",
          pointerId: event.pointerId,
          worldPoint: screenToWorld(event.clientX, event.clientY),
          foregroundCards: foregroundCardsRef.current,
          routedPipes: layout.pipes,
        });
        return;
      }
      dispatch({
        kind: "startPan",
        pointerId: event.pointerId,
        clientPoint: { x: event.clientX, y: event.clientY },
      });
    },
    [dispatch, screenToWorld],
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
        dispatch({ kind: "cancelGesture" });
        if (expandedSequenceIdRef.current) {
          // The open spread closes first; the card stays held.
          setExpandedSequenceId(null);
          return;
        }
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
  }, [clearSelection, dispatch, store]);

  React.useEffect(() => {
    if (!exposeDebugApi) return;
    const api: CellCanvasDebugApi = {
      setViewAt: (wx, wy, zoom, sx, sy) => viewAt(wx, wy, zoom, sx, sy),
      getViewport: () => viewportRef.current,
      getStats: () => ({
        cards: graphRef.current.cards.length,
        pipes: graphRef.current.pipes.length,
        deepCount: layoutRef.current?.deepCount ?? 0,
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
    : previewPortKey;

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

    if (!surface) return null;

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
            onToggleConfigSection={onOperatorToggleConfigSection}
            onApplySecret={editable ? onOperatorApplySecret : undefined}
            onRemoveSecret={editable ? onOperatorRemoveSecret : undefined}
            onToggleAppendix={onOperatorToggleAppendix}
            onPickServiceEngine={editable ? onPickServiceEngine : undefined}
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
            onNextStep={
              editable &&
              onArtifactNextStep &&
              card.ports.filter((port) => port.direction === "output")
                .length === 1
                ? () =>
                    onArtifactNextStep(card.id, {
                      x: (card.col + card.widthCells) * CELL_SIZE + 48,
                      y: (card.row + card.heightCells / 2) * CELL_SIZE,
                    })
                : undefined
            }
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
