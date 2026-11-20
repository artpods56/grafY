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
});
