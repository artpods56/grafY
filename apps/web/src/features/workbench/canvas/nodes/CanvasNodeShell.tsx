"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";
import { RemoteSelectionRing } from "../../room/RemoteSelectionRing";
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
    transitionProperty: {
      default: "transform",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    transitionDuration: "200ms",
    transitionTimingFunction: "cubic-bezier(0.34, 1.56, 0.64, 1)",
  },
  stackDragged: {
    transform: "translate3d(0, -8px, 0)",
    transitionProperty: {
      default: "transform",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    transitionDuration: "200ms",
    transitionTimingFunction: "cubic-bezier(0.34, 1.56, 0.64, 1)",
  },
  frame: {
    position: "relative",
    boxSizing: "border-box",
  },
  shell: {
    position: "relative",
    width: "300px",
    overflow: "visible",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNode,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    boxSizing: "border-box",
    cursor: "grab",
    transitionProperty: {
      default: "box-shadow",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    transitionDuration: "90ms",
    transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
  },
  incompatibleShell: {
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: tokens.colorBorderStrong,
    backgroundColor: tokens.colorSurfaceMuted,
    boxShadow: tokens.shadowNode,
  },
  /**
   * A node whose content is the thing itself: no border, plate, or shadow of
   * its own, so an image sits on the canvas and only the pickup layer moves.
   */
  bareShell: {
    borderWidth: 0,
    backgroundColor: "transparent",
    boxShadow: "none",
    borderRadius: tokens.radiusLg,
  },
  content: {
    boxSizing: "border-box",
    flexShrink: 0,
    width: "100%",
  },
  pickedUp: {
    boxShadow: tokens.shadowNodeRaised,
    transitionDuration: "120ms",
  },
  dragging: {
    cursor: "grabbing",
  },
  pickupShadow: {
    position: "absolute",
    display: "block",
    borderRadius: tokens.radiusLg,
    boxShadow: tokens.shadowNodeActive,
    opacity: 0,
    pointerEvents: "none",
    transform: "translate3d(0, 2px, 0) scale(0.97)",
    transformOrigin: "50% 45%",
    transitionProperty: {
      default: "opacity, transform, box-shadow",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    transitionDuration: "70ms, 120ms, 120ms",
    transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
  },
  pickupShadowActive: {
    opacity: 0.5,
    transform: "translate3d(0, 3px, 0)",
    transitionDuration: "120ms, 200ms, 200ms",
    transitionTimingFunction:
      "cubic-bezier(0.22, 1, 0.36, 1), cubic-bezier(0.34, 1.56, 0.64, 1), cubic-bezier(0.22, 1, 0.36, 1)",
  },
  pickupShadowDragged: {
    opacity: 0.9,
    transform: "translate3d(0, 9px, 0) scale(1.02)",
    boxShadow: tokens.shadowNodeDragged,
    transitionDuration: "120ms, 200ms, 200ms",
    transitionTimingFunction:
      "cubic-bezier(0.22, 1, 0.36, 1), cubic-bezier(0.34, 1.56, 0.64, 1), cubic-bezier(0.22, 1, 0.36, 1)",
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
  const grid = useShellGridFill(naturalWidth, minWidth);
  return { ...lift, ...grid };
}

type CanvasNodeShellState = ReturnType<typeof useCanvasNodeShell>;

interface CanvasNodeShellProps {
  state: CanvasNodeShellState;
  selected: boolean | undefined;
  remoteSelectionColor?: string | null;
  variant?: "default" | "incompatible" | "bare";
  ariaLabel?: string;
  testId?: string;
  children: React.ReactNode;
  resizeHandle?: React.ReactNode;
  appendix?: React.ReactNode;
}

export function CanvasNodeShell({
  state,
  selected,
  remoteSelectionColor,
  variant = "default",
  ariaLabel,
  testId,
  children,
  resizeHandle,
  appendix,
}: CanvasNodeShellProps) {
  const {
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

  return (
    <div
      ref={liftRef}
      {...holdHandlers}
      {...stylex.props(
        s.stack,
        tier === "active" ? s.stackActive : null,
        tier === "dragged" ? s.stackDragged : null,
      )}
      style={{ width: gridWidth }}
    >
      <div {...stylex.props(s.frame)} style={frameStyle}>
        <span
          aria-hidden="true"
          data-node-pickup-shadow="true"
          data-picked-up={pickedUp}
          data-dragging={draggedTier}
          {...stylex.props(
            s.pickupShadow,
            tier === "active" ? s.pickupShadowActive : null,
            tier === "dragged" ? s.pickupShadowDragged : null,
          )}
          style={{
            inset: `${gutter}px ${gutter + 10}px ${gutter + 12}px ${gutter + 10}px`,
          }}
        />
        <article
          aria-label={ariaLabel}
          data-canvas-node-shell="true"
          data-testid={testId}
          {...stylex.props(
            s.shell,
            variant === "incompatible" ? s.incompatibleShell : null,
            pickedUp ? s.pickedUp : null,
            draggedTier ? s.dragging : null,
            variant === "bare" ? s.bareShell : null,
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
      </div>
      {appendix !== undefined ? (
        <div style={gutter ? { marginInline: gutter } : undefined}>
          {appendix}
        </div>
      ) : null}
    </div>
  );
}
