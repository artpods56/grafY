import { Position } from "@xyflow/react";

import { decodeHandleId } from "../handles";
import {
  EDGE_SELECTOR_PILL_HEIGHT,
  EDGE_SELECTOR_WIDTH_CELLS,
} from "../grid-layout";

interface Point {
  x: number;
  y: number;
}

/**
 * Adjacent lattice shells leave at most a gutter between facing handles.
 * One empty cell between cards is a full `cellSize` and must not dock.
 */
const DOCK_GAP_CELLS = 0.6;
const DOCK_ALIGN_CELLS = 0.45;
/** Handles may overlap in the gutter; a wrap-around path is not a join. */
const DOCK_OVERLAP_PX = 16;

export function dockedHandleKey(nodeId: string, handleId: string): string {
  return `${nodeId}::${handleId}`;
}

export function connectionIsDocked({
  source,
  target,
  sourcePosition,
  targetPosition,
  cellSize,
  sourceDegree,
  targetDegree,
}: {
  source: Point;
  target: Point;
  sourcePosition: Position;
  targetPosition: Position;
  cellSize: number;
  sourceDegree: number;
  targetDegree: number;
}): boolean {
  if (sourceDegree !== 1 || targetDegree !== 1) return false;
  if (sourcePosition !== Position.Right || targetPosition !== Position.Left) {
    return false;
  }
  const dx = target.x - source.x;
  const dy = Math.abs(target.y - source.y);
  if (dx < -DOCK_OVERLAP_PX) return false;
  if (dx > cellSize * DOCK_GAP_CELLS) return false;
  if (dy > cellSize * DOCK_ALIGN_CELLS) return false;
  return true;
}

export function dockedBridgeLayout(
  source: Point,
  target: Point,
  cellSize: number,
): { anchor: Point; width: number; height: number } {
  const gap = Math.abs(target.x - source.x);
  return {
    anchor: {
      x: (source.x + target.x) / 2,
      y: (source.y + target.y) / 2,
    },
    width: Math.max(cellSize * EDGE_SELECTOR_WIDTH_CELLS, gap + cellSize),
    height: EDGE_SELECTOR_PILL_HEIGHT,
  };
}

export interface DockedGraphEdge {
  id: string;
  type?: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

export interface DockedHandleBounds {
  id?: string | null;
  x: number;
  y: number;
  width: number;
  height: number;
  position?: Position;
}

export interface DockedGraphNode {
  internals: {
    positionAbsolute: Point;
    handleBounds?: {
      source?: DockedHandleBounds[] | null;
      target?: DockedHandleBounds[] | null;
    };
  };
}

function handleCenter(
  node: DockedGraphNode | undefined,
  handleId: string | null | undefined,
  type: "source" | "target",
): { point: Point; position: Position } | undefined {
  if (!node || !handleId) return undefined;
  const handle = node.internals.handleBounds?.[type]?.find(
    (candidate) => candidate.id === handleId,
  );
  if (!handle) return undefined;
  return {
    point: {
      x: node.internals.positionAbsolute.x + handle.x + handle.width / 2,
      y: node.internals.positionAbsolute.y + handle.y + handle.height / 2,
    },
    position:
      handle.position ?? (type === "source" ? Position.Right : Position.Left),
  };
}

function endpointKey(
  nodeId: string,
  handleId: string | null | undefined,
  end: "source" | "target",
): string {
  return `${end}:${nodeId}:${handleId ?? ""}`;
}

function isPlugHandle(handleId: string | null | undefined): boolean {
  return Boolean(decodeHandleId(handleId)?.plugId);
}

export function dockedConnections(
  edges: readonly DockedGraphEdge[],
  nodes: ReadonlyMap<string, DockedGraphNode>,
  cellSize: number,
  dockableTypes: ReadonlySet<string>,
): { edgeIds: ReadonlySet<string>; handleKeys: ReadonlySet<string> } {
  const dockable = edges.filter(
    (edge) =>
      Boolean(edge.type && dockableTypes.has(edge.type)) &&
      !isPlugHandle(edge.sourceHandle) &&
      !isPlugHandle(edge.targetHandle),
  );
  const degree = new Map<string, number>();
  for (const edge of dockable) {
    const sourceKey = endpointKey(edge.source, edge.sourceHandle, "source");
    const targetKey = endpointKey(edge.target, edge.targetHandle, "target");
    degree.set(sourceKey, (degree.get(sourceKey) ?? 0) + 1);
    degree.set(targetKey, (degree.get(targetKey) ?? 0) + 1);
  }

  const edgeIds = new Set<string>();
  const handleKeys = new Set<string>();
  for (const edge of dockable) {
    const sourceHandle = handleCenter(
      nodes.get(edge.source),
      edge.sourceHandle,
      "source",
    );
    const targetHandle = handleCenter(
      nodes.get(edge.target),
      edge.targetHandle,
      "target",
    );
    if (
      !sourceHandle ||
      !targetHandle ||
      !edge.sourceHandle ||
      !edge.targetHandle
    ) {
      continue;
    }
    if (
      !connectionIsDocked({
        source: sourceHandle.point,
        target: targetHandle.point,
        sourcePosition: sourceHandle.position,
        targetPosition: targetHandle.position,
        cellSize,
        sourceDegree:
          degree.get(endpointKey(edge.source, edge.sourceHandle, "source")) ??
          0,
        targetDegree:
          degree.get(endpointKey(edge.target, edge.targetHandle, "target")) ??
          0,
      })
    ) {
      continue;
    }
    edgeIds.add(edge.id);
    handleKeys.add(dockedHandleKey(edge.source, edge.sourceHandle));
    handleKeys.add(dockedHandleKey(edge.target, edge.targetHandle));
  }
  return { edgeIds, handleKeys };
}
