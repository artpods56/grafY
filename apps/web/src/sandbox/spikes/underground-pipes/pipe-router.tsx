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
  type CardAvoidance,
  type CardRect,
  type PipeRequest,
  type Point,
  type RoutingScene,
  type SceneRouter,
} from "./pipe-routing";
import { pipeRouter, type PipeRouterId } from "./routing";
import { withExits, type ExitShape, type PipeExits } from "./routing/exits";

import {
  anchor,
  directions,
  PipeTransition,
  routeKey,
  toPath,
  type RoutedPath,
} from "./routing/route-transitions";

export type { RoutedPath } from "./routing/route-transitions";

/** Edges of this type are pipes: routed here and drawn by the pipe layers. */
export const PIPE_EDGE_TYPE = "pipe";

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

  set(id: string, next: RoutedPath | undefined): void {
    const current = this.paths.get(id);
    if (current?.path === next?.path && current?.depth === next?.depth) return;
    if (next) this.paths.set(id, next);
    else this.paths.delete(id);
    for (const listener of this.listeners.get(id) ?? []) listener();
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

/** One animation frame for both books. Only active morphs run in it. */
class RouteTransitions {
  readonly resting = new Map<string, PipeTransition>();
  readonly moving = new Map<string, PipeTransition>();
  private active = new Set<PipeTransition>();
  private frame: number | undefined;

  animate(transition: PipeTransition): void {
    this.active.add(transition);
    this.frame ??= requestAnimationFrame(this.tick);
  }

  stop(transition: PipeTransition): void {
    transition.stop();
    this.active.delete(transition);
    if (this.active.size === 0 && this.frame !== undefined) {
      cancelAnimationFrame(this.frame);
      this.frame = undefined;
    }
  }

  dispose(): void {
    for (const routes of [this.resting, this.moving]) {
      for (const transition of routes.values()) this.stop(transition);
      routes.clear();
    }
  }

  private tick = (now: number): void => {
    this.frame = undefined;
    for (const transition of this.active) {
      if (!transition.frame(now)) this.active.delete(transition);
    }
    if (this.active.size) this.frame = requestAnimationFrame(this.tick);
  };
}

interface RouterProps {
  book: RouteBook;
  movingBook: RouteBook;
  router: PipeRouterId;
  radius: number;
  lanes: boolean;
  depth: boolean;
  cards: CardAvoidance;
  exits: PipeExits;
  dwell: boolean;
  morph: boolean;
}

/** Freeze the resting book on pickup. On drop, seed it with the moving paths. */
export function PipeRouter({
  book,
  movingBook,
  router,
  radius,
  lanes,
  depth,
  cards,
  exits,
  dwell,
  morph,
}: RouterProps) {
  const route: SceneRouter = React.useMemo(
    () => pipeRouter(router).create(),
    [router],
  );
  const settled = useStore(selectSettledPipes);
  const moving = useStore(selectMovingSignature);
  const store = useStoreApi();
  const [transitions] = React.useState(() => new RouteTransitions());
  const draggingRef = React.useRef(false);
  // Each pipe's exit shape last time, so a dragged pipe keeps it near a line.
  const shapesRef = React.useRef(new Map<string, ExitShape>());
  React.useLayoutEffect(() => () => transitions.dispose(), [transitions]);

  React.useLayoutEffect(
    function publishRoutes() {
      const dragging = !settled;
      const wasDragging = draggingRef.current;
      draggingRef.current = dragging;
      const { resting, moving: inFlight } = transitions;
      const active = dragging ? inFlight : resting;
      const output = dragging ? movingBook : book;
      if (dragging && !wasDragging) {
        for (const transition of resting.values()) transitions.stop(transition);
      }
      if (dragging && !moving && inFlight.size === 0) return;
      const collected = collectScene(store.getState());
      const { movingIds } = collected;
      const exited = withExits(collected.scene, exits, shapesRef.current);
      const { scene } = exited;
      if (dragging) {
        // Resting pipes are not routed while dragging: keep their shapes.
        for (const [id, shape] of exited.shapes) {
          if (movingIds.has(id)) shapesRef.current.set(id, shape);
        }
      } else {
        shapesRef.current = exited.shapes;
      }
      const layout = route(scene, { lanes, depth, cards });
      const seen = new Set<string>();
      for (const pipe of scene.pipes) {
        const { id } = pipe;
        if (dragging && !movingIds.has(id)) continue;
        const routed = layout.get(id);
        if (!routed) continue;
        seen.add(id);
        const destination = {
          key: `${router}:${lanes}:${depth}:${cards}:${exits}:${routeKey(routed)}`,
          path: toPath(routed.points, routed.depth, radius),
        };
        let transition = active.get(id);
        const released = dragging ? undefined : inFlight.get(id);
        if (!transition || released) {
          if (transition) transitions.stop(transition);
          const previous = dragging ? resting.get(id) : released;
          const prior = previous?.destination ?? destination;
          const priorPath = previous?.shown ?? destination.path;
          const points = anchor(priorPath.points, pipe);
          const shown = toPath(points, priorPath.depth, radius);
          transition = new PipeTransition(
            prior,
            (path) => output.set(id, path),
            (active) => transitions.animate(active),
            shown,
          );
          active.set(id, transition);
          output.set(id, shown);
          // React Flow can mark a node as dragging before its ports move.
          if (dragging && previous && points === priorPath.points) continue;
          // With Morph off, keep a released path that already occupies the
          // settled route. Its next ordinary layout will update it as usual.
          if (
            released &&
            !morph &&
            !released.animating &&
            prior.key === destination.key &&
            points === priorPath.points &&
            directions(points) === directions(prior.path.points)
          )
            continue;
        }
        transition.update({
          destination,
          pipe,
          radius,
          dwell: dragging && dwell,
          morph,
          settle: !dragging && wasDragging,
        });
      }

      for (const [id, transition] of active) {
        if (seen.has(id)) continue;
        transitions.stop(transition);
        active.delete(id);
        output.set(id, undefined);
      }
      if (!dragging) {
        for (const [id, transition] of inFlight) {
          transitions.stop(transition);
          movingBook.set(id, undefined);
        }
        inFlight.clear();
      }
    },
    [
      book,
      movingBook,
      router,
      route,
      radius,
      lanes,
      depth,
      cards,
      exits,
      dwell,
      morph,
      settled,
      moving,
      store,
      transitions,
    ],
  );

  return null;
}
