// @vitest-environment node

import { describe, expect, it } from "vitest";

import {
  runEffectReducer,
  runEffectSequence,
} from "@/lib/state/effect-reducer";

import type { CellCardSurfaceData } from "./cell-contracts";
import { detectCellDockedJoins } from "./cell-docking";
import { DEFAULT_CELL_ROUTING } from "./cell-look";
import {
  CELL_SIZE,
  portAnchorCenter,
  type CellCardModel,
  type CellGraph,
  type CellPort,
} from "./cell-model";
import { routeCellGraph } from "./cell-router";
import {
  DRAG_THRESHOLD_PX,
  WIRE_SNAP_RADIUS,
  cellCanvasInteractionReducer,
  createInitialCellCanvasInteractionState,
  indexGraph,
  isUnderCardsFrame,
  type CellCanvasInteractionAction,
  type CellCanvasInteractionEffect,
  type CellCanvasInteractionState,
  type OpenSpreadSnapshot,
} from "./cell-canvas-interaction-reducer";

const initial = createInitialCellCanvasInteractionState();

function card(
  id: string,
  col: number,
  row: number,
  patch: Partial<CellCardModel> = {},
): CellCardModel {
  return {
    id,
    title: id,
    subtitle: "",
    kind: "artifact",
    col,
    row,
    widthCells: 10,
    heightCells: 8,
    ports: [],
    ...patch,
  };
}

function port(
  id: string,
  direction: CellPort["direction"],
  rowOffset = 2,
): CellPort {
  return {
    id,
    name: id,
    direction,
    rowOffset,
    artifactTypeId: "scalar.text",
    shape: "one",
  };
}

function artifact(itemCount = 1): CellCardSurfaceData {
  return {
    kind: "artifact",
    previewKind: "image",
    artifactTypeId: "file.png",
    typeLabel: "PNG",
    ...(itemCount > 1 ? { itemCount } : {}),
  };
}

interface Scene {
  graph: CellGraph;
  surfaces: Readonly<Record<string, CellCardSurfaceData>>;
  index: ReturnType<typeof indexGraph>;
  docking: ReturnType<typeof detectCellDockedJoins>;
  layout: ReturnType<typeof routeCellGraph>;
}

function sceneOf(
  cards: readonly CellCardModel[],
  surfaces: Readonly<Record<string, CellCardSurfaceData>> = {},
  pipes: CellGraph["pipes"] = [],
): Scene {
  const graph: CellGraph = { cards: [...cards], pipes };
  const index = indexGraph(graph, surfaces);
  const foreground = cards.filter(
    (item) => !isUnderCardsFrame(item.id, surfaces),
  );
  const docking = detectCellDockedJoins(
    { cards: [...foreground], pipes },
    () => "#000",
  );
  const layout = routeCellGraph(
    { cards: [...foreground], pipes: docking.routablePipes },
    DEFAULT_CELL_ROUTING,
  );
  return { graph, surfaces, index, docking, layout };
}

function act(
  state: CellCanvasInteractionState,
  action: CellCanvasInteractionAction,
) {
  return runEffectReducer(cellCanvasInteractionReducer, state, action);
}

function kinds(effects: readonly CellCanvasInteractionEffect[]): string[] {
  return effects.map((effect) => effect.kind);
}

function press(
  scene: Scene,
  cardId: string,
  patch: Partial<
    Extract<CellCanvasInteractionAction, { kind: "cardPointerDown" }>
  > = {},
): Extract<CellCanvasInteractionAction, { kind: "cardPointerDown" }> {
  return {
    kind: "cardPointerDown",
    cardId,
    pointerId: 1,
    clientPoint: { x: 0, y: 0 },
    worldPoint: { x: cardId.length, y: 0 },
    shiftKey: false,
    wasSelectedBefore: false,
    selectedCardIds: new Set<string>(),
    editable: true,
    graph: scene.graph,
    surfaces: scene.surfaces,
    index: scene.index,
    routing: DEFAULT_CELL_ROUTING,
    docking: scene.docking,
    layout: scene.layout,
    punched: false,
    openSpread: null,
    canMergeArtifactCards: null,
    hasMergeCallback: false,
    hasInsertCallback: false,
    ...patch,
  };
}

