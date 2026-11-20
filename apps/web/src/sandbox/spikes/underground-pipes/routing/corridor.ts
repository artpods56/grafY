import {
  PIPE_STUB,
  PIPE_STUB_MIN,
  outward,
  type CardRect,
  type PipeRequest,
  type PipeRoutingBackend,
  type Point,
  type RoutingOptions,
  type RoutingScene,
  type SceneRouter,
} from "../pipe-routing";
import { elbowRoute } from "./elbow";
import { layOutLanes, route, type LaneRange, type Route } from "./lanes";

/**
 * Routes each pipe through the gaps between cards, the way a cable runs in a
 * floor duct: an A* search over a sparse orthogonal grid whose lines are the
 * cards' edges, a margin around each card, the middle of every gap between
 * cards, and each pipe's own stub ends. A pipe lies under the glass, so a card
 * is no wall, only expensive: running under one costs several times its
 * length, hugging its edge a little more than open floor, and each bend costs
 * a stretch of straight pipe. A pipe goes under a card only when every way
 * round is much longer.
 *
 * The rough routes then go to the shared lane layout, which spreads pipes
 * sharing a gap into lanes, kept inside the gap by the cards on either side.
 *
 * Hysteresis: the router remembers each pipe's route. A pipe whose ports and
 * neighbouring cards have not moved keeps its route without a search. One that
 * must be searched again keeps its old shape, stretched to the new ports,
 * unless the new best route is clearly cheaper; so a small drag never flips a
 * pipe from above a card to below it. That memory also keeps a drag cheap:
 * only the dragged card's pipes and the few pipes near it are searched again.
 */

/** Pipes keep this far off a card's edge where the gap allows. */
const CARD_MARGIN = 18;
/** Extra cost per unit of length under a card, on top of the length. */
const UNDER_CARD = 3;
/** Extra cost per unit of length inside a card's margin. */
const NEAR_CARD = 0.25;
/** What a bend costs, in units of straight pipe. */
const BEND = 50;
/** A pipe keeps its old shape unless a new one is this much cheaper. */
const KEEP_RATIO = 0.15;
const KEEP_SLACK = BEND;
/** A card that moves this close to a pipe's route makes it search again. */
const REACH = CARD_MARGIN * 2;
/**
 * Between searches, a pipe whose ports or nearby cards move keeps its old
 * shape stretched to fit; it searches again once they drift this far.
 */
const SEARCH_STEP = 12;
/** The nearest a lane may come to a card's edge. */
const LANE_CLEARANCE = 8;
/** A search that expands this many states gives up and falls back. */
const MAX_EXPANSIONS = 60_000;

