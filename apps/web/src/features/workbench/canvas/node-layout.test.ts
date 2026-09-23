import { describe, expect, it } from "vitest";

import {
  clampNodeLayout,
  hydrateNodeLayout,
  LAYOUT_DIMENSION_MAX,
  mergeNodeLayout,
  serializeNodeLayout,
} from "./node-layout";

describe("node layout", () => {
  it("clamps to usable floors and the browser compositing ceiling", () => {
    expect(
      clampNodeLayout({
        width: 100,
        bodyHeight: 1000,
        appendixHeight: 50,
      }),
    ).toEqual({
      width: 260,
      bodyHeight: 1000,
      appendixHeight: 120,
    });
    expect(
      clampNodeLayout({
        width: LAYOUT_DIMENSION_MAX + 1,
        bodyHeight: LAYOUT_DIMENSION_MAX + 50,
        appendixHeight: LAYOUT_DIMENSION_MAX + 100,
      }),
    ).toEqual({
      width: LAYOUT_DIMENSION_MAX,
      bodyHeight: LAYOUT_DIMENSION_MAX,
      appendixHeight: LAYOUT_DIMENSION_MAX,
    });
  });

  it("returns null when no finite dimensions remain", () => {
    expect(clampNodeLayout({})).toBeNull();
    expect(clampNodeLayout({ width: Number.NaN })).toBeNull();
  });

  it("serializes and hydrates between canvas and saved-graph shapes", () => {
    const layout = {
      width: 420,
      bodyHeight: 180,
      appendixHeight: 320,
    };
    expect(serializeNodeLayout(layout)).toEqual({
      width: 420,
      body_height: 180,
      appendix_height: 320,
    });
    expect(
      hydrateNodeLayout({
        width: 420,
        body_height: 180,
        appendix_height: 320,
      }),
    ).toEqual(layout);
  });

  it("serializes partial layouts with explicit null dimensions", () => {
    expect(serializeNodeLayout({ width: 420 })).toEqual({
      width: 420,
      body_height: null,
      appendix_height: null,
    });
    expect(serializeNodeLayout(null)).toBeNull();
  });

  it("merges patches while preserving untouched dimensions", () => {
    expect(
      mergeNodeLayout({ width: 300, bodyHeight: 120 }, { appendixHeight: 400 }),
    ).toEqual({
      width: 300,
      bodyHeight: 120,
      appendixHeight: 400,
    });
  });
});