function dragPhase(state: CellCanvasInteractionState) {
  if (state.phase.kind !== "draggingCards") {
    throw new Error(`expected draggingCards, got ${state.phase.kind}`);
  }
  return state.phase;
}

describe("pan", () => {
  it("attaches, accumulates client deltas, and detaches", () => {
    const started = act(initial, {
      kind: "startPan",
      pointerId: 7,
      clientPoint: { x: 0, y: 0 },
    });
    expect(started.state.phase).toEqual({
      kind: "panning",
      pointerId: 7,
      lastClient: { x: 0, y: 0 },
    });
    expect(kinds(started.effects)).toEqual([
      "clearSelection",
      "invokePaneClick",
      "attachWindowGesture",
    ]);
    expect(started.effects[2]).toMatchObject({ gesture: "pan", pointerId: 7 });

    const moved = runEffectSequence(
      cellCanvasInteractionReducer,
      started.state,
      [
        { kind: "panMove", pointerId: 7, clientPoint: { x: 10, y: 5 } },
        { kind: "panMove", pointerId: 7, clientPoint: { x: 20, y: 10 } },
        { kind: "panMove", pointerId: 7, clientPoint: { x: 20, y: 10 } },
        { kind: "panMove", pointerId: 4, clientPoint: { x: 80, y: 80 } },
      ],
    );
    expect(moved.effects).toEqual([
      { kind: "panViewportBy", dx: 10, dy: 5 },
      { kind: "panViewportBy", dx: 10, dy: 5 },
    ]);
    expect(moved.state.phase).toMatchObject({
      kind: "panning",
      lastClient: { x: 20, y: 10 },
    });

    const ended = act(moved.state, { kind: "panEnd", pointerId: 7 });
    expect(ended.state.phase).toEqual({ kind: "idle" });
    expect(kinds(ended.effects)).toEqual(["detachWindowGesture"]);
    expect(act(ended.state, { kind: "panEnd", pointerId: 7 }).state).toBe(
      ended.state,
    );
  });

  it("cancels an in-flight pan before a new one", () => {
    const started = act(initial, {
      kind: "startPan",
      pointerId: 1,
      clientPoint: { x: 3, y: 4 },
    });
    const again = act(started.state, {
      kind: "startPan",
      pointerId: 2,
      clientPoint: { x: 8, y: 9 },
    });
    expect(kinds(again.effects)).toEqual([
      "detachWindowGesture",
      "clearSelection",
      "invokePaneClick",
      "attachWindowGesture",
    ]);
    expect(again.state.phase).toMatchObject({ pointerId: 2 });
  });
});

describe("marquee", () => {
  const lone = sceneOf([card("source", 0, 0)]);

  it("selects cards the rect hits and clears the rect on release", () => {
    const started = act(initial, {
      kind: "startMarquee",
      pointerId: 3,
      worldPoint: { x: -1, y: -1 },
      foregroundCards: lone.graph.cards,
      routedPipes: lone.layout.pipes,
    });
    expect(kinds(started.effects)).toEqual([
      "setStoreMarquee",
      "attachWindowGesture",
    ]);
    expect(started.effects[0]).toMatchObject({
      rect: { start: { x: -1, y: -1 }, current: { x: -1, y: -1 } },
    });

    const moved = act(started.state, {
      kind: "marqueeMove",
      pointerId: 3,
      worldPoint: { x: 100, y: 100 },
      foregroundCards: lone.graph.cards,
      routedPipes: lone.layout.pipes,
    });
    expect(kinds(moved.effects)).toEqual([
      "setStoreMarquee",
      "commitSelection",
    ]);
    expect(moved.effects[1]).toMatchObject({
      selection: { cardIds: ["source"], pipeIds: [] },
    });

    const ended = act(moved.state, { kind: "marqueeEnd", pointerId: 3 });
    expect(ended.state.phase).toEqual({ kind: "idle" });
    expect(ended.effects[1]).toEqual({ kind: "setStoreMarquee", rect: null });
    expect(
      act(ended.state, {
        kind: "marqueeMove",
        pointerId: 3,
        worldPoint: { x: 1, y: 1 },
        foregroundCards: lone.graph.cards,
        routedPipes: lone.layout.pipes,
      }).state,
    ).toBe(ended.state);
  });
});

