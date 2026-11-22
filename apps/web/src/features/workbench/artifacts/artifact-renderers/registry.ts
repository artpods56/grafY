"use client";

import * as React from "react";

import type { ArtifactSummary } from "@/lib/api";

import { artifactMeta } from "./artifact-meta";
import { fileTextRenderer } from "./file-text-renderer";
import { geoMapRenderer } from "./geo-map-renderer";
import { imageRenderer } from "./image-renderer";
import {
  jsonRenderer,
  jsonSchemaRenderer,
  scalarRenderer,
} from "./json-renderer";
import { markdownRenderer } from "./markdown-renderer";
import { PrettyValue } from "./pretty-value";
import type { ArtifactRendererSpec } from "./spec";
import { tableRenderer } from "./table-renderer";

export const META_ARTIFACT_RENDERER: ArtifactRendererSpec = {
  id: "meta",
  modes: ["meta"],
  matches: () => true,
  Component: ({ artifact }) =>
    React.createElement(PrettyValue, { value: artifactMeta(artifact) }),
};

export const ARTIFACT_RENDERERS: readonly ArtifactRendererSpec[] = [
  imageRenderer,
  geoMapRenderer,
  tableRenderer,
  jsonSchemaRenderer,
  markdownRenderer,
  scalarRenderer,
  jsonRenderer,
  fileTextRenderer,
  META_ARTIFACT_RENDERER,
];

export function rendererFor(
  artifact: ArtifactSummary,
  payload?: unknown,
): ArtifactRendererSpec {
  return (
    ARTIFACT_RENDERERS.find((renderer) =>
      renderer.matches(artifact, payload),
    ) ?? META_ARTIFACT_RENDERER
  );
}

/** Table and map opt in; markdown, image, JSON, and empty previews do not. */
export function rendererCanBrush(
  artifact: ArtifactSummary | undefined,
): boolean {
  if (!artifact) return false;
  const interaction = rendererFor(artifact).interaction;
  return Boolean(
    interaction &&
    (interaction.emits.length > 0 || interaction.accepts.length > 0),
  );
}
