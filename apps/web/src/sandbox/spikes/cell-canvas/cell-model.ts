/**
 * The cell canvas: every card, port and pipe snaps to a square grid.
 *
 * A cell is two product dense rows tall. A card covers a block of cells; each
 * port sits in the cell just outside its card, inputs on the left and outputs
 * on the right, one port per cell row. Every cell outside a card is gutter,
 * and a gutter cell holds {@link TRACKS_PER_CELL} pipe tracks side by side.
 *
 * This module is pure geometry and has no React or React Flow runtime import,
 * so the router and its tests run without a canvas.
 */

/** Edge of one cell, in flow units: two 25px dense rows. */
export const CELL_SIZE = 50;
/** Pipes that fit side by side through one gutter cell on one layer. */
export const TRACKS_PER_CELL = 3;
/** Distance between the centre lines of neighbouring tracks. */
export const TRACK_PITCH = 14;
/** Distance from a gutter band's edge to its outermost track. */
export const TRACK_MARGIN = 11;
/** A standard card is six cells (300px) wide. */
export const STANDARD_CARD_WIDTH_CELLS = 6;
export const CARD_PLATE_INSET_X = 4;
export const CARD_HEADER_HEIGHT = 24;
export const CARD_PLATE_TOP = 26;
export const CARD_PLATE_BOTTOM_INSET = 4;
export const CELL_CORNER_RADIUS = 12;

/**
 * The pipe contract the cell router keeps. These equal the underground-pipes
 * constants of the same meaning (`cell-router.test.ts` checks it); they are
 * repeated here so this module stays free of React Flow imports.
 */
export const CELL_PIPE_STUB_MIN = 27;
export const CELL_PIPE_LANE_MIN = 10;
export const CELL_PIPE_MAX_DEPTH = 2;

export type CellDir = "left" | "right" | "top" | "bottom";

export interface CellCoord {
  col: number;
  row: number;
}

export interface WorldPoint {
  x: number;
  y: number;
}

/** `one` carries a single artifact, `many` a list (drawn as a twin pipe). */
export type PortShape = "one" | "many";

export interface CellPort {
  id: string;
  name: string;
  direction: "input" | "output";
  /** Cell rows below the card's top row. */
  rowOffset: number;
  artifactTypeId: string;
  shape: PortShape;
  required?: boolean;
}

export interface CellCardModel {
  id: string;
  title: string;
  subtitle: string;
  status?: "idle" | "done" | "working";
  col: number;
  row: number;
  widthCells: number;
  heightCells: number;
  ports: readonly CellPort[];
}

export interface CellPipeModel {
  id: string;
  sourceCardId: string;
  sourcePortId: string;
  targetCardId: string;
  targetPortId: string;
}

export interface CellGraph {
  cards: readonly CellCardModel[];
  pipes: readonly CellPipeModel[];
}

/** `side` leaves a port along its card side; `free` may also leave up or down. */
export type CellExits = "side" | "free";

/**
 * How ground under a card is treated: `free` ignores cards, `gaps` runs under
 * one only when going round is much longer, `avoid` only when there is no
 * other way.
 */
export type UnderCardsMode = "free" | "gaps" | "avoid";

export interface CellRoutingOptions {
  exits: CellExits;
  underCards: UnderCardsMode;
  /** Sink pipes a gutter cannot hold into deeper layers. */
  depth: boolean;
}

export interface RoutedCellPipe {
  id: string;
  /** Corner points, the source port centre first and the target's last. */
  points: WorldPoint[];
  /** Every grid cell the route passes, both port cells included. */
  cellPath: CellCoord[];
  /** The way the pipe leaves its source port. */
  sourceExit: CellDir;
  /** The way the pipe leaves its target port, read backwards from the port. */
  targetExit: CellDir;
  /** 0 is just under the glass; higher layers lie deeper. */
  depth: number;
}

export interface CellRoutingResult {
  pipes: Map<string, RoutedCellPipe>;
  /** Routed pipes below layer 0. */
  deepCount: number;
  maxDepthUsed: number;
}

export function cellToWorldOrigin(col: number, row: number): WorldPoint {
  return { x: col * CELL_SIZE, y: row * CELL_SIZE };
}

export function cellCenter(col: number, row: number): WorldPoint {
  return {
    x: col * CELL_SIZE + CELL_SIZE / 2,
    y: row * CELL_SIZE + CELL_SIZE / 2,
  };
}

export function worldToCell(x: number, y: number): CellCoord {
  return { col: Math.floor(x / CELL_SIZE), row: Math.floor(y / CELL_SIZE) };
}

export function cardWorldRect(card: CellCardModel): {
  x: number;
  y: number;
  width: number;
  height: number;
} {
  return {
    x: card.col * CELL_SIZE,
    y: card.row * CELL_SIZE,
    width: card.widthCells * CELL_SIZE,
    height: card.heightCells * CELL_SIZE,
  };
}

/** The cell just outside the card that holds the port. */
export function portCell(card: CellCardModel, port: CellPort): CellCoord {
  return port.direction === "input"
    ? { col: card.col - 1, row: card.row + port.rowOffset }
    : { col: card.col + card.widthCells, row: card.row + port.rowOffset };
}

export function portSide(port: CellPort): CellDir {
  return port.direction === "input" ? "left" : "right";
}

export function portWorldCenter(
  card: CellCardModel,
  port: CellPort,
  offset?: WorldPoint,
): WorldPoint {
  const cell = portCell(card, port);
  const centre = cellCenter(cell.col, cell.row);
  if (!offset) return centre;
  return { x: centre.x + offset.x, y: centre.y + offset.y };
}

/**
 * World coordinates of `count` tracks in the gutter band of cells
 * `bandMin..bandMax` (inclusive, on the axis across the tracks).
 *
 * One track sits on the preferred cell's centre line. Several sit
 * {@link TRACK_PITCH} apart around it, slid to stay at least
 * {@link TRACK_MARGIN} inside the band; when more tracks are asked for than the
 * band holds, they squeeze evenly across it rather than leave it, so a track
 * never reaches the band's edge cells' neighbours.
 */
export function trackPositionsInBand(
  bandMin: number,
  bandMax: number,
  count: number,
  preferredCell: number,
): number[] {
  if (count <= 0) return [];
  const preferred = Math.min(Math.max(preferredCell, bandMin), bandMax);
  const centre = preferred * CELL_SIZE + CELL_SIZE / 2;
  if (count === 1) return [centre];
  const low = bandMin * CELL_SIZE + TRACK_MARGIN;
  const high = (bandMax + 1) * CELL_SIZE - TRACK_MARGIN;
  const spacing = Math.min(TRACK_PITCH, (high - low) / (count - 1));
  const span = spacing * (count - 1);
  const start = Math.min(Math.max(centre - span / 2, low), high - span);
  const tracks: number[] = [];
  for (let index = 0; index < count; index += 1) {
    tracks.push(start + index * spacing);
  }
  return tracks;
}
