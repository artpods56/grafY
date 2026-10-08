import type { AnnotationColor, AnnotationLayout } from "./annotations";
import type {
  ArtifactViewerCanvasState,
  ArtifactViewerEdgeUpdate,
} from "./artifact-viewer";
import type { WorkflowEdgeRouteOffset } from "./types";

/**
 * The presentation-only edits a person makes to artifact cards and sticky notes on the
 * canvas. Each one takes the current presentation and returns the next one: no fetching,
 * no room traffic, no React. Workbench.tsx owns when they run and where they are sent.
 */

export function withViewerLayout(
  state: ArtifactViewerCanvasState,
  nodeId: string,
  layout: ArtifactViewerCanvasState["nodes"][number]["data"]["layout"],
): ArtifactViewerCanvasState {
  return {
    ...state,
    nodes: state.nodes.map((node) =>
      node.id === nodeId ? { ...node, data: { ...node.data, layout } } : node,
    ),
  };
}

export function withViewerMode(
  state: ArtifactViewerCanvasState,
  nodeId: string,
  mode: string,
): ArtifactViewerCanvasState {
  return {
    ...state,
    nodes: state.nodes.map((node) =>
      node.id === nodeId ? { ...node, data: { ...node.data, mode } } : node,
    ),
  };
}

export function withViewerEdge(
  state: ArtifactViewerCanvasState,
  edgeId: string,
  update: ArtifactViewerEdgeUpdate,
): ArtifactViewerCanvasState {
  return {
    ...state,
    edges: state.edges.map((edge) => {
      if (edge.id !== edgeId) return edge;
      const nextProjection =
        update.projection === undefined
          ? edge.data?.projection
          : (update.projection ?? undefined);
      return {
        ...edge,
        data: {
          ...edge.data,
          sourcePortName: edge.data?.sourcePortName ?? "",
          projection: nextProjection,
        },
      };
    }),
  };
}

export function withViewerEdgeRoute(
  state: ArtifactViewerCanvasState,
  edgeId: string,
  routeOffset: WorkflowEdgeRouteOffset,
): ArtifactViewerCanvasState {
  return {
    ...state,
    edges: state.edges.map((edge) =>
      edge.id === edgeId
        ? {
            ...edge,
            data: {
              ...edge.data,
              sourcePortName: edge.data?.sourcePortName ?? "",
              routeOffset,
            },
          }
        : edge,
    ),
  };
}

export function withViewerBinding(
  state: ArtifactViewerCanvasState,
  bindingId: string,
  binding: ArtifactViewerCanvasState["bindings"][number],
): ArtifactViewerCanvasState {
  return {
    ...state,
    bindings: state.bindings.map((candidate) =>
      candidate.id === bindingId ? binding : candidate,
    ),
  };
}

/**
 * Removing a card also removes the wiring that only it could show: its edges, the
 * bindings that named it, and nothing else. Origins are dropped by the caller, which
 * is the module that owns the authored document.
 */
export function withoutViewer(
  state: ArtifactViewerCanvasState,
  nodeId: string,
): ArtifactViewerCanvasState {
  return {
    ...state,
    nodes: state.nodes.filter((node) => node.id !== nodeId),
    edges: state.edges.filter(
      (edge) => edge.source !== nodeId && edge.target !== nodeId,
    ),
    bindings: state.bindings.filter(
      (binding) =>
        binding.sourceViewerId !== nodeId && binding.targetViewerId !== nodeId,
    ),
  };
}

/**
 * A deleted workflow node leaves its card links behind because nothing else prunes them.
 * Every `remove_nodes` goes through this, whichever gesture produced it, so a card never
 * keeps pointing at a node the document dropped. It mirrors what the room does to its own
 * head in `GraphPresentationDocument.prune_for_removed_nodes`.
 */
export function withoutViewerEdgesFromNodes(
  state: ArtifactViewerCanvasState,
  removedNodeIds: Iterable<string>,
): ArtifactViewerCanvasState {
  const removed = new Set(removedNodeIds);
  if (!removed.size) return state;
  const edges = state.edges.filter((edge) => !removed.has(edge.source));
  if (edges.length === state.edges.length) return state;
  return { ...state, edges };
}

export function withAnnotationLayout(
  state: ArtifactViewerCanvasState,
  nodeId: string,
  layout: AnnotationLayout,
): ArtifactViewerCanvasState {
  return {
    ...state,
    annotations: state.annotations.map((node) =>
      node.id === nodeId ? { ...node, data: { ...node.data, layout } } : node,
    ),
  };
}

export function withAnnotationText(
  state: ArtifactViewerCanvasState,
  nodeId: string,
  text: string,
): ArtifactViewerCanvasState {
  return {
    ...state,
    annotations: state.annotations.map((node) =>
      node.id === nodeId ? { ...node, data: { ...node.data, text } } : node,
    ),
  };
}

export function withAnnotationColor(
  state: ArtifactViewerCanvasState,
  nodeId: string,
  color: AnnotationColor,
): ArtifactViewerCanvasState {
  return {
    ...state,
    annotations: state.annotations.map((node) =>
      node.id === nodeId ? { ...node, data: { ...node.data, color } } : node,
    ),
  };
}

export function withoutAnnotation(
  state: ArtifactViewerCanvasState,
  nodeId: string,
): ArtifactViewerCanvasState {
  return {
    ...state,
    annotations: state.annotations.filter((node) => node.id !== nodeId),
  };
}
