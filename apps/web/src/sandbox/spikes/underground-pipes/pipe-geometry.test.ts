import { describe, expect, it } from "vitest";

import { twinPaths } from "./pipe-geometry";

describe("twinPaths", () => {
  it("leaves a clear gap and ignores duplicate router points", () => {
    expect(
      twinPaths(
        [
          { x: 0, y: 0 },
          { x: 0, y: 0 },
          { x: 20, y: 0 },
        ],
        0,
      ),
    ).toEqual({
      path: "M0,2.65 L20,2.65",
      twin: "M0,-2.65 L20,-2.65",
      centre: "M0,0 L20,0",
    });
  });

  it("rounds both strands at a diagonal turn", () => {
    const strands = twinPaths(
      [
        { x: 0, y: 0 },
        { x: 20, y: 0 },
        { x: 40, y: 20 },
      ],
      5,
    );
    expect(strands.path).toMatch(/^M0,2\.65 L.+ Q.+ L/);
    expect(strands.twin).toMatch(/^M0,-2\.65 L.+ Q.+ L/);
  });

  it("bends both strands around the centre line's corner", () => {
    const strands = twinPaths(
      [
        { x: 0, y: 0 },
        { x: 40, y: 0 },
        { x: 40, y: 40 },
      ],
      10,
    );
    // Concentric arcs start and end on the same perpendiculars.
    expect(numbers(strands.centre)).toEqual([
      0, 0, 30, 0, 40, 0, 40, 10, 40, 40,
    ]);
    expectClose(
      strands.path,
      [0, 2.65, 30, 2.65, 37.35, 2.65, 37.35, 10, 37.35, 40],
    );
    expectClose(
      strands.twin,
      [0, -2.65, 30, -2.65, 42.65, -2.65, 42.65, 10, 42.65, 40],
    );
  });
});

function numbers(path: string): number[] {
  return (path.match(/-?[\d.]+/g) ?? []).map(Number);
}

function expectClose(path: string, expected: number[]) {
  const actual = numbers(path);
  expect(actual).toHaveLength(expected.length);
  expected.forEach((value, index) => {
    expect(actual[index]).toBeCloseTo(value, 6);
  });
}
