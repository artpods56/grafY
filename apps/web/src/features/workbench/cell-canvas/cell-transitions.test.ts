import { describe, expect, it } from "vitest";

import {
  CELL_PIPE_STUB_MIN,
  CELL_SIZE,
  type CellDir,
  type WorldPoint,
} from "./cell-model";
import {
  MAGNETIC_TUG_MAX_PX,
  SETTLE_DURATION_MS,
  anchorPipeEndpoints,
  createCardSettle,
  easeOutCubic,
  interpolatePoint,
  magneticTugOffset,
  morphPipePoints,
  retargetCardSettle,
  snapCellWithHysteresis,
  stepCardSettle,
} from "./cell-transitions";

function at(col: number, row = 0): WorldPoint {
  return { x: col * CELL_SIZE, y: row * CELL_SIZE };
}

function expectOrthogonal(points: readonly WorldPoint[]): void {
  for (let index = 1; index < points.length; index += 1) {
    const a = points[index - 1];
    const b = points[index];
    if (!a || !b) throw new Error("missing point");
    const horizontal = Math.abs(a.y - b.y) < 1e-6;
    const vertical = Math.abs(a.x - b.x) < 1e-6;
    expect(
      horizontal || vertical,
      `segment ${index} ${JSON.stringify(a)} -> ${JSON.stringify(b)}`,
    ).toBe(true);
  }
}

const OUT: Record<CellDir, WorldPoint> = {
  left: { x: -1, y: 0 },
  right: { x: 1, y: 0 },
  top: { x: 0, y: -1 },
  bottom: { x: 0, y: 1 },
};

/** Length of the first run from `port` towards `next`, along `exit`. */
function stubLength(
  port: WorldPoint,
  next: WorldPoint | undefined,
  exit: CellDir,
): number {
  if (!next) throw new Error("missing stub end");
  const out = OUT[exit];
  expect(Math.abs((next.x - port.x) * out.y - (next.y - port.y) * out.x)).toBe(
    0,
  );
  return (next.x - port.x) * out.x + (next.y - port.y) * out.y;
}

describe("snapCellWithHysteresis", () => {
  it("keeps the current cell until 0.62 cells away", () => {
    expect(snapCellWithHysteresis(at(2.55, 4), { col: 2, row: 4 })).toEqual({
      col: 2,
      row: 4,
    });
    expect(snapCellWithHysteresis(at(2.63, 4), { col: 2, row: 4 })).toEqual({
      col: 3,
      row: 4,
    });
  });

  it("does not chatter when the pointer comes back over the boundary", () => {
    const current = { col: 3, row: 1 };
    expect(snapCellWithHysteresis(at(2.45, 1), current).col).toBe(3);
    expect(snapCellWithHysteresis(at(2.39, 1), current).col).toBe(3);
    expect(snapCellWithHysteresis(at(2.36, 1), current).col).toBe(2);
  });

  it("treats each axis on its own", () => {
    expect(snapCellWithHysteresis(at(2.7, 5.55), { col: 2, row: 5 })).toEqual({
      col: 3,
      row: 5,
    });
    expect(snapCellWithHysteresis(at(2.4, 5.7), { col: 2, row: 5 })).toEqual({
      col: 2,
      row: 6,
    });
  });

  it("lands on the pointer's cell after a fast jump", () => {
    expect(snapCellWithHysteresis(at(7.2, -3.9), { col: 2, row: 1 })).toEqual({
      col: 7,
      row: -4,
    });
  });

  it("handles negative coordinates without -0", () => {
    expect(snapCellWithHysteresis(at(-0.55), { col: 0, row: 0 }).col).toBe(0);
    expect(snapCellWithHysteresis(at(-0.7), { col: 0, row: 0 }).col).toBe(-1);
    const back = snapCellWithHysteresis(at(-0.2, -0.3), { col: -1, row: -1 });
    expect(back).toEqual({ col: 0, row: 0 });
    expect(Object.is(back.col, -0)).toBe(false);
    expect(Object.is(back.row, -0)).toBe(false);
    const stay = snapCellWithHysteresis(at(0.3, -0.3), { col: -0, row: -0 });
    expect(Object.is(stay.col, -0)).toBe(false);
    expect(Object.is(stay.row, -0)).toBe(false);
  });
});

