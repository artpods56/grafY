import { describe, expect, it } from "vitest";

import type {
  ArtifactConversionSpec,
  GraphDefinition,
  NodeRegistry,
  NodeSpec,
  Port,
  SavedGraph,
  SavedGraphDocument,
  SavedGraphEdge,
  SavedGraphNode,
} from "@/lib/api";
import { artifactPortFixture, nodeSpecFixture } from "../test-fixtures";
import { registryWithProjectGraphs } from "./project-graphs";
import { decodeHandleId } from "./handles";
import {
  hydrateSavedGraph,
  savedGraphExecutionFingerprint,
  savedGraphFingerprint,
} from "./saved-graph";
import { serializeRunNode, serializeWorkflowEdgeTransport } from "./types";

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
  const port = artifactPortFixture({
    name: direction,
    direction,
    artifact_type: { id: artifactTypeId, schema_version: 1 },
    shape,
    accepted_shapes: acceptedShapes,
  });
  return nodeSpecFixture({
    operator_id: operatorId,
    description: operatorId,
    inputs: direction === "input" ? [port] : [],
    outputs: direction === "output" ? [port] : [],
  });
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
      nodeSpec("target", "input", "z", targetShape, targetAcceptedShapes),
    ],
  };
}

function graphWithEdge(
  edgeConversion: Pick<SavedGraphDocument["edges"][number], "conversion_path">,
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
      agents: [],
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

function graphWithCollectionMode(collectionMode: "direct" | "map"): SavedGraph {
  const graph = graphWithEdge({ conversion_path: conversionPath });
  return {
    ...graph,
    document: {
      ...graph.document,
      edges: graph.document.edges.map((edge: SavedGraphEdge) => ({
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

describe("unavailable saved operators", () => {
  it("hydrates a placeholder and preserves its incident connection", () => {
    const base = graphWithEdge({ conversion_path: conversionPath });
    const graph: SavedGraph = {
      ...base,
      document: {
        ...base.document,
        nodes: base.document.nodes.map((node: SavedGraphNode) =>
          node.id === "source-node"
            ? {
                ...node,
                operator_id: "python.transform",
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
        (spec) => spec.operator_id !== "python.transform",
      ),
    });
    const sourceNode = hydrated.nodes.find((node) => node.id === "source-node");
    const edge = hydrated.edges[0];

    expect(sourceNode?.data.compatibility).toMatchObject({
      status: "unsupported",
      outputs: [{ portName: "output" }],
    });
    expect(sourceNode?.data.compatibility).toHaveProperty(
      "issues.0",
      "Operator python.transform@1 is unavailable. This saved node is preserved but cannot run.",
    );
    expect(sourceNode?.data.layout).toBeNull();
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
        nodes: base.document.nodes.map((node: SavedGraphNode, index: number) =>
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
  it("hydrates an enabled edge and keeps enablement out of run transport", () => {
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
    const enabledGraph = graphWithEdge({ conversion_path: conversionPath });
    const disabledGraph: SavedGraph = {
      ...enabledGraph,
      document: {
        ...enabledGraph.document,
        edges: enabledGraph.document.edges.map((edge: SavedGraphEdge) => ({
          ...edge,
          enabled: false,
        })),
      },
    };
    const disabled = hydrateSavedGraph(disabledGraph, registry());
    const enabledDraft = {
      name: "Edge state",
      document: enabledGraph.document,
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
          viewers: [
            {
              id: "viewer-1",
              position: { x: 1, y: 2 },
            },
          ],
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
    expect(decodeHandleId(hydrated.edges[0]?.sourceHandle)?.shape).toBe("many");
  });

  it("hydrates a map edge from a many source into a one target", () => {
    const hydrated = hydrateSavedGraph(
      graphWithCollectionMode("map"),
      registry("many", "one"),
    );

    expect(hydrated.edges[0]?.data?.collectionMode).toBe("map");
    expect(decodeHandleId(hydrated.edges[0]?.sourceHandle)?.shape).toBe("many");
    expect(decodeHandleId(hydrated.edges[0]?.targetHandle)?.shape).toBe("one");
  });

  it("hydrates a map edge from a many source into a many target", () => {
    const hydrated = hydrateSavedGraph(
      graphWithCollectionMode("map"),
      registry("many", "many"),
    );

    expect(hydrated.edges[0]?.data?.collectionMode).toBe("map");
    expect(decodeHandleId(hydrated.edges[0]?.targetHandle)?.shape).toBe("many");
  });

  it("hydrates map edges on different inputs and rejects duplicate drivers", () => {
    const sourceSpec = nodeSpec("source", "output", "x", "many");
    const otherSourceSpec = nodeSpec("other-source", "output", "x", "many");
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

    const hydrated = hydrateSavedGraph(invalidGraph, testRegistry);
    expect(hydrated.edges.map((edge) => edge.data?.collectionMode)).toEqual([
      "map",
      "map",
    ]);
    expect(() =>
      hydrateSavedGraph(
        {
          ...invalidGraph,
          document: {
            ...invalidGraph.document,
            edges: invalidGraph.document.edges.map((edge: SavedGraphEdge) => ({
              ...edge,
              to_port: "left",
            })),
          },
        },
        testRegistry,
      ),
    ).toThrow(
      "Cannot open “Conversion path”. A connection uses a list mode this input does not accept.",
    );
  });

  it.each([1, 2])(
    "hydrates downstream sequence edges from a node with %i map inputs",
    (driverCount) => {
      const graph = graphWithCollectionMode("map");
      const sourceNode = graph.document.nodes[0];
      const targetNode = graph.document.nodes[1];
      const edge = graph.document.edges[0];
      if (!sourceNode || !targetNode || !edge)
        throw new Error("map-edge fixture is incomplete");
      const targetSpec = nodeSpec("target", "input", "z");
      const targetInput = targetSpec.inputs[0];
      if (!targetInput) throw new Error("target input is missing");
      const testRegistry: NodeRegistry = {
        ...registry("many", "one"),
        nodes: [
          nodeSpec("source", "output", "x", "many"),
          {
            ...targetSpec,
            inputs: [
              { ...targetInput, name: "left" },
              { ...targetInput, name: "right", required: false },
            ],
            outputs: nodeSpec("target", "output", "z").outputs,
          },
          nodeSpec("sink", "input", "z", "many"),
        ],
      };
      const mapEdges = [{ ...edge, id: "map-left", to_port: "left" }];
      if (driverCount === 2)
        mapEdges.push({ ...edge, id: "map-right", to_port: "right" });
      const hydrated = hydrateSavedGraph(
        {
          ...graph,
          document: {
            ...graph.document,
            nodes: [
              sourceNode,
              targetNode,
              { ...targetNode, id: "sink-node", operator_id: "sink" },
            ],
            edges: [
              ...mapEdges,
              {
                ...edge,
                id: "downstream",
                from_node: targetNode.id,
                to_node: "sink-node",
                to_port: "input",
                collection_mode: "direct",
                conversion_path: [],
              },
            ],
          },
        },
        testRegistry,
      );
      const downstream = hydrated.edges.find(
        (edge) => edge.id === "downstream",
      );
      expect(decodeHandleId(downstream?.sourceHandle)?.shape).toBe("many");
      expect(downstream?.data?.collectionMode).toBe("direct");
    },
  );

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
      targetShape: "one" as const,
      targetAcceptedShapes: ["one", "many"] as const,
      expectedMode: "direct",
    },
  ])(
    "rejects $collectionMode for $sourceShape → $targetShape when new connections require $expectedMode",
    ({ collectionMode, sourceShape, targetShape, targetAcceptedShapes }) => {
      expect(() =>
        hydrateSavedGraph(
          graphWithCollectionMode(collectionMode),
          registry(sourceShape, targetShape, targetAcceptedShapes),
        ),
      ).toThrow("A connection uses a list mode this input does not accept.");
    },
  );

  it("keeps a graph whose sequence feed was removed openable", () => {
    const graph = mappedStepGraph([ocrPageEdge(), ocrReadingEdge()]);

    expect(() => hydrateSavedGraph(graph, mappedStepRegistry())).not.toThrow();

    const hydrated = hydrateSavedGraph(graph, mappedStepRegistry());
    const reading = hydrated.edges.find((edge) => edge.id === "reading");
    expect(reading?.data?.collectionMode).toBe("direct");
    expect(decodeHandleId(reading?.sourceHandle)?.shape).toBe("one");
    const page = hydrated.edges.find((edge) => edge.id === "page");
    expect(page?.data?.collectionMode).toBe("map");
  });

  it("leaves the modes of a graph that still runs its step per item alone", () => {
    const graph = mappedStepGraph([
      sequenceFeedEdge(),
      ocrPageEdge(),
      ocrReadingEdge(),
    ]);

    const hydrated = hydrateSavedGraph(graph, mappedStepRegistry());

    expect(
      hydrated.edges.map((edge) => [edge.id, edge.data?.collectionMode]),
    ).toEqual([
      ["feed", "map"],
      ["page", "map"],
      ["reading", "map"],
    ]);
  });
});

/** A port that says what it carries, which the handle of a connection needs. */
function portSpec(
  direction: "input" | "output",
  name: string,
  artifactId: string,
  shape: "one" | "many" = "one",
): Port {
  const built = nodeSpec(name, direction, artifactId, shape);
  const builtPort = direction === "input" ? built.inputs[0] : built.outputs[0];
  if (!builtPort) throw new Error("port fixture has no port");
  return {
    ...builtPort,
    name,
    artifact_type: { id: artifactId, schema_version: 1 },
  };
}

function stepSpec(
  operatorId: string,
  inputs: readonly Port[],
  outputs: readonly Port[],
): NodeSpec {
  const built = nodeSpec(operatorId, "input", "page");
  return { ...built, inputs: [...inputs], outputs: [...outputs] };
}

/** Pages, an OCR step that reads them, and the step that paints boxes on them. */
function mappedStepRegistry(): NodeRegistry {
  return {
    plugins: [],
    artifact_types: ["page", "markdown", "boxes"].map((id) => ({
      key: { id, schema_version: 1 },
      title: id,
      payload_schema: {},
      field_projections: [],
      bundle: { format: "inline-json", version: 1 },
    })),
    artifact_conversions: [],
    nodes: [
      stepSpec("test.pages", [], [portSpec("output", "items", "page", "many")]),
      stepSpec(
        "test.ocr",
        [portSpec("input", "document", "page")],
        [
          portSpec("output", "markdown", "markdown"),
          portSpec("output", "regions", "boxes"),
        ],
      ),
      stepSpec(
        "test.boxes",
        [
          portSpec("input", "image", "page"),
          portSpec("input", "regions", "boxes"),
        ],
        [portSpec("output", "image", "page")],
      ),
    ],
  };
}

function savedStep(id: string, operatorId: string, x: number): SavedGraphNode {
  return {
    id,
    kind: "builtin",
    operator_id: operatorId,
    operator_version: 1,
    config: {},
    input_plugs: [],
    artifact_type_bindings: [],
    position: { x, y: 0 },
  };
}

function savedConnection(
  id: string,
  fromNode: string,
  fromPort: string,
  toNode: string,
  toPort: string,
  collectionMode: "direct" | "map",
): SavedGraphEdge {
  return {
    id,
    enabled: true,
    from_node: fromNode,
    from_port: fromPort,
    to_node: toNode,
    to_port: toPort,
    to_plug: null,
    collection_mode: collectionMode,
    projection: null,
    route_offset: null,
    conversion_path: [],
  };
}

const sequenceFeedEdge = () =>
  savedConnection("feed", "pages", "items", "ocr", "document", "map");
const ocrPageEdge = () =>
  savedConnection("page", "pages", "items", "boxes", "image", "map");
const ocrReadingEdge = () =>
  savedConnection("reading", "ocr", "regions", "boxes", "regions", "map");

function mappedStepGraph(edges: readonly SavedGraphEdge[]): SavedGraph {
  return {
    id: "00000000-0000-4000-8000-000000000002",
    revision: 1,
    name: "Readings",
    created_at: "2026-07-15T12:00:00Z",
    updated_at: "2026-07-15T12:00:00Z",
    document: {
      schema_version: 7,
      origins: [],
      agents: [],
      nodes: [
        savedStep("pages", "test.pages", 0),
        savedStep("ocr", "test.ocr", 300),
        savedStep("boxes", "test.boxes", 600),
      ],
      edges: [...edges],
      presentation: { viewers: [], links: [], bindings: [], annotations: [] },
    },
  };
}

function collectRegistry(): NodeRegistry {
  const source = nodeSpec("source", "output", "text");
  const collector: NodeSpec = nodeSpecFixture({
    operator_id: "test.collect",
    title: "Collect text",
    description: "Collect ordered text inputs.",
    inputs: [
      artifactPortFixture({
        name: "items",
        title: "Items",
        direction: "input",
        artifact_type: { id: "text", schema_version: 1 },
        shape: "many",
        accepted_shapes: ["one", "many"],
        instance_plugs: true,
      }),
    ],
  });
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
      agents: [],
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
    const collectNode = hydrated.nodes.find(
      (node) => node.id === "collect-node",
    );
    const edge = hydrated.edges[0];

    expect(collectNode?.data.inputPlugs).toEqual([
      { id: "plug-first", portName: "items" },
      { id: "plug-second", portName: "items" },
    ]);
    expect(decodeHandleId(edge?.targetHandle)?.plugId).toBe("plug-second");
  });

  it("rejects a node with two plugs of one id without naming either", () => {
    const graph = graphWithCollectPlugs();
    const nodes = graph.document.nodes.map((node: SavedGraphNode) =>
      node.id === "collect-node"
        ? {
            ...node,
            input_plugs: node.input_plugs.map((plug, index) =>
              index === 1 ? { ...plug, id: "plug-first" } : plug,
            ),
          }
        : node,
    );
    const invalidGraph: SavedGraph = {
      ...graph,
      document: { ...graph.document, nodes },
    };

    const hydrated = hydrateSavedGraph(invalidGraph, collectRegistry());
    const compatibility = hydrated.nodes.find(
      (node) => node.id === "collect-node",
    )?.data.compatibility;
    if (compatibility?.status !== "invalid") {
      throw new Error("a duplicated plug id must mark the step invalid");
    }

    expect(compatibility.issues).toEqual([
      "A step has two slots with the same identity.",
    ]);
    expect(compatibility.issues.join(" ")).not.toContain("plug-first");
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
      "A connection points at a slot that was removed.",
    );
  });
});

function genericCollectRegistry(): NodeRegistry {
  const collector: NodeSpec = nodeSpecFixture({
    operator_id: "sequence.collect",
    title: "Collect",
    description: "Collect ordered artifacts.",
    inputs: [
      artifactPortFixture({
        name: "items",
        title: "Items",
        direction: "input",
        artifact_type: null,
        artifact_type_variable: "T",
        accepted_shapes: ["one", "many"],
        instance_plugs: true,
      }),
    ],
    outputs: [
      artifactPortFixture({
        name: "items",
        title: "Items",
        direction: "output",
        artifact_type: null,
        artifact_type_variable: "T",
        shape: "many",
      }),
    ],
  });
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
      agents: [],
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
    const collectNode = hydrated.nodes.find(
      (node) => node.id === "collect-node",
    );
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
        nodes: graph.document.nodes.map((node: SavedGraphNode) =>
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
      issues: ["A step’s type is not available."],
    });
  });

  it("marks an unavailable artifact type invalid without rejecting the graph", () => {
    const graph = graphWithGenericCollectBinding();
    const collectNode = graph.document.nodes.find(
      (node: SavedGraphNode) => node.id === "collect-node",
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
      issues: ["A step’s type is not available."],
    });
  });
});

