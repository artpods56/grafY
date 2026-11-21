"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { Surface } from "@/components/ui/surface";
import { tokens } from "@/lib/stylex/tokens.stylex";

import type {
  CellCardInteractionState,
  CellInteractionStore,
  CellPipeInteractionState,
  CellResizeEdge,
  CellViewportApi,
} from "./cell-contracts";
import type { StageViewport } from "./cell-glass-stage";

/**
 * What a card needs from the canvas around it, without React Flow: the
 * viewport, the interaction store each card subscribes to by id, and the
 * pieces React Flow used to draw for a node — a world-space portal layer, a
 * toolbar over the node and a resize handle.
 *
 * Every hook here works with no provider at all (a card rendered on its own in
 * a unit test or on the server), reading the resting default state.
 */

export interface CellCanvasContextValue {
  viewportApi: CellViewportApi | null;
  store: CellInteractionStore | null;
}

const CellCanvasContext = React.createContext<CellCanvasContextValue>({
  viewportApi: null,
  store: null,
});

export function CellCanvasProvider({
  viewportApi = null,
  store = null,
  children,
}: {
  viewportApi?: CellViewportApi | null;
  store?: CellInteractionStore | null;
  children: React.ReactNode;
}) {
  const value = React.useMemo(
    () => ({ viewportApi, store }),
    [viewportApi, store],
  );
  return (
    <CellCanvasContext.Provider value={value}>
      {children}
    </CellCanvasContext.Provider>
  );
}

export function useCellViewportApi(): CellViewportApi | null {
  return React.useContext(CellCanvasContext).viewportApi;
}

export function useCellInteractionStore(): CellInteractionStore | null {
  return React.useContext(CellCanvasContext).store;
}

export const DEFAULT_CARD_INTERACTION_STATE: CellCardInteractionState =
  Object.freeze({
    selected: false,
    hovered: false,
    dragging: false,
    resizing: false,
    remoteSelectedBy: Object.freeze([]),
    remoteDragCell: null,
    remoteDragColor: null,
  });

export const DEFAULT_PIPE_INTERACTION_STATE: CellPipeInteractionState =
  Object.freeze({ selected: false, hovered: false });

function NOOP_SUBSCRIBE(): () => void {
  return () => {};
}

const defaultCardState = () => DEFAULT_CARD_INTERACTION_STATE;
const defaultPipeState = () => DEFAULT_PIPE_INTERACTION_STATE;

/** One card's selection, hover, drag and remote-peer state; re-renders only that card. */
export function useCellCardState(cardId: string): CellCardInteractionState {
  const store = useCellInteractionStore();
  const subscribe = React.useCallback(
    (listener: () => void) =>
      store ? store.subscribeCard(cardId, listener) : NOOP_SUBSCRIBE(),
    [store, cardId],
  );
  const getSnapshot = React.useCallback(
    () => (store ? store.getCardState(cardId) : DEFAULT_CARD_INTERACTION_STATE),
    [store, cardId],
  );
  return React.useSyncExternalStore(subscribe, getSnapshot, defaultCardState);
}

/** One pipe's selection and hover state; re-renders only that pipe. */
export function useCellPipeState(pipeId: string): CellPipeInteractionState {
  const store = useCellInteractionStore();
  const subscribe = React.useCallback(
    (listener: () => void) =>
      store ? store.subscribePipe(pipeId, listener) : NOOP_SUBSCRIBE(),
    [store, pipeId],
  );
  const getSnapshot = React.useCallback(
    () => (store ? store.getPipeState(pipeId) : DEFAULT_PIPE_INTERACTION_STATE),
    [store, pipeId],
  );
  return React.useSyncExternalStore(subscribe, getSnapshot, defaultPipeState);
}

const s = stylex.create({
  // A 1px plane at the flow origin moved like the viewport, as the glass
  // stage's planes are: children are placed in world units inside it.
  layer: {
    position: "absolute",
    top: 0,
    left: 0,
    width: "1px",
    height: "1px",
    overflow: "visible",
    pointerEvents: "none",
    transformOrigin: "0 0",
    willChange: "transform",
  },
  // The frosted sheet is z-index 2 and the card plane 4.
  underCards: { zIndex: 3 },
  overCards: { zIndex: 6 },

  toolbarAnchor: {
    position: "absolute",
    zIndex: 1,
    pointerEvents: "auto",
  },
  toolbarInCardTop: {
    left: "50%",
    bottom: "calc(100% + 8px)",
    transform: "translateX(-50%)",
  },
  toolbarInCardBottom: {
    left: "50%",
    top: "calc(100% + 8px)",
    transform: "translateX(-50%)",
  },
  toolbar: {
    display: "flex",
    alignItems: "center",
    gap: "2px",
    whiteSpace: "nowrap",
    backgroundColor: tokens.colorChrome,
    borderColor: tokens.colorBorder,
    boxShadow: tokens.shadowNodeRaised,
  },

  grip: {
    position: "absolute",
    zIndex: 2,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    pointerEvents: "auto",
    touchAction: "none",
    color: {
      default: tokens.colorBorderStrong,
      ":hover:not(:disabled)": tokens.colorAccent,
    },
  },
  // The card plate is inset 4px from the cell box on the sides and bottom and
  // starts 26px down; each grip sits on the plate's edge.
  gripSe: {
    right: 0,
    bottom: 0,
    width: "16px",
    height: "16px",
    cursor: "nwse-resize",
  },
  gripE: {
    right: 0,
    top: "26px",
    bottom: "4px",
    width: "8px",
    cursor: "ew-resize",
  },
  gripS: {
    left: "4px",
    right: "4px",
    bottom: 0,
    height: "8px",
    cursor: "ns-resize",
  },
  // A quarter arc concentric with the plate's corner: the plate's 12px radius
  // centres 16px in from the cell box's corner (4px inset + 12px), which is
  // this 10×10 box's (0, 0) when placed 6px from right and bottom.
  cornerMark: {
    position: "absolute",
    right: "6px",
    bottom: "6px",
    width: "10px",
    height: "10px",
    display: "block",
    overflow: "visible",
    pointerEvents: "none",
  },
  edgeBarE: {
    width: "2px",
    height: "16px",
    borderRadius: "1px",
    backgroundColor: "currentColor",
  },
  edgeBarS: {
    width: "16px",
    height: "2px",
    borderRadius: "1px",
    backgroundColor: "currentColor",
  },
});

