"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  ArrowDown,
  ArrowUp,
  Eye,
  EyeOff,
  Layers3,
  LocateFixed,
  Map as MapIcon,
  RotateCcw,
  X,
} from "lucide-react";
import maplibregl from "maplibre-gl";
import { Protocol } from "pmtiles";
import useSWR from "swr";

import {
  artifactContentUrl,
  getArtifactGeoRender,
  queryArtifactGeoFeatures,
  type ArtifactSummary,
  type GeoBounds,
  type GeoRenderCategorizedPointStyle,
  type GeoRenderDescriptor,
  type GeoRenderFillStyle,
  type GeoRenderLabelStyle,
  type GeoRenderLayer,
  type GeoRenderLineStyle,
  type GeoRenderPointStyle,
  type GeoRenderPointCategory,
  type GeoRenderRasterStyle,
  type GeoRenderVectorStyle,
} from "@/lib/api";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type {
  ArtifactInteractionScalar,
  ArtifactViewerActivity,
  ArtifactViewerIncomingBinding,
  ArtifactViewerInteractionContext,
} from "../artifact-interactions";

maplibregl.workerUrl = "/maplibre-gl-csp-worker.js";

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";
const MAP_FIT_OPTIONS = { padding: 28, maxZoom: 14 } as const;
const FEATURE_HIT_RADIUS = 12;
const OSM_SOURCE_ID = "grafy-openstreetmap";
const OSM_LAYER_ID = "grafy-openstreetmap-raster";
const POINT_FILTER: maplibregl.FilterSpecification = [
  "any",
  ["==", ["geometry-type"], "Point"],
  ["==", ["geometry-type"], "MultiPoint"],
];
const POLYGON_FILTER: maplibregl.FilterSpecification = [
  "any",
  ["==", ["geometry-type"], "Polygon"],
  ["==", ["geometry-type"], "MultiPolygon"],
];
const LINE_FILTER: maplibregl.FilterSpecification = [
  "any",
  ["==", ["geometry-type"], "LineString"],
  ["==", ["geometry-type"], "MultiLineString"],
];
const DEFAULT_LABEL_STYLE: GeoRenderLabelStyle = {
  property: "name",
  color: "#111827",
  size: 12,
  halo_color: "#ffffff",
  halo_width: 1,
};

type SelectedGeoFeature = {
  layerId: string;
  layerTitle: string;
  title: string;
  geometryType: string;
  featureId: string | null;
  longitude: number;
  latitude: number;
  properties: Array<{ name: string; value: string }>;
  selectionValues: Record<string, ArtifactInteractionScalar>;
};

let pmtilesProtocolRegistered = false;

const s = stylex.create({
  shell: {
    position: "relative",
    width: "100%",
    minHeight: "320px",
    overflow: "hidden",
    borderRadius: "10px",
    backgroundColor: tokens.colorSurfaceSunken,
  },
  map: { width: "100%", height: "100%" },
  placeholder: {
    height: "100%",
    minHeight: "320px",
    display: "grid",
    placeItems: "center",
    padding: "28px",
    textAlign: "center",
  },
  placeholderContent: {
    maxWidth: "330px",
    display: "grid",
    justifyItems: "center",
    gap: "8px",
  },
  placeholderIcon: { color: tokens.colorAccent },
  placeholderTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 750,
  },
  placeholderCopy: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  actions: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    flexWrap: "wrap",
    gap: "7px",
    marginTop: "4px",
  },
  primaryButton: {
    minHeight: "32px",
    paddingInline: "12px",
    borderWidth: 0,
    borderRadius: "8px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    outlineOffset: "2px",
    backgroundColor: tokens.colorAccent,
    color: tokens.colorOnAccent,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 750,
  },
  mapControls: {
    position: "absolute",
    top: "8px",
    left: "10px",
    zIndex: 3,
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  utilityButton: {
    minWidth: "30px",
    height: "30px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    paddingInline: "8px",
    borderWidth: 0,
    borderRadius: "8px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    outlineOffset: "2px",
    backgroundColor: {
      default: "light-dark(rgba(255,255,255,.95), rgba(20,24,32,.95))",
      ":disabled": tokens.colorSurfaceSunken,
    },
    boxShadow: tokens.shadowNode,
    color: {
      default: tokens.colorTextEmphasis,
      ":disabled": tokens.colorTextDisabled,
    },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    fontSize: "10px",
    fontWeight: 700,
    backdropFilter: "blur(12px)",
  },
  inspector: {
    position: "absolute",
    top: "46px",
    left: "10px",
    zIndex: 3,
    width: "min(292px, calc(100% - 20px))",
    maxHeight: "calc(100% - 58px)",
    display: "grid",
    gap: "6px",
    overflowY: "auto",
    padding: "8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "10px",
    backgroundColor: "light-dark(rgba(255,255,255,.97), rgba(20,24,32,.97))",
    boxShadow: tokens.shadowNodeRaised,
    backdropFilter: "blur(14px)",
  },
  inspectorHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    paddingInline: "2px",
  },
  inspectorTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: "10px",
    fontWeight: 800,
    letterSpacing: "0.05em",
    textTransform: "uppercase",
  },
  layer: {
    display: "grid",
    gap: "6px",
    padding: "7px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  layerHeader: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    alignItems: "center",
    gap: "6px",
  },
  layerTitleButton: {
    minWidth: 0,
    padding: 0,
    overflow: "hidden",
    borderWidth: 0,
    backgroundColor: "transparent",
    color: tokens.colorTextEmphasis,
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 700,
    textAlign: "left",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  layerActions: { display: "flex", alignItems: "center", gap: "2px" },
  iconButton: {
    width: "24px",
    height: "24px",
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "6px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: {
      default: tokens.colorMuted,
      ":disabled": tokens.colorTextDisabled,
    },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
  },
  controls: { display: "grid", gap: "7px" },
  controlGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: "6px 8px",
  },
  control: {
    minWidth: 0,
    display: "grid",
    gap: "3px",
    color: tokens.colorSubtle,
    fontSize: "9px",
  },
  controlWide: { gridColumn: "1 / -1" },
  controlInput: {
    width: "100%",
    minWidth: 0,
    height: "25px",
    paddingInline: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: "6px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    fontFamily: MONO,
    fontSize: "9px",
  },
  colorInput: { padding: "2px" },
  rangeRow: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 34px",
    alignItems: "center",
    gap: "5px",
  },
  range: { width: "100%", accentColor: tokens.colorAccent },
  rangeValue: {
    color: tokens.colorText,
    fontFamily: MONO,
    fontSize: "9px",
    textAlign: "right",
  },
  section: {
    display: "grid",
    gap: "5px",
    paddingTop: "5px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  sectionTitle: {
    color: tokens.colorMuted,
    fontSize: "9px",
    fontWeight: 750,
  },
  toggle: {
    display: "flex",
    alignItems: "center",
    gap: "5px",
    color: tokens.colorText,
    fontSize: "9px",
  },
  categoryList: {
    display: "grid",
    gap: "4px",
  },
  categoryRow: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "16px 22px minmax(0, 1fr) 48px",
    alignItems: "center",
    gap: "6px",
    paddingBlock: "3px",
    color: tokens.colorText,
    fontSize: "9px",
  },
  categoryColor: {
    width: "22px",
    height: "18px",
    padding: "1px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: "4px",
    backgroundColor: "transparent",
    cursor: "pointer",
  },
  categoryRadius: {
    width: "48px",
    minWidth: 0,
    height: "22px",
    paddingInline: "4px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: "4px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    fontFamily: MONO,
    fontSize: "8px",
  },
  categoryText: {
    minWidth: 0,
    display: "grid",
    gap: "1px",
  },
  categoryTitle: {
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontWeight: 700,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  categoryMeta: {
    overflow: "hidden",
    color: tokens.colorMuted,
    fontFamily: MONO,
    fontSize: "8px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  resetButton: {
    minHeight: "25px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "5px",
    paddingInline: "8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: "6px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    cursor: "pointer",
    fontSize: "9px",
  },
  featurePanel: {
    position: "absolute",
    right: "10px",
    bottom: "30px",
    zIndex: 3,
    width: "min(292px, calc(100% - 20px))",
    maxHeight: "min(280px, calc(100% - 82px))",
    display: "grid",
    gridTemplateRows: "auto minmax(0, 1fr)",
    overflow: "hidden",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "10px",
    backgroundColor: "light-dark(rgba(255,255,255,.97), rgba(20,24,32,.97))",
    boxShadow: tokens.shadowNodeRaised,
    backdropFilter: "blur(14px)",
  },
  featureHeader: {
    minWidth: 0,
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: "8px",
    padding: "10px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  featureHeading: {
    minWidth: 0,
    display: "grid",
    gap: "2px",
  },
  featureKicker: {
    overflow: "hidden",
    color: tokens.colorMuted,
    fontSize: "9px",
    fontWeight: 750,
    letterSpacing: "0.04em",
    textOverflow: "ellipsis",
    textTransform: "uppercase",
    whiteSpace: "nowrap",
  },
  featureTitle: {
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 750,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  featureMeta: {
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "9px",
  },
  featureProperties: {
    minHeight: 0,
    display: "grid",
    gap: "1px",
    margin: 0,
    overflowY: "auto",
    padding: "6px 10px 10px",
  },
  featureProperty: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "minmax(72px, .75fr) minmax(0, 1.25fr)",
    gap: "8px",
    paddingBlock: "5px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  featurePropertyName: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorMuted,
    fontFamily: MONO,
    fontSize: "9px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  featurePropertyValue: {
    minWidth: 0,
    margin: 0,
    overflowWrap: "anywhere",
    color: tokens.colorText,
    fontFamily: MONO,
    fontSize: "9px",
    lineHeight: 1.45,
  },
  featureEmpty: {
    margin: 0,
    padding: "10px",
    color: tokens.colorSubtle,
    fontSize: "10px",
  },
  rawShell: { display: "grid", gap: "7px" },
  rawHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
  },
  rawMeta: { color: tokens.colorSubtle, fontSize: "10px" },
  raw: {
    margin: 0,
    fontFamily: MONO,
    fontSize: "10px",
    lineHeight: 1.55,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
});

