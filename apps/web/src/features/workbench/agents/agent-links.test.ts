import { describe, expect, it } from "vitest";

import type {
  NodeRegistry,
  NodeSpec,
  Port,
  SavedGraphAgent,
  SavedGraphNode,
} from "@/lib/api";
import {
  newToolLink,
  openInputPorts,
  toolPortChoices,
  uniqueToolName,
  withContext,
  withoutContext,
  withoutTool,
  withTool,
  withUpdatedTool,
  nodeOutputContext,
  type LinkableDocument,
} from "./agent-links";

function port(name: string, direction: Port["direction"], type: string): Port {
  return {
    name,
    title: name,
    description: null,
    direction,
    artifact_type: { id: type, schema_version: 1 },
    artifact_type_variable: null,
    shape: "one",
    accepted_shapes: ["one"],
    instance_plugs: false,
    variadic: false,
    required: true,
  };
}

const spec: NodeSpec = {
  operator_id: "search",
  operator_version: 1,
  plugin_slug: "test",
  origin: "builtin",
  title: "Search the letters",
  description: "",
  config_schema: {},
  input_schema: {},
  output_schema: {},
  catalog_visible: true,
  runnable: true,
  inputs: [
    port("query", "input", "scalar.text"),
    port("limit", "input", "scalar.integer"),
    port("rows", "input", "table.data"),
    { ...port("url", "input", "scalar.text"), agent_default: "hidden" },
  ],
  outputs: [
    port("text", "output", "scalar.text"),
    port("count", "output", "scalar.integer"),
  ],
};

function artifactType(id: string, json: "string" | "integer" | null) {
  return {
    key: { id, schema_version: 1 },
    title: id,
    payload_schema: {},
    field_projections: [],
    bundle: { format: "inline-json", version: 1 },
    ...(json ? { materialized_json_type: json } : {}),
  };
}

const registry = {
  plugins: [],
  artifact_conversions: [],
  nodes: [spec],
  artifact_types: [
    artifactType("scalar.text", "string"),
    artifactType("scalar.integer", "integer"),
    artifactType("table.data", null),
  ],
} as unknown as NodeRegistry;

function node(id = "search"): SavedGraphNode {
  return {
    id,
    kind: "builtin",
    operator_id: "search",
    operator_version: 1,
    config: {},
    input_plugs: [],
    artifact_type_bindings: [],
    position: { x: 0, y: 0 },
  };
}

const emptyDocument: LinkableDocument = {
  nodes: [node()],
  edges: [],
  origins: [],
};

function agent(patch: Partial<SavedGraphAgent> = {}): SavedGraphAgent {
  return {
    id: "a",
    name: "Agent",
    instructions: "",
    context: [],
    tools: [],
    width: 360,
    height: 480,
    ...patch,
  } as SavedGraphAgent;
}

describe("open inputs", () => {
  it("lists every input with nothing wired to it and no value held on it", () => {
    expect(openInputPorts(node(), spec, emptyDocument)).toEqual([
      "query",
      "limit",
      "rows",
      "url",
    ]);
  });

  it("skips an input an enabled edge feeds, but not one a disabled edge touches", () => {
    const edge = (id: string, enabled: boolean, toPort: string) =>
      ({
        id,
        enabled,
        from_node: "other",
        from_port: "text",
        to_node: "search",
        to_port: toPort,
        to_plug: null,
        collection_mode: "direct",
        projection: null,
        route_offset: null,
        conversion_path: [],
      }) as unknown as LinkableDocument["edges"][number];
    const document: LinkableDocument = {
      nodes: [node()],
      edges: [edge("e1", true, "query"), edge("e2", false, "limit")],
    };

    expect(openInputPorts(node(), spec, document)).toEqual([
      "limit",
      "rows",
      "url",
    ]);
  });

  it("skips an input that holds a value", () => {
    const document: LinkableDocument = {
      nodes: [node()],
      edges: [],
      origins: [
        { id: "o", to_node: "search", to_port: "rows" },
      ] as unknown as LinkableDocument["origins"],
    };

    expect(openInputPorts(node(), spec, document)).not.toContain("rows");
  });
});

