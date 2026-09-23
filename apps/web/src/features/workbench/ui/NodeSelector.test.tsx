// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

import { NodeSelector, type NodeSelectorProps } from "./NodeSelector";

const roots = new Map<Root, HTMLElement>();

function port<Direction extends Port["direction"]>(
  name: string,
  direction: Direction,
  artifactTypeId: string,
): Port & { readonly direction: Direction } {
  return {
    name,
    title: name[0]?.toUpperCase() + name.slice(1),
    description: `${name} port`,
    direction,
    artifact_type: { id: artifactTypeId, schema_version: 1 },
    artifact_type_variable: null,
    shape: "one",
    accepted_shapes: ["one"],
    instance_plugs: false,
    variadic: false,
    required: true,
  };
}

function node(
  operatorId: string,
  title: string,
  pluginSlug: string,
  inputs: readonly Port[],
  outputs: readonly Port[],
  overrides: Partial<NodeSpec> = {},
): NodeSpec {
  return {
    operator_id: operatorId,
    operator_version: 1,
    plugin_slug: pluginSlug,
    title,
    description: `${title} description`,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs,
    outputs,
    catalog_visible: true,
    origin:
      pluginSlug === "graph.module"
        ? "module"
        : pluginSlug === "builtin"
          ? "builtin"
          : "plugin",
    plugin_revision: null,
    runnable: true,
    ...overrides,
  };
}

function registry(): NodeRegistry {
  const textOutput = port("text", "output", "scalar.text");
  const textInput = port("text", "input", "scalar.text");
  const tableOutput = port("table", "output", "table.data");
  const tableInput = port("table", "input", "table.data");
  const layerInput = port("layers", "input", "geo.map_layer");
  const mapOutput = port("map", "output", "geo.map_document");
  const imageInput = port("image", "input", "image.raster");
  const firstModuleRelease = node(
    "graph.module.graph-1",
    "Normalize invoices",
    "graph.module",
    [textInput],
    [tableOutput],
    {
      operator_version: 1,
      catalog_visible: false,
      module_id: "module-1",
      module_graph_id: "graph-1",
      module_graph_revision: 1,
      is_current_library_release: false,
      publication_state: "deprecated",
    },
  );
  const currentModuleRelease = {
    ...firstModuleRelease,
    operator_version: 2,
    catalog_visible: true,
    module_graph_revision: 2,
    is_current_library_release: true,
    publication_state: "published" as const,
  };

  return {
    plugins: [
      {
        slug: "builtin",
        title: "Built-in",
        origin: "builtin",
        entry_kind: "plugin",
        runnable: true,
      },
      {
        slug: "graph.module",
        title: "Workspace library",
        origin: "module",
        entry_kind: "module",
        revision: null,
        runnable: true,
      },
      {
        slug: "external.ocr",
        title: "OCR",
        origin: "plugin",
        entry_kind: "plugin",
        scope: "system",
        revision: 1,
        plugin_release: {
          scope: "system",
          slug: "external.ocr",
          revision: 1,
        },
        runnable: true,
      },
    ],
    artifact_types: [
      "scalar.text",
      "table.data",
      "geo.map_layer",
      "geo.map_document",
      "image.raster",
    ].map((id) => ({
      key: { id, schema_version: 1 },
      title: id,
      bundle: { format: "inline-json" as const, version: 1 },
      payload_schema: {},
      field_projections: [],
    })),
    artifact_conversions: [],
    nodes: [
      node("text.input", "Enter text", "builtin", [], [textOutput], {
        config_schema: {
          type: "object",
          properties: {
            text: {
              type: "string",
              title: "Text",
              description: "Text emitted by the node",
            },
          },
        },
      }),
      node(
        "text.replace",
        "Replace text",
        "builtin",
        [textInput],
        [textOutput],
        {
          config_schema: {
            type: "object",
            properties: {
              replacement: {
                type: "string",
                title: "Replacement",
                description: "Replacement text",
              },
            },
          },
        },
      ),
      node(
        "table.fuzzy_match",
        "Fuzzy match tables",
        "builtin",
        [tableInput],
        [tableOutput],
      ),
      node(
        "gis.map.compose",
        "Compose map",
        "builtin",
        [layerInput],
        [mapOutput],
      ),
      firstModuleRelease,
      currentModuleRelease,
      node(
        "ocr.pages",
        "Read image with OCR",
        "external.ocr",
        [imageInput],
        [textOutput],
      ),
    ],
  };
}

