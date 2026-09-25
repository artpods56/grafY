"use client";

import * as React from "react";

import type { ArtifactSummary } from "@/lib/api";
import type {
  ArtifactViewerEffect,
  ArtifactViewerInteractionContext,
} from "../../artifact-interactions";

import { artifactMeta } from "./artifact-meta";
import { geoMapRenderer } from "./geo-map-renderer";
import { imageRenderer } from "./image-renderer";
import { jsonRenderer, jsonSchemaRenderer } from "./json-renderer";
import { markdownRenderer } from "./markdown-renderer";
import { PrettyValue } from "./pretty-value";
import { tableRenderer } from "./table-renderer";

export interface ArtifactRenderProps {
  artifact: ArtifactSummary;
  payload?: unknown;
  mode: string;
  availableHeight?: number;
  interaction?: ArtifactViewerInteractionContext;
}

export interface ArtifactRendererInteractionCapabilities {
  emits: readonly "key-selection"[];
  accepts: readonly ArtifactViewerEffect[];
}

export interface ArtifactRendererSpec {
  id: string;
  modes: readonly string[];
  interaction?: ArtifactRendererInteractionCapabilities;
  matches(artifact: ArtifactSummary, payload?: unknown): boolean;
  Component: React.ComponentType<ArtifactRenderProps>;
}

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
  jsonRenderer,
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
