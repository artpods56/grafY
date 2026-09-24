import { describe, expect, it } from "vitest";

import { schemaFields } from "./config-schema";

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
