import { describe, expect, it } from "vitest";

import {
  PIPE_LANE_MIN,
  type CardRect,
  type Point,
  type RoutedPipe,
  type RoutingScene,
} from "../pipe-routing";
import { corridorRouter } from "./corridor";
import { DEMO_SCENE, card, gridScene, moveCard, pipe } from "./scenes";

const options = { lanes: true, depth: true };

function pointsFor(layout: Map<string, RoutedPipe>, id: string): Point[] {
  const routed = layout.get(id);
  if (!routed || routed.points.length < 2) {
    throw new Error(`Missing route for ${id}`);
  }
  return routed.points;
}

function segments(points: readonly Point[]): [Point, Point][] {
  const pairs: [Point, Point][] = [];
  for (const [index, from] of points.entries()) {
    const to = points[index + 1];
    if (to) pairs.push([from, to]);
  }
  return pairs;
}

function distance(from: Point, to: Point): number {
  return Math.hypot(to.x - from.x, to.y - from.y);
}

function samples(points: readonly Point[]): Point[] {
  return segments(points).flatMap(([from, to]) => {
    const steps = Math.max(1, Math.ceil(distance(from, to) / 2));
    return Array.from({ length: steps + 1 }, (_, index) => ({
      x: from.x + ((to.x - from.x) * index) / steps,
      y: from.y + ((to.y - from.y) * index) / steps,
    }));
  });
}

function inside({ x, y }: Point, rect: CardRect): boolean {
  return (
    x > rect.x + 1 &&
    x < rect.x + rect.width - 1 &&
    y > rect.y + 1 &&
    y < rect.y + rect.height - 1
  );
}

function cardsWithGap(height: number): CardRect[] {
  return [
    card("upper", 150, -160, 400, 160),
    card("lower", 150, height, 400, 160),
  ];
}

const NARROW_GAP: RoutingScene = {
  cards: cardsWithGap(34),
  pipes: [pipe("through-gap", [0, -35], [700, -35])],
};

const SYMMETRIC: RoutingScene = {
  cards: [card("middle", 150, -80, 400, 160)],
  pipes: [pipe("across", [0, 0], [700, 0])],
};

function crossingAt(points: readonly Point[], x: number): number {
  const crossing = segments(points).find(
    ([from, to]) =>
      from.y === to.y &&
      Math.min(from.x, to.x) < x &&
      Math.max(from.x, to.x) > x,
  );
  if (!crossing) throw new Error(`No horizontal crossing at x = ${x}`);
  return crossing[0].y;
}

describe("corridor router", () => {
  it.each([
    ["demo", DEMO_SCENE],
    ["narrow gap", NARROW_GAP],
  ])("avoids card interiors in the %s scene", (_, scene) => {
    const layout = corridorRouter.create()(scene, options);
    for (const { id } of scene.pipes) {
      const sampled = samples(pointsFor(layout, id));
      for (const rect of scene.cards) {
        expect(
          sampled.find((point) => inside(point, rect)),
          `${id} inside ${rect.id}`,
        ).toBeUndefined();
      }
    }
  });

  it("takes the under-card shortcut when the detour is much longer", () => {
    const wall = card("wall", 300, -1000, 100, 2000);
    const scene = { cards: [wall], pipes: SYMMETRIC.pipes };
    const layout = corridorRouter.create()(scene, options);

    expect(
      samples(pointsFor(layout, "across")).some((point) => inside(point, wall)),
    ).toBe(true);
  });

  it("keeps the old side after a card moves enough to favor the opposite side", () => {
    const route = corridorRouter.create();
    const initial = crossingAt(
      pointsFor(route(SYMMETRIC, options), "across"),
      350,
    );
    expect(Math.abs(initial)).toBeGreaterThanOrEqual(80);
    const side = Math.sign(initial);

    const moved = moveCard(SYMMETRIC, "middle", 0, 15 * side);
    const kept = crossingAt(pointsFor(route(moved, options), "across"), 350);
    const fresh = crossingAt(
      pointsFor(corridorRouter.create()(moved, options), "across"),
      350,
    );

    expect(Math.sign(fresh)).toBe(-side);
    expect(Math.sign(kept)).toBe(side);
  });

  it("keeps its shape and lane through successive tiny drag frames", () => {
    const route = corridorRouter.create();
    let scene = gridScene(5, 4);
    let previous = route(scene, options);
    for (let frame = 0; frame < 4; frame += 1) {
      const moved = moveCard(scene, "1-2", 2, 1);
      const current = route(moved, options);
      // The canvas publishes only the dragged card's pipes during the drag.
      // Shared lanes can re-pack resting pipes, whose visible routes stay frozen.
      const attached = moved.pipes.filter(({ source, target }, index) => {
        const before = scene.pipes[index];
        return before && (source !== before.source || target !== before.target);
      });
      expect(attached.length).toBeGreaterThan(0);
      for (const { id } of attached) {
        const before = pointsFor(previous, id);
        const after = pointsFor(current, id);
        expect(after, id).toHaveLength(before.length);
        for (const [index, point] of after.entries()) {
          const old = before[index];
          if (!old) throw new Error(`Missing previous point for ${id}`);
          expect(distance(point, old), id).toBeLessThan(PIPE_LANE_MIN);
        }
      }
      expect(route(moved, options)).toEqual(current);
      scene = moved;
      previous = current;
    }
  });

  it.each([
    ["demo", DEMO_SCENE],
    ["narrow gap", NARROW_GAP],
  ])("avoids short interior jogs in the %s scene", (_, scene) => {
    const layout = corridorRouter.create()(scene, options);
    for (const { id } of scene.pipes) {
      const points = pointsFor(layout, id);
      if (scene === NARROW_GAP) {
        const y = crossingAt(points, 350);
        expect(y).toBeGreaterThanOrEqual(0);
        expect(y).toBeLessThanOrEqual(34);
      }
      for (const [from, to] of segments(points).slice(1, -1)) {
        expect(distance(from, to), id).toBeGreaterThanOrEqual(15);
      }
    }
  });

  it("fits three distinct lanes inside a shared gap with card clearance", () => {
    const gap = 42;
    const clearance = 8;
    const scene = {
      cards: cardsWithGap(gap),
      pipes: [-36, -35, -34].map((y, index) =>
        pipe(`lane-${index}`, [0, y], [700, y]),
      ),
    };
    const route = corridorRouter.create();
    const layout = route(scene, options);
    const positions = scene.pipes.map(({ id }) =>
      crossingAt(pointsFor(layout, id), 350),
    );
    expect(new Set(positions).size).toBe(3);
    for (const y of positions) {
      expect(y).toBeGreaterThanOrEqual(clearance);
      expect(y).toBeLessThanOrEqual(gap - clearance);
    }
  });
});
