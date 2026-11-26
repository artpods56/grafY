import { describe, expect, it } from "vitest";

import {
  authorableArtifactTypes,
  getArtifactEditor,
  getDefaultPayloadForType,
  JSON_EDITOR,
  TABLE_EDITOR,
  TEXT_EDITOR,
} from "./registry";

describe("getArtifactEditor", () => {
  it("returns the specialized editor for registered types", () => {
    expect(getArtifactEditor("scalar.text", 1)?.typeKey).toBe(
      TEXT_EDITOR.typeKey,
    );
    expect(getArtifactEditor("table.data", 1)?.typeKey).toBe(
      TABLE_EDITOR.typeKey,
    );
  });

  it("falls back to raw JSON for an authorable type without a specialized editor", () => {
    expect(getArtifactEditor("scalar.integer", 1, { authorable: true })).toBe(
      JSON_EDITOR,
    );
    expect(getArtifactEditor("json.schema", 1)).toBe(JSON_EDITOR);
    expect(getArtifactEditor("ocr.tiff_text_regions", 1)).toBe(JSON_EDITOR);
    expect(getArtifactEditor("ocr.tiff_recognized_text", 1)).toBe(JSON_EDITOR);
  });

  it("returns null for a catalogued type that cannot be authored", () => {
    expect(getArtifactEditor("file.tiff", 1, { authorable: false })).toBeNull();
  });
});

describe("getDefaultPayloadForType", () => {
  it("returns the specialized starter JSON for known types", () => {
    expect(getDefaultPayloadForType("scalar.text", 1)).toEqual({ value: "" });
    expect(getDefaultPayloadForType("scalar.integer", 1)).toEqual({
      value: 0,
    });
    expect(getDefaultPayloadForType("table.data", 1)).toEqual({
      columns: [{ id: "column_1", title: "Column 1", value_type: "text" }],
      rows: [{ column_1: "" }],
    });
    expect(getDefaultPayloadForType("json.schema", 1)).toEqual({
      value: '{"type":"object","properties":{}}',
    });
    expect(getDefaultPayloadForType("geo.feature_collection", 1)).toEqual({
      type: "FeatureCollection",
      crs: "EPSG:4326",
      features: [],
      source_name: "untitled",
      bounds: null,
    });
  });

  it("falls back to an empty object", () => {
    expect(getDefaultPayloadForType("prompt.message", 1)).toEqual({});
  });
});

describe("authorableArtifactTypes", () => {
  it("keeps only catalog entries marked authorable", () => {
    expect(
      authorableArtifactTypes([
        {
          key: { id: "scalar.text", schema_version: 1 },
          title: "Text",
          authorable: true,
        },
        {
          key: { id: "file.tiff", schema_version: 1 },
          title: "TIFF",
          authorable: false,
        },
      ]).map((spec) => spec.key.id),
    ).toEqual(["scalar.text"]);
  });
});
