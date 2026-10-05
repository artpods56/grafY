/**
 * The unsaved-work policy of the Workbench canvas.
 *
 * The lifecycle hook owns React state and decides *when* a fingerprint is
 * recomputed; this module only answers what the current canvas and the last
 * accepted checkpoint mean together. Keeping the decisions here lets them be
 * exercised without rendering anything.
 */

import type { GraphPresentation } from "../canvas/artifact-viewer";
import type { AuthoredGraphDocument } from "../model/graph-document";

/** The name every canvas starts with, before a person renames or saves it. */
export const NEW_GRAPH_NAME = "Untitled workflow";

export interface SavedGraphDirtinessInput {
  /** The canvas as authored in this tab. */
  readonly document: AuthoredGraphDocument;
  /** Shared Artifact Viewer presentation folded into the canvas content. */
  readonly presentation: GraphPresentation;
  /** True when the canvas is backed by a graph the server already knows. */
  readonly hasActiveGraph: boolean;
  /** Fingerprint of the draft built from the current document and presentation. */
  readonly currentFingerprint: string;
  /** Null when no checkpoint backs the canvas, such as an uncheckpointed room head. */
  readonly savedFingerprint: string | null;
  /** Fingerprint of the executable topology of the current draft. */
  readonly currentExecutionFingerprint: string;
  /** Null when no checkpoint backs the canvas, as with `savedFingerprint`. */
  readonly savedExecutionFingerprint: string | null;
  /**
   * Edits the room refused while it was connecting or reconnecting, which
   * therefore exist only in this tab. Edits that reach the room journal are
   * durable the moment they happen, so an uncheckpointed revision is not a
   * reason to interrupt a reload.
   */
  readonly hasUnsyncedRoomEdits: boolean;
  readonly saving: boolean;
  readonly openingGraphId: string | null;
  readonly deletingGraphId: string | null;
}

export interface SavedGraphDirtiness {
  /** The canvas holds more than the empty draft a new graph starts from. */
  readonly hasUnsavedDraft: boolean;
  /** The canvas differs from the checkpoint the server last accepted. */
  readonly isDirty: boolean;
  /**
   * Work a reload would actually lose: a graph the server has never been told
   * about, or canvas edits the disconnected room refused to take. `isDirty`
   * answers a different question — whether the canvas matches the last
   * checkpoint — and a journal the room already holds is safe on the server.
   */
  readonly workAtRisk: boolean;
  /**
   * True when the saved revision's topology still matches the canvas, so its
   * materialized outputs can be reused. Ignores presentation.
   */
  readonly canMaterializeSavedGraph: boolean;
  /** A save, open, or delete is in flight. */
  readonly persistenceOperationBusy: boolean;
}

export function savedGraphDirtiness(
  input: SavedGraphDirtinessInput,
): SavedGraphDirtiness {
  const hasUnsavedDraft =
    input.document.nodes.length > 0 ||
    input.document.edges.length > 0 ||
    (input.presentation.viewers?.length ?? 0) > 0 ||
    (input.presentation.links?.length ?? 0) > 0 ||
    (input.presentation.bindings?.length ?? 0) > 0 ||
    input.document.name.trim() !== NEW_GRAPH_NAME;

  return {
    hasUnsavedDraft,
    isDirty: input.hasActiveGraph
      ? input.savedFingerprint !== input.currentFingerprint
      : hasUnsavedDraft,
    workAtRisk: input.hasActiveGraph
      ? input.hasUnsyncedRoomEdits
      : hasUnsavedDraft,
    canMaterializeSavedGraph: Boolean(
      input.hasActiveGraph &&
      input.savedExecutionFingerprint !== null &&
      input.savedExecutionFingerprint === input.currentExecutionFingerprint,
    ),
    persistenceOperationBusy: Boolean(
      input.saving || input.openingGraphId || input.deletingGraphId,
    ),
  };
}
