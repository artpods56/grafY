import { describe, expect, it } from "vitest";

import {
  createSchemaBuilderField,
  moveSchemaBuilderField,
  schemaBuilderFields,
  schemaFieldConsumesInput,
  withSchemaFieldKind,
} from "./schema-builder";

describe("Schema Builder fields", () => {
  it("keeps valid persisted identities and rejects malformed or duplicate rows", () => {
    expect(
      schemaBuilderFields([
        {
          id: "customer",
          name: "customer",
          kind: "schema",
          required: true,
          description: "Nested customer",
        },
        {
          id: "lines",
          name: "lines",
          kind: "sequence",
          item_kind: "schema",
          required: true,
          description: "Invoice lines",
        },
        {
          id: "customer",
          name: "duplicate",
          kind: "string",
          required: false,
          description: "",
        },
        { id: "broken", name: "broken", kind: "sequence" },
      ]),
    ).toEqual([
      {
        id: "customer",
        name: "customer",
        kind: "schema",
        required: true,
        description: "Nested customer",
      },
      {
        id: "lines",
        name: "lines",
        kind: "sequence",
        item_kind: "schema",
        required: true,
        description: "Invoice lines",
      },
    ]);
  });

  it("creates deterministic field names while accepting a caller-owned id", () => {
    expect(createSchemaBuilderField(2, "stable-id")).toEqual({
      id: "stable-id",
      name: "field_3",
      kind: "string",
      required: false,
      description: "",
    });
  });

  it("exposes an input only for nested schemas", () => {
    const primitive = createSchemaBuilderField(0, "primitive");
    const nested = withSchemaFieldKind(primitive, "schema");
    const sequence = {
      ...withSchemaFieldKind(primitive, "sequence"),
      item_kind: "schema" as const,
    };

    expect(schemaFieldConsumesInput(primitive)).toBe(false);
    expect(schemaFieldConsumesInput(nested)).toBe(true);
    expect(schemaFieldConsumesInput(sequence)).toBe(true);
  });

  it("moves fields without changing their identities", () => {
    const fields = [
      createSchemaBuilderField(0, "a"),
      createSchemaBuilderField(1, "b"),
      createSchemaBuilderField(2, "c"),
    ];

    expect(
      moveSchemaBuilderField(fields, "c", 0).map((field) => field.id),
    ).toEqual(["c", "a", "b"]);
    expect(fields.map((field) => field.id)).toEqual(["a", "b", "c"]);
  });
});
