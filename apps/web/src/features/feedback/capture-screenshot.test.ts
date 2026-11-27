import { describe, expect, it } from "vitest";

import { screenshotCrop } from "./capture-screenshot";

describe("screenshotCrop", () => {
  it("pads the element and stays inside the viewport", () => {
    expect(
      screenshotCrop(
        { x: 10, y: 300, width: 100, height: 40 },
        { width: 800, height: 600 },
      ),
    ).toEqual({ x: 0, y: 252, width: 158, height: 136 });
  });

  it("keeps a box for an element outside the viewport", () => {
    const crop = screenshotCrop(
      { x: 2000, y: 2000, width: 10, height: 10 },
      { width: 800, height: 600 },
    );
    expect(crop.width).toBe(1);
    expect(crop.height).toBe(1);
  });
});
