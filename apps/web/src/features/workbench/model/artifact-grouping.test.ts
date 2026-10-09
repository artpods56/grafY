import { describe, expect, it } from "vitest";
import type { SavedGraphOrigin } from "@/lib/api";
import {
  ARTIFACT_VIEWER_NODE_TYPE,
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INPUT_HANDLE,
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
      ungrouped.nodes.map(
        (node) => cardArtifactRefs(node.data.artifactRef)[0].artifact_id,
      ),
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

  it("snapshots producer-fed cards into a sequence and drops the feeds", () => {
    const state = canvas();
    state.edges = [
      {
        id: "feed",
        type: ARTIFACT_VIEWER_EDGE_TYPE,
        source: "producer",
        target: "a",
        targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
        data: { sourcePortName: "file" },
      },
    ];
    const grouped = collectArtifactCards({ state, origins: [] });
    const stack = grouped.nodes.find((node) => node.selected);
    expect(
      cardArtifactRefs(stack?.data.artifactRef).map((ref) => ref.artifact_id),
    ).toEqual(["a", "b"]);
    expect(grouped.edges).toEqual([]);
  });

  it("puts one artifact card into a sequence", () => {
    const state = canvas();
    state.nodes = [card("only", 0)];
    const grouped = collectArtifactCards({ state, origins: [] });
    const stack = grouped.nodes.find((node) => node.selected);
    expect(stack?.data.artifactRef).toMatchObject({
      artifact_type: "file.png",
      item_refs: [{ artifact_id: "only" }],
    });
  });

  it("collects TypeSafe question outputs that only exist on producer cards", () => {
    const question = (id: string, x: number): ArtifactViewerNode => ({
      id,
      type: ARTIFACT_VIEWER_NODE_TYPE,
      selected: true,
      position: { x, y: 0 },
      data: { mode: "artifact", layout: null, artifactRef: null },
    });
    const state: ArtifactViewerCanvasState = {
      nodes: [question("q1", 0), question("q2", 240)],
      edges: ["q1", "q2"].map((id) => ({
        id: `feed-${id}`,
        type: ARTIFACT_VIEWER_EDGE_TYPE,
        source: `question-${id}`,
        target: id,
        targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
        data: { sourcePortName: "question" },
      })),
      bindings: [],
      annotations: [],
    };
    const grouped = collectArtifactCards({
      state,
      origins: [],
      values: {
        q1: {
          artifact_id: "question-a",
          artifact_type: "typesafe.question",
          schema_version: 1,
        },
        q2: {
          artifact_id: "question-b",
          artifact_type: "typesafe.question",
          schema_version: 1,
        },
      },
    });
    const stack = grouped.nodes.find((node) => node.selected);
    expect(stack?.data.artifactRef).toMatchObject({
      artifact_type: "typesafe.question",
      item_refs: [{ artifact_id: "question-a" }, { artifact_id: "question-b" }],
    });
    expect(grouped.edges).toEqual([]);
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