describe("card press and drag", () => {
  const board = sceneOf(
    [card("loose", 40, 2), card("stack", 12, 2), card("frame", 0, 20)],
    {
      loose: artifact(1),
      stack: artifact(3),
      frame: {
        kind: "annotation",
        variant: "frame",
        color: "slate",
        bodyText: "",
        layer: "under-cards",
      },
    },
  );

  it("selects on press and stays idle when the canvas is read-only", () => {
    const pressed = act(initial, press(board, "loose", { editable: false }));
    expect(pressed.state.phase).toEqual({ kind: "idle" });
    expect(kinds(pressed.effects)).toEqual(["commitSelection"]);
    expect(pressed.effects[0]).toMatchObject({
      selection: { cardIds: ["loose"], pipeIds: [] },
    });
  });

  it("toggles selection on shift and still arms a drag", () => {
    const pressed = act(
      initial,
      press(board, "loose", {
        shiftKey: true,
        wasSelectedBefore: true,
        selectedCardIds: new Set(["loose", "stack"]),
      }),
    );
    expect(kinds(pressed.effects)).toEqual([
      "toggleCardSelection",
      "attachWindowGesture",
    ]);
    expect([...dragPhase(pressed.state).session.movingCardIds].sort()).toEqual([
      "loose",
      "stack",
    ]);
  });

  it("does not select a missing card, and cancels the gesture already running", () => {
    const panning = act(initial, {
      kind: "startPan",
      pointerId: 1,
      clientPoint: { x: 0, y: 0 },
    });
    const missing = act(
      panning.state,
      press(board, "missing", {
        index: indexGraph({ cards: [], pipes: [] }, {}),
      }),
    );
    expect(missing.state.phase).toEqual({ kind: "idle" });
    expect(kinds(missing.effects)).toEqual(["detachWindowGesture"]);
  });

  it("ignores motion inside the click threshold and narrows a selected card on release", () => {
    const pressed = act(
      initial,
      press(board, "loose", {
        wasSelectedBefore: true,
        selectedCardIds: new Set(["loose", "stack"]),
      }),
    );
    const nudged = act(pressed.state, {
      kind: "dragMove",
      pointerId: 1,
      clientPoint: { x: DRAG_THRESHOLD_PX - 1, y: 0 },
      worldPoint: { x: 0, y: 0 },
      now: 10,
      openSpread: null,
    });
    expect(nudged.state).toBe(pressed.state);
    expect(nudged.effects).toEqual([]);

    const released = act(nudged.state, {
      kind: "dragUp",
      pointerId: 1,
      now: 20,
    });
    expect(released.state.phase).toEqual({ kind: "idle" });
    expect(kinds(released.effects)).toEqual([
      "detachWindowGesture",
      "cancelDragFrame",
      "commitSelection",
    ]);
    expect(released.effects[2]).toMatchObject({
      selection: { cardIds: ["loose"], pipeIds: [] },
    });
  });

  it("does not narrow selection when shift is held or the card was unselected", () => {
    const shifted = act(
      initial,
      press(board, "loose", { shiftKey: true, wasSelectedBefore: true }),
    );
    expect(
      kinds(
        act(shifted.state, { kind: "dragUp", pointerId: 1, now: 1 }).effects,
      ),
    ).toEqual(["detachWindowGesture", "cancelDragFrame"]);

    const fresh = act(initial, press(board, "loose"));
    expect(
      kinds(act(fresh.state, { kind: "dragUp", pointerId: 1, now: 1 }).effects),
    ).not.toContain("commitSelection");
  });

  it("drags a frame by itself", () => {
    const pressed = act(
      initial,
      press(board, "frame", {
        wasSelectedBefore: true,
        selectedCardIds: new Set(["frame", "loose"]),
      }),
    );
    expect([...dragPhase(pressed.state).session.movingCardIds]).toEqual([
      "frame",
    ]);
    expect(dragPhase(pressed.state).draggingFrame).toBe(true);
  });

  it("arms pipes, reroutes on a cell change, and commits the landing after settle", () => {
    const pressed = act(
      initial,
      press(board, "loose", { worldPoint: { x: 0, y: 0 } }),
    );
    const moved = act(pressed.state, {
      kind: "dragMove",
      pointerId: 1,
      clientPoint: { x: DRAG_THRESHOLD_PX, y: 0 },
      worldPoint: { x: CELL_SIZE, y: 0 },
      now: 100,
      openSpread: null,
    });
    const phase = dragPhase(moved.state);
    expect(phase.movedBeyondClick).toBe(true);
    expect(phase.landingDelta).toEqual({ col: 1, row: 0 });
    expect(moved.state.rerouteCount).toBe(1);
    expect(moved.state.dragFrame?.showGhostCells).toBe(true);
    expect(kinds(moved.effects)).toEqual([
      "notifyDragProgress",
      "notifyDragProgress",
      "setStoreDraggingCards",
      "scheduleDragFrame",
    ]);

    const released = act(moved.state, {
      kind: "dragUp",
      pointerId: 1,
      now: 120,
    });
    expect(dragPhase(released.state).pointerReleased).toBe(true);
    expect(kinds(released.effects)).toEqual(["scheduleDragFrame"]);

    const settled = act(released.state, {
      kind: "dragTick",
      now: 20_000,
      index: board.index,
    });
    expect(settled.state.phase).toEqual({ kind: "idle" });
    expect(settled.state.dragFrame).toBeNull();
    expect(kinds(settled.effects)).toEqual([
      "detachWindowGesture",
      "cancelDragFrame",
      "notifyDragProgress",
      "commitMoveCards",
      "setStoreDraggingCards",
    ]);
    expect(settled.effects[3]).toMatchObject({
      moves: [{ cardId: "loose", col: 41, row: 2 }],
    });
  });

  it("does not commit a move when the card lands on its own cell", () => {
    const pressed = act(initial, press(board, "loose"));
    const moved = act(pressed.state, {
      kind: "dragMove",
      pointerId: 1,
      clientPoint: { x: 4, y: 0 },
      worldPoint: press(board, "loose").worldPoint,
      now: 50,
      openSpread: null,
    });
    expect(dragPhase(moved.state).landingDelta).toEqual({ col: 0, row: 0 });
    const released = act(moved.state, {
      kind: "dragUp",
      pointerId: 1,
      now: 60,
    });
    const settled = act(released.state, {
      kind: "dragTick",
      now: 20_000,
      index: board.index,
    });
    expect(kinds(settled.effects)).not.toContain("commitMoveCards");
    expect(settled.state.phase.kind).toBe("idle");
  });

  it("keeps ticking while a released drag is still morphing or settling", () => {
    const pressed = act(
      initial,
      press(board, "loose", { worldPoint: { x: 0, y: 0 } }),
    );
    const moved = act(pressed.state, {
      kind: "dragMove",
      pointerId: 1,
      clientPoint: { x: 8, y: 0 },
      worldPoint: { x: CELL_SIZE, y: 0 },
      now: 100,
      openSpread: null,
    });
    const released = act(moved.state, {
      kind: "dragUp",
      pointerId: 1,
      now: 100,
    });
    const early = act(released.state, {
      kind: "dragTick",
      now: 110,
      index: board.index,
    });
    expect(early.state.phase.kind).toBe("draggingCards");
    expect(kinds(early.effects)).toContain("scheduleDragFrame");
  });

  it("merges onto the card under the pointer instead of landing", () => {
    const pressed = act(
      initial,
      press(board, "loose", {
        canMergeArtifactCards: (source, target) =>
          source === "loose" && target === "stack",
        hasMergeCallback: true,
        worldPoint: { x: 1000, y: 60 },
      }),
    );
    const moved = act(pressed.state, {
      kind: "dragMove",
      pointerId: 1,
      clientPoint: { x: 12, y: 0 },
      worldPoint: { x: 400, y: 120 },
      now: 200,
      openSpread: null,
    });
    expect(dragPhase(moved.state).mergeTargetId).toBe("stack");
    expect(dragPhase(moved.state).mergeItemCount).toBe(4);
    expect(moved.effects).toContainEqual({
      kind: "setMergeTarget",
      target: { cardId: "stack", itemCount: 4 },
    });

    const dropped = act(moved.state, {
      kind: "dragUp",
      pointerId: 1,
      now: 220,
    });
    expect(dropped.state.phase).toEqual({ kind: "idle" });
    expect(dropped.state.dragFrame).toBeNull();
    expect(kinds(dropped.effects)).toEqual([
      "startStackTucks",
      "detachWindowGesture",
      "cancelDragFrame",
      "setMergeTarget",
      "notifyDragProgress",
      "setStoreDraggingCards",
      "commitMergeArtifactCards",
    ]);
    expect(dropped.effects[0]).toMatchObject({
      joins: [{ card: { id: "loose" }, target: { id: "stack" }, slot: 0 }],
    });
    expect(dropped.effects.at(-1)).toEqual({
      kind: "commitMergeArtifactCards",
      cardId: "loose",
      targetCardId: "stack",
    });
    expect(kinds(dropped.effects)).not.toContain("commitMoveCards");
  });

  it("inserts into the live spread window and does not move the card", () => {
    const stackCard = board.graph.cards[1]!;
    const spread: OpenSpreadSnapshot = {
      card: stackCard,
      layout: {
        canExpand: true,
        windowed: true,
        startCol: 12,
        row: 2,
        totalCols: 30,
        heightCells: 8,
        visibleCount: 3,
        minVisibleCount: 3,
        maxVisibleCount: 3,
      },
      windowStart: 0,
      itemCount: 3,
    };
    const pressed = act(
      initial,
      press(board, "loose", {
        openSpread: spread,
        canMergeArtifactCards: () => true,
        hasInsertCallback: true,
        hasMergeCallback: true,
        worldPoint: { x: 1000, y: 400 },
      }),
    );
    const paged: OpenSpreadSnapshot = {
      ...spread,
      windowStart: 1,
      itemCount: 4,
    };
    const moved = act(pressed.state, {
      kind: "dragMove",
      pointerId: 1,
      clientPoint: { x: 9, y: 0 },
      worldPoint: { x: 22 * CELL_SIZE, y: 6 * CELL_SIZE },
      now: 300,
      openSpread: paged,
    });
    const insert = dragPhase(moved.state).spreadInsert;
    expect(insert).not.toBeNull();
    expect(insert?.insertIndex).toBe(1 + 1);
    expect(moved.effects).toContainEqual({
      kind: "setSpreadInsertTarget",
      target: insert,
    });

    const dropped = act(moved.state, {
      kind: "dragUp",
      pointerId: 1,
      now: 320,
    });
    expect(dropped.state.phase.kind).toBe("idle");
    expect(dropped.effects.at(-1)).toEqual({
      kind: "commitInsertArtifactCardIntoSequence",
      cardId: "loose",
      spreadCardId: "stack",
      insertIndex: insert?.insertIndex,
    });
    expect(kinds(dropped.effects)).not.toContain("commitMoveCards");
    expect(kinds(dropped.effects)).not.toContain("commitMergeArtifactCards");
  });

  it("cancels a drag without committing when another gesture starts", () => {
    const pressed = act(
      initial,
      press(board, "loose", { worldPoint: { x: 0, y: 0 } }),
    );
    const moved = act(pressed.state, {
      kind: "dragMove",
      pointerId: 1,
      clientPoint: { x: 6, y: 0 },
      worldPoint: { x: 4, y: 0 },
      now: 10,
      openSpread: null,
    });
    const cancelled = act(moved.state, { kind: "cancelGesture" });
    expect(cancelled.state.phase).toEqual({ kind: "idle" });
    expect(cancelled.state.dragFrame).toBeNull();
    expect(kinds(cancelled.effects)).toEqual([
      "detachWindowGesture",
      "cancelDragFrame",
      "notifyDragProgress",
      "setStoreDraggingCards",
    ]);
    expect(kinds(cancelled.effects)).not.toContain("commitMoveCards");
  });
});

