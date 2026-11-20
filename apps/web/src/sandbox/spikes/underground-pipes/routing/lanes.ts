import {
  PIPE_LANE,
  PIPE_LANE_MIN,
  PIPE_MAX_DEPTH,
  PIPE_STUB,
  type Point,
  type RoutedPipe,
  type RoutingOptions,
} from "../pipe-routing";

/**
 * Lanes and layers for orthogonal routes, shared by every router that draws
 * right angles: each router builds one rough route per pipe on its own, then
 * hands them all here to be spread apart.
 *
 * Every segment that may move (not a stub: a stub is pinned to its port) is
 * grouped with the segments it overlaps on nearly the same line, and each
 * group is spread into lanes. Pipes that leave a channel early sit on the side
 * they turn to, so they cross none of the pipes that stay in it.
 *
 * A channel between two cards is narrow: a bend keeps its distance from both
 * ports. When a channel holds more pipes than lanes fit, pipes passing through
 * the crowded stretch sink to a deeper layer under the glass, where they take
 * lanes of their own. Pipes starting or ending at a card right beside the
 * crowded stretch stay near the surface.
 */

/** Segments closer than this share a channel. */
const CHANNEL_REACH = PIPE_LANE * 1.5;

/** The range a segment's line may move in. */
export interface LaneRange {
  min: number;
  max: number;
}

export interface Route {
  id: string;
  /** Moved in place by {@link layOutLanes}. */
  points: Point[];
  /** Per segment index: the range its line may move in, or absent if pinned. */
  movable: Map<number, LaneRange>;
  depth: number;
  /** Total length, so the longest pipes sink first. */
  length: number;
}

export const UNBOUNDED: LaneRange = { min: -Infinity, max: Infinity };

function routeLength(points: readonly Point[]): number {
  let length = 0;
  for (let index = 1; index < points.length; index += 1) {
    const before = points[index - 1];
    const after = points[index];
    if (before && after) {
      length += Math.abs(after.x - before.x) + Math.abs(after.y - before.y);
    }
  }
  return length;
}

export function route(
  id: string,
  points: Point[],
  movable: Map<number, LaneRange>,
): Route {
  return { id, points, movable, depth: 0, length: routeLength(points) };
}

type Axis = "x" | "y";

/** A movable segment that runs along one axis and sits at `at` on the other. */
interface Segment {
  route: Route;
  index: number;
  at: number;
  low: number;
  high: number;
  min: number;
  max: number;
  /** Which way the pipe turns at the segment's low and high end: -1, 0 or 1. */
  lowTurn: number;
  highTurn: number;
}

function other(axis: Axis): Axis {
  return axis === "x" ? "y" : "x";
}

/**
 * Segments that sit at a constant `axis` value (vertical ones for "x"), with
 * the direction the pipe turns at each end.
 */
function movableSegments(routes: readonly Route[], axis: Axis): Segment[] {
  const along = other(axis);
  const segments: Segment[] = [];
  for (const route of routes) {
    for (const [index, range] of route.movable) {
      const start = route.points[index];
      const end = route.points[index + 1];
      if (!start || !end || Math.abs(start[axis] - end[axis]) > 0.01) continue;
      if (Math.abs(start[along] - end[along]) < 0.01) continue;
      const before = route.points[index - 1];
      const after = route.points[index + 2];
      const startTurn = before ? Math.sign(before[axis] - start[axis]) : 0;
      const endTurn = after ? Math.sign(after[axis] - end[axis]) : 0;
      const startIsLow = start[along] < end[along];
      segments.push({
        route,
        index,
        at: start[axis],
        low: Math.min(start[along], end[along]),
        high: Math.max(start[along], end[along]),
        min: range.min,
        max: range.max,
        lowTurn: startIsLow ? startTurn : endTurn,
        highTurn: startIsLow ? endTurn : startTurn,
      });
    }
  }
  return segments;
}

function sharesChannel(a: Segment, b: Segment): boolean {
  if (Math.abs(a.at - b.at) >= CHANNEL_REACH) return false;
  return Math.min(a.high, b.high) - Math.max(a.low, b.low) > 0.5;
}

