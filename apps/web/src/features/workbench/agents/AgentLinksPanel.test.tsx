// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  NodeRegistry,
  NodeSpec,
  Port,
  SavedGraphAgent,
  SavedGraphNode,
} from "@/lib/api";
import { AgentLinksPanel } from "./AgentLinksPanel";
import {
  cardContext,
  newToolLink,
  nodeOutputContext,
  withContext,
  withTool,
  withUpdatedTool,
} from "./agent-links";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

type PanelProps = React.ComponentProps<typeof AgentLinksPanel>;
type PanelDocument = PanelProps["document"];
type ChangeAgent = (next: SavedGraphAgent) => void;

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

/** The Graph's own boundary: a node of the Graph, not a node an Agent may call. */
const boundarySpec: NodeSpec = {
  ...spec,
  operator_id: "graph.input",
  plugin_slug: "project-graphs",
  title: "Graph input",
  inputs: [port("value", "input", "scalar.text")],
  outputs: [],
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
  nodes: [spec, boundarySpec],
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

function graphDocument(nodes: readonly SavedGraphNode[]): PanelDocument {
  return {
    nodes,
    edges: [],
    origins: [],
    presentation: {
      viewers: [
        {
          id: "v1",
          artifact_ref: { artifact_type: "scalar.text", schema_version: 1 },
        },
        { id: "v2", artifact_ref: null },
      ],
    },
  };
}

const graph = graphDocument([node("search"), boundaryNode()]);

function boundaryNode(): SavedGraphNode {
  return { ...node("boundary"), operator_id: "graph.input" };
}

const plain: SavedGraphAgent = {
  id: "a",
  name: "Agent",
  instructions: "",
  context: [],
  tools: [],
  width: 360,
  height: 480,
};

/** The Agent as the panel itself would have made it: both writable inputs filled. */
function withSearchTool(): SavedGraphAgent {
  return withTool(
    plain,
    newToolLink(plain, node("search"), spec, graph, registry),
  );
}

const TOOL = "Tool search_the_letters";

const mountedRoots = new Set<ReturnType<typeof createRoot>>();

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  document.body.replaceChildren();
});

async function mount(element: React.ReactElement) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  await act(async () => root.render(element));
  return { container, root };
}

function panel(
  props: Pick<PanelProps, "agent" | "onChange"> & {
    document?: PanelDocument;
    disabled?: boolean;
  },
): React.ReactElement {
  return (
    <AgentLinksPanel
      document={graph}
      registry={registry}
      {...props}
      disabled={props.disabled ?? false}
    />
  );
}

function named(container: HTMLElement, label: string): Element {
  const found = container.querySelector(`[aria-label="${label}"]`);
  expect(found, label).not.toBeNull();
  return found as Element;
}

function selectNamed(container: HTMLElement, label: string): HTMLSelectElement {
  const select = named(container, label);
  expect(select.tagName).toBe("SELECT");
  return select as HTMLSelectElement;
}

function optionValues(select: HTMLSelectElement): string[] {
  return Array.from(select.querySelectorAll("option")).map(
    (option) => option.value,
  );
}

function optionTexts(select: HTMLSelectElement): (string | null)[] {
  return Array.from(select.querySelectorAll("option")).map(
    (option) => option.textContent,
  );
}

function boxes(scope: Element): HTMLInputElement[] {
  return Array.from(
    scope.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'),
  );
}

/** The panel's own port rows, told apart from a <Field>'s label by holding a box. */
function portLabels(scope: Element): Element[] {
  return Array.from(scope.querySelectorAll("label")).filter((label) =>
    label.querySelector('input[type="checkbox"]'),
  );
}

/** The two text controls of a tool: its name, then what it does. */
function textInputs(scope: Element): HTMLInputElement[] {
  return Array.from(
    scope.querySelectorAll<HTMLInputElement>('input:not([type="checkbox"])'),
  );
}