describe("resize", () => {
  const plate = card("plate", 0, 0, {
    kind: "operator",
    widthCells: 12,
    heightCells: 6,
    resizable: true,
  });

  function begin() {
    return act(initial, {
      kind: "startResize",
      card: plate,
      edge: "e",
      startWorld: { x: 0, y: 0 },
      editable: true,
    });
  }

  it("starts only when editable and ignores a matching move", () => {
    expect(
      act(initial, {
        kind: "startResize",
        card: plate,
        edge: "e",
        startWorld: { x: 0, y: 0 },
        editable: false,
      }).state,
    ).toBe(initial);

    const started = begin();
    expect(started.state.phase).toMatchObject({
      kind: "resizingCard",
      preview: { cardId: "plate", widthCells: 12, heightCells: 6 },
    });
    expect(started.effects).toEqual([
      { kind: "setStoreResizingCard", cardId: "plate" },
    ]);

    const same = act(started.state, {
      kind: "resizeMove",
      cardId: "plate",
      edge: "e",
      worldPoint: { x: 4, y: 0 },
    });
    expect(same.state).toBe(started.state);

    const wrong = act(started.state, {
      kind: "resizeMove",
      cardId: "other",
      edge: "e",
      worldPoint: { x: CELL_SIZE * 3, y: 0 },
    });
    expect(wrong.state).toBe(started.state);
  });

  it("counts a real size change and commits it on release", () => {
    const started = begin();
    const grown = act(started.state, {
      kind: "resizeMove",
      cardId: "plate",
      edge: "e",
      worldPoint: { x: CELL_SIZE * 2, y: 0 },
    });
    expect(grown.state.rerouteCount).toBe(1);
    expect(grown.state.phase).toMatchObject({
      preview: { widthCells: 14, heightCells: 6 },
    });

    const ended = act(grown.state, {
      kind: "resizeEnd",
      cardId: "plate",
      edge: "e",
      worldPoint: { x: CELL_SIZE * 2, y: 0 },
    });
    expect(ended.state.phase).toEqual({ kind: "idle" });
    expect(ended.state.rerouteCount).toBe(2);
    expect(kinds(ended.effects)).toEqual([
      "setStoreResizingCard",
      "commitResizeCard",
    ]);
  });

  it("drops a resize that did not change size, and cancel never commits", () => {
    const started = begin();
    const ended = act(started.state, {
      kind: "resizeEnd",
      cardId: "plate",
      edge: "e",
      worldPoint: { x: 2, y: 0 },
    });
    expect(ended.state.phase).toEqual({ kind: "idle" });
    expect(ended.state.rerouteCount).toBe(0);
    expect(kinds(ended.effects)).toEqual(["setStoreResizingCard"]);

    const again = begin();
    const moved = act(again.state, {
      kind: "resizeMove",
      cardId: "plate",
      edge: "se",
      worldPoint: { x: CELL_SIZE, y: CELL_SIZE },
    });
    const cancelled = act(moved.state, { kind: "cancelGesture" });
    expect(cancelled.state.phase).toEqual({ kind: "idle" });
    expect(kinds(cancelled.effects)).toEqual(["setStoreResizingCard"]);
    expect(cancelled.state.rerouteCount).toBe(moved.state.rerouteCount);
  });
});

