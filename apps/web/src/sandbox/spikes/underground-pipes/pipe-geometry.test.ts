import { describe, expect, it } from "vitest";

import {
  bandsPath,
  chamferPath,
  chevronsPath,
  evenStations,
  pointOnRun,
  routeBends,
  straightRuns,
} from "./pipe-geometry";

// Out to the right, down, and in to the right: two bends.
const Z_ROUTE = [
  { x: 0, y: 0 },
  { x: 100, y: 0 },
  { x: 100, y: 200 },
  { x: 300, y: 200 },
];

describe("routeBends", () => {
  it("finds each corner with its directions and the curve's reach", () => {
    const bends = routeBends(Z_ROUTE, 12);
    expect(bends).toHaveLength(2);
    expect(bends[0]).toEqual({
      corner: { x: 100, y: 0 },
      inward: { dx: 1, dy: 0 },
      outward: { dx: 0, dy: 1 },
      reach: 12,
    });
    expect(bends[1]?.outward).toEqual({ dx: 1, dy: 0 });
  });

  it("cuts the reach to half of a short leg", () => {
    const bends = routeBends(
      [
        { x: 0, y: 0 },
        { x: 10, y: 0 },
        { x: 10, y: 50 },
      ],
      12,
    );
    expect(bends[0]?.reach).toBe(5);
  });

  it("skips a point that does not turn", () => {
    expect(
      routeBends(
        [
          { x: 0, y: 0 },
          { x: 50, y: 0 },
          { x: 90, y: 0 },
        ],
        12,
      ),
    ).toEqual([]);
  });
});

describe("straightRuns", () => {
  it("trims each segment at its ports and bends", () => {
    const runs = straightRuns(Z_ROUTE, { endClear: 20, cornerClear: 15 });
    expect(runs).toHaveLength(3);
    expect(runs[0]).toMatchObject({
      from: { x: 20, y: 0 },
      to: { x: 85, y: 0 },
      length: 65,
    });
    expect(runs[1]).toMatchObject({
      from: { x: 100, y: 15 },
      to: { x: 100, y: 185 },
      dx: 0,
      dy: 1,
      length: 170,
    });
    expect(runs[2]).toMatchObject({ from: { x: 115, y: 200 }, length: 165 });
  });

  it("drops a segment the trims use up", () => {
    const runs = straightRuns(
      [
        { x: 0, y: 0 },
        { x: 30, y: 0 },
        { x: 30, y: 100 },
      ],
      { endClear: 20, cornerClear: 15 },
    );
    expect(runs).toHaveLength(1);
    expect(runs[0]?.dy).toBe(1);
  });
});

describe("evenStations", () => {
  it("spreads stations with half a gap at each end", () => {
    expect(evenStations(150, 70)).toEqual([37.5, 112.5]);
  });

  it("places none on a run shorter than the pitch", () => {
    expect(evenStations(60, 70)).toEqual([]);
  });
});

describe("pointOnRun", () => {
  it("walks along the run's direction", () => {
    const [, down] = straightRuns(Z_ROUTE, { endClear: 0, cornerClear: 0 });
    expect(down && pointOnRun(down, 40)).toEqual({ x: 100, y: 40 });
  });
});

describe("bandsPath", () => {
  it("draws a short dash along the direction at each station", () => {
    expect(
      bandsPath(
        [
          { at: { x: 10, y: 5 }, dx: 1, dy: 0 },
          { at: { x: 0, y: 40 }, dx: 0, dy: -1 },
        ],
        4,
      ),
    ).toBe("M8,5 L12,5 M0,42 L0,38");
  });
});

describe("chevronsPath", () => {
  it("points each chevron along its direction", () => {
    expect(chevronsPath([{ at: { x: 0, y: 0 }, dx: 1, dy: 0 }], 4)).toBe(
      "M-2,2 L2,0 L-2,-2",
    );
  });
});

describe("chamferPath", () => {
  it("cuts every bend at 45 degrees", () => {
    expect(chamferPath(Z_ROUTE, 8)).toBe(
      "M0,0 L92,0 L100,8 L100,192 L108,200 L300,200",
    );
  });

  it("draws a straight route as one line", () => {
    expect(
      chamferPath(
        [
          { x: 0, y: 0 },
          { x: 50, y: 0 },
        ],
        8,
      ),
    ).toBe("M0,0 L50,0");
  });
});