function mapInteractionProps(props: ReturnType<typeof stylex.props>) {
  return {
    ...props,
    className: `nodrag nowheel nopan${props.className ? ` ${props.className}` : ""}`,
  };
}

function ensurePmtilesProtocol() {
  if (pmtilesProtocolRegistered) return;
  const protocol = new Protocol();
  maplibregl.addProtocol("pmtiles", protocol.tile);
  pmtilesProtocolRegistered = true;
}

function absoluteApiUrl(workspaceId: string, path: string): string {
  return artifactContentUrl(workspaceId, path) ?? path;
}

function pmtilesUrl(workspaceId: string, path: string): string {
  return `pmtiles://${absoluteApiUrl(workspaceId, path)}`;
}

function sourceId(layer: GeoRenderLayer): string {
  return `grafy-geo-source-${layer.id}`;
}

function layerId(layer: GeoRenderLayer, kind: string): string {
  return `grafy-geo-${layer.id}-${kind}`;
}

function categoryLayerId(
  layer: GeoRenderLayer,
  category: GeoRenderPointCategory,
  kind: "point" | "label",
): string {
  return layerId(layer, `category-${category.id}-${kind}`);
}

function layerRenderIds(layer: GeoRenderLayer): string[] {
  if (layer.style.kind === "raster") return [layerId(layer, "raster")];
  if (layer.style.kind === "categorized_points") {
    return layer.style.categories.flatMap((category) => [
      categoryLayerId(layer, category, "point"),
      categoryLayerId(layer, category, "label"),
    ]);
  }
  return [
    layerId(layer, "fill"),
    layerId(layer, "outline"),
    layerId(layer, "line"),
    layerId(layer, "point"),
    layerId(layer, "label"),
  ];
}

function cloneLayer(layer: GeoRenderLayer): GeoRenderLayer {
  if (layer.style.kind === "raster") {
    return {
      ...layer,
      source: { ...layer.source },
      style: { ...layer.style },
    };
  }
  if (layer.style.kind === "categorized_points") {
    return {
      ...layer,
      source: { ...layer.source },
      style: {
        ...layer.style,
        categories: layer.style.categories.map((category) => ({
          ...category,
          values: [...category.values],
          point: { ...category.point },
        })),
        label: layer.style.label ? { ...layer.style.label } : null,
      },
    };
  }
  return {
    ...layer,
    source: { ...layer.source },
    style: {
      ...layer.style,
      fill: { ...layer.style.fill },
      line: { ...layer.style.line },
      outline: { ...layer.style.outline },
      point: { ...layer.style.point },
      label: layer.style.label ? { ...layer.style.label } : null,
    },
  };
}

function visible(visibleLayer: boolean, enabled = true): "visible" | "none" {
  return visibleLayer && enabled ? "visible" : "none";
}

function combinedOpacity(layer: GeoRenderLayer, opacity: number): number {
  return Math.max(0, Math.min(1, layer.opacity * opacity));
}

function categoryFilter(
  style: GeoRenderCategorizedPointStyle,
  category: GeoRenderPointCategory,
): maplibregl.FilterSpecification {
  return [
    "all",
    POINT_FILTER,
    ["in", ["get", style.category_property], ["literal", [...category.values]]],
  ] as maplibregl.FilterSpecification;
}

function interactionRowsFilter(
  rows: Array<Record<string, ArtifactInteractionScalar>>,
): maplibregl.FilterSpecification | null {
  const completeRows = rows.filter((row) => Object.keys(row).length > 0);
  if (!completeRows.length) return null;
  return [
    "any",
    ...completeRows.map((row) => [
      "all",
      ...Object.entries(row).map(([fieldName, value]) => [
        "==",
        ["get", fieldName],
        value,
      ]),
    ]),
  ] as maplibregl.FilterSpecification;
}

function interactionEffectFilter(
  incoming: readonly ArtifactViewerIncomingBinding[],
  effect: "filter" | "highlight" | "focus",
): maplibregl.FilterSpecification | null {
  const groups = incoming.flatMap((binding) => {
    if (!binding.effects.includes(effect)) return [];
    const filter = interactionRowsFilter(binding.rows);
    return filter ? [filter] : [];
  });
  if (!groups.length) return null;
  return [
    effect === "filter" ? "all" : "any",
    ...groups,
  ] as maplibregl.FilterSpecification;
}

function baseRenderFilter(
  layer: GeoRenderLayer,
  renderId: string,
): maplibregl.FilterSpecification | null {
  if (layer.style.kind === "categorized_points") {
    const category = layer.style.categories.find(
      (candidate) =>
        renderId === categoryLayerId(layer, candidate, "point") ||
        renderId === categoryLayerId(layer, candidate, "label"),
    );
    return category ? categoryFilter(layer.style, category) : null;
  }
  if (layer.style.kind !== "vector") return null;
  if (
    renderId === layerId(layer, "fill") ||
    renderId === layerId(layer, "outline")
  ) {
    return POLYGON_FILTER;
  }
  if (renderId === layerId(layer, "line")) return LINE_FILTER;
  if (renderId === layerId(layer, "point")) return POINT_FILTER;
  return null;
}

function filtersTogether(
  left: maplibregl.FilterSpecification | null,
  right: maplibregl.FilterSpecification | null,
): maplibregl.FilterSpecification | null {
  if (!left) return right;
  if (!right) return left;
  return ["all", left, right] as maplibregl.FilterSpecification;
}

function applyInteractionOverrides(
  map: maplibregl.Map,
  layers: readonly GeoRenderLayer[],
  incoming: readonly ArtifactViewerIncomingBinding[],
) {
  applyLayerOverrides(map, layers);
  const filter = interactionEffectFilter(incoming, "filter");
  const highlight = interactionEffectFilter(incoming, "highlight");

  for (const layer of layers) {
    if (layer.source.kind !== "vector" || layer.style.kind === "raster") {
      continue;
    }
    for (const renderId of layerRenderIds(layer)) {
      if (map.getLayer(renderId)) {
        map.setFilter(
          renderId,
          filtersTogether(baseRenderFilter(layer, renderId), filter),
        );
      }
    }
    if (!highlight) continue;

    if (layer.style.kind === "categorized_points") {
      for (const category of layer.style.categories) {
        const pointId = categoryLayerId(layer, category, "point");
        if (!map.getLayer(pointId)) continue;
        setPaint(map, pointId, "circle-radius", [
          "case",
          highlight,
          category.point.radius + 3,
          category.point.radius,
        ]);
        setPaint(map, pointId, "circle-stroke-color", [
          "case",
          highlight,
          "#111827",
          category.point.stroke_color,
        ]);
        setPaint(map, pointId, "circle-stroke-width", [
          "case",
          highlight,
          Math.max(3, category.point.stroke_width + 2),
          category.point.stroke_width,
        ]);
      }
      continue;
    }

    const pointId = layerId(layer, "point");
    setPaint(map, pointId, "circle-radius", [
      "case",
      highlight,
      layer.style.point.radius + 3,
      layer.style.point.radius,
    ]);
    setPaint(map, pointId, "circle-stroke-color", [
      "case",
      highlight,
      "#111827",
      layer.style.point.stroke_color,
    ]);
    setPaint(map, pointId, "circle-stroke-width", [
      "case",
      highlight,
      Math.max(3, layer.style.point.stroke_width + 2),
      layer.style.point.stroke_width,
    ]);
    for (const [kind, line] of [
      ["line", layer.style.line],
      ["outline", layer.style.outline],
    ] as const) {
      setPaint(map, layerId(layer, kind), "line-color", [
        "case",
        highlight,
        "#f59e0b",
        line.color,
      ]);
      setPaint(map, layerId(layer, kind), "line-width", [
        "case",
        highlight,
        line.width + 3,
        line.width,
      ]);
    }
    setPaint(map, layerId(layer, "fill"), "fill-color", [
      "case",
      highlight,
      "#f59e0b",
      layer.style.fill.color,
    ]);
  }
}

