import { tokens } from "@/lib/stylex/tokens.stylex";

import type {
  AnnotationColorToken,
  CellConfigFieldSpec,
  CellInstancePlugGroup,
  OperatorCardSurfaceData,
} from "./cell-contracts";
import { placeShelves, type ShelfPlacement } from "./cell-config-plan";
import {
  CELL_SIZE,
  FIRST_PORT_ROW,
  PORT_ROW_PITCH,
  type CellCardModel,
} from "./cell-model";

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
  /** Rows 0 and 1 hold the floating header and the plate's rounded top. */
  headerRow: 0;
  portBand: CellBand;
  plugBand: CellBand | null;
  configBand: CellBand | null;
  appendixBand: CellBand | null;
  /** Port centre, in flow units below the card's top edge, by port or plug id. */
  portYOffsets: Record<string, number>;
}

/** The empty cell row between two bands, and under the last one. */
const BAND_GAP_CELLS = 1;
/** An expanded appendix is never shorter than its header and two lines, except single-output cards which take three cells. */
const APPENDIX_MIN_CELLS = 4;
const APPENDIX_SINGLE_OUTPUT_MIN_CELLS = 3;
/** A collapsed appendix is its 24px header with the plate's bottom inset under it. */
const APPENDIX_COLLAPSED_CELLS = 2;

/** The row of plug `index` in its group, one port pitch below the one before. */
export function plugRowOffset(
  group: Pick<CellInstancePlugGroup, "startRowOffset">,
  index: number,
): number {
  return group.startRowOffset + index * PORT_ROW_PITCH;
}

export function fieldDenseRows(field: CellConfigFieldSpec): number {
  const fallback = field.kind === "multiline" ? 3 : 1;
  return Math.max(1, field.denseRows ?? fallback);
}

/**
 * Where each config field sits on the band's two-column shelves, in dense
 * rows from the band's top. A cell is one dense 25px row, so rows are cells.
 */
export function configShelfPlacements(fields: readonly CellConfigFieldSpec[]): {
  placements: ShelfPlacement[];
  totalRows: number;
} {
  return placeShelves(
    fields.map((field) => ({
      span: field.span === 1 ? 1 : 2,
      rows: fieldDenseRows(field),
    })),
  );
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
  return Math.max(1, configShelfPlacements(fields).totalRows);
}

function portCentreY(rowOffset: number): number {
  return (rowOffset + 0.5) * CELL_SIZE;
}

/**
 * Bands of an operator card, top to bottom: header (rows 0 and 1, over the
 * plate's rounded top), regular ports, instance plugs, config shelves,
 * execution appendix. Ports and plugs sit {@link PORT_ROW_PITCH} rows apart
 * and one empty row separates each band from the next; the last band but an
 * appendix gets one empty row under it, so the plate's bottom inset never
 * clips a control. The card is never shorter than its bands, two cells, or
 * the height the model already gives it.
 */
export function computeOperatorCardLayout(
  card: CellCardModel,
  surface: OperatorCardSurfaceData,
): OperatorCardLayoutPlan {
  const groups = surface.instancePlugGroups ?? [];
  const plugPortNames = groups.map((group) => group.portName);

  let lastRegularRow: number | null = null;
  for (const port of card.ports) {
    const isPlug = plugPortNames.some(
      (name) => port.name === name || port.id.startsWith(`${name}:`),
    );
    if (isPlug) continue;
    lastRegularRow = Math.max(lastRegularRow ?? 0, port.rowOffset);
  }
  const portBand: CellBand = {
    startRow: FIRST_PORT_ROW,
    heightCells:
      lastRegularRow === null
        ? 0
        : Math.max(0, lastRegularRow + 1 - FIRST_PORT_ROW),
  };

  let plugBand: CellBand | null = null;
  if (groups.length > 0) {
    const plugStart = Math.min(...groups.map((group) => group.startRowOffset));
    const plugEnd = Math.max(
      ...groups.map((group) => {
        const rows = group.plugs.length + (group.canAdd ? 1 : 0);
        return rows > 0
          ? plugRowOffset(group, rows - 1) + 1
          : group.startRowOffset;
      }),
    );
    plugBand = {
      startRow: plugStart,
      heightCells: Math.max(0, plugEnd - plugStart),
    };
  }

  const bandEnds = [portBand, plugBand]
    .filter((band): band is CellBand => band !== null && band.heightCells > 0)
    .map((band) => band.startRow + band.heightCells + BAND_GAP_CELLS);
  const afterPortsAndPlugsRow = Math.max(FIRST_PORT_ROW, ...bandEnds);

  const configCells = countConfigShelfCells(surface.configFields ?? []);
  const configBand: CellBand | null =
    configCells > 0
      ? { startRow: afterPortsAndPlugsRow, heightCells: configCells }
      : null;
  const afterConfigRow = configBand
    ? configBand.startRow + configBand.heightCells
    : afterPortsAndPlugsRow;

  const appendix = surface.appendix;
  const appendixMinCells =
    appendix != null &&
    appendix.kind !== "error" &&
    (appendix.outputs?.length ?? 0) === 1
      ? APPENDIX_SINGLE_OUTPUT_MIN_CELLS
      : APPENDIX_MIN_CELLS;
  const appendixBand: CellBand | null =
    appendix != null
      ? {
          startRow: afterConfigRow,
          heightCells: appendix.collapsed
            ? APPENDIX_COLLAPSED_CELLS
            : Math.max(appendixMinCells, appendix.heightCells),
        }
      : null;
  const computedEndRow = appendixBand
    ? appendixBand.startRow + appendixBand.heightCells
    : configBand
      ? afterConfigRow + BAND_GAP_CELLS
      : afterPortsAndPlugsRow;

  const portYOffsets: Record<string, number> = {};
  for (const port of card.ports) {
    portYOffsets[port.id] = portCentreY(port.rowOffset);
  }
  for (const group of groups) {
    group.plugs.forEach((plug, index) => {
      if (portYOffsets[plug.plugId] !== undefined) return;
      portYOffsets[plug.plugId] = portCentreY(plugRowOffset(group, index));
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
