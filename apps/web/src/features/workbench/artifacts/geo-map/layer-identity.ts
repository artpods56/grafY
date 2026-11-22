import type { GeoRenderLayer, GeoRenderPointCategory } from "@/lib/api";

export function sourceId(layer: GeoRenderLayer): string {
  return `grafy-geo-source-${layer.id}`;
}

export function layerId(layer: GeoRenderLayer, kind: string): string {
  return `grafy-geo-${layer.id}-${kind}`;
}

export function categoryLayerId(
  layer: GeoRenderLayer,
  category: GeoRenderPointCategory,
  kind: "point" | "label",
): string {
  return layerId(layer, `category-${category.id}-${kind}`);
}

export function layerRenderIds(layer: GeoRenderLayer): string[] {
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

export function cloneLayer(layer: GeoRenderLayer): GeoRenderLayer {
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
