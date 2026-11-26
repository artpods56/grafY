import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  CellSelectionLinkLayer,
  type CellSelectionLinkLine,
} from "./CellSelectionLinkLayer";
import type { CellCardModel } from "./cell-model";

function card(
  id: string,
  col: number,
  row: number,
  widthCells: number,
  heightCells: number,
): CellCardModel {
  return {
    id,
    title: id,
    subtitle: "",
    col,
    row,
    widthCells,
    heightCells,
    ports: [],
  };
}

function line(
  id: string,
  sourceCardId: string,
  targetCardId: string,
): CellSelectionLinkLine {
  return { id, sourceCardId, targetCardId };
}

function markup(
  cards: readonly CellCardModel[],
  lines: readonly CellSelectionLinkLine[],
): string {
  return renderToStaticMarkup(
    <CellSelectionLinkLayer cards={cards} lines={lines} />,
  );
}

function tagWith(html: string, attribute: string, value: string): string {
  const match = new RegExp(`<[a-z]+[^>]*${attribute}="${value}"[^>]*>`).exec(
    html,
  );
  expect(match, `${attribute}="${value}"`).not.toBeNull();
  return match?.[0] ?? "";
}

function attr(tag: string, name: string): string {
  const match = new RegExp(`${name}="([^"]*)"`).exec(tag);
  expect(match, name).not.toBeNull();
  return match?.[1] ?? "";
}

describe("CellSelectionLinkLayer", () => {
  it("joins side-by-side cards from the source's right middle to the target's left middle", () => {
    // Source 4×2 at (0, 0): right middle (100, 25).
    // Target 4×4 at column 6: left middle (150, 50).
    const html = markup(
      [card("source", 0, 0, 4, 2), card("target", 6, 0, 4, 4)],
      [line("link-1", "source", "target")],
    );
    const drawn = tagWith(html, "data-selection-link", "link-1");
    expect(attr(drawn, "x1")).toBe("100");
    expect(attr(drawn, "y1")).toBe("25");
    expect(attr(drawn, "x2")).toBe("150");
    expect(attr(drawn, "y2")).toBe("50");
    expect(attr(drawn, "stroke-opacity")).toBe("0.75");
    expect(attr(drawn, "stroke-width")).toBe("1.5");
    expect(attr(drawn, "stroke-dasharray")).toBe("5 5");
    expect(attr(drawn, "stroke-linecap")).toBe("round");
    expect(attr(drawn, "vector-effect")).toBe("non-scaling-stroke");
    const dot = html.match(/<circle\b[^>]*>/)?.[0] ?? "";
    expect(attr(dot, "cx")).toBe("150");
    expect(attr(dot, "cy")).toBe("50");
    expect(attr(dot, "r")).toBe("3");
    expect(html).toContain('data-selection-links="true"');
    expect(html).toContain('aria-hidden="true"');
  });

  it("joins stacked cards from the source's bottom middle to the target's top middle", () => {
    // Source 4×2 at (0, 0): bottom middle (50, 50).
    // Target 8×2 at row 4: top middle (100, 100).
    const html = markup(
      [card("source", 0, 0, 4, 2), card("target", 0, 4, 8, 2)],
      [line("link-1", "source", "target")],
    );
    const drawn = tagWith(html, "data-selection-link", "link-1");
    expect(attr(drawn, "x1")).toBe("50");
    expect(attr(drawn, "y1")).toBe("50");
    expect(attr(drawn, "x2")).toBe("100");
    expect(attr(drawn, "y2")).toBe("100");
    const dot = html.match(/<circle\b[^>]*>/)?.[0] ?? "";
    expect(attr(dot, "cx")).toBe("100");
    expect(attr(dot, "cy")).toBe("100");
  });

  it("uses the facing side when the target sits to the left or above", () => {
    const left = markup(
      [card("source", 6, 0, 4, 2), card("target", 0, 0, 4, 2)],
      [line("link-1", "source", "target")],
    );
    const across = tagWith(left, "data-selection-link", "link-1");
    expect(attr(across, "x1")).toBe("150");
    expect(attr(across, "y1")).toBe("25");
    expect(attr(across, "x2")).toBe("100");
    expect(attr(across, "y2")).toBe("25");

    const above = markup(
      [card("source", 0, 4, 4, 2), card("target", 0, 0, 4, 2)],
      [line("link-1", "source", "target")],
    );
    const up = tagWith(above, "data-selection-link", "link-1");
    expect(attr(up, "x1")).toBe("50");
    expect(attr(up, "y1")).toBe("100");
    expect(attr(up, "x2")).toBe("50");
    expect(attr(up, "y2")).toBe("50");
  });

  it("skips a line whose card is missing", () => {
    const html = markup(
      [card("source", 0, 0, 4, 2), card("target", 6, 0, 4, 2)],
      [line("missing", "source", "gone"), line("kept", "source", "target")],
    );
    expect(html).not.toContain('data-selection-link="missing"');
    expect(html).toContain('data-selection-link="kept"');
    expect(html.match(/<line\b/g)).toHaveLength(1);
  });

  it("renders nothing when no line has both cards", () => {
    const source = card("source", 0, 0, 4, 2);
    const target = card("target", 6, 0, 4, 2);
    expect(markup([source, target], [])).toBe("");
    expect(markup([], [line("link-1", "source", "target")])).toBe("");
    expect(markup([source], [line("link-1", "source", "gone")])).toBe("");
  });
});
