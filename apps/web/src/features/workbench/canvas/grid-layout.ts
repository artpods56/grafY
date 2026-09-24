import {
  APPENDIX_HEIGHT_MIN,
  BODY_HEIGHT_MIN,
  LAYOUT_DIMENSION_MAX,
  NODE_WIDTH_MIN,
  clampNodeLayout,
  type WorkflowNodeLayout,
} from "./node-layout";

/** Experimental canvas lattice — tweak via the Canvas lab panel. */
export const GRID_CELL_SIZE_MIN = 24;
export const GRID_CELL_SIZE_MAX = 96;
export const GRID_CELL_SIZE_DEFAULT = 50;

/** Standard workflow node width in cells (50×6 = 300px). */
export const STANDARD_NODE_WIDTH_CELLS = 6;

/**
 * Shared I/O rail: each paired input/output row is one cell tall so ports on
 * neighboring nodes can meet on the same lattice line (Lego join).
 */
export const PORT_RAIL_ROW_HEIGHT_CELLS = 1;

/**
 * Midpoint edge feed selector footprint on the lattice. Two cells left the
 * label about six characters once the menu and remove buttons took their side,
 * which truncated most port names into meaninglessness.
 */
export const EDGE_SELECTOR_WIDTH_CELLS = 3;
export const EDGE_SELECTOR_HEIGHT_CELLS = 1;
/** Painted feed pill — matches workflow port tabs. The 1-cell footprint is the bend grab. */
export const EDGE_SELECTOR_PILL_HEIGHT = 24;

export function edgeSelectorBlockSize(cellSize: number): {
  width: number;
  height: number;
} {
  const cell = clampCellSize(cellSize);
  return {
    width: cell * EDGE_SELECTOR_WIDTH_CELLS,
    height: cell * EDGE_SELECTOR_HEIGHT_CELLS,
  };
}

/**
 * Gap between the cell-aligned layout box and painted chrome.
 * Workflow cards inset by this amount; annotation shapes outset by the same
 * so group frames meet the card edges in the shared gutter.
 */
export const GRID_SHELL_GUTTER = 6;

/** Outset used when shape annotations should bleed past occupied cells. */
export function gridShellOutset(
  settings: CanvasGridSettings | null | undefined,
  bypass = false,
): number {
  return shouldFillShellToGrid(settings, bypass) ? GRID_SHELL_GUTTER : 0;
}

export const GRID_CELL_SIZE_PRESETS = [48, 50, 54, 60, 72] as const;

export type GridResizeAxis = "width" | "bodyHeight" | "appendixHeight";

export interface CanvasGridSettings {
  /** Master switch for snap behaviour (background can stay independent). */
  enabled: boolean;
  showBackground: boolean;
  /** Let React Flow unmount nodes and edges outside the viewport. */
  onlyRenderVisibleElements: boolean;
  snapPosition: boolean;
  snapSize: boolean;
  /** Magnetize positions during drag (not only on release). */
  snapWhileDragging: boolean;
  /** Magnetize layout during resize drag (not only on release). */
  snapWhileResizing: boolean;
  /**
   * When off (default), workflow nodes have no corner resize — body grows via
   * field controls (e.g. textarea width/height). Artifact Viewers keep their
   * corner handle.
   */
  allowWorkflowCornerResize: boolean;
  cellSize: number;
}

export const DEFAULT_CANVAS_GRID_SETTINGS: CanvasGridSettings = {
  enabled: true,
  showBackground: true,
  onlyRenderVisibleElements: false,
  snapPosition: true,
  snapSize: true,
  snapWhileDragging: false,
  snapWhileResizing: true,
  allowWorkflowCornerResize: false,
  cellSize: GRID_CELL_SIZE_DEFAULT,
};

export function clampCellSize(value: number): number {
  if (!Number.isFinite(value)) return GRID_CELL_SIZE_DEFAULT;
  return Math.min(
    GRID_CELL_SIZE_MAX,
    Math.max(GRID_CELL_SIZE_MIN, Math.round(value)),
  );
}

export function normalizeCanvasGridSettings(
  partial: Partial<CanvasGridSettings> | null | undefined,
): CanvasGridSettings {
  const base = DEFAULT_CANVAS_GRID_SETTINGS;
  if (!partial) return { ...base };
  return {
    enabled: partial.enabled ?? base.enabled,
    showBackground: partial.showBackground ?? base.showBackground,
    onlyRenderVisibleElements:
      partial.onlyRenderVisibleElements ?? base.onlyRenderVisibleElements,
    snapPosition: partial.snapPosition ?? base.snapPosition,
    snapSize: partial.snapSize ?? base.snapSize,
    snapWhileDragging: partial.snapWhileDragging ?? base.snapWhileDragging,
    snapWhileResizing: partial.snapWhileResizing ?? base.snapWhileResizing,
    allowWorkflowCornerResize:
      partial.allowWorkflowCornerResize ?? base.allowWorkflowCornerResize,
    cellSize: clampCellSize(partial.cellSize ?? base.cellSize),
  };
}

/** Nearest cell multiple; keeps 0 at the origin. */
export function snapToCell(value: number, cellSize: number): number {
  const cell = clampCellSize(cellSize);
  if (!Number.isFinite(value)) return 0;
  const snapped = Math.round(value / cell) * cell;
  return Object.is(snapped, -0) ? 0 : snapped;
}

/**
 * Snap a length to whole cells, never below the smallest cell count that
 * still satisfies `min` (so cell composition stays usable).
 */