describe("magneticTugOffset", () => {
  it("leans 15% of the way towards the pointer", () => {
    const tug = magneticTugOffset({ x: 120, y: 90 }, { col: 2, row: 2 });
    expect(tug.x).toBeCloseTo(3);
    expect(tug.y).toBeCloseTo(-1.5);
  });

  it("clamps the lean to 6px", () => {
    expect(magneticTugOffset({ x: 200, y: -50 }, { col: 2, row: 1 })).toEqual({
      x: MAGNETIC_TUG_MAX_PX,
      y: -MAGNETIC_TUG_MAX_PX,
    });
  });

  it("is exactly zero on the cell origin", () => {
    const tug = magneticTugOffset({ x: -50, y: 0 }, { col: -1, row: 0 });
    expect(Object.is(tug.x, -0)).toBe(false);
    expect(tug).toEqual({ x: 0, y: 0 });
  });
});

describe("easing", () => {
  it("eases out cubically and clamps", () => {
    expect(easeOutCubic(-1)).toBe(0);
    expect(easeOutCubic(0)).toBe(0);
    expect(easeOutCubic(0.5)).toBeCloseTo(0.875);
    expect(easeOutCubic(1)).toBe(1);
    expect(easeOutCubic(2)).toBe(1);
  });

  it("interpolates points linearly", () => {
    expect(interpolatePoint({ x: 0, y: 10 }, { x: 10, y: 30 }, 0.25)).toEqual({
      x: 2.5,
      y: 15,
    });
  });
});

describe("anchorPipeEndpoints", () => {
  const straight = [
    { x: 325, y: 75 },
    { x: 425, y: 75 },
  ];

  it("returns a copy when the ports have not moved", () => {
    const result = anchorPipeEndpoints(
      straight,
      { x: 325, y: 75 },
      "right",
      { x: 425, y: 75 },
      "left",
    );
    expect(result).toEqual(straight);
    expect(result).not.toBe(straight);
  });

  it("keeps a straight pipe straight while its ends line up", () => {
    const source = { x: 330, y: 75 };
    const target = { x: 421, y: 75 };
    expect(
      anchorPipeEndpoints(straight, source, "right", target, "left"),
    ).toEqual([source, target]);
  });

  it("grows a Z-bend instead of a diagonal when an end moves off axis", () => {
    const source = { x: 327, y: 78 };
    const target = { x: 425, y: 75 };
    const result = anchorPipeEndpoints(
      straight,
      source,
      "right",
      target,
      "left",
    );
    expect(result).toEqual([
      source,
      { x: 376, y: 78 },
      { x: 376, y: 75 },
      target,
    ]);
    expectOrthogonal(result);
  });

  it("jogs between full stubs when the ports are too close for a Z", () => {
    const source = { x: 400, y: 78 };
    const target = { x: 425, y: 75 };
    const result = anchorPipeEndpoints(
      straight,
      source,
      "right",
      target,
      "left",
    );
    expectOrthogonal(result);
    expect(result[0]).toEqual(source);
    expect(result.at(-1)).toEqual(target);
    expect(stubLength(source, result[1], "right")).toBeGreaterThanOrEqual(
      CELL_PIPE_STUB_MIN,
    );
    expect(stubLength(target, result.at(-2), "left")).toBeGreaterThanOrEqual(
      CELL_PIPE_STUB_MIN,
    );
  });

  // Out right from (325, 75), down a track at x 375, along row 275, down at
  // x 625, into the input at (675, 325).
  const routed: WorldPoint[] = [
    { x: 325, y: 75 },
    { x: 375, y: 75 },
    { x: 375, y: 275 },
    { x: 625, y: 275 },
    { x: 625, y: 325 },
    { x: 675, y: 325 },
  ];

  it("slides the stub corners along the inner run for a small tug", () => {
    const source = { x: 329, y: 80 };
    const target = { x: 671, y: 322 };
    const result = anchorPipeEndpoints(routed, source, "right", target, "left");
    expect(result).toEqual([
      source,
      { x: 375, y: 80 },
      { x: 375, y: 275 },
      { x: 625, y: 275 },
      { x: 625, y: 322 },
      target,
    ]);
    expectOrthogonal(result);
  });

  it("keeps full stubs when a port moves past its corner", () => {
    const source = { x: 360, y: 72 };
    const target = { x: 640, y: 328 };
    const result = anchorPipeEndpoints(routed, source, "right", target, "left");
    expectOrthogonal(result);
    expect(result[0]).toEqual(source);
    expect(result.at(-1)).toEqual(target);
    expect(stubLength(source, result[1], "right")).toBeGreaterThanOrEqual(
      CELL_PIPE_STUB_MIN,
    );
    expect(stubLength(target, result.at(-2), "left")).toBeGreaterThanOrEqual(
      CELL_PIPE_STUB_MIN,
    );
    // The inner run along row 275 survives.
    expect(result.some((point) => point.y === 275)).toBe(true);
  });

  it("keeps a Z route orthogonal when both ends shift", () => {
    const z = [
      { x: 325, y: 75 },
      { x: 400, y: 75 },
      { x: 400, y: 175 },
      { x: 475, y: 175 },
    ];
    const source = { x: 331, y: 70 };
    const target = { x: 470, y: 179 };
    const result = anchorPipeEndpoints(z, source, "right", target, "left");
    expect(result).toEqual([
      source,
      { x: 400, y: 70 },
      { x: 400, y: 179 },
      target,
    ]);
  });

  it("falls back to an orthogonal link when a narrow Z cannot hold both stubs", () => {
    const z = [
      { x: 325, y: 75 },
      { x: 360, y: 75 },
      { x: 360, y: 175 },
      { x: 395, y: 175 },
    ];
    const source = { x: 340, y: 75 };
    const target = { x: 380, y: 175 };
    const result = anchorPipeEndpoints(z, source, "right", target, "left");
    expectOrthogonal(result);
    expect(stubLength(source, result[1], "right")).toBeGreaterThanOrEqual(
      CELL_PIPE_STUB_MIN,
    );
    expect(stubLength(target, result.at(-2), "left")).toBeGreaterThanOrEqual(
      CELL_PIPE_STUB_MIN,
    );
  });

  it("re-corners an L route between a side port and a free exit", () => {
    const l = [
      { x: 325, y: 75 },
      { x: 525, y: 75 },
      { x: 525, y: 225 },
    ];
    const source = { x: 325, y: 79 };
    const target = { x: 529, y: 225 };
    const result = anchorPipeEndpoints(l, source, "right", target, "top");
    expect(result).toEqual([source, { x: 529, y: 79 }, target]);
  });
});

