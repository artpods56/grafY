import { Position } from "@xyflow/react";

import {
  PIPE_STUB,
  PIPE_STUB_MIN,
  outward,
  type PipeRequest,
  type PipeRoutingBackend,
  type Point,
  type RoutedPipe,
  type RoutingScene,
  type RoutingOptions,
} from "../pipe-routing";
import {
  UNBOUNDED,
  layOutLanes,
  route,
  type LaneRange,
  type Route,
} from "./lanes";

/**
 * The first router: each pipe takes a stub straight out of each port, then one
 * bend between them (forward) or a loop back (when the target lies behind the
 * source). It ignores the cards: a pipe lies under the glass, so it may run
 * under one. Shared channels are spread into lanes and layers by
 * {@link layOutLanes}.
 */

/** How far a loop back drops below a source and target on the same line. */
const LOOP_DROP = 80;

/** One pipe's route on its own, with no regard for other pipes. */
function rawRoute(request: PipeRequest): Route {
  const { source: s, target: t } = request;
  const movable = new Map<number, LaneRange>();
  const outward =
    request.sourceSide === Position.Right &&
    request.targetSide === Position.Left;
  if (!outward) return anySidesRoute(request);

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

/** What a bend costs against length when choosing between candidate routes. */
const BEND = 40;

/** Drops repeated points and joins straight runs; null if a run folds back. */
function straightened(points: readonly Point[]): Point[] | null {
  const kept: Point[] = [];
  for (const point of points) {
    const last = kept.at(-1);
    if (last && Math.abs(last.x - point.x) + Math.abs(last.y - point.y) < 0.5) {
      continue;
    }
    const before = kept.at(-2);
    if (last && before) {
      const ax = Math.sign(last.x - before.x);
      const ay = Math.sign(last.y - before.y);
      const bx = Math.sign(point.x - last.x);
      const by = Math.sign(point.y - last.y);
      if (ax === -bx && ay === -by) return null;
      if (ax === bx && ay === by) {
        kept[kept.length - 1] = point;
        continue;
      }
    }
    kept.push(point);
  }
  return kept;
}

/** True when the route leaves and enters along `out` and `into` far enough. */
function keepsStubs(
  points: readonly Point[],
  out: Point,
  into: Point,
): boolean {
  const [first, second] = points;
  const [beforeLast, last] = [points.at(-2), points.at(-1)];
  if (!first || !second || !beforeLast || !last || points.length < 3) {
    return false;
  }
  const leaving = (second.x - first.x) * out.x + (second.y - first.y) * out.y;
  const entering =
    (beforeLast.x - last.x) * into.x + (beforeLast.y - last.y) * into.y;
  return (
    leaving >= PIPE_STUB_MIN &&
    entering >= PIPE_STUB_MIN &&
    Math.abs((second.x - first.x) * out.y - (second.y - first.y) * out.x) <
      1e-6 &&
    Math.abs(
      (beforeLast.x - last.x) * into.y - (beforeLast.y - last.y) * into.x,
    ) < 1e-6
  );
}

function routeCost(points: readonly Point[]): number {
  let cost = BEND * (points.length - 2);
  for (let index = 1; index < points.length; index += 1) {
    const before = points[index - 1];
    const after = points[index];
    if (before && after) {
      cost += Math.abs(after.x - before.x) + Math.abs(after.y - before.y);
    }
  }
  return cost;
}

/**
 * A pipe whose ports face any way, as a well's free exit gives them: a stub
 * out of each, joined by the cheapest of a few one-, two- and three-bend
 * shapes that neither folds back nor cuts a stub short.
 */
function anySidesRoute(request: PipeRequest): Route {
  const { source: s, target: t } = request;
  const out = outward(request.sourceSide);
  const into = outward(request.targetSide);
  const a = { x: s.x + out.x * PIPE_STUB, y: s.y + out.y * PIPE_STUB };
  const b = { x: t.x + into.x * PIPE_STUB, y: t.y + into.y * PIPE_STUB };
  const [left, right] = [Math.min(a.x, b.x), Math.max(a.x, b.x)];
  const [top, bottom] = [Math.min(a.y, b.y), Math.max(a.y, b.y)];
  // The middle, flush with either stub end, or a loop beyond both.
  const xs = [
    (a.x + b.x) / 2,
    left,
    right,
    left - LOOP_DROP,
    right + LOOP_DROP,
  ];
  const ys = [
    (a.y + b.y) / 2,
    top,
    bottom,
    top - LOOP_DROP,
    bottom + LOOP_DROP,
  ];
  const middles: Point[][] = [
    [{ x: b.x, y: a.y }],
    [{ x: a.x, y: b.y }],
    ...xs.map((x) => [
      { x, y: a.y },
      { x, y: b.y },
    ]),
    ...ys.map((y) => [
      { x: a.x, y },
      { x: b.x, y },
    ]),
  ];
  let best: Point[] | null = null;
  let bestCost = Infinity;
  for (const middle of middles) {
    const points = straightened([s, a, ...middle, b, t]);
    if (!points || !keepsStubs(points, out, into)) continue;
    const cost = routeCost(points);
    if (cost < bestCost - 1e-6) {
      best = points;
      bestCost = cost;
    }
  }
  const points = best ?? [s, a, b, t];
  const movable = new Map<number, LaneRange>();
  // Every run between the stubs may move, but not so far it cuts one short.
  for (let index = 1; index < points.length - 2; index += 1) {
    const range = { ...UNBOUNDED };
    if (index === 1) limit(range, s, out);
    if (index === points.length - 3) limit(range, t, into);
    movable.set(index, range);
  }
  return route(request.id, points, movable);
}

/** Keep a run across a stub at least {@link PIPE_STUB_MIN} out from its port. */
function limit(range: LaneRange, port: Point, out: Point): void {
  const axis = out.x !== 0 ? "x" : "y";
  const sign = out[axis];
  const edge = port[axis] + sign * PIPE_STUB_MIN;
  if (sign > 0) range.min = Math.max(range.min, edge);
  else range.max = Math.min(range.max, edge);
}

/** One pipe's route with no lanes: for a pipe being laid or not yet routed. */
export function elbowRoute(request: PipeRequest): Point[] {
  return rawRoute(request).points;
}

/** Every pipe's elbow route, spread into lanes and layers. */
export function routeElbows(
  { pipes }: RoutingScene,
  options: RoutingOptions,
): Map<string, RoutedPipe> {
  return layOutLanes(pipes.map(rawRoute), options);
}

export const elbowRouter = {
  id: "elbow",
  label: "Elbow",
  supports: { lanes: true, depth: true, cards: false },
  angles: "orthogonal",
  create: () => routeElbows,
} as const satisfies PipeRoutingBackend;
