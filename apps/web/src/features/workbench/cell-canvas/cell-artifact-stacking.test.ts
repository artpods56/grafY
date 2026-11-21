import { describe, expect, it } from "vitest";

import {
  computeSequenceSpreadLayout,
  findArtifactMergeSuggestions,
  findArtifactMergeTarget,
  findSpreadInsertTarget,
} from "./cell-artifact-stacking";
import type { CellCardSurfaceData } from "./cell-contracts";
import { CELL_SIZE, type CellCardModel } from "./cell-model";

function card(
  id: string,
  col: number,
  row: number,
  widthCells = 10,
  heightCells = 8,
): CellCardModel {
  return {
    id,
    title: id,
    subtitle: "",
    kind: "artifact",
    col,
    row,
    widthCells,
    heightCells,
    ports: [],
  };
}

function artifact(itemCount = 1): CellCardSurfaceData {
  return {
    kind: "artifact",
    previewKind: "image",
    artifactTypeId: "file.png",
    typeLabel: "PNG image",
    ...(itemCount > 1 ? { itemCount } : {}),
  };
}

const always = () => true;

describe("findArtifactMergeSuggestions", () => {
  it("offers a left-to-right sequence for two cards laid flush side by side", () => {
    const suggestions = findArtifactMergeSuggestions(
      [card("right", 10, 2), card("left", 0, 0)],
      { left: artifact(), right: artifact(2) },
      always,
    );
    expect(suggestions).toEqual([
      {
        id: "left|right",
        axis: "horizontal",
        cardIds: ["left", "right"],
        targetCardId: "left",
        itemCount: 3,
        bounds: { col: 0, row: 0, widthCells: 20, heightCells: 10 },
        // Centred under the run, on the plates' bottom edge.
        anchor: { x: 250, y: 10 * CELL_SIZE - 4 },
      },
    ]);
  });

  it("offers a whole flush row once, not once per seam", () => {
    const suggestions = findArtifactMergeSuggestions(
      [card("c", 20, 0), card("a", 0, 0), card("d", 30, 0), card("b", 10, 0)],
      { a: artifact(), b: artifact(), c: artifact(3), d: artifact() },
      always,
    );
    expect(suggestions).toHaveLength(1);
    expect(suggestions[0]).toMatchObject({
      id: "a|b|c|d",
      cardIds: ["a", "b", "c", "d"],
      targetCardId: "a",
      itemCount: 6,
      bounds: { col: 0, row: 0, widthCells: 40, heightCells: 8 },
      anchor: { x: 20 * CELL_SIZE, y: 8 * CELL_SIZE - 4 },
    });
  });

  it("merges into the one wired card when the first may not take the rest", () => {
    // `b` is passed into an input: it may receive, but never go away.
    const canMerge = (source: string) => source !== "b";
    const [suggestion] = findArtifactMergeSuggestions(
      [card("a", 0, 0), card("b", 10, 0), card("c", 20, 0)],
      { a: artifact(), b: artifact(), c: artifact() },
      canMerge,
    );
    expect(suggestion).toMatchObject({
      cardIds: ["a", "b", "c"],
      targetCardId: "b",
    });
  });

  it("breaks a row between two wired cards that cannot meet", () => {
    const wired = new Set(["b", "c"]);
    const suggestions = findArtifactMergeSuggestions(
      [card("a", 0, 0), card("b", 10, 0), card("c", 20, 0), card("d", 30, 0)],
      { a: artifact(), b: artifact(), c: artifact(), d: artifact() },
      (source) => !wired.has(source),
    );
    expect(suggestions.map((suggestion) => suggestion.cardIds)).toEqual([
      ["a", "b"],
      ["c", "d"],
    ]);
    expect(suggestions.map((suggestion) => suggestion.targetCardId)).toEqual([
      "b",
      "c",
    ]);
  });

  it("offers nothing across a gap or without overlapping rows", () => {
    expect(
      findArtifactMergeSuggestions(
        [card("a", 0, 0), card("b", 11, 0), card("c", 10, 8)],
        { a: artifact(), b: artifact(), c: artifact() },
        always,
      ),
    ).toEqual([]);
  });

  it("offers to merge stacks laid flush one above the other", () => {
    const suggestions = findArtifactMergeSuggestions(
      [card("top", 0, 0), card("middle", 2, 8), card("bottom", 2, 16)],
      { top: artifact(3), middle: artifact(2), bottom: artifact() },
      always,
    );
    expect(suggestions).toEqual([
      expect.objectContaining({
        axis: "vertical",
        cardIds: ["top", "middle", "bottom"],
        targetCardId: "top",
        itemCount: 6,
        bounds: { col: 0, row: 0, widthCells: 12, heightCells: 24 },
        anchor: { x: 6 * CELL_SIZE, y: 24 * CELL_SIZE - 4 },
      }),
    ]);
  });

  it("leaves stacks a cell apart in a column alone", () => {
    expect(
      findArtifactMergeSuggestions(
        [card("top", 0, 0), card("bottom", 0, 9)],
        { top: artifact(3), bottom: artifact(2) },
        always,
      ),
    ).toEqual([]);
  });

  it("does not offer two single cards stacked vertically", () => {
    expect(
      findArtifactMergeSuggestions(
        [card("top", 0, 0), card("bottom", 0, 8)],
        { top: artifact(), bottom: artifact() },
        always,
      ),
    ).toEqual([]);
  });

  it("does not offer a card in a column that a row already offers", () => {
    const suggestions = findArtifactMergeSuggestions(
      [card("a", 0, 0), card("b", 10, 0), card("below", 0, 8)],
      { a: artifact(3), b: artifact(), below: artifact(2) },
      always,
    );
    expect(suggestions.map((suggestion) => suggestion.id)).toEqual(["a|b"]);
  });

  it("offers nothing the merge check refuses, or for other kinds of card", () => {
    expect(
      findArtifactMergeSuggestions(
        [card("a", 0, 0), card("b", 10, 0)],
        { a: artifact(), b: artifact() },
        () => false,
      ),
    ).toEqual([]);
    expect(
      findArtifactMergeSuggestions(
        [card("a", 0, 0), card("op", 10, 0)],
        { a: artifact(), op: { kind: "operator" } },
        always,
      ),
    ).toEqual([]);
  });
});