interface Box {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

function cardBox(card: CardRect, grow = 0): Box {
  return {
    minX: card.x - grow,
    minY: card.y - grow,
    maxX: card.x + card.width + grow,
    maxY: card.y + card.height + grow,
  };
}

function boxOf(points: readonly Point[], grow: number): Box {
  const box = {
    minX: Infinity,
    minY: Infinity,
    maxX: -Infinity,
    maxY: -Infinity,
  };
  for (const { x, y } of points) {
    box.minX = Math.min(box.minX, x - grow);
    box.minY = Math.min(box.minY, y - grow);
    box.maxX = Math.max(box.maxX, x + grow);
    box.maxY = Math.max(box.maxY, y + grow);
  }
  return box;
}

function overlaps(a: Box, b: Box): boolean {
  return (
    a.minX < b.maxX && b.minX < a.maxX && a.minY < b.maxY && b.minY < a.maxY
  );
}

type Axis = "x" | "y";

/** Where a card starts and ends along one axis. */
function cardStart(card: CardRect, axis: Axis): number {
  return axis === "x" ? card.x : card.y;
}

function cardEnd(card: CardRect, axis: Axis): number {
  return axis === "x" ? card.x + card.width : card.y + card.height;
}

/**
 * What a unit of pipe costs at a point because of one card: under it, in its
 * margin, or not at all. The grid and the cost of a finished route both ask
 * this, so they always agree.
 */
function cardWeight(card: CardRect, x: number, y: number): number {
  const right = card.x + card.width;
  const bottom = card.y + card.height;
  if (x > card.x && x < right && y > card.y && y < bottom) {
    return 1 + UNDER_CARD;
  }
  if (
    x > card.x - CARD_MARGIN &&
    x < right + CARD_MARGIN &&
    y > card.y - CARD_MARGIN &&
    y < bottom + CARD_MARGIN
  ) {
    return 1 + NEAR_CARD;
  }
  return 1;
}

function weightAt(x: number, y: number, cards: readonly CardRect[]): number {
  let weight = 1;
  for (const card of cards) weight = Math.max(weight, cardWeight(card, x, y));
  return weight;
}

/** The cost of a straight horizontal or vertical stretch. */
function stretchCost(a: Point, b: Point, cards: readonly CardRect[]): number {
  const horizontal = Math.abs(a.y - b.y) < 0.01;
  const along: Axis = horizontal ? "x" : "y";
  const across: Axis = horizontal ? "y" : "x";
  const line = a[across];
  const low = Math.min(a[along], b[along]);
  const high = Math.max(a[along], b[along]);
  const nearby = cards.filter(
    (card) =>
      line > cardStart(card, across) - CARD_MARGIN &&
      line < cardEnd(card, across) + CARD_MARGIN &&
      cardStart(card, along) - CARD_MARGIN < high &&
      cardEnd(card, along) + CARD_MARGIN > low,
  );
  if (nearby.length === 0) return high - low;
  const cuts = [low, high];
  for (const card of nearby) {
    const start = cardStart(card, along);
    const end = cardEnd(card, along);
    for (const cut of [start - CARD_MARGIN, start, end, end + CARD_MARGIN]) {
      if (cut > low && cut < high) cuts.push(cut);
    }
  }
  cuts.sort((p, q) => p - q);
  let cost = 0;
  for (let index = 1; index < cuts.length; index += 1) {
    const from = cuts[index - 1] ?? low;
    const to = cuts[index] ?? high;
    const middle = (from + to) / 2;
    const weight = horizontal
      ? weightAt(middle, line, nearby)
      : weightAt(line, middle, nearby);
    cost += (to - from) * weight;
  }
  return cost;
}

/** A whole route's cost: every stretch, and every bend. */
function routeCost(
  points: readonly Point[],
  cards: readonly CardRect[],
): number {
  let cost = BEND * Math.max(0, points.length - 2);
  for (let index = 1; index < points.length; index += 1) {
    const before = points[index - 1];
    const after = points[index];
    if (before && after) cost += stretchCost(before, after, cards);
  }
  return cost;
}

/** Drops repeated points and points in the middle of a straight run. */
function corners(points: readonly Point[]): Point[] {
  const kept: Point[] = [];
  for (const point of points) {
    const last = kept.at(-1);
    if (last && Math.abs(last.x - point.x) + Math.abs(last.y - point.y) < 1e-6)
      continue;
    const beforeLast = kept.at(-2);
    if (
      last &&
      beforeLast &&
      ((Math.abs(beforeLast.x - last.x) < 1e-6 &&
        Math.abs(last.x - point.x) < 1e-6) ||
        (Math.abs(beforeLast.y - last.y) < 1e-6 &&
          Math.abs(last.y - point.y) < 1e-6))
    ) {
      kept[kept.length - 1] = point;
      continue;
    }
    kept.push(point);
  }
  return kept;
}

function stubEnd(port: Point, side: PipeRequest["sourceSide"]): Point {
  const out = outward(side);
  return { x: port.x + out.x * PIPE_STUB, y: port.y + out.y * PIPE_STUB };
}

/** Index of the first value not below `value`. */
function firstAtLeast(values: readonly number[], value: number): number {
  let low = 0;
  let high = values.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if ((values[middle] ?? Infinity) < value) low = middle + 1;
    else high = middle;
  }
  return low;
}

/**
 * Grid lines: every `fixed` value exactly (a pipe must start and end on its
 * own stub ends), and the `loose` ones unless they fall within half a unit of
 * a line already kept.
 */
