import maplibregl from "maplibre-gl";

import type { GeoRenderLayer } from "@/lib/api";
import type { ArtifactViewerIncomingBinding } from "../../artifact-interactions";

import {
  baseRenderFilter,
  combinedOpacity,
  filtersTogether,
  interactionEffectFilter,
} from "./layer-filters";
import { categoryLayerId, layerId, layerRenderIds } from "./layer-identity";
import { setLayerVisibility, setPaint } from "./map-style";
import { DEFAULT_LABEL_STYLE } from "./style-constants";

export function applyInteractionOverrides(
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

export function applyLayerOverrides(
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
