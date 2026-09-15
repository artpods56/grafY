import { describe, expect, it } from "vitest";

import type {
  ArtifactConversionSpec,
  ArtifactTypeSpec,
  FieldProjection,
} from "@/lib/api";
import {
  MAX_CONVERSION_PATH_CANDIDATES,
  MAX_CONVERSION_PATH_LENGTH,
  canonicalHandleId,
  connectionIsValid,
  connectionRouteForSelection,
  connectionRouteSelection,
  connectionRoutesFor,
  decodeHandleId,
  encodeHandleId,
} from "./handles";

describe("typed handle ids", () => {
  it("keeps legacy five-part handles unchanged", () => {
    const id = encodeHandleId({
      portName: "input",
      artifactTypeId: "text",
      schemaVersion: 2,
      shape: "one",
      direction: "input",
    });

    expect(id).toBe("input::text::2::one::input");
    expect(decodeHandleId(id)).toEqual({
      portName: "input",
      artifactTypeId: "text",
      schemaVersion: 2,
      shape: "one",
      direction: "input",
    });
  });

  it("round-trips an instance plug without changing its stable id", () => {
    const id = encodeHandleId({
      portName: "items",
      artifactTypeId: "text",
      schemaVersion: 1,
      shape: "many",
      direction: "input",
      plugId: "00000000-0000-4000-8000-000000000042",
    });

    expect(decodeHandleId(id)).toEqual({
      portName: "items",
      artifactTypeId: "text",
      schemaVersion: 1,
      shape: "many",
      direction: "input",
      plugId: "00000000-0000-4000-8000-000000000042",
    });
  });

  it("round-trips an explicit unbound type variable without changing concrete ids", () => {
    const id = encodeHandleId({
      portName: "items",
      artifactTypeVariable: "Artifact::T",
      shape: "many",
      direction: "input",
      plugId: "plug-1",
    });

    expect(id).toBe("items::Artifact%3A%3AT::$generic::many::input::plug-1");
    expect(decodeHandleId(id)).toEqual({
      portName: "items",
      artifactTypeVariable: "Artifact::T",
      shape: "many",
      direction: "input",
      plugId: "plug-1",
    });
  });

  it("round-trips catalog feed intent and strips it for canonical ids", () => {
    const withFeed = encodeHandleId({
      portName: "result",
      artifactTypeId: "doc.ocr",
      schemaVersion: 1,
      shape: "one",
      direction: "output",
      feed: { kind: "projection", path: ["body", "text"] },
    });

    expect(decodeHandleId(withFeed)).toEqual({
      portName: "result",
      artifactTypeId: "doc.ocr",
      schemaVersion: 1,
      shape: "one",
      direction: "output",
      feed: { kind: "projection", path: ["body", "text"] },
    });
    expect(canonicalHandleId(withFeed)).toBe(
      "result::doc.ocr::1::one::output",
    );
  });
});

function artifactType(
  id: string,
  fieldProjections: readonly FieldProjection[] = [],
): ArtifactTypeSpec {
  return {
    key: { id, schema_version: 1 },
    title: id,
    bundle: { format: "inline-json", version: 1 },
    payload_schema: {},
    field_projections: fieldProjections,
  };
}

function conversion(
  id: string,
  source: string,
  target: string,
): ArtifactConversionSpec {
  return {
    key: { id, version: 1 },
    source_artifact_type: { id: source, schema_version: 1 },
    target_artifact_type: { id: target, schema_version: 1 },
    title: id,
  };
}

function connection(source: string, target: string) {
  return {
    sourceHandle: encodeHandleId({
      portName: "output",
      artifactTypeId: source,
      schemaVersion: 1,
      shape: "one",
      direction: "output",
    }),
    targetHandle: encodeHandleId({
      portName: "input",
      artifactTypeId: target,
      schemaVersion: 1,
      shape: "one",
      direction: "input",
    }),
  };
}