function gridLines(fixed: number[], loose: number[]): number[] {
  const exact = [...new Set(fixed)].sort((a, b) => a - b);
  const lines = [...exact];
  let previous = -Infinity;
  for (const value of [...loose].sort((a, b) => a - b)) {
    if (value - previous < 0.5) continue;
    const next = firstAtLeast(exact, value);
    const above = exact[next] ?? Infinity;
    const below = exact[next - 1] ?? -Infinity;
    if (above - value < 0.5 || value - below < 0.5) continue;
    lines.push(value);
    previous = value;
  }
  return lines.sort((a, b) => a - b);
}

/** Middles of the gaps between card edges, where a gap has room for margins. */
function gapMiddles(edges: number[]): number[] {
  const sorted = [...new Set(edges)].sort((a, b) => a - b);
  const middles: number[] = [];
  for (let index = 1; index < sorted.length; index += 1) {
    const low = sorted[index - 1] ?? 0;
    const high = sorted[index] ?? 0;
    if (high - low > CARD_MARGIN * 2) middles.push((low + high) / 2);
  }
  return middles;
}

/** Steps on the grid: right, left, down, up. */
const STEPS = [
  [1, 0],
  [-1, 0],
  [0, 1],
  [0, -1],
] as const;
/** Where a step may go next: straight on, or a turn either way. */
const NEXT_STEPS = [
  [0, 2, 3],
  [1, 2, 3],
  [2, 0, 1],
  [3, 0, 1],
] as const;

function perpendicular(a: number, b: number): boolean {
  return a >> 1 !== b >> 1;
}

function stepOf(direction: Point): number {
  if (direction.x > 0) return 0;
  if (direction.x < 0) return 1;
  return direction.y > 0 ? 2 : 3;
}

/** A binary min-heap of search states, keyed by estimated total cost. */
class StateHeap {
  private states: number[] = [];
  private keys: number[] = [];

  get size(): number {
    return this.states.length;
  }

  push(state: number, key: number): void {
    let index = this.states.length;
    this.states.push(state);
    this.keys.push(key);
    while (index > 0) {
      const parent = (index - 1) >> 1;
      if ((this.keys[parent] ?? 0) <= key) break;
      this.states[index] = this.states[parent] ?? 0;
      this.keys[index] = this.keys[parent] ?? 0;
      index = parent;
    }
    this.states[index] = state;
    this.keys[index] = key;
  }

  pop(): number {
    const top = this.states[0] ?? -1;
    const lastState = this.states.pop() ?? 0;
    const lastKey = this.keys.pop() ?? 0;
    const count = this.states.length;
    if (count === 0) return top;
    let index = 0;
    for (;;) {
      const left = index * 2 + 1;
      if (left >= count) break;
      const right = left + 1;
      const child =
        right < count && (this.keys[right] ?? 0) < (this.keys[left] ?? 0)
          ? right
          : left;
      if ((this.keys[child] ?? 0) >= lastKey) break;
      this.states[index] = this.states[child] ?? 0;
      this.keys[index] = this.keys[child] ?? 0;
      index = child;
    }
    this.states[index] = lastState;
    this.keys[index] = lastKey;
    return top;
  }
}

/**
 * Search state for every (node, heading) pair, kept between calls so a drag
 * frame allocates nothing. `seen` and `done` hold the number of the search
 * that last wrote a state, so nothing has to be cleared between searches.
 */
class SearchBuffers {
  best = new Float64Array(0);
  parent = new Int32Array(0);
  seen = new Uint32Array(0);
  done = new Uint32Array(0);
  search = 0;

  reserve(states: number): void {
    if (this.best.length >= states) return;
    this.best = new Float64Array(states);
    this.parent = new Int32Array(states);
    this.seen = new Uint32Array(states);
    this.done = new Uint32Array(states);
    this.search = 0;
  }
}

/** The grid for one scene, searched once per pipe that needs a new route. */
class CorridorGrid {
  private readonly xs: number[];
  private readonly ys: number[];
  /** Cost per unit of the edge from node (i, j) to (i + 1, j). */
  private readonly across: Float64Array;
  /** Cost per unit of the edge from node (i, j) to (i, j + 1). */
  private readonly down: Float64Array;
  private readonly buffers: SearchBuffers;