function createGeoMapStyle(
  workspaceId: string,
  descriptor: GeoRenderDescriptor,
  layers: readonly GeoRenderLayer[],
): maplibregl.StyleSpecification {
  const sources: maplibregl.StyleSpecification["sources"] = {};
  const renderLayers: maplibregl.LayerSpecification[] = [];

  if (descriptor.basemap === "openstreetmap") {
    sources[OSM_SOURCE_ID] = {
      type: "raster",
      tiles: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    };
    renderLayers.push({
      id: OSM_LAYER_ID,
      type: "raster",
      source: OSM_SOURCE_ID,
    });
  }

  for (const layer of layers) {
    const id = sourceId(layer);
    if (
      layer.source.kind === "vector" &&
      layer.style.kind === "categorized_points"
    ) {
      sources[id] = {
        type: "vector",
        url: pmtilesUrl(workspaceId, layer.source.archive_url),
        minzoom: layer.source.min_zoom,
        maxzoom: layer.source.max_zoom,
      };
      const sourceLayer = layer.source.source_layer;
      const label = layer.style.label ?? DEFAULT_LABEL_STYLE;
      for (const category of layer.style.categories) {
        const minzoom = Math.max(layer.min_zoom, category.min_zoom);
        const maxzoom = Math.min(layer.max_zoom, category.max_zoom);
        const filter = categoryFilter(layer.style, category);
        const labelRadialOffset = category.point.radius / label.size + 0.35;
        renderLayers.push(
          {
            id: categoryLayerId(layer, category, "point"),
            type: "circle",
            source: id,
            "source-layer": sourceLayer,
            minzoom,
            maxzoom,
            filter,
            layout: {
              visibility: visible(layer.visible, category.point.enabled),
            },
            paint: {
              "circle-color": category.point.color,
              "circle-opacity": combinedOpacity(layer, category.point.opacity),
              "circle-radius": category.point.radius,
              "circle-pitch-scale": "viewport",
              "circle-stroke-color": category.point.stroke_color,
              "circle-stroke-opacity": layer.opacity,
              "circle-stroke-width": category.point.stroke_width,
            },
          },
          {
            id: categoryLayerId(layer, category, "label"),
            type: "symbol",
            source: id,
            "source-layer": sourceLayer,
            minzoom,
            maxzoom,
            filter,
            layout: {
              visibility: visible(
                layer.visible && category.point.enabled,
                layer.style.label !== null,
              ),
              "text-field": [
                "coalesce",
                ["to-string", ["get", label.property]],
                "",
              ],
              "text-size": label.size,
              "text-variable-anchor": ["top", "bottom", "left", "right"],
              "text-radial-offset": labelRadialOffset,
              "text-justify": "auto",
            },
            paint: {
              "text-color": label.color,
              "text-opacity": layer.opacity,
              "text-halo-color": label.halo_color,
              "text-halo-width": label.halo_width,
            },
          },
        );
      }
      continue;
    }
    if (layer.source.kind === "vector" && layer.style.kind === "vector") {
      sources[id] = {
        type: "vector",
        url: pmtilesUrl(workspaceId, layer.source.archive_url),
        minzoom: layer.source.min_zoom,
        maxzoom: layer.source.max_zoom,
      };
      const sourceLayer = layer.source.source_layer;
      renderLayers.push(
        {
          id: layerId(layer, "fill"),
          type: "fill",
          source: id,
          "source-layer": sourceLayer,
          minzoom: layer.min_zoom,
          maxzoom: layer.max_zoom,
          filter: POLYGON_FILTER,
          layout: {
            visibility: visible(layer.visible, layer.style.fill.enabled),
          },
          paint: {
            "fill-color": layer.style.fill.color,
            "fill-opacity": combinedOpacity(layer, layer.style.fill.opacity),
          },
        },
        {
          id: layerId(layer, "outline"),
          type: "line",
          source: id,
          "source-layer": sourceLayer,
          minzoom: layer.min_zoom,
          maxzoom: layer.max_zoom,
          filter: POLYGON_FILTER,
          layout: {
            visibility: visible(layer.visible, layer.style.outline.enabled),
          },
          paint: {
            "line-color": layer.style.outline.color,
            "line-opacity": combinedOpacity(layer, layer.style.outline.opacity),
            "line-width": layer.style.outline.width,
          },
        },
        {
          id: layerId(layer, "line"),
          type: "line",
          source: id,
          "source-layer": sourceLayer,
          minzoom: layer.min_zoom,
          maxzoom: layer.max_zoom,
          filter: LINE_FILTER,
          layout: {
            visibility: visible(layer.visible, layer.style.line.enabled),
          },
          paint: {
            "line-color": layer.style.line.color,
            "line-opacity": combinedOpacity(layer, layer.style.line.opacity),
            "line-width": layer.style.line.width,
          },
        },
        {
          id: layerId(layer, "point"),
          type: "circle",
          source: id,
          "source-layer": sourceLayer,
          minzoom: layer.min_zoom,
          maxzoom: layer.max_zoom,
          filter: POINT_FILTER,
          layout: {
            visibility: visible(layer.visible, layer.style.point.enabled),
          },
          paint: {
            "circle-color": layer.style.point.color,
            "circle-opacity": combinedOpacity(layer, layer.style.point.opacity),
            "circle-radius": layer.style.point.radius,
            "circle-pitch-scale": "viewport",
            "circle-stroke-color": layer.style.point.stroke_color,
            "circle-stroke-opacity": layer.opacity,
            "circle-stroke-width": layer.style.point.stroke_width,
          },
        },
      );
      const label = layer.style.label ?? DEFAULT_LABEL_STYLE;
      renderLayers.push({
        id: layerId(layer, "label"),
        type: "symbol",
        source: id,
        "source-layer": sourceLayer,
        minzoom: layer.min_zoom,
        maxzoom: layer.max_zoom,
        layout: {
          visibility: visible(layer.visible, layer.style.label !== null),
          "text-field": [
            "coalesce",
            ["to-string", ["get", label.property]],
            "",
          ],
          "text-size": label.size,
        },
        paint: {
          "text-color": label.color,
          "text-opacity": layer.opacity,
          "text-halo-color": label.halo_color,
          "text-halo-width": label.halo_width,
        },
      });
      continue;
    }

    if (layer.source.kind === "raster" && layer.style.kind === "raster") {
      sources[id] = {
        type: "raster",
        url: absoluteApiUrl(workspaceId, layer.source.tilejson_url),
        tileSize: 256,
        attribution: layer.source.attribution ?? undefined,
      };
      renderLayers.push({
        id: layerId(layer, "raster"),
        type: "raster",
        source: id,
        minzoom: layer.min_zoom,
        maxzoom: layer.max_zoom,
        layout: { visibility: visible(layer.visible) },
        paint: {
          "raster-opacity": combinedOpacity(layer, layer.style.opacity),
          "raster-brightness-min": layer.style.brightness_min,
          "raster-brightness-max": layer.style.brightness_max,
          "raster-contrast": layer.style.contrast,
          "raster-saturation": layer.style.saturation,
          "raster-hue-rotate": layer.style.hue,
          "raster-resampling": layer.style.resampling,
        },
      });
    }
  }

  return {
    version: 8,
    glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
    sources,
    layers: renderLayers,
  };
}

function normalizedMapBounds(
  bounds: GeoBounds | null,
): maplibregl.LngLatBoundsLike | null {
  if (!bounds) return null;
  let [west, south, east, north] = bounds;
  if (west === east || south === north) {
    west -= 0.02;
    south -= 0.02;
    east += 0.02;
    north += 0.02;
  }
  return [
    [west, south],
    [east, north],
  ];
}

function fitBounds(
  map: maplibregl.Map,
  bounds: GeoBounds | null,
  animate: boolean,
) {
  const normalizedBounds = normalizedMapBounds(bounds);
  if (!normalizedBounds) return;
  map.fitBounds(normalizedBounds, {
    ...MAP_FIT_OPTIONS,
    duration: animate ? 450 : 0,
  });
}

