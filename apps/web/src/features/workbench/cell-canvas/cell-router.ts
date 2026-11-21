import {
  CELL_PIPE_MAX_DEPTH,
  CELL_PIPE_STUB_MIN,
  CELL_SIZE,
  TRACKS_PER_CELL,
  TRACK_MARGIN,
  cellCenter,
  portCell,
  portSide,
  trackPositionsInBand,
  type CellCardModel,
  type CellCoord,
  type CellDir,
  type CellGraph,
  type CellPipeModel,
  type CellRoutingOptions,
  type CellRoutingResult,
  type RoutedCellPipe,
  type UnderCardsMode,
  type WorldPoint,
} from "./cell-model";

/**
 * Routes every pipe of a cell graph in two stages.
 *
 * Stage 1 finds each pipe's cheapest run of cells on its own: an A* search
 * over (cell, heading) states, where a bend, a card's ground and another
 * card's port cell all cost extra. Pipes do not see one another here.
 *
 * Stage 2 spreads the pipes that share a gutter into tracks. Every segment
 * between the two port stubs may slide across its gutter band, the run of
 * plain gutter cells it could lie in without crossing a card, a port or its
 * own neighbouring bends. Segments that share a band and overlap along it form
 * a corridor of `band width × TRACKS_PER_CELL` tracks; when a corridor holds
 * more pipes than that, pipes passing through it sink to a deeper layer.
 *
 * The router is pure: it keeps nothing between calls, so the same graph and
 * options always give the same layout.
 */

const CELL_CARD = 1;
const CELL_PORT = 2;
/** Free cells kept around the graph so a pipe can always go round it. */
const GRID_PADDING = 4;
/** A bend costs as much as this many cells of straight run. */
const BEND_COST = 1.6;
/** Entering another port's cell: only when every other way is boxed in. */
const OTHER_PORT_COST = 200;
const CARD_PENALTY: Readonly<Record<UnderCardsMode, number>> = {
  free: 0,
  gaps: 6,
  avoid: 120,
};
/** Breaks ties between equal-cost states toward the goal. */
const HEURISTIC_TIE_BREAK = 1 + 1e-6;
/** A port this close to a crowded stretch keeps its pipe near the surface. */
const BOTTLENECK_REACH = 2 * CELL_SIZE;
/** A pipe clearing a crowded stretch by this much on both sides sinks first. */
const CLEAR_PASS = 2 * CELL_SIZE;

/** Headings by index; `index ^ 1` is the reverse heading. */
const DIR_NAMES: readonly CellDir[] = ["right", "left", "bottom", "top"];
const DX: readonly number[] = [1, -1, 0, 0];
const DY: readonly number[] = [0, 0, 1, -1];

function dirIndex(dir: CellDir): number {
  return DIR_NAMES.indexOf(dir);
}

/** The heading of the single step between two neighbouring cells. */
function stepDir(from: CellCoord, to: CellCoord): number {
  if (to.col > from.col) return 0;
  if (to.col < from.col) return 1;
  return to.row > from.row ? 2 : 3;
}

// ---------------------------------------------------------------------------
// Occupancy grid

interface Grid {
  minCol: number;
  minRow: number;
  cols: number;
  rows: number;
  /** Per cell: CELL_CARD and CELL_PORT bits; 0 is plain gutter. */
  flags: Uint8Array;
}

function cardPortCells(card: CellCardModel): CellCoord[] {
  return card.ports.map((port) => portCell(card, port));
}

