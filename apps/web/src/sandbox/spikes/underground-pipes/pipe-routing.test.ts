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

  it("sinks a pass-through pipe instead of a longer pipe ending beside the channel", () => {
    // `terminal` is far longer overall, yet terminates at y=50 right beside the
    // crowded stretch around y=25. Only `through` passes straight past it.
    const routes = routePipes([
      request("terminal", [0, -1000], [64, 50]),
      request("through", [0, -220], [64, 280]),
      request("local", [0, 0], [64, 60]),
    ]);

    expect(routes.get("terminal")?.depth).toBe(0);
    expect(routes.get("local")?.depth).toBe(0);
    expect(routes.get("through")?.depth).toBe(1);
  });

  it("keeps every pipe shallow when only local port approaches crowd a gap", () => {
    const routes = routePipes([
      request("one", [0, 0], [54, 50]),
      request("two", [0, 5], [54, 55]),
    ]);

    expect([...routes.values()].map((pipe) => pipe.depth)).toEqual([0, 0]);
  });

  it("prefers sinking a pipe with clear margin over one bending just past the bottleneck", () => {
    // Gap width 64 leaves room=10 (capacity 2). Both `just-past` and `clear`
    // avoid the immediate port reach, yet `clear` passes squarely through the
    // bottleneck while `just-past` turns into a port right below it.
    const routes = routePipes([
      request("just-past", [0, -900], [64, 90]),
      request("clear", [0, -260], [64, 260]),
      request("local", [0, 0], [64, 50]),
    ]);

    expect(routes.get("local")?.depth).toBe(0);
    expect(routes.get("just-past")?.depth).toBe(0);
    expect(routes.get("clear")?.depth).toBe(1);
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
