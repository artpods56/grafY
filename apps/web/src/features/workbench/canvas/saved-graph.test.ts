import { describe, expect, it } from "vitest";

import type {
  ArtifactConversionSpec,
  NodeRegistry,
  NodeSpec,
  SavedGraph,
  SavedGraphDocument,
} from "@/lib/api";
import { decodeHandleId } from "./handles";
import {
  hydrateSavedGraph,
  savedGraphExecutionFingerprint,
  savedGraphFingerprint,
} from "./saved-graph";
import {
  IMAGE_UPLOAD_OPERATOR_ID,
  effectivePortShape,
  serializeWorkflowEdgeTransport,
} from "./types";

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

function nodeSpec(
  operatorId: string,
  direction: "input" | "output",
  artifactTypeId: string,
  shape: "one" | "many" = "one",
  acceptedShapes: readonly ("one" | "many")[] = [shape],
): NodeSpec {
  const port = {
    name: direction,
    title: direction,
    description: null,
    direction,
    artifact_type: { id: artifactTypeId, schema_version: 1 },
    shape,
    accepted_shapes: acceptedShapes,
    instance_plugs: false,
    variadic: false,
    required: true,
  };
  return {
    operator_id: operatorId,
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title: operatorId,
    description: operatorId,
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: direction === "input" ? [port] : [],
    outputs: direction === "output" ? [port] : [],
  };
}

const conversionPath = [
  { id: "x-to-y", version: 1 },
  { id: "y-to-z", version: 1 },
] as const;

function registry(
  sourceShape: "one" | "many" = "one",
  targetShape: "one" | "many" = "one",
  targetAcceptedShapes: readonly ("one" | "many")[] = [targetShape],
): NodeRegistry {
  return {
    plugins: [],
    artifact_types: ["x", "y", "z"].map((id) => ({
      key: { id, schema_version: 1 },
      title: id,
      payload_schema: {},
      field_projections: [],
      bundle: { format: "inline-json", version: 1 },
    })),
    artifact_conversions: [
      conversion("x-to-z", "x", "z"),
      conversion("x-to-y", "x", "y"),
      conversion("y-to-z", "y", "z"),
    ],
    nodes: [
      nodeSpec("source", "output", "x", sourceShape),
      nodeSpec(
        "target",
        "input",
        "z",
        targetShape,
        targetAcceptedShapes,
      ),
    ],
  };
}

function graphWithEdge(
  edgeConversion: Pick<
    SavedGraphDocument["edges"][number],
    "conversion_path"
  >,
): SavedGraph {
  return {
    id: "00000000-0000-4000-8000-000000000001",
    revision: 1,
    name: "Conversion path",
    created_at: "2026-07-15T12:00:00Z",
    updated_at: "2026-07-15T12:00:00Z",
    document: {
      schema_version: 7,
      origins: [],
      nodes: [
        {
          id: "source-node",
          kind: "builtin",
          operator_id: "source",
          operator_version: 1,
          config: {},
          input_plugs: [],
          artifact_type_bindings: [],
          position: { x: 0, y: 0 },
        },
        {
          id: "target-node",
          kind: "builtin",
          operator_id: "target",
          operator_version: 1,
          config: {},
          input_plugs: [],
          artifact_type_bindings: [],
          position: { x: 300, y: 0 },
        },
      ],
      edges: [
        {
          id: "edge",
          enabled: true,
          from_node: "source-node",
          from_port: "output",
          to_node: "target-node",
          to_port: "input",
          to_plug: null,
          collection_mode: "direct",
          projection: null,
          route_offset: null,
          ...edgeConversion,
        },
      ],
      presentation: {
        viewers: [],
        links: [],
        bindings: [],
        annotations: [],
      },
    },
  };
}

function graphWithCollectionMode(
  collectionMode: "direct" | "map",
): SavedGraph {
  const graph = graphWithEdge({ conversion_path: conversionPath });
  return {
    ...graph,
    document: {
      ...graph.document,
      edges: graph.document.edges.map((edge) => ({
        ...edge,
        collection_mode: collectionMode,
      })),
    },
  };
}

