/**
 * These tests run the generated MapLibre style through the real style-spec
 * validator instead of a hand-written expectation of each key.
 *
 * The card suite mocks `maplibre-gl`, so a style was only ever compared with
 * what its author expected and one that MapLibre refuses on load still passed:
 * a raster source built from a TileJSON without attribution carried
 * `attribution: undefined`, which the optional TypeScript property accepts and
 * the spec does not (`sources.<id>.attribution: string expected, undefined
 * found`). No test here constructs a map, so this file leaves `maplibre-gl` and
 * `pmtiles` un-mocked and hands every emitted style to `validateStyleMin` — the
 * check the library itself makes when a style loads.
 */
import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import type { Map as MapLibreMap } from "maplibre-gl";
import { describe, expect, it } from "vitest";

import type {
  GeoBounds,
  GeoRenderCategorizedPointStyle,
  GeoRenderDescriptor,
  GeoRenderLabelStyle,
  GeoRenderLayer,
  GeoRenderPointCategory,
} from "@/lib/api";

import type { ArtifactViewerIncomingBinding } from "../../artifact-interactions";
import {
  applyInteractionOverrides,
  applyLayerOverrides,
} from "./layer-overrides";
import { categoryLayerId, layerId } from "./layer-identity";
import { createGeoMapStyle, pmtilesUrl } from "./map-style";
import { OSM_LAYER_ID, OSM_SOURCE_ID } from "./style-constants";

const WORKSPACE_ID = "11111111-1111-4111-8111-111111111111";
const BOUNDS: GeoBounds = [-180, -85, 180, 85];

const LABEL: GeoRenderLabelStyle = {
  property: "name",
  color: "#111827",
  size: 12,
  halo_color: "#ffffff",
  halo_width: 1,
};

const VECTOR_ARCHIVE_URL =
  "/v1/workspaces/11111111-1111-4111-8111-111111111111/artifacts/22222222-2222-4222-8222-222222222222/download?part=vector";
const TILEJSON_URL =
  "/api/v1/workspaces/11111111-1111-4111-8111-111111111111/artifacts/44444444-4444-4444-8444-444444444444/tilejson.json";

// --- Fixtures ---------------------------------------------------------------

function vectorLayer(
  mutate: (layer: GeoRenderLayer) => GeoRenderLayer = (layer) => layer,
): GeoRenderLayer {
  return mutate({
    id: "layer-vector",
    title: "Countries",
    visible: true,
    opacity: 1,
    min_zoom: 0,
    max_zoom: 14,
    source: {
      kind: "vector",
      artifact_id: "22222222-2222-4222-8222-222222222222",
      archive_url: VECTOR_ARCHIVE_URL,
      bounds: BOUNDS,
      fields: [],
      source_layer: "countries",
      min_zoom: 0,
      max_zoom: 14,
    },
    style: {
      kind: "vector",
      fill: { color: "#2563eb", enabled: true, opacity: 0.6 },
      line: { color: "#1d4ed8", enabled: true, opacity: 1, width: 1.5 },
      outline: { color: "#0f172a", enabled: true, opacity: 1, width: 0.8 },
      point: {
        color: "#dc2626",
        enabled: true,
        opacity: 1,
        radius: 4,
        stroke_color: "#ffffff",
        stroke_width: 1,
      },
      label: LABEL,
    },
  });
}

function categorizedLayer(
  mutate: (layer: GeoRenderLayer) => GeoRenderLayer = (layer) => layer,
): GeoRenderLayer {
  const style: GeoRenderCategorizedPointStyle = {
    kind: "categorized_points",
    category_property: "kind",
    label: LABEL,
    categories: [
      {
        id: "city",
        title: "City",
        min_zoom: 3,
        max_zoom: 12,
        values: ["city", "town"],
        point: {
          color: "#dc2626",
          enabled: true,
          opacity: 1,
          radius: 5,
          stroke_color: "#ffffff",
          stroke_width: 1.5,
        },
      },
      {
        id: "village",
        title: "Village",
        min_zoom: 6,
        max_zoom: 14,
        values: ["hamlet", 3, true],
        point: {
          color: "#059669",
          enabled: false,
          opacity: 0.5,
          radius: 3,
          stroke_color: "#0f172a",
          stroke_width: 0,
        },
      },
    ],
  };
  return mutate({
    id: "layer-points",
    title: "Places",
    visible: true,
    opacity: 0.9,
    min_zoom: 2,
    max_zoom: 13,
    source: {
      kind: "vector",
      artifact_id: "33333333-3333-4333-8333-333333333333",
      archive_url:
        "/api/v1/artifacts/33333333-3333-4333-8333-333333333333/pmtiles",
      bounds: null,
      fields: [],
      source_layer: "places",
      min_zoom: 0,
      max_zoom: 14,
    },
    style,
  });
}

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