function setLayerVisibility(
  map: maplibregl.Map,
  id: string,
  isVisible: boolean,
) {
  if (map.getLayer(id)) {
    map.setLayoutProperty(id, "visibility", isVisible ? "visible" : "none");
  }
}

function setPaint(
  map: maplibregl.Map,
  id: string,
  property: string,
  value: unknown,
) {
  if (map.getLayer(id)) map.setPaintProperty(id, property, value);
}

function applyLayerOverrides(
  map: maplibregl.Map,
  layers: readonly GeoRenderLayer[],
) {
  for (const layer of layers) {
    for (const id of layerRenderIds(layer)) {
      if (map.getLayer(id)) {
        map.setLayerZoomRange(id, layer.min_zoom, layer.max_zoom);
      }
    }

    if (layer.style.kind === "raster") {
      const id = layerId(layer, "raster");
      setLayerVisibility(map, id, layer.visible);
      setPaint(
        map,
        id,
        "raster-opacity",
        combinedOpacity(layer, layer.style.opacity),
      );
      setPaint(map, id, "raster-brightness-min", layer.style.brightness_min);
      setPaint(map, id, "raster-brightness-max", layer.style.brightness_max);
      setPaint(map, id, "raster-contrast", layer.style.contrast);
      setPaint(map, id, "raster-saturation", layer.style.saturation);
      setPaint(map, id, "raster-hue-rotate", layer.style.hue);
      setPaint(map, id, "raster-resampling", layer.style.resampling);
      continue;
    }

    if (layer.style.kind === "categorized_points") {
      const label = layer.style.label ?? DEFAULT_LABEL_STYLE;
      for (const category of layer.style.categories) {
        const minzoom = Math.max(layer.min_zoom, category.min_zoom);
        const maxzoom = Math.min(layer.max_zoom, category.max_zoom);
        const labelRadialOffset = category.point.radius / label.size + 0.35;
        const pointId = categoryLayerId(layer, category, "point");
        const labelId = categoryLayerId(layer, category, "label");
        if (map.getLayer(pointId)) {
          map.setLayerZoomRange(pointId, minzoom, maxzoom);
        }
        if (map.getLayer(labelId)) {
          map.setLayerZoomRange(labelId, minzoom, maxzoom);
        }
        setLayerVisibility(
          map,
          pointId,
          layer.visible && category.point.enabled,
        );
        setPaint(map, pointId, "circle-color", category.point.color);
        setPaint(
          map,
          pointId,
          "circle-opacity",
          combinedOpacity(layer, category.point.opacity),
        );
        setPaint(map, pointId, "circle-radius", category.point.radius);
        setPaint(
          map,
          pointId,
          "circle-stroke-color",
          category.point.stroke_color,
        );
        setPaint(map, pointId, "circle-stroke-opacity", layer.opacity);
        setPaint(
          map,
          pointId,
          "circle-stroke-width",
          category.point.stroke_width,
        );
        setLayerVisibility(
          map,
          labelId,
          layer.visible && category.point.enabled && layer.style.label !== null,
        );
        if (map.getLayer(labelId)) {
          map.setLayoutProperty(labelId, "text-field", [
            "coalesce",
            ["to-string", ["get", label.property]],
            "",
          ]);
          map.setLayoutProperty(labelId, "text-size", label.size);
          map.setLayoutProperty(labelId, "text-variable-anchor", [
            "top",
            "bottom",
            "left",
            "right",
          ]);
          map.setLayoutProperty(
            labelId,
            "text-radial-offset",
            labelRadialOffset,
          );
          map.setLayoutProperty(labelId, "text-justify", "auto");
        }
        setPaint(map, labelId, "text-color", label.color);
        setPaint(map, labelId, "text-opacity", layer.opacity);
        setPaint(map, labelId, "text-halo-color", label.halo_color);
        setPaint(map, labelId, "text-halo-width", label.halo_width);
      }
      continue;
    }

    const fillId = layerId(layer, "fill");
    setLayerVisibility(map, fillId, layer.visible && layer.style.fill.enabled);
    setPaint(map, fillId, "fill-color", layer.style.fill.color);
    setPaint(
      map,
      fillId,
      "fill-opacity",
      combinedOpacity(layer, layer.style.fill.opacity),
    );

    for (const [kind, style] of [
      ["outline", layer.style.outline],
      ["line", layer.style.line],
    ] as const) {
      const id = layerId(layer, kind);
      setLayerVisibility(map, id, layer.visible && style.enabled);
      setPaint(map, id, "line-color", style.color);
      setPaint(map, id, "line-opacity", combinedOpacity(layer, style.opacity));
      setPaint(map, id, "line-width", style.width);
    }

    const pointId = layerId(layer, "point");
    setLayerVisibility(
      map,
      pointId,
      layer.visible && layer.style.point.enabled,
    );
    setPaint(map, pointId, "circle-color", layer.style.point.color);
    setPaint(
      map,
      pointId,
      "circle-opacity",
      combinedOpacity(layer, layer.style.point.opacity),
    );
    setPaint(map, pointId, "circle-radius", layer.style.point.radius);
    setPaint(
      map,
      pointId,
      "circle-stroke-color",
      layer.style.point.stroke_color,
    );
    setPaint(map, pointId, "circle-stroke-opacity", layer.opacity);
    setPaint(
      map,
      pointId,
      "circle-stroke-width",
      layer.style.point.stroke_width,
    );

    if (layer.style.label) {
      const labelId = layerId(layer, "label");
      setLayerVisibility(map, labelId, layer.visible);
      if (map.getLayer(labelId)) {
        map.setLayoutProperty(labelId, "text-field", [
          "coalesce",
          ["to-string", ["get", layer.style.label.property]],
          "",
        ]);
        map.setLayoutProperty(labelId, "text-size", layer.style.label.size);
      }
      setPaint(map, labelId, "text-color", layer.style.label.color);
      setPaint(map, labelId, "text-opacity", layer.opacity);
      setPaint(map, labelId, "text-halo-color", layer.style.label.halo_color);
      setPaint(map, labelId, "text-halo-width", layer.style.label.halo_width);
    } else {
      setLayerVisibility(map, layerId(layer, "label"), false);
    }
  }

  for (const layer of layers) {
    for (const id of layerRenderIds(layer)) {
      if (map.getLayer(id)) map.moveLayer(id);
    }
  }
}

function NumberControl({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <label {...stylex.props(s.control)}>
      <span>{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        {...stylex.props(s.controlInput)}
        onChange={(event) => {
          const next = Number(event.currentTarget.value);
          if (Number.isFinite(next))
            onChange(Math.max(min, Math.min(max, next)));
        }}
      />
    </label>
  );
}

function RangeControl({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <label {...stylex.props(s.control, s.controlWide)}>
      <span>{label}</span>
      <span {...stylex.props(s.rangeRow)}>
        <input
          type="range"
          value={value}
          min={min}
          max={max}
          step={step}
          {...stylex.props(s.range)}
          onChange={(event) => onChange(Number(event.currentTarget.value))}
        />
        <output {...stylex.props(s.rangeValue)}>
          {value.toFixed(step < 1 ? 2 : 0)}
        </output>
      </span>
    </label>
  );
}

function ColorControl({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label {...stylex.props(s.control)}>
      <span>{label}</span>
      <input
        type="color"
        value={value}
        {...stylex.props(s.controlInput, s.colorInput)}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
    </label>
  );
}

function EnabledControl({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label {...stylex.props(s.toggle)}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.currentTarget.checked)}
      />
      {label}
    </label>
  );
}

function FillControls({
  title,
  value,
  onChange,
}: {
  title: string;
  value: GeoRenderFillStyle;
  onChange: (value: GeoRenderFillStyle) => void;
}) {
  return (
    <div {...stylex.props(s.section)}>
      <span {...stylex.props(s.sectionTitle)}>{title}</span>
      <EnabledControl
        label="Enabled"
        checked={value.enabled}
        onChange={(enabled) => onChange({ ...value, enabled })}
      />
      <div {...stylex.props(s.controlGrid)}>
        <ColorControl
          label="Color"
          value={value.color}
          onChange={(color) => onChange({ ...value, color })}
        />
        <RangeControl
          label="Opacity"
          value={value.opacity}
          min={0}
          max={1}
          step={0.05}
          onChange={(opacity) => onChange({ ...value, opacity })}
        />
      </div>
    </div>
  );
}