describe("morphPipePoints", () => {
  const from = [
    { x: 0, y: 0 },
    { x: 200, y: 0 },
  ];
  const to = [
    { x: 0, y: 0 },
    { x: 100, y: 0 },
    { x: 100, y: 100 },
    { x: 200, y: 100 },
  ];

  it("returns exact copies at either end", () => {
    const start = morphPipePoints(from, to, 0);
    expect(start).toEqual(from);
    expect(start).not.toBe(from);
    expect(morphPipePoints(from, to, -1)).toEqual(from);
    expect(morphPipePoints(from, to, 1)).toEqual(to);
    expect(morphPipePoints(from, to, 1.5)).toEqual(to);
  });

  it("keeps the ends on their ports while the middle bends", () => {
    const mid = morphPipePoints(from, to, 0.5);
    expect(mid[0]).toEqual({ x: 0, y: 0 });
    const eased = easeOutCubic(0.5);
    const end = mid.at(-1);
    expect(end?.x).toBeCloseTo(200);
    expect(end?.y).toBeCloseTo(100 * eased);
    // The straight pipe was given stubs, so its first run stays level.
    expect(mid[1]?.y).toBeCloseTo(0);
    expect(mid[1]?.x).toBeGreaterThan(0);
    expect(mid.length).toBeGreaterThan(2);
  });

  it("moves matching routes corner by corner", () => {
    const a = [
      { x: 0, y: 0 },
      { x: 50, y: 0 },
      { x: 50, y: 100 },
      { x: 150, y: 100 },
    ];
    const b = [
      { x: 0, y: 0 },
      { x: 80, y: 0 },
      { x: 80, y: 100 },
      { x: 150, y: 100 },
    ];
    const mid = morphPipePoints(a, b, 0.5);
    const eased = easeOutCubic(0.5);
    expect(mid).toHaveLength(4);
    expect(mid[1]?.x).toBeCloseTo(50 + 30 * eased);
    expect(mid[2]?.x).toBeCloseTo(50 + 30 * eased);
    expectOrthogonal(mid);
  });

  it("handles routes with different corner counts", () => {
    const bent = [
      { x: 0, y: 0 },
      { x: 40, y: 0 },
      { x: 40, y: 60 },
      { x: 120, y: 60 },
      { x: 120, y: 160 },
      { x: 200, y: 160 },
    ];
    const target = [
      { x: 0, y: 0 },
      { x: 100, y: 0 },
      { x: 100, y: 160 },
      { x: 200, y: 160 },
    ];
    for (const progress of [0.1, 0.5, 0.9]) {
      const mid = morphPipePoints(bent, target, progress);
      expect(mid[0]).toEqual({ x: 0, y: 0 });
      expect(mid.at(-1)?.x).toBeCloseTo(200);
      expect(mid.at(-1)?.y).toBeCloseTo(160);
      for (const point of mid) {
        expect(Number.isFinite(point.x) && Number.isFinite(point.y)).toBe(true);
      }
    }
  });
});

