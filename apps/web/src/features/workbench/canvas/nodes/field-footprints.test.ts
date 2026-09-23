import { describe, expect, it } from "vitest";

import type { SchemaField } from "../config-schema";
import { STANDARD_NODE_WIDTH_CELLS } from "../grid-layout";
import {
  HALF_WIDTH_CELLS,
  MIN_HALF_BRICK_PX,
  configBoardColumns,
  configControlKind,
  fieldFootprint,
  packFieldFootprints,
  secretFootprint,
  type FieldFootprint,
} from "./field-footprints";

function scalarField(overrides: Partial<SchemaField> = {}): SchemaField {
  return {
    name: "field",
    title: "Field",
    type: "string",
    required: false,
    nullable: false,
    ...overrides,
  } as SchemaField;
}

describe("config field footprints", () => {
  it("resolves control kinds from the schema shape", () => {
    expect(configControlKind(scalarField())).toBe("text");
    expect(configControlKind(scalarField({ type: "integer" }))).toBe("number");
    expect(
      configControlKind(scalarField({ enumValues: ["fast", "slow"] })),
    ).toBe("select");
    expect(configControlKind(scalarField({ type: "boolean" }))).toBe(
      "checkbox",
    );
    expect(configControlKind(scalarField({ format: "textarea" }))).toBe(
      "textarea",
    );
    expect(
      configControlKind(
        scalarField({ format: "textarea", codeLanguage: "sql" }),
      ),
    ).toBe("code");
  });

  it("gives short controls half the standard node and long controls all of it", () => {
    expect(fieldFootprint(scalarField())).toEqual({
      columns: HALF_WIDTH_CELLS,
      rows: 1,
      growX: true,
    });
    expect(fieldFootprint(scalarField({ type: "boolean" }))).toEqual({
      columns: HALF_WIDTH_CELLS,
      rows: 1,
      growX: true,
    });
    expect(fieldFootprint(scalarField({ format: "textarea" }))).toEqual({
      columns: STANDARD_NODE_WIDTH_CELLS,
      rows: 2,
      growX: true,
      growY: true,
    });
    expect(secretFootprint().columns).toBe(STANDARD_NODE_WIDTH_CELLS);
  });

  it("charges a tuple one extra cell per additional pair of inputs", () => {
    const items = [
      { title: "West", type: "number" as const },
      { title: "South", type: "number" as const },
      { title: "East", type: "number" as const },
      { title: "North", type: "number" as const },
    ];
    expect(
      fieldFootprint({
        name: "bounds",
        title: "Bounds",
        type: "number-tuple",
        items,
        required: true,
        nullable: false,
      }).rows,
    ).toBe(2);
    expect(
      fieldFootprint({
        name: "center",
        title: "Center",
        type: "number-tuple",
        items: items.slice(0, 2),
        required: true,
        nullable: false,
      }).rows,
    ).toBe(1);
  });

  it("stretches before reflowing: extra columns only at comfortable brick width", () => {
    expect(configBoardColumns(300, 50)).toBe(STANDARD_NODE_WIDTH_CELLS);
    // Double width still packs two half-bricks — CSS 1fr tracks do the growing.
    expect(configBoardColumns(600, 50)).toBe(STANDARD_NODE_WIDTH_CELLS);
    expect(configBoardColumns(MIN_HALF_BRICK_PX * 3, 50)).toBe(9);
    expect(configBoardColumns(MIN_HALF_BRICK_PX * 4, 50)).toBe(12);
    // Never pack skinnier than one half-brick, even on a tiny node.
    expect(configBoardColumns(100, 50)).toBe(STANDARD_NODE_WIDTH_CELLS);
  });
});

const short: FieldFootprint = { columns: 3, rows: 2, growX: true };
const wide: FieldFootprint = { columns: 6, rows: 3, growX: true, growY: true };

describe("config field packing", () => {
  it("pairs half-width bricks on one shelf and preserves schema order", () => {
    const board = packFieldFootprints([short, short, short], { columns: 6 });
    expect(board.placements.map((placement) => placement.index)).toEqual([
      0, 1, 2,
    ]);
    expect(
      board.placements.map(({ col, row, w, h }) => ({ col, row, w, h })),
    ).toEqual([
      { col: 0, row: 0, w: 3, h: 2 },
      { col: 3, row: 0, w: 3, h: 2 },
      // Lone third brick grows into the empty half of its shelf.
      { col: 0, row: 2, w: 6, h: 2 },
    ]);
    expect(board.rows).toBe(4);
  });

  it("reflows into more columns only when the packer is given more columns", () => {
    const narrow = packFieldFootprints([short, short, short, short], {
      columns: 6,
    });
    const widened = packFieldFootprints([short, short, short, short], {
      columns: 12,
    });
    expect(narrow.rows).toBe(4);
    expect(widened.rows).toBe(2);
    // Spare columns are shared so each brick grows past its 3-cell minimum.
    expect(widened.placements.map((placement) => placement.w)).toEqual([
      3, 3, 3, 3,
    ]);
    expect(widened.placements.map((placement) => placement.col)).toEqual([
      0, 3, 6, 9,
    ]);
  });

  it("opens a new shelf when the next brick no longer fits", () => {
    const board = packFieldFootprints([short, wide, short], { columns: 6 });
    expect(
      board.placements.map(({ index, col, row }) => ({ index, col, row })),
    ).toEqual([
      { index: 0, col: 0, row: 0 },
      { index: 1, col: 0, row: 2 },
      { index: 2, col: 0, row: 5 },
    ]);
    expect(board.rows).toBe(7);
  });

  it("clamps bricks wider than the board and keeps them on their own shelf", () => {
    const board = packFieldFootprints([wide, short], { columns: 4 });
    expect(board.placements).toEqual([
      { index: 0, col: 0, row: 0, w: 4, h: 3 },
      { index: 1, col: 0, row: 3, w: 4, h: 2 },
    ]);
  });

  it("shares leftover shelf columns across growable bricks", () => {
    const board = packFieldFootprints([short, short], { columns: 9 });
    expect(board.placements.map(({ col, w }) => ({ col, w }))).toEqual([
      { col: 0, w: 5 },
      { col: 5, w: 4 },
    ]);
  });

  it("hands spare body rows to the growable shelves", () => {
    const board = packFieldFootprints([short, wide], {
      columns: 6,
      minRows: 9,
    });
    expect(board.rows).toBe(9);
    expect(board.placements).toEqual([
      { index: 0, col: 0, row: 0, w: 6, h: 2 },
      { index: 1, col: 0, row: 2, w: 6, h: 7 },
    ]);
  });

  it("grows the body past a requested height that cannot hold the bricks", () => {
    const board = packFieldFootprints([wide, wide], { columns: 6, minRows: 2 });
    expect(board.rows).toBe(6);
    expect(board.placements.map((placement) => placement.h)).toEqual([3, 3]);
  });

  it("keeps a requested height that no brick can claim", () => {
    const board = packFieldFootprints([short], { columns: 6, minRows: 5 });
    expect(board.rows).toBe(5);
    expect(board.placements[0]?.h).toBe(2);
    expect(packFieldFootprints([], { columns: 6, minRows: 3 })).toEqual({
      columns: 6,
      rows: 3,
      placements: [],
    });
  });
});