function LineControls({
  title,
  value,
  onChange,
}: {
  title: string;
  value: GeoRenderLineStyle;
  onChange: (value: GeoRenderLineStyle) => void;
}) {
  return (
    <div {...stylex.props(s.section)}>
      <span {...stylex.props(s.sectionTitle)}>{title}</span>
      <EnabledControl
        label="Enabled"
        checked={value.enabled}
        onChange={(enabled) => onChange({ ...value, enabled })}
      />
      <div {...stylex.props(s.controlGrid)}>
        <ColorControl
          label="Color"
          value={value.color}
          onChange={(color) => onChange({ ...value, color })}
        />
        <NumberControl
          label="Width"
          value={value.width}
          min={0}
          max={64}
          step={0.5}
          onChange={(width) => onChange({ ...value, width })}
        />
        <RangeControl
          label="Opacity"
          value={value.opacity}
          min={0}
          max={1}
          step={0.05}
          onChange={(opacity) => onChange({ ...value, opacity })}
        />
      </div>
    </div>
  );
}

function PointControls({
  value,
  onChange,
}: {
  value: GeoRenderPointStyle;
  onChange: (value: GeoRenderPointStyle) => void;
}) {
  return (
    <div {...stylex.props(s.section)}>
      <span {...stylex.props(s.sectionTitle)}>Point</span>
      <EnabledControl
        label="Enabled"
        checked={value.enabled}
        onChange={(enabled) => onChange({ ...value, enabled })}
      />
      <div {...stylex.props(s.controlGrid)}>
        <ColorControl
          label="Color"
          value={value.color}
          onChange={(color) => onChange({ ...value, color })}
        />
        <ColorControl
          label="Stroke"
          value={value.stroke_color}
          onChange={(stroke_color) => onChange({ ...value, stroke_color })}
        />
        <NumberControl
          label="Radius"
          value={value.radius}
          min={0}
          max={128}
          step={0.5}
          onChange={(radius) => onChange({ ...value, radius })}
        />
        <NumberControl
          label="Stroke width"
          value={value.stroke_width}
          min={0}
          max={32}
          step={0.5}
          onChange={(stroke_width) => onChange({ ...value, stroke_width })}
        />
        <RangeControl
          label="Opacity"
          value={value.opacity}
          min={0}
          max={1}
          step={0.05}
          onChange={(opacity) => onChange({ ...value, opacity })}
        />
      </div>
    </div>
  );
}

function LabelControls({
  value,
  onChange,
}: {
  value: GeoRenderLabelStyle;
  onChange: (value: GeoRenderLabelStyle) => void;
}) {
  return (
    <div {...stylex.props(s.section)}>
      <span {...stylex.props(s.sectionTitle)}>Label</span>
      <div {...stylex.props(s.controlGrid)}>
        <label {...stylex.props(s.control, s.controlWide)}>
          <span>Property</span>
          <input
            type="text"
            value={value.property}
            {...stylex.props(s.controlInput)}
            onChange={(event) =>
              onChange({ ...value, property: event.currentTarget.value })
            }
          />
        </label>
        <ColorControl
          label="Color"
          value={value.color}
          onChange={(color) => onChange({ ...value, color })}
        />
        <ColorControl
          label="Halo"
          value={value.halo_color}
          onChange={(halo_color) => onChange({ ...value, halo_color })}
        />
        <NumberControl
          label="Size"
          value={value.size}
          min={6}
          max={72}
          step={1}
          onChange={(size) => onChange({ ...value, size })}
        />
        <NumberControl
          label="Halo width"
          value={value.halo_width}
          min={0}
          max={16}
          step={0.5}
          onChange={(halo_width) => onChange({ ...value, halo_width })}
        />
      </div>
    </div>
  );
}

function VectorControls({
  value,
  onChange,
}: {
  value: GeoRenderVectorStyle;
  onChange: (value: GeoRenderVectorStyle) => void;
}) {
  return (
    <>
      <FillControls
        title="Fill"
        value={value.fill}
        onChange={(fill) => onChange({ ...value, fill })}
      />
      <LineControls
        title="Line"
        value={value.line}
        onChange={(line) => onChange({ ...value, line })}
      />
      <LineControls
        title="Outline"
        value={value.outline}
        onChange={(outline) => onChange({ ...value, outline })}
      />
      <PointControls
        value={value.point}
        onChange={(point) => onChange({ ...value, point })}
      />
      {value.label ? (
        <div {...stylex.props(s.section)}>
          <LabelControls
            value={value.label}
            onChange={(label) => onChange({ ...value, label })}
          />
          <button
            type="button"
            {...stylex.props(s.resetButton)}
            onClick={() => onChange({ ...value, label: null })}
          >
            Disable labels
          </button>
        </div>
      ) : (
        <div {...stylex.props(s.section)}>
          <span {...stylex.props(s.sectionTitle)}>Label</span>
          <button
            type="button"
            {...stylex.props(s.resetButton)}
            onClick={() =>
              onChange({ ...value, label: { ...DEFAULT_LABEL_STYLE } })
            }
          >
            Enable labels
          </button>
        </div>
      )}
    </>
  );
}

function CategorizedPointControls({
  value,
  onChange,
}: {
  value: GeoRenderCategorizedPointStyle;
  onChange: (value: GeoRenderCategorizedPointStyle) => void;
}) {
  const updateCategory = (
    categoryId: string,
    update: (category: GeoRenderPointCategory) => GeoRenderPointCategory,
  ) => {
    onChange({
      ...value,
      categories: value.categories.map((category) =>
        category.id === categoryId ? update(category) : category,
      ),
    });
  };

  return (
    <>
      <div {...stylex.props(s.section)}>
        <span {...stylex.props(s.sectionTitle)}>
          Categories · {value.category_property}
        </span>
        <div {...stylex.props(s.categoryList)}>
          {value.categories.map((category) => (
            <div key={category.id} {...stylex.props(s.categoryRow)}>
              <input
                type="checkbox"
                checked={category.point.enabled}
                aria-label={`Show ${category.title}`}
                onChange={(event) =>
                  updateCategory(category.id, (current) => ({
                    ...current,
                    point: {
                      ...current.point,
                      enabled: event.currentTarget.checked,
                    },
                  }))
                }
              />
              <input
                type="color"
                value={category.point.color}
                aria-label={`${category.title} color`}
                {...stylex.props(s.categoryColor)}
                onChange={(event) =>
                  updateCategory(category.id, (current) => ({
                    ...current,
                    point: {
                      ...current.point,
                      color: event.currentTarget.value,
                    },
                  }))
                }
              />
              <span {...stylex.props(s.categoryText)}>
                <span title={category.title} {...stylex.props(s.categoryTitle)}>
                  {category.title}
                </span>
                <span
                  title={`${category.values.join(", ")} · zoom ${category.min_zoom}–${category.max_zoom}`}
                  {...stylex.props(s.categoryMeta)}
                >
                  {category.values.join(", ")} · z{category.min_zoom}–
                  {category.max_zoom}
                </span>
              </span>
              <input
                type="number"
                value={category.point.radius}
                min={0}
                max={128}
                step={0.5}
                aria-label={`${category.title} radius`}
                title="Point radius"
                {...stylex.props(s.categoryRadius)}
                onChange={(event) => {
                  const radius = Number(event.currentTarget.value);
                  if (!Number.isFinite(radius)) return;
                  updateCategory(category.id, (current) => ({
                    ...current,
                    point: {
                      ...current.point,
                      radius: Math.max(0, Math.min(128, radius)),
                    },
                  }));
                }}
              />
            </div>
          ))}
        </div>
      </div>
      {value.label ? (
        <div {...stylex.props(s.section)}>
          <LabelControls
            value={value.label}
            onChange={(label) => onChange({ ...value, label })}
          />
          <button
            type="button"
            {...stylex.props(s.resetButton)}
            onClick={() => onChange({ ...value, label: null })}
          >
            Disable labels
          </button>
        </div>
      ) : (
        <div {...stylex.props(s.section)}>
          <span {...stylex.props(s.sectionTitle)}>Label</span>
          <button
            type="button"
            {...stylex.props(s.resetButton)}
            onClick={() =>
              onChange({ ...value, label: { ...DEFAULT_LABEL_STYLE } })
            }
          >
            Enable labels
          </button>
        </div>
      )}
    </>
  );
}

