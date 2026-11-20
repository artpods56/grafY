"use client";

import * as React from "react";
import {
  useStore,
  useStoreApi,
  type InternalNode,
  type Position,
  type ReactFlowState,
} from "@xyflow/react";

import {
  pipePath,
  type CardRect,
  type PipeRequest,
  type Point,
  type RoutingScene,
  type SceneRouter,
} from "./pipe-routing";
import { pipeRouter, type PipeRouterId } from "./routing";

/**
 * Feeds the canvas to the chosen router and publishes the routes the pipe
 * layers draw.
 *
 * Two rules keep a drag calm:
 *   - while any card drags, the resting pipes stay frozen in {@link RouteBook}:
 *     {@link selectSettledPipes} reads "" and nothing is re-published, so no
 *     resting pipe jumps lanes or repaints mid-drag
 *   - {@link MovingPipeRouter} routes the whole graph again on every drag
 *     frame, woken by a small signature of the moving pipes alone, and
 *     publishes only those pipes. Pickup and drop therefore see the same
 *     layout as the frames around them, and nothing jumps.
 *
 * Both share one router instance, so a router that remembers its last layout
 * carries it from the drag into the drop.
 */

/** Edges of this type are pipes: routed here and drawn by the pipe layers. */
export const PIPE_EDGE_TYPE = "pipe";

export interface RoutedPath {
  path: string;
  /** The route's corner points in flow units, ports first and last. */
  points: readonly Point[];
  depth: number;
}

/**
 * The resting pipes' paths and layers, published by {@link PipeRouter}. A pipe
 * subscribes to its own entry only, so a re-route re-renders just the pipes
 * that moved.
 */
export class RouteBook {
  private paths = new Map<string, RoutedPath>();
  private listeners = new Map<string, Set<() => void>>();

  get(id: string): RoutedPath | undefined {
    return this.paths.get(id);
  }

  subscribe(id: string, listener: () => void): () => void {
    const listeners = this.listeners.get(id) ?? new Set();
    listeners.add(listener);
    this.listeners.set(id, listeners);
    return () => {
      listeners.delete(listener);
    };
  }

  publish(next: ReadonlyMap<string, RoutedPath>): void {
    const changed: string[] = [];
    const paths = new Map<string, RoutedPath>();
    for (const [id, routed] of next) {
      const current = this.paths.get(id);
      // Keep the old object when nothing changed: it is the snapshot a pipe
      // compares against.
      if (current?.path === routed.path && current.depth === routed.depth) {
        paths.set(id, current);
      } else {
        paths.set(id, routed);
        changed.push(id);
      }
    }
    for (const id of this.paths.keys()) {
      if (!next.has(id)) changed.push(id);
    }
    this.paths = paths;
    for (const id of changed) {
      for (const listener of this.listeners.get(id) ?? []) listener();
    }
  }
}

/** The centre of a handle's ring, and the side of the card it sits on. */
function handleCentre(
  node: InternalNode,
  type: "source" | "target",
  handleId: string | null | undefined,
): { point: Point; side: Position } | null {
  const handles = node.internals.handleBounds?.[type] ?? [];
  const handle = handleId
    ? handles.find((candidate) => candidate.id === handleId)
    : handles[0];
  if (!handle) return null;
  const origin = node.internals.positionAbsolute;
  return {
    point: {
      x: origin.x + handle.x + handle.width / 2,
      y: origin.y + handle.y + handle.height / 2,
    },
    side: handle.position,
  };
}

const EMPTY_PATHS: ReadonlyMap<string, RoutedPath> = new Map();

function anyNodeDragging(state: ReactFlowState): boolean {
  for (const node of state.nodeLookup.values()) {
    if (node.dragging) return true;
  }
  return false;
}

/** Every measured card's rectangle, in flow units. */
function collectCards(state: ReactFlowState): CardRect[] {
  const cards: CardRect[] = [];
  for (const node of state.nodeLookup.values()) {
    const { width, height } = node.measured;
    if (!width || !height) continue;
    const { x, y } = node.internals.positionAbsolute;
    cards.push({ id: node.id, x, y, width, height });
  }
  return cards;
}

