import { describe, expect, it } from "vitest";

import {
  interactionScalarFromIntegerEncoding,
  interactionScalarFromTableCell,
  targetRowsForBinding,
  type ArtifactKeySelection,
  type ArtifactViewerBinding,
} from "./artifact-interactions";

const BINDING: ArtifactViewerBinding = {
  id: "artifact-viewer-binding-1",
  sourceViewerId: "artifact-viewer-table",
  targetViewerId: "artifact-viewer-map",
  mappings: [
    { sourceField: "normalized_name", targetField: "transliteration" },
    { sourceField: "district", targetField: "district" },
  ],
  effects: ["highlight", "focus"],
  emptySelection: "show_all",
};

describe("artifact viewer interaction mapping", () => {
  it("maps composite typed keys without coercing their values", () => {
    const selection: ArtifactKeySelection = {
      kind: "key-selection",
      items: [
        {
          sourceIndex: 7,
          values: {
            normalized_name: "belynichi",
            district: "Mohilev",
            confidence: 0.94,
          },
        },
        {
          sourceIndex: 11,
          values: {
            normalized_name: "kniazhitsy",
            district: null,
          },
        },
      ],
    };

    expect(targetRowsForBinding(BINDING, selection)).toEqual([
      { transliteration: "belynichi", district: "Mohilev" },
      { transliteration: "kniazhitsy", district: null },
    ]);
  });

  it("does not emit a partial key when a mapped field is missing", () => {
    expect(
      targetRowsForBinding(BINDING, {
        kind: "key-selection",
        items: [{ values: { normalized_name: "belynichi" } }],
      }),
    ).toEqual([]);
  });

  it("treats an unfinished field mapping as inactive", () => {
    expect(
      targetRowsForBinding(
        {
          ...BINDING,
          mappings: [{ sourceField: "normalized_name", targetField: "" }],
        },
        {
          kind: "key-selection",
          items: [{ values: { normalized_name: "belynichi" } }],
        },
      ),
    ).toEqual([]);
  });
});

describe("table cell integer encoding", () => {
  it("restores safe integers so linked tables can match on numeric keys", () => {
    expect(
      interactionScalarFromTableCell({
        encoding: "integer",
        value: "12",
      }),
    ).toBe(12);
    expect(interactionScalarFromIntegerEncoding("12")).toBe(12);
  });

  it("keeps integers outside the JS safe range as strings", () => {
    const large = String(2 ** 60 + 95);
    expect(
      interactionScalarFromTableCell({
        encoding: "integer",
        value: large,
      }),
    ).toBe(large);
  });

  it("drops json-encoded cells from selection keys", () => {
    expect(
      interactionScalarFromTableCell({
        encoding: "json",
        value: '{"index":1}',
      }),
    ).toBeUndefined();
  });
});
