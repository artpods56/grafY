"use client";

import { isGeoMapArtifact } from "../artifact-card";
import { GeoMapArtifactRenderer } from "../geo-map-artifact-renderer";

import type { ArtifactRendererSpec } from "./spec";

export const geoMapRenderer: ArtifactRendererSpec = {
  id: "geo-map",
  modes: ["map", "raw"],
  interaction: {
    emits: ["key-selection"],
    accepts: ["filter", "highlight", "focus"],
  },
  matches: isGeoMapArtifact,
  Component: GeoMapArtifactRenderer,
};
