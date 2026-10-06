import { describe, expect, it } from "vitest";

import type { ArtifactTypeSpec } from "@/lib/api";

import {
  artifactTypeTitle,
  formatArtifactTypeContract,
  formatArtifactTypeLabel,
  formatArtifactTypeSequence,
  formatArtifactTypeSequenceTooltip,
  formatArtifactTypeTooltip,
} from "./artifact-type-label";

const TEXT_VALUE = {
  key: { id: "scalar.text", schema_version: 1 },
  title: "Text value",
} as ArtifactTypeSpec;

const INTEGER_VALUE = {
  key: { id: "scalar.integer", schema_version: 1 },
  title: "Integer value",
} as ArtifactTypeSpec;

const TABLE_V2 = {
  key: { id: "table.data", schema_version: 2 },
  title: "Table",
} as ArtifactTypeSpec;

const CATALOG = [TEXT_VALUE, INTEGER_VALUE, TABLE_V2];

describe("artifact type labels", () => {
  it("names a type by its catalog title", () => {
    expect(
      formatArtifactTypeLabel(
        { id: "scalar.integer", schema_version: 1 },
        CATALOG,
      ),
    ).toBe("Integer value");
    expect(
      artifactTypeTitle({ id: "scalar.text", schema_version: 1 }, CATALOG),
    ).toBe("Text value");
  });

  it("hides the version a person never chose", () => {
    const label = formatArtifactTypeLabel(
      { id: "scalar.text", schema_version: 1 },
      CATALOG,
    );

    expect(label).toBe("Text value");
    expect(label).not.toContain("@");
    expect(label).not.toContain("1");
  });

  it("shows the version the catalog's own way once the schema has moved", () => {
    expect(
      formatArtifactTypeLabel({ id: "table.data", schema_version: 2 }, CATALOG),
    ).toBe("Table · v2");
  });

  it("ignores a catalog entry from another schema version", () => {
    expect(
      formatArtifactTypeLabel(
        { id: "scalar.text", schema_version: 3 },
        CATALOG,
      ),
    ).toBe("scalar.text@3");
  });

  it("falls back to the full identity when no title is known", () => {
    expect(
      formatArtifactTypeLabel({ id: "scalar.text", schema_version: 1 }, []),
    ).toBe("scalar.text@1");
    expect(
      formatArtifactTypeLabel({ id: "scalar.text", schema_version: 4 }, null),
    ).toBe("scalar.text@4");
    expect(
      artifactTypeTitle({ id: "scalar.text", schema_version: 1 }, null),
    ).toBe("scalar.text@1");
  });

  it("ignores a blank catalog title", () => {
    const blank = [
      { key: { id: "scalar.text", schema_version: 1 }, title: "   " },
    ];

    expect(
      formatArtifactTypeLabel({ id: "scalar.text", schema_version: 1 }, blank),
    ).toBe("scalar.text@1");
  });

  it("wraps the title in the sequence shape", () => {
    expect(
      formatArtifactTypeContract(
        { id: "scalar.text", schema_version: 1 },
        CATALOG,
        true,
      ),
    ).toBe("Sequence<Text value>");
    expect(formatArtifactTypeSequence("Text value")).toBe(
      "Sequence<Text value>",
    );
    expect(
      formatArtifactTypeContract(
        { id: "scalar.text", schema_version: 1 },
        CATALOG,
      ),
    ).toBe("Text value");
    expect(
      formatArtifactTypeContract(
        { id: "table.data", schema_version: 2 },
        CATALOG,
        true,
      ),
    ).toBe("Sequence<Table · v2>");
  });

  it("keeps the full identity available for the tooltip", () => {
    expect(
      formatArtifactTypeTooltip({ id: "scalar.text", schema_version: 1 }),
    ).toBe("scalar.text@1");
    expect(
      formatArtifactTypeTooltip({ id: "table.data", schema_version: 2 }),
    ).toBe("table.data@2");
    expect(
      formatArtifactTypeSequenceTooltip({
        id: "scalar.text",
        schema_version: 1,
      }),
    ).toBe("Sequence<scalar.text@1>");
  });
});
