import { describe, expect, it } from "vitest";

import type {
  ArtifactConversionSpec,
  ArtifactTypeSpec,
  FieldProjection,
} from "@/lib/api";
import {
  MAX_CONVERSION_PATH_CANDIDATES,
  MAX_CONVERSION_PATH_LENGTH,
  acceptedPortMetaArtifactTypes,
  connectionRouteDeliveredArtifactType,
  connectionRouteForPortSelection,
  connectionRouteSelection,
  connectionRoutesForPorts,
  portsCanConnect,
} from "./connection-routes";
import type { PortMeta } from "./types";

describe("service contract routes", () => {
  const readerOutput: PortMeta = {
    portName: "reader",
    shape: "one",
    direction: "output",
    serviceContracts: [{ id: "ocr.reader", version: 1 }],
  };
  const readerInput: PortMeta = {
    portName: "reader",
    shape: "one",
    direction: "input",
    serviceContracts: [{ id: "ocr.reader", version: 1 }],
  };
  const mismatchedInput: PortMeta = {
    portName: "reader",
    shape: "one",
    direction: "input",
    serviceContracts: [{ id: "other.service", version: 1 }],
  };

  it("accepts a matching service contract and rejects a mismatched one", () => {
    expect(connectionRoutesForPorts(readerOutput, readerInput, [], [])).toEqual(
      [{ kind: "exact", conversionPath: [] }],
    );
    expect(portsCanConnect(readerOutput, readerInput)).toBe(true);
    expect(
      connectionRouteForPortSelection(readerOutput, readerInput, [], [], {
        conversionPath: [],
      }),
    ).toEqual({ kind: "exact", conversionPath: [] });
    expect(
      connectionRouteForPortSelection(readerOutput, mismatchedInput, [], [], {
        conversionPath: [],
      }),
    ).toBeNull();
    expect(
      connectionRouteForPortSelection(readerOutput, readerInput, [], [], {
        conversionPath: [{ id: "not-a-service-conversion", version: 1 }],
      }),
    ).toBeNull();
    expect(
      connectionRouteForPortSelection(readerOutput, readerInput, [], [], {
        projection: { path: ["reader"] },
        conversionPath: [],
      }),
    ).toBeNull();
    expect(
      connectionRoutesForPorts(readerOutput, mismatchedInput, [], []),
    ).toEqual([]);
    expect(portsCanConnect(readerOutput, mismatchedInput)).toBe(false);
  });

  it("does not mix a service port with an artifact port", () => {
    const textInput: PortMeta = {
      portName: "text",
      artifactTypeId: "scalar.text",
      schemaVersion: 1,
      shape: "one",
      direction: "input",
    };

    expect(connectionRoutesForPorts(readerOutput, textInput, [], [])).toEqual(
      [],
    );
    expect(portsCanConnect(readerOutput, textInput)).toBe(false);
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

function sourcePort(id: string): PortMeta {
  return {
    portName: "output",
    artifactTypeId: id,
    schemaVersion: 1,
    shape: "one",
    direction: "output",
  };
}

function targetPort(id: string): PortMeta {
  return {
    portName: "input",
    artifactTypeId: id,
    schemaVersion: 1,
    shape: "one",
    direction: "input",
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
      connectionRoutesForPorts(
        sourcePort("customer.record"),
        targetPort("scalar.text"),
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
      connectionRoutesForPorts(
        sourcePort("customer.record"),
        targetPort("scalar.text"),
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

    const routes = connectionRoutesForPorts(
      sourcePort("customer.record"),
      targetPort("scalar.text"),
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

    const replayed = connectionRouteForPortSelection(
      sourcePort("customer.record"),
      targetPort("scalar.text"),
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
      connectionRouteForPortSelection(
        sourcePort("customer.record"),
        targetPort("scalar.text"),
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
    const routes = connectionRoutesForPorts(
      {
        portName: "value",
        artifactTypeId: "scalar.integer",
        schemaVersion: 1,
        shape: "one",
        direction: "output",
      },
      {
        portName: "items",
        artifactTypeVariable: "T",
        shape: "one",
        direction: "input",
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
    const genericSource: PortMeta = {
      portName: "items",
      artifactTypeVariable: "T",
      shape: "many",
      direction: "output",
    };
    const concreteTarget: PortMeta = {
      portName: "items",
      artifactTypeId: "scalar.text",
      schemaVersion: 1,
      shape: "many",
      direction: "input",
    };

    expect(
      connectionRoutesForPorts(genericSource, concreteTarget, [], []),
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
      connectionRoutesForPorts(
        genericSource,
        {
          portName: "other",
          artifactTypeVariable: "U",
          shape: "many",
          direction: "input",
        },
        [],
        [],
      ),
    ).toEqual([]);
  });

  it("discovers and orders a transitive x to y to z path", () => {
    const routes = connectionRoutesForPorts(
      sourcePort("x"),
      targetPort("z"),
      [],
      [conversion("y-to-z", "y", "z"), conversion("x-to-y", "x", "y")],
    );

    expect(routes).toHaveLength(1);
    expect(routes[0]?.kind).toBe("conversion");
    expect(routes[0]?.conversionPath.map((step) => step.key.id)).toEqual([
      "x-to-y",
      "y-to-z",
    ]);
  });

  it("retains equal-depth alternatives in stable id order", () => {
    const routes = connectionRoutesForPorts(
      sourcePort("x"),
      targetPort("z"),
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
    const routes = connectionRoutesForPorts(
      sourcePort("x"),
      targetPort("z"),
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
    const cyclicRoutes = connectionRoutesForPorts(
      sourcePort("x"),
      targetPort("z"),
      [],
      [
        conversion("x-to-a", "x", "a"),
        conversion("a-to-x", "a", "x"),
        conversion("a-to-z", "a", "z"),
      ],
    );
    expect(cyclicRoutes[0]?.conversionPath.map((step) => step.key.id)).toEqual([
      "x-to-a",
      "a-to-z",
    ]);

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
      connectionRoutesForPorts(
        sourcePort("x"),
        targetPort("z"),
        [],
        withinBound,
      )[0]?.conversionPath,
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
    expect(
      connectionRoutesForPorts(
        sourcePort("x"),
        targetPort("z"),
        [],
        beyondBound,
      ),
    ).toEqual([]);

    const overflowing = Array.from(
      { length: MAX_CONVERSION_PATH_CANDIDATES + 1 },
      (_, index) => conversion(`parallel-${index}`, "x", "z"),
    );
    expect(
      connectionRoutesForPorts(
        sourcePort("x"),
        targetPort("z"),
        [],
        overflowing,
      ),
    ).toEqual([]);

    const overflowingProjections = Array.from(
      { length: MAX_CONVERSION_PATH_CANDIDATES + 1 },
      (_, index): FieldProjection => ({
        path: [`value-${index}`],
        target_artifact_type: { id: "z", schema_version: 1 },
        title: `Value ${index}`,
      }),
    );
    expect(
      connectionRoutesForPorts(
        sourcePort("x"),
        targetPort("z"),
        [artifactType("x", overflowingProjections)],
        [],
      ),
    ).toEqual([]);
  });

  it("replays an exact persisted non-shortest path", () => {
    const conversions = [
      conversion("x-to-z", "x", "z"),
      conversion("x-to-y", "x", "y"),
      conversion("y-to-z", "y", "z"),
    ];
    const replayed = connectionRouteForPortSelection(
      sourcePort("x"),
      targetPort("z"),
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
    const routes = connectionRoutesForPorts(
      sourcePort("x"),
      targetPort("x"),
      [artifactType("x", [projection])],
      [conversion("x-to-x", "x", "x")],
    );

    expect(routes).toEqual([{ kind: "exact", conversionPath: [] }]);
  });
});

describe("multi-type input ports", () => {
  const multiTypeTarget: PortMeta = {
    portName: "file",
    artifactTypeId: "file.csv",
    schemaVersion: 1,
    shape: "one",
    direction: "input",
    alsoAccepts: [{ id: "file.xlsx", schema_version: 1 }],
  };

  it("lists primary and additional accepted artifact types without duplicates", () => {
    expect(acceptedPortMetaArtifactTypes(multiTypeTarget)).toEqual([
      { id: "file.csv", schema_version: 1 },
      { id: "file.xlsx", schema_version: 1 },
    ]);
  });

  it("accepts an edge of either declared artifact type and converts into either", () => {
    expect(
      connectionRoutesForPorts(sourcePort("file.csv"), multiTypeTarget, [], []),
    ).toEqual([{ kind: "exact", conversionPath: [] }]);
    expect(
      connectionRoutesForPorts(
        sourcePort("file.xlsx"),
        multiTypeTarget,
        [],
        [],
      ),
    ).toEqual([{ kind: "exact", conversionPath: [] }]);
    expect(portsCanConnect(sourcePort("file.xlsx"), multiTypeTarget)).toBe(
      true,
    );

    const toXlsx = conversion("to-xlsx", "raw.sheet", "file.xlsx");
    expect(
      connectionRoutesForPorts(
        sourcePort("raw.sheet"),
        multiTypeTarget,
        [],
        [toXlsx],
      ),
    ).toEqual([{ kind: "conversion", conversionPath: [toXlsx] }]);
  });
});

describe("delivered artifact type", () => {
  const text: FieldProjection = {
    path: ["text"],
    target_artifact_type: { id: "scalar.text", schema_version: 1 },
    title: "Text",
  };
  const textToMarkdown = conversion(
    "builtin.text_to_markdown",
    "scalar.text",
    "text.markdown",
  );
  const markdownToTable = conversion(
    "builtin.markdown_to_table",
    "text.markdown",
    "table.data",
  );

  it("is null when the route feeds the output unchanged", () => {
    const [route] = connectionRoutesForPorts(
      sourcePort("scalar.text"),
      targetPort("scalar.text"),
      [],
      [],
    );

    expect(connectionRouteDeliveredArtifactType(route!)).toBeNull();
  });

  it("is the projected field's type", () => {
    const [route] = connectionRoutesForPorts(
      sourcePort("ocr.page_result"),
      targetPort("scalar.text"),
      [artifactType("ocr.page_result", [text])],
      [],
    );

    expect(connectionRouteDeliveredArtifactType(route!)).toEqual({
      id: "scalar.text",
      schema_version: 1,
    });
  });

  it("is the last conversion's target, after any projection", () => {
    const route = connectionRouteForPortSelection(
      sourcePort("ocr.page_result"),
      targetPort("table.data"),
      [artifactType("ocr.page_result", [text])],
      [textToMarkdown, markdownToTable],
      {
        projection: { path: ["text"] },
        conversionPath: [
          { id: "builtin.text_to_markdown", version: 1 },
          { id: "builtin.markdown_to_table", version: 1 },
        ],
      },
    );

    expect(route?.kind).toBe("projection-conversion");
    expect(connectionRouteDeliveredArtifactType(route!)).toEqual({
      id: "table.data",
      schema_version: 1,
    });
  });
});
