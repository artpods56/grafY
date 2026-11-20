import { Position } from "@xyflow/react";

import {
  PIPE_STUB,
  PIPE_STUB_MIN,
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
  supports: { lanes: true, depth: true },
  angles: "orthogonal",
  create: () => routeElbows,
} as const satisfies PipeRoutingBackend;