describe("saved conversion paths", () => {
  it("hydrates and exposes the exact ordered path for run transport", () => {
    const hydrated = hydrateSavedGraph(
      graphWithEdge({ conversion_path: conversionPath }),
      registry(),
    );
    const edge = hydrated.edges[0];

    expect(edge?.data?.conversionPath).toEqual(conversionPath);
    expect(serializeWorkflowEdgeTransport(edge?.data).conversion_path).toEqual(
      conversionPath,
    );
  });
});

describe("scoped Plugin node hydration", () => {
  it("selects the matching scope and slug when operator identities overlap", () => {
    const base = graphWithEdge({ conversion_path: conversionPath });
    const graph: SavedGraph = {
      ...base,
      document: {
        ...base.document,
        nodes: base.document.nodes.map((node) =>
          node.id === "source-node"
            ? {
                ...node,
                plugin_release_pin: {
                  scope: "system",
                  slug: "reports",
                  revision: 1,
                },
              }
            : node,
        ),
      },
    };
    const liveRegistry = registry();
    const systemSpec: NodeSpec = {
      ...nodeSpec("source", "output", "x"),
      plugin_slug: "reports",
      origin: "plugin",
      plugin_revision: 3,
      plugin_release: { scope: "system", slug: "reports", revision: 3 },
      title: "System report source",
    };
    const workspaceSpec: NodeSpec = {
      ...nodeSpec("source", "output", "x"),
      plugin_slug: "reports",
      origin: "plugin",
      plugin_revision: 5,
      plugin_release: {
        scope: "workspace",
        slug: "reports",
        revision: 5,
      },
      title: "Workspace report source",
    };
    const hydrated = hydrateSavedGraph(graph, {
      ...liveRegistry,
      nodes: [
        systemSpec,
        workspaceSpec,
        ...liveRegistry.nodes.filter((spec) => spec.operator_id !== "source"),
      ],
    });

    expect(hydrated.nodes[0]?.data.spec.title).toBe("System report source");
    expect(hydrated.nodes[0]?.data.pluginReleasePin).toEqual({
      scope: "system",
      slug: "reports",
      revision: 1,
    });
  });
});

describe("unavailable saved operators", () => {
  it("hydrates a placeholder and preserves its incident connection", () => {
    const base = graphWithEdge({ conversion_path: conversionPath });
    const graph: SavedGraph = {
      ...base,
      document: {
        ...base.document,
        nodes: base.document.nodes.map((node) =>
          node.id === "source-node"
            ? {
                ...node,
                operator_id: "gis.map.compose",
                plugin_release_pin: {
                  scope: "system",
                  slug: "gis",
                  revision: 4,
                },
                config: { nested: { preserved: true } },
                input_plugs: [
                  { id: "historical-plug", port: "historical-input" },
                ],
                artifact_type_bindings: [
                  {
                    variable: "Z",
                    artifact_type: { id: "z", schema_version: 1 },
                  },
                  {
                    variable: "A",
                    artifact_type: { id: "x", schema_version: 1 },
                  },
                ],
                layout: null,
              }
            : {
                ...node,
              },
        ),
      },
    };
    const liveRegistry = registry();
    const hydrated = hydrateSavedGraph(graph, {
      ...liveRegistry,
      nodes: liveRegistry.nodes.filter(
        (spec) => spec.operator_id !== "gis.map.compose",
      ),
    });
    const sourceNode = hydrated.nodes.find(
      (node) => node.id === "source-node",
    );
    const edge = hydrated.edges[0];

    expect(sourceNode?.data.compatibility).toMatchObject({
      status: "unsupported",
      outputs: [{ portName: "output" }],
    });
    expect(sourceNode?.data.compatibility).toHaveProperty(
      "issues.0",
      "Operator gis.map.compose@1 is unavailable. This saved node is preserved but cannot run.",
    );
    expect(sourceNode?.data.layout).toBeNull();
    expect(sourceNode?.data.pluginReleasePin).toEqual({
      scope: "system",
      slug: "gis",
      revision: 4,
    });
    expect(edge?.sourceHandle).toContain("$compatibility::output");
    expect(decodeHandleId(edge?.sourceHandle)).toBeNull();
    expect(decodeHandleId(edge?.targetHandle)).toMatchObject({
      portName: "input",
      direction: "input",
    });
    expect(edge?.data?.compatibilityIssues).toHaveLength(1);
  });
});

