import { Position } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import {
  PIPE_LANE_MIN,
  PIPE_STUB_MIN,
  outward,
  type Point,
  type PipeRequest,
} from "../pipe-routing";
import { octilinearRouter } from "./octilinear";
import { gridScene, pipe } from "./scenes";

const route = octilinearRouter.create();
const options = { lanes: true, depth: true };

function diagonals(points: Point[]) {
  return points.flatMap((start, index) => {
    const end = points[index + 1];
    if (!end || start.x === end.x || start.y === end.y) return [];
    const dx = end.x - start.x;
    const dy = end.y - start.y;
    expect(Math.abs(dx)).toBeCloseTo(Math.abs(dy), 6);
    const slope = Math.sign(dx * dy);
    return [
      {
        slope,
        offset: (start.y - slope * start.x) / Math.SQRT2,
        low: Math.min(start.x, end.x),
        high: Math.max(start.x, end.x),
      },
    ];
  });
}

function expectStubs(request: PipeRequest, points: Point[]) {
  const { source, sourceSide, target, targetSide } = request;
  expect(points[0]).toEqual(source);
  expect(points.at(-1)).toEqual(target);
  for (const [port, adjacent, side] of [
    [source, points[1], sourceSide],
    [target, points.at(-2), targetSide],
  ] as const) {
    if (!adjacent) throw new Error("Missing stub");
    const dx = adjacent.x - port.x;
    const dy = adjacent.y - port.y;
    const direction = outward(side);
    expect(dx * direction.y - dy * direction.x).toBeCloseTo(0, 6);
    expect(dx * direction.x + dy * direction.y).toBeGreaterThanOrEqual(
      PIPE_STUB_MIN - 1e-6,
    );
  }
  for (const [index, point] of points.entries()) {
    const prev = points[index - 1];
    if (prev)
      expect(Math.hypot(point.x - prev.x, point.y - prev.y)).toBeGreaterThan(
        0.5,
      );
  }
}

describe("PCB router", () => {
  it.each([options, { lanes: false, depth: false }])(
    "chamfers a Z while keeping both stubs with %o",
    (settings) => {
      const request = pipe("z", [0, 0], [300, 140]);
      const points =
        route({ pipes: [request], cards: [] }, settings).get(request.id)
          ?.points ?? [];
      expect(diagonals(points)).toHaveLength(2);
      expectStubs(request, points);
    },
  );

  it("merges a short jog into one diagonal", () => {
    const request = pipe("jog", [0, 0], [300, 20]);
    const points = route({ pipes: [request], cards: [] }, options).get(
      request.id,
    )?.points;
    expect(points).toEqual([
      { x: 0, y: 0 },
      { x: 140, y: 0 },
      { x: 160, y: 20 },
      { x: 300, y: 20 },
    ]);
  });

  it("keeps parallel diagonals apart through stacked plugs", () => {
    const pipes = [
      pipe("plug-1", [1643, 810], [1737, 888]),
      pipe("plug-2", [1643, 430], [1737, 936]),
      pipe("plug-3", [2523, 430], [1737, 984]),
    ];
    const cuts = [...route({ pipes, cards: [] }, options)].flatMap(
      ([id, { points, depth }]) =>
        diagonals(points).map((cut) => ({ ...cut, id, depth })),
    );
    expect(new Set(cuts.map(({ id }) => id)).size).toBe(3);
    for (const [index, a] of cuts.entries()) {
      for (const b of cuts.slice(index + 1)) {
        if (a.id === b.id || a.depth !== b.depth || a.slope !== b.slope)
          continue;
        if (Math.min(a.high, b.high) - Math.max(a.low, b.low) <= 1e-6) continue;
        expect(Math.abs(a.offset - b.offset)).toBeGreaterThanOrEqual(
          PIPE_LANE_MIN - 1e-6,
        );
      }
    }
  });

  it("falls back to square bends when duplicate short jogs share a layer", () => {
    const first = pipe("a", [0, 0], [300, 12]);
    const second = { ...first, id: "b" };
    const scene = { pipes: [first, second], cards: [] };
    const layout = route(scene, { lanes: false, depth: false });
    expect(
      [...layout.values()].map(({ points }) => diagonals(points).length).sort(),
    ).toEqual([0, 1]);
  });

  it("still chamfers at least half the routes in a grid", () => {
    const scene = gridScene(5, 4);
    const layout = route(scene, options);
    const chamfered = [...layout.values()].filter(
      ({ points }) => diagonals(points).length > 0,
    );
    expect(chamfered.length).toBeGreaterThanOrEqual(scene.pipes.length / 2);
  });

  it("keeps valid stubs when the elbow route has a nearly flat jog or vertical ports", () => {
    const pipes = [
      pipe("sub-unit", [0, 0], [300, 0.25]),
      {
        ...pipe("vertical", [0, 0], [30, 30]),
        sourceSide: Position.Bottom,
        targetSide: Position.Top,
      },
      { ...pipe("mixed", [0, 0], [30, 30]), targetSide: Position.Top },
    ];
    const layout = route({ pipes, cards: [] }, options);
    for (const request of pipes) {
      const points = layout.get(request.id)?.points ?? [];
      expectStubs(request, points);
      diagonals(points);
    }
  });
});