/** A native select answers only to its own value setter, the way React listens. */
async function choose(select: HTMLSelectElement, value: string) {
  const setValue = Object.getOwnPropertyDescriptor(
    HTMLSelectElement.prototype,
    "value",
  )!.set!;
  await act(async () => {
    setValue.call(select, value);
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

async function toggle(checkbox: HTMLInputElement) {
  await act(async () => {
    checkbox.click();
  });
}

async function type(input: HTMLInputElement, value: string) {
  const setValue = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!;
  await act(async () => {
    setValue.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function press(container: HTMLElement, label: string) {
  const button = named(container, label);
  await act(async () => {
    (button as HTMLButtonElement).click();
  });
}

async function dropOn(section: Element, payload: unknown) {
  const dataTransfer = {
    types: ["application/x-grafy-artifact"],
    getData: (type: string) =>
      type === "application/x-grafy-artifact" ? JSON.stringify(payload) : "",
  };
  await act(async () => {
    section.dispatchEvent(
      Object.assign(new Event("drop", { bubbles: true, cancelable: true }), {
        dataTransfer,
      }),
    );
  });
}

describe("the tools of an Agent", () => {
  it("draws one row per tool, with its ports and why one cannot be offered", async () => {
    const { container } = await mount(
      panel({ agent: withSearchTool(), onChange: vi.fn() }),
    );
    const tool = named(container, TOOL);

    // query, limit, rows, url, then the text and the count output.
    expect(boxes(tool).map((box) => box.checked)).toEqual([
      true,
      true,
      false,
      false,
      true,
      true,
    ]);
    expect(boxes(tool)[2]?.disabled).toBe(true);
    const rows = portLabels(tool)[2];
    expect(rows?.textContent).toContain(
      "A model can only write text or numbers",
    );
    expect(rows?.getAttribute("title")).toBe(
      "A model can only write text or numbers",
    );
  });

  it("leaves the other inputs in the node's own order when one is unchecked", async () => {
    const onChange = vi.fn<ChangeAgent>();
    const { container } = await mount(
      panel({ agent: withSearchTool(), onChange }),
    );

    await toggle(boxes(named(container, TOOL))[1]!);

    expect(onChange.mock.calls[0]?.[0].tools[0]?.filled_ports).toEqual([
      "query",
    ]);
  });

  it("returns what is left when an output is unchecked, and keeps the last one", async () => {
    const agent = withSearchTool();
    const onChange = vi.fn<ChangeAgent>();
    const { container, root } = await mount(panel({ agent, onChange }));

    await toggle(boxes(named(container, TOOL))[4]!);
    expect(onChange.mock.calls[0]?.[0].tools[0]?.returned_ports).toEqual([
      "count",
    ]);

    const oneLeft = withUpdatedTool(agent, agent.tools[0]!.id, {
      returned_ports: ["count"],
    });
    await act(async () => {
      root.render(panel({ agent: oneLeft, onChange: vi.fn() }));
    });
    const outputs = boxes(named(container, TOOL)).slice(4);
    expect(outputs.map((box) => box.checked)).toEqual([false, true]);
    expect(outputs[1]?.disabled).toBe(true);
  });

  it("names no output once every output is returned again", async () => {
    const agent = withSearchTool();
    const oneReturned = withUpdatedTool(agent, agent.tools[0]!.id, {
      returned_ports: ["count"],
    });
    const onChange = vi.fn<ChangeAgent>();
    const { container } = await mount(panel({ agent: oneReturned, onChange }));

    await toggle(boxes(named(container, TOOL))[4]!);

    expect(onChange.mock.calls[0]?.[0].tools[0]?.returned_ports).toEqual([]);
  });

  it("offers an unlinked node once and never the Graph's own boundary", async () => {
    const onChange = vi.fn<ChangeAgent>();
    const { container, root } = await mount(panel({ agent: plain, onChange }));

    expect(
      optionValues(selectNamed(container, "Add a node as a tool")),
    ).toEqual(["", "search"]);
    await choose(selectNamed(container, "Add a node as a tool"), "search");
    expect(onChange.mock.calls[0]?.[0].tools[0]).toMatchObject({
      node_id: "search",
      filled_ports: ["query", "limit"],
    });

    await act(async () => {
      root.render(panel({ agent: withSearchTool(), onChange: vi.fn() }));
    });
    expect(
      optionValues(selectNamed(container, "Add a node as a tool")),
    ).toEqual([""]);

    const twin = graphDocument([node("search"), node("again"), boundaryNode()]);
    await act(async () => {
      root.render(panel({ agent: plain, onChange: vi.fn(), document: twin }));
    });
    expect(optionTexts(selectNamed(container, "Add a node as a tool"))).toEqual(
      ["Add a tool…", "Search the letters", "Search the letters (2)"],
    );
  });

  it("keeps a typed name one a model can call", async () => {
    const onChange = vi.fn<ChangeAgent>();
    const { container } = await mount(
      panel({ agent: withSearchTool(), onChange }),
    );

    await type(textInputs(named(container, TOOL))[0]!, "Find Letters!");

    expect(onChange.mock.calls[0]?.[0].tools[0]?.name).toBe("find_letters_");
  });

  it("removes a tool, and still removes one whose node is gone", async () => {
    const agent = withSearchTool();
    const onChange = vi.fn<ChangeAgent>();
    const { container } = await mount(panel({ agent, onChange }));

    await press(container, "Remove tool search_the_letters");
    expect(onChange.mock.calls[0]?.[0].tools).toEqual([]);

    const orphan = withTool(plain, {
      ...agent.tools[0]!,
      node_id: "gone",
    });
    const second = await mount(panel({ agent: orphan, onChange: vi.fn() }));
    expect(named(second.container, TOOL).textContent).toContain(
      "this node is no longer available",
    );
  });
});

describe("the context of an Agent", () => {
  it("adds a node output and a card, hides what is linked, removes either", async () => {
    const onChange = vi.fn<ChangeAgent>();
    const { container, root } = await mount(panel({ agent: plain, onChange }));

    expect(optionValues(selectNamed(container, "Add context"))).toEqual([
      "",
      "output:search:text",
      "output:search:count",
      "card:v1",
    ]);
    const select = selectNamed(container, "Add context");
    await choose(select, "output:search:text");
    await choose(select, "card:v1");
    expect(onChange.mock.calls[0]?.[0].context[0]).toMatchObject({
      kind: "node_output",
      node_id: "search",
      port: "text",
    });
    expect(onChange.mock.calls[1]?.[0].context[0]).toMatchObject({
      kind: "card",
      card_id: "v1",
    });

    const linked = withContext(
      withContext(plain, nodeOutputContext("search", "text")),
      cardContext("v1"),
    );
    await act(async () => {
      root.render(panel({ agent: linked, onChange: vi.fn() }));
    });
    expect(optionValues(selectNamed(container, "Add context"))).toEqual([
      "",
      "output:search:count",
    ]);

    const removeChange = vi.fn<ChangeAgent>();
    await act(async () => {
      root.render(
        panel({
          agent: withContext(plain, nodeOutputContext("search", "text")),
          onChange: removeChange,
        }),
      );
    });
    expect(
      Array.from(container.querySelectorAll("span")).some((span) =>
        span.textContent?.includes("Search the letters · text"),
      ),
    ).toBe(true);
    await press(container, "Remove context Search the letters · text");
    expect(removeChange.mock.calls[0]?.[0].context).toEqual([]);
  });

  it("connects a Library artifact dropped on the section, and none while disabled", async () => {
    const artifact = {
      artifact_id: "11111111-1111-4111-8111-111111111111",
      artifact_type: "scalar.text",
      schema_version: 1,
    };
    const payload = { value: artifact, shape: "one" };
    const onChange = vi.fn<ChangeAgent>();
    const { container } = await mount(panel({ agent: plain, onChange }));

    await dropOn(named(container, "Context"), payload);

    expect(onChange.mock.calls[0]?.[0].context[0]).toEqual({
      id: expect.any(String),
      kind: "library_item",
      library_item_id: artifact.artifact_id,
    });

    const frozen = vi.fn<ChangeAgent>();
    const locked = await mount(
      panel({ agent: plain, onChange: frozen, disabled: true }),
    );
    await dropOn(named(locked.container, "Context"), payload);
    expect(frozen).not.toHaveBeenCalled();
  });
});

describe("a panel nobody may edit", () => {
  it("disables every control it still shows", async () => {
    const agent = withContext(
      withSearchTool(),
      nodeOutputContext("search", "text"),
    );
    const { container } = await mount(
      panel({ agent, onChange: vi.fn(), disabled: true }),
    );

    const checkboxes = container.querySelectorAll<HTMLInputElement>(
      'input[type="checkbox"]',
    );
    expect(checkboxes).toHaveLength(6);
    for (const checkbox of checkboxes) expect(checkbox.disabled).toBe(true);

    const selects = container.querySelectorAll<HTMLSelectElement>("select");
    expect(selects).toHaveLength(2);
    for (const select of selects) expect(select.disabled).toBe(true);

    const buttons = container.querySelectorAll<HTMLButtonElement>("button");
    expect(buttons).toHaveLength(2);
    for (const button of buttons) expect(button.disabled).toBe(true);
  });
});
