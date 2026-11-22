import { describe, expect, it } from "vitest";
import {
  DEFAULT_CANVAS_LAB,
  encodeCanvasLab,
  readCanvasLab,
} from "./canvas-lab";

describe("Canvas lab URLs", () => {
  it("round-trips every control in a stable order", () => {
    const settings = {
      material: "frost",
      well: "recessed",
      corners: "sharp",
      stackStyle: "deck",
      blur: 1.2,
      frost: 0.75,
      cardFill: 0.72,
      grid: false,
      pipe: "fibre",
      exits: "side",
      underCards: "avoid",
      depth: false,
    } satisfies typeof DEFAULT_CANVAS_LAB;
    const encoded = encodeCanvasLab(settings);
    expect(encoded).toBe(
      "1:glass:frost,well:recessed,corners:sharp,stack:deck,blur:1.2,frost:0.75,fill:72,grid:0,pipe:fibre,exits:side,under:avoid,depth:0",
    );
    expect(readCanvasLab(encoded)).toEqual(settings);
  });

  it("keeps defaults for unknown values and clamps finite numbers", () => {
    const overrides =
      "1:future:3,well:drilled,grid:false,depth:0,blur:99,frost:-1,fill:0";
    expect(readCanvasLab(overrides)).toEqual({
      ...DEFAULT_CANVAS_LAB,
      depth: false,
      blur: 12,
      frost: 0,
      cardFill: 0.2,
    });
    expect(readCanvasLab("2:well:punched")).toEqual(DEFAULT_CANVAS_LAB);
    expect(
      readCanvasLab("1:blur:,frost:Infinity,fill:0x80,well:flat:invalid"),
    ).toEqual(DEFAULT_CANVAS_LAB);
  });

  it("uses the saved grid preference until the URL overrides it", () => {
    const saved = { ...DEFAULT_CANVAS_LAB, grid: false };
    expect(readCanvasLab("1", saved).grid).toBe(false);
    const explicit = encodeCanvasLab({ ...saved, grid: true }, saved);
    expect(explicit).toBe("1:grid:1");
    expect(readCanvasLab(explicit, saved).grid).toBe(true);
  });
});
