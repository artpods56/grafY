import { describe, expect, it } from "vitest";

import {
  DEFAULT_CANVAS_GRID_SETTINGS,
  EDGE_SELECTOR_HEIGHT_CELLS,
  EDGE_SELECTOR_PILL_HEIGHT,
  EDGE_SELECTOR_WIDTH_CELLS,
  GRID_CELL_SIZE_DEFAULT,
  GRID_SHELL_GUTTER,
  PORT_RAIL_ROW_HEIGHT_CELLS,
  STANDARD_NODE_WIDTH_CELLS,
  ceilToCell,
  clampCellSize,
  edgeSelectorBlockSize,
  gridAlignedWidth,
  gridShellOutset,
  lengthFromSpan,
  normalizeCanvasGridSettings,
  shouldFillShellToGrid,
  shouldSnapPosition,
  shouldSnapSize,
  edgeSelectorSnapPitch,
  snapEdgeSelectorRouteOffset,
  snapLength,
  snapNodeLayout,
  snapPosition,
  snapToCell,
  spanFromLength,
} from "./grid-layout";
import {
  ARTIFACT_CARD_WIDTH_MIN,
  DEFAULT_ARTIFACT_CARD_WIDTH,
} from "./artifact-card";

describe("grid layout", () => {
  it("defaults to a 50px cell and 6-cell standard width", () => {
    expect(GRID_CELL_SIZE_DEFAULT).toBe(50);
    expect(GRID_SHELL_GUTTER).toBe(6);
    expect(DEFAULT_CANVAS_GRID_SETTINGS.cellSize).toBe(50);
    expect(DEFAULT_CANVAS_GRID_SETTINGS.onlyRenderVisibleElements).toBe(false);
    expect(DEFAULT_CANVAS_GRID_SETTINGS.allowWorkflowCornerResize).toBe(false);
    expect(lengthFromSpan(STANDARD_NODE_WIDTH_CELLS, 50)).toBe(300);
  });

  it("sizes edge selectors as 3×1 cells", () => {
    expect(EDGE_SELECTOR_WIDTH_CELLS).toBe(3);
    expect(EDGE_SELECTOR_HEIGHT_CELLS).toBe(1);
    expect(EDGE_SELECTOR_PILL_HEIGHT).toBe(24);
    expect(edgeSelectorBlockSize(50)).toEqual({ width: 150, height: 50 });
    expect(edgeSelectorBlockSize(60)).toEqual({ width: 180, height: 60 });
  });

  it("uses one-cell port rail rows for Lego port alignment", () => {
    expect(PORT_RAIL_ROW_HEIGHT_CELLS).toBe(1);
    expect(lengthFromSpan(PORT_RAIL_ROW_HEIGHT_CELLS, 50)).toBe(50);
  });

  it("snaps edge selector centers onto the half-cell lattice", () => {
    expect(edgeSelectorSnapPitch(50)).toBe(25);
    const natural = { x: 123, y: 47 };
    const offset = snapEdgeSelectorRouteOffset(
      natural,
      { x: 0, y: 0 },
      100,
      50,
      50,
    );
    const anchor = {
      x: natural.x + offset.x,
      y: natural.y + offset.y,
    };
    // Nearest half-cell: 125 / 50
    expect(anchor).toEqual({ x: 125, y: 50 });
    expect(anchor.x % 25).toBe(0);
    expect(anchor.y % 25).toBe(0);
  });

  it("snaps values to the nearest cell multiple", () => {
    expect(snapToCell(0, 50)).toBe(0);
    expect(snapToCell(24, 50)).toBe(0);
    expect(snapToCell(25, 50)).toBe(50);
    expect(snapToCell(310, 50)).toBe(300);
    expect(snapPosition({ x: 145, y: -20 }, 50)).toEqual({ x: 150, y: 0 });
  });

  it("keeps snapped lengths at or above the usable floor in whole cells", () => {
    // NODE_WIDTH_MIN is 260 → ceil(260/50)*50 = 300
    expect(snapLength(250, 50, 260)).toBe(300);
    expect(snapLength(300, 50, 260)).toBe(300);
    expect(snapLength(324, 50, 260)).toBe(300);
    expect(snapLength(325, 50, 260)).toBe(350);
  });

  it("snaps layout axes independently", () => {
    expect(
      snapNodeLayout(
        { width: 310, bodyHeight: 100, appendixHeight: 250 },
        ["width", "bodyHeight"],
        50,
      ),
    ).toEqual({
      width: 300,
      bodyHeight: 100,
      appendixHeight: 250,
    });
  });

  it("converts between spans and pixel lengths", () => {
    expect(spanFromLength(300, 50)).toBe(6);
    expect(lengthFromSpan(3, 50)).toBe(150);
  });

  it("ceils measured shell sizes up to whole cells", () => {
    expect(ceilToCell(300, 50)).toBe(300);
    expect(ceilToCell(300.2, 50)).toBe(300);
    expect(ceilToCell(301, 50)).toBe(350);
    expect(ceilToCell(310, 50)).toBe(350);
  });

  it("outsets annotation shapes by the same gutter cards inset", () => {
    expect(gridShellOutset(DEFAULT_CANVAS_GRID_SETTINGS)).toBe(
      GRID_SHELL_GUTTER,
    );
    expect(gridShellOutset(DEFAULT_CANVAS_GRID_SETTINGS, true)).toBe(0);
    expect(
      gridShellOutset({ ...DEFAULT_CANVAS_GRID_SETTINGS, snapSize: false }),
    ).toBe(0);
  });

  it("snaps each shell to its own width floor", () => {
    const cell = DEFAULT_CANVAS_GRID_SETTINGS.cellSize;
    // A five-cell artifact card snaps back to five cells, not up to the
    // six-cell workflow-node floor.
    expect(
      gridAlignedWidth(
        DEFAULT_ARTIFACT_CARD_WIDTH,
        DEFAULT_CANVAS_GRID_SETTINGS,
        false,
        ARTIFACT_CARD_WIDTH_MIN,
      ),
    ).toBe(DEFAULT_ARTIFACT_CARD_WIDTH);
    expect(
      gridAlignedWidth(
        DEFAULT_ARTIFACT_CARD_WIDTH,
        DEFAULT_CANVAS_GRID_SETTINGS,
      ),
    ).toBe(STANDARD_NODE_WIDTH_CELLS * cell);
    expect(
      gridAlignedWidth(
        ARTIFACT_CARD_WIDTH_MIN - 20,
        DEFAULT_CANVAS_GRID_SETTINGS,
        false,
        ARTIFACT_CARD_WIDTH_MIN,
      ),
    ).toBe(snapLength(ARTIFACT_CARD_WIDTH_MIN, cell, ARTIFACT_CARD_WIDTH_MIN));
  });

  it("aligns display width and shell fill with size-snap settings", () => {
    expect(gridAlignedWidth(300, DEFAULT_CANVAS_GRID_SETTINGS)).toBe(300);
    expect(gridAlignedWidth(310, DEFAULT_CANVAS_GRID_SETTINGS)).toBe(300);
    expect(gridAlignedWidth(310, DEFAULT_CANVAS_GRID_SETTINGS, true)).toBe(310);
    expect(shouldFillShellToGrid(DEFAULT_CANVAS_GRID_SETTINGS)).toBe(true);
    expect(
      shouldFillShellToGrid({
        ...DEFAULT_CANVAS_GRID_SETTINGS,
        snapSize: false,
      }),
    ).toBe(false);
  });

  it("normalizes and clamps stored settings", () => {
    expect(clampCellSize(10)).toBe(24);
    expect(clampCellSize(200)).toBe(96);
    expect(
      normalizeCanvasGridSettings({
        enabled: false,
        cellSize: 54.4,
        snapWhileDragging: true,
        onlyRenderVisibleElements: true,
        allowWorkflowCornerResize: true,
      }),
    ).toEqual({
      ...DEFAULT_CANVAS_GRID_SETTINGS,
      enabled: false,
      cellSize: 54,
      snapWhileDragging: true,
      onlyRenderVisibleElements: true,
      allowWorkflowCornerResize: true,
    });
  });

  it("gates snap by mode, drag phase, and Alt bypass", () => {
    const settings = {
      ...DEFAULT_CANVAS_GRID_SETTINGS,
      snapWhileDragging: false,
      snapWhileResizing: true,
    };
    expect(
      shouldSnapPosition(settings, { dragging: false, bypass: false }),
    ).toBe(true);
    expect(
      shouldSnapPosition(settings, { dragging: true, bypass: false }),
    ).toBe(false);
    expect(
      shouldSnapPosition(settings, { dragging: false, bypass: true }),
    ).toBe(false);
    expect(shouldSnapSize(settings, { drafting: true, bypass: false })).toBe(
      true,
    );
    expect(
      shouldSnapSize(
        { ...settings, enabled: false },
        { drafting: false, bypass: false },
      ),
    ).toBe(false);
  });
});
