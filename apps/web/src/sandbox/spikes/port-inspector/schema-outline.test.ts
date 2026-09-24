import { describe, expect, it } from "vitest";

import { GEO_MAP_LAYER_SCHEMA } from "../../fixtures/vector-map-layer";
import { findOutlineNode, schemaOutline } from "./schema-outline";

describe("schemaOutline", () => {
  const outline = schemaOutline(GEO_MAP_LAYER_SCHEMA);

  it("keeps top-level map layer fields", () => {
    expect(outline.map((node) => node.name)).toEqual([
      "title",
      "visible",
      "opacity",
      "min_zoom",
      "max_zoom",
      "source",
      "style",
    ]);
  });

  it("expands oneOf source kinds", () => {
    const source = outline.find((node) => node.name === "source");
    expect(source?.typeLabel).toBe("feature_collection | raster_scan | wms");
    expect(source?.children.map((node) => node.name)).toEqual([
      "as feature_collection",
      "as raster_scan",
      "as wms",
    ]);
    const wms = source?.children.find((node) => node.name === "as wms");
    expect(wms?.children.map((node) => node.name)).toContain("bounds");
    const bounds = wms?.children.find((node) => node.name === "bounds");
    expect(bounds?.children.map((node) => node.name)).toEqual([
      "West longitude",
      "South latitude",
      "East longitude",
      "North latitude",
    ]);
  });

  it("finds nested nodes by id", () => {
    const found = findOutlineNode(outline, "root/source/as:wms/url");
    expect(found?.name).toBe("url");
    expect(found?.typeLabel).toBe("str");
  });
});