function RasterControls({
  value,
  onChange,
}: {
  value: GeoRenderRasterStyle;
  onChange: (value: GeoRenderRasterStyle) => void;
}) {
  return (
    <div {...stylex.props(s.section)}>
      <span {...stylex.props(s.sectionTitle)}>Raster</span>
      <div {...stylex.props(s.controlGrid)}>
        <RangeControl
          label="Opacity"
          value={value.opacity}
          min={0}
          max={1}
          step={0.05}
          onChange={(opacity) => onChange({ ...value, opacity })}
        />
        <RangeControl
          label="Brightness min"
          value={value.brightness_min}
          min={0}
          max={value.brightness_max}
          step={0.05}
          onChange={(brightness_min) => onChange({ ...value, brightness_min })}
        />
        <RangeControl
          label="Brightness max"
          value={value.brightness_max}
          min={value.brightness_min}
          max={1}
          step={0.05}
          onChange={(brightness_max) => onChange({ ...value, brightness_max })}
        />
        <RangeControl
          label="Contrast"
          value={value.contrast}
          min={-1}
          max={1}
          step={0.05}
          onChange={(contrast) => onChange({ ...value, contrast })}
        />
        <RangeControl
          label="Saturation"
          value={value.saturation}
          min={-1}
          max={1}
          step={0.05}
          onChange={(saturation) => onChange({ ...value, saturation })}
        />
        <RangeControl
          label="Hue"
          value={value.hue}
          min={0}
          max={359}
          step={1}
          onChange={(hue) => onChange({ ...value, hue })}
        />
        <label {...stylex.props(s.control, s.controlWide)}>
          <span>Resampling</span>
          <select
            value={value.resampling}
            {...stylex.props(s.controlInput)}
            onChange={(event) =>
              onChange({
                ...value,
                resampling: event.currentTarget.value as "linear" | "nearest",
              })
            }
          >
            <option value="linear">linear</option>
            <option value="nearest">nearest</option>
          </select>
        </label>
      </div>
    </div>
  );
}

function LayerInspector({
  layer,
  index,
  count,
  expanded,
  onExpandedChange,
  onChange,
  onMove,
  onReset,
}: {
  layer: GeoRenderLayer;
  index: number;
  count: number;
  expanded: boolean;
  onExpandedChange: () => void;
  onChange: (layer: GeoRenderLayer) => void;
  onMove: (direction: -1 | 1) => void;
  onReset: () => void;
}) {
  return (
    <section {...stylex.props(s.layer)}>
      <div {...stylex.props(s.layerHeader)}>
        <button
          type="button"
          aria-expanded={expanded}
          title={layer.title}
          {...stylex.props(s.layerTitleButton)}
          onClick={onExpandedChange}
        >
          {index + 1}. {layer.title}
        </button>
        <span {...stylex.props(s.layerActions)}>
          <button
            type="button"
            disabled={index === 0}
            aria-label={`Move ${layer.title} down in the map stack`}
            title="Move down"
            {...stylex.props(s.iconButton)}
            onClick={() => onMove(1)}
          >
            <ArrowDown size={12} aria-hidden="true" />
          </button>
          <button
            type="button"
            disabled={index === count - 1}
            aria-label={`Move ${layer.title} up in the map stack`}
            title="Move up"
            {...stylex.props(s.iconButton)}
            onClick={() => onMove(-1)}
          >
            <ArrowUp size={12} aria-hidden="true" />
          </button>
          <button
            type="button"
            aria-label={`${layer.visible ? "Hide" : "Show"} ${layer.title}`}
            {...stylex.props(s.iconButton)}
            onClick={() => onChange({ ...layer, visible: !layer.visible })}
          >
            {layer.visible ? (
              <Eye size={13} aria-hidden="true" />
            ) : (
              <EyeOff size={13} aria-hidden="true" />
            )}
          </button>
        </span>
      </div>
      {expanded ? (
        <div {...stylex.props(s.controls)}>
          <div {...stylex.props(s.controlGrid)}>
            <RangeControl
              label="Layer opacity"
              value={layer.opacity}
              min={0}
              max={1}
              step={0.05}
              onChange={(opacity) => onChange({ ...layer, opacity })}
            />
            <NumberControl
              label="Min zoom"
              value={layer.min_zoom}
              min={0}
              max={layer.max_zoom}
              step={1}
              onChange={(min_zoom) => onChange({ ...layer, min_zoom })}
            />
            <NumberControl
              label="Max zoom"
              value={layer.max_zoom}
              min={layer.min_zoom}
              max={24}
              step={1}
              onChange={(max_zoom) => onChange({ ...layer, max_zoom })}
            />
          </div>
          {layer.style.kind === "vector" ? (
            <VectorControls
              value={layer.style}
              onChange={(style) => onChange({ ...layer, style })}
            />
          ) : layer.style.kind === "categorized_points" ? (
            <CategorizedPointControls
              value={layer.style}
              onChange={(style) => onChange({ ...layer, style })}
            />
          ) : (
            <RasterControls
              value={layer.style}
              onChange={(style) => onChange({ ...layer, style })}
            />
          )}
          <button
            type="button"
            {...stylex.props(s.resetButton)}
            onClick={onReset}
          >
            <RotateCcw size={11} aria-hidden="true" />
            Reset layer
          </button>
        </div>
      ) : null}
    </section>
  );
}

