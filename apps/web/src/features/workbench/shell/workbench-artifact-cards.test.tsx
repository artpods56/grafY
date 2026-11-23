// @vitest-environment jsdom

import { act } from "react";
import * as React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

import {
  DEFAULT_ARTIFACT_CARD_WIDTH,
  type ArtifactCardValue,
} from "../artifacts/artifact-card";
import {
  ANNOTATION_NODE_TYPE,
  DEFAULT_ANNOTATION_COLOR,
  DEFAULT_ANNOTATION_LAYOUT,
  type AnnotationNode,
} from "../authoring/annotations";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_NODE_TYPE,
  type ArtifactViewerCanvasState,
  type ArtifactViewerNode,
} from "../artifacts/artifact-viewer";
import type { SavedGraphOrigin } from "@/lib/api";
import type { GraphCommand } from "../authoring/graph-document";
import { CELL_SIZE } from "../cell-canvas/cell-model";
import {
  ARTIFACT_CARD_DROP_GUTTER,
  artifactCardDropPosition,
  artifactCardDropPositions,
  artifactCardFootprint,
  useArtifactCardCommands,
} from "./workbench-artifact-cards";

function single(artifactId: string) {
  return {
    artifact_id: artifactId,
    artifact_type: "file.jpeg",
    schema_version: 1,
  };
}

function cardValue(artifactIds: readonly string[]): ArtifactCardValue {
  return {
    artifact_type: "file.jpeg",
    schema_version: 1,
    item_refs: artifactIds.map(single),
    ordered: true,
    index_key: "order_index",
    sequence_id: "22222222-2222-4222-8222-222222222222",
  };
}

function card(id: string, selected = false): ArtifactViewerNode {
  return {
    id,
    type: ARTIFACT_VIEWER_NODE_TYPE,
    position: { x: 10, y: 20 },
    selected,
    data: { layout: null, mode: null, artifactRef: cardValue([`art-${id}`]) },
  };
}

function annotation(id: string, selected = false): AnnotationNode {
  return {
    id,
    type: ANNOTATION_NODE_TYPE,
    position: { x: 0, y: 0 },
    selected,
    data: {
      kind: "text",
      layout: DEFAULT_ANNOTATION_LAYOUT.text,
      text: "",
      color: DEFAULT_ANNOTATION_COLOR,
    },
  };
}

function state(
  nodes: readonly ArtifactViewerNode[],
  annotations: readonly AnnotationNode[] = [],
): ArtifactViewerCanvasState {
  return {
    nodes: [...nodes],
    edges: [],
    bindings: [],
    annotations: [...annotations],
  };
}

async function mount(options: {
  nodes?: readonly ArtifactViewerNode[];
  annotations?: readonly AnnotationNode[];
  edges?: ArtifactViewerCanvasState["edges"];
  origins?: readonly SavedGraphOrigin[];
  localAuthoringEnabled?: boolean;
  groupingDisabledReason?: string | null;
}) {
  const base = {
    ...state(options.nodes ?? [], options.annotations ?? []),
    edges: [...(options.edges ?? [])],
  };
  const committed: ArtifactViewerCanvasState[] = [];
  const commands: GraphCommand[][] = [];
  /** Every time the card layer asked the node layer to let go. */
  const cleared: string[] = [];
  let api: ReturnType<typeof useArtifactCardCommands> | null = null;

  function HarnessComponent() {
    api = useArtifactCardCommands({
      applyAuthoringCommands: (batch) => {
        commands.push([...batch]);
      },
      artifactViewers: base,
      authoredDocumentRef: { current: { origins: options.origins ?? [] } },
      // The real commit refuses while the canvas cannot author, and says so.
      commitArtifactViewers: (updater) => {
        if (!(options.localAuthoringEnabled ?? true)) return false;
        committed.push(updater(base));
        return true;
      },
      collection: {
        spec: null,
        disabledReason: null,
        sources: [],
        nodes: [],
        edges: [],
        onCollected: () => {},
      },
      groupingDisabledReason: options.groupingDisabledReason ?? null,
      localAuthoringEnabled: options.localAuthoringEnabled ?? true,
      selection: {
        clearWorkflowSelection: () => {
          cleared.push("workflow");
        },
      },
    });
    return null;
  }

  const root = createRoot(document.createElement("div"));
  await act(async () => {
    root.render(React.createElement(HarnessComponent));
  });
  const read = () => {
    if (!api) throw new Error("harness did not render");
    return api;
  };
  return { cleared, commands, committed, read, unmount: () => root.unmount() };
}

