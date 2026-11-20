import { describe, expect, it } from "vitest";

import type { GeoRenderDescriptor, GeoRenderLayer } from "@/lib/api";

import { createGeoMapStyle } from "./map-style";

describe("createGeoMapStyle", () => {
  it("omits attribution on raster sources when null so MapLibre accepts the style", () => {
    const layer: GeoRenderLayer = {
      id: "layer-1",
      title: "PGM arkusz 16",
      visible: true,
      opacity: 0.9,
      min_zoom: 0,
      max_zoom: 22,
      source: {
        kind: "raster",
        artifact_id: "00000000-0000-0000-0000-000000000001",
        tilejson_url: "/api/v1/workspaces/ws-1/artifacts/a1/geo/tilejson.json",
        bounds: [30, 54, 31, 55],
        attribution: null,
      },
      style: {
        kind: "raster",
        opacity: 1,
        brightness_min: 0,
        brightness_max: 1,
        contrast: 0,
        saturation: 0,
        hue: 0,
        resampling: "linear",
      },
    };
    const descriptor: GeoRenderDescriptor = {
      artifact_id: "00000000-0000-0000-0000-000000000002",
      kind: "map_document",
      basemap: "openstreetmap",
      initial_bounds: [30, 54, 31, 55],
      layers: [layer],
    };

    const style = createGeoMapStyle("ws-1", descriptor, [layer]);
    const rasterSource = style.sources["grafy-geo-source-layer-1"];
    expect(rasterSource).toBeDefined();
    expect(rasterSource && "attribution" in rasterSource).toBe(false);
  });
});