describe("connect", () => {
  const source = card("source", 2, 2, {
    kind: "operator",
    widthCells: 12,
    heightCells: 6,
    ports: [port("out", "output")],
  });
  const sink = card("sink", 18, 2, {
    kind: "operator",
    widthCells: 12,
    heightCells: 6,
    ports: [port("in", "input")],
  });
  const cards = [source, sink];
  const fromPort = source.ports[0]!;
  const sinkCentre = portAnchorCenter(sink, sink.ports[0]!, false);

  function begin(cursor = { x: 0, y: 0 }) {
    return act(initial, {
      kind: "startConnect",
      pointerId: 5,
      fromCardId: "source",
      fromPort,
      cursor,
      cards,
      surfaces: {},
      punched: false,
    });
  }

  it("snaps to a port inside the radius and commits that connection", () => {
    expect(WIRE_SNAP_RADIUS).toBe(22);
    const far = begin();
    expect(far.state.phase).toMatchObject({
      kind: "connectingPipe",
      target: null,
    });
    expect(far.effects[0]).toEqual({
      kind: "setStoreActivePortKey",
      key: null,
    });
    expect(far.effects[1]).toMatchObject({ gesture: "connect", pointerId: 5 });

    const near = act(far.state, {
      kind: "connectMove",
      pointerId: 5,
      cursor: { x: sinkCentre.x + 4, y: sinkCentre.y },
      cards,
      surfaces: {},
      punched: false,
    });
    expect(near.state.phase).toMatchObject({
      target: { cardId: "sink", port: { id: "in" } },
    });
    expect(kinds(near.effects)).toEqual(["setStoreActivePortKey"]);

    const held = act(near.state, {
      kind: "connectMove",
      pointerId: 9,
      cursor: { x: 0, y: 0 },
      cards,
      surfaces: {},
      punched: false,
    });
    expect(held.state).toBe(near.state);

    const committed = act(near.state, {
      kind: "connectEnd",
      pointerId: 5,
      clientPoint: { x: 12, y: 14 },
      isCancel: false,
    });
    expect(committed.state.phase).toEqual({ kind: "idle" });
    expect(committed.effects[2]).toEqual({
      kind: "commitConnect",
      ends: {
        sourceCardId: "source",
        sourcePortId: "out",
        targetCardId: "sink",
        targetPortId: "in",
      },
    });
    expect(committed.state.lastConnectDropEmpty).toBeNull();
  });

  it("records an empty drop and ignores a cancelled release", () => {
    const started = begin({ x: 40, y: 80 });
    const dropped = act(started.state, {
      kind: "connectEnd",
      pointerId: 5,
      clientPoint: { x: 3, y: 4 },
      isCancel: false,
    });
    expect(dropped.state.lastConnectDropEmpty).toEqual({
      sourceCardId: "source",
      sourcePortId: "out",
      direction: "downstream",
      worldPoint: { x: 40, y: 80 },
      targetCell: { col: 1, row: 3 },
      clientPoint: { x: 3, y: 4 },
    });
    expect(kinds(dropped.effects)).toEqual([
      "detachWindowGesture",
      "setStoreActivePortKey",
      "notifyConnectDropEmpty",
    ]);

    const again = begin();
    const cancelled = act(again.state, {
      kind: "connectEnd",
      pointerId: 5,
      clientPoint: { x: 1, y: 1 },
      isCancel: true,
    });
    expect(cancelled.state.phase).toEqual({ kind: "idle" });
    expect(cancelled.state.lastConnectDropEmpty).toBeNull();
    expect(kinds(cancelled.effects)).toEqual([
      "detachWindowGesture",
      "setStoreActivePortKey",
    ]);
  });

  it("skips a port the caller rejects", () => {
    const rejected = act(initial, {
      kind: "startConnect",
      pointerId: 5,
      fromCardId: "source",
      fromPort,
      cursor: sinkCentre,
      cards,
      surfaces: {},
      punched: false,
      canConnect: () => false,
    });
    expect(rejected.state.phase).toMatchObject({ target: null });
  });
});