describe("card settle", () => {
  it("starts at rest on its origin", () => {
    const state = createCardSettle({ x: 100, y: 50 });
    expect(state.active).toBe(false);
    expect(state.current).toEqual({ x: 100, y: 50 });
    expect(state.durationMs).toBe(SETTLE_DURATION_MS);
    expect(stepCardSettle(state, 500)).toBe(state);
  });

  it("glides monotonically with an ease-out cubic", () => {
    const start = retargetCardSettle(
      createCardSettle({ x: 0, y: 0 }),
      { x: 50, y: 100 },
      1000,
    );
    expect(start.active).toBe(true);
    let previous = 0;
    for (let ms = 0; ms < SETTLE_DURATION_MS; ms += 10) {
      const frame = stepCardSettle(start, 1000 + ms);
      expect(frame.active).toBe(true);
      expect(frame.current.x).toBeGreaterThanOrEqual(previous);
      expect(frame.current.y).toBeCloseTo(frame.current.x * 2);
      expect(frame.current.x).toBeCloseTo(
        50 * easeOutCubic(ms / SETTLE_DURATION_MS),
      );
      previous = frame.current.x;
    }
  });

  it("lands exactly on the target and goes inactive", () => {
    const start = retargetCardSettle(
      createCardSettle({ x: 0, y: 0 }),
      { x: 50, y: 100 },
      1000,
    );
    for (const now of [1000 + SETTLE_DURATION_MS, 5000]) {
      const done = stepCardSettle(start, now);
      expect(done.active).toBe(false);
      expect(done.current).toEqual({ x: 50, y: 100 });
    }
  });

  it("retargets mid-flight from where the card is drawn", () => {
    const first = retargetCardSettle(
      createCardSettle({ x: 0, y: 0 }),
      { x: 100, y: 0 },
      0,
    );
    const midway = stepCardSettle(first, 60).current;
    const second = retargetCardSettle(first, { x: 0, y: 50 }, 60);
    expect(second.from).toEqual(midway);
    expect(stepCardSettle(second, 60).current).toEqual(midway);
    // One frame later the card has barely moved: no jump on retarget.
    const next = stepCardSettle(second, 61).current;
    expect(Math.hypot(next.x - midway.x, next.y - midway.y)).toBeLessThan(5);
    const done = stepCardSettle(second, 60 + SETTLE_DURATION_MS);
    expect(done.current).toEqual({ x: 0, y: 50 });
    expect(done.active).toBe(false);
  });

  it("does not animate a hop too small to see", () => {
    const state = retargetCardSettle(
      createCardSettle({ x: 10, y: 10 }),
      { x: 10.01, y: 10 },
      0,
    );
    expect(state.active).toBe(false);
    expect(state.current).toEqual({ x: 10.01, y: 10 });
  });

  it("finishes at once with no duration", () => {
    const state = retargetCardSettle(
      createCardSettle({ x: 0, y: 0 }),
      { x: 50, y: 0 },
      0,
      0,
    );
    expect(stepCardSettle(state, 0).current).toEqual({ x: 50, y: 0 });
  });
});
