import { describe, expect, it } from "vitest";

import { schemaFields, validateConfig } from "./config-schema";

const boundsItems = [
  {
    type: "number",
    title: "West longitude",
    minimum: -180,
    maximum: 180,
  },
  {
    type: "number",
    title: "South latitude",
    minimum: -90,
    maximum: 90,
  },
  {
    type: "number",
    title: "East longitude",
    minimum: -180,
    maximum: 180,
  },
  {
    type: "number",
    title: "North latitude",
    minimum: -90,
    maximum: 90,
  },
] as const;

const boundsDescription =
  "WGS84 bounds ordered as west longitude, south latitude, east longitude, north latitude.";

describe("schemaFields", () => {
  it("exposes a required fixed numeric tuple as one editable field", () => {
    expect(
      schemaFields({
        type: "object",
        properties: {
          bounds: {
            type: "array",
            title: "Bounds",
            description: boundsDescription,
            prefixItems: boundsItems,
            minItems: 4,
            maxItems: 4,
          },
        },
        required: ["bounds"],
      }),
    ).toEqual([
      {
        name: "bounds",
        title: "Bounds",
        description: boundsDescription,
        type: "number-tuple",
        items: boundsItems,
        required: true,
        nullable: false,
      },
    ]);
  });

  it("unwraps Pydantic's nullable tuple and retains branch metadata", () => {
    expect(
      schemaFields({
        type: "object",
        properties: {
          initial_bounds: {
            title: "Initial Bounds",
            default: null,
            anyOf: [
              {
                type: "array",
                description: boundsDescription,
                prefixItems: boundsItems,
                minItems: 4,
                maxItems: 4,
              },
              { type: "null" },
            ],
          },
        },
      }),
    ).toEqual([
      {
        name: "initial_bounds",
        title: "Initial Bounds",
        description: boundsDescription,
        type: "number-tuple",
        items: boundsItems,
        required: false,
        nullable: true,
      },
    ]);
  });

  it("keeps scalar and string-list fields and ignores unsupported arrays", () => {
    expect(
      schemaFields({
        type: "object",
        properties: {
          title: { type: "string", minLength: 1 },
          opacity: {
            anyOf: [
              { type: "number", minimum: 0, maximum: 1 },
              { type: "null" },
            ],
          },
          tags: {
            type: "array",
            items: { type: "string", minLength: 1, maxLength: 255 },
            maxItems: 8,
          },
          uneven: {
            type: "array",
            prefixItems: [{ type: "number" }, { type: "string" }],
            minItems: 2,
            maxItems: 2,
          },
          malformed_union: {
            anyOf: [{ type: "number" }, { type: "null" }, 42],
          },
        },
        required: ["title"],
      }),
    ).toEqual([
      {
        name: "title",
        title: "title",
        description: undefined,
        type: "string",
        enumValues: undefined,
        format: undefined,
        codeLanguage: undefined,
        minimum: undefined,
        maximum: undefined,
        minLength: 1,
        maxLength: undefined,
        pattern: undefined,
        required: true,
        nullable: false,
      },
      {
        name: "opacity",
        title: "opacity",
        description: undefined,
        type: "number",
        enumValues: undefined,
        format: undefined,
        codeLanguage: undefined,
        minimum: 0,
        maximum: 1,
        minLength: undefined,
        maxLength: undefined,
        pattern: undefined,
        required: false,
        nullable: true,
      },
      {
        name: "tags",
        title: "tags",
        description: undefined,
        type: "string-list",
        minItems: undefined,
        maxItems: 8,
        itemMinLength: 1,
        itemMaxLength: 255,
        itemPattern: undefined,
        required: false,
        nullable: false,
      },
    ]);
  });

  it("marks SQL textarea fields as code without changing prose textareas", () => {
    expect(
      schemaFields({
        type: "object",
        properties: {
          sql: {
            type: "string",
            format: "textarea",
            contentMediaType: "application/sql",
          },
          notes: {
            type: "string",
            format: "textarea",
          },
        },
      }),
    ).toEqual([
      expect.objectContaining({
        name: "sql",
        format: "textarea",
        codeLanguage: "sql",
      }),
      expect.objectContaining({
        name: "notes",
        format: "textarea",
        codeLanguage: undefined,
      }),
    ]);
  });
});

