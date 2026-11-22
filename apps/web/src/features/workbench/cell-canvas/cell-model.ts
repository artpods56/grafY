/**
 * The cell canvas: every card, port and pipe snaps to a square grid.
 *
 * A cell is one product dense row (25px) tall. A card covers a block of cells;
 * each port sits in the cell just outside its card, inputs on the left and
 * outputs on the right, ports {@link PORT_ROW_PITCH} cell rows apart. Every
 * cell outside a card is gutter, and a gutter cell holds
 * {@link TRACKS_PER_CELL} pipe tracks side by side.
 *
 * This module is pure geometry and has no React or React Flow runtime import,
 * so the router and its tests run without a canvas.
 */

/** Edge of one cell, in flow units: one 25px dense row. */
export const CELL_SIZE = 25;
/** Pipes that fit side by side through one gutter cell on one layer. */
export const TRACKS_PER_CELL = 1;
/** Distance between the centre lines of neighbouring tracks. */
export const TRACK_PITCH = 14;
/** Distance from a gutter band's edge to its outermost track. */
export const TRACK_MARGIN = 6;
/** A standard card is twelve cells (300px) wide. */
export const STANDARD_CARD_WIDTH_CELLS = 12;
/**
 * Cell rows from one port to the next: a 22px port tab and its well fill one
 * cell, and the empty cell between two ports keeps their wells and pipes apart.
 */
export const PORT_ROW_PITCH = 2;
/**
 * The first port's row on an operator card. Row 0 holds the floating title
 * (0..24) and row 1 holds the plate's rounded top (26..50); row 2's tab
 * clears the 12px corner cleanly.
 */
export const FIRST_PORT_ROW = 2;
/**
 * The first port row on a card that opens its plate with a 23px strip
 * (artifact, collection, agent, the demo card): the strip runs 26..50, ending
 * right on row 2's upper edge.
 */
export const STRIP_FIRST_PORT_ROW = 2;
/** The artifact card's output port id. */
export const ARTIFACT_CARD_OUTPUT_PORT_ID = "artifact-card-output";
/**
 * The artifact card's output row: on the bottom-right corner, one row clear
 * of the plate's lower edge so its punched well keeps the 12px corner.
 */
export function artifactCardOutputRow(heightCells: number): number {
  return Math.max(STRIP_FIRST_PORT_ROW, heightCells - 2);
}

export const CARD_PLATE_INSET_X = 4;
export const CARD_HEADER_HEIGHT = 24;
export const CARD_PLATE_BOTTOM_INSET = 4;
export const CELL_CORNER_RADIUS = 12;
/**
 * Every card's plate starts here, whatever its kind, so cards side by side
 * line up and cards stacked with no row between them keep a tight 6px gap
 * from one plate to the next title.
 */
export const CARD_PLATE_TOP = 26;
/** The floating title sits at the top of row 0 (0..24), 2px over the plate. */
export const CARD_HEADER_TOP = 0;

/**
 * The pipe contract the cell router keeps. A pipe's stub runs from its port
 * cell's centre to its first bend; the shortest one the router lays leaves a
 * 25px port cell for the next cell's track, which sits at least
 * {@link TRACK_MARGIN} inside that cell: `CELL_SIZE / 2 + TRACK_MARGIN` =
 * 18.5. The minimum sits just under it, so every routed stub keeps it and a
 * 12px bend still fits on it.
 */
export const CELL_PIPE_STUB_MIN = 18;
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

export type CellCardKind =
  "operator" | "artifact" | "collection" | "annotation" | "agent";

export interface CellResizeBounds {
  minWidthCells: number;
  maxWidthCells?: number;
  minHeightCells: number;
  maxHeightCells?: number;
}

export interface CellRect {
  col: number;
  row: number;
  widthCells: number;
  heightCells: number;
}

export interface CellPort {
  id: string;
  name: string;
  direction: "input" | "output";
  /** Cell rows below the card's top row. */
  rowOffset: number;
  artifactTypeId: string;
  shape: PortShape;
  required?: boolean;
  kind?: "artifact" | "service";
  serviceContractLabel?: string;
}

