import { tokens } from "@/lib/stylex/tokens.stylex";

import type {
  AnnotationColorToken,
  CellConfigFieldSpec,
  OperatorCardSurfaceData,
} from "./cell-contracts";
import { CELL_SIZE, type CellCardModel } from "./cell-model";

/**
 * Where each part of a real card sits on the cell lattice, worked out from
 * the card's data alone: no part of a card is measured in the DOM. A card's
 * rows are whole cells, so a band that grows pushes the bands below it down by
 * whole cells and never moves a port above it.
 */

/** A run of whole cell rows inside a card, counted from the card's top row. */
export interface CellBand {
  startRow: number;
  heightCells: number;
}

export interface OperatorCardLayoutPlan {
  totalHeightCells: number;
  /** Row 0 holds the floating header and the plate's subtitle strip. */
  headerRow: 0;
  portBand: CellBand;
  plugBand: CellBand | null;
  configBand: CellBand | null;
  appendixBand: CellBand | null;
  /** Port centre, in flow units below the card's top edge, by port or plug id. */
  portYOffsets: Record<string, number>;
}

/** A cell is two dense 25px control rows. */
const DENSE_ROWS_PER_CELL = 2;

function fieldDenseRows(field: CellConfigFieldSpec): number {
  const fallback = field.kind === "multiline" ? 3 : 1;
  return Math.max(1, field.denseRows ?? fallback);
}

/**
 * Cell rows the config shelves take. Shelves are two columns wide: a
 * `span: 1` field takes one column and shares its shelf with the next field
 * when that one is `span: 1` too, the shelf as tall as the taller of the two;
 * a `span: 2` field (the default) takes a whole shelf.
 */
export function countConfigShelfCells(
  fields: readonly CellConfigFieldSpec[],
): number {
  if (fields.length === 0) return 0;
  let totalDenseRows = 0;
  let pendingHalfRows: number | null = null;
  for (const field of fields) {
    const rows = fieldDenseRows(field);
    if (field.span === 1) {
      if (pendingHalfRows === null) {
        pendingHalfRows = rows;
      } else {
        totalDenseRows += Math.max(pendingHalfRows, rows);
        pendingHalfRows = null;
      }
      continue;
    }
    if (pendingHalfRows !== null) {
      totalDenseRows += pendingHalfRows;
      pendingHalfRows = null;
    }
    totalDenseRows += rows;
  }
  if (pendingHalfRows !== null) totalDenseRows += pendingHalfRows;
  return Math.max(1, Math.ceil(totalDenseRows / DENSE_ROWS_PER_CELL));
}

function portCentreY(rowOffset: number): number {
  return (rowOffset + 0.5) * CELL_SIZE;
}

/**
 * Bands of an operator card, top to bottom: header (row 0), regular ports,
 * instance plugs, config shelves, execution appendix. The card is never
 * shorter than its bands, two cells, or the height the model already gives it.
 */
export function computeOperatorCardLayout(
  card: CellCardModel,
  surface: OperatorCardSurfaceData,
): OperatorCardLayoutPlan {
  const groups = surface.instancePlugGroups ?? [];
  const plugPortNames = groups.map((group) => group.portName);

  let maxRegularRow = 0;
  for (const port of card.ports) {
    const isPlug = plugPortNames.some(
      (name) => port.name === name || port.id.startsWith(`${name}:`),
    );
    if (isPlug) continue;
    maxRegularRow = Math.max(maxRegularRow, port.rowOffset);
  }
  const portBand: CellBand = {
    startRow: 1,
    heightCells: Math.max(0, maxRegularRow),
  };

  let plugBand: CellBand | null = null;
  if (groups.length > 0) {
    const plugStart = Math.min(...groups.map((group) => group.startRowOffset));
    const plugEnd = Math.max(
      ...groups.map(
        (group) =>
          group.startRowOffset + group.plugs.length + (group.canAdd ? 1 : 0),
      ),
    );
    plugBand = {
      startRow: plugStart,
      heightCells: Math.max(0, plugEnd - plugStart),
    };
  }

  const afterPortsAndPlugsRow = Math.max(
    1,
    portBand.startRow + portBand.heightCells,
    plugBand ? plugBand.startRow + plugBand.heightCells : 1,
  );

  const configCells = countConfigShelfCells(surface.configFields ?? []);
  const configBand: CellBand | null =
    configCells > 0
      ? { startRow: afterPortsAndPlugsRow, heightCells: configCells }
      : null;
  const afterConfigRow = configBand
    ? configBand.startRow + configBand.heightCells
    : afterPortsAndPlugsRow;

  const appendix = surface.appendix;
  const appendixBand: CellBand | null =
    appendix != null
      ? {
          startRow: afterConfigRow,
          heightCells: appendix.collapsed
            ? 1
            : Math.max(2, appendix.heightCells),
        }
      : null;
  const computedEndRow = appendixBand
    ? appendixBand.startRow + appendixBand.heightCells
    : afterConfigRow;

  const portYOffsets: Record<string, number> = {};
  for (const port of card.ports) {
    portYOffsets[port.id] = portCentreY(port.rowOffset);
  }
  for (const group of groups) {
    group.plugs.forEach((plug, index) => {
      if (portYOffsets[plug.plugId] !== undefined) return;
      portYOffsets[plug.plugId] = portCentreY(group.startRowOffset + index);
    });
  }

  return {
    totalHeightCells: Math.max(2, computedEndRow, card.heightCells),
    headerRow: 0,
    portBand,
    plugBand,
    configBand,
    appendixBand,
    portYOffsets,
  };
}

/** The hue each annotation colour mixes from: theme tokens, never a literal. */
function annotationHue(color: AnnotationColorToken): string {
  switch (color) {
    case "slate":
      return tokens.colorSubtle;
    case "blue":
      return tokens.colorInfo;
    case "emerald":
      return tokens.colorSuccess;
    case "amber":
      return tokens.colorWarning;
    case "violet":
      return `color-mix(in oklab, ${tokens.colorInfo} 55%, ${tokens.colorDanger})`;
    case "rose":
      return tokens.colorDanger;
  }
}

/**
 * Border, translucent fill and text colours of an annotation, as CSS values.
 * The fill stays see-through so a frame tints the glass under the cards
 * instead of covering it; dark mode takes a stronger tint to read on the
 * darker sheet.
 */
export function annotationColorVars(color: AnnotationColorToken): {
  border: string;
  fill: string;
  text: string;
} {
  const hue = annotationHue(color);
  return {
    border: `light-dark(color-mix(in oklab, ${hue} 45%, transparent), color-mix(in oklab, ${hue} 55%, transparent))`,
    fill: `light-dark(color-mix(in oklab, ${hue} 9%, transparent), color-mix(in oklab, ${hue} 14%, transparent))`,
    text: `light-dark(color-mix(in oklab, ${hue} 70%, ${tokens.colorText}), color-mix(in oklab, ${hue} 55%, ${tokens.colorText}))`,
  };
}
