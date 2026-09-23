"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { useViewport } from "@xyflow/react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import {
  shouldSnapSize,
  snapNodeLayout,
  type GridResizeAxis,
} from "../grid-layout";
import {
  DEFAULT_APPENDIX_HEIGHT,
  DEFAULT_BODY_HEIGHT,
  DEFAULT_NODE_WIDTH,
  clampNodeLayout,
  type WorkflowNodeLayout,
} from "../node-layout";

const s = stylex.create({
  handle: {
    position: "absolute",
    right: "2px",
    bottom: "2px",
    width: "14px",
    height: "14px",
    padding: 0,
    borderWidth: 0,
    borderRadius: "3px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHoverStrong,
    },
    cursor: "nwse-resize",
    touchAction: "none",
  },
  glyph: {
    position: "absolute",
    right: "3px",
    bottom: "3px",
    width: "7px",
    height: "7px",
    borderRightWidth: 2,
    borderRightStyle: "solid",
    borderBottomWidth: 2,
    borderBottomStyle: "solid",
    borderColor: tokens.colorSubtle,
    opacity: 0.75,
    pointerEvents: "none",
  },
});

function nodeInteractionProps(props: ReturnType<typeof stylex.props>) {
  return {
    ...props,
    className: `nodrag nopan nowheel${props.className ? ` ${props.className}` : ""}`,
  };
}

export function LayoutResizeHandle({
  layout,
  axes,
  ariaLabel,
  onDraft,
  onCommit,
}: {
  layout: WorkflowNodeLayout | null;
  axes: readonly GridResizeAxis[];
  ariaLabel: string;
  onDraft: (layout: WorkflowNodeLayout | null) => void;
  onCommit: (layout: WorkflowNodeLayout | null) => void;
}) {
  const { zoom } = useViewport();
  const grid = useOptionalCanvasGridSettings();
  const dragRef = React.useRef<{
    pointerId: number;
    startX: number;
    startY: number;
    startWidth: number;
    startBodyHeight: number;
    startAppendixHeight: number;
    latest: WorkflowNodeLayout | null;
  } | null>(null);

  const resolveLayout = React.useCallback(
    (next: WorkflowNodeLayout | null, drafting: boolean, bypass: boolean) => {
      const clamped = clampNodeLayout(next);
      const settings = grid?.settings;
      if (!settings || !shouldSnapSize(settings, { drafting, bypass })) {
        return clamped;
      }
      return snapNodeLayout(clamped, axes, settings.cellSize) ?? clamped;
    },
    [axes, grid?.settings],
  );

  return (
    <button
      type="button"
      aria-label={ariaLabel}
      title={ariaLabel}
      {...nodeInteractionProps(stylex.props(s.handle))}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.preventDefault();
        event.stopPropagation();
        event.currentTarget.setPointerCapture(event.pointerId);
        const start = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          startWidth: layout?.width ?? DEFAULT_NODE_WIDTH,
          startBodyHeight: layout?.bodyHeight ?? DEFAULT_BODY_HEIGHT,
          startAppendixHeight:
            layout?.appendixHeight ?? DEFAULT_APPENDIX_HEIGHT,
          latest: layout,
        };
        dragRef.current = start;
      }}
      onPointerMove={(event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        event.preventDefault();
        event.stopPropagation();
        const scale = Math.max(zoom, 0.01);
        const deltaX = (event.clientX - drag.startX) / scale;
        const deltaY = (event.clientY - drag.startY) / scale;
        const next: WorkflowNodeLayout = { ...layout };
        if (axes.includes("width")) {
          next.width = drag.startWidth + deltaX;
        }
        if (axes.includes("bodyHeight")) {
          next.bodyHeight = drag.startBodyHeight + deltaY;
        }
        if (axes.includes("appendixHeight")) {
          next.appendixHeight = drag.startAppendixHeight + deltaY;
        }
        const resolved = resolveLayout(next, true, event.altKey);
        drag.latest = resolved;
        onDraft(resolved);
      }}
      onPointerUp={(event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        event.preventDefault();
        event.stopPropagation();
        if (event.currentTarget.hasPointerCapture(event.pointerId)) {
          event.currentTarget.releasePointerCapture(event.pointerId);
        }
        dragRef.current = null;
        onCommit(resolveLayout(drag.latest, false, event.altKey));
      }}
      onPointerCancel={(event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        event.stopPropagation();
        dragRef.current = null;
        onDraft(null);
      }}
    >
      <span aria-hidden="true" {...stylex.props(s.glyph)} />
    </button>
  );
}
