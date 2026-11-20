import { describe, expect, it } from "vitest";

import {
  PIPE_LANE_MIN,
  PIPE_MAX_DEPTH,
  PIPE_STUB_MIN,
  outward,
  type PipeRoutingBackend,
  type Point,
  type RoutedPipe,
  type RoutingOptions,
  type RoutingScene,
} from "../pipe-routing";
import { PIPE_ROUTERS } from ".";
import { DEMO_SCENE, card, gridScene, moveCard, pipe } from "./scenes";

/**
 * What every router promises the pipe layers, checked on the spike's graphs
 * and a few awkward pipes, with every option combination.
 */

const SCENES: Record<string, RoutingScene> = {
  demo: DEMO_SCENE,
  grid: gridScene(5, 4),
  awkward: {
    cards: [card("a", 0, 0), card("b", 500, 0), card("wall", 200, 300)],
    pipes: [
      // Ports on one line, facing each other: no bend at all.
      pipe("straight", [323, 100], [477, 100]),
      // Target behind the source on the same line.
      pipe("behind", [823, 60], [-23, 60]),
      // Target barely ahead: too close for a forward bend.
      pipe("close", [323, 150], [360, 400]),
      // Far apart with a card in between.
      pipe("across", [323, 20], [177, 400]),
    ],
  },
};

const OPTIONS: RoutingOptions[] = [
  { lanes: true, depth: true },
  { lanes: true, depth: false },
  { lanes: false, depth: false },
];

function segments(points: readonly Point[]): [Point, Point][] {
  const pairs: [Point, Point][] = [];
  for (let index = 1; index < points.length; index += 1) {
    const before = points[index - 1];
    const after = points[index];
    if (before && after) pairs.push([before, after]);
  }
  return pairs;
}

function direction(from: Point, to: Point): Point {
  const length = Math.hypot(to.x - from.x, to.y - from.y);
  return { x: (to.x - from.x) / length, y: (to.y - from.y) / length };
}

function snapshot(layout: Map<string, RoutedPipe>): string {
  return JSON.stringify([...layout].sort(([a], [b]) => a.localeCompare(b)));
}

describe.each<PipeRoutingBackend>(PIPE_ROUTERS)("$label router", (router) => {
  describe.each(Object.entries(SCENES))("on the %s scene", (_, scene) => {
    it.each(OPTIONS)("keeps the contract with %o", (options) => {
      const layout = router.create()(scene, options);
      expect([...layout.keys()].sort()).toEqual(
        scene.pipes.map((request) => request.id).sort(),
      );
      for (const request of scene.pipes) {
        const routed = layout.get(request.id);
        const points = routed?.points ?? [];
        // Starts and ends at its ports.
        expect(points[0]).toEqual(request.source);
        expect(points.at(-1)).toEqual(request.target);

        // Leaves and enters straight and square to the card side.
        const [first, second] = [points[0], points[1]];
        const [beforeLast, last] = [points.at(-2), points.at(-1)];
        if (!first || !second || !beforeLast || !last) {
          throw new Error(`${request.id} has fewer than two points`);
        }
        const leaving = direction(first, second);
        const out = outward(request.sourceSide);
        expect(leaving.x).toBeCloseTo(out.x, 6);
        expect(leaving.y).toBeCloseTo(out.y, 6);
        const entering = direction(beforeLast, last);
        const into = outward(request.targetSide);
        expect(entering.x).toBeCloseTo(-into.x, 6);
        expect(entering.y).toBeCloseTo(-into.y, 6);
        if (points.length > 2) {
          expect(
            Math.hypot(second.x - first.x, second.y - first.y),
          ).toBeGreaterThanOrEqual(PIPE_STUB_MIN - 1e-6);
          expect(
            Math.hypot(last.x - beforeLast.x, last.y - beforeLast.y),
          ).toBeGreaterThanOrEqual(PIPE_STUB_MIN - 1e-6);
        }

        for (const [from, to] of segments(points)) {
          const dx = Math.abs(to.x - from.x);
          const dy = Math.abs(to.y - from.y);
          // No zero-length segments.
          expect(dx + dy).toBeGreaterThan(0.5);
          const square = dx < 1e-6 || dy < 1e-6;
          const diagonal = Math.abs(dx - dy) < 1e-6;
          expect(
            square || (router.angles === "octilinear" && diagonal),
            `${request.id}: segment ${JSON.stringify([from, to])}`,
          ).toBe(true);
        }

        expect(Number.isInteger(routed?.depth)).toBe(true);
        expect(routed?.depth).toBeGreaterThanOrEqual(0);
        expect(routed?.depth).toBeLessThanOrEqual(PIPE_MAX_DEPTH);
      }
    });

    it("gives the same layout for the same scene", () => {
      const options = { lanes: true, depth: true };
      const route = router.create();
      const first = snapshot(route(scene, options));
      expect(snapshot(route(scene, options))).toBe(first);
      expect(snapshot(router.create()(scene, options))).toBe(first);
    });
  });

  it("never jumps a picked-up card's pipes to another lane", () => {
    // Picking a card up nudges it by a pixel or two. Its pipes leave the
    // frozen resting layout for the moving one; they must not jump to other
    // lanes, layers or shapes as they do. Lanes may re-space a little.
    const scene = gridScene(5, 4);
    const options = { lanes: true, depth: true };
    const route = router.create();
    const before = route(scene, options);
    const nudged = moveCard(scene, "1-2", 2, 1);
    const after = route(nudged, options);
    const attached = nudged.pipes.filter(
      (request, index) =>
        JSON.stringify(request) !== JSON.stringify(scene.pipes[index]),
    );
    expect(attached.length).toBeGreaterThan(0);
    for (const { id } of attached) {
      const routed = before.get(id);
      const moved = after.get(id);
      if (!routed) throw new Error(`${id} was not routed`);
      expect(moved?.depth, id).toBe(routed.depth);
      expect(moved?.points.length, id).toBe(routed.points.length);
      for (const [index, point] of routed.points.entries()) {
        const now = moved?.points[index] ?? point;
        expect(
          Math.abs(now.x - point.x) + Math.abs(now.y - point.y),
          id,
        ).toBeLessThan(PIPE_LANE_MIN);
      }
    }
  });
});
