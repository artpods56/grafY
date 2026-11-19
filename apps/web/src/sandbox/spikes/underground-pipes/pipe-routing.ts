import { Position } from "@xyflow/react";

/**
 * Orthogonal pipe routes, computed for all pipes together so that pipes
 * sharing a channel run side by side instead of on top of each other.
 *
 * Each pipe first gets its own route: a stub straight out of each port, then
 * one bend between them (forward) or a loop back (when the target lies
 * behind the source). Every segment that may move (not a stub: a stub is
 * pinned to its port) is grouped with the segments it overlaps on nearly the
 * same line, and each group is spread into lanes. Pipes that leave a channel
 * early sit on the side they turn to, so they cross none of the pipes that
 * stay in it.
 *
 * A channel between two cards is narrow: a bend keeps its distance from both
 * ports. When a channel holds more pipes than lanes fit, pipes passing through
 * the crowded stretch sink to a deeper layer under the glass, where they take
 * lanes of their own. Pipes starting or ending at a card right beside the
 * crowded stretch stay near the surface.
 */

export interface Point {
  x: number;
  y: number;
}

export interface PipeRequest {
  id: string;
  /** Centre of the source port's ring, and the side of the card it sits on. */
  source: Point;
  sourceSide: Position;
  target: Point;
  targetSide: Position;
}

export interface RoutedPipe {
  points: Point[];
  /** 0 is just under the glass; higher layers lie deeper. */
  depth: number;
}

/** How far a pipe runs straight out of its port before its first bend. */
export const PIPE_STUB = 30;
/** The shortest a stub may get when its bend is moved into a lane. */
export const PIPE_STUB_MIN = 27;
/** Distance between the centre lines of two pipes sharing a channel. */
export const PIPE_LANE = 14;
/** The tightest lanes may get in a narrow channel before pipes sink deeper. */
export const PIPE_LANE_MIN = 10;
/** The deepest layer a pipe may sink to. */
export const PIPE_MAX_DEPTH = 2;
/** Segments closer than this share a channel. */
const CHANNEL_REACH = PIPE_LANE * 1.5;
/** How far a loop back drops below a source and target on the same line. */
const LOOP_DROP = 80;

interface Route {
  id: string;
  points: Point[];
  /** Per segment index: the range its line may move in, or absent if pinned. */
  movable: Map<number, { min: number; max: number }>;
  depth: number;
  /** Total length, so the longest pipes sink first. */
  length: number;
}

const UNBOUNDED = { min: -Infinity, max: Infinity };

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

function route(
  id: string,
  points: Point[],
  movable: Map<number, { min: number; max: number }>,
): Route {
  return { id, points, movable, depth: 0, length: routeLength(points) };
}

/** One pipe's route on its own, with no regard for other pipes. */
function rawRoute(request: PipeRequest): Route {
  const { source: s, target: t } = request;
  const movable = new Map<number, { min: number; max: number }>();
  const outward =
    request.sourceSide === Position.Right &&
    request.targetSide === Position.Left;
  if (!outward) {
    // Only right-to-left ports exist on this canvas; anything else goes
    // through a single bend and is left alone.
    const midX = (s.x + t.x) / 2;
    return route(
      request.id,
      [s, { x: midX, y: s.y }, { x: midX, y: t.y }, t],
      movable,
    );
  }

  const forward = t.x - s.x >= PIPE_STUB_MIN * 2;
  if (forward) {
    if (Math.abs(s.y - t.y) < 0.5) return route(request.id, [s, t], movable);
    const midX = (s.x + t.x) / 2;
    movable.set(1, { min: s.x + PIPE_STUB_MIN, max: t.x - PIPE_STUB_MIN });
    return route(
      request.id,
      [s, { x: midX, y: s.y }, { x: midX, y: t.y }, t],
      movable,
    );
  }

  // The target lies behind the source: out, across, back, and in.
  const outX = s.x + PIPE_STUB;
  const inX = t.x - PIPE_STUB;
  const loopY = Math.abs(s.y - t.y) < 0.5 ? s.y + LOOP_DROP : (s.y + t.y) / 2;
  movable.set(1, { min: s.x + PIPE_STUB_MIN, max: Infinity });
  movable.set(2, UNBOUNDED);
  movable.set(3, { min: -Infinity, max: t.x - PIPE_STUB_MIN });
  return route(
    request.id,
    [
      s,
      { x: outX, y: s.y },
      { x: outX, y: loopY },
      { x: inX, y: loopY },
      { x: inX, y: t.y },
      t,
    ],
    movable,
  );
}

/** A route with no lanes: for a pipe that is moving and will settle later. */
export function routePipe(request: PipeRequest): Point[] {
  return rawRoute(request).points;
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
  for (let a = 0; a < segments.length; a += 1) {
    for (let b = a + 1; b < segments.length; b += 1) {
      const left = segments[a];
      const right = segments[b];
      if (left && right && sharesChannel(left, right)) {
        parent[root(a)] = root(b);
      }
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
 * Every pipe's route, with pipes that share a channel spread into lanes and,
 * where a channel is too narrow, sunk into deeper layers. `lanes: false`
 * routes each pipe on its own, to compare against; `depth: false` keeps every
 * pipe on one layer and squeezes the lanes instead.
 */
export function routePipes(
  requests: readonly PipeRequest[],
  { lanes = true, depth = true }: { lanes?: boolean; depth?: boolean } = {},
): Map<string, RoutedPipe> {
  const routes = requests.map(rawRoute);
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

/** SVG path through the points, with square or rounded bends. */
export function pipePath(points: readonly Point[], radius: number): string {
  const first = points[0];
  if (!first) return "";
  const parts = [`M${first.x},${first.y}`];
  for (let index = 1; index < points.length - 1; index += 1) {
    const before = points[index - 1];
    const corner = points[index];
    const after = points[index + 1];
    if (!before || !corner || !after) continue;
    const inLength = Math.hypot(corner.x - before.x, corner.y - before.y);
    const outLength = Math.hypot(after.x - corner.x, after.y - corner.y);
    const bend = Math.min(radius, inLength / 2, outLength / 2);
    if (bend < 0.5) {
      parts.push(`L${corner.x},${corner.y}`);
      continue;
    }
    const enter = {
      x: corner.x - ((corner.x - before.x) / inLength) * bend,
      y: corner.y - ((corner.y - before.y) / inLength) * bend,
    };
    const leave = {
      x: corner.x + ((after.x - corner.x) / outLength) * bend,
      y: corner.y + ((after.y - corner.y) / outLength) * bend,
    };
    parts.push(
      `L${enter.x},${enter.y}`,
      `Q${corner.x},${corner.y} ${leave.x},${leave.y}`,
    );
  }
  const last = points[points.length - 1];
  if (last && points.length > 1) parts.push(`L${last.x},${last.y}`);
  return parts.join(" ");
}