/**
 * A world-space plane over or under the cards, in place of React Flow's
 * `ViewportPortal`. It passes the pointer through; children that take it set
 * `pointerEvents: "auto"` themselves.
 */
export function CellViewportLayer({
  layer,
  viewport,
  children,
}: {
  layer: "under-cards" | "over-cards";
  viewport?: StageViewport;
  children?: React.ReactNode;
}) {
  const viewportApi = useCellViewportApi();
  const active = viewport ?? viewportApi?.viewport ?? { x: 0, y: 0, zoom: 1 };
  return (
    <div
      data-cell-viewport-layer={layer}
      {...stylex.props(
        s.layer,
        layer === "under-cards" ? s.underCards : s.overCards,
      )}
      style={{
        transform: `translate3d(${active.x}px, ${active.y}px, 0) scale(${active.zoom})`,
      }}
    >
      {children}
    </div>
  );
}

/** Gap between a card's edge and its toolbar. */
const TOOLBAR_GAP = 8;

/**
 * A strip of actions floating 8px above or below a card, in place of React
 * Flow's `NodeToolbar`. Given `rect` it places itself in world units (render
 * it inside a {@link CellViewportLayer}); without one it places itself against
 * the card's own positioned root.
 */
export function CellCardToolbar({
  rect,
  visible,
  position = "top",
  children,
}: {
  rect?: { x: number; y: number; width: number; height: number };
  visible: boolean;
  position?: "top" | "bottom";
  children?: React.ReactNode;
}) {
  if (!visible) return null;
  let worldPlacement: React.CSSProperties | undefined;
  if (rect) {
    worldPlacement =
      position === "top"
        ? {
            left: rect.x + rect.width / 2,
            top: rect.y - TOOLBAR_GAP,
            transform: "translate(-50%, -100%)",
          }
        : {
            left: rect.x + rect.width / 2,
            top: rect.y + rect.height + TOOLBAR_GAP,
            transform: "translateX(-50%)",
          };
  }
  let inCardPlacement = null;
  if (!rect) {
    inCardPlacement =
      position === "top" ? s.toolbarInCardTop : s.toolbarInCardBottom;
  }
  return (
    <div
      data-cell-card-toolbar={position}
      {...stylex.props(s.toolbarAnchor, inCardPlacement)}
      style={worldPlacement}
    >
      <Surface tone="raised" padding="xs" shape="pill" xstyle={s.toolbar}>
        {children}
      </Surface>
    </div>
  );
}

type ResizeHandler = (
  cardId: string,
  edge: CellResizeEdge,
  event: React.PointerEvent<HTMLDivElement>,
) => void;

const GRIP_STYLE = { se: s.gripSe, e: s.gripE, s: s.gripS } as const;
const EDGE_MARK_STYLE = { e: s.edgeBarE, s: s.edgeBarS } as const;

/**
 * A card's resize handle, in place of React Flow's `NodeResizeControl`. It
 * captures the pointer and stops the press from reaching the card, so a resize
 * never starts a card drag. The caller turns the pointer moves into whole
 * cells.
 */
export function CellResizeGrip({
  cardId,
  edge = "se",
  visible = true,
  onResizeStart,
  onResizeMove,
  onResizeEnd,
}: {
  cardId: string;
  edge?: CellResizeEdge;
  visible?: boolean;
  onResizeStart?: ResizeHandler;
  onResizeMove?: ResizeHandler;
  onResizeEnd?: ResizeHandler;
}) {
  const activePointer = React.useRef<number | null>(null);
  if (!visible) return null;

  const onPointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.stopPropagation();
    event.preventDefault();
    activePointer.current = event.pointerId;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    onResizeStart?.(cardId, edge, event);
  };
  const onPointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (activePointer.current !== event.pointerId) return;
    event.stopPropagation();
    onResizeMove?.(cardId, edge, event);
  };
  const finish = (event: React.PointerEvent<HTMLDivElement>) => {
    if (activePointer.current !== event.pointerId) return;
    event.stopPropagation();
    activePointer.current = null;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    onResizeEnd?.(cardId, edge, event);
  };

  return (
    <div
      role="separator"
      aria-label={`Resize ${cardId}`}
      aria-orientation={edge === "s" ? "horizontal" : "vertical"}
      data-cell-resize-grip={edge}
      data-resize-grip={edge}
      data-resize-card-id={cardId}
      {...stylex.props(s.grip, GRIP_STYLE[edge])}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finish}
      onPointerCancel={finish}
    >
      {edge === "se" ? (
        <svg
          aria-hidden="true"
          width="10"
          height="10"
          viewBox="0 0 10 10"
          fill="none"
          {...stylex.props(s.cornerMark)}
        >
          <path
            d="M 8.42 1.18 A 8.5 8.5 0 0 1 1.18 8.42"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
      ) : (
        <span aria-hidden {...stylex.props(EDGE_MARK_STYLE[edge])} />
      )}
    </div>
  );
}