describe("saved node layout", () => {
  it("hydrates node chrome sizes", () => {
    const base = graphWithEdge({ conversion_path: conversionPath });
    const withLayout: SavedGraph = {
      ...base,
      document: {
        ...base.document,
        nodes: base.document.nodes.map((node, index) =>
          index === 0
            ? {
                ...node,
                layout: {
                  width: 420,
                  body_height: 180,
                  appendix_height: 320,
                },
              }
            : node,
        ),
      },
    };
    const hydrated = hydrateSavedGraph(withLayout, registry());
    expect(hydrated.nodes[0]?.data.layout).toEqual({
      width: 420,
      bodyHeight: 180,
      appendixHeight: 320,
    });
    expect(hydrated.nodes[1]?.data.layout).toBeNull();
  });
});

describe("saved edge enablement", () => {
  it("hydrates a legacy edge as enabled and keeps enablement out of run transport", () => {
    const hydrated = hydrateSavedGraph(
      graphWithEdge({ conversion_path: conversionPath }),
      registry(),
    );
    const edge = hydrated.edges[0];

    expect(edge?.data?.enabled).toBe(true);
    expect(serializeWorkflowEdgeTransport(edge?.data)).not.toHaveProperty(
      "enabled",
    );
  });

  it("keeps disabled state in the dirty fingerprint", () => {
    const legacyGraph = graphWithEdge({ conversion_path: conversionPath });
    const disabledGraph: SavedGraph = {
      ...legacyGraph,
      document: {
        ...legacyGraph.document,
        edges: legacyGraph.document.edges.map((edge) => ({
          ...edge,
          enabled: false,
        })),
      },
    };
    const disabled = hydrateSavedGraph(disabledGraph, registry());
    const enabledDraft = {
      name: "Edge state",
      document: legacyGraph.document,
    };
    const disabledDraft = {
      name: "Edge state",
      document: disabledGraph.document,
    };

    expect(disabled.edges[0]?.data?.enabled).toBe(false);
    expect(disabledDraft.document.edges[0]).toMatchObject({ enabled: false });
    expect(savedGraphFingerprint(disabledDraft)).not.toBe(
      savedGraphFingerprint(enabledDraft),
    );
  });

  it("normalizes a missing legacy flag to enabled in the fingerprint", () => {
    const graph = graphWithEdge({ conversion_path: conversionPath });
    const enabledDraft = {
      name: "Legacy fingerprint",
      document: graph.document,
    };
    const enabledEdge = enabledDraft.document.edges[0];
    if (!enabledEdge) throw new Error("enabled-edge fixture is incomplete");
    const legacyEdge = { ...enabledEdge } as
      Omit<typeof enabledEdge, "enabled"> & { enabled?: boolean };
    delete legacyEdge.enabled;
    const legacyDraft = {
      ...enabledDraft,
      document: {
        ...enabledDraft.document,
        edges: [legacyEdge],
      },
    } as unknown as typeof enabledDraft;

    expect(
      savedGraphFingerprint(legacyDraft),
    ).toBe(savedGraphFingerprint(enabledDraft));
  });

  it("ignores presentation in the execution fingerprint", () => {
    const graph = graphWithEdge({ conversion_path: conversionPath });
    const base = {
      name: "Presentation drift",
      document: graph.document,
    };
    const withViewer = {
      ...base,
      document: {
        ...base.document,
        presentation: {
          viewers: [{
            id: "viewer-1",
            position: { x: 1, y: 2 },
          }],
          links: base.document.presentation?.links ?? [],
          bindings: base.document.presentation?.bindings ?? [],
          annotations: base.document.presentation?.annotations ?? [],
        },
      },
    };

    expect(savedGraphFingerprint(base)).not.toBe(
      savedGraphFingerprint(withViewer),
    );
    expect(savedGraphExecutionFingerprint(base)).toBe(
      savedGraphExecutionFingerprint(withViewer),
    );
  });
});