describe("useArtifactCardCommands", () => {
  it("places a new card selected and deselects the cards already on the canvas", async () => {
    const view = await mount({ nodes: [card("card-1", true)] });

    await act(async () => {
      view.read().addArtifactCard(cardValue(["art-new"]), { x: 40, y: 60 });
    });

    const next = view.committed.at(-1);
    expect(next?.nodes).toHaveLength(2);
    expect(next?.nodes[0]?.selected).toBe(false);
    const placed = next?.nodes[1];
    expect(placed?.selected).toBe(true);
    expect(placed?.position).toEqual({ x: 40, y: 60 });
    expect(placed?.data.layout).toBeNull();
    expect(placed?.data.mode).toBeNull();
    expect(placed?.data.artifactRef).toEqual(cardValue(["art-new"]));
    // The card is the whole selection, so the node layer is told to let go too.
    expect(view.cleared).toEqual(["workflow"]);
    view.unmount();
  });

  it("takes the selection off an annotation the canvas held before the drop", async () => {
    const view = await mount({
      nodes: [],
      annotations: [annotation("note-1", true)],
    });

    await act(async () => {
      view.read().addArtifactCard(cardValue(["art-new"]), { x: 40, y: 60 });
    });

    expect(view.committed.at(-1)?.annotations[0]?.selected).toBe(false);
    view.unmount();
  });

  it("keeps what a person held when the canvas refuses the drop", async () => {
    const view = await mount({
      nodes: [card("card-1", true)],
      localAuthoringEnabled: false,
    });

    await act(async () => {
      view.read().addArtifactCard(cardValue(["art-new"]), { x: 40, y: 60 });
    });

    expect(view.committed).toEqual([]);
    expect(view.cleared).toEqual([]);
    view.unmount();
  });

  it("does not group cards while the canvas cannot author", async () => {
    const blocked = await mount({
      nodes: [card("card-1", true)],
      localAuthoringEnabled: false,
    });
    await act(async () => {
      blocked.read().collectSelectedArtifacts();
    });
    expect(blocked.committed).toEqual([]);

    const groupingBlocked = await mount({
      nodes: [card("card-1", true)],
      groupingDisabledReason: "Select at least two cards.",
    });
    await act(async () => {
      groupingBlocked.read().collectSelectedArtifacts();
    });
    expect(groupingBlocked.committed).toEqual([]);
    blocked.unmount();
    groupingBlocked.unmount();
  });

  it("groups when authoring is allowed and grouping has no reason to refuse", async () => {
    const view = await mount({
      nodes: [card("card-1", true), card("card-2", true)],
    });

    await act(async () => {
      view.read().collectSelectedArtifacts();
    });

    expect(view.committed).toHaveLength(1);
    view.unmount();
  });

  it("removes the card when its artifacts are taken away", async () => {
    const view = await mount({ nodes: [card("card-1")] });

    await act(async () => {
      view.read().updateArtifactCardRefs("card-1", null);
    });

    expect(view.committed.at(-1)?.nodes).toEqual([]);
    expect(view.commands).toEqual([]);
    view.unmount();
  });

  it("ignores a card that is no longer on the canvas", async () => {
    const view = await mount({ nodes: [card("card-1")] });

    await act(async () => {
      view.read().updateArtifactCardRefs("gone-card", cardValue(["art-x"]));
    });

    expect(view.committed).toEqual([]);
    expect(view.commands).toEqual([]);
    view.unmount();
  });
});