function buildGrid(cards: readonly CellCardModel[]): Grid {
  let minCol = 0;
  let maxCol = 0;
  let minRow = 0;
  let maxRow = 0;
  let first = true;
  const include = (col: number, row: number) => {
    if (first) {
      [minCol, maxCol, minRow, maxRow] = [col, col, row, row];
      first = false;
      return;
    }
    minCol = Math.min(minCol, col);
    maxCol = Math.max(maxCol, col);
    minRow = Math.min(minRow, row);
    maxRow = Math.max(maxRow, row);
  };
  for (const card of cards) {
    include(card.col, card.row);
    include(card.col + card.widthCells - 1, card.row + card.heightCells - 1);
    for (const cell of cardPortCells(card)) include(cell.col, cell.row);
  }
  minCol -= GRID_PADDING;
  minRow -= GRID_PADDING;
  const cols = maxCol + GRID_PADDING - minCol + 1;
  const rows = maxRow + GRID_PADDING - minRow + 1;
  const grid: Grid = {
    minCol,
    minRow,
    cols,
    rows,
    flags: new Uint8Array(cols * rows),
  };
  for (const card of cards) {
    for (let row = card.row; row < card.row + card.heightCells; row += 1) {
      for (let col = card.col; col < card.col + card.widthCells; col += 1) {
        const index = cellIndex(grid, col, row);
        if (index >= 0)
          grid.flags[index] = (grid.flags[index] ?? 0) | CELL_CARD;
      }
    }
  }
  for (const card of cards) {
    for (const cell of cardPortCells(card)) {
      const index = cellIndex(grid, cell.col, cell.row);
      if (index >= 0) grid.flags[index] = (grid.flags[index] ?? 0) | CELL_PORT;
    }
  }
  return grid;
}

/** The cell's index in the grid, or -1 outside it. */
function cellIndex(grid: Grid, col: number, row: number): number {
  const c = col - grid.minCol;
  const r = row - grid.minRow;
  if (c < 0 || r < 0 || c >= grid.cols || r >= grid.rows) return -1;
  return r * grid.cols + c;
}

function indexCell(grid: Grid, index: number): CellCoord {
  const c = index % grid.cols;
  return { col: c + grid.minCol, row: (index - c) / grid.cols + grid.minRow };
}

// ---------------------------------------------------------------------------
// Stage 1: A* over (cell, heading)

/** A binary min-heap of search states keyed by estimated total cost. */
interface Heap {
  states: number[];
  keys: number[];
}

function heapPush(heap: Heap, state: number, key: number): void {
  const { states, keys } = heap;
  let index = states.length;
  states.push(state);
  keys.push(key);
  while (index > 0) {
    const parent = (index - 1) >> 1;
    const parentKey = keys[parent] ?? 0;
    if (parentKey <= key) break;
    states[index] = states[parent] ?? 0;
    keys[index] = parentKey;
    index = parent;
  }
  states[index] = state;
  keys[index] = key;
}

function heapPop(heap: Heap): number {
  const { states, keys } = heap;
  const top = states[0] ?? -1;
  const lastState = states.pop();
  const lastKey = keys.pop();
  if (states.length === 0 || lastState === undefined || lastKey === undefined) {
    return top;
  }
  const size = states.length;
  let index = 0;
  for (;;) {
    const left = index * 2 + 1;
    if (left >= size) break;
    const right = left + 1;
    const leftKey = keys[left] ?? Infinity;
    const rightKey = right < size ? (keys[right] ?? Infinity) : Infinity;
    const child = rightKey < leftKey ? right : left;
    const childKey = Math.min(leftKey, rightKey);
    if (childKey >= lastKey) break;
    states[index] = states[child] ?? 0;
    keys[index] = childKey;
    index = child;
  }
  states[index] = lastState;
  keys[index] = lastKey;
  return top;
}

/** Search buffers, allocated once per routing call and reused per pipe. */
interface Search {
  grid: Grid;
  cardPenalty: number;
  cost: Float64Array;
  parent: Int32Array;
  /** The pipe generation that last wrote `cost`/`parent` for a state. */
  seen: Uint32Array;
  closed: Uint32Array;
  heap: Heap;
  generation: number;
}