describe("saved collection modes", () => {
  it("hydrates a direct edge when the target accepts the source shape", () => {
    const hydrated = hydrateSavedGraph(
      graphWithCollectionMode("direct"),
      registry("many", "one", ["one", "many"]),
    );

    expect(hydrated.edges[0]?.data?.collectionMode).toBe("direct");
    expect(decodeHandleId(hydrated.edges[0]?.sourceHandle)?.shape).toBe(
      "many",
    );
  });

  it("hydrates a map edge from a many source into a one target", () => {
    const hydrated = hydrateSavedGraph(
      graphWithCollectionMode("map"),
      registry("many", "one"),
    );

    expect(hydrated.edges[0]?.data?.collectionMode).toBe("map");
    expect(decodeHandleId(hydrated.edges[0]?.sourceHandle)?.shape).toBe(
      "many",
    );
    expect(decodeHandleId(hydrated.edges[0]?.targetHandle)?.shape).toBe("one");
  });

  it("rejects map edges targeting different inputs on the same node", () => {
    const sourceSpec = nodeSpec("source", "output", "x", "many");
    const otherSourceSpec = nodeSpec(
      "other-source",
      "output",
      "x",
      "many",
    );
    const targetSpec = nodeSpec("target", "input", "z");
    const targetInput = targetSpec.inputs[0]!;
    const testRegistry: NodeRegistry = {
      ...registry("many", "one"),
      nodes: [
        sourceSpec,
        otherSourceSpec,
        {
          ...targetSpec,
          inputs: [
            { ...targetInput, name: "left", title: "Left" },
            { ...targetInput, name: "right", title: "Right" },
          ],
        },
      ],
    };
    const graph = graphWithCollectionMode("map");
    const sourceNode = graph.document.nodes[0];
    const targetNode = graph.document.nodes[1];
    const edge = graph.document.edges[0];
    if (!sourceNode || !targetNode || !edge) {
      throw new Error("map-edge test fixture is incomplete");
    }
    const invalidGraph: SavedGraph = {
      ...graph,
      document: {
        ...graph.document,
        nodes: [
          sourceNode,
          {
            ...sourceNode,
            id: "other-source-node",
            kind: "builtin",
            operator_id: "other-source",
          },
          targetNode,
        ],
        edges: [
          { ...edge, id: "map-left", to_port: "left" },
          {
            ...edge,
            id: "map-right",
            from_node: "other-source-node",
            to_port: "right",
          },
        ],
      },
    };

    expect(() => hydrateSavedGraph(invalidGraph, testRegistry)).toThrow(
      "node target-node has more than one map edge: map-left targets input left and map-right targets input right; exactly one edge may drive mapped execution",
    );
  });

  it.each([
    {
      collectionMode: "direct" as const,
      sourceShape: "many" as const,
      targetShape: "one" as const,
      targetAcceptedShapes: ["one"] as const,
      expectedMode: "map",
    },
    {
      collectionMode: "direct" as const,
      sourceShape: "one" as const,
      targetShape: "many" as const,
      targetAcceptedShapes: ["many"] as const,
      expectedMode: null,
    },
    {
      collectionMode: "map" as const,
      sourceShape: "one" as const,
      targetShape: "one" as const,
      targetAcceptedShapes: ["one"] as const,
      expectedMode: "direct",
    },
    {
      collectionMode: "map" as const,
      sourceShape: "many" as const,
      targetShape: "many" as const,
      targetAcceptedShapes: ["many"] as const,
      expectedMode: "direct",
    },
    {
      collectionMode: "map" as const,
      sourceShape: "many" as const,
      targetShape: "one" as const,
      targetAcceptedShapes: ["one", "many"] as const,
      expectedMode: "direct",
    },
  ])(
    "rejects $collectionMode for $sourceShape → $targetShape when new connections require $expectedMode",
    ({
      collectionMode,
      sourceShape,
      targetShape,
      targetAcceptedShapes,
      expectedMode,
    }) => {
      const expected = expectedMode
        ? `'${expectedMode}'`
        : "no supported collection mode";
      expect(() =>
        hydrateSavedGraph(
          graphWithCollectionMode(collectionMode),
          registry(sourceShape, targetShape, targetAcceptedShapes),
        ),
      ).toThrow(
        `uses collection mode '${collectionMode}' for source shape '${sourceShape}' and target shape '${targetShape}', expected ${expected}`,
      );
    },
  );
});

