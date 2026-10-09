// @vitest-environment jsdom

import { act } from "react";
import * as React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

import { ANNOTATION_NODE_TYPE } from "../canvas/annotations";
import { ARTIFACT_VIEWER_NODE_TYPE } from "../canvas/artifact-viewer";
import type {
  ArtifactViewerCanvasState,
  ArtifactViewerNode,
} from "../canvas/artifact-viewer";
import type { AnnotationNode } from "../canvas/annotations";
import { useCanvasSelection } from "./workbench-canvas-selection";

function card(id: string, selected: boolean): ArtifactViewerNode {
  return {
    id,
    type: ARTIFACT_VIEWER_NODE_TYPE,
    position: { x: 0, y: 0 },
    selected,
    data: { layout: null, mode: null, artifactRef: null },
  };
}

function note(id: string, selected: boolean): AnnotationNode {
  return {
    id,
    type: ANNOTATION_NODE_TYPE,
    position: { x: 0, y: 0 },
    selected,
    data: {
      kind: "text",
      layout: { width: 10, height: 10 },
      text: "",
      color: "#000000",
    },
  };
}

type Selection = ReturnType<typeof useCanvasSelection>;

/** Mounts the hook over the four stores the canvas reads its selection from. */
async function mount(start: {
  nodeIds?: readonly string[];
  edgeIds?: readonly string[];
  viewers?: readonly ArtifactViewerNode[];
  annotations?: readonly AnnotationNode[];
}) {
  let latest: {
    edgeIds: string[];
    nodeIds: string[];
    selectOnly: Selection["selectOnly"];
    viewers: ArtifactViewerCanvasState;
  } | null = null;

  function HarnessComponent() {
    const [nodeIds, setSelectedNodeIdSet] = React.useState<ReadonlySet<string>>(
      new Set(start.nodeIds ?? []),
    );
    const [edgeIds, setSelectedEdgeIdSet] = React.useState<ReadonlySet<string>>(
      new Set(start.edgeIds ?? []),
    );
    const [viewers, setArtifactViewers] =
      React.useState<ArtifactViewerCanvasState>({
        nodes: [...(start.viewers ?? [])],
        edges: [],
        bindings: [],
        annotations: [...(start.annotations ?? [])],
      });
    const { selectOnly } = useCanvasSelection({
      setArtifactViewers,
      setSelectedEdgeIdSet,
      setSelectedNodeIdSet,
    });
    latest = {
      edgeIds: [...edgeIds],
      nodeIds: [...nodeIds],
      selectOnly,
      viewers,
    };
    return null;
  }

  const root = createRoot(document.createElement("div"));
  await act(async () => {
    root.render(React.createElement(HarnessComponent));
  });
  return {
    read() {
      if (!latest) throw new Error("harness did not render");
      return latest;
    },
    select: (selection: Parameters<Selection["selectOnly"]>[0]) =>
      act(async () => {
        latest?.selectOnly(selection);
      }),
    unmount: () => root.unmount(),
  };
}

describe("useCanvasSelection", () => {
  it("holds the node it is given and nothing else, in any layer", async () => {
    const view = await mount({
      nodeIds: ["node-1"],
      edgeIds: ["edge-1"],
      viewers: [card("card-1", true)],
      annotations: [note("note-1", true)],
    });

    await view.select({ nodeIds: ["node-2"] });

    expect(view.read().nodeIds).toEqual(["node-2"]);
    expect(view.read().edgeIds).toEqual([]);
    expect(view.read().viewers.nodes.map((node) => node.selected)).toEqual([
      false,
    ]);
    expect(
      view.read().viewers.annotations.map((node) => node.selected),
    ).toEqual([false]);
    view.unmount();
  });

  it("holds the card it is given and leaves a card that never changed alone", async () => {
    const untouched = card("card-3", false);
    const view = await mount({
      nodeIds: ["node-1"],
      viewers: [card("card-1", true), card("card-2", false), untouched],
    });

    await view.select({ viewerIds: ["card-2"] });

    const read = view.read();
    expect(read.nodeIds).toEqual([]);
    expect(read.viewers.nodes.map((node) => node.selected)).toEqual([
      false,
      true,
      false,
    ]);
    // A card that was already holding nothing is handed back as the same object,
    // so a selection does not re-render every card on the canvas.
    expect(read.viewers.nodes[2]).toBe(untouched);
    view.unmount();
  });

  it("clears every layer when handed nothing", async () => {
    const view = await mount({
      nodeIds: ["node-1"],
      edgeIds: ["edge-1"],
      viewers: [card("card-1", true)],
    });

    await view.select({});

    const read = view.read();
    expect(read.nodeIds).toEqual([]);
    expect(read.edgeIds).toEqual([]);
    expect(read.viewers.nodes.map((node) => node.selected)).toEqual([false]);
    view.unmount();
  });
});
