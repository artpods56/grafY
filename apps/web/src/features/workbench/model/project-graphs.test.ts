import { describe, expect, it } from "vitest";

import {
  CALL_NODE_OPERATOR_VERSION,
  GRAPH_INPUT_OPERATOR_ID,
  GRAPH_OUTPUT_OPERATOR_ID,
  PROJECT_GRAPHS_PLUGIN_SLUG,
  boundaryNodeSpecs,
  callNodeSpec,
  callableGraphs,
  graphCallers,
  graphDeleteRefusal,
  graphInterface,
  nextBoundaryName,
  registryWithProjectGraphs,
  wouldCreateCycle,
} from "./project-graphs";
import type {
  GraphDefinition,
  NodeRegistry,
  NodeSpec,
  SavedGraphDocument,
  SavedGraphNode,
} from "@/lib/api";

function documentOf(nodes: readonly SavedGraphNode[]): SavedGraphDocument {
  return {
    schema_version: 7,
    nodes,
    edges: [],
    origins: [],
    agents: [],
    presentation: { viewers: [], links: [], bindings: [], annotations: [] },
  };
}

/** A boundary node: one declared input or output of its own Graph. */
function boundary(
  id: string,
  operatorId: typeof GRAPH_INPUT_OPERATOR_ID | typeof GRAPH_OUTPUT_OPERATOR_ID,
  config: Record<string, unknown> = {},
  artifactType: { id: string; schema_version: number } | null = null,
): SavedGraphNode {
  return {
    id,
    kind: "builtin",
    operator_id: operatorId,
    operator_version: 1,
    position: { x: 0, y: 0 },
    config,
    input_plugs: [],
    artifact_type_bindings: artifactType
      ? [{ variable: "T", artifact_type: artifactType }]
      : [],
  };
}

/** A node that places a sibling Graph on the canvas. */
function callNode(id: string, calleeId: string): SavedGraphNode {
  return {
    id,
    kind: "call",
    operator_id: calleeId,
    operator_version: CALL_NODE_OPERATOR_VERSION,
    position: { x: 0, y: 0 },
    config: {},
    input_plugs: [],
    artifact_type_bindings: [],
  };
}

/** An ordinary node: neither boundary nor call, so invisible to the interface. */
function plain(id: string, operatorId = "demo.op"): SavedGraphNode {
  return {
    id,
    kind: "builtin",
    operator_id: operatorId,
    operator_version: 1,
    position: { x: 0, y: 0 },
    config: {},
    input_plugs: [],
    artifact_type_bindings: [],
  };
}

function graph(
  id: string,
  name: string,
  nodes: readonly SavedGraphNode[] = [],
): GraphDefinition {
  return { id, name, document: documentOf(nodes) };
}

function catalogSpec(operatorId: string): NodeSpec {
  return {
    operator_id: operatorId,
    operator_version: 1,
    plugin_slug: "builtin",
    origin: "builtin",
    title: operatorId,
    description: "",
    inputs: [],
    outputs: [],
    config_schema: {},
    input_schema: {},
    output_schema: {},
    runnable: true,
    catalog_visible: true,
  };
}

function registryWith(operatorIds: readonly string[]): NodeRegistry {
  return {
    plugins: [
      {
        entry_kind: "plugin",
        origin: "builtin",
        slug: "builtin",
        title: "Built-in",
      },
    ],
    artifact_types: [],
    artifact_conversions: [],
    nodes: operatorIds.map(catalogSpec),
  };
}

/** The JSON behind a config schema, whose declared type is an open object. */
function schemaProperties(schema: NodeSpec["config_schema"]) {
  return schema.properties as Record<string, unknown>;
}

