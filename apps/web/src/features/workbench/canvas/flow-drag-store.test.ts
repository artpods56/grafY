import { describe, expect, it } from "vitest";

import {
  draggedNodeProps,
  holdsDraggedIds,
  moveDraggedNodes,
  type DraggedNodePosition,
  type FlowStore,
} from "./flow-drag-store";

/**
 * The shape React Flow keeps in `nodeLookup`: a user node plus the internals the
 * renderer reads. Only the fields this module touches are filled in.
 */
type InternalNode = {
  id: string;
  position: { x: number; y: number };
  data: Record<string, unknown>;
  dragging?: boolean;
  measured?: { width?: number; height?: number };
  internals: {
    positionAbsolute: { x: number; y: number };
    userNode: { id: string; position: { x: number; y: number } };
    z: number;
  };
};

type Lookup = Map<string, InternalNode>;

function heldNode(id: string, x: number, y: number): InternalNode {
  const userNode = { id, position: { x, y } };
  return {
    id,
    position: { x, y },
    data: {},
    dragging: false,
    measured: { width: 220, height: 90 },
    internals: { positionAbsolute: { x, y }, userNode, z: 0 },
  };
}

/**
 * React Flow's store, reduced to the two calls this module makes: read the
 * lookup, publish a new one. `published` records what was handed to `setState`
 * and `lookup` stays the Map the gesture started from, so a test can prove
 * neither was written through.
 */
function fakeStore(lookup: Lookup) {
  const published: Array<Record<string, unknown>> = [];
  let state: { nodeLookup: Lookup } = { nodeLookup: lookup };
  const store = {
    getState: () => state,
    setState: (patch: Record<string, unknown>) => {
      published.push(patch);
      state = { ...state, ...patch };
    },
  } as unknown as FlowStore;
  return { published, store };
}

/** The lookup the store holds now. */
function current(store: FlowStore): Lookup {
  return store.getState().nodeLookup;
}

/** The one lookup a successful write published. */
function publishedLookup(
  published: readonly Record<string, unknown>[],
): Lookup {
  expect(published).toHaveLength(1);
  const next = published[0]?.["nodeLookup"];
  expect(next).toBeInstanceOf(Map);
  return next as Lookup;
}

function positionOn(id: string, x: number, y: number): DraggedNodePosition {
  return { node_id: id, x, y };
}

