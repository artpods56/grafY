"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { useViewport } from "@xyflow/react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import { shouldSnapSize, snapNodeLayout } from "../grid-layout";
import {
  DEFAULT_BODY_HEIGHT,
  DEFAULT_NODE_WIDTH,
  clampNodeLayout,
  mergeNodeLayout,
  type WorkflowNodeLayout,
} from "../node-layout";

const RESIZE_AXES = ["width", "bodyHeight"] as const;

const s = stylex.create({
  handle: {
    position: "absolute",
    right: "0",
    bottom: "0",
    width: "16px",
    height: "16px",
    padding: 0,
    borderWidth: 0,
    borderRadius: "3px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHoverStrong,
    },
    cursor: "nwse-resize",
    touchAction: "none",
    zIndex: 2,
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

/**
 * SE grip on a textarea field — grows node width and body height without a
 * corner resize on the card chrome.
 */
export function TextareaBodyResizeHandle({
  layout,
  ariaLabel,
  onDraft,
  onCommit,
}: {
  layout: WorkflowNodeLayout | null;
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
    latest: WorkflowNodeLayout | null;
  } | null>(null);

  const resolveLayout = React.useCallback(
    (width: number, bodyHeight: number, drafting: boolean, bypass: boolean) => {
      const merged = mergeNodeLayout(layout, { width, bodyHeight });
      const settings = grid?.settings;
      if (!settings || !shouldSnapSize(settings, { drafting, bypass })) {
        return clampNodeLayout(merged);
      }
      return (
        snapNodeLayout(merged, RESIZE_AXES, settings.cellSize) ??
        clampNodeLayout(merged)
      );
    },
    [grid?.settings, layout],
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
        dragRef.current = {
          pointerId: event.pointerId,
          startX: event.clientX,
          startY: event.clientY,
          startWidth: layout?.width ?? DEFAULT_NODE_WIDTH,
          startBodyHeight: layout?.bodyHeight ?? DEFAULT_BODY_HEIGHT,
          latest: layout,
        };
      }}
      onPointerMove={(event) => {
        const drag = dragRef.current;
        if (!drag || drag.pointerId !== event.pointerId) return;
        event.preventDefault();
        event.stopPropagation();
        const scale = Math.max(zoom, 0.01);
        const deltaX = (event.clientX - drag.startX) / scale;
        const deltaY = (event.clientY - drag.startY) / scale;
        const resolved = resolveLayout(
          drag.startWidth + deltaX,
          drag.startBodyHeight + deltaY,
          true,
          event.altKey,
        );
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
        const resolved = resolveLayout(
          drag.latest?.width ?? drag.startWidth,
          drag.latest?.bodyHeight ?? drag.startBodyHeight,
          false,
          event.altKey,
        );
        onCommit(resolved);
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