  constructor({ pipes, cards }: RoutingScene, buffers: SearchBuffers) {
    const fixedX: number[] = [];
    const fixedY: number[] = [];
    for (const pipe of pipes) {
      for (const end of [
        stubEnd(pipe.source, pipe.sourceSide),
        stubEnd(pipe.target, pipe.targetSide),
      ]) {
        fixedX.push(end.x);
        fixedY.push(end.y);
      }
    }
    const edgesX = cards.flatMap((card) => [card.x, card.x + card.width]);
    const edgesY = cards.flatMap((card) => [card.y, card.y + card.height]);
    this.xs = gridLines(fixedX, [
      ...edgesX,
      ...edgesX.flatMap((x) => [x - CARD_MARGIN, x + CARD_MARGIN]),
      ...gapMiddles(edgesX),
    ]);
    this.ys = gridLines(fixedY, [
      ...edgesY,
      ...edgesY.flatMap((y) => [y - CARD_MARGIN, y + CARD_MARGIN]),
      ...gapMiddles(edgesY),
    ]);
    const nodes = this.xs.length * this.ys.length;
    this.across = new Float64Array(nodes).fill(1);
    this.down = new Float64Array(nodes).fill(1);
    for (const card of cards) this.weighCard(card);
    buffers.reserve(nodes * 4);
    this.buffers = buffers;
  }

  /** Raise the cost of every grid edge under or beside one card. */
  private weighCard(card: CardRect): void {
    const { xs, ys } = this;
    const box = cardBox(card, CARD_MARGIN);
    const width = xs.length;
    const i0 = Math.max(0, firstAtLeast(xs, box.minX) - 1);
    const i1 = Math.min(xs.length - 1, firstAtLeast(xs, box.maxX));
    const j0 = Math.max(0, firstAtLeast(ys, box.minY) - 1);
    const j1 = Math.min(ys.length - 1, firstAtLeast(ys, box.maxY));
    for (let j = j0; j <= j1; j += 1) {
      for (let i = i0; i <= i1; i += 1) {
        const x = xs[i] ?? 0;
        const y = ys[j] ?? 0;
        const node = j * width + i;
        const nextX = xs[i + 1];
        if (nextX !== undefined) {
          const weight = cardWeight(card, (x + nextX) / 2, y);
          if (weight > (this.across[node] ?? 1)) this.across[node] = weight;
        }
        const nextY = ys[j + 1];
        if (nextY !== undefined) {
          const weight = cardWeight(card, x, (y + nextY) / 2);
          if (weight > (this.down[node] ?? 1)) this.down[node] = weight;
        }
      }
    }
  }

  private nodeAt(point: Point): number {
    const i = firstAtLeast(this.xs, point.x - 1e-6);
    const j = firstAtLeast(this.ys, point.y - 1e-6);
    if (Math.abs((this.xs[i] ?? Infinity) - point.x) > 1e-6) return -1;
    if (Math.abs((this.ys[j] ?? Infinity) - point.y) > 1e-6) return -1;
    return j * this.xs.length + i;
  }

  /** Grid nodes on a stub, other than its far end: a route may not cross it. */
  private stubNodes(port: Point, end: Point, into: Set<number>): void {
    const horizontal = Math.abs(port.y - end.y) < 1e-6;
    const lines = horizontal ? this.xs : this.ys;
    const from = horizontal ? port.x : port.y;
    const to = horizontal ? end.x : end.y;
    const low = Math.min(from, to) - 1;
    const high = Math.max(from, to) + 1;
    for (
      let index = firstAtLeast(lines, low);
      index < lines.length;
      index += 1
    ) {
      const value = lines[index] ?? Infinity;
      if (value > high) break;
      if (Math.abs(value - to) < 1e-6) continue;
      const node = this.nodeAt(
        horizontal ? { x: value, y: port.y } : { x: port.x, y: value },
      );
      if (node >= 0) into.add(node);
    }
  }

