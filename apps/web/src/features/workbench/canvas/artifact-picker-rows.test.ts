import { expect, it } from "vitest";

import type { TableSchema } from "@/lib/api";

import { pickerColumns, pickerPreview } from "./artifact-picker-rows";

const column = (id: string, value_type: string) =>
  ({ id, title: id, value_type }) as TableSchema["columns"][number];

it("picks by the column named text, labelled by another text column", () => {
  const picked = pickerColumns([
    column("page", "integer"),
    column("kind", "text"),
    column("text", "text"),
  ]);
  expect(picked?.content.id).toBe("text");
  expect(picked?.label?.id).toBe("kind");
});

it("falls back to the first text column, with no label when it is the only one", () => {
  const picked = pickerColumns([
    column("n", "integer"),
    column("note", "text"),
  ]);
  expect(picked?.content.id).toBe("note");
  expect(picked?.label).toBeNull();
});

it("offers nothing for a table with no text", () => {
  expect(pickerColumns([column("n", "integer")])).toBeNull();
});

it("reads a cell as one line without its markup, even one cut mid-tag", () => {
  expect(pickerPreview("<table><tr><th>A</th>\n<td>B</td></tr><td cl")).toBe(
    "A B",
  );
  expect(pickerPreview(3)).toBe("");
});
