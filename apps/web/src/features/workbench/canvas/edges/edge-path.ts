import { Position } from "@xyflow/react";

import type { WorkflowEdgeRouteOffset } from "../types";

interface Point {
  x: number;
  y: number;
}

export interface EdgeFanEndpoint {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
  targetHandle?: string | null;
}

export interface EdgeFanOffsets {
  source: number;
  target: number;
}

export type FanSortAxis = "x" | "y";

/** Perpendicular spacing between sibling edges that share a handle. */
const FAN_SPACING = 7;

function midpoint(left: Point, right: Point): Point {
  return {
    x: (left.x + right.x) / 2,
    y: (left.y + right.y) / 2,
  };
}

function controlOffset(distance: number): number {
  return distance >= 0 ? distance / 2 : 6.25 * Math.sqrt(-distance);
}

function bezierControlPoint(
  position: Position,
  start: Point,
  end: Point,
): Point {
  switch (position) {
    case Position.Left:
      return {
        x: start.x - controlOffset(start.x - end.x),
        y: start.y,
      };
    case Position.Right:
      return {
        x: start.x + controlOffset(end.x - start.x),
        y: start.y,
      };
    case Position.Top:
      return {
        x: start.x,
        y: start.y - controlOffset(start.y - end.y),
      };
    case Position.Bottom:
      return {
        x: start.x,
        y: start.y + controlOffset(end.y - start.y),
      };
  }
}

function fanSlotOffset(index: number, count: number, spacing: number): number {
  if (count <= 1 || index < 0) return 0;
  return (index - (count - 1) / 2) * spacing;
}

/** Axis perpendicular to a handle's exit — used to order sibling cables. */
export function fanSortAxis(position: Position): FanSortAxis {
  return position === Position.Left || position === Position.Right ? "y" : "x";
}

function compareFanOrder(
  leftPoint: Point | undefined,
  rightPoint: Point | undefined,
  axis: FanSortAxis,
  leftId: string,
  rightId: string,
): number {
  const cross = axis === "x" ? "y" : "x";
  const leftPrimary = leftPoint?.[axis] ?? 0;
  const rightPrimary = rightPoint?.[axis] ?? 0;
  if (leftPrimary !== rightPrimary) return leftPrimary - rightPrimary;
  const leftCross = leftPoint?.[cross] ?? 0;
  const rightCross = rightPoint?.[cross] ?? 0;
  if (leftCross !== rightCross) return leftCross - rightCross;
  return leftId.localeCompare(rightId);
}

function fanGroups(
  edges: readonly EdgeFanEndpoint[],
  endpoint: "source" | "target",
): EdgeFanEndpoint[][] {
  const groupsByNode = new Map<
    string,
    Map<string | null | undefined, EdgeFanEndpoint[]>
  >();
  for (const edge of edges) {
    const nodeId = edge[endpoint];
    const handleId =
      endpoint === "source" ? edge.sourceHandle : edge.targetHandle;
    const groupsByHandle = groupsByNode.get(nodeId) ?? new Map();
    const group = groupsByHandle.get(handleId) ?? [];
    group.push(edge);
    groupsByHandle.set(handleId, group);
    groupsByNode.set(nodeId, groupsByHandle);
  }
  return [...groupsByNode.values()].flatMap((groupsByHandle) => [
    ...groupsByHandle.values(),
  ]);
}

/** Compute every edge's fan slots together so callers can share the group work. */
export function edgeFanOffsetsById(
  edges: readonly EdgeFanEndpoint[],
  {
    sourceOrderPoints = new Map(),
    targetOrderPoints = new Map(),
    sourceAxis = "y",
    targetAxis = "y",
    spacing = FAN_SPACING,
  }: {
    sourceOrderPoints?: ReadonlyMap<string, Point>;
    targetOrderPoints?: ReadonlyMap<string, Point>;
    sourceAxis?: FanSortAxis;
    targetAxis?: FanSortAxis;
    spacing?: number;
  } = {},
): ReadonlyMap<string, EdgeFanOffsets> {
  const offsetsById = new Map<string, EdgeFanOffsets>();
  for (const edge of edges) {
    offsetsById.set(edge.id, { source: 0, target: 0 });
  }

  for (const group of fanGroups(edges, "source")) {
    const sorted = group
      .slice()
      .sort((left, right) =>
        compareFanOrder(
          sourceOrderPoints.get(left.id),
          sourceOrderPoints.get(right.id),
          sourceAxis,
          left.id,
          right.id,
        ),
      );
    for (const [index, edge] of sorted.entries()) {
      const offsets = offsetsById.get(edge.id);
      if (offsets) {
        offsets.source = fanSlotOffset(index, sorted.length, spacing);
      }
    }
  }

  for (const group of fanGroups(edges, "target")) {
    const sorted = group
      .slice()
      .sort((left, right) =>
        compareFanOrder(
          targetOrderPoints.get(left.id),
          targetOrderPoints.get(right.id),
          targetAxis,
          left.id,
          right.id,
        ),
      );
    for (const [index, edge] of sorted.entries()) {
      const offsets = offsetsById.get(edge.id);
      if (offsets) {
        offsets.target = fanSlotOffset(index, sorted.length, spacing);
      }
    }
  }

  return offsetsById;
}