  /**
   * The cheapest route for one pipe, ports first and last, or null when the
   * search fails. The route leaves along its source stub and enters along its
   * target stub; it never crosses either stub.
   */
  route(pipe: PipeRequest): Point[] | null {
    const from = stubEnd(pipe.source, pipe.sourceSide);
    const to = stubEnd(pipe.target, pipe.targetSide);
    const start = this.nodeAt(from);
    const goal = this.nodeAt(to);
    if (start < 0 || goal < 0) return null;
    const leaving = stepOf(outward(pipe.sourceSide));
    const towardOut = outward(pipe.targetSide);
    const arriving = stepOf({ x: -towardOut.x, y: -towardOut.y });
    const blocked = new Set<number>();
    this.stubNodes(pipe.source, from, blocked);
    this.stubNodes(pipe.target, to, blocked);
    blocked.delete(start);
    blocked.delete(goal);

    const width = this.xs.length;
    const goalX = to.x;
    const goalY = to.y;
    const estimate = (node: number, step: number): number => {
      const x = this.xs[node % width] ?? 0;
      const y = this.ys[Math.floor(node / width)] ?? 0;
      const distance = Math.abs(goalX - x) + Math.abs(goalY - y);
      return (
        distance + BEND * fewestBends(step, arriving, goalX - x, goalY - y)
      );
    };

    const { best, parent, seen, done } = this.buffers;
    this.buffers.search += 1;
    const stamp = this.buffers.search;
    const heap = new StateHeap();
    const relax = (state: number, cost: number, from: number) => {
      if (seen[state] === stamp && (best[state] ?? 0) <= cost) return;
      seen[state] = stamp;
      best[state] = cost;
      parent[state] = from;
      // Among equal estimates, the state nearer the goal first: it keeps
      // the search from flooding the many equally short ways across a grid.
      const left = estimate(state >> 2, state & 3);
      heap.push(state, cost + left * (1 + 1e-6));
    };
    relax(start * 4 + leaving, 0, -1);
    let expansions = 0;
    while (heap.size > 0) {
      const state = heap.pop();
      if (done[state] === stamp) continue;
      done[state] = stamp;
      const node = state >> 2;
      const step = state & 3;
      const cost = best[state] ?? 0;
      if (node === goal && step === arriving) return this.trace(state, pipe);
      expansions += 1;
      if (expansions > MAX_EXPANSIONS) return null;
      if (node === goal) {
        // Turn into the target stub: a bend at the goal itself.
        if (perpendicular(step, arriving)) {
          relax(goal * 4 + arriving, cost + BEND, state);
        }
        continue;
      }
      const i = node % width;
      const j = (node - i) / width;
      for (const nextStep of NEXT_STEPS[step] ?? []) {
        const [di, dj] = STEPS[nextStep];
        const ni = i + di;
        const nj = j + dj;
        if (ni < 0 || nj < 0 || ni >= width || nj >= this.ys.length) continue;
        const nextNode = nj * width + ni;
        if (blocked.has(nextNode)) continue;
        const length =
          di === 0
            ? Math.abs((this.ys[nj] ?? 0) - (this.ys[j] ?? 0))
            : Math.abs((this.xs[ni] ?? 0) - (this.xs[i] ?? 0));
        const weight =
          di === 0
            ? (this.down[Math.min(j, nj) * width + i] ?? 1)
            : (this.across[j * width + Math.min(i, ni)] ?? 1);
        const turn = nextStep === step ? 0 : BEND;
        relax(nextNode * 4 + nextStep, cost + length * weight + turn, state);
      }
    }
    return null;
  }

  private trace(state: number, pipe: PipeRequest): Point[] {
    const width = this.xs.length;
    const path: Point[] = [];
    for (let at = state; at >= 0; at = this.buffers.parent[at] ?? -1) {
      const node = at >> 2;
      path.push({
        x: this.xs[node % width] ?? 0,
        y: this.ys[Math.floor(node / width)] ?? 0,
      });
    }
    path.reverse();
    return corners([pipe.source, ...path, pipe.target]);
  }
}

/**
 * The fewest bends that can take a pipe heading `step` to a point `dx, dy`
 * away, arriving heading `arriving`. A lower bound, so the search stays exact.
 */
