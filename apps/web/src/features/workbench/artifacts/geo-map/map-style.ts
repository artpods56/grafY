import maplibregl from "maplibre-gl";

import {
  artifactContentUrl,
  type GeoBounds,
  type GeoRenderDescriptor,
  type GeoRenderLayer,
} from "@/lib/api";

import { combinedOpacity, visible } from "./layer-filters";
import { layerId, sourceId } from "./layer-identity";
import {
  MAP_FIT_OPTIONS,
  OSM_LAYER_ID,
  OSM_SOURCE_ID,
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
 * A layer reaches the map only through its raster source: a tilejson URL the
 * browser can fetch as tiles. The render contract carries no other source kind,
 * so a layer whose style is not a raster style is skipped rather than drawn from
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
