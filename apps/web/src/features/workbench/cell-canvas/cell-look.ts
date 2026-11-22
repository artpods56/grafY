import type { CellGlassLook } from "./cell-glass-stage";
import type { CellRoutingOptions } from "./cell-model";

export const DEFAULT_CELL_GLASS_LOOK: CellGlassLook = {
  material: "liquid",
  well: "punched",
  pipe: "glass",
  corners: "rounded",
  stackStyle: "fan",
  blur: 3,
  frost: 0.5,
  cardFill: 0.8,
  grid: true,
};

export const DEFAULT_CELL_ROUTING: CellRoutingOptions = {
  exits: "free",
  underCards: "gaps",
  depth: true,
};