function placedCard(
  id: string,
  artifactIds: readonly string[],
  position = { x: 100, y: 200 },
): ArtifactViewerNode {
  return {
    id,
    type: ARTIFACT_VIEWER_NODE_TYPE,
    position,
    selected: false,
    data: {
      layout: null,
      mode: null,
      artifactRef:
        artifactIds.length === 1
          ? single(artifactIds[0] ?? "")
          : cardValue(artifactIds),
    },
  };
}

function origin(
  id: string,
  sourceCardIds: readonly string[],
  value: ArtifactCardValue,
): SavedGraphOrigin {
  return {
    id,
    to_node: "consumer",
    to_port: "images",
    to_plug: null,
    value,
    source_card_ids: [...sourceCardIds],
    collection_mode: "direct",
    conversion_path: [],
  };
}

function refIds(value: ArtifactCardValue | null | undefined): string[] {
  if (!value) return [];
  return "item_refs" in value
    ? value.item_refs.map((ref) => ref.artifact_id)
    : [value.artifact_id];
}

describe("sequence authoring", () => {
  it("lets two standalone cards of one type merge, either way round", async () => {
    const view = await mount({
      nodes: [placedCard("a", ["a1"]), placedCard("b", ["b1", "b2"])],
    });
    expect(view.read().canMergeArtifactCards("a", "b")).toBe(true);
    expect(view.read().canMergeArtifactCards("b", "a")).toBe(true);
    expect(view.read().canMergeArtifactCards("a", "a")).toBe(false);
    expect(view.read().canMergeArtifactCards("a", "gone")).toBe(false);
    view.unmount();
  });

  it("refuses a card following a producer, another type, or a read-only canvas", async () => {
    const follower: ArtifactViewerNode = {
      ...placedCard("follow", ["f1"]),
      data: { layout: null, mode: "artifact", artifactRef: single("f1") },
    };
    const png: ArtifactViewerNode = {
      ...placedCard("png", ["p1"]),
      data: {
        layout: null,
        mode: null,
        artifactRef: { ...single("p1"), artifact_type: "file.png" },
      },
    };
    const view = await mount({
      nodes: [placedCard("a", ["a1"]), follower, png],
      edges: [
        {
          id: "feed",
          type: ARTIFACT_VIEWER_EDGE_TYPE,
          source: "producer",
          target: "follow",
          targetHandle: "artifact-viewer-input",
          data: { sourcePortName: "result" },
        },
      ],
    });
    expect(view.read().canMergeArtifactCards("a", "follow")).toBe(false);
    expect(view.read().canMergeArtifactCards("follow", "a")).toBe(false);
    expect(view.read().canMergeArtifactCards("a", "png")).toBe(false);
    view.unmount();

    const readOnly = await mount({
      nodes: [placedCard("a", ["a1"]), placedCard("b", ["b1"])],
      localAuthoringEnabled: false,
    });
    expect(readOnly.read().canMergeArtifactCards("a", "b")).toBe(false);
    readOnly.unmount();
  });

  it("never merges away a card that is passed into an input", async () => {
    const view = await mount({
      nodes: [placedCard("a", ["a1"]), placedCard("b", ["b1"])],
      origins: [origin("wired", ["a"], single("a1"))],
    });
    expect(view.read().canMergeArtifactCards("a", "b")).toBe(false);
    await act(async () => {
      view.read().mergeArtifactCards("a", "b");
    });
    expect(view.committed).toEqual([]);
    expect(view.commands).toEqual([]);
    // The wired card may still take the other in.
    expect(view.read().canMergeArtifactCards("b", "a")).toBe(true);
    view.unmount();
  });

  it("merges onto the target after its own items and hands it the selection", async () => {
    const view = await mount({
      nodes: [
        { ...placedCard("a", ["a1"]), selected: true },
        placedCard("b", ["b1", "b2"]),
      ],
    });
    await act(async () => {
      view.read().mergeArtifactCards("a", "b", "target-first");
    });
    const next = view.committed.at(-1);
    expect(next?.nodes.map((node) => node.id)).toEqual(["b"]);
    const target = next?.nodes[0];
    expect(target?.selected).toBe(true);
    expect(refIds(target?.data.artifactRef)).toEqual(["b1", "b2", "a1"]);
    // The target keeps its sequence identity.
    expect(target?.data.artifactRef).toMatchObject({
      sequence_id: "22222222-2222-4222-8222-222222222222",
    });
    expect(view.cleared).toEqual(["workflow"]);
    view.unmount();
  });

  it("puts the source first when it sits to the left", async () => {
    const view = await mount({
      nodes: [placedCard("left", ["l1"]), placedCard("right", ["r1"])],
    });
    await act(async () => {
      view.read().mergeArtifactCards("left", "right", "source-first");
    });
    const target = view.committed.at(-1)?.nodes[0];
    expect(target?.id).toBe("right");
    expect(refIds(target?.data.artifactRef)).toEqual(["l1", "r1"]);
    expect(target?.data.artifactRef).toHaveProperty("item_refs");
    view.unmount();
  });

  it("rewrites what the target is passed into with the merged sequence", async () => {
    const view = await mount({
      nodes: [placedCard("a", ["a1"]), placedCard("b", ["b1"])],
      origins: [origin("wired", ["b"], single("b1"))],
    });
    await act(async () => {
      view.read().mergeArtifactCards("a", "b");
    });
    expect(view.commands).toHaveLength(1);
    const [command] = view.commands[0] ?? [];
    expect(command).toMatchObject({
      kind: "update_origin",
      origin_id: "wired",
      update: { source_card_ids: ["b", "b"] },
    });
    if (command?.kind !== "update_origin") throw new Error("not an update");
    expect(refIds(command.update.value)).toEqual(["b1", "a1"]);
    view.unmount();
  });

  it("moves one item within a sequence and rewrites the origin it feeds", async () => {
    const view = await mount({
      nodes: [placedCard("s", ["s1", "s2", "s3"])],
      origins: [
        origin("wired", ["s", "s", "s"], cardValue(["s1", "s2", "s3"])),
      ],
    });
    await act(async () => {
      view.read().reorderArtifactCardItem("s", 0, 2);
    });
    expect(refIds(view.committed.at(-1)?.nodes[0]?.data.artifactRef)).toEqual([
      "s2",
      "s3",
      "s1",
    ]);
    const [command] = view.commands[0] ?? [];
    if (command?.kind !== "update_origin") throw new Error("not an update");
    expect(refIds(command.update.value)).toEqual(["s2", "s3", "s1"]);
    view.unmount();
  });

  it("ignores a reorder that goes nowhere or out of range", async () => {
    const view = await mount({ nodes: [placedCard("s", ["s1", "s2"])] });
    await act(async () => {
      view.read().reorderArtifactCardItem("s", 1, 1);
      view.read().reorderArtifactCardItem("s", 0, 5);
    });
    expect(view.committed).toEqual([]);
    view.unmount();
  });

  it("pulls one item out onto its own card a cell to the right", async () => {
    const view = await mount({ nodes: [placedCard("s", ["s1", "s2", "s3"])] });
    await act(async () => {
      view.read().extractArtifactCardItem("s", 1);
    });
    const [kept, added] = view.committed;
    expect(refIds(kept?.nodes[0]?.data.artifactRef)).toEqual(["s1", "s3"]);
    const extracted = added?.nodes.at(-1);
    expect(extracted?.data.artifactRef).toEqual(single("s2"));
    // Ten cells wide at the default width, so it lands one empty cell past
    // the card's right edge.
    expect(extracted?.position).toEqual({
      x: 100 + 10 * CELL_SIZE + CELL_SIZE,
      y: 200,
    });
    expect(extracted?.selected).toBe(true);
    view.unmount();
  });

  it("leaves a single card behind when the second to last item is pulled out", async () => {
    const view = await mount({ nodes: [placedCard("s", ["s1", "s2"])] });
    await act(async () => {
      view.read().extractArtifactCardItem("s", 0);
    });
    expect(view.committed[0]?.nodes[0]?.data.artifactRef).toEqual(single("s2"));
    view.unmount();
  });

  it("lands a pulled-out item on the cell it was dropped on and inherits the sequence's layout", async () => {
    const resized = placedCard("s", ["s1", "s2", "s3"]);
    resized.data = {
      ...resized.data,
      layout: { width: 250, bodyHeight: 375 },
    };
    const view = await mount({ nodes: [resized] });
    await act(async () => {
      view.read().extractArtifactCardItem("s", 2, { col: 30, row: 12 });
    });
    const [kept, added] = view.committed;
    expect(refIds(kept?.nodes[0]?.data.artifactRef)).toEqual(["s1", "s2"]);
    const extracted = added?.nodes.at(-1);
    expect(extracted?.data.artifactRef).toEqual(single("s3"));
    expect(extracted?.data.layout).toEqual({ width: 250, bodyHeight: 375 });
    expect(extracted?.position).toEqual({
      x: 30 * CELL_SIZE,
      y: 12 * CELL_SIZE,
    });
    view.unmount();
  });

  it("merges a whole flush run onto its target in visual order at the leftmost card's position", async () => {
    const view = await mount({
      nodes: [
        { ...placedCard("a", ["a1"]), position: { x: 0, y: 50 } },
        { ...placedCard("b", ["b1", "b2"]), position: { x: 250, y: 50 } },
        { ...placedCard("c", ["c1"]), position: { x: 500, y: 50 } },
        { ...placedCard("d", ["b2", "d1"]), position: { x: 750, y: 50 } },
      ],
      origins: [origin("wired", ["b", "b"], cardValue(["b1", "b2"]))],
    });
    await act(async () => {
      view.read().mergeArtifactCardRun(["a", "b", "c", "d"], "b");
    });
    // One commit and one origin rewrite for the whole run.
    expect(view.committed).toHaveLength(1);
    const next = view.committed[0];
    expect(next?.nodes.map((node) => node.id)).toEqual(["b"]);
    const target = next?.nodes[0];
    expect(target?.selected).toBe(true);
    // Stacks always collapse onto the first (leftmost) card's position, even
    // when a wired card further right stays as the surviving node id.
    expect(target?.position).toEqual({ x: 0, y: 50 });
    // Each artifact once, in the cards' order left to right.
    expect(refIds(target?.data.artifactRef)).toEqual([
      "a1",
      "b1",
      "b2",
      "c1",
      "d1",
    ]);
    expect(target?.data.artifactRef).toMatchObject({
      sequence_id: "22222222-2222-4222-8222-222222222222",
    });
    expect(view.commands).toHaveLength(1);
    const [command] = view.commands[0] ?? [];
    if (command?.kind !== "update_origin") throw new Error("not an update");
    expect(refIds(command.update.value)).toEqual([
      "a1",
      "b1",
      "b2",
      "c1",
      "d1",
    ]);
    expect(view.cleared).toEqual(["workflow"]);
    view.unmount();
  });

  it("drops a run that would merge away a wired card", async () => {
    const view = await mount({
      nodes: [placedCard("a", ["a1"]), placedCard("b", ["b1"])],
      origins: [origin("wired", ["a"], single("a1"))],
    });
    await act(async () => {
      view.read().mergeArtifactCardRun(["a", "b"], "b");
      view.read().mergeArtifactCardRun(["a", "b"], "missing");
    });
    expect(view.committed).toEqual([]);
    expect(view.commands).toEqual([]);
    view.unmount();
  });

  it("inserts a dragged card into a sequence at the exact index and rewrites wired origins", async () => {
    const view = await mount({
      nodes: [
        placedCard("seq", ["s1", "s2", "s3"]),
        placedCard("loose", ["x1", "s2", "x2"]),
      ],
      origins: [
        origin("wired", ["seq", "seq", "seq"], cardValue(["s1", "s2", "s3"])),
      ],
    });
    await act(async () => {
      view.read().insertArtifactCardIntoSequence("loose", "seq", 1);
    });
    expect(view.committed).toHaveLength(1);
    const next = view.committed[0];
    expect(next?.nodes.map((node) => node.id)).toEqual(["seq"]);
    const target = next?.nodes[0];
    expect(target?.selected).toBe(true);
    // Inserts x1 and x2 at index 1 while deduping already-present s2.
    expect(refIds(target?.data.artifactRef)).toEqual([
      "s1",
      "x1",
      "x2",
      "s2",
      "s3",
    ]);
    expect(view.commands).toHaveLength(1);
    const [command] = view.commands[0] ?? [];
    if (command?.kind !== "update_origin") throw new Error("not an update");
    expect(refIds(command.update.value)).toEqual([
      "s1",
      "x1",
      "x2",
      "s2",
      "s3",
    ]);
    view.unmount();
  });

  it("removes one item from a sequence and rewrites the origin it feeds", async () => {
    const view = await mount({
      nodes: [placedCard("s", ["s1", "s2", "s3"])],
      origins: [
        origin("wired", ["s", "s", "s"], cardValue(["s1", "s2", "s3"])),
      ],
    });
    await act(async () => {
      view.read().removeArtifactCardItem("s", 1);
    });
    expect(view.committed).toHaveLength(1);
    const kept = view.committed[0]?.nodes[0]?.data.artifactRef;
    expect(refIds(kept)).toEqual(["s1", "s3"]);
    expect(kept).toHaveProperty("item_refs");
    const [command] = view.commands[0] ?? [];
    if (command?.kind !== "update_origin") throw new Error("not an update");
    expect(refIds(command.update.value)).toEqual(["s1", "s3"]);
    view.unmount();
  });

  it("leaves a single card when the second to last item is removed", async () => {
    const view = await mount({
      nodes: [placedCard("s", ["s1", "s2"])],
      origins: [origin("wired", ["s", "s"], cardValue(["s1", "s2"]))],
    });
    await act(async () => {
      view.read().removeArtifactCardItem("s", 0);
      view.read().removeArtifactCardItem("s", 9);
    });
    expect(view.committed).toHaveLength(1);
    expect(view.committed[0]?.nodes[0]?.data.artifactRef).toEqual(single("s2"));
    const [command] = view.commands[0] ?? [];
    expect(command).toEqual({
      kind: "update_origin",
      origin_id: "wired",
      update: {
        value: single("s2"),
        source_card_ids: ["s"],
      },
    });
    view.unmount();
  });

  it("removes the card when its last item is removed", async () => {
    const view = await mount({ nodes: [placedCard("s", ["s1"])] });
    await act(async () => {
      view.read().removeArtifactCardItem("s", 0);
    });
    expect(view.committed[0]?.nodes).toEqual([]);
    view.unmount();
  });
});

