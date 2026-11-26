import maplibregl from "maplibre-gl";

import {
  artifactContentUrl,
  type GeoBounds,
  type GeoRenderDescriptor,
  type GeoRenderLayer,
} from "@/lib/api";

import { categoryFilter, combinedOpacity, visible } from "./layer-filters";
import { categoryLayerId, layerId, sourceId } from "./layer-identity";
import {
  DEFAULT_LABEL_STYLE,
  LINE_FILTER,
  MAP_FIT_OPTIONS,
  OSM_LAYER_ID,
  OSM_SOURCE_ID,
  POINT_FILTER,
  POLYGON_FILTER,
} from "./style-constants";

export function absoluteApiUrl(workspaceId: string, path: string): string {
  return artifactContentUrl(workspaceId, path) ?? path;
}

/**
 * A MapLibre raster source knows `attribution` as a string or not at all, and a
 * TileJSON without one reaches us as `null`. Writing the key with `undefined`
 * type-checks against the optional property but fails style validation when the
 * map loads (`sources.<id>.attribution: string expected, undefined found`), so a
 * blank attribution — empty, whitespace, or absent — leaves the key out instead.
 */
function rasterAttribution(
  attribution: string | null | undefined,
): string | null {
  const trimmed = attribution?.trim();
  return trimmed ? trimmed : null;
}

/**
 * The MapLibre style for one render descriptor.
 *
 * A raster layer reads tiles through its TileJSON. A feature layer reads its
 * collection's stored features as one GeoJSON document and is drawn and styled
 * here, so the layer inspector can restyle it without another request. A layer
 * whose style does not fit its source is skipped rather than drawn from
 * something the descriptor never named.
 */
export function createGeoMapStyle(
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
      layer.source.kind === "geojson" &&
      layer.style.kind === "categorized_points"
    ) {
      sources[id] = {
        type: "geojson",
        data: absoluteApiUrl(workspaceId, layer.source.data_url),
      };
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
    if (layer.source.kind === "geojson" && layer.style.kind === "vector") {
      sources[id] = {
        type: "geojson",
        data: absoluteApiUrl(workspaceId, layer.source.data_url),
      };
      const label = layer.style.label ?? DEFAULT_LABEL_STYLE;
      renderLayers.push(
        {
          id: layerId(layer, "fill"),
          type: "fill",
          source: id,
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
        {
          id: layerId(layer, "label"),
          type: "symbol",
          source: id,
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
        },
      );
      continue;
    }
    if (layer.source.kind === "raster" && layer.style.kind === "raster") {
      const source: maplibregl.RasterSourceSpecification = {
        type: "raster",
        url: absoluteApiUrl(workspaceId, layer.source.tilejson_url),
        tileSize: 256,
      };
      const attribution = rasterAttribution(layer.source.attribution);
      if (attribution !== null) source.attribution = attribution;
      sources[id] = source;
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

export function normalizedMapBounds(
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

export function fitBounds(
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

export function setLayerVisibility(
  map: maplibregl.Map,
  id: string,
  isVisible: boolean,
) {
  if (map.getLayer(id)) {
    map.setLayoutProperty(id, "visibility", isVisible ? "visible" : "none");
  }
}

export function setPaint(
  map: maplibregl.Map,
  id: string,
  property: string,
  value: unknown,
) {
  if (map.getLayer(id)) map.setPaintProperty(id, property, value);
}