describe("validateConfig", () => {
  const schema = {
    type: "object",
    additionalProperties: false,
    properties: {
      mode: { type: "string", enum: ["fast", "safe"] },
      count: { type: "integer", minimum: 1, maximum: 4 },
    },
    required: ["mode", "count"],
  };

  it("reports missing, stale enum, scalar type, numeric bound, and forbidden keys", () => {
    expect(
      validateConfig(schema, {
        mode: "legacy",
        count: 5,
        extra: true,
      }),
    ).toEqual([
      { fieldName: "mode", message: "Choose one of the allowed values." },
      { fieldName: "count", message: "Must be at most 4." },
      { fieldName: "extra", message: "This key is not allowed." },
    ]);
    expect(validateConfig(schema, { mode: "safe", count: "2" })).toEqual([
      { fieldName: "count", message: "Expected integer." },
    ]);
    expect(validateConfig(schema, { mode: "safe" })).toEqual([
      { fieldName: "count", message: "This field is required." },
    ]);
  });

  it("allows extra keys when additionalProperties is omitted or true", () => {
    expect(
      validateConfig(
        { type: "object", properties: { name: { type: "string" } } },
        { name: "valid", extension: 3 },
      ),
    ).toEqual([]);
    expect(
      validateConfig(
        { ...schema, additionalProperties: true },
        { mode: "safe", count: 2, extension: 3 },
      ),
    ).toEqual([]);
  });

  it("resolves references and nullable unions while keeping optional null values valid", () => {
    const referencedSchema = {
      $defs: {
        Mode: { type: "string", enum: ["safe", "fast"] },
        Limit: { type: "integer", minimum: 1, maximum: 8 },
      },
      type: "object",
      properties: {
        mode: { $ref: "#/$defs/Mode" },
        limit: { anyOf: [{ $ref: "#/$defs/Limit" }, { type: "null" }] },
      },
      required: ["mode"],
    };

    expect(
      validateConfig(referencedSchema, { mode: "safe", limit: null }),
    ).toEqual([]);
    expect(validateConfig(referencedSchema, { mode: "old", limit: 9 })).toEqual(
      [
        { fieldName: "mode", message: "Choose one of the allowed values." },
        { fieldName: "limit", message: "Must be at most 8." },
      ],
    );
    expect(validateConfig(referencedSchema, {})).toEqual([
      { fieldName: "mode", message: "This field is required." },
    ]);
  });

  it("rejects values outside emitted single Literal const constraints", () => {
    const literalSchema = {
      type: "object",
      properties: {
        mode: { const: "fast", type: "string", title: "Mode" },
        empty: { const: null },
        enabled: { const: false, type: "boolean" },
      },
    };

    expect(
      validateConfig(literalSchema, {
        mode: "retired",
        empty: "",
        enabled: true,
      }),
    ).toEqual([
      { fieldName: "mode", message: "Use the required literal value." },
      { fieldName: "empty", message: "Use the required literal value." },
      { fieldName: "enabled", message: "Use the required literal value." },
    ]);
    expect(
      validateConfig(literalSchema, {
        mode: "fast",
        empty: null,
        enabled: false,
      }),
    ).toEqual([]);
  });

  it("selects emitted discriminated union branches using their literal values", () => {
    const unionSchema = {
      $defs: {
        Fast: {
          type: "object",
          properties: { kind: { const: "fast", type: "string" } },
          required: ["kind"],
          additionalProperties: false,
        },
        Safe: {
          type: "object",
          properties: { kind: { const: "safe", type: "string" } },
          required: ["kind"],
          additionalProperties: false,
        },
      },
      type: "object",
      properties: {
        policy: {
          discriminator: {
            propertyName: "kind",
            mapping: { fast: "#/$defs/Fast", safe: "#/$defs/Safe" },
          },
          oneOf: [{ $ref: "#/$defs/Fast" }, { $ref: "#/$defs/Safe" }],
        },
      },
      required: ["policy"],
    };

    expect(validateConfig(unionSchema, { policy: { kind: "fast" } })).toEqual(
      [],
    );
    expect(validateConfig(unionSchema, { policy: { kind: "safe" } })).toEqual(
      [],
    );
    expect(
      validateConfig(unionSchema, { policy: { kind: "retired" } }),
    ).toEqual([
      { fieldName: "policy", message: "Use the required literal value." },
    ]);
    expect(
      validateConfig(unionSchema, { policy: { kind: "fast", extra: true } }),
    ).toEqual([{ fieldName: "extra", message: "This key is not allowed." }]);
  });

  it("distinguishes optional omission, explicit null, and required nullable fields", () => {
    const presenceSchema = {
      type: "object",
      properties: {
        note: { type: "string" },
        limit: { anyOf: [{ type: "integer" }, { type: "null" }] },
      },
      required: ["limit"],
    };

    expect(validateConfig(presenceSchema, { limit: null })).toEqual([]);
    expect(validateConfig(presenceSchema, { note: null, limit: null })).toEqual(
      [{ fieldName: "note", message: "Expected string." }],
    );
    expect(validateConfig(presenceSchema, {})).toEqual([
      { fieldName: "limit", message: "This field is required." },
    ]);
  });

  it("enforces local ref siblings, union alternatives, and schema-valued extra keys", () => {
    const siblingSchema = {
      $defs: { Limit: { type: "integer", minimum: 1 } },
      type: "object",
      properties: {
        limit: { $ref: "#/$defs/Limit", maximum: 5 },
        choice: {
          anyOf: [{ type: "string", enum: ["auto"] }, { type: "boolean" }],
        },
      },
      additionalProperties: { type: "string" },
    };

    expect(
      validateConfig(siblingSchema, { limit: 5, choice: "auto", extra: "ok" }),
    ).toEqual([]);
    expect(validateConfig(siblingSchema, { limit: 1, choice: false })).toEqual(
      [],
    );
    expect(validateConfig(siblingSchema, { limit: 0 })).toEqual([
      { fieldName: "limit", message: "Must be at least 1." },
    ]);
    expect(
      validateConfig(siblingSchema, { limit: 6, choice: "retired", extra: 3 }),
    ).toEqual([
      { fieldName: "limit", message: "Must be at most 5." },
      { fieldName: "choice", message: "Choose one of the allowed values." },
      { fieldName: "extra", message: "Expected string." },
    ]);
  });
});
