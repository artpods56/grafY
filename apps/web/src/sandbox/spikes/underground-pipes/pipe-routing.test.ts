import { Position } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import {
  PIPE_LANE,
  PIPE_LANE_MIN,
  PIPE_STUB_MIN,
  routePipes,
  type PipeRequest,
  type Point,
} from "./pipe-routing";

function request(
  id: string,
  source: [number, number],
  target: [number, number],
): PipeRequest {
  return {
    id,
    source: { x: source[0], y: source[1] },
    sourceSide: Position.Right,
    target: { x: target[0], y: target[1] },
    targetSide: Position.Left,
  };
}

function verticalXs(points: readonly Point[]): number[] {
  const xs: number[] = [];
  for (let index = 0; index < points.length - 1; index += 1) {
    const start = points[index];
    const end = points[index + 1];
    if (start && end && start.x === end.x && start.y !== end.y) {
      xs.push(start.x);
    }
  }
  return xs;
}

/** The x where a pipe makes its last bend before entering its target. */
function lastBendX(routes: ReturnType<typeof routePipes>, id: string): number {
  return verticalXs(routes.get(id)?.points ?? []).at(-1) ?? Number.NaN;
}

describe("routePipes", () => {
  it("gives pipes into stacked plugs their own lanes, nearest plug innermost", () => {
    // Three sources behind the card loop back into three plugs one above another.
    const routes = routePipes([
      request("top", [700, 0], [500, 100]),
      request("middle", [720, 10], [500, 140]),
      request("bottom", [740, 20], [500, 180]),
    ]);

    expect(lastBendX(routes, "top")).toBeLessThanOrEqual(500 - PIPE_STUB_MIN);
    expect(lastBendX(routes, "top") - lastBendX(routes, "middle")).toBeCloseTo(
      PIPE_LANE,
    );
    expect(
      lastBendX(routes, "middle") - lastBendX(routes, "bottom"),
    ).toBeCloseTo(PIPE_LANE);
  });

  it("nests pipes into a card's plugs in the narrow gap between two columns", () => {
    // The stress grid: two from the column to the left, one looping back from
    // the right, into plugs 1, 2 and 3 of one card. The gap leaves 40 units.
    const routes = routePipes([
      request("plug-1", [1643, 810], [1737, 888]),
      request("plug-2", [1643, 430], [1737, 936]),
      request("plug-3", [2523, 430], [1737, 984]),
    ]);
    const one = lastBendX(routes, "plug-1");
    const two = lastBendX(routes, "plug-2");
    const three = lastBendX(routes, "plug-3");

    expect(one).toBeLessThanOrEqual(1737 - PIPE_STUB_MIN);
    expect(one - two).toBeGreaterThanOrEqual(PIPE_LANE_MIN - 1e-6);
    expect(two - three).toBeGreaterThanOrEqual(PIPE_LANE_MIN - 1e-6);
    for (const id of ["plug-1", "plug-2", "plug-3"]) {
      expect(routes.get(id)?.depth).toBe(0);
    }
  });

  it("sinks pipes a channel cannot hold to a deeper layer", () => {
    // Six pipes bend in a 94-wide gap: 40 units of room fit five lanes.
    const routes = routePipes(
      [0, 1, 2, 3, 4, 5].map((index) =>
        request(`p${index}`, [0, index * 10], [94, 200 + index * 10]),
      ),
    );
    const surface = [...routes.values()].filter((pipe) => pipe.depth === 0);
    const sunk = [...routes.values()].filter((pipe) => pipe.depth === 1);
    expect(sunk).toHaveLength(1);

    const xs = surface
      .map((pipe) => verticalXs(pipe.points)[0] ?? Number.NaN)
      .sort((a, b) => a - b);
    for (let index = 1; index < xs.length; index += 1) {
      expect((xs[index] ?? 0) - (xs[index - 1] ?? 0)).toBeGreaterThanOrEqual(
        PIPE_LANE_MIN - 1e-6,
      );
    }
  });

  it("splits two forward pipes that bend in the same channel", () => {
    const routes = routePipes([
      request("upper", [0, 0], [200, 100]),
      request("lower", [0, 50], [200, 150]),
    ]);
    // The upper pipe turns into its target first, so it takes the lane on that
    // side and the two never cross.
    expect(lastBendX(routes, "upper") - lastBendX(routes, "lower")).toBeCloseTo(
      PIPE_LANE,
    );
  });

  it("leaves a pipe with a channel of its own where it was", () => {
    const routes = routePipes([request("alone", [0, 0], [200, 100])]);
    expect(verticalXs(routes.get("alone")?.points ?? [])).toEqual([100]);
  });
});
