"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Popover } from "@base-ui/react/popover";
import { ChevronDown, X } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import { overlay } from "@/lib/stylex/overlay.stylex";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import {
  EDGE_SELECTOR_HEIGHT_CELLS,
  EDGE_SELECTOR_PILL_HEIGHT,
  EDGE_SELECTOR_WIDTH_CELLS,
  GRID_CELL_SIZE_DEFAULT,
  edgeSelectorBlockSize,
} from "../grid-layout";

const s = stylex.create({
  positioner: {
    position: "absolute",
    display: "grid",
    placeItems: "center",
    pointerEvents: "all",
    zIndex: 10,
  },
  dockedPositioner: {
    pointerEvents: "none",
    zIndex: 20,
  },
  /**
   * Full 2×1 footprint is the bend grab — much larger than the painted pill.
   * Menu / remove sit above with their own hit targets.
   */
  bendHandle: {
    position: "absolute",
    inset: 0,
    width: "100%",
    height: "100%",
    padding: 0,
    borderWidth: 0,
    borderRadius: "8px",
    backgroundColor: "transparent",
    cursor: "grab",
    touchAction: "none",
    zIndex: 1,
  },
  bendHandleDragging: {
    cursor: "grabbing",
  },
  block: {
    position: "relative",
    boxSizing: "border-box",
    display: "grid",
    alignItems: "stretch",
    overflow: "visible",
    width: "100%",
    // Literal: StyleX cannot import constants from grid-layout.ts.
    // Keep in sync with EDGE_SELECTOR_PILL_HEIGHT.
    height: "24px",
    borderWidth: 0,
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceMuted,
    boxShadow: tokens.shadowNode,
    pointerEvents: "none",
    zIndex: 2,
  },
  blockSelected: {
    boxShadow: tokens.shadowNodeSelected,
    outlineWidth: 1,
    outlineStyle: "solid",
    outlineColor: tokens.colorAccentBorder,
  },
  blockDragging: {
    backgroundColor: tokens.colorAccentSoft,
  },
  blockDisabled: {
    opacity: 0.78,
  },
  labelFace: {
    minWidth: 0,
    width: "100%",
    height: "100%",
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    paddingLeft: "14px",
    paddingRight: "44px",
    borderWidth: 0,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    pointerEvents: "none",
  },
  editLabel: {
    minWidth: 0,
    flex: "1 1 auto",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    textAlign: "left",
  },
  menuButton: {
    position: "absolute",
    top: "50%",
    right: "22px",
    width: "20px",
    height: "20px",
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "9999px",
    transform: "translateY(-50%)",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHoverStrong,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorTextEmphasis },
    cursor: "pointer",
    pointerEvents: "all",
    zIndex: 3,
  },
  removeButton: {
    position: "absolute",
    top: "50%",
    right: "2px",
    width: "20px",
    height: "20px",
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "9999px",
    transform: "translateY(-50%)",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorDangerHover,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorDanger },
    cursor: "pointer",
    pointerEvents: "all",
    zIndex: 3,
  },
  popup: {
    width: "300px",
    overflow: "hidden",
    zIndex: 50,
  },
  // At rest an edge says only what its ports do not: a small quiet chip.
  restPositioner: {
    width: "auto",
    height: "auto",
  },
  restChip: {
    display: "block",
    maxWidth: "150px",
    height: "18px",
    boxSizing: "border-box",
    paddingInline: "8px",
    overflow: "hidden",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "9999px",
    backgroundColor: tokens.colorChrome,
    color: tokens.colorMuted,
    fontSize: "10px",
    fontWeight: 500,
    lineHeight: "16px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    cursor: "pointer",
  },
});

/**
 * Hover that survives the gap between an edge's path and its label, which
 * live in different layers: leaving one and entering the other within a
 * beat keeps it hovered.
 */
export function useHoverIntent(leaveDelayMs = 160) {
  const [hovered, setHovered] = React.useState(false);
  const timer = React.useRef<number | null>(null);
  const clear = () => {
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = null;
  };
  React.useEffect(() => clear, []);
  const handlers = React.useMemo(
    () => ({
      onPointerEnter: () => {
        clear();
        setHovered(true);
      },
      onPointerLeave: () => {
        clear();
        timer.current = window.setTimeout(() => {
          timer.current = null;
          setHovered(false);
        }, leaveDelayMs);
      },
    }),
    [leaveDelayMs],
  );
  return { hovered, handlers };
}

type HoverHandlers = ReturnType<typeof useHoverIntent>["handlers"];

export type EdgeSelectorBendHandlers = Pick<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  | "onClick"
  | "onDoubleClick"
  | "onKeyDown"
  | "onPointerDown"
  | "onPointerMove"
  | "onPointerUp"
  | "onPointerCancel"
  | "onLostPointerCapture"
>;

