import { Position } from "@xyflow/react";
import { describe, expect, it } from "vitest";

import { exitShape, withExits } from "./exits";
import { DEMO_SCENE, pipe } from "./scenes";

describe("exitShape", () => {
  it("leaves along the side while the target lies ahead", () => {
    expect(exitShape(200, 300)).toBe("side");
  });

  it("turns toward the other end when the target is behind", () => {
    expect(exitShape(-400, 300)).toBe("apart-down");
    expect(exitShape(-400, -300)).toBe("apart-up");
  });

  it("turns both ends the same way when they lie nearly level", () => {
    expect(exitShape(-400, 0)).toBe("under");
    expect(exitShape(-400, -10)).toBe("over");
  });

  it("turns when the target is nearly straight below", () => {
    expect(exitShape(10, 300)).toBe("apart-down");
  });

  it("keeps its shape until the ends move well past the line", () => {
    // Just past the line into side: a vertical pipe stays vertical.
    expect(exitShape(60, 300, "apart-down")).toBe("apart-down");
    expect(exitShape(80, 300, "apart-down")).toBe("side");
    // A side pipe stays a side pipe down to the line itself.
    expect(exitShape(54, 300, "side")).toBe("side");
    expect(exitShape(53, 300, "side")).toBe("apart-down");
    // Level ends keep the way they turned until clearly apart.
    expect(exitShape(-400, -15, "under")).toBe("under");
    expect(exitShape(-400, 70, "under")).toBe("under");
    expect(exitShape(-400, 80, "under")).toBe("apart-down");
    expect(exitShape(-400, 61, "apart-down")).toBe("apart-down");
    expect(exitShape(-400, 59, "apart-down")).toBe("under");
  });
});

describe("withExits", () => {
  it("leaves the scene alone with side exits", () => {
    expect(withExits(DEMO_SCENE, "side").scene).toBe(DEMO_SCENE);
  });

  it("rewrites only the sides of pipes that turn", () => {
    const { scene, shapes } = withExits(
      {
        cards: [],
        pipes: [
          pipe("ahead", [1000, 0], [1300, 100]),
          pipe("behind", [300, 0], [0, 200]),
        ],
      },
      "free",
    );
    expect(shapes.get("ahead")).toBe("side");
    expect(scene.pipes[0]?.sourceSide).toBe(Position.Right);
    expect(scene.pipes[1]).toMatchObject({
      sourceSide: Position.Bottom,
      targetSide: Position.Top,
    });
  });

  it("keeps the side of an end whose way out runs under another port", () => {
    const { scene } = withExits(
      {
        cards: [],
        pipes: [
          // Would turn up out of the lower of two stacked inputs.
          pipe("back", [300, -300], [0, 48]),
          pipe("stacked", [-300, 0], [0, 0]),
        ],
      },
      "free",
    );
    expect(scene.pipes[0]).toMatchObject({
      sourceSide: Position.Bottom,
      targetSide: Position.Left,
    });
  });
});