describe("artifactCardDropPosition", () => {
  it("centres a dropped card on the cursor", () => {
    expect(artifactCardDropPosition({ x: 300, y: 200 }, 1)).toEqual({
      x: 175,
      y: 176,
    });
  });

  it("lifts a card that carries a set so the stack reads below the cursor", () => {
    const singleCard = artifactCardDropPosition({ x: 300, y: 200 }, 1);
    const setCard = artifactCardDropPosition({ x: 300, y: 200 }, 2);
    expect(setCard.x).toBe(singleCard.x);
    expect(singleCard.y - setCard.y).toBe(52);
  });
});

describe("addArtifactCards", () => {
  it("lands a drop of several cards as one change to the canvas", async () => {
    const view = await mount({ nodes: [card("card-1", true)] });

    await act(async () => {
      view.read().addArtifactCards([
        { value: cardValue(["art-a"]), position: { x: 10, y: 20 } },
        { value: cardValue(["art-b", "art-c"]), position: { x: 284, y: 20 } },
      ]);
    });

    // One commit for the batch, so the presentation room syncs once to a canvas
    // that has all of them rather than once per card.
    expect(view.committed).toHaveLength(1);
    const next = view.committed[0]!;
    expect(next.nodes).toHaveLength(3);
    expect(next.nodes[0]?.selected).toBe(false);
    expect(next.nodes.slice(1).map((node) => node.selected)).toEqual([
      true,
      true,
    ]);
    expect(next.nodes[2]?.position).toEqual({ x: 284, y: 20 });
    expect(next.nodes[2]?.data.artifactRef).toEqual(
      cardValue(["art-b", "art-c"]),
    );
    view.unmount();
  });

  it("leaves the canvas alone when the drag carried no card", async () => {
    const view = await mount({ nodes: [card("card-1")] });

    await act(async () => {
      view.read().addArtifactCards([]);
    });

    expect(view.committed).toEqual([]);
    view.unmount();
  });
});

