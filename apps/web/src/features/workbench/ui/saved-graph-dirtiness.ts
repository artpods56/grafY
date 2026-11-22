import type { GraphPresentation } from "../canvas/artifact-viewer";
import type { AuthoredGraphDocument } from "../model/graph-document";

export const NEW_GRAPH_NAME = "Untitled workflow";

interface SavedGraphDirtinessInput {
  readonly document: AuthoredGraphDocument;
  readonly presentation: GraphPresentation;
  readonly hasActiveGraph: boolean;
  readonly hasUnsyncedRoomEdits: boolean;
  readonly hasPendingRoomCommands: boolean;
  readonly saving: boolean;
  readonly openingGraphId: string | null;
  readonly deletingGraphId: string | null;
}

export function savedGraphDirtiness(input: SavedGraphDirtinessInput) {
  const hasUnsavedDraft =
    input.document.nodes.length > 0 ||
    input.document.edges.length > 0 ||
    input.document.origins.length > 0 ||
    (input.document.agents?.length ?? 0) > 0 ||
    input.presentation.viewers.length > 0 ||
    input.presentation.links.length > 0 ||
    input.presentation.bindings.length > 0 ||
    input.presentation.annotations.length > 0 ||
    input.document.name.trim() !== NEW_GRAPH_NAME;

  const isDirty = input.hasActiveGraph
    ? input.hasUnsyncedRoomEdits || input.hasPendingRoomCommands
    : hasUnsavedDraft;

  return {
    hasUnsavedDraft,
    isDirty,
    workAtRisk: isDirty,
    persistenceOperationBusy: Boolean(
      input.saving || input.openingGraphId || input.deletingGraphId,
    ),
  };
}