describe("moveDraggedNodes", () => {
  it("declines when there is no canvas to write to", () => {
    expect(moveDraggedNodes(null, [positionOn("node-a", 10, 20)])).toBe(false);
  });

  it("returns false for an empty list, since there is nothing to move", () => {
    const lookup = new Map([["node-a", heldNode("node-a", 0, 0)]]);
    const { store, published } = fakeStore(lookup);

    expect(moveDraggedNodes(store, [])).toBe(false);
    expect(published).toEqual([]);
    expect(current(store)).toBe(lookup);
  });

  it("declines and writes nothing when a position names a node the canvas does not hold", () => {
    const lookup = new Map([
      ["node-a", heldNode("node-a", 0, 0)],
      ["node-b", heldNode("node-b", 100, 100)],
    ]);
    const { store, published } = fakeStore(lookup);

    const accepted = moveDraggedNodes(store, [
      positionOn("node-a", 500, 600),
      positionOn("node-gone", 1, 1),
    ]);

    // Either the sample lands or none of it does: a partial write would leave the
    // hand holding one node at the pointer and another somewhere behind it.
    expect(accepted).toBe(false);
    expect(published).toEqual([]);
    expect(current(store)).toBe(lookup);
    expect(lookup.get("node-a")?.position).toEqual({ x: 0, y: 0 });
  });

  it("moves the named node and leaves every other entry the same object", () => {
    const nodeA = heldNode("node-a", 0, 0);
    const nodeB = heldNode("node-b", 100, 100);
    const nodeC = heldNode("node-c", 200, 200);
    const lookup = new Map([
      ["node-a", nodeA],
      ["node-b", nodeB],
      ["node-c", nodeC],
    ]);
    const { store, published } = fakeStore(lookup);

    expect(moveDraggedNodes(store, [positionOn("node-b", 320, 410)])).toBe(
      true,
    );

    const next = publishedLookup(published);
    expect(next.get("node-b")).not.toBe(nodeB);
    expect(next.get("node-b")?.position).toEqual({ x: 320, y: 410 });
    // Identity is the whole point: every node left alone re-renders nothing.
    expect(next.get("node-a")).toBe(nodeA);
    expect(next.get("node-c")).toBe(nodeC);
    expect(next.size).toBe(3);
  });

  it("publishes a new lookup instead of writing into the one it read", () => {
    const nodeA = heldNode("node-a", 0, 0);
    const lookup = new Map([["node-a", nodeA]]);
    const { store, published } = fakeStore(lookup);

    moveDraggedNodes(store, [positionOn("node-a", 40, 50)]);

    // The store hands the same Map to every subscriber, so a write through it
    // would move a node without telling anyone that it moved.
    expect(lookup).not.toBe(publishedLookup(published));
    expect(nodeA.position).toEqual({ x: 0, y: 0 });
    expect(nodeA.internals.positionAbsolute).toEqual({ x: 0, y: 0 });
    expect(lookup.get("node-a")).toBe(nodeA);
  });

  it("sets the position, the dragging flag, and the absolute position together", () => {
    const lookup = new Map([["node-a", heldNode("node-a", 0, 0)]]);
    const { store } = fakeStore(lookup);

    moveDraggedNodes(store, [positionOn("node-a", 640, 270)]);

    const movedNode = current(store).get("node-a");
    expect(movedNode?.position).toEqual({ x: 640, y: 270 });
    expect(movedNode?.dragging).toBe(true);
    // The renderer draws `positionAbsolute`, and any later recompute derives it
    // from `position`: disagreeing would draw the node in one place and
    // hit-test it in another. The canvas holds no parented nodes, so the two
    // are the same number.
    expect(movedNode?.internals.positionAbsolute).toEqual({ x: 640, y: 270 });
  });

  it("keeps the user node the store already holds, which is what survives a prop sync", () => {
    const nodeA = heldNode("node-a", 0, 0);
    const userNode = nodeA.internals.userNode;
    const lookup = new Map([["node-a", nodeA]]);
    const { store, published } = fakeStore(lookup);

    moveDraggedNodes(store, [positionOn("node-a", 80, 90)]);

    // `adoptUserNodes` keeps its own internal node only while the incoming prop
    // object is `internals.userNode`. Swapping it here would let the next sync of
    // an unchanged document undo the move.
    expect(publishedLookup(published)).toBe(current(store));
    expect(current(store).get("node-a")?.internals.userNode).toBe(userNode);
    expect(current(store)).not.toBe(lookup);
  });

  it("carries the rest of the internal node through untouched", () => {
    const nodeA = heldNode("node-a", 0, 0);
    const lookup = new Map([["node-a", nodeA]]);
    const { store } = fakeStore(lookup);

    moveDraggedNodes(store, [positionOn("node-a", 10, 20)]);

    const movedNode = current(store).get("node-a");
    expect(movedNode?.measured).toEqual({ width: 220, height: 90 });
    expect(movedNode?.data).toBe(nodeA.data);
    expect(movedNode?.internals.z).toBe(0);
  });

  it("moves every node of a multi-node sample in one publish", () => {
    const nodeC = heldNode("node-c", 20, 20);
    const lookup = new Map([
      ["node-a", heldNode("node-a", 0, 0)],
      ["node-b", heldNode("node-b", 10, 10)],
      ["node-c", nodeC],
    ]);
    const { store, published } = fakeStore(lookup);

    const accepted = moveDraggedNodes(store, [
      positionOn("node-a", 200, 260),
      positionOn("node-b", 210, 270),
    ]);

    expect(accepted).toBe(true);
    const next = publishedLookup(published);
    expect(next.get("node-a")?.position).toEqual({ x: 200, y: 260 });
    expect(next.get("node-b")?.internals.positionAbsolute).toEqual({
      x: 210,
      y: 270,
    });
    expect(next.get("node-c")).toBe(nodeC);
  });

  it("follows a gesture: each sample replaces the last sample, not the document", () => {
    const lookup = new Map([["node-a", heldNode("node-a", 0, 0)]]);
    const { store, published } = fakeStore(lookup);

    moveDraggedNodes(store, [positionOn("node-a", 54, 54)]);
    moveDraggedNodes(store, [positionOn("node-a", 108, 108)]);

    expect(published).toHaveLength(2);
    expect(current(store).get("node-a")?.position).toEqual({ x: 108, y: 108 });
    // The first sample's Map is the one the second read, and neither was written
    // through: the gesture is a chain of publishes off one frozen document.
    expect(published[1]?.["nodeLookup"]).toBe(current(store));
    expect(lookup.get("node-a")?.position).toEqual({ x: 0, y: 0 });
  });
});