function createSearch(grid: Grid, options: CellRoutingOptions): Search {
  const states = grid.cols * grid.rows * 4;
  return {
    grid,
    cardPenalty: CARD_PENALTY[options.underCards],
    cost: new Float64Array(states),
    parent: new Int32Array(states),
    seen: new Uint32Array(states),
    closed: new Uint32Array(states),
    heap: { states: [], keys: [] },
    generation: 0,
  };
}

/**
 * A lower bound on the bends left from heading `dir` with the goal `dc, dr`
 * cells away, given the headings the goal may be entered with.
 */
function minBends(
  dir: number,
  dc: number,
  dr: number,
  arrival: number,
): number {
  if (dc === 0 && dr === 0) return 0;
  const dx = DX[dir] ?? 0;
  const dy = DY[dir] ?? 0;
  const ahead = dc * dx + dr * dy;
  const aside = dx !== 0 ? dr : dc;
  if (aside === 0) {
    if (ahead > 0) return (arrival >> dir) & 1 ? 0 : 2;
    return 2;
  }
  return ahead < 0 ? 2 : 1;
}

/**
 * The cheapest run of cells from `start` to `goal`, both included, whose first
 * step heads one of `firstDirs` and whose last step one of the `arrival` bits.
 */
function findCellPath(
  search: Search,
  start: CellCoord,
  goal: CellCoord,
  firstDirs: readonly number[],
  arrival: number,
): CellCoord[] | null {
  const { grid, cost, parent, seen, closed, heap } = search;
  const { cols, rows, flags } = grid;
  const startIndex = cellIndex(grid, start.col, start.row);
  const goalIndex = cellIndex(grid, goal.col, goal.row);
  if (startIndex < 0 || goalIndex < 0) return null;
  search.generation += 1;
  const generation = search.generation;
  heap.states.length = 0;
  heap.keys.length = 0;
  const goalC = goalIndex % cols;
  const goalR = (goalIndex - goalC) / cols;

  const neighbour = (index: number, dir: number): number => {
    const c = (index % cols) + (DX[dir] ?? 0);
    const r = Math.floor(index / cols) + (DY[dir] ?? 0);
    if (c < 0 || r < 0 || c >= cols || r >= rows) return -1;
    return r * cols + c;
  };
  const terrain = (index: number): number => {
    if (index === goalIndex) return 1;
    const flag = flags[index] ?? 0;
    if (flag & CELL_PORT) return OTHER_PORT_COST;
    if (flag & CELL_CARD) return 1 + search.cardPenalty;
    return 1;
  };
  const relax = (state: number, total: number, from: number) => {
    if (seen[state] === generation && total >= (cost[state] ?? 0)) return;
    seen[state] = generation;
    cost[state] = total;
    parent[state] = from;
    const index = state >> 2;
    const c = index % cols;
    const r = (index - c) / cols;
    const dc = goalC - c;
    const dr = goalR - r;
    const estimate =
      Math.abs(dc) +
      Math.abs(dr) +
      minBends(state & 3, dc, dr, arrival) * BEND_COST;
    heapPush(heap, state, total + estimate * HEURISTIC_TIE_BREAK);
  };

  for (const dir of firstDirs) {
    const next = neighbour(startIndex, dir);
    if (next < 0) continue;
    if (next === goalIndex && !((arrival >> dir) & 1)) continue;
    relax(next * 4 + dir, terrain(next), -1);
  }

  while (heap.states.length > 0) {
    const state = heapPop(heap);
    if (closed[state] === generation) continue;
    closed[state] = generation;
    const index = state >> 2;
    const dir = state & 3;
    if (index === goalIndex) return tracePath(search, state, start);
    const here = cost[state] ?? 0;
    for (let next = 0; next < 4; next += 1) {
      if (next === (dir ^ 1)) continue;
      const to = neighbour(index, next);
      if (to < 0 || to === startIndex) continue;
      if (to === goalIndex && !((arrival >> next) & 1)) continue;
      const bend = next === dir ? 0 : BEND_COST;
      relax(to * 4 + next, here + terrain(to) + bend, state);
    }
  }
  return null;
}

