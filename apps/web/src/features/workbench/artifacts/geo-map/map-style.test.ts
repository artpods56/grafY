/**
 * These tests run the generated MapLibre style through the real style-spec
 * validator instead of a hand-written expectation of each key.
 *
 * The card suite mocks `maplibre-gl`, so a style was only ever compared with
 * what its author expected and one that MapLibre refuses on load still passed:
 * a raster source built from a TileJSON without attribution carried
 * `attribution: undefined`, which the optional TypeScript property accepts and
 * the spec does not (`sources.<id>.attribution: string expected, undefined
 * found`). No test here constructs a map, so this file leaves `maplibre-gl`
 * un-mocked and hands every emitted style to `validateStyleMin` — the check the
 * library itself makes when a style loads.
 */
import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import type { Map as MapLibreMap } from "maplibre-gl";
import { describe, expect, it } from "vitest";

import type { GeoBounds, GeoRenderDescriptor, GeoRenderLayer } from "@/lib/api";

import type { ArtifactViewerIncomingBinding } from "../artifact-interactions";
import {
  applyInteractionOverrides,
  applyLayerOverrides,
} from "./layer-overrides";
import { layerId } from "./layer-identity";
import { createGeoMapStyle } from "./map-style";
import { OSM_LAYER_ID, OSM_SOURCE_ID } from "./style-constants";

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const BOUNDS: GeoBounds = [-180, -85, 180, 85];

const TILEJSON_URL =
  "/api/v1/workspaces/11111111-1111-4111-8111-111111111111/artifacts/44444444-4444-4444-8444-444444444444/tilejson.json";
const OTHER_TILEJSON_URL =
  "/api/v1/workspaces/11111111-1111-4111-8111-111111111111/artifacts/66666666-6666-4666-8666-666666666666/tilejson.json";

// --- Fixtures ---------------------------------------------------------------

/** One raster layer: a tilejson the map fetches by tile, as every layer now is. */
function rasterLayer(
  attribution: string | null = null,
  mutate: (layer: GeoRenderLayer) => GeoRenderLayer = (layer) => layer,
): GeoRenderLayer {
  return mutate({
    id: "layer-raster",
    title: "Scan",
    visible: true,
    opacity: 1,
    min_zoom: 0,
    max_zoom: 18,
    source: {
      kind: "raster",
      artifact_id: "44444444-4444-4444-8444-444444444444",
      attribution,
      bounds: BOUNDS,
      tilejson_url: TILEJSON_URL,
    },
    style: {
      kind: "raster",
      opacity: 0.75,
      brightness_min: 0.1,
      brightness_max: 0.9,
      contrast: 0.2,
      saturation: -0.1,
      hue: 12,
      resampling: "nearest",
    },
  });
}

/** A second raster, so a composed map has more than one layer to order. */
function otherRasterLayer(
  attribution: string | null = "© survey",
  mutate: (layer: GeoRenderLayer) => GeoRenderLayer = (layer) => layer,
): GeoRenderLayer {
  return mutate(
    rasterLayer(attribution, (layer) => ({
      ...layer,
      id: "layer-mosaic",
      title: "Mosaic",
      min_zoom: 3,
      max_zoom: 20,
      source: {
        ...layer.source,
        artifact_id: "66666666-6666-4666-8666-666666666666",
        tilejson_url: OTHER_TILEJSON_URL,
      },
    })),
  );
}

/** A TileJSON with no attribution at all reaches the client without the key. */
function withoutAttributionKey(layer: GeoRenderLayer): GeoRenderLayer {
  const source = { ...layer.source } as unknown as Record<string, unknown>;
  delete source.attribution;
  return { ...layer, source } as GeoRenderLayer;
}

function descriptor(
  basemap: GeoRenderDescriptor["basemap"],
  layers: readonly GeoRenderLayer[],
): GeoRenderDescriptor {
  return {
    artifact_id: "55555555-5555-4555-8555-555555555555",
    kind: "map_layer",
    basemap,
    initial_bounds: BOUNDS,
    layers,
  };
}

// --- Reading a style back ---------------------------------------------------

type StyleObject = ReturnType<typeof createGeoMapStyle>;

/** The property bag of a source, read without the union's objections. */
type SourceRecord = Record<string, unknown>;

