"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";
import { RemoteSelectionRing } from "../../room/RemoteSelectionRing";
import {
  CanvasCardFrame,
  CanvasCardHead,
  canvasCard,
} from "./CanvasCardLayout";
import { NODE_HEADER_HEIGHT } from "./CanvasNodeChrome";
import { PortRevealProvider, usePortReveal } from "./PortBall";
import { usePickupLift } from "./usePickupLift";
import { useShellGridFill } from "./useShellGridFill";

const s = stylex.create({
  stack: {
    position: "relative",
    display: "grid",
    width: "fit-content",
    transitionProperty: {
      default: "transform",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    transitionDuration: "120ms",
    transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
  },
  stackActive: {
    transform: "translate3d(0, -2px, 0)",
    transitionDuration: "200ms",
    transitionTimingFunction: "cubic-bezier(0.34, 1.56, 0.64, 1)",
  },
  stackDragged: {
    transform: "translate3d(0, -8px, 0)",
    transitionDuration: "200ms",
    transitionTimingFunction: "cubic-bezier(0.34, 1.56, 0.64, 1)",
  },
  // The plate: the node's body under its name. Flat at rest; it takes the same
  // ground shadow as an artifact's media when picked up, and a deeper one when
  // carried. Rails hang off this plate via `data-artifact-rail`.
  shell: {
    position: "relative",
    width: "300px",
    overflow: "visible",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorChrome,
    boxShadow: "none",
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    boxSizing: "border-box",
    cursor: "grab",
    transitionProperty: "box-shadow, border-color",
    transitionDuration: {
      default: "180ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
    transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
  },
  shellActive: {
    borderColor: tokens.colorBorderStrong,
    boxShadow: tokens.shadowNodeActive,
  },
  shellDragged: {
    borderColor: tokens.colorBorderStrong,
    boxShadow: tokens.shadowNodeDragged,
    cursor: "grabbing",
  },
  incompatibleShell: {
    borderStyle: "dashed",
    borderColor: tokens.colorBorderStrong,
    backgroundColor: tokens.colorSurfaceMuted,
  },
  content: {
    boxSizing: "border-box",
    flexShrink: 0,
    width: "100%",
  },
});

interface UseCanvasNodeShellOptions {
  id: string;
  selected: boolean | undefined;
  dragging: boolean | undefined;
  naturalWidth: number;
  /** Lattice floor for the shell width; artifact cards are narrower than nodes. */
  minWidth?: number;
  updateNodeInternals: (id: string) => void;
}

export function useCanvasNodeShell({
  id,
  selected,
  dragging,
  naturalWidth,
  minWidth,
  updateNodeInternals,
}: UseCanvasNodeShellOptions) {
  const lift = usePickupLift({
    id,
    selected,
    dragging,
    updateNodeInternals,
  });
  const grid = useShellGridFill(naturalWidth, minWidth, NODE_HEADER_HEIGHT);
  return { ...lift, ...grid, id, updateNodeInternals };
}

type CanvasNodeShellState = ReturnType<typeof useCanvasNodeShell>;

interface CanvasNodeShellProps {
  state: CanvasNodeShellState;
  selected: boolean | undefined;
  remoteSelectionColor?: string | null;
  variant?: "default" | "incompatible";
  ariaLabel?: string;
  testId?: string;
  /** The name row; it sits above the plate, not inside it. */
  header: React.ReactNode;
  /** Keeps the ports out while one of the node's menus is open. */
  menuOpen?: boolean;
  children: React.ReactNode;
  resizeHandle?: React.ReactNode;
  appendix?: React.ReactNode;
}

/**
 * A node on the canvas, sharing the artifact card's DOM: frame → head / body,
 * with port rails hung outside the plate. Port names stay off the plate
 * (option B) — each ball carries its name on hover.
 */
export function CanvasNodeShell({
  state,
  selected,
  remoteSelectionColor,
  variant = "default",
  ariaLabel,
  testId,
  header,
  menuOpen = false,
  children,
  resizeHandle,
  appendix,
}: CanvasNodeShellProps) {
  const {
    id,
    updateNodeInternals,
    tier,
    pickedUp,
    draggedTier,
    liftRef,
    holdHandlers,
    contentRef,
    frameStyle,
    shellStyle,
    gridWidth,
    gutter,
  } = state;
  const portReveal = usePortReveal({
    id,
    active: Boolean(selected) || menuOpen,
    updateNodeInternals,
  });

  return (
    <PortRevealProvider value={portReveal}>
      <div
        ref={liftRef}
        {...holdHandlers}
        data-node-tier={tier}
        data-artifact-node="true"
        {...stylex.props(
          s.stack,
          tier === "active" ? s.stackActive : null,
          tier === "dragged" ? s.stackDragged : null,
        )}
        style={{ width: gridWidth }}
      >
        <CanvasCardFrame style={frameStyle}>
          <CanvasCardHead>{header}</CanvasCardHead>
          <article
            aria-label={ariaLabel}
            data-artifact-body="true"
            data-canvas-node-shell="true"
            data-picked-up={pickedUp}
            data-dragging={draggedTier}
            data-testid={testId}
            {...stylex.props(
              canvasCard.body,
              s.shell,
              variant === "incompatible" ? s.incompatibleShell : null,
              tier === "active" ? s.shellActive : null,
              tier === "dragged" ? s.shellDragged : null,
            )}
            style={shellStyle}
          >
            {!selected && remoteSelectionColor ? (
              <RemoteSelectionRing color={remoteSelectionColor} />
            ) : null}
            <div ref={contentRef} {...stylex.props(s.content)}>
              {children}
            </div>
            {resizeHandle}
          </article>
        </CanvasCardFrame>
        {appendix !== undefined ? (
          <div style={gutter ? { marginInline: gutter } : undefined}>
            {appendix}
          </div>
        ) : null}
      </div>
    </PortRevealProvider>
  );
}
