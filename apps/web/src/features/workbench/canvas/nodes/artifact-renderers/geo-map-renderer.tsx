"use client";

import { GeoMapArtifactRenderer } from "../geo-map-artifact-renderer";

import type { ArtifactRendererSpec } from "./registry";

export const geoMapRenderer: ArtifactRendererSpec = {
  id: "geo-map",
  modes: ["map", "raw"],
  interaction: {
    emits: ["key-selection"],
    accepts: ["filter", "highlight", "focus"],
  },
  matches: (artifact) =>
    [
      "geo.feature_collection",
      "geo.raster_scan",
      "geo.map_layer",
      "geo.map_document",
    ].includes(artifact.artifact_type) && artifact.schema_version === 1,
  Component: GeoMapArtifactRenderer,
};