describe("saved Module nodes", () => {
  const moduleGraphId = "00000000-0000-4000-8000-000000000008";
  const moduleOperatorId = `module.graph.${moduleGraphId}`;

  function graphWithModuleNode(
    node: SavedGraphDocument["nodes"][number],
  ): SavedGraph {
    return {
      id: "00000000-0000-4000-8000-000000000009",
      revision: 1,
      name: "Graph that still holds a Module call",
      created_at: "2026-07-16T12:00:00Z",
      updated_at: "2026-07-16T12:00:00Z",
      document: {
        schema_version: 7,
        origins: [],
        agents: [],
        nodes: [
          {
            id: "images",
            kind: "builtin" as const,
            operator_id: "image.crop_regions",
            operator_version: 1,
            config: {},
            input_plugs: [],
            artifact_type_bindings: [],
            position: { x: 0, y: 0 },
          },
          node,
        ],
        edges: [
          {
            id: "map-images",
            from_node: "images",
            from_port: "output",
            to_node: "extract",
            to_port: "image",
            to_plug: null,
            enabled: true,
            collection_mode: "direct" as const,
            projection: null,
            conversion_path: [],
            route_offset: null,
          },
        ],
        presentation: { viewers: [], links: [], bindings: [], annotations: [] },
      },
    };
  }

  function storedModuleNode(
    kind: SavedGraphDocument["nodes"][number]["kind"],
  ): SavedGraphDocument["nodes"][number] {
    return {
      id: "extract",
      kind,
      operator_id: moduleOperatorId,
      operator_version: 1,
      config: {},
      input_plugs: [],
      artifact_type_bindings: [],
      position: { x: 300, y: 0 },
    };
  }

  function moduleRegistry(spec: NodeSpec | null): NodeRegistry {
    return {
      plugins: [
        {
          slug: "builtin",
          title: "Built-in",
          origin: "builtin",
          entry_kind: "plugin",
        },
      ],
      artifact_types: ["x"].map((id) => ({
        key: { id, schema_version: 1 },
        title: id,
        payload_schema: {},
        field_projections: [],
        bundle: { format: "inline-json" as const, version: 1 },
      })),
      artifact_conversions: [],
      nodes: [
        nodeSpec("image.crop_regions", "output", "x"),
        ...(spec ? [spec] : []),
      ],
    };
  }

  it("keeps a stored Module node openable, unsupported and unable to run", () => {
    const hydrated = hydrateSavedGraph(
      graphWithModuleNode(storedModuleNode("module")),
      moduleRegistry(null),
    );
    const moduleNode = hydrated.nodes.find((node) => node.id === "extract");
    const edge = hydrated.edges[0];

    // The document stays openable: nothing was dropped when hydrating.
    expect(hydrated.nodes.map((node) => node.id)).toEqual([
      "images",
      "extract",
    ]);
    expect(moduleNode?.data.compatibility).toMatchObject({
      status: "unsupported",
    });
    expect(moduleNode?.data.compatibility).toHaveProperty(
      "issues.0",
      `Operator ${moduleOperatorId}@1 is a Module, a node type that is no longer supported. This saved node is preserved but cannot run.`,
    );
    expect(moduleNode?.data.spec.runnable).toBe(false);
    expect(moduleNode?.data.spec.origin).toBe("builtin");
    expect(edge?.targetHandle).toContain("$compatibility::input");

    // Preserved means preserved: it cannot be sent to execution.
    expect(() => serializeRunNode("extract", moduleNode!.data)).toThrow(
      /unsupported node extract/,
    );
  });

  it("refuses to run a stored Module node even when an operator shares its id", () => {
    const sameIdentity = nodeSpec(moduleOperatorId, "output", "x");
    const hydrated = hydrateSavedGraph(
      graphWithModuleNode(storedModuleNode("module")),
      moduleRegistry(sameIdentity),
    );
    const moduleNode = hydrated.nodes.find((node) => node.id === "extract");

    expect(moduleNode?.data.compatibility).toMatchObject({
      status: "unsupported",
    });
    expect(moduleNode?.data.compatibility).toHaveProperty(
      "issues.0",
      `Operator ${moduleOperatorId}@1 is a Module, a node type that is no longer supported. This saved node is preserved but cannot run.`,
    );
  });

  it("hydrates a call node through the ordinary operator lookup", () => {
    const hydrated = hydrateSavedGraph(
      graphWithModuleNode({ ...storedModuleNode("call"), kind: "call" }),
      moduleRegistry(null),
    );
    const callNode = hydrated.nodes.find((node) => node.id === "extract");

    expect(callNode?.data.compatibility).toHaveProperty(
      "issues.0",
      `Operator ${moduleOperatorId}@1 is unavailable. This saved node is preserved but cannot run.`,
    );
  });
});