describe("project-graphs interface", () => {
  it("keeps document order and reads name, required, description and type", () => {
    const iface = graphInterface(
      graph("g", "Main", [
        plain("noise"),
        boundary(
          "in-1",
          GRAPH_INPUT_OPERATOR_ID,
          { public_name: "rows", description: "The rows to read" },
          { id: "table.data", schema_version: 2 },
        ),
        boundary("out-1", GRAPH_OUTPUT_OPERATOR_ID, { public_name: "report" }),
        boundary(
          "in-2",
          GRAPH_INPUT_OPERATOR_ID,
          { public_name: "note", required: false },
          { id: "scalar.text", schema_version: 1 },
        ),
        boundary(
          "out-2",
          GRAPH_OUTPUT_OPERATOR_ID,
          { public_name: "log", description: "What happened" },
          null,
        ),
      ]),
    );

    expect(iface.inputs).toEqual([
      {
        name: "rows",
        artifactType: { id: "table.data", schema_version: 2 },
        required: true,
        description: "The rows to read",
      },
      {
        name: "note",
        artifactType: { id: "scalar.text", schema_version: 1 },
        required: false,
        description: null,
      },
    ]);
    expect(iface.outputs).toEqual([
      {
        name: "report",
        artifactType: null,
        required: true,
        description: null,
      },
      {
        name: "log",
        artifactType: null,
        required: true,
        description: "What happened",
      },
    ]);
  });

  it("is empty for a Graph with no boundary nodes", () => {
    expect(
      graphInterface(graph("g", "Plain", [plain("a"), plain("b", "other.op")])),
    ).toEqual({ inputs: [], outputs: [] });
  });
});

describe("project-graphs calls", () => {
  it("lists every call site of a Graph in graph order then node order", () => {
    const graphs = [
      graph("caller-a", "Caller A", [
        plain("ignored", "callee"),
        callNode("a-2", "callee"),
        callNode("a-1", "callee"),
      ]),
      graph("other", "Other", [plain("x")]),
      graph("caller-b", "Caller B", [callNode("b-1", "callee")]),
      graph("callee", "Callee", [callNode("self", "unrelated")]),
    ];

    expect(graphCallers(graphs, "callee")).toEqual([
      { graphId: "caller-a", nodeId: "a-2" },
      { graphId: "caller-a", nodeId: "a-1" },
      { graphId: "caller-b", nodeId: "b-1" },
    ]);
  });

  it("refuses a call that would make the call relation cyclic", () => {
    const chain = [
      graph("a", "A", [callNode("a-to-b", "b")]),
      graph("b", "B", [callNode("b-to-c", "c")]),
      graph("c", "C"),
    ];
    // A Graph never calls itself.
    expect(wouldCreateCycle(chain, "a", "a")).toBe(true);
    // B calling A would close A -> B -> A.
    expect(wouldCreateCycle(chain, "b", "a")).toBe(true);
    // C calling A would close A -> B -> C -> A.
    expect(wouldCreateCycle(chain, "c", "a")).toBe(true);

    const diamond = [
      graph("a", "A", [callNode("a-to-b", "b"), callNode("a-to-c", "c")]),
      graph("b", "B"),
      graph("c", "C"),
    ];
    // B calling C is the other half of a diamond, not a cycle.
    expect(wouldCreateCycle(diamond, "b", "c")).toBe(false);
  });

  it("offers the siblings a Graph may call, in graph order", () => {
    const graphs = [
      graph("a", "A"),
      graph("b", "B"),
      graph("c", "C", [callNode("c-to-a", "a")]),
      graph("d", "D", [callNode("d-to-b", "b")]),
    ];
    // D calls B, so B cannot call it back; C only reaches A, so it may.
    expect(
      callableGraphs(graphs, "b").map((candidate) => candidate.id),
    ).toEqual(["a", "c"]);
    // The same rule from A's side: C calls A, so A cannot call C.
    expect(
      callableGraphs(graphs, "a").map((candidate) => candidate.id),
    ).toEqual(["b", "d"]);
  });

  it("refuses to delete a Graph that is still called, naming its callers", () => {
    const graphs = [
      graph("one", "One", [callNode("one-to-target", "target")]),
      graph("two", "Two", [
        callNode("two-to-target-1", "target"),
        callNode("two-to-target-2", "target"),
      ]),
      graph("target", "Target"),
      graph("free", "Free"),
    ];

    expect(graphDeleteRefusal(graphs, "free")).toBeNull();
    expect(graphDeleteRefusal(graphs, "no-such-graph")).toBeNull();
    expect(graphDeleteRefusal(graphs, "one")).toBeNull();

    expect(graphDeleteRefusal(graphs, "two")).toBeNull();

    expect(graphDeleteRefusal(graphs, "target")).toBe(
      "“Target” is still called from “One”, “Two”. Remove those call nodes first.",
    );

    const once = [
      graph("solo", "Solo", [
        callNode("solo-to-target-1", "target"),
        callNode("solo-to-target-2", "target"),
      ]),
      graph("target", "Target"),
    ];
    expect(graphDeleteRefusal(once, "target")).toBe(
      "“Target” is still called from “Solo”. Remove those call nodes first.",
    );

    // A call node inside the Graph itself is not a caller of it.
    const selfish = [graph("target", "Target", [callNode("own", "target")])];
    expect(graphDeleteRefusal(selfish, "target")).toBeNull();
  });
});