export function snapLength(
  value: number,
  cellSize: number,
  min: number,
  max: number = LAYOUT_DIMENSION_MAX,
): number {
  const cell = clampCellSize(cellSize);
  const floor = Math.max(cell, Math.ceil(min / cell) * cell);
  const snapped = snapToCell(value, cell);
  return Math.min(max, Math.max(floor, snapped));
}

export function snapPosition(
  position: { x: number; y: number },
  cellSize: number,
): { x: number; y: number } {
  return {
    x: snapToCell(position.x, cellSize),
    y: snapToCell(position.y, cellSize),
  };
}

/**
 * Edge selectors snap on a half-cell lattice so their centers can sit on the
 * same horizontal lines as port-rail handle centers (mid-cell).
 */
export function edgeSelectorSnapPitch(cellSize: number): number {
  return clampCellSize(cellSize) / 2;
}

/**
 * Snap an edge selector's route offset so the bent path anchor (block center)
 * lands on a half-cell lattice point.
 */
export function snapEdgeSelectorRouteOffset(
  naturalAnchor: { x: number; y: number },
  routeOffset: { x: number; y: number },
  _width: number,
  _height: number,
  cellSize: number,
): { x: number; y: number } {
  const anchor = {
    x: naturalAnchor.x + routeOffset.x,
    y: naturalAnchor.y + routeOffset.y,
  };
  const snappedAnchor = snapPosition(anchor, edgeSelectorSnapPitch(cellSize));
  return {
    x: snappedAnchor.x - naturalAnchor.x,
    y: snappedAnchor.y - naturalAnchor.y,
  };
}

export function spanFromLength(length: number, cellSize: number): number {
  const cell = clampCellSize(cellSize);
  if (!Number.isFinite(length) || length <= 0) return 1;
  return Math.max(1, Math.round(length / cell));
}

export function lengthFromSpan(span: number, cellSize: number): number {
  const cell = clampCellSize(cellSize);
  return Math.max(1, Math.round(span)) * cell;
}

/**
 * Grow a measured length up to the next cell boundary so a card edge can sit
 * on the lattice. Values already on a cell line (within 0.5px) stay put.
 */
export function ceilToCell(value: number, cellSize: number): number {
  const cell = clampCellSize(cellSize);
  if (!Number.isFinite(value) || value <= 0) return cell;
  const nearest = Math.round(value / cell) * cell;
  if (Math.abs(value - nearest) < 0.5) {
    return Math.max(cell, nearest === 0 ? cell : nearest);
  }
  return Math.max(cell, Math.ceil(value / cell) * cell);
}

/**
 * Display width forced onto the lattice when size snap is active. `minWidth` is
 * the floor a shell may not snap below; workflow nodes and artifact cards have
 * different floors, so the caller passes its own.
 */
export function gridAlignedWidth(
  width: number,
  settings: CanvasGridSettings | null | undefined,
  bypass = false,
  minWidth: number = NODE_WIDTH_MIN,
): number {
  if (!settings || !shouldSnapSize(settings, { drafting: false, bypass })) {
    return width;
  }
  return snapLength(width, settings.cellSize, minWidth);
}

/** Whether card shells should pad their measured size up to whole cells. */
export function shouldFillShellToGrid(
  settings: CanvasGridSettings | null | undefined,
  bypass = false,
): boolean {
  if (!settings || bypass) return false;
  return settings.enabled && settings.snapSize;
}

export function snapNodeLayout(
  layout: WorkflowNodeLayout | null | undefined,
  axes: readonly GridResizeAxis[],
  cellSize: number,
): WorkflowNodeLayout | null {
  if (!layout) return null;
  const next: WorkflowNodeLayout = { ...layout };
  if (axes.includes("width") && next.width !== undefined) {
    next.width = snapLength(next.width, cellSize, NODE_WIDTH_MIN);
  }
  if (axes.includes("bodyHeight") && next.bodyHeight !== undefined) {
    next.bodyHeight = snapLength(next.bodyHeight, cellSize, BODY_HEIGHT_MIN);
  }
  if (axes.includes("appendixHeight") && next.appendixHeight !== undefined) {
    next.appendixHeight = snapLength(
      next.appendixHeight,
      cellSize,
      APPENDIX_HEIGHT_MIN,
    );
  }
  return clampNodeLayout(next);
}

/** Axes present on a layout blob — used when snapping an existing card. */
export function layoutSnapAxes(
  layout: WorkflowNodeLayout | null | undefined,
  fallback: readonly GridResizeAxis[] = ["width"],
): GridResizeAxis[] {
  if (!layout) return [...fallback];
  const axes: GridResizeAxis[] = [];
  if (layout.width !== undefined) axes.push("width");
  if (layout.bodyHeight !== undefined) axes.push("bodyHeight");
  if (layout.appendixHeight !== undefined) axes.push("appendixHeight");
  return axes.length ? axes : [...fallback];
}

export function shouldSnapPosition(
  settings: CanvasGridSettings,
  opts: { dragging: boolean; bypass: boolean },
): boolean {
  if (!settings.enabled || !settings.snapPosition || opts.bypass) return false;
  return opts.dragging ? settings.snapWhileDragging : true;
}

export function shouldSnapSize(
  settings: CanvasGridSettings,
  opts: { drafting: boolean; bypass: boolean },
): boolean {
  if (!settings.enabled || !settings.snapSize || opts.bypass) return false;
  return opts.drafting ? settings.snapWhileResizing : true;
}
