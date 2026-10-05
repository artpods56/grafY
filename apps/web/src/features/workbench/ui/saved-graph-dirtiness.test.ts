import { describe, expect, it } from "vitest";

import type { GraphPresentation } from "../canvas/artifact-viewer";
import type { AuthoredGraphDocument } from "../model/graph-document";
import {
  NEW_GRAPH_NAME,
  savedGraphDirtiness,
  type SavedGraphDirtinessInput,
} from "./saved-graph-dirtiness";

/** Fingerprint pair of the checkpoint the server last accepted. */
const CHECKPOINT = "fp-checkpoint";
const CHECKPOINT_EXECUTION = "fp-execution-checkpoint";

const emptyPresentation: GraphPresentation = {
  viewers: [],
  links: [],
  bindings: [],
  annotations: [],
};

const savedCanvasNode = {
  id: "llm",
  kind: "builtin" as const,
  operator_id: "llm.openai.completion",
  operator_version: 1,
  position: { x: 0, y: 0 },
  input_plugs: [],
  artifact_type_bindings: [],
};

function documentWith(
  overrides: Partial<AuthoredGraphDocument> = {},
): AuthoredGraphDocument {
  return {
    name: NEW_GRAPH_NAME,
    nodes: [],
    edges: [],
    origins: [],
    ...overrides,
  };
}

function decisions(overrides: Partial<SavedGraphDirtinessInput> = {}) {
  return savedGraphDirtiness({
    document: documentWith(),
    presentation: emptyPresentation,
    hasActiveGraph: false,
    currentFingerprint: CHECKPOINT,
    savedFingerprint: null,
    currentExecutionFingerprint: CHECKPOINT_EXECUTION,
    savedExecutionFingerprint: null,
    hasUnsyncedRoomEdits: false,
    saving: false,
    openingGraphId: null,
    deletingGraphId: null,
    ...overrides,
  });
}

