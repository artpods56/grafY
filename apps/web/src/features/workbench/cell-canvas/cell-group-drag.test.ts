import { describe, expect, it } from "vitest";

import {
  computeCellResize,
  createGroupDragSession,
  hasCardOverlap,
  minCardHeightCellsForPorts,
  partitionSceneForMovingCards,
  rectsOverlap,
  resolveNonOverlappingDelta,
  updateGroupDragSession,
} from "./cell-group-drag";
import type { CellCardModel, CellPipeModel } from "./cell-model";

function card(id: string, col: number, row: number): CellCardModel {
  return {
    id,
    title: id,
    subtitle: "",
    col,
    row,
    widthCells: 3,
    heightCells: 2,
    ports: [],
  };
}

describe("group drag", () => {
  it("preserves the grab offset and uses the latest snapped cell for hysteresis", () => {
    const cards = [card("anchor", 2, -1), card("other", 8, 0)];
    const session = createGroupDragSession(
      cards,
      new Set(["other"]),
      "anchor",
      { x: 115, y: 15 },
    );
    expect(session.movingCardIds).toEqual(new Set(["anchor"]));
    expect(session.grabOffsetWorld).toEqual({ x: 65, y: 40 });

    // The card changes cell 0.74 cells (18.5px) past its origin.
    const near = updateGroupDragSession(session, cards, { x: 133, y: 15 });
    expect(near.snappedDelta).toEqual({ col: 0, row: 0 });
    expect(near.changedCell).toBe(false);
    expect(near.visualOffset.x).toBeCloseTo(2.7);
    expect(near.visualOffset.y).toBe(0);

    const over = updateGroupDragSession(near.session, cards, { x: 134, y: 15 });
    expect(over.snappedDelta).toEqual({ col: 1, row: 0 });
    expect(over.changedCell).toBe(true);
    expect(over.visualOffset.x).toBeCloseTo(-0.9);
    expect(over.visualOffset.y).toBe(0);
    expect(over.movedCards[0]).toMatchObject({ col: 3, row: -1 });
    expect(over.movedCards[1]).toBe(cards[1]);

    const back = updateGroupDragSession(over.session, over.movedCards, {
      x: 123,
      y: 15,
    });
    expect(back.snappedDelta).toEqual({ col: 1, row: 0 });
    expect(back.changedCell).toBe(false);
    const returned = updateGroupDragSession(back.session, back.movedCards, {
      x: 120,
      y: 15,
    });
    expect(returned.snappedDelta).toEqual({ col: 0, row: 0 });
    expect(returned.movedCards).toEqual(cards);
  });

  it("applies one integer delta to each selected card's initial cell", () => {
    const cards = [
      card("a", -2, 3),
      card("b", 5, 4),
      card("c", 10, -5),
      card("rest", 20, 0),
    ];
    const session = createGroupDragSession(
      cards,
      new Set(["a", "b", "c", "missing"]),
      "a",
      {
        x: -10,
        y: 85,
      },
    );
    expect(session.movingCardIds).toEqual(new Set(["a", "b", "c"]));
    const forward = updateGroupDragSession(session, cards, {
      x: 73.5,
      y: 29.5,
    });
    expect(forward.snappedDelta).toEqual({ col: 3, row: -2 });
    const reverse = updateGroupDragSession(
      forward.session,
      forward.movedCards,
      { x: -35, y: 160 },
    );
    expect(reverse.snappedDelta).toEqual({ col: -1, row: 3 });
    expect(
      reverse.movedCards.map(({ id, col, row }) => [id, col, row]),
    ).toEqual([
      ["a", -3, 6],
      ["b", 4, 7],
      ["c", 9, -2],
      ["rest", 20, 0],
    ]);
    expect(reverse.movedCards[3]).toBe(cards[3]);
  });

  it("returns positive zero for a snap from a negative coordinate to the origin", () => {
    const cards = [card("a", 0, 0)];
    const session = createGroupDragSession(cards, new Set(), "a", {
      x: 0,
      y: 0,
    });
    const left = updateGroupDragSession(session, cards, { x: -25, y: -25 });
    expect(left.snappedDelta).toEqual({ col: -1, row: -1 });
    const back = updateGroupDragSession(left.session, left.movedCards, {
      x: -5,
      y: -5,
    });
    expect(back.snappedDelta.col).toBe(0);
    expect(back.snappedDelta.row).toBe(0);
    expect(back.movedCards[0]).toMatchObject({ col: 0, row: 0 });
  });

  it("keeps wells shared with resting pipes in the resting scene", () => {
    function pipe(
      id: string,
      sourceCardId: string,
      targetCardId: string,
    ): CellPipeModel {
      return {
        id,
        sourceCardId,
        sourcePortId: "out",
        targetCardId,
        targetPortId: "in",
      };
    }
    const fromRest = pipe("from resting", "a", "b");
    const withinGroup = pipe("within group", "b", "c");
    const toRest = pipe("to resting", "c", "d");
    const rest = pipe("resting", "a", "e");
    const graph = {
      cards: ["a", "b", "c", "d", "e"].map((id, index) =>
        card(id, index * 4, 0),
      ),
      pipes: [fromRest, withinGroup, toRest, rest],
    };
    expect(partitionSceneForMovingCards(graph, new Set(["b", "c"]))).toEqual({
      restingPipes: [rest],
      movingPipes: [fromRest, withinGroup, toRest],
      attachedPipeIds: new Set(["from resting", "within group", "to resting"]),
      restingWellKeys: new Set(["a:out", "e:in"]),
      movingWellKeys: new Set(["b:in", "b:out", "c:in", "c:out", "d:in"]),
    });
  });
});