async function renderSelector(overrides: Partial<NodeSelectorProps> = {}) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.set(root, container);
  let props: NodeSelectorProps = {
    open: true,
    registry: registry(),
    activeGraphId: null,
    onOpenChange: vi.fn(),
    onAddNode: vi.fn(),
    ...overrides,
  };
  const render = async (next: Partial<NodeSelectorProps> = {}) => {
    props = { ...props, ...next };
    await React.act(async () => {
      root.render(<NodeSelector {...props} />);
      await Promise.resolve();
    });
  };
  await render();
  return {
    container,
    root,
    render,
    get props() {
      return props;
    },
  };
}

function dialog(): HTMLElement {
  const element = document.body.querySelector<HTMLElement>('[role="dialog"]');
  if (!element) throw new Error("Node selector dialog was not rendered");
  return element;
}

function searchInput(): HTMLInputElement {
  const input = dialog().querySelector<HTMLInputElement>(
    '[aria-label="Search nodes"]',
  );
  if (!input) throw new Error("Node search was not rendered");
  return input;
}

function options(): HTMLButtonElement[] {
  return [...dialog().querySelectorAll<HTMLButtonElement>('[role="option"]')];
}

function buttonNamed(name: string): HTMLButtonElement {
  const button = [
    ...dialog().querySelectorAll<HTMLButtonElement>("button"),
  ].find(
    (candidate) =>
      candidate.textContent?.trim() === name ||
      candidate.getAttribute("aria-label") === name,
  );
  if (!button) throw new Error(`Button ${name} was not rendered`);
  return button;
}

async function enterSearch(value: string) {
  const input = searchInput();
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  await React.act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function press(element: Element, key: string) {
  await React.act(async () => {
    element.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true }));
  });
}

