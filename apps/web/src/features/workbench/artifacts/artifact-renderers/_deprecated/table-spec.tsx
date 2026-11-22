"use client";

import { isTableArtifact } from "../../artifact-card";
import { TableArtifactRenderer } from "../table-renderer";

import type { ArtifactRendererSpec } from "./spec";

/** Old registry entry. The card mounts `TableArtifactRenderer` directly. */
export const tableRenderer: ArtifactRendererSpec = {
  id: "table",
  modes: ["table", "raw"],
  interaction: {
    emits: ["key-selection"],
    accepts: ["filter", "highlight"],
  },
  matches: isTableArtifact,
  Component: ({ artifact, mode, availableHeight, interaction }) => (
    <TableArtifactRenderer
      artifact={artifact}
      mode={mode}
      availableHeight={availableHeight}
      interaction={interaction}
    />
  ),
};
