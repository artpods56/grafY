import { describe, expect, it } from "vitest";

import { emptyGraphPresentation } from "../canvas/artifact-viewer";
import { NEW_GRAPH_NAME, savedGraphDirtiness } from "./saved-graph-dirtiness";

type Input = Parameters<typeof savedGraphDirtiness>[0];

function decisions(overrides: Partial<Input> = {}) {
  return savedGraphDirtiness({
    document: {
      name: NEW_GRAPH_NAME,
      nodes: [],
      edges: [],
      origins: [],
      agents: [],
    },
    presentation: emptyGraphPresentation(),
    hasActiveGraph: false,
    hasUnsyncedRoomEdits: false,
    hasPendingRoomCommands: false,
    saving: false,
    openingGraphId: null,
    deletingGraphId: null,
    ...overrides,
  });
}

describe("savedGraphDirtiness", () => {
  const authored = {
    name: "Authored",
    nodes: [],
    edges: [],
    origins: [],
    agents: [],
  };

  it("treats a blank draft as clean", () => {
    expect(decisions()).toEqual({
      hasUnsavedDraft: false,
      isDirty: false,
      workAtRisk: false,
      persistenceOperationBusy: false,
    });
  });

  it("marks an authored draft at risk", () => {
    expect(decisions({ document: authored })).toMatchObject({
      hasUnsavedDraft: true,
      isDirty: true,
      workAtRisk: true,
    });
  });

  it("counts annotation-only drafts as authored", () => {
    const presentation = emptyGraphPresentation();
    const result = decisions({
      presentation: {
        ...presentation,
        annotations: [
          {
            id: "annotation-1",
            kind: "text",
            text: "Note",
            color: "amber",
            position: { x: 0, y: 0 },
            layout: { width: 240, height: 160 },
          },
        ],
      },
    });
    expect(result.isDirty).toBe(true);
  });

  it.each([
    { pending: false, unsynced: false, atRisk: false },
    { pending: true, unsynced: false, atRisk: true },
    { pending: false, unsynced: true, atRisk: true },
  ])(
    "uses room sync state for a Project ($pending, $unsynced)",
    ({ pending, unsynced, atRisk }) => {
      expect(
        decisions({
          document: authored,
          hasActiveGraph: true,
          hasUnsyncedRoomEdits: unsynced,
          hasPendingRoomCommands: pending,
        }),
      ).toMatchObject({ isDirty: atRisk, workAtRisk: atRisk });
    },
  );

  it.each([
    { saving: true },
    { openingGraphId: "open" },
    { deletingGraphId: "delete" },
  ])(
    "reports persistence operations independently of unsaved edits",
    (overrides) => {
      expect(decisions(overrides)).toMatchObject({
        workAtRisk: false,
        persistenceOperationBusy: true,
      });
    },
  );
});