afterEach(async () => {
  for (const [root, container] of roots) {
    await React.act(async () => root.unmount());
    container.remove();
  }
  roots.clear();
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("NodeSelector", () => {
  it("scopes the rail by source with artifact and input-node refinements", async () => {
    await renderSelector();

    expect(
      dialog()
        .querySelector('[role="toolbar"]')
        ?.getAttribute("aria-orientation"),
    ).toBe("vertical");
    const filters = [
      ...dialog().querySelectorAll<HTMLButtonElement>(
        '[role="toolbar"] button',
      ),
    ];
    expect(filters.map((filter) => filter.textContent)).toEqual([
      "All",
      "Built-in",
      "OCR",
      "Workspace library",
    ]);

    // Source category scopes the list to one provider plugin.
    await React.act(async () => buttonNamed("Built-in, 4 nodes").click());
    expect(dialog().textContent).toContain("Built-in nodes");
    expect(options().map((option) => option.textContent)).toEqual([
      expect.stringContaining("Compose map"),
      expect.stringContaining("Enter text"),
      expect.stringContaining("Fuzzy match tables"),
      expect.stringContaining("Replace text"),
    ]);

    // The artifact type refines within the active source.
    const artifactSelect = dialog().querySelector<HTMLSelectElement>(
      '[aria-label="Artifact type"]',
    );
    expect(artifactSelect).not.toBeNull();
    await React.act(async () => {
      if (!artifactSelect) return;
      artifactSelect.value = "artifact:scalar.text@1";
      artifactSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(options().map((option) => option.textContent)).toEqual([
      expect.stringContaining("Enter text"),
      expect.stringContaining("Replace text"),
    ]);

    // Input nodes only: nodes that take no inputs because they are inputs themselves.
    const inputToggle = dialog().querySelector<HTMLInputElement>(
      'input[type="checkbox"]',
    );
    expect(inputToggle).not.toBeNull();
    await React.act(async () => {
      inputToggle?.click();
    });
    expect(inputToggle?.checked).toBe(true);
    expect(options().map((option) => option.textContent)).toEqual([
      expect.stringContaining("Enter text"),
    ]);
  });

  it("searches the full registry and inspects a result without inserting it", async () => {
    const onAddNode = vi.fn();
    await renderSelector({ onAddNode });

    expect(searchInput().hasAttribute("autofocus")).toBe(false);
    await vi.waitFor(() => expect(document.activeElement).toBe(dialog()));
    await enterSearch("OCR");

    expect(options()).toHaveLength(1);
    expect(options()[0]?.textContent).toContain("Read image with OCR");
    await React.act(async () => options()[0]?.click());
    expect(dialog().querySelector("aside")?.textContent).toContain(
      "Read image with OCR description",
    );
    expect(onAddNode).not.toHaveBeenCalled();
  });

  it("focuses search when a fine pointer opens the controlled dialog", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn(
        (query: string): MediaQueryList =>
          ({
            matches: query === "(pointer: fine)",
            media: query,
            onchange: null,
            addEventListener: vi.fn(),
            removeEventListener: vi.fn(),
            addListener: vi.fn(),
            removeListener: vi.fn(),
            dispatchEvent: vi.fn(),
          }) satisfies MediaQueryList,
      ),
    );

    await renderSelector();

    await vi.waitFor(() => expect(document.activeElement).toBe(searchInput()));
  });

  it("keeps toolbar semantics aligned with live compact-layout changes", async () => {
    let compact = true;
    const listeners = new Set<EventListener>();
    vi.stubGlobal(
      "matchMedia",
      vi.fn(
        (query: string): MediaQueryList =>
          ({
            get matches() {
              return query === "(max-width: 720px)" && compact;
            },
            media: query,
            onchange: null,
            addEventListener: ((_type: string, listener: EventListener) => {
              listeners.add(listener);
            }) as MediaQueryList["addEventListener"],
            removeEventListener: ((_type: string, listener: EventListener) => {
              listeners.delete(listener);
            }) as MediaQueryList["removeEventListener"],
            addListener: vi.fn(),
            removeListener: vi.fn(),
            dispatchEvent: vi.fn(),
          }) satisfies MediaQueryList,
      ),
    );

    await renderSelector();

    expect(
      dialog()
        .querySelector('[role="toolbar"]')
        ?.getAttribute("aria-orientation"),
    ).toBe("horizontal");

    compact = false;
    await React.act(async () => {
      for (const listener of listeners) listener(new Event("change"));
    });
    expect(
      dialog()
        .querySelector('[role="toolbar"]')
        ?.getAttribute("aria-orientation"),
    ).toBe("vertical");
  });

  it("renders the selected node in the inspector with its ports and settings", async () => {
    await renderSelector();

    await enterSearch("Enter text");
    const enterPreview = dialog().querySelector(
      '[aria-label="Enter text: 0 inputs, 1 output"]',
    );
    expect(enterPreview).not.toBeNull();
    expect(enterPreview?.textContent).toContain("Start");
    expect(enterPreview?.textContent).toContain("Text");
    expect(enterPreview?.textContent).toContain("string");
    expect(dialog().querySelector("aside")?.textContent).toContain(
      "Starts a workflow",
    );

    await enterSearch("Fuzzy match tables");
    const fuzzyPreview = dialog().querySelector(
      '[aria-label="Fuzzy match tables: 1 input, 1 output"]',
    );
    expect(fuzzyPreview).not.toBeNull();
    expect(fuzzyPreview?.textContent).toContain("Table");
    expect(fuzzyPreview?.textContent).not.toContain("string");

    await enterSearch("Replace text");
    const replacePreview = dialog().querySelector(
      '[aria-label="Replace text: 1 input, 1 output"]',
    );
    expect(replacePreview).not.toBeNull();
    expect(replacePreview?.textContent).toContain("Replacement");
    expect(replacePreview?.textContent).toContain("string");
  });

  it("inserts only through the explicit action", async () => {
    const onAddNode = vi.fn();
    await renderSelector({ onAddNode });

    await enterSearch("Replace text");
    await React.act(async () => options()[0]?.click());
    expect(onAddNode).not.toHaveBeenCalled();
    expect(
      [...dialog().querySelectorAll("button")].filter((button) =>
        button.getAttribute("aria-label")?.startsWith("Add "),
      ),
    ).toHaveLength(0);
    await React.act(async () => buttonNamed("Add Replace text").click());

    expect(onAddNode).toHaveBeenCalledOnce();
    expect(onAddNode.mock.calls[0]?.[0].operator_id).toBe("text.replace");
  });

  it("scopes Works with to one port and inspects a suggested node", async () => {
    await renderSelector();

    await enterSearch("Replace text");
    await React.act(async () => options()[0]?.click());

    expect(dialog().querySelector("aside")?.textContent).toContain(
      "Works with:",
    );
    const portSelect = dialog().querySelector<HTMLSelectElement>(
      '[aria-label="Works with port"]',
    );
    expect(portSelect?.value).toBe("input:text");
    expect(portSelect?.selectedOptions[0]?.textContent).toBe("Text input");
    expect(dialog().querySelector("aside")?.textContent).toContain(
      "Enter text",
    );

    await React.act(async () => {
      if (!portSelect) return;
      portSelect.value = "output:text";
      portSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(portSelect?.value).toBe("output:text");
    expect(portSelect?.selectedOptions[0]?.textContent).toBe("Text output");

    await React.act(async () =>
      buttonNamed("Inspect Normalize invoices").click(),
    );
    expect(dialog().querySelector("aside")?.textContent).toContain(
      "Module contract · release 2",
    );
    expect(
      options().find(
        (option) => option.getAttribute("aria-selected") === "true",
      )?.textContent,
    ).toContain("Normalize invoices");
  });

  it("moves from search through results with arrows and inserts with Enter", async () => {
    const onAddNode = vi.fn();
    await renderSelector({ onAddNode });

    await enterSearch("Replace text");
    await press(searchInput(), "ArrowDown");
    expect(document.activeElement).toBe(options()[0]);
    await press(options()[0]!, "Enter");

    expect(onAddNode).toHaveBeenCalledOnce();
    expect(onAddNode.mock.calls[0]?.[0].operator_id).toBe("text.replace");
  });

  it("filters results through a typed contextual port contract", async () => {
    const contextPort = port("source text", "output", "scalar.text");
    await renderSelector({
      compatibility: { direction: "downstream", port: contextPort },
    });

    expect(options().map((option) => option.textContent)).toEqual([
      expect.stringContaining("Normalize invoices"),
      expect.stringContaining("Replace text"),
    ]);
    expect(dialog().textContent).toContain(
      "Showing nodes that can connect from Source text.",
    );
  });

  it("shows Module release state and inserts the chosen immutable release", async () => {
    const onAddNode = vi.fn();
    const onOpenGraph = vi.fn();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    await renderSelector({ onAddNode, onOpenGraph });

    await React.act(async () =>
      buttonNamed("Workspace library, 1 node").click(),
    );
    expect(options()[0]?.textContent).toContain("Normalize invoices");
    expect(dialog().querySelector("aside")?.textContent).toContain(
      "Module contract · release 2",
    );
    expect(dialog().querySelector("aside")?.textContent).toContain("published");
    await React.act(async () => buttonNamed("Open source graph").click());
    expect(onOpenGraph).toHaveBeenCalledWith("graph-1");

    const release = dialog().querySelector<HTMLSelectElement>(
      '[aria-label="Module release"]',
    );
    expect(release?.options).toHaveLength(2);
    await React.act(async () => {
      if (!release) return;
      release.value = "graph.module.graph-1@1";
      release.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await React.act(async () => buttonNamed("Insert module call").click());

    expect(window.confirm).toHaveBeenCalledOnce();
    expect(onAddNode.mock.calls[0]?.[0].operator_version).toBe(1);
    expect(onAddNode.mock.calls[0]?.[0].module_graph_revision).toBe(1);
  });

  it("educates from an empty Workspace library and keeps its action available", async () => {
    const emptyRegistry = registry();
    const onOpenWorkspaceLibrary = vi.fn();
    await renderSelector({
      registry: {
        ...emptyRegistry,
        nodes: emptyRegistry.nodes.filter(
          (spec) => spec.plugin_slug !== "graph.module",
        ),
      },
      onOpenWorkspaceLibrary,
    });

    await React.act(async () =>
      buttonNamed("Workspace library, 0 nodes").click(),
    );
    expect(options()).toHaveLength(0);
    expect(dialog().textContent).toContain(
      "No published Modules in this workspace yet.",
    );
    await React.act(async () => buttonNamed("Open workspace library").click());
    expect(onOpenWorkspaceLibrary).toHaveBeenCalledOnce();
  });

  it("renders a no-result state and resets to All nodes", async () => {
    await renderSelector();

    await enterSearch("not a real node");
    expect(options()).toHaveLength(0);
    expect(dialog().querySelector('[role="status"]')?.textContent).toBe(
      "No nodes found.",
    );
    expect(dialog().textContent).toContain(
      "No nodes match the current search or filter.",
    );
    await React.act(async () => buttonNamed("Reset search and filter").click());

    expect(searchInput().value).toBe("");
    expect(options().length).toBeGreaterThan(0);
    expect(buttonNamed("All, 6 nodes").getAttribute("aria-pressed")).toBe(
      "true",
    );
  });

  it("announces counts, loading, errors, and recovery atomically", async () => {
    const onRetry = vi.fn();
    const rendered = await renderSelector();

    const status = dialog().querySelector('[role="status"]');
    expect(dialog().getAttribute("aria-labelledby")).toBe(
      "node-selector-title",
    );
    expect(dialog().getAttribute("aria-describedby")).toBe(
      "node-selector-description",
    );
    expect(searchInput().getAttribute("aria-controls")).toBe(
      "node-selector-results",
    );
    expect(
      dialog()
        .querySelector('[role="listbox"]')
        ?.getAttribute("aria-activedescendant"),
    ).toBe(options()[0]?.id);
    expect(options()[0]?.getAttribute("aria-selected")).toBe("true");
    expect(status?.getAttribute("aria-live")).toBe("polite");
    expect(status?.getAttribute("aria-atomic")).toBe("true");
    expect(status?.textContent).toBe("6 nodes.");

    await rendered.render({ loading: true });
    expect(dialog().querySelector('[role="status"]')?.textContent).toBe(
      "Loading nodes…",
    );
    expect(
      dialog().querySelector('[role="listbox"]')?.getAttribute("aria-busy"),
    ).toBe("true");

    await rendered.render({
      loading: false,
      errorMessage: "Registry request timed out.",
      onRetry,
    });
    const alert = dialog().querySelector('[role="alert"]');
    expect(alert?.getAttribute("aria-live")).toBe("assertive");
    expect(dialog().textContent).toContain(
      "Nodes couldn’t be loaded. Registry request timed out.",
    );
    await React.act(async () => buttonNamed("Try again").click());
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("uses one roving filter stop and exposes permission-disabled insertion", async () => {
    await renderSelector({
      canInsert: false,
      insertDisabledReason:
        "Viewers can inspect nodes but cannot edit this graph.",
    });

    const filters = [
      ...dialog().querySelectorAll<HTMLButtonElement>(
        '[role="toolbar"] button',
      ),
    ];
    expect(filters.filter((button) => button.tabIndex === 0)).toHaveLength(1);
    filters[0]?.focus();
    await press(filters[0]!, "ArrowDown");
    expect(document.activeElement).toBe(filters[1]);
    expect(filters[1]?.getAttribute("aria-pressed")).toBe("true");
    await React.act(async () => filters[0]?.click());

    await enterSearch("Enter text");
    const insert = buttonNamed("Add Enter text");
    expect(insert.disabled).toBe(true);
    expect(insert.getAttribute("title")).toBe(
      "Viewers can inspect nodes but cannot edit this graph.",
    );
    expect(dialog().textContent).toContain(
      "Viewers can inspect nodes but cannot edit this graph.",
    );
  });

  it("shows catalog-only Plugin releases but prevents insertion", async () => {
    const catalog = registry();
    const onAddNode = vi.fn();
    await renderSelector({
      registry: {
        ...catalog,
        plugins: [
          ...catalog.plugins,
          {
            slug: "notes",
            title: "Notes",
            origin: "plugin",
            entry_kind: "plugin",
            scope: "workspace",
            revision: 1,
            plugin_release: {
              scope: "workspace",
              slug: "notes",
              revision: 1,
            },
            runnable: false,
          },
        ],
        nodes: [
          ...catalog.nodes,
          node("notes.summary.render", "Render summary", "notes", [], [], {
            plugin_revision: 1,
            plugin_release: {
              scope: "workspace",
              slug: "notes",
              revision: 1,
            },
            runnable: false,
            non_runnable_reason: "missing_runtime_artifact",
            non_runnable_detail: "This release has no immutable runtime image.",
          }),
        ],
      },
      onAddNode,
    });

    await enterSearch("Render summary");
    const add = buttonNamed("Add Render summary");
    expect(dialog().textContent).toContain("Catalog preview only.");
    expect(dialog().textContent).toContain(
      "This release has no immutable runtime image.",
    );
    expect(add.disabled).toBe(true);
    expect(add.title).toBe("This release has no immutable runtime image.");
    await React.act(async () => add.click());
    expect(onAddNode).not.toHaveBeenCalled();
  });

  it("closes on Escape and lets the dialog primitive restore opener focus", async () => {
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    roots.set(root, container);
    const onOpenChange = vi.fn();

    function ControlledSelector() {
      const [open, setOpen] = React.useState(false);
      const openerRef = React.useRef<HTMLButtonElement>(null);
      return (
        <>
          <button ref={openerRef} type="button" onClick={() => setOpen(true)}>
            Open Add node
          </button>
          <NodeSelector
            open={open}
            registry={registry()}
            activeGraphId={null}
            returnFocusRef={openerRef}
            onOpenChange={(nextOpen) => {
              onOpenChange(nextOpen);
              setOpen(nextOpen);
            }}
            onAddNode={() => undefined}
          />
        </>
      );
    }

    await React.act(async () => root.render(<ControlledSelector />));
    const opener = container.querySelector<HTMLButtonElement>("button");
    opener?.focus();
    await React.act(async () => opener?.click());

    await press(dialog(), "Escape");
    expect(onOpenChange.mock.calls[0]?.[0]).toBe(false);
    await vi.waitFor(() => expect(document.activeElement).toBe(opener));
  });
});
