import maplibregl from "maplibre-gl";

import type { GeoRenderLabelStyle } from "@/lib/api";
import type { ArtifactInteractionScalar } from "../../artifact-interactions";

export const MAP_FIT_OPTIONS = { padding: 28, maxZoom: 14 } as const;

export const FEATURE_HIT_RADIUS = 12;

export const OSM_SOURCE_ID = "grafy-openstreetmap";

export const OSM_LAYER_ID = "grafy-openstreetmap-raster";

export const POINT_FILTER: maplibregl.FilterSpecification = [
  "any",
  ["==", ["geometry-type"], "Point"],
  ["==", ["geometry-type"], "MultiPoint"],
];

export const POLYGON_FILTER: maplibregl.FilterSpecification = [
  "any",
  ["==", ["geometry-type"], "Polygon"],
  ["==", ["geometry-type"], "MultiPolygon"],
];

export const LINE_FILTER: maplibregl.FilterSpecification = [
  "any",
  ["==", ["geometry-type"], "LineString"],
  ["==", ["geometry-type"], "MultiLineString"],
];

export const DEFAULT_LABEL_STYLE: GeoRenderLabelStyle = {
  property: "name",
  color: "#111827",
  size: 12,
  halo_color: "#ffffff",
  halo_width: 1,
};

export type SelectedGeoFeature = {
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