describe("computeSequenceSpreadLayout", () => {
  const stack = card("stack", 50, 10, 10, 8);

  it("lays a small sequence open in full, flush rightward from the card's own column", () => {
    expect(
      computeSequenceSpreadLayout({
        card: stack,
        itemCount: 3,
        foregroundCards: [stack],
      }),
    ).toEqual({
      canExpand: true,
      windowed: false,
      startCol: 50,
      row: 10,
      totalCols: 30,
      heightCells: 8,
      visibleCount: 3,
      minVisibleCount: 3,
      maxVisibleCount: 3,
    });
  });

  it("cannot open when blocked closely on the right, even with open space on the left", () => {
    const operator = card("op", 65, 12, 10, 6);
    // 10 + 5 = 15 cols rightward fits only 1 slot (< min 3 for 3 items).
    expect(
      computeSequenceSpreadLayout({
        card: stack,
        itemCount: 3,
        foregroundCards: [stack, operator],
      }),
    ).toEqual({ canExpand: false });
  });

  it("ignores cards outside the card's rows and cards to the left", () => {
    const left = card("left", 40, 10, 10, 8);
    const above = card("above", 60, 0, 10, 10);
    const layout = computeSequenceSpreadLayout({
      card: stack,
      itemCount: 3,
      foregroundCards: [stack, left, above],
    });
    expect(layout).toMatchObject({
      canExpand: true,
      startCol: 50,
      totalCols: 30,
    });
  });

  it("opens a 2-item sequence with room for 2 slots to the right", () => {
    const right = card("right", 70, 10, 10, 8);
    expect(
      computeSequenceSpreadLayout({
        card: stack,
        itemCount: 2,
        foregroundCards: [stack, right],
      }),
    ).toEqual({
      canExpand: true,
      windowed: false,
      startCol: 50,
      row: 10,
      totalCols: 20,
      heightCells: 8,
      visibleCount: 2,
      minVisibleCount: 2,
      maxVisibleCount: 2,
    });
  });

  it("windows a long sequence strictly rightward from card.col with no empty docks", () => {
    expect(
      computeSequenceSpreadLayout({
        card: stack,
        itemCount: 20,
        foregroundCards: [stack],
      }),
    ).toEqual({
      canExpand: true,
      windowed: true,
      startCol: 50,
      row: 10,
      totalCols: 40,
      heightCells: 8,
      visibleCount: 4,
      minVisibleCount: 3,
      maxVisibleCount: 13,
    });
  });

  it("sizes the default slot count to the viewport", () => {
    const layout = computeSequenceSpreadLayout({
      card: stack,
      itemCount: 20,
      foregroundCards: [stack],
      // 0.85 * 950 / 250 = 3 slots.
      viewportWorldWidth: 950,
    });
    expect(layout).toMatchObject({
      windowed: true,
      startCol: 50,
      visibleCount: 3,
      totalCols: 30,
    });
  });

  it("keeps a resized spread inside the free corridor to the right", () => {
    const right = card("right", 100, 10, 10, 8);
    // 50..100 = 50 free columns rightward -> 5 card slots at most.
    const layout = computeSequenceSpreadLayout({
      card: stack,
      itemCount: 20,
      foregroundCards: [stack, right],
      preferredVisibleCount: 12,
    });
    expect(layout).toMatchObject({
      windowed: true,
      startCol: 50,
      visibleCount: 5,
      maxVisibleCount: 5,
      totalCols: 50,
    });
    if (!layout.canExpand) throw new Error("expected a spread");
    expect(layout.startCol + layout.totalCols).toBeLessThanOrEqual(100);
  });

  it("transitions from windowed to full spread when resized to every item", () => {
    const windowed = computeSequenceSpreadLayout({
      card: stack,
      itemCount: 6,
      foregroundCards: [stack],
      preferredVisibleCount: 4,
    });
    expect(windowed).toMatchObject({
      windowed: true,
      startCol: 50,
      visibleCount: 4,
      minVisibleCount: 3,
      maxVisibleCount: 6,
    });
    expect(
      computeSequenceSpreadLayout({
        card: stack,
        itemCount: 6,
        foregroundCards: [stack],
        preferredVisibleCount: 6,
      }),
    ).toMatchObject({
      windowed: false,
      startCol: 50,
      visibleCount: 6,
      totalCols: 60,
    });
  });

  it("cannot open a single item", () => {
    expect(
      computeSequenceSpreadLayout({
        card: stack,
        itemCount: 1,
        foregroundCards: [stack],
      }),
    ).toEqual({ canExpand: false });
  });
});