function fewestBends(
  step: number,
  arriving: number,
  dx: number,
  dy: number,
): number {
  if (step === arriving) {
    const [sx, sy] = STEPS[step] ?? [0, 0];
    const ahead =
      sx !== 0
        ? Math.abs(dy) < 1e-6 && dx * sx >= 0
        : Math.abs(dx) < 1e-6 && dy * sy >= 0;
    return ahead ? 0 : 2;
  }
  return perpendicular(step, arriving) ? 1 : 2;
}

function samePorts(a: PipeRequest, b: PipeRequest): boolean {
  return (
    a.source.x === b.source.x &&
    a.source.y === b.source.y &&
    a.target.x === b.target.x &&
    a.target.y === b.target.y &&
    a.sourceSide === b.sourceSide &&
    a.targetSide === b.targetSide
  );
}

/**
 * An old route stretched to moved ports: each stub moves with its port and
 * drags the line of the stretch after it along. Null when the stretched route
 * would fold back on itself or cut a stub short.
 */
function stretch(
  points: readonly Point[],
  from: PipeRequest,
  to: PipeRequest,
): Point[] | null {
  if (points.length < 4) return null;
  if (from.sourceSide !== to.sourceSide || from.targetSide !== to.targetSide) {
    return null;
  }
  const moved = points.map((point) => ({ ...point }));
  const last = moved.length - 1;
  const shift = (index: number, dx: number, dy: number) => {
    const point = moved[index];
    if (point) moved[index] = { x: point.x + dx, y: point.y + dy };
  };
  const sourceShift = {
    x: to.source.x - from.source.x,
    y: to.source.y - from.source.y,
  };
  const targetShift = {
    x: to.target.x - from.target.x,
    y: to.target.y - from.target.y,
  };
  const sourceOut = outward(to.sourceSide);
  const targetOut = outward(to.targetSide);
  // Ports and stub ends move with their cards; the next corner follows along
  // the stub's axis only, so the stretch after a stub stays straight.
  shift(1, sourceShift.x, sourceShift.y);
  shift(
    2,
    sourceOut.x !== 0 ? sourceShift.x : 0,
    sourceOut.y !== 0 ? sourceShift.y : 0,
  );
  shift(last - 1, targetShift.x, targetShift.y);
  shift(
    last - 2,
    targetOut.x !== 0 ? targetShift.x : 0,
    targetOut.y !== 0 ? targetShift.y : 0,
  );
  moved[0] = { ...to.source };
  moved[last] = { ...to.target };
  for (let index = 1; index <= last; index += 1) {
    const before = moved[index - 1];
    const after = moved[index];
    const oldBefore = points[index - 1];
    const oldAfter = points[index];
    if (!before || !after || !oldBefore || !oldAfter) return null;
    const dx = after.x - before.x;
    const dy = after.y - before.y;
    if (Math.abs(dx) > 1e-6 && Math.abs(dy) > 1e-6) return null;
    if (Math.abs(dx) + Math.abs(dy) < 1) return null;
    // Every stretch still runs the way it ran: nothing folds back.
    if (Math.sign(dx) !== Math.sign(oldAfter.x - oldBefore.x)) return null;
    if (Math.sign(dy) !== Math.sign(oldAfter.y - oldBefore.y)) return null;
  }
  const sourceStub =
    Math.abs((moved[1]?.x ?? 0) - to.source.x) +
    Math.abs((moved[1]?.y ?? 0) - to.source.y);
  const targetStub =
    Math.abs((moved[last - 1]?.x ?? 0) - to.target.x) +
    Math.abs((moved[last - 1]?.y ?? 0) - to.target.y);
  if (sourceStub < PIPE_STUB_MIN || targetStub < PIPE_STUB_MIN) return null;
  return moved;
}

/** Where each stretch between the stubs may move when lanes are spread. */
interface Lanes {
  ranges: Map<number, LaneRange>;
  /** Where a card moving would change a range. */
  reach: Box;
}