/** One emitted layer, read as the plain object the validator sees. */
type LayerRecord = {
  id: string;
  type?: string;
  source?: string;
  minzoom?: number;
  maxzoom?: number;
  filter?: unknown;
  layout?: Record<string, unknown>;
  paint?: Record<string, unknown>;
};

function sourceOf(style: StyleObject, id: string): SourceRecord {
  const sources = style.sources as unknown as Record<string, SourceRecord>;
  const source = sources[id];
  if (!source) throw new Error(`style has no source ${id}`);
  return source;
}

function layerOf(style: StyleObject, id: string): LayerRecord {
  const layer = style.layers.find((candidate) => candidate.id === id);
  if (!layer) throw new Error(`style has no layer ${id}`);
  return layer as unknown as LayerRecord;
}

function styleErrors(style: StyleObject): string[] {
  return validateStyleMin(style).map((error: unknown) => {
    const message = (error as { message?: unknown })?.message;
    return typeof message === "string" ? message : String(error);
  });
}

/**
 * Every key the style carries must hold a value the spec can read. An
 * `undefined` survives `tsc` because the property is optional, and is dropped by
 * `JSON.stringify`, so the object handed to MapLibre and the JSON the browser
 * would send are two different styles — which is how issue #259 reached a
 * runtime crash with a green suite.
 */
function undefinedStylePaths(style: unknown, path = "style"): string[] {
  if (Array.isArray(style)) {
    return style.flatMap((item, index) =>
      undefinedStylePaths(item, `${path}[${index}]`),
    );
  }
  if (!style || typeof style !== "object") return [];
  return Object.entries(style).flatMap(([key, value]) =>
    value === undefined
      ? [`${path}.${key}`]
      : undefinedStylePaths(value, `${path}.${key}`),
  );
}

function build(
  basemap: GeoRenderDescriptor["basemap"],
  layers: readonly GeoRenderLayer[],
): StyleObject {
  return createGeoMapStyle(WORKSPACE_ID, descriptor(basemap, layers), layers);
}

/**
 * The map surface `applyLayerOverrides` and `applyInteractionOverrides` use,
 * writing straight through to a style object so the edits a live map would take
 * are validated by the style spec rather than asserted by hand. Every method
 * reads and writes the same layer list, so an override that addresses a layer
 * the style does not carry is skipped exactly as the helpers skip it against a
 * real map.
 */
function styleAsMap(style: StyleObject) {
  const layers = style.layers as unknown as LayerRecord[];
  const index = new Map(layers.map((layer) => [layer.id, layer]));
  const mustGet = (id: string): LayerRecord => {
    const layer = index.get(id);
    if (!layer) throw new Error(`style has no layer ${id}`);
    return layer;
  };
  return {
    getLayer: (id: string) => index.get(id) ?? null,
    setLayoutProperty(id: string, name: string, value: unknown) {
      const layout = (mustGet(id).layout ??= {});
      layout[name] = value;
    },
    setPaintProperty(id: string, name: string, value: unknown) {
      const paint = (mustGet(id).paint ??= {});
      paint[name] = value;
    },
    setFilter(id: string, filter: unknown) {
      mustGet(id).filter = filter;
    },
    setLayerZoomRange(id: string, minzoom: number, maxzoom: number) {
      const layer = mustGet(id);
      layer.minzoom = minzoom;
      layer.maxzoom = maxzoom;
    },
    moveLayer(id: string) {
      const layer = mustGet(id);
      const at = layers.indexOf(layer);
      layers.splice(at, 1);
      layers.push(layer);
    },
  } as unknown as MapLibreMap;
}

const SELECTION: ArtifactViewerIncomingBinding[] = [
  {
    bindingId: "binding-1",
    effects: ["filter", "highlight"],
    sourceSelectionCount: 2,
    rows: [{ kind: "city", population: 1200, capital: true }, { kind: "town" }],
  },
];