describe("exclusive gestures", () => {
  it("cancels a resize without committing when a connection starts", () => {
    const plate = card("plate", 0, 0, { widthCells: 12, heightCells: 6 });
    const resizing = act(initial, {
      kind: "startResize",
      card: plate,
      edge: "s",
      startWorld: { x: 0, y: 0 },
      editable: true,
    });
    const connecting = act(resizing.state, {
      kind: "startConnect",
      pointerId: 2,
      fromCardId: "plate",
      fromPort: port("out", "output"),
      cursor: { x: 10, y: 10 },
      cards: [plate],
      surfaces: {},
      punched: false,
    });
    expect(kinds(connecting.effects).slice(0, 2)).toEqual([
      "setStoreResizingCard",
      "setStoreActivePortKey",
    ]);
    expect(connecting.effects[0]).toEqual({
      kind: "setStoreResizingCard",
      cardId: null,
    });
    expect(kinds(connecting.effects)).not.toContain("commitResizeCard");
    expect(connecting.state.phase.kind).toBe("connectingPipe");
  });

  it("leaves idle state untouched", () => {
    expect(act(initial, { kind: "cancelGesture" }).state).toBe(initial);
    expect(
      act(initial, {
        kind: "dragTick",
        now: 1,
        index: indexGraph({ cards: [], pipes: [] }, {}),
      }).state,
    ).toBe(initial);
  });

  it("ignores dragTick before pointer movement crosses the drag threshold", () => {
    const solo = sceneOf([card("loose", 4, 2)]);
    const pressed = act(initial, press(solo, "loose"));
    expect(pressed.state.phase).toMatchObject({
      kind: "draggingCards",
      movedBeyondClick: false,
    });
    const ticked = act(pressed.state, {
      kind: "dragTick",
      now: 16,
      index: solo.index,
    });
    expect(ticked.state).toBe(pressed.state);
    expect(ticked.state.dragFrame).toBeNull();
    expect(ticked.effects).toEqual([]);
  });
});
