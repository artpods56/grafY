import type { ComponentType } from "react";

import type { ArtifactSummary } from "@/lib/api";
import type {
  ArtifactViewerEffect,
  ArtifactViewerInteractionContext,
} from "../../artifact-interactions";

/**
 * The contract every artifact renderer implements. It lives apart from the registry so
 * that a renderer can name its own type without importing the list that imports it.
 */
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
  Component: ComponentType<ArtifactRenderProps>;
}