describe("draggedNodeProps", () => {
  it("hands back the prop objects the canvas holds for the named nodes", () => {
    const nodeA = heldNode("node-a", 0, 0);
    const nodeB = heldNode("node-b", 10, 10);
    const { store } = fakeStore(
      new Map([
        ["node-a", nodeA],
        ["node-b", nodeB],
      ]),
    );

    const held = draggedNodeProps(store, ["node-a", "node-b"]);

    expect(held).not.toBeNull();
    expect(held?.["node-a"]).toBe(nodeA.internals.userNode);
    expect(held?.["node-b"]).toBe(nodeB.internals.userNode);
  });

  it("holds nothing when there is no canvas, no id, or an unknown one", () => {
    const lookup = new Map([["node-a", heldNode("node-a", 0, 0)]]);
    const { store } = fakeStore(lookup);

    expect(draggedNodeProps(null, ["node-a"])).toBeNull();
    expect(draggedNodeProps(store, [])).toBeNull();
    expect(draggedNodeProps(store, ["node-a", "node-gone"])).toBeNull();
    expect(current(store)).toBe(lookup);
  });

  it("is unaffected by the write it is paired with, so a gesture keeps one identity", () => {
    const nodeA = heldNode("node-a", 0, 0);
    const lookup = new Map([["node-a", nodeA]]);
    const { store } = fakeStore(lookup);

    const held = draggedNodeProps(store, ["node-a"]);
    moveDraggedNodes(store, [positionOn("node-a", 30, 40)]);
    const again = draggedNodeProps(store, ["node-a"]);

    // The render holds the object the store was handed and the store keeps
    // pointing at it: that pair is what a later prop sync has to agree with for
    // the pointer's position to survive it.
    expect(again?.["node-a"]).toBe(held?.["node-a"]);
  });
});

describe("holdsDraggedIds", () => {
  it("recognises the sample a held gesture is already carrying", () => {
    const held = { "node-a": { id: "node-a" }, "node-b": { id: "node-b" } };

    // The answer decides whether a pointer sample renders, so every sample of an
    // unchanged gesture has to say yes, whatever order it names the ids in.
    expect(holdsDraggedIds(held, ["node-a", "node-b"])).toBe(true);
    expect(holdsDraggedIds(held, ["node-b", "node-a"])).toBe(true);
  });

  it("asks for a fresh hold when the gesture is not held yet or has changed", () => {
    const held = { "node-a": { id: "node-a" } };

    expect(holdsDraggedIds(null, ["node-a"])).toBe(false);
    expect(holdsDraggedIds(held, [])).toBe(false);
    expect(holdsDraggedIds(held, ["node-b"])).toBe(false);
    expect(holdsDraggedIds(held, ["node-a", "node-b"])).toBe(false);
  });
});