/** A TileJSON with no attribution at all reaches the client without the key. */
function withoutAttributionKey(layer: GeoRenderLayer): GeoRenderLayer {
  const source = { ...layer.source } as unknown as Record<string, unknown>;
  delete source.attribution;
  return { ...layer, source } as GeoRenderLayer;
}

function categoriesOf(
  layer: GeoRenderLayer,
): readonly GeoRenderPointCategory[] {
  if (layer.style.kind !== "categorized_points") {
    throw new Error(`layer ${layer.id} is not categorized`);
  }
  return layer.style.categories;
}

function categoryOf(layer: GeoRenderLayer, id: string): GeoRenderPointCategory {
  const category = categoriesOf(layer).find((candidate) => candidate.id === id);
  if (!category) throw new Error(`layer ${layer.id} has no category ${id}`);
  return category;
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
  "source-layer"?: string;
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
  });

  describe("vector layers", () => {
    it("publishes one pmtiles vector source per layer", () => {
      const style = build("none", [vectorLayer()]);
      const source = sourceOf(style, "grafy-geo-source-layer-vector");

      expect(source.type).toBe("vector");
      expect(source.url).toBe(pmtilesUrl(WORKSPACE_ID, VECTOR_ARCHIVE_URL));
      expect(String(source.url).startsWith("pmtiles://")).toBe(true);
      expect(source.minzoom).toBe(0);
      expect(source.maxzoom).toBe(14);
      expect("attribution" in source).toBe(false);
      expect(styleErrors(style)).toEqual([]);
    });

    it("emits the fill, outline, line, point, and label layers in order", () => {
      const style = build("none", [vectorLayer()]);

      expect(style.layers.map((layer) => layer.id)).toEqual([
        "grafy-geo-layer-vector-fill",
        "grafy-geo-layer-vector-outline",
        "grafy-geo-layer-vector-line",
        "grafy-geo-layer-vector-point",
        "grafy-geo-layer-vector-label",
      ]);
      for (const id of style.layers.map((layer) => layer.id)) {
        const layer = layerOf(style, id);
        expect(layer.source).toBe("grafy-geo-source-layer-vector");
        expect(layer["source-layer"]).toBe("countries");
        expect(layer.minzoom).toBe(0);
        expect(layer.maxzoom).toBe(14);
      }
      expect(styleErrors(style)).toEqual([]);
    });

    it("keeps each geometry kind under its own filter and paint", () => {
      const layer = vectorLayer();
      const style = build("none", [layer]);
      const id = (kind: string) => layerId(layer, kind);

      const fill = layerOf(style, id("fill"));
      expect(fill.type).toBe("fill");
      expect(fill.filter).toEqual([
        "any",
        ["==", ["geometry-type"], "Polygon"],
        ["==", ["geometry-type"], "MultiPolygon"],
      ]);
      expect(fill.paint?.["fill-color"]).toBe("#2563eb");
      expect(fill.paint?.["fill-opacity"]).toBeCloseTo(0.6, 10);

      const outline = layerOf(style, id("outline"));
      expect(outline.type).toBe("line");
      expect(outline.filter).toEqual([
        "any",
        ["==", ["geometry-type"], "Polygon"],
        ["==", ["geometry-type"], "MultiPolygon"],
      ]);
      expect(outline.paint?.["line-color"]).toBe("#0f172a");
      expect(outline.paint?.["line-width"]).toBe(0.8);

      const line = layerOf(style, id("line"));
      expect(line.type).toBe("line");
      expect(line.filter).toEqual([
        "any",
        ["==", ["geometry-type"], "LineString"],
        ["==", ["geometry-type"], "MultiLineString"],
      ]);
      expect(line.paint?.["line-color"]).toBe("#1d4ed8");

      const point = layerOf(style, id("point"));
      expect(point.type).toBe("circle");
      expect(point.filter).toEqual([
        "any",
        ["==", ["geometry-type"], "Point"],
        ["==", ["geometry-type"], "MultiPoint"],
      ]);
      expect(point.paint?.["circle-radius"]).toBe(4);
      expect(point.paint?.["circle-pitch-scale"]).toBe("viewport");

      const label = layerOf(style, id("label"));
      expect(label.type).toBe("symbol");
      expect(label.layout?.["text-field"]).toEqual([
        "coalesce",
        ["to-string", ["get", "name"]],
        "",
      ]);
      expect(label.layout?.["text-size"]).toBe(12);
      expect(label.paint?.["text-halo-color"]).toBe("#ffffff");
      expect(label.paint?.["text-halo-width"]).toBe(1);
      expect(styleErrors(style)).toEqual([]);
    });

    it("carries layer opacity into every sub-layer", () => {
      const layer = vectorLayer();
      const style = build("none", [
        vectorLayer((candidate) => ({ ...candidate, opacity: 0.5 })),
      ]);

      expect(
        layerOf(style, layerId(layer, "fill")).paint?.["fill-opacity"],
      ).toBeCloseTo(0.3, 10);
      expect(
        layerOf(style, layerId(layer, "point")).paint?.["circle-opacity"],
      ).toBeCloseTo(0.5, 10);
      expect(
        layerOf(style, layerId(layer, "label")).paint?.["text-opacity"],
      ).toBe(0.5);
      expect(styleErrors(style)).toEqual([]);
    });

    it.each(["fill", "outline", "line", "point"] as const)(
      "draws %s as none once its own switch is off",
      (kind) => {
        const layer = vectorLayer((candidate) => {
          const style = candidate.style;
          if (style.kind !== "vector") return candidate;
          return {
            ...candidate,
            style: { ...style, [kind]: { ...style[kind], enabled: false } },
          };
        });
        const style = build("none", [layer]);

        expect(layerOf(style, layerId(layer, kind)).layout?.visibility).toBe(
          "none",
        );
        expect(styleErrors(style)).toEqual([]);
      },
    );

    it("keeps an invisible layer in the style rather than dropping it", () => {
      const layer = vectorLayer((candidate) => ({
        ...candidate,
        visible: false,
      }));
      const style = build("none", [layer]);

      expect(style.layers).toHaveLength(5);
      for (const id of style.layers.map((candidate) => candidate.id)) {
        expect(layerOf(style, id).layout?.visibility).toBe("none");
      }
      expect(styleErrors(style)).toEqual([]);
    });

    it("falls back to the default label and hides it when the style has none", () => {
      const layer = vectorLayer((candidate) => ({
        ...candidate,
        style: { ...candidate.style, label: null },
      }));
      const style = build("none", [layer]);
      const label = layerOf(style, layerId(layer, "label"));

      expect(label.layout?.visibility).toBe("none");
      expect(label.layout?.["text-field"]).toEqual([
        "coalesce",
        ["to-string", ["get", "name"]],
        "",
      ]);
      expect(label.layout?.["text-size"]).toBe(12);
      expect(styleErrors(style)).toEqual([]);
    });
  });

  describe("categorized point layers", () => {
    it("emits one point and one label layer per category", () => {
      const layer = categorizedLayer();
      const style = build("none", [layer]);
      const categories = categoriesOf(layer);

      expect(categories).toHaveLength(2);
      expect(style.layers.map((candidate) => candidate.id)).toEqual([
        "grafy-geo-layer-points-category-city-point",
        "grafy-geo-layer-points-category-city-label",
        "grafy-geo-layer-points-category-village-point",
        "grafy-geo-layer-points-category-village-label",
      ]);
      for (const category of categories) {
        expect(
          layerOf(style, categoryLayerId(layer, category, "point")).type,
        ).toBe("circle");
        expect(
          layerOf(style, categoryLayerId(layer, category, "label")).type,
        ).toBe("symbol");
      }
      expect(styleErrors(style)).toEqual([]);
    });

    it("intersects the category zoom range with the layer's", () => {
      const layer = categorizedLayer();
      const city = categoryOf(layer, "city");
      const village = categoryOf(layer, "village");
      const style = build("none", [layer]);

      // Layer 2–13 ∩ city 3–12, and layer 2–13 ∩ village 6–14.
      for (const id of [
        categoryLayerId(layer, city, "point"),
        categoryLayerId(layer, city, "label"),
      ]) {
        expect(layerOf(style, id).minzoom).toBe(3);
        expect(layerOf(style, id).maxzoom).toBe(12);
      }
      for (const id of [
        categoryLayerId(layer, village, "point"),
        categoryLayerId(layer, village, "label"),
      ]) {
        expect(layerOf(style, id).minzoom).toBe(6);
        expect(layerOf(style, id).maxzoom).toBe(13);
      }
      expect(styleErrors(style)).toEqual([]);
    });

    it("filters each category on its own values", () => {
      const layer = categorizedLayer();
      const style = build("none", [layer]);
      const filter = layerOf(
        style,
        "grafy-geo-layer-points-category-city-point",
      ).filter;

      expect(filter).toEqual([
        "all",
        [
          "any",
          ["==", ["geometry-type"], "Point"],
          ["==", ["geometry-type"], "MultiPoint"],
        ],
        ["in", ["get", "kind"], ["literal", ["city", "town"]]],
      ]);
      expect(styleErrors(style)).toEqual([]);
    });

    it("paints each category and offsets its label clear of the point", () => {
      const layer = categorizedLayer();
      const style = build("none", [layer]);
      const city = layerOf(style, "grafy-geo-layer-points-category-city-point");
      const cityLabel = layerOf(
        style,
        "grafy-geo-layer-points-category-city-label",
      );

      expect(city.paint?.["circle-color"]).toBe("#dc2626");
      expect(city.paint?.["circle-radius"]).toBe(5);
      expect(city.paint?.["circle-stroke-width"]).toBe(1.5);
      // Layer opacity 0.9 × city opacity 1.
      expect(city.paint?.["circle-opacity"]).toBeCloseTo(0.9, 10);
      expect(cityLabel.layout?.["text-radial-offset"]).toBeCloseTo(
        5 / LABEL.size + 0.35,
        10,
      );
      expect(cityLabel.layout?.["text-variable-anchor"]).toEqual([
        "top",
        "bottom",
        "left",
        "right",
      ]);
      expect(cityLabel.layout?.["text-justify"]).toBe("auto");
      expect(styleErrors(style)).toEqual([]);
    });

    it("hides a disabled category and keeps its layers valid", () => {
      const layer = categorizedLayer();
      const style = build("none", [layer]);

      expect(
        layerOf(style, "grafy-geo-layer-points-category-village-point").layout
          ?.visibility,
      ).toBe("none");
      expect(
        layerOf(style, "grafy-geo-layer-points-category-village-label").layout
          ?.visibility,
      ).toBe("none");
      expect(styleErrors(style)).toEqual([]);
    });

    it("keeps a layer whose every category is switched off valid", () => {
      const layer = categorizedLayer((candidate) => {
        if (candidate.style.kind !== "categorized_points") return candidate;
        return {
          ...candidate,
          style: {
            ...candidate.style,
            categories: candidate.style.categories.map((category) => ({
              ...category,
              point: { ...category.point, enabled: false },
            })),
          },
        };
      });
      const style = build("none", [layer]);

      expect(style.layers).toHaveLength(4);
      expect(styleErrors(style)).toEqual([]);
    });
  });

  describe("composed maps", () => {
    const layers = [vectorLayer(), categorizedLayer(), rasterLayer("© survey")];

    it("adds the openstreetmap basemap underneath the data layers", () => {
      const style = build("openstreetmap", layers);

      expect(Object.keys(style.sources)).toEqual([
        OSM_SOURCE_ID,
        "grafy-geo-source-layer-vector",
        "grafy-geo-source-layer-points",
        "grafy-geo-source-layer-raster",
      ]);
      const basemapSource = sourceOf(style, OSM_SOURCE_ID);
      expect(basemapSource.attribution).toBe("© OpenStreetMap contributors");
      expect(style.layers[0]?.id).toBe(OSM_LAYER_ID);
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
        vectorLayer((layer) => ({ ...layer, id: "layer-vector-2" })),
        rasterLayer(null, (layer) => ({ ...layer, id: "layer-raster-2" })),
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
      "validates a raster-only, vector-only, and mixed map on the %s basemap",
      (_label, basemap) => {
        const cases: GeoRenderLayer[][] = [
          [rasterLayer(null)],
          [vectorLayer()],
          [categorizedLayer()],
          [vectorLayer(), categorizedLayer()],
          [categorizedLayer(), rasterLayer("© survey"), vectorLayer()],
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
        vectorLayer(),
        categorizedLayer(),
        rasterLayer(null, (layer) => ({ ...layer, visible: false })),
      ];
      const style = build("openstreetmap", layers);

      applyLayerOverrides(styleAsMap(style), layers);

      expect(styleErrors(style)).toEqual([]);
      expect(undefinedStylePaths(style)).toEqual([]);
      expect(
        layerOf(style, "grafy-geo-layer-raster-raster").layout?.visibility,
      ).toBe("none");
      expect(
        layerOf(style, "grafy-geo-layer-vector-fill").layout?.visibility,
      ).toBe("visible");
    });

    it("re-draws the layers an override moved in the card list", () => {
      const first = vectorLayer();
      const second = categorizedLayer();
      const style = build("none", [first, second]);

      applyLayerOverrides(styleAsMap(style), [second, first]);

      expect(style.layers.map((layer) => layer.id)).toEqual([
        "grafy-geo-layer-points-category-city-point",
        "grafy-geo-layer-points-category-city-label",
        "grafy-geo-layer-points-category-village-point",
        "grafy-geo-layer-points-category-village-label",
        "grafy-geo-layer-vector-fill",
        "grafy-geo-layer-vector-outline",
        "grafy-geo-layer-vector-line",
        "grafy-geo-layer-vector-point",
        "grafy-geo-layer-vector-label",
      ]);
      expect(styleErrors(style)).toEqual([]);
    });

    it("keeps zoom-range and opacity edits inside the spec", () => {
      const layer = vectorLayer((candidate) => ({
        ...candidate,
        opacity: 0.4,
        min_zoom: 4,
        max_zoom: 9,
      }));
      const style = build("none", [layer]);

      applyLayerOverrides(styleAsMap(style), [layer]);

      const fill = layerOf(style, layerId(layer, "fill"));
      expect(fill.minzoom).toBe(4);
      expect(fill.maxzoom).toBe(9);
      expect(fill.paint?.["fill-opacity"]).toBeCloseTo(0.24, 10);
      expect(styleErrors(style)).toEqual([]);
    });

    it("keeps interaction filters and highlight expressions valid", () => {
      const layers = [vectorLayer(), categorizedLayer(), rasterLayer(null)];
      const style = build("openstreetmap", layers);

      applyInteractionOverrides(styleAsMap(style), layers, SELECTION);

      expect(styleErrors(style)).toEqual([]);
      expect(undefinedStylePaths(style)).toEqual([]);
    });

    it("combines the selection filter with each layer's own geometry filter", () => {
      const layer = vectorLayer();
      const style = build("none", [layer]);

      applyInteractionOverrides(styleAsMap(style), [layer], SELECTION);

      // One incoming binding contributes one OR-group over its selected rows,
      // and the "filter" effect ANDs the groups together.
      const selectionFilter: unknown[] = [
        "all",
        [
          "any",
          [
            "all",
            ["==", ["get", "kind"], "city"],
            ["==", ["get", "population"], 1200],
            ["==", ["get", "capital"], true],
          ],
          ["all", ["==", ["get", "kind"], "town"]],
        ],
      ];
      expect(layerOf(style, layerId(layer, "point")).filter).toEqual([
        "all",
        [
          "any",
          ["==", ["geometry-type"], "Point"],
          ["==", ["geometry-type"], "MultiPoint"],
        ],
        selectionFilter,
      ]);
      // A layer with no geometry filter of its own takes the selection alone.
      expect(layerOf(style, layerId(layer, "label")).filter).toEqual(
        selectionFilter,
      );
      expect(styleErrors(style)).toEqual([]);
    });

    it("draws highlighted features with case expressions", () => {
      const layer = vectorLayer();
      const style = build("none", [layer]);

      applyInteractionOverrides(styleAsMap(style), [layer], SELECTION);

      const point = layerOf(style, layerId(layer, "point"));
      expect(Array.isArray(point.paint?.["circle-radius"])).toBe(true);
      expect((point.paint?.["circle-radius"] as unknown[])[0]).toBe("case");
      expect(styleErrors(style)).toEqual([]);
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