function collectScene(state: ReactFlowState): {
  scene: RoutingScene;
  movingIds: Set<string>;
} {
  const pipes: PipeRequest[] = [];
  const movingIds = new Set<string>();
  for (const edge of state.edges) {
    if (edge.type !== PIPE_EDGE_TYPE) continue;
    const sourceNode = state.nodeLookup.get(edge.source);
    const targetNode = state.nodeLookup.get(edge.target);
    if (!sourceNode || !targetNode) continue;
    const source = handleCentre(sourceNode, "source", edge.sourceHandle);
    const target = handleCentre(targetNode, "target", edge.targetHandle);
    if (!source || !target) continue;
    pipes.push({
      id: edge.id,
      source: source.point,
      sourceSide: source.side,
      target: target.point,
      targetSide: target.side,
    });
    if (sourceNode.dragging || targetNode.dragging) {
      movingIds.add(edge.id);
    }
  }
  return { scene: { pipes, cards: collectCards(state) }, movingIds };
}

/**
 * The whole scene when no card is dragging; "" while a drag is in progress so
 * resting pipes stay frozen in their pre-drag lanes and depths instead of
 * jumping when a card is picked up.
 */
function selectSettledPipes(state: ReactFlowState): string {
  if (anyNodeDragging(state)) return "";
  return JSON.stringify(collectScene(state).scene);
}

/**
 * Compact signature of only the pipes attached to dragging card(s), so drag
 * frames wake {@link MovingPipeRouter} without serialising the resting graph.
 */
function selectMovingSignature(state: ReactFlowState): string {
  if (!anyNodeDragging(state)) return "";
  const parts: string[] = [];
  for (const edge of state.edges) {
    if (edge.type !== PIPE_EDGE_TYPE) continue;
    const sourceNode = state.nodeLookup.get(edge.source);
    const targetNode = state.nodeLookup.get(edge.target);
    if (!sourceNode || !targetNode) continue;
    if (!sourceNode.dragging && !targetNode.dragging) continue;
    const source = handleCentre(sourceNode, "source", edge.sourceHandle);
    const target = handleCentre(targetNode, "target", edge.targetHandle);
    if (!source || !target) continue;
    parts.push(
      `${edge.id}:${source.point.x},${source.point.y},${target.point.x},${target.point.y}`,
    );
  }
  return parts.join("|");
}

interface RouterProps {
  route: SceneRouter;
  /** Corner radius of the drawn path; 0 for sharp corners. */
  radius: number;
  lanes: boolean;
  depth: boolean;
}

/**
 * Routes the dragged card(s)' pipes in the full graph's layout while leaving
 * all resting pipes frozen in the resting book. Because it routes the same
 * full graph on pickup and on drop, lanes and depths never jump when grabbing
 * or releasing a card, and resting SVG layers never repaint.
 */
function MovingPipeRouter({
  book,
  route,
  radius,
  lanes,
  depth,
}: RouterProps & { book: RouteBook }) {
  const storeApi = useStoreApi();
  const movingSig = useStore(selectMovingSignature);
  React.useLayoutEffect(() => {
    if (!movingSig) {
      book.publish(EMPTY_PATHS);
      return;
    }
    const { scene, movingIds } = collectScene(storeApi.getState());
    if (movingIds.size === 0) {
      book.publish(EMPTY_PATHS);
      return;
    }
    const paths = new Map<string, RoutedPath>();
    for (const [id, routed] of route(scene, { lanes, depth })) {
      if (!movingIds.has(id)) continue;
      paths.set(id, {
        path: pipePath(routed.points, radius),
        points: routed.points,
        depth: routed.depth,
      });
    }
    book.publish(paths);
  }, [book, depth, lanes, movingSig, radius, route, storeApi]);
  return null;
}

/** Lays out all resting pipes together and publishes their paths. */
export function PipeRouter({
  book,
  movingBook,
  router,
  radius,
  lanes,
  depth,
}: Omit<RouterProps, "route"> & {
  book: RouteBook;
  movingBook: RouteBook;
  router: PipeRouterId;
}) {
  const route = React.useMemo(() => pipeRouter(router).create(), [router]);
  const settled = useStore(selectSettledPipes);
  React.useLayoutEffect(() => {
    if (!settled) return;
    const scene = JSON.parse(settled) as RoutingScene;
    const paths = new Map<string, RoutedPath>();
    for (const [id, routed] of route(scene, { lanes, depth })) {
      paths.set(id, {
        path: pipePath(routed.points, radius),
        points: routed.points,
        depth: routed.depth,
      });
    }
    book.publish(paths);
  }, [book, depth, lanes, radius, route, settled]);
  return (
    <MovingPipeRouter
      book={movingBook}
      route={route}
      radius={radius}
      lanes={lanes}
      depth={depth}
    />
  );
}