function tracePath(
  search: Search,
  goalState: number,
  start: CellCoord,
): CellCoord[] {
  const cells: CellCoord[] = [];
  for (let state = goalState; state >= 0; state = search.parent[state] ?? -1) {
    cells.push(indexCell(search.grid, state >> 2));
  }
  cells.push(start);
  return cells.reverse();
}

/** The cells where the route turns, with both ends. */
function cornersOf(cells: readonly CellCoord[]): CellCoord[] {
  const corners: CellCoord[] = [];
  for (const [index, cell] of cells.entries()) {
    const before = cells[index - 1];
    const after = cells[index + 1];
    if (!before || !after || stepDir(before, cell) !== stepDir(cell, after)) {
      corners.push(cell);
    }
  }
  return corners;
}

// ---------------------------------------------------------------------------
// Stage 2: gutter bands, corridors, depth and tracks

interface Work {
  id: string;
  cells: CellCoord[];
  corners: CellCoord[];
  /** Corner points, moved in place as segments take their tracks. */
  points: WorldPoint[];
  depth: number;
  /** Manhattan length in cells, so the longest pipes sink first. */
  length: number;
}

/** A segment between the two stubs, free to slide across its band. */
interface Segment {
  work: Work;
  /** Its index among the route's segments: corner `index` to `index + 1`. */
  index: number;
  /** Vertical segments sit at a column and slide along x. */
  vertical: boolean;
  /** Its cell column (vertical) or row (horizontal) as routed. */
  line: number;
  /** World extent along the segment, between its corner cell centres. */
  low: number;
  high: number;
  bandMin: number;
  bandMax: number;
  /** Which way the pipe turns at the low and high end: -1 or 1. */
  lowTurn: number;
  highTurn: number;
}

/** True when every cell of the line between `low` and `high` is gutter. */
function isGutterLine(
  grid: Grid,
  vertical: boolean,
  line: number,
  low: number,
  high: number,
): boolean {
  for (let along = low; along <= high; along += 1) {
    const index = vertical
      ? cellIndex(grid, line, along)
      : cellIndex(grid, along, line);
    if (index < 0 || grid.flags[index] !== 0) return false;
  }
  return true;
}

function perp(cell: CellCoord, vertical: boolean): number {
  return vertical ? cell.col : cell.row;
}

function along(cell: CellCoord, vertical: boolean): number {
  return vertical ? cell.row : cell.col;
}

/**
 * The movable segment `index` of a route with its gutter band: the lines it
 * may take without leaving plain gutter, and without reaching the line of
 * either neighbouring bend's far corner, which keeps both neighbouring
 * segments (stubs included) at least a cell long.
 */
function movableSegment(grid: Grid, work: Work, index: number): Segment | null {
  const { corners } = work;
  const start = corners[index];
  const end = corners[index + 1];
  if (!start || !end) return null;
  const vertical = start.col === end.col;
  const line = perp(start, vertical);
  const from = along(start, vertical);
  const to = along(end, vertical);
  const low = Math.min(from, to);
  const high = Math.max(from, to);

  let floor = -Infinity;
  let ceiling = Infinity;
  for (const neighbour of [corners[index - 1], corners[index + 2]]) {
    if (!neighbour) continue;
    const position = perp(neighbour, vertical);
    if (position < line) floor = Math.max(floor, position + 1);
    else ceiling = Math.min(ceiling, position - 1);
  }

  let bandMin = line;
  let bandMax = line;
  if (isGutterLine(grid, vertical, line, low, high)) {
    while (
      bandMin - 1 >= floor &&
      isGutterLine(grid, vertical, bandMin - 1, low, high)
    ) {
      bandMin -= 1;
    }
    while (
      bandMax + 1 <= ceiling &&
      isGutterLine(grid, vertical, bandMax + 1, low, high)
    ) {
      bandMax += 1;
    }
  }

  const before = corners[index - 1];
  const after = corners[index + 2];
  const startTurn = before ? Math.sign(perp(before, vertical) - line) : 0;
  const endTurn = after ? Math.sign(perp(after, vertical) - line) : 0;
  const startIsLow = from < to;
  return {
    work,
    index,
    vertical,
    line,
    low: low * CELL_SIZE + CELL_SIZE / 2,
    high: high * CELL_SIZE + CELL_SIZE / 2,
    bandMin,
    bandMax,
    lowTurn: startIsLow ? startTurn : endTurn,
    highTurn: startIsLow ? endTurn : startTurn,
  };
}