describe("call nodes whose callee interface moved", () => {
  it("keeps the connection and marks the call node invalid instead of refusing the Graph", () => {
    const base = graphWithEdge({ conversion_path: conversionPath });
    const liveRegistry = registry();
    // The callee now declares `fresh`; the saved edge still targets `input`.
    const callee: GraphDefinition = {
      id: "callee",
      name: "Callee",
      document: {
        schema_version: 7,
        origins: [],
        agents: [],
        edges: [],
        presentation: { viewers: [], links: [], bindings: [], annotations: [] },
        nodes: [
          {
            id: "in",
            kind: "builtin",
            operator_id: "graph.input",
            operator_version: 1,
            config: { public_name: "fresh" },
            input_plugs: [],
            artifact_type_bindings: [
              { variable: "T", artifact_type: { id: "z", schema_version: 1 } },
            ],
            position: { x: 0, y: 0 },
          },
        ],
      },
    };
    const graph: SavedGraph = {
      ...base,
      document: {
        ...base.document,
        nodes: base.document.nodes.map((node: SavedGraphNode) =>
          node.id === "target-node"
            ? { ...node, kind: "call", operator_id: "callee" }
            : node,
        ),
        edges: base.document.edges.map((edge: SavedGraphEdge) => ({
          ...edge,
          conversion_path: [],
        })),
      },
    };

    const hydrated = hydrateSavedGraph(
      graph,
      registryWithProjectGraphs(liveRegistry, [callee], "other"),
    );

    const callNode = hydrated.nodes.find((node) => node.id === "target-node");
    expect(callNode?.data.compatibility).toMatchObject({
      status: "invalid",
      issues: ["Input “input” no longer exists on “Callee”."],
    });
    expect(hydrated.edges).toHaveLength(1);
    expect(hydrated.edges[0]?.data?.compatibilityIssues).toHaveLength(1);
  });
});
