import { describe, expect, it } from "vitest";

import {
  createTableEditorState,
  formatCellInput,
  parseCellInput,
  parseTablePayload,
  reduceTableEditor,
  tableEditorPayload,
} from "./table-editor-reducer";

function apply(
  state: ReturnType<typeof createTableEditorState>,
  actions: Parameters<typeof reduceTableEditor>[1][],
) {
  return actions.reduce(reduceTableEditor, state);
}

describe("parseTablePayload", () => {
  it("fills missing cells and drops unknown columns", () => {
    const snapshot = parseTablePayload({
      columns: [
        { id: "name", title: "Name", value_type: "text" },
        { id: "age", title: "Age", value_type: "integer" },
      ],
      rows: [{ name: "Ada", extra: "nope" }, { age: 36 }],
    });
    expect(snapshot.columns).toEqual([
      { id: "name", title: "Name", value_type: "text" },
      { id: "age", title: "Age", value_type: "integer" },
    ]);
    expect(snapshot.rows).toEqual([
      { name: "Ada", age: null },
      { name: null, age: 36 },
    ]);
  });

  it("starts a one-column table when the payload has no columns", () => {
    expect(parseTablePayload({}).columns).toEqual([
      { id: "column_1", title: "Column 1", value_type: "text" },
    ]);
  });
});

describe("reduceTableEditor", () => {
  it("edits cells, adds rows and columns, and serializes table.data@1", () => {
    const next = apply(createTableEditorState(), [
      { type: "set-cell", row: 0, columnId: "column_1", value: "Ada" },
      { type: "add-row" },
      { type: "add-column", title: "Age", value_type: "integer" },
      { type: "set-cell", row: 1, columnId: "column_2", value: 36 },
    ]);
    expect(tableEditorPayload(next)).toEqual({
      columns: [
        { id: "column_1", title: "Column 1", value_type: "text" },
        { id: "column_2", title: "Age", value_type: "integer" },
      ],
      rows: [
        { column_1: "Ada", column_2: null },
        { column_1: null, column_2: 36 },
      ],
    });
  });

  it("renames and deletes columns, and will not delete the last column", () => {
    const started = apply(createTableEditorState(), [
      { type: "add-column", title: "Age" },
      { type: "rename-column", columnId: "column_1", title: "Name" },
    ]);
    const deleted = reduceTableEditor(started, {
      type: "delete-column",
      columnId: "column_2",
    });
    expect(deleted.columns).toEqual([
      { id: "column_1", title: "Name", value_type: "text" },
    ]);
    expect(
      reduceTableEditor(deleted, {
        type: "delete-column",
        columnId: "column_1",
      }),
    ).toBe(deleted);
  });

  it("undoes the last change and reset restores the initial payload", () => {
    const initial = createTableEditorState({
      columns: [{ id: "name", title: "Name", value_type: "text" }],
      rows: [{ name: "Ada" }],
    });
    const edited = reduceTableEditor(initial, {
      type: "set-cell",
      row: 0,
      columnId: "name",
      value: "Grace",
    });
    expect(edited.rows[0]?.name).toBe("Grace");
    expect(reduceTableEditor(edited, { type: "undo" }).rows[0]?.name).toBe(
      "Ada",
    );
    const reset = reduceTableEditor(
      reduceTableEditor(edited, { type: "add-row" }),
      { type: "reset" },
    );
    expect(tableEditorPayload(reset)).toEqual({
      columns: [{ id: "name", title: "Name", value_type: "text" }],
      rows: [{ name: "Ada" }],
    });
    expect(reset.past).toEqual([]);
  });
});

describe("parseCellInput", () => {
  it("parses typed values and leaves invalid input as text", () => {
    expect(parseCellInput("12", "integer")).toBe(12);
    expect(parseCellInput("12.5", "integer")).toBe("12.5");
    expect(parseCellInput("true", "boolean")).toBe(true);
    expect(parseCellInput("", "text")).toBeNull();
    expect(formatCellInput(null)).toBe("");
    expect(formatCellInput({ a: 1 })).toBe('{"a":1}');
  });
});