/**
 * The span each stretch between the stubs may move in when lanes are spread:
 * inside its gap, clear of the cards on either side, without folding its
 * neighbours back or cutting a stub below {@link PIPE_STUB_MIN}.
 */
function laneRanges(
  points: readonly Point[],
  pipe: PipeRequest,
  cards: readonly CardRect[],
): Lanes {
  const ranges = new Map<number, LaneRange>();
  const reach = {
    minX: Infinity,
    minY: Infinity,
    maxX: -Infinity,
    maxY: -Infinity,
  };
  const lastStretch = points.length - 2;
  for (let index = 1; index < lastStretch; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    if (!start || !end) continue;
    const axis: Axis = Math.abs(start.x - end.x) < 1e-6 ? "x" : "y";
    const along: Axis = axis === "x" ? "y" : "x";
    const at = start[axis];
    const low = Math.min(start[along], end[along]);
    const high = Math.max(start[along], end[along]);
    let min = -Infinity;
    let max = Infinity;
    for (const card of cards) {
      if (cardEnd(card, along) <= low || cardStart(card, along) >= high) {
        continue;
      }
      const near = cardStart(card, axis);
      const far = cardEnd(card, axis);
      if (far <= at + 0.5) min = Math.max(min, far + LANE_CLEARANCE);
      else if (near >= at - 0.5) max = Math.min(max, near - LANE_CLEARANCE);
    }
    // The cards bounding this stretch, and any card moving in between.
    const band = {
      [axis]: [min - LANE_CLEARANCE - 1, max + LANE_CLEARANCE + 1],
      [along]: [low, high],
    } as Record<Axis, [number, number]>;
    reach.minX = Math.min(reach.minX, band.x[0]);
    reach.maxX = Math.max(reach.maxX, band.x[1]);
    reach.minY = Math.min(reach.minY, band.y[0]);
    reach.maxY = Math.max(reach.maxY, band.y[1]);
    for (const neighbour of [points[index - 1], points[index + 2]]) {
      if (!neighbour) continue;
      if (neighbour[axis] < at - 1e-6) min = Math.max(min, neighbour[axis] + 1);
      if (neighbour[axis] > at + 1e-6) max = Math.min(max, neighbour[axis] - 1);
    }
    for (const [isStub, port, side] of [
      [index === 1, pipe.source, pipe.sourceSide],
      [index === lastStretch - 1, pipe.target, pipe.targetSide],
    ] as const) {
      if (!isStub) continue;
      const out = outward(side)[axis];
      if (out > 0) min = Math.max(min, port[axis] + PIPE_STUB_MIN);
      if (out < 0) max = Math.min(max, port[axis] - PIPE_STUB_MIN);
    }
    ranges.set(index, min <= max ? { min, max } : { min: at, max: at });
  }
  return { ranges, reach };
}

/** A card that was added, removed, moved or resized since the last call. */
interface CardChange {
  id: string;
  before: CardRect | undefined;
  now: CardRect | undefined;
}

function changedCards(
  known: ReadonlyMap<string, CardRect>,
  cards: readonly CardRect[],
): CardChange[] {
  const changes: CardChange[] = [];
  const present = new Set<string>();
  for (const card of cards) {
    present.add(card.id);
    const before = known.get(card.id);
    if (before && cardShift(before, card) === 0) continue;
    changes.push({ id: card.id, before, now: card });
  }
  for (const [id, before] of known) {
    if (!present.has(id)) changes.push({ id, before, now: undefined });
  }
  return changes;
}

function cardShift(a: CardRect, b: CardRect): number {
  return (
    Math.abs(a.x - b.x) +
    Math.abs(a.y - b.y) +
    Math.abs(a.width - b.width) +
    Math.abs(a.height - b.height)
  );
}

function touches(change: CardChange, box: Box): boolean {
  return (
    (change.now !== undefined && overlaps(cardBox(change.now), box)) ||
    (change.before !== undefined && overlaps(cardBox(change.before), box))
  );
}

