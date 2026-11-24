import { describe, expect, it, vi } from "vitest";

import type {
  AnnotationColorToken,
  CellConfigFieldSpec,
  CellInstancePlugItem,
  OperatorCardSurfaceData,
} from "./cell-contracts";
import {
  annotationColorVars,
  computeOperatorCardLayout,
  countConfigShelfCells,
} from "./cell-card-geometry";
import { CELL_SIZE, type CellCardModel } from "./cell-model";

// The compiled tokens are `var(--…)` references; the suite-wide mock in
// vitest.setup.ts carries only two hex values, which would hide both a hue
// mix-up and a literal leaking into the output.
vi.mock("@/lib/stylex/tokens.stylex", () => ({
  tokens: new Proxy({}, { get: (_target, name) => `var(--${String(name)})` }),
}));

function field(
  id: string,
  overrides: Partial<CellConfigFieldSpec> = {},
): CellConfigFieldSpec {
  return { id, label: id, kind: "text", value: "", ...overrides };
}

function plug(plugId: string): CellInstancePlugItem {
  return { plugId, label: plugId, connected: false };
}

const card: CellCardModel = {
  id: "op",
  title: "Operator",
  subtitle: "op.kind",
  kind: "operator",
  col: 0,
  row: 0,
  widthCells: 12,
  heightCells: 4,
  ports: [
    {
      id: "in-a",
      name: "a",
      direction: "input",
      rowOffset: 2,
      artifactTypeId: "scalar.text@1",
      shape: "one",
    },
    {
      id: "out-b",
      name: "b",
      direction: "output",
      rowOffset: 4,
      artifactTypeId: "scalar.text@1",
      shape: "one",
    },
    {
      id: "pages:0",
      name: "pages",
      direction: "input",
      rowOffset: 6,
      artifactTypeId: "image.raster@1",
      shape: "one",
    },
  ],
};

function surfaceWithPlugs(count: number): OperatorCardSurfaceData {
  return {
    kind: "operator",
    instancePlugGroups: [
      {
        portName: "pages",
        title: "Pages",
        artifactTypeId: "image.raster@1",
        shape: "one",
        startRowOffset: 6,
        plugs: Array.from({ length: count }, (_, index) =>
          plug(`pages:${index}`),
        ),
        canAdd: true,
      },
    ],
    configFields: [field("mode")],
  };
}

describe("countConfigShelfCells", () => {
  it("takes no rows without fields", () => {
    expect(countConfigShelfCells([])).toBe(0);
  });

  it("pairs two adjacent half-width fields on one shelf", () => {
    expect(
      countConfigShelfCells([field("a", { span: 1 }), field("b", { span: 1 })]),
    ).toBe(1);
  });

  it("flushes a lone half-width field before a full-width one", () => {
    // One dense row, one cell, for the lone half shelf and one for the full
    // shelf; a third full-width row takes a third cell.
    expect(
      countConfigShelfCells([field("a", { span: 1 }), field("b", { span: 2 })]),
    ).toBe(2);
    expect(
      countConfigShelfCells([
        field("a", { span: 1 }),
        field("b", { span: 2 }),
        field("c"),
      ]),
    ).toBe(3);
    expect(
      countConfigShelfCells([
        field("a", { span: 1 }),
        field("b", { span: 1 }),
        field("c"),
      ]),
    ).toBe(2);
  });

  it("gives a multiline field's three dense rows three cells", () => {
    expect(
      countConfigShelfCells([field("prompt", { kind: "multiline" })]),
    ).toBe(3);
  });
});