/** Groups of segments that overlap on (nearly) the same line. */
function channels(segments: readonly Segment[]): Segment[][] {
  const parent = segments.map((_, index) => index);
  const root = (index: number): number => {
    let current = index;
    while (parent[current] !== current) current = parent[current] ?? current;
    return current;
  };
  // Only segments less than CHANNEL_REACH apart can share a channel, so each
  // is compared with its neighbours in order of position.
  const byPosition = segments
    .map((_, index) => index)
    .sort((a, b) => (segments[a]?.at ?? 0) - (segments[b]?.at ?? 0));
  for (let rank = 0; rank < byPosition.length; rank += 1) {
    const a = byPosition[rank] ?? 0;
    const left = segments[a];
    for (let next = rank + 1; left && next < byPosition.length; next += 1) {
      const b = byPosition[next] ?? 0;
      const right = segments[b];
      if (!right || right.at - left.at >= CHANNEL_REACH) break;
      if (sharesChannel(left, right)) parent[root(a)] = root(b);
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

/** The span every segment of a channel may move in, if both ends are bounded. */
function sharedRoom(channel: readonly Segment[]): number | null {
  const low = Math.max(...channel.map((segment) => segment.min));
  const high = Math.min(...channel.map((segment) => segment.max));
  if (!Number.isFinite(low) || !Number.isFinite(high) || high < low) {
    return null;
  }
  return high - low;
}

/** How many pipes fit side by side in a channel at the tightest spacing. */
function capacity(channel: readonly Segment[]): number {
  const room = sharedRoom(channel);
  return room === null ? Infinity : Math.floor(room / PIPE_LANE_MIN) + 1;
}

/**
 * Negative when `a` should take the lower lane. The pipe that leaves the
 * channel first, at either end, takes the side it turns to; it then crosses
 * no pipe that stays.
 */
function laneOrder(a: Segment, b: Segment): number {
  if (Math.abs(a.high - b.high) > 0.5) {
    const first = a.high < b.high ? a : b;
    return first === a ? first.highTurn : -first.highTurn;
  }
  if (Math.abs(a.low - b.low) > 0.5) {
    const first = a.low > b.low ? a : b;
    return first === a ? first.lowTurn : -first.lowTurn;
  }
  if (a.highTurn !== b.highTurn) return a.highTurn - b.highTurn;
  return a.route.id.localeCompare(b.route.id);
}

function overlapsAlong(a: Segment, b: Segment): boolean {
  return Math.min(a.high, b.high) - Math.max(a.low, b.low) > 0.5;
}

/**
 * A lane per segment: one past every overlapping segment earlier in lane
 * order. Segments that never run side by side share a lane, so a long channel
 * needs as many lanes as pipes run abreast at once, not as many as pass
 * through it.
 */
function laneIndices(channel: readonly Segment[]): Map<Segment, number> {
  const lanes = new Map<Segment, number>();
  for (const segment of [...channel].sort(laneOrder)) {
    let lane = 0;
    for (const [placed, index] of lanes) {
      if (overlapsAlong(placed, segment)) lane = Math.max(lane, index + 1);
    }
    lanes.set(segment, lane);
  }
  return lanes;
}

function laneCount(lanes: ReadonlyMap<Segment, number>): number {
  let count = 0;
  for (const index of lanes.values()) count = Math.max(count, index + 1);
  return count;
}

/** Spread one channel into lanes, keeping every segment inside its range. */
function spread(channel: Segment[], axis: Axis): void {
  const lanes = laneIndices(channel);
  const count = laneCount(lanes);
  if (count < 2) return;
  const room = sharedRoom(channel);
  const spacing =
    room === null
      ? PIPE_LANE
      : Math.max(PIPE_LANE_MIN, Math.min(PIPE_LANE, room / (count - 1)));
  const centre =
    channel.reduce((sum, segment) => sum + segment.at, 0) / channel.length;
  const laneAt = (index: number) =>
    centre + (index - (count - 1) / 2) * spacing;
  // Shift the whole channel as little as possible to respect every range.
  let lowestShift = -Infinity;
  let highestShift = Infinity;
  for (const [segment, index] of lanes) {
    lowestShift = Math.max(lowestShift, segment.min - laneAt(index));
    highestShift = Math.min(highestShift, segment.max - laneAt(index));
  }
  const shift =
    lowestShift <= highestShift
      ? Math.min(Math.max(0, lowestShift), highestShift)
      : (lowestShift + highestShift) / 2;
  for (const [segment, index] of lanes) {
    const lane = laneAt(index) + shift;
    const at = Math.min(Math.max(lane, segment.min), segment.max);
    const start = segment.route.points[segment.index];
    const end = segment.route.points[segment.index + 1];
    if (start) start[axis] = at;
    if (end) end[axis] = at;
  }
}

/** Midpoint of the first positive-length interval with peak occupancy. */
function busiestPosition(channel: readonly Segment[]): number {
  const ends = channel
    .flatMap((segment) => [
      { at: segment.low, step: 1 },
      { at: segment.high, step: -1 },
    ])
    .sort((a, b) => a.at - b.at || a.step - b.step);
  let abreast = 0;
  let most = 0;
  let where = channel[0]?.low ?? 0;
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

/**
 * True when a port sits on a card directly beside the crowded point `(at, where)`.
 * Such a pipe is terminating or starting right at the bottleneck rather than
 * passing through it, so it should stay on the shallower layer.
 */
function isPortBesideBottleneck(
  port: Point | undefined,
  at: number,
  where: number,
  axis: Axis,
): boolean {
  if (!port) return false;
  const along = other(axis);
  const reach = PIPE_STUB * 2;
  return (
    Math.abs(port[axis] - at) <= reach && Math.abs(port[along] - where) <= reach
  );
}

/**
 * Pick the best pass-through pipe to sink from a crowded channel's busiest
 * stretch. Pipes whose source or target port sits right beside the bottleneck
 * never sink; among the remaining pass-through pipes, prefer ones whose
 * segment clears the bottleneck cleanly on both sides, then longest overall.
 */
function sinkingThroughPipe(
  channel: readonly Segment[],
  axis: Axis,
): Route | null {
  const where = busiestPosition(channel);
  let best: Route | null = null;
  let bestClear = false;
  for (const segment of channel) {
    if (segment.low >= where || segment.high <= where) continue;
    const { route, at } = segment;
    if (
      isPortBesideBottleneck(route.points[0], at, where, axis) ||
      isPortBesideBottleneck(route.points.at(-1), at, where, axis)
    ) {
      continue;
    }
    const clearance = Math.min(where - segment.low, segment.high - where);
    const clear = clearance >= PIPE_STUB * 3;
    if (
      !best ||
      (clear && !bestClear) ||
      (clear === bestClear &&
        (route.length > best.length ||
          (route.length === best.length && route.id < best.id)))
    ) {
      best = route;
      bestClear = clear;
    }
  }
  return best;
}

/**
 * Where a channel needs more lanes than fit, sink the best pass-through pipe
 * running through its busiest stretch one layer deeper, until it fits or no
 * pass-through pipe remains.
 */
function assignDepths(routes: readonly Route[]): void {
  for (let depth = 0; depth < PIPE_MAX_DEPTH; depth += 1) {
    for (let pass = 0; pass < 3; pass += 1) {
      let sank = false;
      for (const axis of ["x", "y"] as const) {
        const layer = routes.filter((route) => route.depth === depth);
        for (const channel of channels(movableSegments(layer, axis))) {
          const room = capacity(channel);
          if (room === Infinity) continue;
          let members = channel;
          while (laneCount(laneIndices(members)) > room) {
            const sinking = sinkingThroughPipe(members, axis);
            if (!sinking) break;
            sinking.depth = depth + 1;
            sank = true;
            members = members.filter((segment) => segment.route !== sinking);
          }
        }
      }
      if (!sank) break;
    }
  }
}

/**
 * Spread routes that share a channel into lanes and, where a channel is too
 * narrow, sink some into deeper layers. `lanes: false` leaves every route as
 * it is; `depth: false` keeps every pipe on one layer and squeezes the lanes
 * instead.
 */
export function layOutLanes(
  routes: readonly Route[],
  { lanes, depth }: RoutingOptions,
): Map<string, RoutedPipe> {
  if (lanes) {
    if (depth) assignDepths(routes);
    for (let layer = 0; layer <= PIPE_MAX_DEPTH; layer += 1) {
      const onLayer = routes.filter((route) => route.depth === layer);
      // Twice, so that lanes pushed into a neighbouring channel are spread
      // again together with it.
      for (let pass = 0; pass < 2; pass += 1) {
        for (const axis of ["x", "y"] as const) {
          for (const channel of channels(movableSegments(onLayer, axis))) {
            spread(channel, axis);
          }
        }
      }
    }
  }
  return new Map(
    routes.map((route) => [
      route.id,
      { points: route.points, depth: route.depth },
    ]),
  );
}