function overlapsAlong(a: Segment, b: Segment): boolean {
  return Math.min(a.high, b.high) - Math.max(a.low, b.low) > 0.5;
}

/**
 * Groups of segments on the same axis that lie within a cell of each other in
 * overlapping bands and overlap along them.
 */
function corridors(segments: readonly Segment[]): Segment[][] {
  const order = segments
    .map((_, index) => index)
    .sort(
      (a, b) =>
        (segments[a]?.bandMin ?? 0) - (segments[b]?.bandMin ?? 0) ||
        (segments[a]?.line ?? 0) - (segments[b]?.line ?? 0) ||
        a - b,
    );
  const parent = segments.map((_, index) => index);
  const root = (index: number): number => {
    let current = index;
    while (parent[current] !== current) current = parent[current] ?? current;
    return current;
  };
  for (let rank = 0; rank < order.length; rank += 1) {
    const a = order[rank] ?? 0;
    const left = segments[a];
    if (!left) continue;
    for (let next = rank + 1; next < order.length; next += 1) {
      const b = order[next] ?? 0;
      const right = segments[b];
      if (!right) continue;
      if (right.bandMin > left.bandMax) break;
      if (Math.abs(right.line - left.line) > 1) continue;
      if (overlapsAlong(left, right)) parent[root(a)] = root(b);
    }
  }
  const groups = new Map<number, Segment[]>();
  for (const [index, segment] of segments.entries()) {
    const key = root(index);
    const group = groups.get(key) ?? [];
    group.push(segment);
    groups.set(key, group);
  }
  return [...groups.values()];
}

/** The band every member shares, or the members' union if they share none. */
function sharedBand(corridor: readonly Segment[]): [number, number] {
  let low = -Infinity;
  let high = Infinity;
  let unionLow = Infinity;
  let unionHigh = -Infinity;
  for (const segment of corridor) {
    low = Math.max(low, segment.bandMin);
    high = Math.min(high, segment.bandMax);
    unionLow = Math.min(unionLow, segment.bandMin);
    unionHigh = Math.max(unionHigh, segment.bandMax);
  }
  return low <= high ? [low, high] : [unionLow, unionHigh];
}

function capacity(corridor: readonly Segment[]): number {
  const [low, high] = sharedBand(corridor);
  return (high - low + 1) * TRACKS_PER_CELL;
}

/**
 * Negative when `a` should take the lower track. The pipe that leaves the
 * corridor first, at either end, takes the side it turns to; it then crosses
 * no pipe that stays.
 */
function trackOrder(a: Segment, b: Segment): number {
  if (Math.abs(a.high - b.high) > 0.5) {
    const first = a.high < b.high ? a : b;
    return first === a ? first.highTurn : -first.highTurn;
  }
  if (Math.abs(a.low - b.low) > 0.5) {
    const first = a.low > b.low ? a : b;
    return first === a ? first.lowTurn : -first.lowTurn;
  }
  if (a.highTurn !== b.highTurn) return a.highTurn - b.highTurn;
  if (a.work.id !== b.work.id) return a.work.id < b.work.id ? -1 : 1;
  return a.index - b.index;
}

interface Lane {
  segment: Segment;
  track: number;
}