/**
 * Perpendicular fan offsets for edges that share a source or target handle.
 *
 * `sourceOrderPoints` / `targetOrderPoints` map edge id → the far-end point
 * used to order that edge (typically the opposite handle). When those points
 * move, sibling cables reshuffle so the exit order tracks node layout.
 */
export function edgeFanOffsets(
  edges: readonly EdgeFanEndpoint[],
  edgeId: string,
  {
    sourceOrderPoints = new Map(),
    targetOrderPoints = new Map(),
    sourceAxis = "y",
    targetAxis = "y",
    spacing = FAN_SPACING,
  }: {
    sourceOrderPoints?: ReadonlyMap<string, Point>;
    targetOrderPoints?: ReadonlyMap<string, Point>;
    sourceAxis?: FanSortAxis;
    targetAxis?: FanSortAxis;
    spacing?: number;
  } = {},
): EdgeFanOffsets {
  return (
    edgeFanOffsetsById(edges, {
      sourceOrderPoints,
      targetOrderPoints,
      sourceAxis,
      targetAxis,
      spacing,
    }).get(edgeId) ?? { source: 0, target: 0 }
  );
}

/** Shift a handle point along the axis perpendicular to its exit direction. */
export function applyHandleFanOffset(
  point: Point,
  position: Position,
  offset: number,
): Point {
  if (offset === 0) return point;
  switch (position) {
    case Position.Left:
    case Position.Right:
      return { x: point.x, y: point.y + offset };
    case Position.Top:
    case Position.Bottom:
      return { x: point.x + offset, y: point.y };
  }
}

/** Bezier path with a draggable midpoint offset (shared by workflow + viewer edges). */
export function routedBezierPath({
  source,
  target,
  sourcePosition,
  targetPosition,
  routeOffset,
}: {
  source: Point;
  target: Point;
  sourcePosition: Position;
  targetPosition: Position;
  routeOffset: WorkflowEdgeRouteOffset;
}): { anchor: Point; path: string } {
  const sourceControl = bezierControlPoint(sourcePosition, source, target);
  const targetControl = bezierControlPoint(targetPosition, target, source);

  const sourceHalfControl = midpoint(source, sourceControl);
  const controlMidpoint = midpoint(sourceControl, targetControl);
  const targetHalfControl = midpoint(targetControl, target);
  const sourceAnchorControl = midpoint(sourceHalfControl, controlMidpoint);
  const targetAnchorControl = midpoint(controlMidpoint, targetHalfControl);
  const naturalAnchor = midpoint(sourceAnchorControl, targetAnchorControl);
  const anchor = {
    x: naturalAnchor.x + routeOffset.x,
    y: naturalAnchor.y + routeOffset.y,
  };
  const routedSourceAnchorControl = {
    x: sourceAnchorControl.x + routeOffset.x,
    y: sourceAnchorControl.y + routeOffset.y,
  };
  const routedTargetAnchorControl = {
    x: targetAnchorControl.x + routeOffset.x,
    y: targetAnchorControl.y + routeOffset.y,
  };

  return {
    anchor,
    path: [
      `M${source.x},${source.y}`,
      `C${sourceHalfControl.x},${sourceHalfControl.y}`,
      `${routedSourceAnchorControl.x},${routedSourceAnchorControl.y}`,
      `${anchor.x},${anchor.y}`,
      `C${routedTargetAnchorControl.x},${routedTargetAnchorControl.y}`,
      `${targetHalfControl.x},${targetHalfControl.y}`,
      `${target.x},${target.y}`,
    ].join(" "),
  };
}