describe("registry field projection routes", () => {
  it("connects a nested string projection directly to scalar.text@1", () => {
    const displayName: FieldProjection = {
      path: ["profile", "display_name"],
      target_artifact_type: { id: "scalar.text", schema_version: 1 },
      title: "Display name",
    };

    expect(
      connectionRoutesFor(
        connection("customer.record", "scalar.text"),
        [artifactType("customer.record", [displayName])],
        [],
      ),
    ).toEqual([
      {
        kind: "projection",
        projection: displayName,
        conversionPath: [],
      },
    ]);
  });

  it("composes a nested integer projection with integer_to_text", () => {
    const age: FieldProjection = {
      path: ["profile", "age"],
      target_artifact_type: { id: "scalar.integer", schema_version: 1 },
      title: "Age",
    };
    const integerToText = conversion(
      "builtin.scalar.integer_to_text",
      "scalar.integer",
      "scalar.text",
    );

    expect(
      connectionRoutesFor(
        connection("customer.record", "scalar.text"),
        [artifactType("customer.record", [age])],
        [integerToText],
      ),
    ).toEqual([
      {
        kind: "projection-conversion",
        projection: age,
        conversionPath: [integerToText],
      },
    ]);
  });

  it("keeps multiple nested string projections ambiguous in path order", () => {
    const displayName: FieldProjection = {
      path: ["profile", "display_name"],
      target_artifact_type: { id: "scalar.text", schema_version: 1 },
      title: "Display name",
    };
    const city: FieldProjection = {
      path: ["address", "city"],
      target_artifact_type: { id: "scalar.text", schema_version: 1 },
      title: "City",
    };

    const routes = connectionRoutesFor(
      connection("customer.record", "scalar.text"),
      [artifactType("customer.record", [displayName, city])],
      [],
    );

    expect(routes.map((route) => route.kind)).toEqual([
      "projection",
      "projection",
    ]);
    expect(
      routes.map((route) =>
        route.kind === "projection" ? route.projection.path : [],
      ),
    ).toEqual([
      ["address", "city"],
      ["profile", "display_name"],
    ]);
  });

  it("replays the exact persisted nested projection path", () => {
    const billingName: FieldProjection = {
      path: ["billing", "display_name"],
      target_artifact_type: { id: "scalar.text", schema_version: 1 },
      title: "Billing display name",
    };
    const profileName: FieldProjection = {
      path: ["profile", "display_name"],
      target_artifact_type: { id: "scalar.text", schema_version: 1 },
      title: "Profile display name",
    };
    const artifactTypes = [
      artifactType("customer.record", [profileName, billingName]),
    ];
    const persistedSelection = {
      projection: { path: ["profile", "display_name"] },
      conversionPath: [],
    };

    const replayed = connectionRouteForSelection(
      connection("customer.record", "scalar.text"),
      artifactTypes,
      [],
      persistedSelection,
    );

    expect(replayed).toEqual({
      kind: "projection",
      projection: profileName,
      conversionPath: [],
    });
    expect(connectionRouteSelection(replayed!)).toEqual(persistedSelection);
    expect(
      connectionRouteForSelection(
        connection("customer.record", "scalar.text"),
        artifactTypes,
        [],
        {
          projection: { path: ["display_name"] },
          conversionPath: [],
        },
      ),
    ).toBeNull();
  });
});