/** Non-overlapping segments can share a track. */
function layOutCorridor(corridor: readonly Segment[]): {
  lanes: Lane[];
  count: number;
} {
  const lanes: Lane[] = [];
  let count = 0;
  for (const segment of corridor.slice().sort(trackOrder)) {
    let track = 0;
    for (const placed of lanes) {
      if (overlapsAlong(placed.segment, segment)) {
        track = Math.max(track, placed.track + 1);
      }
    }
    count = Math.max(count, track + 1);
    lanes.push({ segment, track });
  }
  return { lanes, count };
}

/** Midpoint of the first stretch where the most segments run abreast. */
function busiestPosition(corridor: readonly Segment[]): number {
  const ends = corridor
    .flatMap((segment) => [
      { at: segment.low, step: 1 },
      { at: segment.high, step: -1 },
    ])
    .sort((a, b) => a.at - b.at || a.step - b.step);
  let abreast = 0;
  let most = 0;
  let where = corridor[0]?.low ?? 0;
  for (const [index, end] of ends.entries()) {
    abreast += end.step;
    const next = ends[index + 1];
    if (abreast > most && next && next.at > end.at) {
      most = abreast;
      where = (end.at + next.at) / 2;
    }
  }
  return where;
}

function isPortBesideBottleneck(
  port: WorldPoint | undefined,
  segment: Segment,
  where: number,
): boolean {
  if (!port) return false;
  const line = segment.line * CELL_SIZE + CELL_SIZE / 2;
  const across = segment.vertical ? port.x : port.y;
  const lengthwise = segment.vertical ? port.y : port.x;
  return (
    Math.abs(across - line) <= BOTTLENECK_REACH &&
    Math.abs(lengthwise - where) <= BOTTLENECK_REACH
  );
}

/**
 * The pipe to sink from a crowded corridor: one passing through its busiest
 * stretch with neither port beside it, preferring one that clears it well on
 * both sides, then the longest, then the first by id.
 */
function pipeToSink(corridor: readonly Segment[]): Work | null {
  const where = busiestPosition(corridor);
  let best: Work | null = null;
  let bestClear = false;
  for (const segment of corridor) {
    if (segment.low >= where || segment.high <= where) continue;
    const { work } = segment;
    if (
      isPortBesideBottleneck(work.points[0], segment, where) ||
      isPortBesideBottleneck(work.points.at(-1), segment, where)
    ) {
      continue;
    }
    const clear =
      Math.min(where - segment.low, segment.high - where) >= CLEAR_PASS;
    if (
      !best ||
      (clear && !bestClear) ||
      (clear === bestClear &&
        (work.length > best.length ||
          (work.length === best.length && work.id < best.id)))
    ) {
      best = work;
      bestClear = clear;
    }
  }
  return best;
}

function onLayer(segments: readonly Segment[], depth: number): Segment[] {
  return segments.filter((segment) => segment.work.depth === depth);
}

/** Sink pass-through pipes out of corridors that hold more than they fit. */
function assignDepths(segments: readonly Segment[]): void {
  for (let depth = 0; depth < CELL_PIPE_MAX_DEPTH; depth += 1) {
    for (let pass = 0; pass < 3; pass += 1) {
      let sank = false;
      for (const vertical of [true, false]) {
        const layer = onLayer(segments, depth).filter(
          (segment) => segment.vertical === vertical,
        );
        for (const corridor of corridors(layer)) {
          const room = capacity(corridor);
          let members = corridor;
          while (
            members.length > room &&
            layOutCorridor(members).count > room
          ) {
            const sinking = pipeToSink(members);
            if (!sinking) break;
            sinking.depth = depth + 1;
            sank = true;
            members = members.filter((segment) => segment.work !== sinking);
          }
        }
      }
      if (!sank) break;
    }
  }
}