function collectRegistry(): NodeRegistry {
  const source = nodeSpec("source", "output", "text");
  const collector: NodeSpec = {
    operator_id: "test.collect",
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title: "Collect text",
    description: "Collect ordered text inputs.",
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [
      {
        name: "items",
        title: "Items",
        description: null,
        direction: "input",
        artifact_type: { id: "text", schema_version: 1 },
        shape: "many",
        accepted_shapes: ["one", "many"],
        instance_plugs: true,
        variadic: false,
        required: true,
      },
    ],
    outputs: [],
  };
  return {
    plugins: [],
    artifact_types: [
      {
        key: { id: "text", schema_version: 1 },
        title: "Text",
        payload_schema: {},
        field_projections: [],
        bundle: { format: "inline-json", version: 1 },
      },
    ],
    artifact_conversions: [],
    nodes: [source, collector],
  };
}

function graphWithCollectPlugs(): SavedGraph {
  return {
    id: "00000000-0000-4000-8000-000000000002",
    revision: 1,
    name: "Collect inputs",
    created_at: "2026-07-15T12:00:00Z",
    updated_at: "2026-07-15T12:00:00Z",
    document: {
      schema_version: 7,
      origins: [],
      nodes: [
        {
          id: "source-node",
          kind: "builtin",
          operator_id: "source",
          operator_version: 1,
          config: {},
          input_plugs: [],
          artifact_type_bindings: [],
          position: { x: 0, y: 0 },
        },
        {
          id: "collect-node",
          kind: "builtin",
          operator_id: "test.collect",
          operator_version: 1,
          config: {},
          input_plugs: [
            { id: "plug-first", port: "items" },
            { id: "plug-second", port: "items" },
          ],
          artifact_type_bindings: [],
          position: { x: 300, y: 0 },
        },
      ],
      edges: [
        {
          id: "edge",
          from_node: "source-node",
          from_port: "output",
          to_node: "collect-node",
          to_port: "items",
          to_plug: "plug-second",
          enabled: true,
          collection_mode: "direct",
          projection: null,
          conversion_path: [],
          route_offset: { x: 12, y: -4 },
        },
      ],
      presentation: {
        viewers: [],
        links: [],
        bindings: [],
        annotations: [],
      },
    },
  };
}

describe("saved instance plugs", () => {
  it("hydrates plug order and edge targeting", () => {
    const hydrated = hydrateSavedGraph(
      graphWithCollectPlugs(),
      collectRegistry(),
    );
    const collectNode = hydrated.nodes.find((node) => node.id === "collect-node");
    const edge = hydrated.edges[0];

    expect(collectNode?.data.inputPlugs).toEqual([
      { id: "plug-first", portName: "items" },
      { id: "plug-second", portName: "items" },
    ]);
    expect(decodeHandleId(edge?.targetHandle)?.plugId).toBe("plug-second");
  });

  it("rejects an edge that targets a missing plug", () => {
    const graph = graphWithCollectPlugs();
    const edge = graph.document.edges[0];
    const invalidGraph: SavedGraph = {
      ...graph,
      document: {
        ...graph.document,
        edges: edge ? [{ ...edge, to_plug: "plug-missing" }] : [],
      },
    };

    expect(() => hydrateSavedGraph(invalidGraph, collectRegistry())).toThrow(
      "references missing input plug plug-missing",
    );
  });
});

function genericCollectRegistry(): NodeRegistry {
  const collector: NodeSpec = {
    operator_id: "sequence.collect",
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title: "Collect",
    description: "Collect ordered artifacts.",
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [
      {
        name: "items",
        title: "Items",
        description: null,
        direction: "input",
        artifact_type: null,
        artifact_type_variable: "T",
        shape: "one",
        accepted_shapes: ["one", "many"],
        instance_plugs: true,
        variadic: false,
        required: true,
      },
    ],
    outputs: [
      {
        name: "items",
        title: "Items",
        description: null,
        direction: "output",
        artifact_type: null,
        artifact_type_variable: "T",
        shape: "many",
        accepted_shapes: ["many"],
        instance_plugs: false,
        variadic: false,
        required: true,
      },
    ],
  };
  return {
    plugins: [],
    artifact_types: [
      {
        key: { id: "scalar.integer", schema_version: 1 },
        title: "Integer",
        payload_schema: {},
        field_projections: [],
        bundle: { format: "inline-json", version: 1 },
      },
    ],
    artifact_conversions: [],
    nodes: [nodeSpec("source", "output", "scalar.integer"), collector],
  };
}

