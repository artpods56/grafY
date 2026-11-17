import { useStoreApi } from "@xyflow/react";
import * as React from "react";

/**
 * React Flow's own store, as the hooks hand it out. Named here so the canvas can
 * pass a handle to the Workbench without either side importing the package's
 * internal state type.
 */
export type FlowStore = ReturnType<typeof useStoreApi>;
type FlowStoreState = ReturnType<FlowStore["getState"]>;
type FlowInternalNode = NonNullable<
  ReturnType<FlowStoreState["nodeLookup"]["get"]>
>;

/** A held node and where the pointer has it now, already grid-snapped. */
export type DraggedNodePosition = {
  node_id: string;
  x: number;
  y: number;
};

/**
 * Move the held nodes by writing them into React Flow's store.
 *
 * A pointer sample used to land in Workbench state, because React Flow in
 * controlled mode only reports a drag: `updateNodePositions` builds a position
 * change and hands it to `onNodesChange`, leaving the rendered position entirely
 * ours to hold. State at that rate costs a render per sample, and with it the
 * derived data of every node and card on the canvas — so a gesture was priced by
 * the size of the document rather than by what the hand was doing.
 *
 * The store is where React Flow reads positions from: a node wrapper subscribes
 * to `nodeLookup.get(id)` and an edge recomputes its endpoints from the same
 * lookup, so replacing one entry moves that node and redraws the wires attached
 * to it, while every other entry keeps its identity and re-renders nothing.
 * `internals.userNode` is left pointing at the prop object, so the next prop
 * sync — which adopts by reference equality — cannot undo the move.
 *
 * Returns false when the gesture has to go the old way: no canvas to write to
 * yet, or a name the canvas does not hold. Nothing is written in that case.
 */
export function moveDraggedNodes(
  store: FlowStore | null,
  positions: readonly DraggedNodePosition[],
): boolean {
  if (!store || positions.length === 0) return false;
  const previous = store.getState().nodeLookup;
  const moved = new Map(previous);
  for (const position of positions) {
    const internal = previous.get(position.node_id) as
      FlowInternalNode | undefined;
    if (!internal) return false;
    const next = {
      ...internal,
      position: { x: position.x, y: position.y },
      dragging: true,
      internals: {
        ...internal.internals,
        // The canvas holds no parented nodes, so absolute and local agree. Were
        // that to change, a child would have to be offset by its parent here.
        positionAbsolute: { x: position.x, y: position.y },
      },
    } as FlowInternalNode;
    moved.set(position.node_id, next);
  }
  store.setState({ nodeLookup: moved });
  return true;
}

/**
 * The canvas node objects the store was handed for `ids` — the exact identities
 * `moveDraggedNodes` writes beside, and therefore the identities the owner of the
 * document has to keep handing back for as long as the gesture lasts.
 *
 * A prop sync rebuilds an internal node from whatever it is given, so a render
 * that arrives mid-gesture for some unrelated reason would otherwise redraw the
 * held node from the document and snap it back under the pointer. Returning one
 * of these objects untouched is what makes that render agree with the store
 * instead of fighting it: `adoptUserNodes` keeps its own node when the incoming
 * object is the one it already holds. The cost is that the object is a
 * snapshot — a change to a held node's data waits for the hand to open.
 *
 * Returns null, holding nothing, when there is no canvas or an id is unknown.
 */
export function draggedNodeProps<Node>(
  store: FlowStore | null,
  ids: readonly string[],
): Record<string, Node> | null {
  if (!store || ids.length === 0) return null;
  const lookup = store.getState().nodeLookup;
  const held: Record<string, Node> = {};
  for (const id of ids) {
    const internal = lookup.get(id) as FlowInternalNode | undefined;
    if (!internal) return null;
    held[id] = internal.internals.userNode as unknown as Node;
  }
  return held;
}

/**
 * True when `held` — what `draggedNodeProps` handed back at the close of the hand
 * — already covers exactly the ids this sample carries. While it does, the
 * gesture needs neither a fresh hold nor the render a fresh hold would cause.
 */
export function holdsDraggedIds<Node>(
  held: Record<string, Node> | null,
  ids: readonly string[],
): boolean {
  if (!held || ids.length === 0) return false;
  const heldIds = Object.keys(held);
  if (heldIds.length !== ids.length) return false;
  for (const id of ids) {
    if (held[id] === undefined) return false;
  }
  return true;
}

/**
 * Publishes the store to a ref so the owner of the document can write to it. A
 * child of the canvas, because the store arrives through context.
 */
export function FlowStoreBridge({
  storeRef,
}: {
  storeRef: React.RefObject<FlowStore | null>;
}) {
  const store = useStoreApi();
  React.useLayoutEffect(() => {
    storeRef.current = store;
    return () => {
      if (storeRef.current === store) storeRef.current = null;
    };
  }, [store, storeRef]);
  return null;
}
