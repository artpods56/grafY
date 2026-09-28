import maplibregl from "maplibre-gl";

import type {
  GeoRenderCategorizedPointStyle,
  GeoRenderLayer,
  GeoRenderPointCategory,
} from "@/lib/api";
import type {
  ArtifactInteractionScalar,
  ArtifactViewerIncomingBinding,
} from "../../artifact-interactions";

import { categoryLayerId, layerId } from "./layer-identity";
import { LINE_FILTER, POINT_FILTER, POLYGON_FILTER } from "./style-constants";

export function visible(
  visibleLayer: boolean,
  enabled = true,
): "visible" | "none" {
  return visibleLayer && enabled ? "visible" : "none";
}

export function combinedOpacity(
  layer: GeoRenderLayer,
  opacity: number,
): number {
  return Math.max(0, Math.min(1, layer.opacity * opacity));
}

export function categoryFilter(
  style: GeoRenderCategorizedPointStyle,
  category: GeoRenderPointCategory,
): maplibregl.FilterSpecification {
  return [
    "all",
    POINT_FILTER,
    ["in", ["get", style.category_property], ["literal", [...category.values]]],
  ] as maplibregl.FilterSpecification;
}

export function interactionRowsFilter(
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

export function interactionEffectFilter(
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

export function baseRenderFilter(
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

export function filtersTogether(
  left: maplibregl.FilterSpecification | null,
  right: maplibregl.FilterSpecification | null,
): maplibregl.FilterSpecification | null {
  if (!left) return right;
  if (!right) return left;
  return ["all", left, right] as maplibregl.FilterSpecification;
}