describe("savedGraphDirtiness", () => {
  it("treats an untouched new graph as nothing to lose", () => {
    const result = decisions();

    expect(result).toEqual({
      hasUnsavedDraft: false,
      isDirty: false,
      workAtRisk: false,
      canMaterializeSavedGraph: false,
      persistenceOperationBusy: false,
    });
  });

  it("treats a canvas the server has never been told about as work at risk", () => {
    const result = decisions({
      document: documentWith({ nodes: [savedCanvasNode] }),
    });

    expect(result.hasUnsavedDraft).toBe(true);
    expect(result.isDirty).toBe(true);
    expect(result.workAtRisk).toBe(true);
    // A brand new graph has no saved revision whose materialized outputs fit.
    expect(result.canMaterializeSavedGraph).toBe(false);
  });

  it("counts a rename away from the default name as unsaved work", () => {
    expect(
      decisions({ document: documentWith({ name: "Quarterly review" }) })
        .workAtRisk,
    ).toBe(true);
    // The comparison is against the trimmed name, so stray whitespace is not an edit.
    expect(
      decisions({
        document: documentWith({ name: `  ${NEW_GRAPH_NAME}  ` }),
      }).workAtRisk,
    ).toBe(false);
  });

  it("counts shared presentation content as unsaved work on an empty canvas", () => {
    expect(
      decisions({
        presentation: {
          ...emptyPresentation,
          viewers: [{ id: "viewer-1", position: { x: 10, y: 20 } }],
        },
      }).hasUnsavedDraft,
    ).toBe(true);
    expect(
      decisions({
        presentation: {
          ...emptyPresentation,
          links: [
            {
              id: "link-1",
              source_node_id: "llm",
              source_port_name: "text",
              target_viewer_id: "viewer-1",
            },
          ],
        },
      }).hasUnsavedDraft,
    ).toBe(true);
    expect(
      decisions({
        presentation: {
          ...emptyPresentation,
          bindings: [
            {
              id: "binding-1",
              source_viewer_id: "viewer-1",
              target_viewer_id: "viewer-2",
              effects: ["highlight"],
              empty_selection: "show_all",
              mappings: [],
            },
          ],
        },
      }).hasUnsavedDraft,
    ).toBe(true);
  });

  it("compares a saved graph against its checkpoint fingerprint", () => {
    const edited = decisions({
      hasActiveGraph: true,
      document: documentWith({
        name: "Renamed after the checkpoint",
        nodes: [savedCanvasNode],
      }),
      currentFingerprint: "fp-edited-document",
      savedFingerprint: CHECKPOINT,
      savedExecutionFingerprint: CHECKPOINT_EXECUTION,
    });

    expect(edited.isDirty).toBe(true);
    // The server still holds the last checkpoint, so a reload loses nothing.
    expect(edited.workAtRisk).toBe(false);

    const reconciled = decisions({
      hasActiveGraph: true,
      document: documentWith({
        name: "Renamed after the checkpoint",
        nodes: [savedCanvasNode],
      }),
      currentFingerprint: "fp-edited-document",
      savedFingerprint: "fp-edited-document",
      savedExecutionFingerprint: CHECKPOINT_EXECUTION,
    });

    expect(reconciled.isDirty).toBe(false);
    expect(reconciled.workAtRisk).toBe(false);
  });

  it("reports only execution drift as unmaterializable but not dirty", () => {
    const drifted = decisions({
      hasActiveGraph: true,
      currentFingerprint: CHECKPOINT,
      savedFingerprint: CHECKPOINT,
      currentExecutionFingerprint: "fp-execution-topology-changed",
      savedExecutionFingerprint: CHECKPOINT_EXECUTION,
    });

    expect(drifted.isDirty).toBe(false);
    expect(drifted.canMaterializeSavedGraph).toBe(false);

    const aligned = decisions({
      hasActiveGraph: true,
      currentFingerprint: CHECKPOINT,
      savedFingerprint: CHECKPOINT,
      currentExecutionFingerprint: CHECKPOINT_EXECUTION,
      savedExecutionFingerprint: CHECKPOINT_EXECUTION,
    });

    expect(aligned.isDirty).toBe(false);
    expect(aligned.canMaterializeSavedGraph).toBe(true);
  });

  it("keeps room edits ahead of the collaborative head out of the risk set", () => {
    // An uncheckpointed room head clears the saved fingerprints: the journal
    // holds the canvas, but no checkpoint matches it yet.
    const aheadOfCheckpoint = decisions({
      hasActiveGraph: true,
      document: documentWith({
        name: "Live room edit",
        nodes: [savedCanvasNode],
      }),
      currentFingerprint: "fp-live-room-edit",
      savedFingerprint: null,
      currentExecutionFingerprint: "fp-execution-live-room-edit",
      savedExecutionFingerprint: null,
      hasUnsyncedRoomEdits: false,
    });

    expect(aheadOfCheckpoint.isDirty).toBe(true);
    expect(aheadOfCheckpoint.canMaterializeSavedGraph).toBe(false);
    // The room journal already holds these edits, so a reload loses nothing.
    expect(aheadOfCheckpoint.workAtRisk).toBe(false);
  });

  it("treats edits the disconnected room refused as work at risk", () => {
    const result = decisions({
      hasActiveGraph: true,
      currentFingerprint: CHECKPOINT,
      savedFingerprint: CHECKPOINT,
      currentExecutionFingerprint: CHECKPOINT_EXECUTION,
      savedExecutionFingerprint: CHECKPOINT_EXECUTION,
      hasUnsyncedRoomEdits: true,
    });

    // The checkpoint matches the canvas, yet the refused edits live only here.
    expect(result.isDirty).toBe(false);
    expect(result.workAtRisk).toBe(true);
  });

  it("marks persistence busy while a save, open, or delete is in flight", () => {
    expect(decisions({ saving: true }).persistenceOperationBusy).toBe(true);
    expect(
      decisions({ openingGraphId: "graph-a" }).persistenceOperationBusy,
    ).toBe(true);
    expect(
      decisions({ deletingGraphId: "graph-a" }).persistenceOperationBusy,
    ).toBe(true);
    expect(decisions({ saving: true }).workAtRisk).toBe(false);
    expect(decisions().persistenceOperationBusy).toBe(false);
  });
});