describe("findSpreadInsertTarget", () => {
  const stack = card("stack", 10, 4, 10, 8);
  const layout = computeSequenceSpreadLayout({
    card: stack,
    itemCount: 6,
    foregroundCards: [stack],
    preferredVisibleCount: 4,
  });
  if (!layout.canExpand) throw new Error("expected open layout");

  it("maps pointer x inside the spread to the exact slot gap and sequence index", () => {
    const y = (4 + 4) * CELL_SIZE;
    // Left half of the left stack -> slot 0, the sequence's start.
    expect(
      findSpreadInsertTarget({
        spreadCardId: "stack",
        layout,
        windowStart: 1,
        itemCount: 6,
        cardWidthCells: 10,
        point: { x: 12 * CELL_SIZE, y },
      }),
    ).toEqual({ spreadCardId: "stack", slot: 0, insertIndex: 0 });
    // Between slot 1 and slot 2 -> slot 2, insertIndex = windowStart + 2.
    expect(
      findSpreadInsertTarget({
        spreadCardId: "stack",
        layout,
        windowStart: 1,
        itemCount: 6,
        cardWidthCells: 10,
        point: { x: 30 * CELL_SIZE, y },
      }),
    ).toEqual({ spreadCardId: "stack", slot: 2, insertIndex: 3 });
    // Right half of the right stack -> slot 4, the sequence's end.
    expect(
      findSpreadInsertTarget({
        spreadCardId: "stack",
        layout,
        windowStart: 1,
        itemCount: 6,
        cardWidthCells: 10,
        point: { x: 48 * CELL_SIZE, y },
      }),
    ).toEqual({ spreadCardId: "stack", slot: 4, insertIndex: 6 });
  });

  it("inserts at windowStart + slot at the outer edges when no stack sits there", () => {
    const y = (4 + 4) * CELL_SIZE;
    const at = (windowStart: number, x: number) =>
      findSpreadInsertTarget({
        spreadCardId: "stack",
        layout,
        windowStart,
        itemCount: 6,
        cardWidthCells: 10,
        point: { x: x * CELL_SIZE, y },
      });
    // windowStart 0: slot 0 is an open card, the right edge is a stack.
    expect(at(0, 12)).toEqual({
      spreadCardId: "stack",
      slot: 0,
      insertIndex: 0,
    });
    expect(at(0, 48)).toEqual({
      spreadCardId: "stack",
      slot: 4,
      insertIndex: 6,
    });
    // windowStart 2 (last page): the left edge is a stack, the right is not.
    expect(at(2, 12)).toEqual({
      spreadCardId: "stack",
      slot: 0,
      insertIndex: 0,
    });
    expect(at(2, 48)).toEqual({
      spreadCardId: "stack",
      slot: 4,
      insertIndex: 6,
    });
    // Inside the left stack's right half -> just after the stack's top.
    expect(at(2, 17)).toEqual({
      spreadCardId: "stack",
      slot: 1,
      insertIndex: 3,
    });
    // Inside the right stack's left half -> just before the stack's top.
    expect(at(1, 42)).toEqual({
      spreadCardId: "stack",
      slot: 3,
      insertIndex: 4,
    });
  });

  it("returns null outside the spread frame", () => {
    expect(
      findSpreadInsertTarget({
        spreadCardId: "stack",
        layout,
        windowStart: 0,
        itemCount: 6,
        cardWidthCells: 10,
        point: { x: 5 * CELL_SIZE, y: 8 * CELL_SIZE },
      }),
    ).toBeNull();
  });
});

