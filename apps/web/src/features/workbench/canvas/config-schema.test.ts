import { describe, expect, it } from "vitest";

import {
  buildDefaultForField,
  evaluateVisibleWhen,
  schemaFields,
  validateConfig,
  visibleSchemaFields,
  type VisibleWhenPredicate,
} from "./config-schema";

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
        defaultValue: null,
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

  it("keeps a declared textarea format on a string field", () => {
    expect(
      schemaFields({
        type: "object",
        properties: {
          notes: {
            type: "string",
            format: "textarea",
          },
          title: {
            type: "string",
          },
        },
      }),
    ).toEqual([
      expect.objectContaining({
        name: "notes",
        format: "textarea",
      }),
      expect.objectContaining({
        name: "title",
        format: undefined,
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
    // A nested problem belongs to the top-level field the card can show it on.
    expect(
      validateConfig(unionSchema, { policy: { kind: "fast", extra: true } }),
    ).toEqual([{ fieldName: "policy", message: "This key is not allowed." }]);
    expect(validateConfig(unionSchema, { policy: {} })).toEqual([
      { fieldName: "policy", message: "This field is required." },
    ]);
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

describe("config schema metadata", () => {
  it("merges ref siblings with inherited constraints and honors explicit hiding", () => {
    const schema = {
      $defs: {
        Limit: {
          type: "integer",
          title: "Inherited",
          minimum: 10,
          maximum: 128,
        },
        Alias: { $ref: "#/$defs/Limit", description: "Maximum output length" },
        Secret: { type: "string", "x-grafy-hidden": true },
      },
      properties: {
        max_completion_tokens: {
          $ref: "#/$defs/Alias",
          title: "Output tokens",
          minimum: 1,
          default: 16,
          examples: [24],
          "x-grafy-widget": "slider",
          "x-grafy-group": "Generation",
        },
        credential: { $ref: "#/$defs/Secret" },
        ignored: { $ref: "#/$defs/Limit", "x-grafy-hidden": true },
        resolution: {
          type: "string",
          enum: ["nearest", "linear"],
          "x-grafy-enum-labels": { nearest: "Nearest", linear: "Linear" },
          "x-grafy-widget": "segmented",
        },
      },
    };

    expect(schemaFields(schema)).toEqual([
      expect.objectContaining({
        name: "max_completion_tokens",
        type: "integer",
        title: "Output tokens",
        description: "Maximum output length",
        defaultValue: 16,
        examples: [24],
        minimum: 1,
        maximum: 128,
        widget: "slider",
        group: "Generation",
      }),
      expect.objectContaining({
        name: "resolution",
        enumLabels: { nearest: "Nearest", linear: "Linear" },
        widget: "segmented",
      }),
    ]);
    expect(validateConfig(schema, { max_completion_tokens: 3 })).toEqual([]);
    expect(validateConfig(schema, { max_completion_tokens: 0 })).toEqual([
      { fieldName: "max_completion_tokens", message: "Must be at least 1." },
    ]);
  });

  it("bounds parsing of recursive objects and reference chains", () => {
    const schema = {
      $defs: {
        A: { $ref: "#/$defs/B" },
        B: { $ref: "#/$defs/A", type: "string" },
        Tree: {
          type: "object",
          properties: { child: { $ref: "#/$defs/Tree" } },
        },
      },
      properties: {
        alias: { $ref: "#/$defs/A" },
        tree: { $ref: "#/$defs/Tree" },
      },
    };

    const [alias, tree] = schemaFields(schema);
    expect(alias?.type).toBe("string");
    expect(validateConfig(schema, { alias: 7 })).toEqual([
      { fieldName: "alias", message: "Expected string." },
    ]);
    let depth = 0;
    let current = tree;
    while (current?.type === "object") {
      depth += 1;
      current = current.fields[0];
    }
    expect(depth).toBe(8);
  });

  it("ignores malformed visibility and presentation metadata", () => {
    const [field] = schemaFields({
      properties: {
        sample: {
          type: "integer",
          "x-grafy-widget": "unknown",
          "x-grafy-group": " ",
          "x-grafy-enum-labels": { one: 1 },
          "x-grafy-visible-when": {
            all: [
              { field: "enabled", truthy: true },
              { portArtifactType: { port: "input", in: [8] } },
            ],
          },
        },
      },
    });
    expect(field).toMatchObject({ name: "sample", type: "integer" });
    for (const key of ["widget", "group", "enumLabels", "visibleWhen"]) {
      expect(field).not.toHaveProperty(key);
    }
  });
});

describe("config field visibility", () => {
  const context = {
    config: {
      mode: { b: [1, false], a: "x" },
      disabled: false,
      empty: [],
      unset: null,
    },
    connectedPorts: {
      input: { connected: true, artifactTypeKey: "geo.vector@2" },
      unknown: { connected: true, artifactTypeKey: null },
      missing: { connected: false, artifactTypeKey: "geo.vector@2" },
    },
  };
  const mode = { a: "x", b: [1, false] };
  const cases: [VisibleWhenPredicate, boolean][] = [
    [{ field: "mode", eq: mode }, true],
    [{ field: "mode", neq: mode }, false],
    [{ field: "mode", in: [false, mode] }, true],
    [{ field: "unset", eq: null }, true],
    [{ field: "defaulted", eq: "fallback" }, true],
    [{ field: "empty", truthy: false }, true],
    [{ field: "missing", truthy: true }, false],
    [{ field: "disabled", truthy: false }, true],
    [{ field: "mode", truthy: true }, true],
    [{ portConnected: "input" }, true],
    [{ portConnected: "unknown" }, true],
    [{ portConnected: "unlisted", is: false }, true],
    [
      {
        portArtifactType: {
          port: "input",
          in: ["geo.vector@2"],
          notIn: ["geo.vector@1"],
        },
      },
      true,
    ],
    [
      {
        portArtifactType: {
          port: "input",
          in: ["geo.vector@2"],
          notIn: ["geo.vector@2"],
        },
      },
      false,
    ],
    [{ portArtifactType: { port: "input", in: ["geo.vector@1"] } }, false],
    [{ portArtifactType: { port: "unknown", in: ["geo.vector@2"] } }, false],
    [{ portArtifactType: { port: "missing", notIn: ["geo.vector@2"] } }, true],
    [
      {
        portArtifactType: {
          port: "missing",
          notIn: ["geo.vector@2"],
          whenUnconnected: "hide",
        },
      },
      false,
    ],
    [
      {
        portArtifactType: {
          port: "missing",
          in: ["geo.vector@2"],
          whenUnconnected: "show",
        },
      },
      true,
    ],
    [
      {
        all: [
          { portConnected: "input" },
          { not: { field: "disabled", truthy: true } },
        ],
      },
      true,
    ],
    [
      {
        any: [{ portConnected: "missing" }, { field: "empty", truthy: false }],
      },
      true,
    ],
    [
      { any: [{ portConnected: "missing" }, { field: "empty", truthy: true }] },
      false,
    ],
  ];
  it.each(cases)("evaluates %j as %s", (predicate, expected) => {
    expect(
      evaluateVisibleWhen(predicate, context, {
        unset: "fallback",
        defaulted: "fallback",
      }),
    ).toBe(expected);
  });

  it("uses sibling defaults and reveals hidden fields with validation errors", () => {
    const schema = {
      properties: {
        mode: { type: "string", default: "manual" },
        count: {
          type: "integer",
          minimum: 1,
          "x-grafy-visible-when": {
            all: [
              { field: "mode", eq: "manual" },
              { not: { portConnected: "upstream" } },
            ],
          },
        },
      },
    };
    const fields = schemaFields(schema);
    expect(
      visibleSchemaFields(fields, { config: {} }).map(({ name }) => name),
    ).toEqual(["mode", "count"]);
    const config = { mode: "automatic", count: 0 };
    expect(
      visibleSchemaFields(fields, { config }).map(({ name }) => name),
    ).toEqual(["mode"]);
    expect(
      visibleSchemaFields(
        fields,
        { config },
        validateConfig(schema, config),
      ).map(({ name }) => name),
    ).toEqual(["mode", "count"]);
  });
});

describe("recursive config fields", () => {
  const schema = {
    $defs: {
      GeoRasterStyle: {
        type: "object",
        title: "GeoRasterStyle",
        properties: {
          kind: { const: "raster", type: "string" },
          opacity: {
            type: "number",
            exclusiveMinimum: 0,
            exclusiveMaximum: 1,
            examples: [0.75],
          },
          resampling: { type: "string", enum: ["linear", "nearest"] },
        },
        required: ["kind", "opacity", "resampling"],
      },
      GeoFeatureStyle: {
        discriminator: { propertyName: "kind" },
        oneOf: [
          { $ref: "#/$defs/GeoCategorizedPointStyle" },
          { $ref: "#/$defs/GeoVectorStyle" },
        ],
        "x-grafy-enum-labels": { categorized_points: "By category" },
      },
      GeoVectorStyle: {
        type: "object",
        title: "Vector",
        properties: { kind: { const: "vector" } },
        required: ["kind"],
      },
      GeoCategorizedPointStyle: {
        type: "object",
        properties: {
          kind: { const: "categorized_points" },
          categories: {
            type: "array",
            items: { $ref: "#/$defs/GeoPointCategory" },
            minItems: 2,
            maxItems: 128,
          },
        },
        required: ["kind", "categories"],
      },
      GeoPointCategory: {
        type: "object",
        title: "Category",
        properties: {
          id: {
            type: "string",
            pattern: "^[A-Za-z][A-Za-z0-9_-]*$",
            "x-grafy-auto-id": true,
          },
          enabled: { const: true },
          title: { type: "string", minLength: 1 },
          values: {
            type: "array",
            items: { $ref: "#/$defs/GeoCategoryValue" },
            minItems: 1,
          },
        },
        required: ["id", "enabled", "title", "values"],
      },
      GeoCategoryValue: {
        anyOf: [
          { type: "string" },
          { type: "integer" },
          { type: "number" },
          { type: "boolean" },
        ],
      },
    },
    properties: {
      raster: { $ref: "#/$defs/GeoRasterStyle" },
      features: { $ref: "#/$defs/GeoFeatureStyle" },
    },
  };

  it("retains literals, auto IDs, and recursive field kinds", () => {
    expect(schemaFields(schema)).toMatchObject([
      {
        type: "object",
        constFields: { kind: "raster" },
        fields: [
          {
            name: "opacity",
            exclusiveMinimum: 0,
            exclusiveMaximum: 1,
            examples: [0.75],
          },
          { name: "resampling", enumValues: ["linear", "nearest"] },
        ],
      },
      {
        type: "discriminated-union",
        discriminator: "kind",
        branches: [
          {
            tag: "categorized_points",
            label: "By category",
            constFields: { kind: "categorized_points" },
            fields: [
              {
                type: "object-list",
                itemTitle: "Category",
                itemAutoIdFields: ["id"],
                itemConstFields: { enabled: true },
                minItems: 2,
                maxItems: 128,
                itemFields: [
                  { name: "title", type: "string" },
                  {
                    name: "values",
                    type: "primitive-list",
                    minItems: 1,
                    allowedTypes: ["string", "integer", "number", "boolean"],
                  },
                ],
              },
            ],
          },
          {
            tag: "vector",
            label: "Vector",
            constFields: { kind: "vector" },
            fields: [],
          },
        ],
      },
    ]);
  });

  it("infers the discriminator from distinct string const properties", () => {
    expect(
      schemaFields({
        properties: {
          features: { anyOf: schema.$defs.GeoFeatureStyle.oneOf },
        },
        $defs: schema.$defs,
      }),
    ).toMatchObject([{ type: "discriminated-union", discriminator: "kind" }]);
  });

  it("builds schema-valid nested defaults with distinct generated IDs", () => {
    const ids = ["12345678abcd", "87654321abcd"];
    const config = Object.fromEntries(
      schemaFields(schema).map((field) => [
        field.name,
        buildDefaultForField(field, { generateId: () => ids.shift() ?? "" }),
      ]),
    );
    expect(config).toEqual({
      raster: { kind: "raster", opacity: 0.75, resampling: "linear" },
      features: {
        kind: "categorized_points",
        categories: [
          { id: "item_1_12345678", enabled: true, title: "a", values: [""] },
          { id: "item_2_87654321", enabled: true, title: "a", values: [""] },
        ],
      },
    });
    expect(validateConfig(schema, config)).toEqual([]);
  });

  it("uses explicit defaults before examples and returns fresh arrays", () => {
    const [field] = schemaFields({
      properties: {
        names: {
          type: "array",
          items: { type: "string" },
          default: ["default"],
          examples: [["example"]],
        },
      },
    });
    if (!field) throw new Error("Expected a names field");
    const value = buildDefaultForField(field);
    expect(value).toEqual(["default"]);
    expect(value).not.toBe(field.defaultValue);
  });
});