describe("conversion route discovery", () => {
  it("offers exact and integer-to-text bindings for an unbound generic target", () => {
    const integerToText = conversion(
      "builtin.scalar.integer_to_text",
      "scalar.integer",
      "scalar.text",
    );
    const routes = connectionRoutesFor(
      {
        sourceHandle: encodeHandleId({
          portName: "value",
          artifactTypeId: "scalar.integer",
          schemaVersion: 1,
          shape: "one",
          direction: "output",
        }),
        targetHandle: encodeHandleId({
          portName: "items",
          artifactTypeVariable: "T",
          shape: "one",
          direction: "input",
        }),
      },
      [],
      [integerToText],
    );

    expect(routes).toEqual([
      {
        kind: "exact",
        conversionPath: [],
        artifactTypeBinding: {
          endpoint: "target",
          variable: "T",
          artifactType: { id: "scalar.integer", schema_version: 1 },
        },
      },
      {
        kind: "conversion",
        conversionPath: [integerToText],
        artifactTypeBinding: {
          endpoint: "target",
          variable: "T",
          artifactType: { id: "scalar.text", schema_version: 1 },
        },
      },
    ]);
  });

  it("binds an unbound generic source to a concrete target and rejects variable-to-variable", () => {
    const genericSource = encodeHandleId({
      portName: "items",
      artifactTypeVariable: "T",
      shape: "many",
      direction: "output",
    });
    const concreteTarget = encodeHandleId({
      portName: "items",
      artifactTypeId: "scalar.text",
      schemaVersion: 1,
      shape: "many",
      direction: "input",
    });

    expect(
      connectionRoutesFor(
        { sourceHandle: genericSource, targetHandle: concreteTarget },
        [],
        [],
      ),
    ).toEqual([
      {
        kind: "exact",
        conversionPath: [],
        artifactTypeBinding: {
          endpoint: "source",
          variable: "T",
          artifactType: { id: "scalar.text", schema_version: 1 },
        },
      },
    ]);
    expect(
      connectionRoutesFor(
        {
          sourceHandle: genericSource,
          targetHandle: encodeHandleId({
            portName: "other",
            artifactTypeVariable: "U",
            shape: "many",
            direction: "input",
          }),
        },
        [],
        [],
      ),
    ).toEqual([]);
  });

  it("discovers and orders a transitive x to y to z path", () => {
    const routes = connectionRoutesFor(
      connection("x", "z"),
      [],
      [conversion("y-to-z", "y", "z"), conversion("x-to-y", "x", "y")],
    );

    expect(routes).toHaveLength(1);
    expect(routes[0]?.kind).toBe("conversion");
    expect(
      routes[0]?.conversionPath.map((step) => step.key.id),
    ).toEqual(["x-to-y", "y-to-z"]);
  });

  it("retains equal-depth alternatives in stable id order", () => {
    const routes = connectionRoutesFor(
      connection("x", "z"),
      [],
      [
        conversion("x-to-b", "x", "b"),
        conversion("b-to-z", "b", "z"),
        conversion("x-to-a", "x", "a"),
        conversion("a-to-z", "a", "z"),
      ],
    );

    expect(
      routes.map((route) => route.conversionPath.map((step) => step.key.id)),
    ).toEqual([
      ["x-to-a", "a-to-z"],
      ["x-to-b", "b-to-z"],
    ]);
  });

  it("keeps distinct projection semantics ambiguous even at different depths", () => {
    const projection: FieldProjection = {
      path: ["value"],
      target_artifact_type: { id: "projected", schema_version: 1 },
      title: "Value",
    };
    const routes = connectionRoutesFor(
      connection("x", "z"),
      [artifactType("x", [projection])],
      [
        conversion("x-to-z", "x", "z"),
        conversion("projected-to-y", "projected", "y"),
        conversion("y-to-z", "y", "z"),
      ],
    );

    expect(routes.map((route) => route.kind)).toEqual([
      "conversion",
      "projection-conversion",
    ]);
  });

  it("rejects cycles, overlong paths, and overflowing candidate sets", () => {
    const cyclicRoutes = connectionRoutesFor(
      connection("x", "z"),
      [],
      [
        conversion("x-to-a", "x", "a"),
        conversion("a-to-x", "a", "x"),
        conversion("a-to-z", "a", "z"),
      ],
    );
    expect(
      cyclicRoutes[0]?.conversionPath.map((step) => step.key.id),
    ).toEqual(["x-to-a", "a-to-z"]);

    const withinBound = Array.from(
      { length: MAX_CONVERSION_PATH_LENGTH },
      (_, index) =>
        conversion(
          `step-${index}`,
          index === 0 ? "x" : `n-${index}`,
          index === MAX_CONVERSION_PATH_LENGTH - 1 ? "z" : `n-${index + 1}`,
        ),
    );
    expect(
      connectionRoutesFor(connection("x", "z"), [], withinBound)[0]
        ?.conversionPath,
    ).toHaveLength(MAX_CONVERSION_PATH_LENGTH);

    const beyondBound = [
      ...withinBound.slice(0, -1),
      conversion(
        "step-before-z",
        `n-${MAX_CONVERSION_PATH_LENGTH - 1}`,
        "last",
      ),
      conversion("step-to-z", "last", "z"),
    ];
    expect(connectionRoutesFor(connection("x", "z"), [], beyondBound)).toEqual(
      [],
    );

    const overflowing = Array.from(
      { length: MAX_CONVERSION_PATH_CANDIDATES + 1 },
      (_, index) => conversion(`parallel-${index}`, "x", "z"),
    );
    expect(connectionRoutesFor(connection("x", "z"), [], overflowing)).toEqual(
      [],
    );

    const overflowingProjections = Array.from(
      { length: MAX_CONVERSION_PATH_CANDIDATES + 1 },
      (_, index): FieldProjection => ({
        path: [`value-${index}`],
        target_artifact_type: { id: "z", schema_version: 1 },
        title: `Value ${index}`,
      }),
    );
    expect(
      connectionRoutesFor(
        connection("x", "z"),
        [artifactType("x", overflowingProjections)],
        [],
      ),
    ).toEqual([]);

    const overflowingProjection: FieldProjection = {
      path: ["value"],
      target_artifact_type: { id: "projected", schema_version: 1 },
      title: "Value",
    };
    expect(
      connectionRoutesFor(
        connection("x", "z"),
        [artifactType("x", [overflowingProjection])],
        [
          conversion("x-to-z", "x", "z"),
          ...Array.from(
            { length: MAX_CONVERSION_PATH_CANDIDATES + 1 },
            (_, index) =>
              conversion(`projected-parallel-${index}`, "projected", "z"),
          ),
        ],
      ),
    ).toEqual([]);

    const singleProjection: FieldProjection = {
      path: ["value"],
      target_artifact_type: { id: "projected", schema_version: 1 },
      title: "Value",
    };
    expect(
      connectionRoutesFor(
        connection("x", "z"),
        [artifactType("x", [singleProjection])],
        [
          ...overflowing,
          conversion("projected-to-z", "projected", "z"),
        ],
      ),
    ).toEqual([]);
  });

  it("replays an exact persisted non-shortest path", () => {
    const conversions = [
      conversion("x-to-z", "x", "z"),
      conversion("x-to-y", "x", "y"),
      conversion("y-to-z", "y", "z"),
    ];
    const discovered = connectionRoutesFor(
      connection("x", "z"),
      [],
      conversions,
    );
    expect(discovered[0]?.conversionPath.map((step) => step.key.id)).toEqual([
      "x-to-z",
    ]);

    const replayed = connectionRouteForSelection(
      connection("x", "z"),
      [],
      conversions,
      {
        conversionPath: [
          { id: "x-to-y", version: 1 },
          { id: "y-to-z", version: 1 },
        ],
      },
    );
    expect(replayed).not.toBeNull();
    expect(connectionRouteSelection(replayed!).conversionPath).toEqual([
      { id: "x-to-y", version: 1 },
      { id: "y-to-z", version: 1 },
    ]);
  });

  it("gives an exact whole-artifact match zero-hop precedence", () => {
    const projection: FieldProjection = {
      path: ["value"],
      target_artifact_type: { id: "x", schema_version: 1 },
      title: "Value",
    };
    const routes = connectionRoutesFor(
      connection("x", "x"),
      [artifactType("x", [projection])],
      [conversion("x-to-x", "x", "x")],
    );

    expect(routes).toEqual([{ kind: "exact", conversionPath: [] }]);
  });
});