describe("createGeoMapStyle", () => {
  it("keeps a style with no basemap and no layers valid", () => {
    const style = build("none", []);
    expect(style.sources).toEqual({});
    expect(style.layers).toEqual([]);
    expect(styleErrors(style)).toEqual([]);
  });

  describe("raster sources", () => {
    it.each([
      ["null attribution", rasterLayer(null)],
      ["empty attribution", rasterLayer("")],
      ["whitespace attribution", rasterLayer("   ")],
      ["absent attribution key", withoutAttributionKey(rasterLayer(null))],
    ])("omits attribution for %s", (_name, layer) => {
      const style = build("none", [layer]);
      const source = sourceOf(style, "grafy-geo-source-layer-raster");

      expect("attribution" in source).toBe(false);
      expect(undefinedStylePaths(style)).toEqual([]);
      expect(styleErrors(style)).toEqual([]);
    });

    it("carries a real attribution through, stripped of surrounding space", () => {
      const style = build("none", [rasterLayer("  © survey office  ")]);
      const source = sourceOf(style, "grafy-geo-source-layer-raster");

      expect(source.attribution).toBe("© survey office");
      expect(styleErrors(style)).toEqual([]);
    });

    it("points the source at the tilejson and paints the raster layer", () => {
      const layer = rasterLayer("© survey", (candidate) => ({
        ...candidate,
        opacity: 0.5,
      }));
      const style = build("none", [layer]);
      const source = sourceOf(style, "grafy-geo-source-layer-raster");
      const raster = layerOf(style, "grafy-geo-layer-raster-raster");

      expect(source.type).toBe("raster");
      expect(source.url).toBe(TILEJSON_URL);
      expect(source.tileSize).toBe(256);
      expect(raster.type).toBe("raster");
      expect(raster.source).toBe("grafy-geo-source-layer-raster");
      expect(raster.minzoom).toBe(0);
      expect(raster.maxzoom).toBe(18);
      expect(raster.layout?.visibility).toBe("visible");
      // Layer opacity 0.5 × raster opacity 0.75.
      expect(raster.paint?.["raster-opacity"]).toBeCloseTo(0.375, 10);
      expect(raster.paint?.["raster-brightness-min"]).toBe(0.1);
      expect(raster.paint?.["raster-brightness-max"]).toBe(0.9);
      expect(raster.paint?.["raster-contrast"]).toBe(0.2);
      expect(raster.paint?.["raster-saturation"]).toBe(-0.1);
      expect(raster.paint?.["raster-hue-rotate"]).toBe(12);
      expect(raster.paint?.["raster-resampling"]).toBe("nearest");
      expect(styleErrors(style)).toEqual([]);
    });

    it("hides a raster layer the card switched off", () => {
      const style = build("none", [
        rasterLayer(null, (candidate) => ({ ...candidate, visible: false })),
      ]);

      expect(
        layerOf(style, "grafy-geo-layer-raster-raster").layout?.visibility,
      ).toBe("none");
      expect(styleErrors(style)).toEqual([]);
    });

    it("keeps an invisible layer in the style rather than dropping it", () => {
      const style = build("none", [
        rasterLayer(null, (candidate) => ({ ...candidate, visible: false })),
        otherRasterLayer(),
      ]);

      expect(style.layers.map((candidate) => candidate.id)).toEqual([
        "grafy-geo-layer-raster-raster",
        "grafy-geo-layer-mosaic-raster",
      ]);
      expect(
        layerOf(style, "grafy-geo-layer-raster-raster").layout?.visibility,
      ).toBe("none");
      expect(
        layerOf(style, "grafy-geo-layer-mosaic-raster").layout?.visibility,
      ).toBe("visible");
      expect(styleErrors(style)).toEqual([]);
    });
  });

  describe("composed maps", () => {
    const layers = [rasterLayer("© survey"), otherRasterLayer()];

    it("adds the openstreetmap basemap underneath the data layers", () => {
      const style = build("openstreetmap", layers);

      expect(Object.keys(style.sources)).toEqual([
        OSM_SOURCE_ID,
        "grafy-geo-source-layer-raster",
        "grafy-geo-source-layer-mosaic",
      ]);
      const basemapSource = sourceOf(style, OSM_SOURCE_ID);
      expect(basemapSource.attribution).toBe("© OpenStreetMap contributors");
      expect(style.layers.map((layer) => layer.id)).toEqual([
        OSM_LAYER_ID,
        "grafy-geo-layer-raster-raster",
        "grafy-geo-layer-mosaic-raster",
      ]);
      expect(styleErrors(style)).toEqual([]);
    });

    it("omits the openstreetmap source and layer when the basemap is none", () => {
      const style = build("none", layers);

      expect(Object.keys(style.sources)).not.toContain(OSM_SOURCE_ID);
      expect(style.layers.map((layer) => layer.id)).not.toContain(OSM_LAYER_ID);
      expect(styleErrors(style)).toEqual([]);
    });

    it("keeps every source and layer id unique", () => {
      const style = build("openstreetmap", [
        ...layers,
        rasterLayer(null, (layer) => ({ ...layer, id: "layer-raster-2" })),
        otherRasterLayer(null, (layer) => ({ ...layer, id: "layer-mosaic-2" })),
      ]);
      const layerIds = style.layers.map((layer) => layer.id);
      const sourceIds = Object.keys(style.sources);

      expect(new Set(layerIds).size).toBe(layerIds.length);
      expect(new Set(sourceIds).size).toBe(sourceIds.length);
      expect(styleErrors(style)).toEqual([]);
    });

    it.each([
      ["openstreetmap", "openstreetmap"],
      ["none", "none"],
    ] as const)(
      "validates a one-layer and a many-layer map on the %s basemap",
      (_label, basemap) => {
        const cases: GeoRenderLayer[][] = [
          [rasterLayer(null)],
          [rasterLayer("© survey"), otherRasterLayer()],
          [otherRasterLayer(), rasterLayer(null)],
        ];
        for (const caseLayers of cases) {
          const style = build(basemap, caseLayers);
          expect(styleErrors(style)).toEqual([]);
          expect(undefinedStylePaths(style)).toEqual([]);
        }
      },
    );
  });

  describe("overrides applied before the style is read back", () => {
    it("keeps the style valid after applyLayerOverrides repaints it", () => {
      const layers = [
        rasterLayer("© survey"),
        otherRasterLayer(null, (layer) => ({ ...layer, visible: false })),
      ];
      const style = build("openstreetmap", layers);

      applyLayerOverrides(styleAsMap(style), layers);

      expect(styleErrors(style)).toEqual([]);
      expect(undefinedStylePaths(style)).toEqual([]);
      expect(
        layerOf(style, "grafy-geo-layer-mosaic-raster").layout?.visibility,
      ).toBe("none");
      expect(
        layerOf(style, "grafy-geo-layer-raster-raster").layout?.visibility,
      ).toBe("visible");
    });

    it("re-draws the layers an override moved in the card list", () => {
      const first = rasterLayer("© survey");
      const second = otherRasterLayer();
      const style = build("none", [first, second]);

      applyLayerOverrides(styleAsMap(style), [second, first]);

      expect(style.layers.map((layer) => layer.id)).toEqual([
        "grafy-geo-layer-mosaic-raster",
        "grafy-geo-layer-raster-raster",
      ]);
      expect(styleErrors(style)).toEqual([]);
    });

    it("keeps zoom-range and opacity edits inside the spec", () => {
      const layer = rasterLayer("© survey", (candidate) => ({
        ...candidate,
        opacity: 0.4,
        min_zoom: 4,
        max_zoom: 9,
      }));
      const style = build("none", [layer]);

      applyLayerOverrides(styleAsMap(style), [layer]);

      const raster = layerOf(style, layerId(layer, "raster"));
      expect(raster.minzoom).toBe(4);
      expect(raster.maxzoom).toBe(9);
      // Layer opacity 0.4 × raster opacity 0.75.
      expect(raster.paint?.["raster-opacity"]).toBeCloseTo(0.3, 10);
      expect(styleErrors(style)).toEqual([]);
    });

    it("keeps a selection carrying filters and highlights valid", () => {
      const layers = [rasterLayer("© survey"), otherRasterLayer()];
      const style = build("openstreetmap", layers);

      applyInteractionOverrides(styleAsMap(style), layers, SELECTION);

      expect(styleErrors(style)).toEqual([]);
      expect(undefinedStylePaths(style)).toEqual([]);
    });

    it("leaves a raster layer untouched by an interaction", () => {
      const layer = rasterLayer("© survey");
      const style = build("none", [layer]);
      const before = structuredClone(layerOf(style, layerId(layer, "raster")));

      applyInteractionOverrides(styleAsMap(style), [layer], SELECTION);

      expect(layerOf(style, layerId(layer, "raster"))).toEqual(before);
      expect(styleErrors(style)).toEqual([]);
    });
  });
});