export interface EdgeSelectorBlockProps {
  anchor: { x: number; y: number };
  selected?: boolean;
  disabled?: boolean;
  label: string;
  /** Spanning join between adjacent facing ports; hides the bend grab. */
  docked?: boolean;
  width?: number;
  height?: number;
  bendAriaLabel: string;
  bendDragging?: boolean;
  bendHandlers: EdgeSelectorBendHandlers;
  editAriaLabel: string;
  editTitle: string;
  editDisabled?: boolean;
  removeAriaLabel: string;
  onRemove: () => void;
  children: React.ReactNode;
  /**
   * What an idle edge shows when not selected or hovered: the full selector,
   * just its label (when the label says more than the ports do), or nothing.
   */
  rest?: "full" | "label" | "hidden";
  /** The edge's path is hovered (it shares `hoverHandlers` with the block). */
  hovered?: boolean;
  hoverHandlers?: HoverHandlers;
}

/** Midpoint feed selector — 3 cells wide × 1 cell tall in flow coordinates. */
export function EdgeSelectorBlock({
  anchor,
  selected = false,
  disabled = false,
  label,
  docked = false,
  width: widthOverride,
  height: heightOverride,
  bendAriaLabel,
  bendDragging = false,
  bendHandlers,
  editAriaLabel,
  editTitle,
  editDisabled = false,
  removeAriaLabel,
  onRemove,
  children,
  rest = "full",
  hovered = false,
  hoverHandlers,
}: EdgeSelectorBlockProps) {
  const [menuOpen, setMenuOpen] = React.useState(false);
  const grid = useOptionalCanvasGridSettings();
  const cellSize = grid?.settings.cellSize ?? GRID_CELL_SIZE_DEFAULT;
  const routed = edgeSelectorBlockSize(cellSize);
  const width = widthOverride ?? routed.width;
  const height =
    heightOverride ?? (docked ? EDGE_SELECTOR_PILL_HEIGHT : routed.height);
  const expanded =
    rest === "full" ||
    docked ||
    selected ||
    hovered ||
    menuOpen ||
    bendDragging;

  if (!expanded && rest === "hidden") return null;
  if (!expanded) {
    return (
      <div
        className="nodrag nopan nowheel"
        data-testid="edge-selector-block"
        data-rest="label"
        style={{
          transform: `translate(-50%, -50%) translate(${anchor.x}px, ${anchor.y}px)`,
        }}
        {...stylex.props(s.positioner, s.restPositioner)}
        {...hoverHandlers}
      >
        <span
          title={label}
          {...stylex.props(s.restChip, disabled ? s.blockDisabled : null)}
        >
          {label}
        </span>
      </div>
    );
  }

  return (
    <div
      className="nodrag nopan nowheel"
      data-testid="edge-selector-block"
      data-docked={docked ? "true" : undefined}
      data-width-cells={docked ? undefined : EDGE_SELECTOR_WIDTH_CELLS}
      data-height-cells={docked ? undefined : EDGE_SELECTOR_HEIGHT_CELLS}
      data-cell-size={cellSize}
      style={{
        width,
        height,
        transform: `translate(-50%, -50%) translate(${anchor.x}px, ${anchor.y}px)`,
      }}
      {...stylex.props(s.positioner, docked ? s.dockedPositioner : null)}
      {...hoverHandlers}
    >
      {docked ? null : (
        <button
          type="button"
          aria-label={bendAriaLabel}
          aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown Home"
          title="Drag to bend · arrow keys nudge · double-click or Home to reset"
          disabled={disabled}
          {...stylex.props(
            s.bendHandle,
            bendDragging ? s.bendHandleDragging : null,
          )}
          {...bendHandlers}
        />
      )}
      <div
        {...stylex.props(
          s.block,
          selected ? s.blockSelected : null,
          bendDragging ? s.blockDragging : null,
          disabled ? s.blockDisabled : null,
        )}
      >
        <span {...stylex.props(s.labelFace)}>
          <span title={label} {...stylex.props(s.editLabel)}>
            {label}
          </span>
        </span>
        <Popover.Root onOpenChange={setMenuOpen}>
          <Popover.Trigger
            type="button"
            disabled={editDisabled}
            aria-label={editAriaLabel}
            title={editTitle}
            {...stylex.props(s.menuButton)}
            onPointerDown={(event) => event.stopPropagation()}
          >
            <ChevronDown size={11} />
          </Popover.Trigger>
          <Popover.Portal>
            <Popover.Positioner side="bottom" align="center" sideOffset={7}>
              <Popover.Popup
                className="nodrag nopan nowheel"
                {...stylex.props(overlay.popup, s.popup)}
              >
                {children}
              </Popover.Popup>
            </Popover.Positioner>
          </Popover.Portal>
        </Popover.Root>
        <button
          type="button"
          aria-label={removeAriaLabel}
          title="Remove connection"
          {...stylex.props(s.removeButton)}
          onPointerDown={(event) => event.stopPropagation()}
          onClick={(event) => {
            event.stopPropagation();
            onRemove();
          }}
        >
          <X size={12} aria-hidden="true" />
        </button>
      </div>
    </div>
  );
}