describe("multi-type input ports", () => {
  const multiTypeTarget = encodeHandleId({
    portName: "file",
    artifactTypeId: "file.csv",
    schemaVersion: 1,
    shape: "one",
    direction: "input",
    alsoAccepts: [{ id: "file.xlsx", schema_version: 1 }],
  });

  function source(id: string): string {
    return encodeHandleId({
      portName: "output",
      artifactTypeId: id,
      schemaVersion: 1,
      shape: "one",
      direction: "output",
    });
  }

  it("round-trips the additional accepted artifact types", () => {
    const decoded = decodeHandleId(multiTypeTarget);

    expect(decoded).toMatchObject({
      artifactTypeId: "file.csv",
      alsoAccepts: [{ id: "file.xlsx", schema_version: 1 }],
    });
    expect(encodeHandleId(decoded!)).toBe(multiTypeTarget);
  });

  it("accepts an edge of either declared artifact type", () => {
    expect(
      connectionRoutesFor(
        { sourceHandle: source("file.csv"), targetHandle: multiTypeTarget },
        [],
        [],
      ),
    ).toEqual([{ kind: "exact", conversionPath: [] }]);
    expect(
      connectionRoutesFor(
        { sourceHandle: source("file.xlsx"), targetHandle: multiTypeTarget },
        [],
        [],
      ),
    ).toEqual([{ kind: "exact", conversionPath: [] }]);
  });

  it("refuses a third artifact type", () => {
    expect(
      connectionRoutesFor(
        { sourceHandle: source("file.pdf"), targetHandle: multiTypeTarget },
        [],
        [],
      ),
    ).toEqual([]);
  });

  it("accepts a declared conversion to a member of the set", () => {
    const pdfToXlsx = conversion(
      "builtin.file.pdf_to_xlsx",
      "file.pdf",
      "file.xlsx",
    );

    expect(
      connectionRoutesFor(
        { sourceHandle: source("file.pdf"), targetHandle: multiTypeTarget },
        [],
        [pdfToXlsx],
      ),
    ).toEqual([{ kind: "conversion", conversionPath: [pdfToXlsx] }]);
  });

  it("validates a drag connection against any member of the set", () => {
    expect(
      connectionIsValid({
        sourceHandle: source("file.xlsx"),
        targetHandle: multiTypeTarget,
      }),
    ).toBe(true);
    expect(
      connectionIsValid({
        sourceHandle: source("file.pdf"),
        targetHandle: multiTypeTarget,
      }),
    ).toBe(false);
  });
});