function GeoMapPreview({
  descriptor,
  availableHeight,
  onUnload,
  interaction,
}: {
  descriptor: GeoRenderDescriptor;
  availableHeight?: number;
  onUnload: () => void;
  interaction?: ArtifactViewerInteractionContext;
}) {
  const { workspace } = useWorkspaceContext();
  const workspaceId = workspace.id;
  const containerRef = React.useRef<HTMLDivElement>(null);
  const mapRef = React.useRef<maplibregl.Map | null>(null);
  const [layers, setLayers] = React.useState(() =>
    descriptor.layers.map(cloneLayer),
  );
  const [inspectorOpen, setInspectorOpen] = React.useState(false);
  const [expandedLayerId, setExpandedLayerId] = React.useState<string | null>(
    null,
  );
  const [mapReady, setMapReady] = React.useState(false);
  const [mapError, setMapError] = React.useState<string | null>(null);
  const [selectedFeature, setSelectedFeature] =
    React.useState<SelectedGeoFeature | null>(null);
  const layersRef = React.useRef(layers);
  const interactionRef = React.useRef(interaction);
  const focusedSelectionRef = React.useRef<{
    map: maplibregl.Map;
    signature: string;
  } | null>(null);
  const inspectorId = React.useId();
  const focusBindings =
    interaction?.incoming.filter((binding) =>
      binding.effects.includes("focus"),
    ) ?? [];
  const focusRows = focusBindings.flatMap((binding) => binding.rows);
  const unmappedFocusSelectionCount = focusBindings.reduce(
    (count, binding) =>
      count + Math.max(0, binding.sourceSelectionCount - binding.rows.length),
    0,
  );
  const focusSignature = JSON.stringify(focusRows);
  const focusKey = focusRows.length
    ? ([
        "geo-artifact-focus",
        workspaceId,
        descriptor.artifact_id,
        focusSignature,
      ] as const)
    : null;
  const {
    data: focusResult,
    error: focusError,
    isValidating: focusLoading,
    mutate: retryFocus,
  } = useSWR(focusKey, ([, keyWorkspaceId, artifactId]) =>
    queryArtifactGeoFeatures(keyWorkspaceId, artifactId, {
      rows: focusRows.map((values) => ({ values })),
    }),
  );

  React.useEffect(() => {
    layersRef.current = layers;
  }, [layers]);

  React.useEffect(() => {
    interactionRef.current = interaction;
  }, [interaction]);

  React.useEffect(() => {
    if (!interaction) return;
    const fields = new Map<
      string,
      { id: string; title: string; valueType: string }
    >();
    for (const layer of descriptor.layers) {
      if (layer.source.kind !== "vector") continue;
      for (const field of layer.source.fields ?? []) {
        fields.set(field.id, {
          id: field.id,
          title: field.title,
          valueType: field.value_type,
        });
      }
    }
    interaction.onFieldsChange([...fields.values()]);
  }, [descriptor.layers, interaction]);

  React.useEffect(() => {
    if (!containerRef.current) return;
    ensurePmtilesProtocol();
    const interactiveLayerIds = descriptor.layers.flatMap((layer) => {
      if (layer.style.kind === "vector") {
        return [
          layerId(layer, "fill"),
          layerId(layer, "line"),
          layerId(layer, "point"),
        ];
      }
      if (layer.style.kind === "categorized_points") {
        return layer.style.categories.map((category) =>
          categoryLayerId(layer, category, "point"),
        );
      }
      return [];
    });
    let map: maplibregl.Map;
    try {
      const mapOptions: maplibregl.MapOptions = {
        container: containerRef.current,
        style: createGeoMapStyle(workspaceId, descriptor, layersRef.current),
        attributionControl: true,
      };
      const initialBounds = normalizedMapBounds(descriptor.initial_bounds);
      if (initialBounds) {
        mapOptions.bounds = initialBounds;
        mapOptions.fitBoundsOptions = { ...MAP_FIT_OPTIONS, duration: 0 };
      } else {
        mapOptions.center = [0, 18];
        mapOptions.zoom = 1.25;
      }
      map = new maplibregl.Map(mapOptions);
    } catch (error) {
      const message =
        error instanceof Error
          ? error.message
          : "The browser could not initialize the interactive map";
      const errorTimer = window.setTimeout(() => setMapError(message), 0);
      return () => window.clearTimeout(errorTimer);
    }
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    const renderedFeaturesAt = (event: maplibregl.MapMouseEvent) => {
      const canvas = map.getCanvas();
      const displayedBounds = canvas.getBoundingClientRect();
      const scaleX =
        displayedBounds.width > 0 && canvas.clientWidth > 0
          ? canvas.clientWidth / displayedBounds.width
          : 1;
      const scaleY =
        displayedBounds.height > 0 && canvas.clientHeight > 0
          ? canvas.clientHeight / displayedBounds.height
          : 1;
      const canvasIsScaled =
        Math.abs(scaleX - 1) > 0.001 || Math.abs(scaleY - 1) > 0.001;
      // React Flow scales the viewer with CSS while MapLibre queries its
      // unscaled canvas coordinate system.
      const point: [number, number] = [
        event.point.x * scaleX,
        event.point.y * scaleY,
      ];
      // Keep sparse points easy to select without making their visual markers larger.
      const queryBounds: [maplibregl.PointLike, maplibregl.PointLike] = [
        [
          point[0] - FEATURE_HIT_RADIUS * scaleX,
          point[1] - FEATURE_HIT_RADIUS * scaleY,
        ],
        [
          point[0] + FEATURE_HIT_RADIUS * scaleX,
          point[1] + FEATURE_HIT_RADIUS * scaleY,
        ],
      ];
      const renderedLayerIds = interactiveLayerIds.filter((id) =>
        map.getLayer(id),
      );
      const features = renderedLayerIds.length
        ? map.queryRenderedFeatures(queryBounds, { layers: renderedLayerIds })
        : [];
      return {
        features,
        lngLat: canvasIsScaled ? map.unproject(point) : event.lngLat,
      };
    };
    map.on("mousemove", (event) => {
      map
        .getCanvasContainer()
        .classList.toggle(
          "maplibregl-track-pointer",
          renderedFeaturesAt(event).features.length > 0,
        );
    });
    map.on("mouseout", () => {
      map.getCanvasContainer().classList.remove("maplibregl-track-pointer");
    });
    map.on("dragstart", () => {
      map.getCanvasContainer().classList.remove("maplibregl-track-pointer");
    });
    map.on("click", (event) => {
      const { features, lngLat } = renderedFeaturesAt(event);
      const feature = features[0];
      if (!feature) {
        setSelectedFeature(null);
        interactionRef.current?.onSelectionChange({
          kind: "key-selection",
          items: [],
        });
        return;
      }

      const ownerLayer = layersRef.current.find((layer) =>
        layerRenderIds(layer).includes(feature.layer.id),
      );
      const rawProperties: Record<string, unknown> =
        feature.properties && typeof feature.properties === "object"
          ? feature.properties
          : {};
      const titleProperty =
        ownerLayer?.style.kind === "vector" ||
        ownerLayer?.style.kind === "categorized_points"
          ? (ownerLayer.style.label?.property ?? DEFAULT_LABEL_STYLE.property)
          : DEFAULT_LABEL_STYLE.property;
      const titleValue = rawProperties[titleProperty];
      const featureId =
        feature.id === undefined || feature.id === null
          ? null
          : String(feature.id);
      const properties = Object.entries(rawProperties)
        .map(([name, rawValue]) => {
          let value: string;
          if (rawValue === null) {
            value = "null";
          } else if (
            typeof rawValue === "string" ||
            typeof rawValue === "number" ||
            typeof rawValue === "boolean"
          ) {
            value = String(rawValue);
          } else {
            value = JSON.stringify(rawValue) ?? String(rawValue);
          }
          return { name, value };
        })
        .sort((left, right) => left.name.localeCompare(right.name));
      const selectionValues = Object.fromEntries(
        Object.entries(rawProperties).flatMap(([name, value]) =>
          value === null ||
          typeof value === "string" ||
          typeof value === "number" ||
          typeof value === "boolean"
            ? [[name, value]]
            : [],
        ),
      );
      const title =
        typeof titleValue === "string" && titleValue.trim()
          ? titleValue
          : featureId
            ? `Feature ${featureId}`
            : `${feature.geometry.type} feature`;

      setInspectorOpen(false);
      setSelectedFeature({
        layerId: ownerLayer?.id ?? feature.layer.id,
        layerTitle: ownerLayer?.title ?? "Map feature",
        title,
        geometryType: feature.geometry.type,
        featureId,
        longitude: lngLat.lng,
        latitude: lngLat.lat,
        properties,
        selectionValues,
      });
      interactionRef.current?.onSelectionChange({
        kind: "key-selection",
        items: [{ values: selectionValues }],
      });
    });
    map.on("load", () => {
      setMapReady(true);
      applyLayerOverrides(map, layersRef.current);
    });
    map.on("error", (event) => {
      const message = event.error?.message;
      if (message) setMapError(message);
    });
    return () => {
      mapRef.current = null;
      map.getCanvasContainer().classList.remove("maplibregl-track-pointer");
      map.remove();
    };
  }, [descriptor, workspaceId]);

  React.useEffect(() => {
    const map = mapRef.current;
    if (!mapReady || !map?.isStyleLoaded()) return;
    applyInteractionOverrides(map, layers, interaction?.incoming ?? []);
  }, [interaction?.incoming, layers, mapReady]);

  React.useEffect(() => {
    if (!focusRows.length) {
      focusedSelectionRef.current = null;
      return;
    }
    const map = mapRef.current;
    if (
      !mapReady ||
      !map?.isStyleLoaded() ||
      !focusResult?.bounds ||
      (focusedSelectionRef.current?.map === map &&
        focusedSelectionRef.current.signature === focusSignature)
    ) {
      return;
    }
    fitBounds(map, focusResult.bounds, true);
    focusedSelectionRef.current = { map, signature: focusSignature };
  }, [focusResult?.bounds, focusRows.length, focusSignature, mapReady]);

  React.useEffect(() => {
    mapRef.current?.resize();
  }, [availableHeight]);

  const updateLayer = (index: number, next: GeoRenderLayer) => {
    setSelectedFeature((current) =>
      current?.layerId === next.id ? null : current,
    );
    setLayers((current) =>
      current.map((layer, currentIndex) =>
        currentIndex === index ? next : layer,
      ),
    );
  };

  const moveLayer = (index: number, direction: -1 | 1) => {
    setLayers((current) => {
      const nextIndex = index + direction;
      if (nextIndex < 0 || nextIndex >= current.length) return current;
      const next = [...current];
      [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
      return next;
    });
  };

  const viewerActivity = React.useMemo<ArtifactViewerActivity | null>(() => {
    if (mapError) {
      return {
        state: "error",
        title: "Map rendering failed",
        message: mapError,
      };
    }
    if (!mapReady) {
      return {
        state: "working",
        title: "Loading interactive map",
        message: "Preparing map layers.",
      };
    }
    if (focusError) {
      const detail =
        focusError instanceof Error
          ? focusError.message
          : "The map query failed.";
      return {
        state: "error",
        title: "Linked selection lookup failed",
        message: detail,
        retry: () => void retryFocus(),
      };
    }
    if (focusLoading) {
      return {
        state: "working",
        title: "Locating linked selection",
        message: "Searching the map layers for matching features.",
      };
    }
    if (unmappedFocusSelectionCount > 0 && focusRows.length === 0) {
      return {
        state: "warning",
        title: "Selection mapping failed",
        message:
          "The selected row does not provide all configured target fields.",
      };
    }
    if (focusResult?.matched_feature_count === 0) {
      return {
        state: "warning",
        title: "No linked feature found",
        message: "No map feature matched the linked selection.",
      };
    }
    if (
      focusResult &&
      focusResult.matched_feature_count > 0 &&
      !focusResult.bounds
    ) {
      const featureLabel =
        focusResult.matched_feature_count === 1 ? "feature" : "features";
      return {
        state: "warning",
        title: "Linked feature has no geometry",
        message: `Matched ${focusResult.matched_feature_count} ${featureLabel}, but no geometry was available to focus.`,
      };
    }
    if (focusResult?.matched_feature_count === 1) {
      return {
        state: unmappedFocusSelectionCount > 0 ? "warning" : "success",
        title: "Linked feature located",
        message: "Located 1 matching map feature.",
      };
    }
    if (focusResult && focusResult.matched_feature_count > 1) {
      return {
        state: "warning",
        title: "Multiple linked features located",
        message: `Located ${focusResult.matched_feature_count} matches; showing their combined extent.`,
      };
    }
    return null;
  }, [
    focusError,
    focusLoading,
    focusResult,
    focusRows.length,
    mapError,
    mapReady,
    retryFocus,
    unmappedFocusSelectionCount,
  ]);

  React.useEffect(() => {
    interaction?.onActivityChange(viewerActivity);
    return () => interaction?.onActivityChange(null);
  }, [interaction, viewerActivity]);

  return (
    <div
      data-grafy-geo-map="true"
      {...mapInteractionProps(stylex.props(s.shell))}
      style={{ height: Math.max(320, availableHeight ?? 420) }}
    >
      <div
        ref={containerRef}
        aria-label="Interactive GIS map. Click a feature to inspect its properties."
        {...mapInteractionProps(stylex.props(s.map))}
      />
      <div {...stylex.props(s.mapControls)}>
        <button
          type="button"
          aria-expanded={inspectorOpen}
          aria-controls={inspectorId}
          {...mapInteractionProps(stylex.props(s.utilityButton))}
          onClick={() => {
            setSelectedFeature(null);
            setInspectorOpen((open) => !open);
          }}
        >
          <Layers3 size={13} aria-hidden="true" />
          {layers.length} {layers.length === 1 ? "layer" : "layers"}
        </button>
        <button
          type="button"
          disabled={!descriptor.initial_bounds}
          aria-label="Fit descriptor bounds"
          title={
            descriptor.initial_bounds
              ? "Fit descriptor bounds"
              : "No descriptor bounds"
          }
          {...mapInteractionProps(stylex.props(s.utilityButton))}
          onClick={() => {
            const map = mapRef.current;
            if (map) fitBounds(map, descriptor.initial_bounds, true);
          }}
        >
          <LocateFixed size={13} aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label="Unload interactive map"
          title="Unload interactive map"
          {...mapInteractionProps(stylex.props(s.utilityButton))}
          onClick={onUnload}
        >
          <X size={13} aria-hidden="true" />
        </button>
      </div>
      {inspectorOpen ? (
        <div
          id={inspectorId}
          role="region"
          aria-label="Map layer inspector"
          {...mapInteractionProps(stylex.props(s.inspector))}
        >
          <div {...stylex.props(s.inspectorHeader)}>
            <span {...stylex.props(s.inspectorTitle)}>Layer inspector</span>
            <button
              type="button"
              {...stylex.props(s.resetButton)}
              onClick={() => setLayers(descriptor.layers.map(cloneLayer))}
            >
              <RotateCcw size={11} aria-hidden="true" />
              Reset all
            </button>
          </div>
          {layers.map((layer, index) => (
            <LayerInspector
              key={layer.id}
              layer={layer}
              index={index}
              count={layers.length}
              expanded={expandedLayerId === layer.id}
              onExpandedChange={() =>
                setExpandedLayerId((current) =>
                  current === layer.id ? null : layer.id,
                )
              }
              onChange={(next) => updateLayer(index, next)}
              onMove={(direction) => moveLayer(index, direction)}
              onReset={() => {
                const original = descriptor.layers.find(
                  (candidate) => candidate.id === layer.id,
                );
                if (original) updateLayer(index, cloneLayer(original));
              }}
            />
          ))}
        </div>
      ) : null}
      {selectedFeature ? (
        <section
          role="region"
          aria-label="Selected feature details"
          {...mapInteractionProps(stylex.props(s.featurePanel))}
        >
          <header {...stylex.props(s.featureHeader)}>
            <span {...stylex.props(s.featureHeading)}>
              <span {...stylex.props(s.featureKicker)}>
                {selectedFeature.layerTitle} · {selectedFeature.geometryType}
              </span>
              <span {...stylex.props(s.featureTitle)}>
                {selectedFeature.title}
              </span>
              <span {...stylex.props(s.featureMeta)}>
                {selectedFeature.featureId
                  ? `ID ${selectedFeature.featureId} · `
                  : ""}
                {selectedFeature.longitude.toFixed(5)},{" "}
                {selectedFeature.latitude.toFixed(5)}
              </span>
            </span>
            <button
              type="button"
              aria-label="Close feature details"
              title="Close feature details"
              {...mapInteractionProps(stylex.props(s.iconButton))}
              onClick={() => {
                setSelectedFeature(null);
                interaction?.onSelectionChange({
                  kind: "key-selection",
                  items: [],
                });
              }}
            >
              <X size={13} aria-hidden="true" />
            </button>
          </header>
          {selectedFeature.properties.length ? (
            <dl {...stylex.props(s.featureProperties)}>
              {selectedFeature.properties.map((property) => (
                <div key={property.name} {...stylex.props(s.featureProperty)}>
                  <dt
                    title={property.name}
                    {...stylex.props(s.featurePropertyName)}
                  >
                    {property.name}
                  </dt>
                  <dd {...stylex.props(s.featurePropertyValue)}>
                    {property.value}
                  </dd>
                </div>
              ))}
            </dl>
          ) : (
            <p {...stylex.props(s.featureEmpty)}>
              This feature has no properties.
            </p>
          )}
        </section>
      ) : null}
    </div>
  );
}

function GeoMapRendererState({
  artifact,
  mode,
  availableHeight,
  interaction,
}: {
  artifact: ArtifactSummary;
  mode: string;
  availableHeight?: number;
  interaction?: ArtifactViewerInteractionContext;
}) {
  const { workspace } = useWorkspaceContext();
  const [loadRequested, setLoadRequested] = React.useState(false);
  const renderKey = loadRequested
    ? (["geo-artifact-render", workspace.id, artifact.artifact_id] as const)
    : null;
  const {
    data: descriptor,
    error,
    isLoading,
    mutate,
  } = useSWR(renderKey, ([, workspaceId, artifactId]) =>
    getArtifactGeoRender(workspaceId, artifactId),
  );

  if (!loadRequested) {
    return (
      <div {...mapInteractionProps(stylex.props(s.shell))}>
        <div {...stylex.props(s.placeholder)}>
          <div {...stylex.props(s.placeholderContent)}>
            <MapIcon
              size={26}
              aria-hidden="true"
              {...stylex.props(s.placeholderIcon)}
            />
            <span {...stylex.props(s.placeholderTitle)}>GIS preview ready</span>
            <span {...stylex.props(s.placeholderCopy)}>
              Load the render descriptor when you want to inspect this artifact.
            </span>
            <button
              type="button"
              {...mapInteractionProps(stylex.props(s.primaryButton))}
              onClick={() => setLoadRequested(true)}
            >
              Load interactive map
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div {...mapInteractionProps(stylex.props(s.shell))}>
        <div {...stylex.props(s.placeholder)}>
          <div role="alert" {...stylex.props(s.placeholderContent)}>
            <span {...stylex.props(s.placeholderTitle)}>
              GIS preview unavailable
            </span>
            <span {...stylex.props(s.placeholderCopy)}>
              The render descriptor could not be loaded.
            </span>
            <span {...stylex.props(s.actions)}>
              <button
                type="button"
                {...stylex.props(s.primaryButton)}
                onClick={() => void mutate()}
              >
                Retry
              </button>
              <button
                type="button"
                {...stylex.props(s.resetButton)}
                onClick={() => setLoadRequested(false)}
              >
                Unload
              </button>
            </span>
          </div>
        </div>
      </div>
    );
  }

  if (isLoading || !descriptor) {
    return (
      <div {...mapInteractionProps(stylex.props(s.shell))}>
        <div role="status" {...stylex.props(s.placeholder)}>
          Loading GIS render descriptor…
        </div>
      </div>
    );
  }

  if (mode === "raw") {
    return (
      <div {...stylex.props(s.rawShell)}>
        <div {...stylex.props(s.rawHeader)}>
          <span {...stylex.props(s.rawMeta)}>
            {descriptor.kind} · {descriptor.layers.length}{" "}
            {descriptor.layers.length === 1 ? "layer" : "layers"}
          </span>
          <button
            type="button"
            {...stylex.props(s.resetButton)}
            onClick={() => setLoadRequested(false)}
          >
            Unload
          </button>
        </div>
        <pre {...stylex.props(s.raw)}>
          {JSON.stringify(descriptor, null, 2)}
        </pre>
      </div>
    );
  }

  return (
    <GeoMapPreview
      descriptor={descriptor}
      availableHeight={availableHeight}
      onUnload={() => setLoadRequested(false)}
      interaction={interaction}
    />
  );
}

export function GeoMapArtifactRenderer({
  artifact,
  mode,
  availableHeight,
  interaction,
}: {
  artifact: ArtifactSummary;
  payload?: unknown;
  mode: string;
  availableHeight?: number;
  interaction?: ArtifactViewerInteractionContext;
}) {
  return (
    <GeoMapRendererState
      key={artifact.artifact_id}
      artifact={artifact}
      mode={mode}
      availableHeight={availableHeight}
      interaction={interaction}
    />
  );
}
