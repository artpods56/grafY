import type { SchemaField } from "../config-schema";
import { STANDARD_NODE_WIDTH_CELLS, clampCellSize } from "../grid-layout";

/**
 * Config fields are laid out as bricks on the canvas lattice. Every footprint
 * below is measured in whole cells and budgets two parts: label row (~17px)
 * and control. Field descriptions live in the label tooltip rather than on the
 * brick, so they cost no height.
 *
 * Calibration is against the default 50px cell, including the 8px gutter each
 * brick reserves below itself:
 * - single-line control (31px) + label ≈ 60px → 1 cell
 * - checkbox (label + full-width bar) → compact 3×1 brick
 * - textarea (96px) + label ≈ 125px → 2 cells
 * - secret (status row + input + hint footer) ≈ 84px → 2 cells
 *
 * Footprints are *minimum* shelf shares and deliberately round down: a brick
 * whose content outgrows its cells stretches the row, while one that overshoots
 * leaves a hole. Widening the node stretches the CSS tracks first; packing only
 * adds columns when another half-brick can sit at {@link MIN_HALF_BRICK_PX}
 * without shrinking its neighbours.
 */
export type ConfigControlKind =
  | "text"
  | "number"
  | "select"
  | "checkbox"
  | "textarea"
  | "code"
  | "number-tuple"
  | "string-list"
  | "secret";

/** Half of the standard node so two short fields pair on one shelf. */
export const HALF_WIDTH_CELLS = STANDARD_NODE_WIDTH_CELLS / 2;

/** A board narrower than one half-width brick cannot pair anything. */
export const CONFIG_BOARD_COLUMNS_MIN = HALF_WIDTH_CELLS;

/**
 * Prefer stretching existing bricks over inventing skinnier columns. A new
 * half-width slot opens only when every slot on the shelf can stay this wide,
 * so descriptions gain characters as the node grows instead of staying clipped.
 */
export const MIN_HALF_BRICK_PX = 220;

export interface FieldFootprint {
  columns: number;
  rows: number;
  /** May absorb columns left over on its shelf. */
  growX?: boolean;
  /** May absorb rows left over when the body is taller than the bricks. */
  growY?: boolean;
}

const FOOTPRINTS: Record<ConfigControlKind, FieldFootprint> = {
  // Short bricks growX so leftover shelf columns widen them (and their copy).
  text: { columns: HALF_WIDTH_CELLS, rows: 1, growX: true },
  number: { columns: HALF_WIDTH_CELLS, rows: 1, growX: true },
  select: { columns: HALF_WIDTH_CELLS, rows: 1, growX: true },
  checkbox: { columns: HALF_WIDTH_CELLS, rows: 1, growX: true },
  textarea: {
    columns: STANDARD_NODE_WIDTH_CELLS,
    rows: 2,
    growX: true,
    growY: true,
  },
  code: {
    columns: STANDARD_NODE_WIDTH_CELLS,
    rows: 2,
    growX: true,
    growY: true,
  },
  // Base brick holds one row of tuple inputs; extra pairs are added per field.
  "number-tuple": { columns: STANDARD_NODE_WIDTH_CELLS, rows: 1, growX: true },
  "string-list": { columns: STANDARD_NODE_WIDTH_CELLS, rows: 2, growX: true },
  secret: { columns: STANDARD_NODE_WIDTH_CELLS, rows: 2, growX: true },
};

export function configControlKind(field: SchemaField): ConfigControlKind {
  if (field.type === "number-tuple") return "number-tuple";
  if (field.type === "string-list") return "string-list";
  if (field.type === "boolean") return "checkbox";
  if (field.enumValues?.length) return "select";
  if (field.format === "textarea")
    return field.codeLanguage ? "code" : "textarea";
  return field.type === "string" ? "text" : "number";
}

export function footprintForControlKind(
  kind: ConfigControlKind,
): FieldFootprint {
  return FOOTPRINTS[kind];
}

/**
 * Footprint for one schema field. Tuples are the one kind whose height is
 * schema-derived: their inputs render two per row, so every extra pair of
 * values costs another cell.
 */
export function fieldFootprint(field: SchemaField): FieldFootprint {
  const footprint = FOOTPRINTS[configControlKind(field)];
  if (field.type !== "number-tuple") return footprint;
  const itemRows = Math.max(1, Math.ceil(field.items.length / 2));
  return { ...footprint, rows: footprint.rows + itemRows - 1 };
}

