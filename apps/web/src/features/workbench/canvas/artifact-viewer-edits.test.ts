import { describe, expect, it } from "vitest";

import {
  ANNOTATION_NODE_TYPE,
  DEFAULT_ANNOTATION_COLOR,
  type AnnotationNode,
} from "./annotations";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_NODE_TYPE,
  type ArtifactViewerCanvasState,
  type ArtifactViewerEdge,
  type ArtifactViewerNode,
} from "./artifact-viewer";
import {
  withAnnotationColor,
  withAnnotationLayout,
  withAnnotationText,
  withViewerBinding,
  withViewerEdge,
  withViewerEdgeRoute,
  withViewerLayout,
  withViewerMode,
  withoutAnnotation,
  withoutViewer,
  withoutViewerEdgesFromNodes,
} from "./artifact-viewer-edits";
import type { ArtifactViewerBinding } from "./artifact-interactions";

function viewer(
  id: string,
  overrides: Partial<ArtifactViewerNode["data"]> = {},
): ArtifactViewerNode {
  return {
    id,
    type: ARTIFACT_VIEWER_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: { layout: null, mode: "table", ...overrides },
  };
}

function viewerEdge(
  id: string,
  source: string,
  target: string,
  overrides: Partial<ArtifactViewerEdge["data"]> = {},
): ArtifactViewerEdge {
  return {
    id,
    type: ARTIFACT_VIEWER_EDGE_TYPE,
    source,
    target,
    data: { sourcePortName: "result", ...overrides },
  };
}

function annotation(id: string): AnnotationNode {
  return {
    id,
    type: ANNOTATION_NODE_TYPE,
    position: { x: 0, y: 0 },
    data: {
      kind: "text",
      layout: { width: 200, height: 100 },
      text: "note",
      color: DEFAULT_ANNOTATION_COLOR,
    },
  };
}

function binding(id: string, sourceViewerId: string): ArtifactViewerBinding {
  return {
    id,
    sourceViewerId,
    targetViewerId: "viewer-b",
    mappings: [],
    effects: [],
    emptySelection: "show_all",
  };
}

function state(
  overrides: Partial<ArtifactViewerCanvasState> = {},
): ArtifactViewerCanvasState {
  return {
    graphId: "graph-1",
    nodes: [],
    edges: [],
    bindings: [],
    annotations: [],
    ...overrides,
  };
}

describe("artifact viewer presentation edits", () => {
  it("replaces only the addressed node and leaves the input state alone", () => {
    const current = state({ nodes: [viewer("a"), viewer("b")] });

    const next = withViewerLayout(current, "a", {
      width: 320,
      bodyHeight: 240,
    });

    expect(next.nodes[0]?.data?.layout).toEqual({
      width: 320,
      bodyHeight: 240,
    });
    expect(next.nodes[1]).toBe(current.nodes[1]);
    expect(current.nodes[0]?.data?.layout).toBeNull();
  });

  it("keeps the graph identity it was handed", () => {
    const next = withViewerMode(state({ graphId: "graph-7" }), "a", "json");

    expect(next.graphId).toBe("graph-7");
    expect(next.nodes).toEqual([]);
  });

  it("sets the display mode on the addressed card", () => {
    const next = withViewerMode(
      state({ nodes: [viewer("a", { mode: "table" }), viewer("b")] }),
      "a",
      "image",
    );

    expect(next.nodes.map((node) => node.data.mode)).toEqual([
      "image",
      "table",
    ]);
  });

  it("treats an omitted projection as keep and a null projection as clear", () => {
    const withProjection = state({
      edges: [viewerEdge("e1", "a", "b", { projection: { path: ["rows"] } })],
    });

    const kept = withViewerEdge(withProjection, "e1", {});
    const cleared = withViewerEdge(withProjection, "e1", { projection: null });

    expect(kept.edges[0]?.data?.projection).toEqual({ path: ["rows"] });
    expect(cleared.edges[0]?.data?.projection).toBeUndefined();
  });

  it("defaults a missing source port name instead of leaving it undefined", () => {
    const current = state({
      edges: [
        {
          id: "e1",
          type: ARTIFACT_VIEWER_EDGE_TYPE,
          source: "a",
          target: "b",
          data: {} as ArtifactViewerEdge["data"],
        },
      ],
    });

    const next = withViewerEdge(current, "e1", {});

    expect(next.edges[0]?.data?.sourcePortName).toBe("");
  });

  it("stores a route offset on the addressed edge only", () => {
    const current = state({
      edges: [viewerEdge("e1", "a", "b"), viewerEdge("e2", "a", "c")],
    });

    const next = withViewerEdgeRoute(current, "e2", { x: 12, y: -8 });

    expect(next.edges[0]?.data?.routeOffset).toBeUndefined();
    expect(next.edges[1]?.data?.routeOffset).toEqual({ x: 12, y: -8 });
  });

  it("swaps a binding by identity", () => {
    const current = state({
      bindings: [binding("b1", "viewer-a"), binding("b2", "viewer-c")],
    });

    const next = withViewerBinding(current, "b1", {
      ...binding("b1", "viewer-z"),
      emptySelection: "show_all",
    });

    expect(next.bindings.map((item) => item.sourceViewerId)).toEqual([
      "viewer-z",
      "viewer-c",
    ]);
  });

  it("removes a card with the edges and bindings that named it", () => {
    const current = state({
      nodes: [viewer("a"), viewer("b")],
      edges: [
        viewerEdge("into-a", "x", "a"),
        viewerEdge("out-of-a", "a", "b"),
        viewerEdge("b-to-itself", "b", "b"),
      ],
      bindings: [binding("from-a", "a"), binding("from-b", "b")],
    });

    const next = withoutViewer(current, "a");

    expect(next.nodes.map((node) => node.id)).toEqual(["b"]);
    expect(next.edges.map((edge) => edge.id)).toEqual(["b-to-itself"]);
    expect(next.bindings.map((item) => item.id)).toEqual(["from-b"]);
  });

  it("drops viewer edges leaving removed workflow nodes but keeps incoming ones", () => {
    const current = state({
      edges: [
        viewerEdge("from-node", "node-1", "a"),
        viewerEdge("from-other", "node-2", "b"),
        viewerEdge("to-node", "b", "node-1"),
      ],
    });

    const next = withoutViewerEdgesFromNodes(current, ["node-1", "node-2"]);

    expect(next.edges.map((edge) => edge.id)).toEqual(["to-node"]);
    expect(next.nodes.map((node) => node.id)).toEqual(
      current.nodes.map((node) => node.id),
    );
  });

  it("keeps the viewer state identical when no removed node sourced a card link", () => {
    const current = state({ edges: [viewerEdge("from-node", "node-1", "a")] });

    expect(withoutViewerEdgesFromNodes(current, ["node-9"])).toBe(current);
    expect(withoutViewerEdgesFromNodes(current, [])).toBe(current);
  });

  it("edits annotation presentation without touching siblings", () => {
    const current = state({
      annotations: [annotation("n1"), annotation("n2")],
    });

    const moved = withAnnotationLayout(current, "n1", {
      width: 400,
      height: 120,
    });
    const written = withAnnotationText(moved, "n1", "renamed");
    const coloured = withAnnotationColor(written, "n1", "#b45309");
    const removed = withoutAnnotation(coloured, "n2");

    expect(removed.annotations.map((node) => node.id)).toEqual(["n1"]);
    expect(removed.annotations[0]?.data).toMatchObject({
      layout: { width: 400, height: 120 },
      text: "renamed",
      color: "#b45309",
    });
    expect(current.annotations[0]?.data?.text).toBe("note");
  });
});