describe("computeOperatorCardLayout", () => {
  it("centres every regular port on its cell row", () => {
    const plan = computeOperatorCardLayout(card, { kind: "operator" });
    expect(plan.portYOffsets["in-a"]).toBe(2.5 * CELL_SIZE);
    expect(plan.portYOffsets["out-b"]).toBe(4.5 * CELL_SIZE);
    expect(plan.portBand).toEqual({ startRow: 2, heightCells: 5 });
    expect(plan.headerRow).toBe(0);
    expect(plan.plugBand).toBeNull();
    // The last port's row, then one empty row for the plate's bottom inset.
    expect(plan.totalHeightCells).toBe(8);
  });

  it("leaves instance plug ports out of the regular port band", () => {
    const plan = computeOperatorCardLayout(card, surfaceWithPlugs(2));
    expect(plan.portBand).toEqual({ startRow: 2, heightCells: 3 });
    // Plugs on rows 6 and 8, the "Add" row on 10.
    expect(plan.plugBand).toEqual({ startRow: 6, heightCells: 5 });
    // One empty row between bands, and one under the config shelves.
    expect(plan.configBand).toEqual({ startRow: 12, heightCells: 1 });
    expect(plan.totalHeightCells).toBe(14);
    expect(plan.portYOffsets["pages:1"]).toBe(8.5 * CELL_SIZE);
  });

  it("adds a plug as one port pitch without moving anything above it", () => {
    const before = computeOperatorCardLayout(card, surfaceWithPlugs(2));
    const after = computeOperatorCardLayout(card, surfaceWithPlugs(3));

    expect(after.configBand?.startRow).toBe(
      (before.configBand?.startRow ?? 0) + 2,
    );
    expect(after.totalHeightCells).toBe(before.totalHeightCells + 2);
    expect(after.portBand).toEqual(before.portBand);
    expect(after.portYOffsets["in-a"]).toBe(before.portYOffsets["in-a"]);
    expect(after.portYOffsets["out-b"]).toBe(before.portYOffsets["out-b"]);
    expect(after.portYOffsets["pages:2"]).toBe(10.5 * CELL_SIZE);
  });

  it("collapses the appendix to two rows and keeps four rows at least open", () => {
    const appendix = {
      title: "Last run",
      kindBadge: "table",
      heightCells: 4,
      summaryText: "12 rows",
    };
    const open = computeOperatorCardLayout(card, {
      kind: "operator",
      appendix,
    });
    const collapsed = computeOperatorCardLayout(card, {
      kind: "operator",
      appendix: { ...appendix, collapsed: true },
    });
    const short = computeOperatorCardLayout(card, {
      kind: "operator",
      appendix: { ...appendix, heightCells: 1 },
    });
    const singleOutput = computeOperatorCardLayout(card, {
      kind: "operator",
      appendix: {
        ...appendix,
        kind: "output",
        heightCells: 3,
        outputs: [
          {
            port: "text",
            label: "Text",
            count: 1,
            kind: "single",
            typeLabel: "Text",
            artifactIds: ["art-1"],
          },
        ],
      },
    });

    // An appendix closes the card itself: no empty row under it.
    expect(open.appendixBand).toEqual({ startRow: 8, heightCells: 4 });
    expect(open.totalHeightCells).toBe(12);
    expect(collapsed.appendixBand).toEqual({ startRow: 8, heightCells: 2 });
    expect(collapsed.totalHeightCells).toBe(10);
    expect(short.appendixBand?.heightCells).toBe(4);
    expect(singleOutput.appendixBand).toEqual({ startRow: 8, heightCells: 3 });
    expect(singleOutput.totalHeightCells).toBe(11);
  });

  it("never shrinks below the model's own height", () => {
    const plan = computeOperatorCardLayout(
      { ...card, ports: [], heightCells: 19 },
      { kind: "operator" },
    );
    expect(plan.totalHeightCells).toBe(19);
  });
});

describe("annotationColorVars", () => {
  const colors: AnnotationColorToken[] = [
    "slate",
    "blue",
    "emerald",
    "amber",
    "violet",
    "rose",
  ];

  it("gives each colour its own theme-aware values with no hex literal", () => {
    const seen = new Set<string>();
    for (const color of colors) {
      const vars = annotationColorVars(color);
      for (const value of [vars.border, vars.fill, vars.text]) {
        expect(value).not.toMatch(/#/);
        expect(value).toMatch(/^light-dark\(/);
        expect(value).not.toContain("undefined");
        seen.add(value);
      }
    }
    expect(seen.size).toBe(colors.length * 3);
  });
});