describe("artifactCardFootprint", () => {
  const box = (artifactRef: ArtifactCardValue) =>
    artifactCardFootprint({
      data: { layout: null, mode: null, artifactRef },
    });

  it("sizes an unsized table or map, including a sequence of them", () => {
    const table = {
      artifact_id: "grid",
      artifact_type: "table.data",
      schema_version: 1,
    };
    expect(box(table)).toEqual({ width: 600, height: 350 });
    expect(
      box({
        artifact_type: "table.data",
        schema_version: 1,
        ordered: true,
        index_key: "order_index",
        item_refs: [table, { ...table, artifact_id: "grid-b" }],
      }),
    ).toEqual({ width: 600, height: 350 });
    expect(
      box({
        artifact_id: "map",
        artifact_type: "geo.map_document",
        schema_version: 1,
      }),
    ).toEqual({ width: 450, height: 350 });
    expect(
      box({
        artifact_id: "photo",
        artifact_type: "file.png",
        schema_version: 1,
      }).width,
    ).toBe(DEFAULT_ARTIFACT_CARD_WIDTH);
  });

  it("keeps a saved layout ahead of the kind default", () => {
    expect(
      artifactCardFootprint({
        data: {
          layout: { width: 200, bodyHeight: 150 },
          mode: null,
          artifactRef: {
            artifact_id: "grid",
            artifact_type: "table.data",
            schema_version: 1,
          },
        },
      }),
    ).toEqual({ width: 200, height: 150 });
  });
});

