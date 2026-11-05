import { describe, expect, it } from "vitest";

import {
  cellViews,
  defaultTextCardView,
  prettyCellJson,
  textCardViews,
} from "./cell-views";

describe("cellViews", () => {
  it("offers Markdown for any text and nothing more for plain prose", () => {
    expect(cellViews("| a | b |\n| - | - |")).toEqual(["text", "markdown"]);
  });

  it("offers JSON only for a value that parses to an object or array", () => {
    expect(cellViews('{"a": 1}')).toContain("json");
    expect(cellViews(" [1, 2]")).toContain("json");
    expect(cellViews("{not json")).not.toContain("json");
    expect(cellViews("12")).not.toContain("json");
    expect(cellViews({ a: 1 })).toEqual(["text", "json"]);
  });

  it("offers the rendered table only for a whole HTML table", () => {
    expect(cellViews('<table class="x"><tr><td>1</td></tr></table>')).toContain(
      "html",
    );
    expect(cellViews("a <table> mentioned in prose")).not.toContain("html");
  });

  it("leaves a number or an empty cell as text", () => {
    expect(cellViews(12)).toEqual(["text"]);
    expect(cellViews(null)).toEqual(["text"]);
  });
});

describe("prettyCellJson", () => {
  it("indents stored JSON text and structured values alike", () => {
    expect(prettyCellJson('{"a":[1]}')).toBe('{\n  "a": [\n    1\n  ]\n}');
    expect(prettyCellJson({ a: 1 })).toBe('{\n  "a": 1\n}');
  });

  it("answers null for anything else", () => {
    expect(prettyCellJson("hello")).toBeNull();
    expect(prettyCellJson(null)).toBeNull();
  });
});

describe("text cards", () => {
  it("offers no switch for JSON, which already reads as indented text", () => {
    expect(textCardViews('{"a": 1}')).toEqual([]);
    expect(textCardViews("# Hi")).toEqual(["text", "markdown"]);
  });

  it("opens on a table it holds, then on what the artifact says it is", () => {
    const table = textCardViews("<table><tr><td>1</td></tr></table>");
    expect(defaultTextCardView(table, "scalar.text")).toBe("html");
    const words = textCardViews("# Hi");
    expect(defaultTextCardView(words, "text.markdown")).toBe("markdown");
    expect(defaultTextCardView(words, "scalar.text")).toBe("text");
    expect(defaultTextCardView([], "text.markdown")).toBe("text");
  });
});
