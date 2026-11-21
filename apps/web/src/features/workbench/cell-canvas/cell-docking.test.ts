import { describe, expect, it } from "vitest";
import { detectCellDockedJoins, isPortPairDocked } from "./cell-docking";
import {
  ARTIFACT_CARD_OUTPUT_PORT_ID,
  type CellCardModel,
  type CellPipeModel,
  type CellPort,
} from "./cell-model";

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

  it("leaves an artifact's punched corner output to route, not dock, on a flush neighbour", () => {
    const corner: CellPort = { ...output, id: ARTIFACT_CARD_OUTPUT_PORT_ID };
    const artifact = { ...source, ports: [corner] };
    const fromCorner = { ...pipe, sourcePortId: corner.id };
    const graph = { cards: [artifact, target], pipes: [fromCorner] };

    // In the gutter the port is on its row: it docks.
    expect(detectCellDockedJoins(graph, () => "c").dockedPipeIds).toEqual(
      new Set(["pipe"]),
    );
    // Punched, it sits in the corner off the row's midline: it routes.
    const punched = detectCellDockedJoins(graph, () => "c", { punched: true });
    expect(punched.dockedJoins).toEqual([]);
    expect(punched.routablePipes).toEqual([fromCorner]);
  });

  it("still docks a punched port that sits on its row's midline", () => {
    const graph = { cards: [source, target], pipes: [pipe] };
    expect(
      detectCellDockedJoins(graph, () => "c", { punched: true }).dockedPipeIds,
    ).toEqual(new Set(["pipe"]));
  });
});

describe("ports that share an id across directions", () => {
  it("docks the input and output named alike on their own sides", () => {
    const imageIn: CellPort = { ...input, id: "image" };
    const imageOut: CellPort = { ...output, id: "image", rowOffset: 1 };
    const editor: CellCardModel = {
      ...target,
      id: "editor",
      // Input listed after the output, so a bare-id lookup finds the output.
      ports: [imageOut, imageIn],
    };
    const sink: CellCardModel = {
      ...target,
      id: "sink",
      col: editor.col + editor.widthCells + 2,
      ports: [{ ...input, rowOffset: 1 }],
    };
    const into = { ...pipe, targetCardId: "editor", targetPortId: "image" };
    const outof = {
      ...pipe,
      id: "outof",
      sourceCardId: "editor",
      sourcePortId: "image",
      targetCardId: "sink",
    };
    const result = detectCellDockedJoins(
      { cards: [source, editor, sink], pipes: [into, outof] },
      () => "c",
    );
    // `source`'s output meets `editor`'s input flush; `sink` is two cells off.
    expect(result.dockedPipeIds).toEqual(new Set(["pipe"]));
    expect(result.routablePipes).toEqual([outof]);
  });
});