describe("artifactCardDropPositions", () => {
  it("centres the row a drop lays out on the cursor", () => {
    const [first, second] = artifactCardDropPositions({ x: 500, y: 300 }, [
      { artifactCount: 1, width: 250 },
      { artifactCount: 1, width: 250 },
    ]);

    expect(first!.y).toBe(second!.y);
    expect(second!.x - first!.x).toBe(
      DEFAULT_ARTIFACT_CARD_WIDTH + ARTIFACT_CARD_DROP_GUTTER,
    );
    const middleOfRow =
      (first!.x + second!.x + DEFAULT_ARTIFACT_CARD_WIDTH) / 2;
    expect(middleOfRow).toBeCloseTo(500, 6);
  });

  it("lifts a card that carries a set exactly as a single drop does", () => {
    const [single] = artifactCardDropPositions({ x: 300, y: 200 }, [
      { artifactCount: 1, width: 250 },
    ]);
    const [set] = artifactCardDropPositions({ x: 300, y: 200 }, [
      { artifactCount: 3, width: 250 },
    ]);

    expect(single!.x).toBe(set!.x);
    expect(single!.y - set!.y).toBe(52);
  });

  it("centres a mixed table and image drop with a gap between their bodies", () => {
    expect(
      artifactCardDropPositions({ x: 500, y: 300 }, [
        { artifactCount: 1, width: 600 },
        { artifactCount: 1, width: 250 },
      ]),
    ).toEqual([
      { x: 63, y: 276 },
      { x: 687, y: 276 },
    ]);
  });
});