describe("findArtifactMergeTarget", () => {
  const cards = [card("dragged", 0, 0), card("target", 20, 0)];
  const surfaces = { dragged: artifact(), target: artifact(2) };
  const inside = { x: 20 * CELL_SIZE + 5, y: 5 };

  it("finds the artifact card under the pointer", () => {
    expect(
      findArtifactMergeTarget(cards, surfaces, "dragged", inside, always),
    ).toBe("target");
  });

  it("ignores the dragged card itself, empty canvas, and refused targets", () => {
    expect(
      findArtifactMergeTarget(
        cards,
        surfaces,
        "dragged",
        { x: 5, y: 5 },
        always,
      ),
    ).toBeNull();
    expect(
      findArtifactMergeTarget(
        cards,
        surfaces,
        "dragged",
        { x: 15 * CELL_SIZE, y: 5 },
        always,
      ),
    ).toBeNull();
    expect(
      findArtifactMergeTarget(cards, surfaces, "dragged", inside, () => false),
    ).toBeNull();
  });

  it("ignores a dragged card that is not an artifact", () => {
    expect(
      findArtifactMergeTarget(
        cards,
        { ...surfaces, dragged: { kind: "operator" } },
        "dragged",
        inside,
        always,
      ),
    ).toBeNull();
  });
});
