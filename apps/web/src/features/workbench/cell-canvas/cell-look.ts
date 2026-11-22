import type {
  CellCorners,
  CellGlassLook,
  CellGlassMaterial,
  CellStackStyle,
  CellWellStyle,
} from "./cell-glass-stage";
import type {
  CellExits,
  CellRoutingOptions,
  UnderCardsMode,
} from "./cell-model";
import type { PipeFamily } from "./pipe-visuals";

export const CELL_BLUR_MIN = 0;
export const CELL_BLUR_MAX = 12;
export const CELL_FROST_MIN = 0;
export const CELL_FROST_MAX = 0.9;
export const CELL_CARD_FILL_MIN = 0.2;
export const CELL_CARD_FILL_MAX = 1;

export const DEFAULT_CELL_GLASS_LOOK: CellGlassLook = {
  material: "liquid",
  well: "recessed",
  pipe: "glass",
  corners: "rounded",
  stackStyle: "fan",
  blur: 0.3,
  frost: 0.5,
  cardFill: 0.58,
  grid: true,
};

export const DEFAULT_CELL_ROUTING: CellRoutingOptions = {
  exits: "side",
  underCards: "gaps",
  depth: true,
};

function isMaterial(value: unknown): value is CellGlassMaterial {
  return value === "frost" || value === "liquid";
}

function isWellStyle(value: unknown): value is CellWellStyle {
  return value === "recessed" || value === "flat" || value === "punched";
}

function isPipeFamily(value: unknown): value is PipeFamily {
  return value === "glass" || value === "fibre";
}

function isCorners(value: unknown): value is CellCorners {
  return value === "rounded" || value === "sharp";
}

function isStackStyle(value: unknown): value is CellStackStyle {
  return value === "fan" || value === "deck";
}

function isExits(value: unknown): value is CellExits {
  return value === "side" || value === "free";
}

function isUnderCards(value: unknown): value is UnderCardsMode {
  return value === "free" || value === "gaps" || value === "avoid";
}

function clampNumber(
  value: unknown,
  min: number,
  max: number,
  fallback: number,
): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return fallback;
  return Math.max(min, Math.min(max, value));
}

export function normalizeCellGlassLook(
  input?: Partial<CellGlassLook> | null,
): CellGlassLook {
  if (!input || typeof input !== "object")
    return { ...DEFAULT_CELL_GLASS_LOOK };
  return {
    material: isMaterial(input.material)
      ? input.material
      : DEFAULT_CELL_GLASS_LOOK.material,
    well: isWellStyle(input.well) ? input.well : DEFAULT_CELL_GLASS_LOOK.well,
    pipe: isPipeFamily(input.pipe) ? input.pipe : DEFAULT_CELL_GLASS_LOOK.pipe,
    corners: isCorners(input.corners)
      ? input.corners
      : DEFAULT_CELL_GLASS_LOOK.corners,
    stackStyle: isStackStyle(input.stackStyle)
      ? input.stackStyle
      : DEFAULT_CELL_GLASS_LOOK.stackStyle,
    blur: clampNumber(
      input.blur,
      CELL_BLUR_MIN,
      CELL_BLUR_MAX,
      DEFAULT_CELL_GLASS_LOOK.blur,
    ),
    frost: clampNumber(
      input.frost,
      CELL_FROST_MIN,
      CELL_FROST_MAX,
      DEFAULT_CELL_GLASS_LOOK.frost,
    ),
    cardFill: clampNumber(
      input.cardFill,
      CELL_CARD_FILL_MIN,
      CELL_CARD_FILL_MAX,
      DEFAULT_CELL_GLASS_LOOK.cardFill,
    ),
    grid:
      typeof input.grid === "boolean"
        ? input.grid
        : DEFAULT_CELL_GLASS_LOOK.grid,
  };
}

export function normalizeCellRouting(
  input?: Partial<CellRoutingOptions> | null,
): CellRoutingOptions {
  if (!input || typeof input !== "object") return { ...DEFAULT_CELL_ROUTING };
  return {
    exits: isExits(input.exits) ? input.exits : DEFAULT_CELL_ROUTING.exits,
    underCards: isUnderCards(input.underCards)
      ? input.underCards
      : DEFAULT_CELL_ROUTING.underCards,
    depth:
      typeof input.depth === "boolean"
        ? input.depth
        : DEFAULT_CELL_ROUTING.depth,
  };
}
