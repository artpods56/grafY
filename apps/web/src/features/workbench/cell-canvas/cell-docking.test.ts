import { describe, expect, it } from "vitest";
import {
  detectCellDockedJoins,
  findDockSnapCandidate,
  isPortPairDocked,
} from "./cell-docking";
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
          seamPoint: { x: 100, y: 225 },
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

describe("findDockSnapCandidate", () => {
  it("snaps a dragged source diagonally within the default threshold", () => {
    const dragged = { ...source, col: -2, row: 1 };
    expect(findDockSnapCandidate(dragged, [target], [pipe])).toEqual({
      col: -1,
      row: 2,
      matchedPipeIds: ["pipe"],
    });
    expect(findDockSnapCandidate(dragged, [target], [pipe], 0)).toBeNull();
  });

  it("snaps a dragged target and collects every pipe that fits the same placement", () => {
    const sourceWithTwoPorts = {
      ...source,
      ports: [output, { ...output, id: "out-2", rowOffset: 3 }],
    };
    const dragged = {
      ...target,
      col: 4,
      row: 2,
      ports: [input, { ...input, id: "in-2", rowOffset: 2 }],
    };
    const pipes = [
      pipe,
      { ...pipe, id: "pipe-2", sourcePortId: "out-2", targetPortId: "in-2" },
    ];

    expect(
      findDockSnapCandidate(dragged, [sourceWithTwoPorts], pipes, 2),
    ).toEqual({
      col: 2,
      row: 3,
      matchedPipeIds: ["pipe", "pipe-2"],
    });
    expect(
      findDockSnapCandidate(dragged, [sourceWithTwoPorts], pipes),
    ).toBeNull();
  });

  it("rejects a snap that would overlap an unrelated stationary card", () => {
    const dragged = { ...source, col: -2 };
    const obstacle = {
      ...target,
      id: "obstacle",
      col: 1,
      widthCells: 1,
      ports: [],
    };

    expect(
      findDockSnapCandidate(dragged, [target, obstacle], [pipe]),
    ).toBeNull();
  });

  it("uses Manhattan distance and then pipe order to break Chebyshev ties", () => {
    const dragged = { ...source, col: -2 };
    const otherPorts = {
      ...target,
      ports: [
        input,
        { ...input, id: "above", rowOffset: 0 },
        { ...input, id: "below", rowOffset: 2 },
      ],
    };
    const above = { ...pipe, id: "above-pipe", targetPortId: "above" };
    const below = { ...pipe, id: "below-pipe", targetPortId: "below" };

    expect(
      findDockSnapCandidate(dragged, [otherPorts], [above, below, pipe]),
    ).toEqual({
      col: -1,
      row: 2,
      matchedPipeIds: ["pipe"],
    });
    expect(
      findDockSnapCandidate(dragged, [otherPorts], [below, above]),
    ).toEqual({
      col: -1,
      row: 3,
      matchedPipeIds: ["below-pipe"],
    });
  });

  it("ignores pipes that use an input as a source", () => {
    const dragged: CellCardModel = {
      ...source,
      col: -2,
      ports: [{ ...output, direction: "input" }],
    };

    expect(findDockSnapCandidate(dragged, [target], [pipe])).toBeNull();
  });
});