function graphWithGenericCollectBinding(): SavedGraph {
  return {
    id: "00000000-0000-4000-8000-000000000003",
    revision: 1,
    name: "Generic collect",
    created_at: "2026-07-15T12:00:00Z",
    updated_at: "2026-07-15T12:00:00Z",
    document: {
      schema_version: 7,
      origins: [],
      nodes: [
        {
          id: "source-node",
          kind: "builtin",
          operator_id: "source",
          operator_version: 1,
          config: {},
          input_plugs: [],
          artifact_type_bindings: [],
          position: { x: 0, y: 0 },
        },
        {
          id: "collect-node",
          kind: "builtin",
          operator_id: "sequence.collect",
          operator_version: 1,
          config: {},
          input_plugs: [{ id: "plug-1", port: "items" }],
          artifact_type_bindings: [
            {
              variable: "T",
              artifact_type: { id: "scalar.integer", schema_version: 1 },
            },
          ],
          position: { x: 300, y: 0 },
        },
      ],
      edges: [
        {
          id: "edge",
          from_node: "source-node",
          from_port: "output",
          to_node: "collect-node",
          to_port: "items",
          to_plug: "plug-1",
          enabled: true,
          collection_mode: "direct",
          projection: null,
          conversion_path: [],
          route_offset: null,
        },
      ],
      presentation: {
        viewers: [],
        links: [],
        bindings: [],
        annotations: [],
      },
    },
  };
}

describe("saved generic artifact type bindings", () => {
  it("hydrates bound handles", () => {
    const hydrated = hydrateSavedGraph(
      graphWithGenericCollectBinding(),
      genericCollectRegistry(),
    );
    const collectNode = hydrated.nodes.find((node) => node.id === "collect-node");
    const edge = hydrated.edges[0];

    expect(collectNode?.data.artifactTypeBindings).toEqual({
      T: { id: "scalar.integer", schema_version: 1 },
    });
    expect(decodeHandleId(edge?.targetHandle)).toMatchObject({
      artifactTypeId: "scalar.integer",
      schemaVersion: 1,
      plugId: "plug-1",
    });
  });

  it("marks a binding for an undeclared variable invalid without rejecting the graph", () => {
    const graph = graphWithGenericCollectBinding();
    const invalid: SavedGraph = {
      ...graph,
      document: {
        ...graph.document,
        nodes: graph.document.nodes.map((node) =>
          node.id === "collect-node"
            ? {
                ...node,
                artifact_type_bindings: [
                  {
                    variable: "Missing",
                    artifact_type: {
                      id: "scalar.integer",
                      schema_version: 1,
                    },
                  },
                ],
              }
            : node,
        ),
      },
    };

    const hydrated = hydrateSavedGraph(invalid, genericCollectRegistry());
    const collectNode = hydrated.nodes.find(
      (node) => node.id === "collect-node",
    );
    expect(collectNode?.data.compatibility).toMatchObject({
      status: "invalid",
      issues: [
        "node collect-node binds undeclared artifact type variable Missing",
      ],
    });
  });

  it("marks an unavailable artifact type invalid without rejecting the graph", () => {
    const graph = graphWithGenericCollectBinding();
    const collectNode = graph.document.nodes.find(
      (node) => node.id === "collect-node",
    );
    const invalid: SavedGraph = {
      ...graph,
      document: {
        ...graph.document,
        nodes: collectNode
          ? [
              {
                ...collectNode,
                artifact_type_bindings: [
                  {
                    variable: "T",
                    artifact_type: {
                      id: "artifact.missing",
                      schema_version: 9,
                    },
                  },
                ],
              },
            ]
          : [],
        edges: [],
      },
    };

    const hydrated = hydrateSavedGraph(invalid, genericCollectRegistry());
    expect(hydrated.nodes[0]?.data.compatibility).toMatchObject({
      status: "invalid",
      issues: [
        "node collect-node binds unavailable artifact type artifact.missing@9",
      ],
    });
  });
});

