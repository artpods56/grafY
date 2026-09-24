"use client";

import type { InternalNode, Node } from "@xyflow/react";
import { useStore } from "@xyflow/react";

import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE,
} from "../artifact-viewer";
import { useOptionalCanvasGridSettings } from "../canvas-grid-settings";
import { GRID_CELL_SIZE_DEFAULT } from "../grid-layout";
import { WORKFLOW_EDGE_TYPE } from "../types";
import {
  dockedConnections,
  dockedHandleKey,
  type DockedGraphEdge,
  type DockedGraphNode,
} from "./docked-connection";

const DOCKABLE_EDGE_TYPES: ReadonlySet<string> = new Set([
  WORKFLOW_EDGE_TYPE,
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE,
]);

interface DockedStoreState {
  edges: readonly DockedGraphEdge[];
  nodeLookup: ReadonlyMap<string, InternalNode<Node>>;
}

interface DockedSets {
  cellSize: number;
  edgeIds: ReadonlySet<string>;
  handleKeys: ReadonlySet<string>;
}

const dockedCache = new WeakMap<object, DockedSets>();

function dockedSetsForState(
  state: DockedStoreState,
  cellSize: number,
): DockedSets {
  const cached = dockedCache.get(state);
  if (cached && cached.cellSize === cellSize) return cached;
  const computed = dockedConnections(
    state.edges,
    state.nodeLookup as ReadonlyMap<string, DockedGraphNode>,
    cellSize,
    DOCKABLE_EDGE_TYPES,
  );
  const next = {
    cellSize,
    edgeIds: computed.edgeIds,
    handleKeys: computed.handleKeys,
  };
  dockedCache.set(state, next);
  return next;
}

function useDockedCellSize(): number {
  return (
    useOptionalCanvasGridSettings()?.settings.cellSize ?? GRID_CELL_SIZE_DEFAULT
  );
}

export function useEdgeIsDocked(edgeId: string): boolean {
  const cellSize = useDockedCellSize();
  return useStore(
    (state) => dockedSetsForState(state, cellSize).edgeIds.has(edgeId),
    Object.is,
  );
}

export function useHandleIsDocked(
  nodeId: string,
  handleId: string | undefined,
): boolean {
  const cellSize = useDockedCellSize();
  return useStore(
    (state) =>
      Boolean(
        handleId &&
        dockedSetsForState(state, cellSize).handleKeys.has(
          dockedHandleKey(nodeId, handleId),
        ),
      ),
    Object.is,
  );
}
