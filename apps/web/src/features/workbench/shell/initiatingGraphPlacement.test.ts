import { describe, expect, it } from "vitest";

import { mayPlaceOnInitiatingGraph } from "./initiatingGraphPlacement";

const graph = "main";

describe("mayPlaceOnInitiatingGraph", () => {
  it("places when authoring is on and the graph is still the one that started", () => {
    expect(
      mayPlaceOnInitiatingGraph({
        authoringEnabled: true,
        activeGraphId: graph,
        initiatingGraphId: graph,
      }),
    ).toBe(true);
  });

  it("refuses while authoring is paused, even on the same graph", () => {
    expect(
      mayPlaceOnInitiatingGraph({
        authoringEnabled: false,
        activeGraphId: graph,
        initiatingGraphId: graph,
      }),
    ).toBe(false);
  });

  it("refuses after the active graph changes", () => {
    expect(
      mayPlaceOnInitiatingGraph({
        authoringEnabled: true,
        activeGraphId: "other",
        initiatingGraphId: graph,
      }),
    ).toBe(false);
  });

  it("refuses when the request never recorded a graph", () => {
    expect(
      mayPlaceOnInitiatingGraph({
        authoringEnabled: true,
        activeGraphId: graph,
        initiatingGraphId: null,
      }),
    ).toBe(false);
  });
});
