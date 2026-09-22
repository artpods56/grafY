"use client";

import * as React from "react";

import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import {
  GRID_SHELL_GUTTER,
  ceilToCell,
  gridAlignedWidth,
  shouldFillShellToGrid,
} from "../grid-layout";

/**
 * Forces a card shell onto whole grid cells from measured content size.
 * Uses layout `offsetHeight` (not getBoundingClientRect) so zoom cannot skew
 * the cell math.
 *
 * The returned `frameStyle` is the cell-aligned occupancy box. The painted
 * card (`shellStyle`) sits inset by {@link GRID_SHELL_GUTTER} so lattice lines
 * remain visible around neighboring nodes.
 */
export function useShellGridFill(
  naturalWidth: number,
  minWidth?: number,
): {
  contentRef: React.RefObject<HTMLDivElement | null>;
  frameStyle: React.CSSProperties;
  shellStyle: React.CSSProperties;
  gridWidth: number;
  paintWidth: number;
  gutter: number;
  fillMinHeight: number | undefined;
} {
  const grid = useOptionalCanvasGridSettings();
  const settings = grid?.settings ?? null;
  const bypass = grid?.bypassSnap ?? false;
  const fill = shouldFillShellToGrid(settings, bypass);
  const cellSize = settings?.cellSize ?? 50;
  const gridWidth = gridAlignedWidth(naturalWidth, settings, bypass, minWidth);
  const gutter = fill ? GRID_SHELL_GUTTER : 0;
  const paintWidth = Math.max(1, gridWidth - gutter * 2);

  const contentRef = React.useRef<HTMLDivElement | null>(null);
  const [fillHeight, setFillHeight] = React.useState<number | undefined>(
    undefined,
  );

  React.useLayoutEffect(() => {
    if (!fill) return;
    const el = contentRef.current;
    if (!el) return;

    const update = () => {
      // offsetHeight is in local layout px (pre-parent-transform), matching
      // React Flow node coordinates and Background gap units.
      const height = el.offsetHeight;
      if (height <= 0) return;
      setFillHeight((previous) => {
        // Include gutters so the painted inner area still fits content.
        const next = ceilToCell(height + GRID_SHELL_GUTTER * 2, cellSize);
        return previous === next ? previous : next;
      });
    };
    update();

    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [cellSize, fill]);

  const activeFillHeight = fill ? fillHeight : undefined;

  const frameStyle = React.useMemo<React.CSSProperties>(() => {
    const style: React.CSSProperties = {
      width: gridWidth,
      boxSizing: "border-box",
    };
    if (activeFillHeight !== undefined) {
      style.height = activeFillHeight;
      style.minHeight = activeFillHeight;
      style.padding = GRID_SHELL_GUTTER;
    }
    return style;
  }, [activeFillHeight, gridWidth]);

  const shellStyle = React.useMemo<React.CSSProperties>(() => {
    const style: React.CSSProperties = {
      width: fill ? "100%" : gridWidth,
      boxSizing: "border-box",
      display: "flex",
      flexDirection: "column",
    };
    if (activeFillHeight !== undefined) {
      style.height = "100%";
      style.minHeight = 0;
      // Keep overflow visible so port handles can extend past the card.
    }
    return style;
  }, [activeFillHeight, fill, gridWidth]);

  return {
    contentRef,
    frameStyle,
    shellStyle,
    gridWidth,
    paintWidth,
    gutter,
    fillMinHeight: activeFillHeight,
  };
}