/** Place every segment of one corridor on its track. */
function spreadCorridor(corridor: readonly Segment[]): void {
  const [bandMin, bandMax] = sharedBand(corridor);
  const lines = corridor.map((segment) => segment.line).sort((a, b) => a - b);
  const preferred = lines[Math.floor((lines.length - 1) / 2)] ?? bandMin;
  const { lanes, count } = layOutCorridor(corridor);
  const tracks = trackPositionsInBand(bandMin, bandMax, count, preferred);
  for (const { segment, track } of lanes) {
    const lowest = segment.bandMin * CELL_SIZE + TRACK_MARGIN;
    const highest = (segment.bandMax + 1) * CELL_SIZE - TRACK_MARGIN;
    const at = Math.min(Math.max(tracks[track] ?? lowest, lowest), highest);
    const axis = segment.vertical ? "x" : "y";
    const start = segment.work.points[segment.index];
    const end = segment.work.points[segment.index + 1];
    if (start) start[axis] = at;
    if (end) end[axis] = at;
  }
}

function centres(corners: readonly CellCoord[]): WorldPoint[] {
  return corners.map((corner) => cellCenter(corner.col, corner.row));
}

/**
 * True when every segment still runs the way it was routed, at right angles
 * and with positive length, and both stubs keep their minimum length.
 */
function keepsShape(work: Work): boolean {
  const { points, corners } = work;
  for (let index = 1; index < points.length; index += 1) {
    const from = points[index - 1];
    const to = points[index];
    const was = corners[index - 1];
    const now = corners[index];
    if (!from || !to || !was || !now) return false;
    const dx = to.x - from.x;
    const dy = to.y - from.y;
    const routedDx = Math.sign(now.col - was.col);
    const routedDy = Math.sign(now.row - was.row);
    if (routedDx !== 0 && (Math.sign(dx) !== routedDx || dy !== 0)) {
      return false;
    }
    if (routedDy !== 0 && (Math.sign(dy) !== routedDy || dx !== 0)) {
      return false;
    }
    if (Math.abs(dx) + Math.abs(dy) <= 0.5) return false;
  }
  if (points.length > 2) {
    const stubs: [WorldPoint | undefined, WorldPoint | undefined][] = [
      [points[0], points[1]],
      [points.at(-2), points.at(-1)],
    ];
    for (const [a, b] of stubs) {
      if (!a || !b) return false;
      if (Math.abs(b.x - a.x) + Math.abs(b.y - a.y) < CELL_PIPE_STUB_MIN) {
        return false;
      }
    }
  }
  return true;
}

// ---------------------------------------------------------------------------

interface Endpoints {
  source: CellCoord;
  target: CellCoord;
  sourceSide: CellDir;
  targetSide: CellDir;
}

function endpointsOf(
  pipe: CellPipeModel,
  cardsById: ReadonlyMap<string, CellCardModel>,
): Endpoints | null {
  const sourceCard = cardsById.get(pipe.sourceCardId);
  const targetCard = cardsById.get(pipe.targetCardId);
  const sourcePort = sourceCard?.ports.find(
    (port) => port.id === pipe.sourcePortId,
  );
  const targetPort = targetCard?.ports.find(
    (port) => port.id === pipe.targetPortId,
  );
  if (!sourceCard || !targetCard || !sourcePort || !targetPort) return null;
  return {
    source: portCell(sourceCard, sourcePort),
    target: portCell(targetCard, targetPort),
    sourceSide: portSide(sourcePort),
    targetSide: portSide(targetPort),
  };
}

/** The run of cells for one pipe, honouring the exit rules. */
function routeCells(
  search: Search,
  ends: Endpoints,
  options: CellRoutingOptions,
): CellCoord[] {
  const { source, target } = ends;
  if (source.col === target.col && source.row === target.row) return [source];
  const out = dirIndex(ends.sourceSide);
  // The heading that would come out of the target's card into its port.
  const fromInside = dirIndex(ends.targetSide);
  let firstDirs: number[];
  let arrival: number;
  if (options.exits === "side") {
    firstDirs = [out];
    arrival = 1 << (fromInside ^ 1);
  } else {
    firstDirs = [0, 1, 2, 3].filter((dir) => dir !== (out ^ 1));
    arrival = 0b1111 & ~(1 << fromInside);
  }
  const found = findCellPath(search, source, target, firstDirs, arrival);
  // The grid is padded on every side, so a route always exists; keep a
  // straight fallback rather than throw if that ever changes.
  return found ?? [source, target];
}