describe("a node's tool link", () => {
  it("starts by offering the open inputs a model can write, minus the ones the operator hides", () => {
    const link = newToolLink(agent(), node(), spec, emptyDocument, registry);

    expect(link.node_id).toBe("search");
    expect(link.name).toBe("search_the_letters");
    expect(link.filled_ports).toEqual(["query", "limit"]);
    expect(link.returned_ports).toEqual([]);
    expect(link.id).toMatch(/^tool-/);
  });

  it("explains every input that cannot be offered", () => {
    const link = newToolLink(agent(), node(), spec, emptyDocument, registry);

    const { inputs, outputs } = toolPortChoices(
      link,
      node(),
      spec,
      emptyDocument,
      registry,
    );

    expect(
      inputs.map((input) => [input.name, input.filled, input.offerable]),
    ).toEqual([
      ["query", true, true],
      ["limit", true, true],
      ["rows", false, false],
      ["url", false, true],
    ]);
    expect(inputs.find((input) => input.name === "rows")?.reason).toBe(
      "A model can only write text or numbers",
    );
    // None named means all returned.
    expect(outputs.map((output) => output.returned)).toEqual([true, true]);
  });

  it("an input the Graph already feeds is not offerable", () => {
    const document: LinkableDocument = {
      nodes: [node()],
      edges: [],
      origins: [
        { id: "o", to_node: "search", to_port: "query" },
      ] as unknown as LinkableDocument["origins"],
    };
    const link = newToolLink(agent(), node(), spec, document, registry);

    expect(link.filled_ports).toEqual(["limit"]);
    const { inputs } = toolPortChoices(link, node(), spec, document, registry);
    expect(inputs[0]).toMatchObject({
      offerable: false,
      reason: "Already fed by the Graph",
    });
  });

  it("named outputs are the only ones returned", () => {
    const link = {
      ...newToolLink(agent(), node(), spec, emptyDocument, registry),
      returned_ports: ["count"],
    };

    const { outputs } = toolPortChoices(
      link,
      node(),
      spec,
      emptyDocument,
      registry,
    );

    expect(outputs.map((output) => [output.name, output.returned])).toEqual([
      ["text", false],
      ["count", true],
    ]);
  });

  it("names a second tool for the same operator apart", () => {
    expect(uniqueToolName("Search the letters", ["search_the_letters"])).toBe(
      "search_the_letters_2",
    );
    expect(
      uniqueToolName("Search the letters", [
        "search_the_letters",
        "search_the_letters_2",
      ]),
    ).toBe("search_the_letters_3");
    expect(uniqueToolName("9 lives!", [])).toBe("lives");
    expect(uniqueToolName("***", [])).toBe("tool");
  });
});

describe("editing an Agent's links", () => {
  it("adds, updates and removes a tool without touching the Agent's other fields", () => {
    const link = newToolLink(agent(), node(), spec, emptyDocument, registry);
    const withIt = withTool(agent({ instructions: "Be brief." }), link);
    expect(withIt.tools).toEqual([link]);
    expect(withIt.instructions).toBe("Be brief.");

    const renamed = withUpdatedTool(withIt, link.id, {
      name: "find_letters",
      filled_ports: ["query"],
    });
    expect(renamed.tools[0]).toMatchObject({
      id: link.id,
      node_id: "search",
      name: "find_letters",
      filled_ports: ["query"],
    });

    expect(withoutTool(renamed, link.id).tools).toEqual([]);
    expect(withoutTool(renamed, "missing").tools).toHaveLength(1);
  });

  it("adds and removes context links", () => {
    const link = nodeOutputContext("search", "text");
    expect(link).toMatchObject({
      kind: "node_output",
      node_id: "search",
      port: "text",
    });

    const withIt = withContext(agent(), link);
    expect(withIt.context).toEqual([link]);
    expect(withoutContext(withIt, link.id).context).toEqual([]);
  });
});