describe("project-graphs boundary names", () => {
  it("picks a name that direction does not use yet", () => {
    expect(nextBoundaryName(graph("g", "Main"), "input")).toBe("input");
    expect(nextBoundaryName(graph("g", "Main"), "output")).toBe("output");

    const taken = graph("g", "Main", [
      boundary("in-1", GRAPH_INPUT_OPERATOR_ID, { public_name: "input" }),
    ]);
    expect(nextBoundaryName(taken, "input")).toBe("input_2");
    // The other direction is unaffected by what inputs are called.
    expect(nextBoundaryName(taken, "output")).toBe("output");

    const moreTaken = graph("g", "Main", [
      boundary("in-1", GRAPH_INPUT_OPERATOR_ID, { public_name: "input" }),
      boundary("in-2", GRAPH_INPUT_OPERATOR_ID, { public_name: "input_2" }),
      boundary("out-1", GRAPH_OUTPUT_OPERATOR_ID, { public_name: "output" }),
    ]);
    expect(nextBoundaryName(moreTaken, "input")).toBe("input_3");
    expect(nextBoundaryName(moreTaken, "output")).toBe("output_2");
  });
});

describe("project-graphs specs", () => {
  it("describes the two boundary operators", () => {
    const specs = boundaryNodeSpecs();
    const [input, output] = specs;

    expect(specs.map((spec) => spec.operator_id)).toEqual([
      GRAPH_INPUT_OPERATOR_ID,
      GRAPH_OUTPUT_OPERATOR_ID,
    ]);
    for (const spec of specs) {
      expect(spec.plugin_slug).toBe(PROJECT_GRAPHS_PLUGIN_SLUG);
      expect(spec.origin).toBe("builtin");
      expect(spec.operator_version).toBe(1);
      expect(spec.catalog_visible).toBe(true);
      expect(spec.runnable).toBe(true);
      expect(spec.input_schema).toEqual({});
      expect(spec.output_schema).toEqual({});
    }

    // An input node produces its Graph's input, an output node consumes one.
    expect(input?.inputs).toEqual([]);
    expect(input?.outputs.map((port) => [port.name, port.direction])).toEqual([
      ["value", "output"],
    ]);
    expect(output?.inputs.map((port) => [port.name, port.direction])).toEqual([
      ["value", "input"],
    ]);
    expect(output?.outputs).toEqual([]);
    expect(input?.outputs[0]?.artifact_type_variable).toBe("T");

    expect(schemaProperties(input?.config_schema ?? {}).required).toBeDefined();
    expect(
      schemaProperties(output?.config_schema ?? {}).required,
    ).toBeUndefined();
  });

  it("shows a call node as the callee's interface", () => {
    const callee = graph("callee", "Callee", [
      boundary(
        "in-1",
        GRAPH_INPUT_OPERATOR_ID,
        { public_name: "rows" },
        {
          id: "table.data",
          schema_version: 2,
        },
      ),
      boundary("in-2", GRAPH_INPUT_OPERATOR_ID, {
        public_name: "note",
        required: false,
        description: "Optional note",
      }),
      boundary(
        "out-1",
        GRAPH_OUTPUT_OPERATOR_ID,
        { public_name: "report" },
        {
          id: "scalar.text",
          schema_version: 1,
        },
      ),
    ]);

    const spec = callNodeSpec(callee, true);
    expect(spec.operator_id).toBe("callee");
    expect(spec.operator_version).toBe(CALL_NODE_OPERATOR_VERSION);
    expect(spec.plugin_slug).toBe(PROJECT_GRAPHS_PLUGIN_SLUG);
    expect(spec.title).toBe("Callee");
    expect(spec.description).toBe("Runs the Graph “Callee” as one step.");
    expect(spec.config_schema).toEqual({});
    expect(spec.catalog_visible).toBe(true);

    expect(spec.inputs).toEqual([
      {
        name: "rows",
        title: "rows",
        description: null,
        direction: "input",
        artifact_type: { id: "table.data", schema_version: 2 },
        artifact_type_variable: null,
        shape: "one",
        accepted_shapes: ["one"],
        instance_plugs: false,
        variadic: false,
        required: true,
      },
      {
        name: "note",
        title: "note",
        description: "Optional note",
        direction: "input",
        artifact_type: null,
        artifact_type_variable: null,
        shape: "one",
        accepted_shapes: ["one"],
        instance_plugs: false,
        variadic: false,
        required: false,
      },
    ]);
    expect(spec.outputs).toEqual([
      {
        name: "report",
        title: "report",
        description: null,
        direction: "output",
        artifact_type: { id: "scalar.text", schema_version: 1 },
        artifact_type_variable: null,
        shape: "one",
        accepted_shapes: ["one"],
        instance_plugs: false,
        variadic: false,
        required: true,
      },
    ]);

    expect(callNodeSpec(callee, false).catalog_visible).toBe(false);
  });

  it("adds the Project's Graphs to the registry without touching the input", () => {
    const graphs = [
      graph("open", "Open"),
      graph("visible", "Visible"),
      graph("blocked", "Blocked", [callNode("blocked-to-open", "open")]),
    ];
    const registry = registryWith(["demo.op"]);
    const before = registry.nodes.length;

    const withGraphs = registryWithProjectGraphs(registry, graphs, "open");
    const added = withGraphs.nodes.slice(before);

    expect(withGraphs).not.toBe(registry);
    expect(registry.nodes.length).toBe(before);
    expect(withGraphs.plugins).toHaveLength(2);
    expect(withGraphs.plugins[1]?.slug).toBe(PROJECT_GRAPHS_PLUGIN_SLUG);

    expect(added.map((spec) => spec.operator_id)).toEqual([
      GRAPH_INPUT_OPERATOR_ID,
      GRAPH_OUTPUT_OPERATOR_ID,
      "visible",
      "blocked",
    ]);
    const visibility = new Map(
      added.map((spec) => [spec.operator_id, spec.catalog_visible]),
    );
    expect(visibility.get("visible")).toBe(true);
    // Blocked reaches the open Graph, so calling it back would be a cycle.
    expect(visibility.get("blocked")).toBe(false);

    // Re-projecting the result adds the plugin entry once.
    const again = registryWithProjectGraphs(withGraphs, graphs, "open");
    expect(
      again.plugins.filter(
        (plugin) => plugin.slug === PROJECT_GRAPHS_PLUGIN_SLUG,
      ),
    ).toHaveLength(1);

    // With no Graph open nothing is offered, but every Graph is still described.
    const nothingOpen = registryWithProjectGraphs(registry, graphs, null);
    expect(
      nothingOpen.nodes
        .slice(before)
        .filter((spec) => spec.operator_id !== GRAPH_INPUT_OPERATOR_ID)
        .filter((spec) => spec.operator_id !== GRAPH_OUTPUT_OPERATOR_ID)
        .map((spec) => [spec.operator_id, spec.catalog_visible]),
    ).toEqual([
      ["open", false],
      ["visible", false],
      ["blocked", false],
    ]);
  });
});