/** How far a pipe's ports moved; Infinity when a port changed sides. */
function portShift(a: PipeRequest, b: PipeRequest): number {
  if (a.sourceSide !== b.sourceSide || a.targetSide !== b.targetSide) {
    return Infinity;
  }
  return Math.max(
    Math.abs(a.source.x - b.source.x) + Math.abs(a.source.y - b.source.y),
    Math.abs(a.target.x - b.target.x) + Math.abs(a.target.y - b.target.y),
  );
}

/** The ports and nearby cards a route was last searched for. */
interface Searched {
  request: PipeRequest;
  cards: ReadonlyMap<string, CardRect>;
}

/**
 * True once a pipe's ports, or a card near its route, have drifted more than
 * {@link SEARCH_STEP} from where they were at its last search, or a card has
 * come near it: a better route may exist now.
 */
function drifted(
  searched: Searched,
  pipe: PipeRequest,
  changes: readonly CardChange[],
  reach: Box,
): boolean {
  if (portShift(searched.request, pipe) > SEARCH_STEP) return true;
  for (const change of changes) {
    const before = searched.cards.get(change.id);
    if (before) {
      if (!change.now || cardShift(before, change.now) > SEARCH_STEP) {
        return true;
      }
    } else if (change.now && overlaps(cardBox(change.now), reach)) {
      return true;
    }
  }
  return false;
}

function cardsNear(
  box: Box,
  cards: readonly CardRect[],
): Map<string, CardRect> {
  const near = new Map<string, CardRect>();
  for (const card of cards) {
    if (overlaps(cardBox(card), box)) near.set(card.id, card);
  }
  return near;
}

interface Remembered {
  /** The ports `points` fit. */
  request: PipeRequest;
  /** The route before lanes, ports first and last. */
  points: Point[];
  /** Where a moving card may change the route. */
  reach: Box;
  searched: Searched;
  lanes: Lanes;
}

function createCorridorRouter(): SceneRouter {
  const buffers = new SearchBuffers();
  let remembered = new Map<string, Remembered>();
  let knownCards = new Map<string, CardRect>();
  return (scene: RoutingScene, options: RoutingOptions) => {
    const changes = changedCards(knownCards, scene.cards);
    let grid: CorridorGrid | null = null;
    const next = new Map<string, Remembered>();
    const routes: Route[] = [];
    for (const pipe of scene.pipes) {
      const old = remembered.get(pipe.id);
      let memory: Remembered;
      if (
        old &&
        samePorts(old.request, pipe) &&
        !changes.some((change) => touches(change, old.reach))
      ) {
        // Nothing near this pipe moved.
        memory = changes.some((change) => touches(change, old.lanes.reach))
          ? { ...old, lanes: laneRanges(old.points, pipe, scene.cards) }
          : old;
      } else {
        const kept = old ? stretch(old.points, old.request, pipe) : null;
        let points: Point[];
        let searched: Searched;
        if (old && kept && !drifted(old.searched, pipe, changes, old.reach)) {
          // Moved a little since the last search: the old shape, stretched.
          points = kept;
          searched = old.searched;
        } else {
          grid ??= new CorridorGrid(scene, buffers);
          const fresh = grid.route(pipe) ?? elbowRoute(pipe);
          points =
            kept &&
            routeCost(kept, scene.cards) <=
              routeCost(fresh, scene.cards) * (1 + KEEP_RATIO) + KEEP_SLACK
              ? kept
              : fresh;
          searched = {
            request: pipe,
            cards: cardsNear(boxOf(points, REACH), scene.cards),
          };
        }
        memory = {
          request: pipe,
          points,
          reach: boxOf(points, REACH),
          searched,
          lanes: laneRanges(points, pipe, scene.cards),
        };
      }
      next.set(pipe.id, memory);
      routes.push(
        route(
          pipe.id,
          memory.points.map((point) => ({ ...point })),
          memory.lanes.ranges,
        ),
      );
    }
    remembered = next;
    knownCards = new Map(scene.cards.map((card) => [card.id, card]));
    return layOutLanes(routes, options);
  };
}

export const corridorRouter = {
  id: "corridor",
  label: "Corridor",
  supports: { lanes: true, depth: true },
  angles: "orthogonal",
  create: createCorridorRouter,
} as const satisfies PipeRoutingBackend;