function routeLength(corners: readonly CellCoord[]): number {
  let length = 0;
  for (let index = 1; index < corners.length; index += 1) {
    const a = corners[index - 1];
    const b = corners[index];
    if (a && b) length += Math.abs(b.col - a.col) + Math.abs(b.row - a.row);
  }
  return length;
}

/**
 * Route `graph`'s pipes, or only those in `onlyPipeIds` (a dragged card's
 * pipes). Every card and port shapes the ground either way; only the routed
 * pipes share gutters with one another.
 */
export function routeCellGraph(
  graph: CellGraph,
  options: CellRoutingOptions,
  onlyPipeIds?: ReadonlySet<string>,
): CellRoutingResult {
  const grid = buildGrid(graph.cards);
  const search = createSearch(grid, options);
  const cardsById = new Map(graph.cards.map((card) => [card.id, card]));

  const works: Work[] = [];
  const exits = new Map<
    string,
    Pick<RoutedCellPipe, "sourceExit" | "targetExit">
  >();
  for (const pipe of graph.pipes) {
    if (onlyPipeIds && !onlyPipeIds.has(pipe.id)) continue;
    const ends = endpointsOf(pipe, cardsById);
    if (!ends) continue;
    const cells = routeCells(search, ends, options);
    const corners =
      cells.length === 1 ? [ends.source, ends.target] : cornersOf(cells);
    const first = cells[0];
    const second = cells[1];
    const last = cells.at(-1);
    const beforeLast = cells.at(-2);
    exits.set(pipe.id, {
      sourceExit:
        first && second
          ? (DIR_NAMES[stepDir(first, second)] ?? ends.sourceSide)
          : ends.sourceSide,
      targetExit:
        last && beforeLast
          ? (DIR_NAMES[stepDir(last, beforeLast)] ?? ends.targetSide)
          : ends.targetSide,
    });
    works.push({
      id: pipe.id,
      cells,
      corners,
      points: centres(corners),
      depth: 0,
      length: routeLength(corners),
    });
  }

  const segments: Segment[] = [];
  for (const work of works) {
    for (let index = 1; index <= work.corners.length - 3; index += 1) {
      const segment = movableSegment(grid, work, index);
      if (segment) segments.push(segment);
    }
  }

  if (options.depth) assignDepths(segments);
  for (let depth = 0; depth <= CELL_PIPE_MAX_DEPTH; depth += 1) {
    const layer = onLayer(segments, depth);
    for (const vertical of [true, false]) {
      const axisSegments = layer.filter(
        (segment) => segment.vertical === vertical,
      );
      for (const corridor of corridors(axisSegments)) spreadCorridor(corridor);
    }
  }

  const pipes = new Map<string, RoutedCellPipe>();
  let deepCount = 0;
  let maxDepthUsed = 0;
  for (const work of works) {
    // Tracks never fold a route back on itself by construction; if a corner
    // case ever did, the cell-centre route is always valid.
    const points = keepsShape(work) ? work.points : centres(work.corners);
    const exit = exits.get(work.id);
    if (!exit) continue;
    if (work.depth > 0) deepCount += 1;
    maxDepthUsed = Math.max(maxDepthUsed, work.depth);
    pipes.set(work.id, {
      id: work.id,
      points,
      cellPath: work.cells,
      sourceExit: exit.sourceExit,
      targetExit: exit.targetExit,
      depth: work.depth,
    });
  }
  return { pipes, deepCount, maxDepthUsed };
}