describe("card overlap", () => {
  it("allows shared seams and detects overlapping interiors", () => {
    const a = card("a", -3, 0);
    const b = card("b", 0, 0);
    const c = card("c", -1, 1);
    expect(rectsOverlap(a, b)).toBe(false);
    expect(rectsOverlap(a, c)).toBe(true);
    expect(hasCardOverlap([a, b, card("d", 0, 2)])).toBe(false);
    expect(hasCardOverlap([a, b, c])).toBe(true);
  });

  it("finds the nearest clear group placement and cancels when the search radius is exhausted", () => {
    const cards = [
      card("a", 0, 0),
      card("b", 0, 4),
      card("wall-a", 5, 0),
      card("wall-b", 5, 4),
    ];
    const moving = new Set(["a", "b"]);
    const resolved = resolveNonOverlappingDelta(cards, moving, {
      col: 5,
      row: 0,
    });
    expect(resolved).toEqual({ col: 5, row: -2 });
    const movedCards = cards.map((item) =>
      moving.has(item.id)
        ? {
            ...item,
            col: item.col + resolved.col,
            row: item.row + resolved.row,
          }
        : item,
    );
    expect(hasCardOverlap(movedCards)).toBe(false);
    expect(
      resolveNonOverlappingDelta(cards, moving, { col: 5, row: 0 }, 1),
    ).toEqual({ col: 0, row: 0 });
  });

  it("preserves a clear delta even if stationary cards already overlap", () => {
    const cards = [card("a", 0, 0), card("wall-a", 5, 0), card("wall-b", 6, 0)];
    const delta = resolveNonOverlappingDelta(cards, new Set(["a"]), {
      col: -0,
      row: -2,
    });
    expect(delta.col).toBe(0);
    expect(delta.row).toBe(-2);
  });
});

describe("card resize", () => {
  const start = { x: 50, y: 50 };

  it("rounds movement to cells and only resizes the axes touched by the handle", () => {
    const a = { ...card("a", 0, 0), widthCells: 5, heightCells: 6 };
    expect(computeCellResize(a, "e", start, { x: 63, y: 200 })).toEqual({
      cardId: "a",
      widthCells: 6,
      heightCells: 6,
    });
    expect(computeCellResize(a, "s", start, { x: 0, y: 37 })).toEqual({
      cardId: "a",
      widthCells: 5,
      heightCells: 5,
    });
  });

  it("clamps both axes to configured bounds and protects the lowest port row", () => {
    const a: CellCardModel = {
      ...card("a", 0, 0),
      widthCells: 6,
      heightCells: 7,
      resizeBounds: {
        minWidthCells: 4,
        maxWidthCells: 8,
        minHeightCells: 3,
        maxHeightCells: 10,
      },
      ports: [
        {
          id: "one",
          name: "One",
          direction: "input",
          rowOffset: 1,
          artifactTypeId: "text",
          shape: "one",
        },
        {
          id: "two",
          name: "Two",
          direction: "output",
          rowOffset: 5,
          artifactTypeId: "text",
          shape: "one",
        },
      ],
    };
    // The lowest port row, then the row the plate's bottom inset takes.
    expect(minCardHeightCellsForPorts(a)).toBe(7);
    expect(computeCellResize(a, "se", start, { x: -100, y: -100 })).toEqual({
      cardId: "a",
      widthCells: 4,
      heightCells: 7,
    });
    expect(computeCellResize(a, "se", start, { x: 600, y: 600 })).toEqual({
      cardId: "a",
      widthCells: 8,
      heightCells: 10,
    });
    const lowCap = {
      ...a,
      resizeBounds: {
        ...a.resizeBounds,
        minWidthCells: 4,
        minHeightCells: 3,
        maxHeightCells: 4,
      },
    };
    expect(
      computeCellResize(lowCap, "s", start, { x: 100, y: -100 }).heightCells,
    ).toBe(7);
  });
});
