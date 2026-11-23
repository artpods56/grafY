import { describe, expect, it } from "vitest";

import {
  advanceDraftSession,
  canvasPlacementTarget,
  mayPlaceOnInitiatingCanvas,
  type CanvasPlacementTarget,
} from "./initiatingGraphPlacement";

const draft: CanvasPlacementTarget = { kind: "draft", sessionId: "1" };
const laterDraft: CanvasPlacementTarget = { kind: "draft", sessionId: "2" };
const projectA: CanvasPlacementTarget = {
  kind: "saved",
  projectId: "project-a",
  graphId: "main",
};
const projectB: CanvasPlacementTarget = {
  kind: "saved",
  projectId: "project-b",
  graphId: "main",
};
const projectAOtherGraph: CanvasPlacementTarget = {
  kind: "saved",
  projectId: "project-a",
  graphId: "other",
};

describe("mayPlaceOnInitiatingCanvas", () => {
  it("places on the unsaved draft when authoring is on and the draft is unchanged", () => {
    expect(
      canvasPlacementTarget({
        projectId: null,
        graphId: null,
        draftSessionId: "1",
      }),
    ).toEqual(draft);
    expect(
      mayPlaceOnInitiatingCanvas({
        authoringEnabled: true,
        active: draft,
        initiating: draft,
      }),
    ).toBe(true);
  });

  it("refuses while authoring is paused", () => {
    expect(
      mayPlaceOnInitiatingCanvas({
        authoringEnabled: false,
        active: draft,
        initiating: draft,
      }),
    ).toBe(false);
    expect(
      mayPlaceOnInitiatingCanvas({
        authoringEnabled: false,
        active: projectA,
        initiating: projectA,
      }),
    ).toBe(false);
  });

  it("refuses a late card from one Project's main graph onto another's", () => {
    expect(
      mayPlaceOnInitiatingCanvas({
        authoringEnabled: true,
        active: projectB,
        initiating: projectA,
      }),
    ).toBe(false);
  });

  it("refuses when the draft is left for a saved Project, or the reverse", () => {
    expect(
      mayPlaceOnInitiatingCanvas({
        authoringEnabled: true,
        active: projectA,
        initiating: draft,
      }),
    ).toBe(false);
    expect(
      mayPlaceOnInitiatingCanvas({
        authoringEnabled: true,
        active: draft,
        initiating: projectA,
      }),
    ).toBe(false);
  });

  it("places on the same saved Project and graph", () => {
    expect(
      mayPlaceOnInitiatingCanvas({
        authoringEnabled: true,
        active: projectA,
        initiating: projectA,
      }),
    ).toBe(true);
  });

  it("refuses after the open graph changes inside one Project", () => {
    expect(
      mayPlaceOnInitiatingCanvas({
        authoringEnabled: true,
        active: projectAOtherGraph,
        initiating: projectA,
      }),
    ).toBe(false);
  });

  it("refuses a card started on an earlier visit to the draft", () => {
    expect(advanceDraftSession("project-a", null, 1)).toBe(2);
    expect(advanceDraftSession(null, null, 1)).toBe(1);
    expect(
      mayPlaceOnInitiatingCanvas({
        authoringEnabled: true,
        active: laterDraft,
        initiating: draft,
      }),
    ).toBe(false);
  });

  it("does not treat a saved Project with no open graph as the draft", () => {
    expect(
      canvasPlacementTarget({
        projectId: "project-a",
        graphId: null,
        draftSessionId: "1",
      }),
    ).toBeNull();
    expect(
      mayPlaceOnInitiatingCanvas({
        authoringEnabled: true,
        active: null,
        initiating: projectA,
      }),
    ).toBe(false);
  });
});
