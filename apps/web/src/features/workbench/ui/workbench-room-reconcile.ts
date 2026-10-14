import type { CollaborativeHead } from "@/lib/api";

import {
  presentationFromCollaborativeHead,
  type ArtifactViewerCanvasState,
  type GraphPresentation,
} from "../canvas/artifact-viewer";
import {
  authoredGraphDocument,
  createSavedGraphRequest,
  type AuthoredGraphDocument,
} from "../model/graph-document";
import { sameCanonicalJson } from "../room/graph-diff";
import type { RoomGraphCommand } from "../room/protocol";
import { projectPendingCommands } from "../room/room-command-bridge";

export interface RoomReconciliation {
  /** The authored document to adopt, or null when it already matches. */
  readonly document: AuthoredGraphDocument | null;
  /** The presentation to adopt, or null when it already matches. */
  readonly presentation: GraphPresentation | null;
}

/**
 * What the author should see after an accepted batch: the confirmed head with
 * this client's pending batches on top. Returns null parts when the current
 * state already shows exactly that, so an echo of the author's own edit
 * changes nothing.
 */
export function reconcileWithConfirmedHead(input: {
  readonly head: CollaborativeHead;
  readonly pendingCommands: readonly RoomGraphCommand[];
  readonly document: AuthoredGraphDocument;
  readonly presentation: GraphPresentation;
}): RoomReconciliation {
  const projected = projectPendingCommands(input.head, input.pendingCommands);
  const nextDocument = authoredGraphDocument(projected);
  const nextPresentation = presentationFromCollaborativeHead(projected);
  return {
    document: sameCanonicalJson(
      createSavedGraphRequest(nextDocument),
      createSavedGraphRequest(input.document),
    )
      ? null
      : nextDocument,
    presentation: sameCanonicalJson(nextPresentation, input.presentation)
      ? null
      : nextPresentation,
  };
}

/**
 * Adopt a presentation without dropping canvas state: an item that already
 * exists keeps its React Flow fields (selection, measurements) and takes the
 * new content; new items come in as built; removed items go.
 */
export function mergeArtifactViewerState(
  current: ArtifactViewerCanvasState,
  next: ArtifactViewerCanvasState,
): ArtifactViewerCanvasState {
  return {
    nodes: mergeById(current.nodes, next.nodes),
    edges: mergeById(current.edges, next.edges),
    annotations: mergeById(current.annotations, next.annotations),
    bindings: next.bindings,
  };
}

/** `next` in its own order, with each item that survived merged over `current`. */
function mergeById<T extends { readonly id: string }>(
  current: readonly T[],
  next: readonly T[],
): T[] {
  const currentById = new Map(current.map((item) => [item.id, item]));
  return next.map((item) => {
    const held = currentById.get(item.id);
    return held ? { ...held, ...item } : item;
  });
}