export function secretFootprint(): FieldFootprint {
  return FOOTPRINTS.secret;
}

/**
 * Columns the packer may use. Tracks still paint as `1fr`, so any leftover
 * pixel width stretches bricks. Extra columns appear only in half-brick
 * quanta once each slot can stay at least {@link MIN_HALF_BRICK_PX} wide.
 */
export function configBoardColumns(width: number, cellSize: number): number {
  const cell = clampCellSize(cellSize);
  const naturalHalfPx = HALF_WIDTH_CELLS * cell;
  const slotPx = Math.max(naturalHalfPx, MIN_HALF_BRICK_PX);
  // Standard node always packs two half-bricks; stretch before reflowing.
  const standardSlots = STANDARD_NODE_WIDTH_CELLS / HALF_WIDTH_CELLS;
  const fittedSlots = Math.max(
    standardSlots,
    Math.floor(Math.max(0, width) / slotPx),
  );
  return Math.max(CONFIG_BOARD_COLUMNS_MIN, fittedSlots * HALF_WIDTH_CELLS);
}

export interface FieldPlacement {
  /** Index into the footprint list — schema order is never reshuffled. */
  index: number;
  /** Zero-based lattice coordinates on the board. */
  col: number;
  row: number;
  w: number;
  h: number;
}

export interface PackedFieldBoard {
  columns: number;
  rows: number;
  placements: FieldPlacement[];
}

interface Shelf {
  height: number;
  items: FieldPlacement[];
  growsY: boolean;
}

/**
 * Order-preserving shelf packing: each brick joins the current row while it
 * still fits, otherwise it opens the next one. `minRows` is a request (the
 * saved body height); the board grows past it whenever the bricks need more.
 */
export function packFieldFootprints(
  footprints: readonly FieldFootprint[],
  { columns, minRows = 0 }: { columns: number; minRows?: number },
): PackedFieldBoard {
  const boardColumns = Math.max(1, Math.floor(columns));
  const requestedRows = Math.max(0, Math.floor(minRows));
  const shelves: Shelf[] = [];
  let cursor = 0;

  for (const [index, footprint] of footprints.entries()) {
    const w = Math.min(
      boardColumns,
      Math.max(1, Math.floor(footprint.columns)),
    );
    const h = Math.max(1, Math.floor(footprint.rows));
    let shelf = shelves.at(-1);
    if (!shelf || cursor + w > boardColumns) {
      shelf = { height: 0, items: [], growsY: false };
      shelves.push(shelf);
      cursor = 0;
    }
    shelf.items.push({ index, col: cursor, row: 0, w, h });
    shelf.height = Math.max(shelf.height, h);
    shelf.growsY = shelf.growsY || footprint.growY === true;
    cursor += w;
  }

  // Hand leftover columns round-robin to growX bricks so every willing field
  // on the shelf gets wider (descriptions stop truncating) instead of one
  // absorber swallowing the whole gap. Fall back to every brick when none opt in.
  for (const shelf of shelves) {
    let spare =
      boardColumns - shelf.items.reduce((total, item) => total + item.w, 0);
    if (spare <= 0 || shelf.items.length === 0) continue;
    const growers = shelf.items.filter(
      (item) => footprints[item.index]?.growX === true,
    );
    const targets = growers.length > 0 ? growers : shelf.items;
    let turn = 0;
    while (spare > 0) {
      const target = targets[turn % targets.length];
      if (!target) break;
      target.w += 1;
      spare -= 1;
      turn += 1;
    }
    let col = 0;
    for (const item of shelf.items) {
      item.col = col;
      col += item.w;
    }
  }

  const packedRows = shelves.reduce((total, shelf) => total + shelf.height, 0);
  const growable = shelves.filter((shelf) => shelf.growsY);
  const spareRows = requestedRows - packedRows;
  if (spareRows > 0 && growable.length > 0) {
    const share = Math.floor(spareRows / growable.length);
    const remainder = spareRows % growable.length;
    for (const [position, shelf] of growable.entries()) {
      shelf.height += share + (position < remainder ? 1 : 0);
    }
  }

  const placements: FieldPlacement[] = [];
  let row = 0;
  for (const shelf of shelves) {
    for (const item of shelf.items) {
      placements.push(
        footprints[item.index]?.growY
          ? { ...item, row, h: shelf.height }
          : { ...item, row },
      );
    }
    row += shelf.height;
  }

  return {
    columns: boardColumns,
    rows: Math.max(row, requestedRows),
    placements,
  };
}
