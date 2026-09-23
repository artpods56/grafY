import { describe, expect, it } from "vitest";
import type { SavedGraphOrigin } from "@/lib/api";
import {
  ARTIFACT_VIEWER_NODE_TYPE,
  ARTIFACT_VIEWER_EDGE_TYPE,
  presentationFromArtifactViewers,
  artifactViewersFromPresentation,
  type ArtifactViewerCanvasState,
  type ArtifactViewerNode,
} from "../canvas/artifact-viewer";
import { cardArtifactRefs } from "../canvas/artifact-card";
import {
  collectArtifactCards,
  ungroupArtifactCard,
  tidyArtifactCards,
  artifactGroupingDisabledReason,
} from "./artifact-grouping";

function card(id: string, x: number, selected = true): ArtifactViewerNode {
  return {
    id,
    type: ARTIFACT_VIEWER_NODE_TYPE,
    selected,
    position: { x, y: 100 },
    data: {
      mode: null,
      layout: { width: 250 },
      artifactRef: {
        artifact_id: id,
        artifact_type: "file.png",
        schema_version: 1,
      },
    },
  };
}

function canvas(): ArtifactViewerCanvasState {
  return {
    graphId: null,
    nodes: [card("b", 400), card("a", 100), card("other", 900, false)],
    edges: [],
    bindings: [],
    annotations: [],
  };
}

describe("artifact grouping", () => {
  it("replaces selected cards, persists the sequence, and ungroups in its current order", () => {
    const state = canvas();
    const grouped = collectArtifactCards({ state, origins: [] });
    expect(grouped.nodes).toHaveLength(2);
    expect(
      grouped.nodes.some((node) => node.id === "a" || node.id === "b"),
    ).toBe(false);
    const stack = grouped.nodes.find((node) => node.selected);
    if (!stack) throw new Error("Selected stack missing");
    expect(
      cardArtifactRefs(stack.data.artifactRef).map((ref) => ref.artifact_id),
    ).toEqual(["a", "b"]);
    expect(presentationFromArtifactViewers(grouped).viewers).toHaveLength(2);
    const value = stack.data.artifactRef;
    if (!value || !("item_refs" in value)) throw new Error("Sequence missing");
    stack.data.artifactRef = {
      ...value,
      item_refs: [...value.item_refs].reverse(),
    };
    const reopened = artifactViewersFromPresentation(
      "graph-1",
      presentationFromArtifactViewers(grouped),
    );
    const ungrouped = ungroupArtifactCard({
      state: reopened,
      origins: [],
      nodeId: stack.id,
    });
    expect(ungrouped.nodes).toHaveLength(3);
    const restored = ungrouped.nodes.filter((node) => node.selected);
    expect(
      restored.map(
        (node) => cardArtifactRefs(node.data.artifactRef)[0].artifact_id,
      ),
    ).toEqual(["b", "a"]);
    expect(restored[0].position.x).toBeLessThan(restored[1].position.x);
    expect(ungrouped.nodes.find((node) => node.id === "other")).toMatchObject({
      data: reopened.nodes.find((node) => node.id === "other")?.data,
      position: state.nodes[2].position,
    });
    expect(state.nodes).toHaveLength(3);
  });

  it("refuses mixed contracts and leaves selection intact", () => {
    const state = canvas();
    state.nodes[0].data.artifactRef = {
      artifact_id: "b",
      artifact_type: "file.jpeg",
      schema_version: 1,
    };
    expect(collectArtifactCards({ state, origins: [] })).toBe(state);
  });

  it("does not collect or ungroup cards carrying an input origin", () => {
    const state = canvas();
    const value = state.nodes[0].data.artifactRef;
    if (!value) throw new Error("Artifact missing");
    const origin: SavedGraphOrigin = {
      id: "origin",
      conversion_path: [],
      to_node: "sink",
      to_port: "files",
      value,
    };
    expect(collectArtifactCards({ state, origins: [origin] })).toBe(state);
    const grouped = collectArtifactCards({ state, origins: [] });
    const stack = grouped.nodes.find((node) => node.selected);
    if (!stack) throw new Error("Stack missing");
    expect(
      ungroupArtifactCard({
        state: grouped,
        origins: [origin],
        nodeId: stack.id,
      }),
    ).toBe(grouped);
    expect(
      artifactGroupingDisabledReason({
        cards: [stack],
        state: grouped,
        origins: [origin],
      }),
    ).toContain("Disconnect");
  });

  it("refuses replacement of a viewer following a producer", () => {
    const state = canvas();
    state.edges = [
      {
        id: "feed",
        type: ARTIFACT_VIEWER_EDGE_TYPE,
        source: "producer",
        target: "a",
        data: { sourcePortName: "file" },
      },
    ];
    expect(collectArtifactCards({ state, origins: [] })).toBe(state);
  });

  it("tidies only selected cards and keeps values and connections unchanged", () => {
    const state = canvas();
    state.nodes[0].position = { x: 105, y: 105 };
    const next = tidyArtifactCards(state);
    expect(next.nodes[0].position).not.toEqual(state.nodes[0].position);
    expect(next.nodes.map((node) => node.data)).toEqual(
      state.nodes.map((node) => node.data),
    );
    expect(next.nodes[2]).toBe(state.nodes[2]);
    expect(next.edges).toBe(state.edges);
  });
});
