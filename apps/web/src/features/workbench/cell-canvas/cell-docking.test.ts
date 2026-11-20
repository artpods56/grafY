import { describe, expect, it } from "vitest";
import { detectCellDockedJoins, isPortPairDocked } from "./cell-docking";
import type { CellCardModel, CellPipeModel, CellPort } from "./cell-model";

const output: CellPort = {
  id: "out",
  name: "Result",
  direction: "output",
  rowOffset: 2,
  artifactTypeId: "result",
  shape: "many",
};
const input: CellPort = {
  id: "in",
  name: "Input",
  direction: "input",
  rowOffset: 1,
  artifactTypeId: "input",
  shape: "one",
};
const source: CellCardModel = {
  id: "source",
  title: "Source",
  subtitle: "",
  col: -1,
  row: 2,
  widthCells: 3,
  heightCells: 4,
  ports: [output],
};
const target: CellCardModel = {
  id: "target",
  title: "Target",
  subtitle: "",
  col: 2,
  row: 3,
  widthCells: 4,
  heightCells: 4,
  ports: [input],
};
const pipe: CellPipeModel = {
  id: "pipe",
  sourceCardId: source.id,
  sourcePortId: output.id,
  targetCardId: target.id,
  targetPortId: input.id,
};

describe("isPortPairDocked", () => {
  it("requires a flush seam, matching port rows, and output-to-input direction", () => {
    expect(isPortPairDocked(source, output, target, input)).toBe(true);
    expect(isPortPairDocked(source, output, { ...target, col: 3 }, input)).toBe(
      false,
    );
    expect(isPortPairDocked(source, output, { ...target, row: 4 }, input)).toBe(
      false,
    );
    expect(isPortPairDocked(source, input, target, output)).toBe(false);
  });
});

describe("detectCellDockedJoins", () => {
  it("keeps exact joins out of the routing input and preserves their presentation metadata", () => {
    const docked = {
      ...pipe,
      enabled: false,
      projectionLabel: "field.name",
      conversionLabel: "2 conv",
    };
    const gappedCard = { ...target, id: "gapped", col: 3 };
    const gapped = { ...pipe, id: "separated", targetCardId: gappedCard.id };
    const missingPort = { ...pipe, id: "missing", targetPortId: "unknown" };

    expect(
      detectCellDockedJoins(
        {
          cards: [source, target, gappedCard],
          pipes: [gapped, docked, missingPort],
        },
        (type) => `color:${type}`,
      ),
    ).toEqual({
      dockedJoins: [
        {
          pipeId: "pipe",
          sourceCardId: "source",
          sourcePortId: "out",
          targetCardId: "target",
          targetPortId: "in",
          seamCol: 2,
          row: 4,
          seamPoint: { x: 50, y: 112.5 },
          color: "color:result",
          sequence: true,
          enabled: false,
          projectionLabel: "field.name",
          conversionLabel: "2 conv",
        },
      ],
      routablePipes: [gapped, missingPort],
      dockedPipeIds: new Set(["pipe"]),
    });
  });
});
