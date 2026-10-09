// @vitest-environment jsdom

import { act } from "react";
import * as React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

import type { ArtifactCardValue } from "../canvas/artifact-card";
import {
  ANNOTATION_NODE_TYPE,
  DEFAULT_ANNOTATION_COLOR,
  DEFAULT_ANNOTATION_LAYOUT,
  type AnnotationNode,
} from "../canvas/annotations";
import {
  ARTIFACT_VIEWER_NODE_TYPE,
  type ArtifactViewerCanvasState,
  type ArtifactViewerNode,
} from "../canvas/artifact-viewer";
import type { GraphCommand } from "../model/graph-document";
import { DEFAULT_ARTIFACT_CARD_WIDTH } from "../canvas/artifact-card";
import {
  ARTIFACT_CARD_DROP_GUTTER,
  artifactCardDropPosition,
  artifactCardDropPositions,
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
  localAuthoringEnabled?: boolean;
  groupingDisabledReason?: string | null;
}) {
  const base = state(options.nodes ?? [], options.annotations ?? []);
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
      authoredDocumentRef: { current: { origins: [] } },
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