export interface CellCardModel {
  id: string;
  title: string;
  subtitle: string;
  kind?: CellCardKind;
  status?: "idle" | "done" | "working" | "error";
  col: number;
  row: number;
  widthCells: number;
  heightCells: number;
  ports: readonly CellPort[];
  resizable?: boolean;
  resizeBounds?: CellResizeBounds;
}

export interface CellPipeModel {
  id: string;
  sourceCardId: string;
  sourcePortId: string;
  targetCardId: string;
  targetPortId: string;
  projectionLabel?: string | null;
  conversionLabel?: string | null;
  enabled?: boolean;
  collectionMode?: "direct" | "map";
  /** Port label fallback shown on hover/selection when no projection/conversion label exists. */
  sourcePortLabel?: string;
  incompatible?: boolean;
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

export function cardCellRect(card: CellCardModel): CellRect {
  return {
    col: card.col,
    row: card.row,
    widthCells: card.widthCells,
    heightCells: card.heightCells,
  };
}

/**
 * A port's identity on its card. An operator may name an input and an output
 * alike (`image` in, `image` out), so the bare id is not unique on a card.
 */
export function cellPortKey(
  direction: CellPort["direction"],
  portId: string,
): string {
  return `${direction}:${portId}`;
}

/**
 * Whether a pipe holds the port. The canvas marks `cellPortKey`s; a bare id
 * still counts, for a caller that has only one port of that name.
 */
export function isPortConnected(
  connectedPortIds: ReadonlySet<string>,
  port: CellPort,
): boolean {
  return (
    connectedPortIds.has(cellPortKey(port.direction, port.id)) ||
    connectedPortIds.has(port.id)
  );
}

/** Whether a connection drag is over this port (`${cardId}:${cellPortKey}`). */
export function isPortActive(
  activePortKey: string | null | undefined,
  cardId: string,
  port: CellPort,
): boolean {
  if (!activePortKey) return false;
  return (
    activePortKey === `${cardId}:${cellPortKey(port.direction, port.id)}` ||
    activePortKey === `${cardId}:${port.id}`
  );
}

/**
 * The port a pipe end names: the one on the pipe's side of the card, else
 * (for a fixture that leaves direction out) the first with that id.
 */
export function findPipeEndPort(
  ports: readonly CellPort[],
  portId: string,
  direction: CellPort["direction"],
): CellPort | undefined {
  let fallback: CellPort | undefined;
  for (const port of ports) {
    if (port.id !== portId) continue;
    if (port.direction === direction) return port;
    fallback ??= port;
  }
  return fallback;
}

/** The cell just outside the card that holds the port. */
export function portCell(card: CellCardModel, port: CellPort): CellCoord {
  return port.direction === "input"
    ? { col: card.col - 1, row: card.row + port.rowOffset }
    : { col: card.col + card.widthCells, row: card.row + port.rowOffset };
}

/** The port row of a collection's `index`th member, or of its spare slot. */
export function collectionRowOffset(index: number): number {
  return STRIP_FIRST_PORT_ROW + index * PORT_ROW_PITCH;
}

/**
 * Cells a collection card needs for `rows` member rows (its spare slot
 * included): two header/strip rows (0..50), then two cells per row.
 */
export function collectionHeightCells(rows: number): number {
  return STRIP_FIRST_PORT_ROW + Math.max(1, rows) * PORT_ROW_PITCH;
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
 * Punched wells: a port sits inside its card's plate, this far in from the
 * card's outer edge, like a hole drilled through the card down to the pipe
 * bed. Its 11px well (and a liquid well's sheen) keeps a clear band of plate
 * between it and the plate's 4px inset edge.
 */
export const PUNCHED_PORT_INSET = 22;

/**
 * A punched port's centre relative to the card's outer origin: the single
 * source of truth for the hole the card draws, the hit test, and the pipe's
 * lead-in. A port sits `PUNCHED_PORT_INSET` in from its side, on its row's
 * midline, except the artifact card's output, which is pinned to the
 * bottom-right corner the same inset in from both edges (18px inside the 4px
 * plate border on each), so its two gaps match.
 */
export function punchedPortCardCentre(
  card: Pick<CellCardModel, "widthCells" | "heightCells">,
  port: Pick<CellPort, "id" | "direction" | "rowOffset">,
): WorldPoint {
  const width = card.widthCells * CELL_SIZE;
  if (port.id === ARTIFACT_CARD_OUTPUT_PORT_ID) {
    return {
      x: width - PUNCHED_PORT_INSET,
      y: card.heightCells * CELL_SIZE - PUNCHED_PORT_INSET,
    };
  }
  return {
    x:
      port.direction === "input"
        ? PUNCHED_PORT_INSET
        : width - PUNCHED_PORT_INSET,
    y: (port.rowOffset + 0.5) * CELL_SIZE,
  };
}

/** A punched port's centre in world coordinates. */
export function punchedPortWorldCenter(
  card: CellCardModel,
  port: CellPort,
  offset?: WorldPoint,
): WorldPoint {
  const local = punchedPortCardCentre(card, port);
  return {
    x: card.col * CELL_SIZE + local.x + (offset?.x ?? 0),
    y: card.row * CELL_SIZE + local.y + (offset?.y ?? 0),
  };
}

/** Where a pipe meets the port: its gutter cell, or its punched hole. */
export function portAnchorCenter(
  card: CellCardModel,
  port: CellPort,
  punched: boolean,
  offset?: WorldPoint,
): WorldPoint {
  return punched
    ? punchedPortWorldCenter(card, port, offset)
    : portWorldCenter(card, port, offset);
}

function sameRow(a: WorldPoint, b: WorldPoint): boolean {
  return Math.abs(a.y - b.y) < 0.5;
}

function sameColumn(a: WorldPoint, b: WorldPoint): boolean {
  return Math.abs(a.x - b.x) < 0.5;
}

/**
 * Carries the route's start on into `anchor`, horizontally. `route` is
 * changed in place and always keeps at least its first point's gutter column.
 *
 * - Leaving sideways on the anchor's row, the first run just grows.
 * - Leaving sideways off the anchor's row (the artifact output's corner hole
 *   sits below its gutter row) into a vertical turn, the whole first run slides
 *   onto the anchor's row and the turn absorbs the difference.
 * - Leaving sideways with no turn to absorb it, the run gains a step in the
 *   gutter column, outside the card.
 * - Leaving up or down, the vertical run stretches to the anchor's row and a
 *   horizontal lead-in joins it.
 */
function leadIntoAnchor(route: WorldPoint[], anchor: WorldPoint): void {
  const first = route[0];
  const second = route[1];
  if (!first || !second) return;
  if (sameRow(first, second)) {
    if (sameRow(first, anchor)) {
      route[0] = { ...anchor };
      return;
    }
    const third = route[2];
    if (third && sameColumn(second, third)) {
      route[0] = { ...anchor };
      route[1] = { x: second.x, y: anchor.y };
      return;
    }
    route.unshift({ ...anchor }, { x: first.x, y: anchor.y });
    return;
  }
  if (sameColumn(first, second)) {
    route[0] = { x: first.x, y: anchor.y };
  }
  route.unshift({ ...anchor });
}

/**
 * A pipe routed between gutter cells, carried on into the punched holes. The
 * router's route is kept; each end runs straight on, horizontally, under the
 * card's edge to the hole's centre, so no segment turns inside a card's plate.
 * See {@link leadIntoAnchor} for how an end meets a hole off its gutter row.
 */
export function punchedPipePoints(
  points: readonly WorldPoint[],
  source: WorldPoint,
  target: WorldPoint,
): WorldPoint[] {
  if (points.length < 2) return [{ ...source }, { ...target }];
  const result = points.map((point) => ({ ...point }));
  leadIntoAnchor(result, source);
  result.reverse();
  leadIntoAnchor(result, target);
  result.reverse();
  return result;
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