describe("saved graph module nodes", () => {
  const moduleGraphId = "00000000-0000-4000-8000-000000000008";
  const moduleOperatorId = `module.graph.${moduleGraphId}`;
  const imageType = { id: "image.raster", schema_version: 1 } as const;
  const completionType = { id: "llm.completion", schema_version: 1 } as const;
  const moduleInput = {
    name: "image",
    title: "Image",
    description: null,
    direction: "input" as const,
    artifact_type: imageType,
    shape: "one" as const,
    accepted_shapes: ["one" as const],
    instance_plugs: false,
    variadic: false,
    required: true,
  };
  const moduleOutput = {
    name: "completion",
    title: "Completion",
    description: null,
    direction: "output" as const,
    artifact_type: completionType,
    shape: "one" as const,
    accepted_shapes: ["one" as const],
    instance_plugs: false,
    variadic: false,
    required: true,
  };

  function moduleSpec(revision: number, catalogVisible: boolean): NodeSpec {
    return {
      operator_id: moduleOperatorId,
      operator_version: revision,
      plugin_slug: "saved-graph-modules",
      origin: "module",
      title: `Extract image r${revision}`,
      description: "Hidden structured extraction graph",
      config_schema: {},
      input_schema: {},
      output_schema: {},
      inputs: [moduleInput],
      outputs: [moduleOutput],
      module_graph_id: moduleGraphId,
      module_graph_revision: revision,
      catalog_visible: catalogVisible,
      runnable: true,
    };
  }

  it("hydrates the pinned historical revision and exposes mapped outputs as a sequence", () => {
    const sourceSpec = nodeSpec(
      IMAGE_UPLOAD_OPERATOR_ID,
      "output",
      "image.raster",
      "many",
    );
    const savedGraph: SavedGraph = {
      id: "00000000-0000-4000-8000-000000000009",
      revision: 1,
      name: "Map extraction module",
      created_at: "2026-07-16T12:00:00Z",
      updated_at: "2026-07-16T12:00:00Z",
      document: {
        schema_version: 7,
        origins: [],
        nodes: [
          {
            id: "images",
            kind: "builtin",
            operator_id: IMAGE_UPLOAD_OPERATOR_ID,
            operator_version: 1,
            config: {},
            input_plugs: [],
            artifact_type_bindings: [],
            position: { x: 0, y: 0 },
          },
          {
            id: "extract",
            kind: "builtin",
            operator_id: moduleOperatorId,
            operator_version: 1,
            config: {},
            input_plugs: [],
            artifact_type_bindings: [],
            position: { x: 300, y: 0 },
          },
        ],
        edges: [{
          id: "map-images",
          from_node: "images",
          from_port: "output",
          to_node: "extract",
          to_port: "image",
          to_plug: null,
          enabled: true,
          collection_mode: "map",
          projection: null,
          conversion_path: [],
          route_offset: null,
        }],
        presentation: {
          viewers: [],
          links: [],
          bindings: [],
          annotations: [],
        },
      },
    };
    const moduleV1 = moduleSpec(1, false);
    const hydrated = hydrateSavedGraph(savedGraph, {
      plugins: [{
        slug: "saved-graph-modules",
        title: "Modules",
        origin: "module",
        entry_kind: "module",
        runnable: true,
      }],
      artifact_types: [
        {
          key: imageType,
          title: "Image",
          payload_schema: {},
          field_projections: [],
          bundle: { format: "inline-json", version: 1 },
        },
        {
          key: completionType,
          title: "Completion",
          payload_schema: {},
          field_projections: [],
          bundle: { format: "inline-json", version: 1 },
        },
      ],
      artifact_conversions: [],
      nodes: [sourceSpec, moduleV1, moduleSpec(2, true)],
    });
    const moduleNode = hydrated.nodes.find((node) => node.id === "extract");

    expect(moduleNode?.data.spec).toBe(moduleV1);
    expect(moduleNode?.data.spec.module_graph_revision).toBe(1);
    expect(hydrated.edges[0]?.data?.collectionMode).toBe("map");
    expect(
      moduleNode
        ? effectivePortShape(
            { ...moduleNode.data, mappedInputPort: "image" },
            moduleNode.data.spec.outputs[0]!,
          )
        : null,
    ).toBe("many");
  });
});
