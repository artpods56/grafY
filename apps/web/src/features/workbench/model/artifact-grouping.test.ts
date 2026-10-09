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
    nodes: [card("b", 400), card("a", 100), card("other", 900, false)],
    edges: [],
    bindings: [],
    annotations: [],
  };
}

describe("artifact grouping", () => {
  it("ungroups a table sequence into readable cards without overlapping rows", () => {
    const state = canvas();
    state.nodes = [0, 1, 2].map((index) => ({
      ...card(`table-${index}`, index * 100),
      data: {
        mode: null,
        layout: null,
        artifactRef: {
          artifact_id: `table-${index}`,
          artifact_type: "table.data",
          schema_version: 1,
        },
      },
    }));
    const grouped = collectArtifactCards({ state, origins: [] });
    const stack = grouped.nodes.find((node) => node.selected);
    if (!stack) throw new Error("Table sequence missing");
    const ungrouped = ungroupArtifactCard({
      state: grouped,
      origins: [],
      nodeId: stack.id,
    });
    expect(ungrouped.nodes.map((node) => node.data.layout?.width)).toEqual([
      600, 600, 600,
    ]);
    expect(
      ungrouped.nodes.map((node) => ({
        x: node.position.x - stack.position.x,
        y: node.position.y - stack.position.y,
      })),
    ).toEqual([
      { x: 0, y: 0 },
      { x: 664, y: 0 },
      { x: 0, y: 448 },
    ]);
    expect(
      ungrouped.nodes.map((node) => {
        const first = cardArtifactRefs(node.data.artifactRef)[0];
        if (!first) throw new Error("expected an artifact ref");
        return first.artifact_id;
      }),
    ).toEqual(["table-0", "table-1", "table-2"]);
  });
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
      restored.map((node) => {
        const first = cardArtifactRefs(node.data.artifactRef)[0];
        if (!first) throw new Error("expected an artifact ref");
        return first.artifact_id;
      }),
    ).toEqual(["b", "a"]);
    const [leftCard, rightCard] = restored;
    if (!leftCard || !rightCard) throw new Error("expected two restored cards");
    expect(leftCard.position.x).toBeLessThan(rightCard.position.x);
    const otherState = state.nodes[2];
    if (!otherState) throw new Error("expected the unselected card");
    expect(ungrouped.nodes.find((node) => node.id === "other")).toMatchObject({
      data: reopened.nodes.find((node) => node.id === "other")?.data,
      position: otherState.position,
    });
    expect(state.nodes).toHaveLength(3);
  });

  it("refuses mixed contracts and leaves selection intact", () => {
    const state = canvas();
    const mixed = state.nodes[0];
    if (!mixed) throw new Error("expected a first card");
    mixed.data.artifactRef = {
      artifact_id: "b",
      artifact_type: "file.jpeg",
      schema_version: 1,
    };
    expect(collectArtifactCards({ state, origins: [] })).toBe(state);
  });

  it("does not collect or ungroup cards carrying an input origin", () => {
    const state = canvas();
    const firstCard = state.nodes[0];
    if (!firstCard) throw new Error("expected a first card");
    const value = firstCard.data.artifactRef;
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
    const moved = state.nodes[0];
    if (!moved) throw new Error("expected a first card");
    moved.position = { x: 105, y: 105 };
    const next = tidyArtifactCards(state);
    const nextFirst = next.nodes[0];
    if (!nextFirst) throw new Error("expected a first tidied card");
    expect(nextFirst.position).not.toEqual(moved.position);
    expect(next.nodes.map((node) => node.data)).toEqual(
      state.nodes.map((node) => node.data),
    );
    expect(next.nodes[2]).toBe(state.nodes[2]);
    expect(next.edges).toBe(state.edges);
  });
});
