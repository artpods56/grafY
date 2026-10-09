import * as React from "react";

import type { ArtifactViewerCanvasState } from "../canvas/artifact-viewer";

/**
 * What is held on the canvas, in the ids of the things a person can select.
 *
 * The canvas draws three kinds of thing — nodes, artifact cards, annotations — out of
 * three stores, and a rubber-band takes any mix of them into one selection. So the
 * answer to "what is selected" has four writers: the node id set, the edge id set, and
 * the `selected` flag on a card and on an annotation.
 */
export type CanvasSelection = {
  readonly annotationIds?: readonly string[];
  readonly edgeIds?: readonly string[];
  readonly nodeIds?: readonly string[];
  readonly viewerIds?: readonly string[];
};

export type CanvasSelectionDeps = {
  setArtifactViewers: React.Dispatch<
    React.SetStateAction<ArtifactViewerCanvasState>
  >;
  setSelectedEdgeIdSet: React.Dispatch<
    React.SetStateAction<ReadonlySet<string>>
  >;
  setSelectedNodeIdSet: React.Dispatch<
    React.SetStateAction<ReadonlySet<string>>
  >;
};

const EMPTY_SELECTION: ReadonlySet<string> = new Set();

/** Nodes that hold nothing, keeping every other field — and every untouched node — as it was. */
function deselect<T extends { id: string; selected?: boolean }>(
  nodes: T[],
  held: ReadonlySet<string>,
): T[] {
  let changed = false;
  const next = nodes.map((node) => {
    const selected = held.has(node.id);
    if (node.selected === selected) return node;
    changed = true;
    return { ...node, selected };
  });
  return changed ? next : nodes;
}

/**
 * Cards and annotations that hold nothing.
 *
 * A commit that places a card or an annotation writes its own selection, and the
 * committed state is what the room hears, so the deselection travels with the thing
 * placed rather than as a second write behind it.
 */
export function withoutPresentationSelection(
  state: ArtifactViewerCanvasState,
): ArtifactViewerCanvasState {
  const nodes = deselect(state.nodes, EMPTY_SELECTION);
  const annotations = deselect(state.annotations, EMPTY_SELECTION);
  if (nodes === state.nodes && annotations === state.annotations) return state;
  return { ...state, annotations, nodes };
}

/**
 * The one place the canvas is told what a person holds.
 *
 * A gesture that only writes its own layer leaves the others holding what they held
 * before, and a person who then drags the new thing drags the old one with it.
 */
export function useCanvasSelection(deps: CanvasSelectionDeps) {
  const { setArtifactViewers, setSelectedEdgeIdSet, setSelectedNodeIdSet } =
    deps;

  /**
   * Let go of every node and edge.
   *
   * For a gesture that commits cards or annotations itself: the commit already leaves
   * nothing else in the presentation state held, and a refusal there must not move a
   * selection, so the caller clears this layer only when its commit landed.
   */
  const clearWorkflowSelection = React.useCallback(() => {
    setSelectedNodeIdSet(EMPTY_SELECTION);
    setSelectedEdgeIdSet(EMPTY_SELECTION);
  }, [setSelectedEdgeIdSet, setSelectedNodeIdSet]);

  /** Hold nothing but `selection`, in every layer the canvas draws from. */
  const selectOnly = React.useCallback(
    (selection: CanvasSelection) => {
      const viewerIds = new Set(selection.viewerIds ?? []);
      const annotationIds = new Set(selection.annotationIds ?? []);
      setSelectedNodeIdSet(
        selection.nodeIds ? new Set(selection.nodeIds) : EMPTY_SELECTION,
      );
      setSelectedEdgeIdSet(
        selection.edgeIds ? new Set(selection.edgeIds) : EMPTY_SELECTION,
      );
      setArtifactViewers((current) => {
        const nodes = deselect(current.nodes, viewerIds);
        const annotations = deselect(current.annotations, annotationIds);
        if (nodes === current.nodes && annotations === current.annotations) {
          return current;
        }
        return { ...current, annotations, nodes };
      });
    },
    [setArtifactViewers, setSelectedEdgeIdSet, setSelectedNodeIdSet],
  );

  return { clearWorkflowSelection, selectOnly };
}

/** What a gesture can do to what the canvas holds. */
export type CanvasSelectionCommands = ReturnType<typeof useCanvasSelection>;
