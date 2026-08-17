// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

const xyflowMocks = vi.hoisted(() => ({
  updateNodeInternals: vi.fn(),
}));

vi.mock("@xyflow/react", () => ({
  Handle: ({
    id,
    isConnectable,
  }: {
    id: string;
    isConnectable: boolean;
  }) => (
    <span
      data-testid="compatibility-handle"
      data-handle-id={id}
      data-connectable={String(isConnectable)}
    />
  ),
  Position: { Left: "left", Right: "right" },
  useEdges: () => [],
  useNodeConnections: () => [],
  useStore: (
    selector: (state: {
      edges: unknown[];
      nodeLookup: Map<string, unknown>;
    }) => unknown,
  ) => selector({ edges: [], nodeLookup: new Map() }),
  useUpdateNodeInternals: () => xyflowMocks.updateNodeInternals,
  useViewport: () => ({ zoom: 1, x: 0, y: 0 }),
}));

const gridSettingsMocks = vi.hoisted(() => ({
  allowWorkflowCornerResize: false,
}));

vi.mock("../canvas-grid-settings", () => ({
  useOptionalCanvasGridSettings: () => ({
    settings: {
      enabled: true,
      showBackground: true,
      snapPosition: true,
      snapSize: true,
      snapWhileDragging: false,
      snapWhileResizing: true,
      allowWorkflowCornerResize: gridSettingsMocks.allowWorkflowCornerResize,
      cellSize: 50,
    },
    bypassSnap: false,
  }),
}));

vi.mock("./LayoutResizeHandle", () => ({
  LayoutResizeHandle: ({ ariaLabel }: { ariaLabel: string }) => (
    <button type="button" data-testid="corner-resize" aria-label={ariaLabel} />
  ),
}));

vi.mock("./TextareaBodyResizeHandle", () => ({
  TextareaBodyResizeHandle: ({ ariaLabel }: { ariaLabel: string }) => (
    <button
      type="button"
      data-testid="textarea-body-resize"
      aria-label={ariaLabel}
    />
  ),
}));

vi.mock("@base-ui/react/popover", () => ({
  Popover: {
    Root: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Trigger: ({
      children,
      ...props
    }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
      children: React.ReactNode;
    }) => (
      <button type="button" {...props}>
        {children}
      </button>
    ),
    Portal: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Positioner: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Popup: ({ children }: { children: React.ReactNode }) => (
      <div>{children}</div>
    ),
  },
}));

vi.mock("./type-inspector", () => ({
  PortTypePopover: ({ children }: { children: React.ReactNode }) => children,
}));

import type { NodeSpec } from "@/lib/api";
import {
  compatibilityHandleId,
  createWorkflowNodeData,
} from "../types";
import WorkflowNodeCard, {
  configFieldLabelIsRedundant,
  type ConfigBrick,
} from "./WorkflowNode";
import { fieldFootprint } from "./field-footprints";

function unavailableSpec(): NodeSpec {
  return {
    operator_id: "legacy.operator",
    operator_version: 4,
    plugin_slug: "unavailable",
    title: "legacy.operator",
    description: "Unavailable operator",
    catalog_visible: false,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
  };
}

function boundsSpec(): NodeSpec {
  return {
    operator_id: "gis.map.wms_layer",
    operator_version: 1,
    plugin_slug: "gis",
    title: "Remote WMS map layer",
    description: "Adds a remote WMS layer.",
    catalog_visible: true,
    config_schema: {
      type: "object",
      properties: {
        bounds: {
          type: "array",
          title: "Bounds",
          description:
            "WGS84 bounds ordered as west longitude, south latitude, east longitude, north latitude.",
          prefixItems: [
            {
              type: "number",
              title: "West longitude",
              minimum: -180,
              maximum: 180,
            },
            {
              type: "number",
              title: "South latitude",
              minimum: -90,
              maximum: 90,
            },
            {
              type: "number",
              title: "East longitude",
              minimum: -180,
              maximum: 180,
            },
            {
              type: "number",
              title: "North latitude",
              minimum: -90,
              maximum: 90,
            },
          ],
          minItems: 4,
          maxItems: 4,
        },
      },
      required: ["bounds"],
    },
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
  };
}

function fuzzyMatchSpec(): NodeSpec {
  return {
    operator_id: "table.fuzzy_match",
    operator_version: 1,
    plugin_slug: "builtin.table",
    title: "Fuzzy match tables",
    description: "Ranks candidate records.",
    catalog_visible: true,
    config_schema: {
      type: "object",
      properties: {
        right_alias_columns: {
          type: "array",
          title: "Right Alias Columns",
          description: "Additional normalized candidate-name columns.",
          items: { type: "string", minLength: 1 },
          maxItems: 8,
        },
      },
    },
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
  };
}


function tableFileImportSpec(): NodeSpec {
  return {
    operator_id: "table.file.import",
    operator_version: 1,
    plugin_slug: "builtin.table",
    title: "Import table file",
    description: "Import a staged CSV or XLSX file as a table artifact.",
    catalog_visible: true,
    config_schema: {
      type: "object",
      properties: {
        uploads: {
          type: "array",
          title: "Uploads",
          minItems: 1,
          maxItems: 1,
        },
        sheet_name: {
          title: "Sheet Name",
          description: "XLSX worksheet name. Leave empty to use the active sheet.",
          default: null,
          anyOf: [
            { type: "string", minLength: 1, maxLength: 255 },
            { type: "null" },
          ],
        },
        header_row: {
          type: "integer",
          title: "Header Row",
          description: "One-based row containing column titles.",
          default: 1,
          minimum: 1,
        },
        delimiter: {
          title: "Delimiter",
          description: "CSV delimiter. Leave empty to detect it from the file.",
          default: null,
          anyOf: [
            { type: "string", minLength: 1, maxLength: 1 },
            { type: "null" },
          ],
        },
        skip_empty_rows: {
          type: "boolean",
          title: "Skip Empty Rows",
          default: true,
        },
      },
      required: ["uploads"],
    },
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
  };
}


function artifactQuerySpec(): NodeSpec {
  return {
    operator_id: "sql.artifacts.query",
    operator_version: 1,
    plugin_slug: "external.sql",
    title: "Query artifact tables",
    description: "Runs read-only queries over table artifacts.",
    catalog_visible: true,
    config_schema: {
      type: "object",
      properties: { relations: { type: "array" } },
      required: ["relations"],
    },
    input_schema: {},
    output_schema: {},
    inputs: [
      {
        name: "statements",
        title: "Statements",
        description: null,
        direction: "input",
        artifact_type: { id: "sql.statement", schema_version: 1 },
        artifact_type_variable: null,
        shape: "one",
        accepted_shapes: ["one"],
        instance_plugs: true,
        variadic: true,
        required: true,
      },
      {
        name: "relations",
        title: "Relations",
        description: null,
        direction: "input",
        artifact_type: { id: "table.data", schema_version: 1 },
        artifact_type_variable: null,
        shape: "one",
        accepted_shapes: ["one"],
        instance_plugs: true,
        variadic: true,
        required: true,
      },
    ],
    outputs: [],
  };
}

function textPipeSpec(): NodeSpec {
  return {
    operator_id: "text.pipe",
    operator_version: 1,
    plugin_slug: "text",
    title: "Text pipe",
    description: "Passes text through.",
    catalog_visible: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [
      {
        name: "text",
        title: "text",
        description: null,
        direction: "input",
        artifact_type: { id: "text.plain", schema_version: 1 },
        artifact_type_variable: null,
        shape: "one",
        accepted_shapes: ["one"],
        instance_plugs: false,
        variadic: false,
        required: true,
      },
    ],
    outputs: [
      {
        name: "text",
        title: "text",
        description: null,
        direction: "output",
        artifact_type: { id: "text.plain", schema_version: 1 },
        artifact_type_variable: null,
        shape: "one",
        accepted_shapes: ["one"],
        instance_plugs: false,
        variadic: false,
        required: false,
      },
      {
        name: "meta",
        title: "meta",
        description: null,
        direction: "output",
        artifact_type: { id: "json.document", schema_version: 1 },
        artifact_type_variable: null,
        shape: "one",
        accepted_shapes: ["one"],
        instance_plugs: false,
        variadic: false,
        required: false,
      },
    ],
  };
}

function rawSqlStatementSpec(): NodeSpec {
  return {
    operator_id: "sql.statement.raw",
    operator_version: 1,
    plugin_slug: "external.sql",
    title: "Raw SQL statement",
    description: "Builds a parameterized SQL statement.",
    catalog_visible: true,
    config_schema: {
      type: "object",
      properties: {
        sql: {
          type: "string",
          title: "Sql",
          description:
            "SQL statement using canonical named :parameter placeholders.",
          format: "textarea",
          contentMediaType: "application/sql",
        },
      },
      required: ["sql"],
    },
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
  };
}

/** Mirrors llm.openai_compatible.chat_completion: short fields plus a secret. */
function chatCompletionSpec(): NodeSpec {
  return {
    operator_id: "llm.openai_compatible.chat_completion",
    operator_version: 1,
    plugin_slug: "llm",
    title: "OpenAI-compatible Chat Completion",
    description: "Calls an OpenAI-compatible Chat Completions endpoint.",
    catalog_visible: true,
    config_schema: {
      type: "object",
      properties: {
        base_url: {
          type: "string",
          title: "Base Url",
          description: "OpenAI-compatible API base URL, including its version path.",
        },
        model: {
          type: "string",
          title: "Model",
          description: "Provider model identifier.",
        },
        temperature: {
          type: "number",
          title: "Temperature",
          description: "Sampling temperature passed to the provider.",
          minimum: 0,
          maximum: 2,
        },
        timeout_ms: {
          type: "integer",
          title: "Timeout Ms",
          description: "Maximum provider request time in milliseconds.",
          minimum: 1000,
        },
        strict: {
          type: "boolean",
          title: "Strict",
          description: "Whether the provider must enforce a connected JSON Schema.",
        },
      },
    },
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
    secret_inputs: [
      {
        name: "api_key",
        title: "API key",
        description: "Write-only bearer credential for the configured base URL.",
        config_dependencies: ["base_url"],
      },
    ],
  };
}

function renderNode(
  id: string,
  data: ReturnType<typeof createWorkflowNodeData>,
  selected = false,
  dragging = false,
): { container: HTMLElement; root: ReturnType<typeof createRoot> } {
  const container = document.createElement("div");
  const root = createRoot(container);
  React.act(() => {
    root.render(
      <WorkflowNodeCard
        {...({ id, data, selected, dragging } as React.ComponentProps<
          typeof WorkflowNodeCard
        >)}
      />,
    );
  });
  return { container, root };
}

describe("WorkflowNode pickup", () => {
  it("defers the pickup remeasure until the spring lift settles", async () => {
    const data = createWorkflowNodeData(textPipeSpec());
    const node = renderNode("text", data);

    expect(
      node.container.querySelector('[data-node-pickup-shadow="true"]')
        ?.getAttribute("data-picked-up"),
    ).toBe("false");
    xyflowMocks.updateNodeInternals.mockClear();

    React.act(() => {
      node.root.render(
        <WorkflowNodeCard
          {...({
            id: "text",
            data,
            selected: true,
            dragging: false,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });
    expect(
      node.container.querySelector('[data-node-pickup-shadow="true"]')
        ?.getAttribute("data-picked-up"),
    ).toBe("true");
    // Option C rides a 200ms spring; handles remeasure per frame while it
    // runs so edges track the lift instead of jumping at settle.
    expect(xyflowMocks.updateNodeInternals).not.toHaveBeenCalled();
    await vi.waitFor(() =>
      expect(xyflowMocks.updateNodeInternals).toHaveBeenCalled(),
    );
    xyflowMocks.updateNodeInternals.mockClear();

    React.act(() => {
      node.root.render(
        <WorkflowNodeCard
          {...({
            id: "text",
            data,
            selected: true,
            dragging: true,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });
    expect(
      node.container.querySelector('[data-node-pickup-shadow="true"]')
        ?.getAttribute("data-dragging"),
    ).toBe("true");
    // A real drag snaps the spring and remeasures immediately for the drag loop.
    expect(xyflowMocks.updateNodeInternals).toHaveBeenCalledOnce();

    React.act(() => node.root.unmount());
  });

  it("hold-lifts the whole selection when holding one of its members", async () => {
    const data = createWorkflowNodeData(textPipeSpec());
    const first = renderNode("text-a", data, true);
    const second = renderNode("text-b", data, true);

    const plateOf = (node: { container: HTMLElement }) =>
      node.container.querySelector('[data-node-pickup-shadow="true"]');
    expect(plateOf(first)?.getAttribute("data-dragging")).toBe("false");
    expect(plateOf(second)?.getAttribute("data-dragging")).toBe("false");

    const stack = first.container.firstElementChild as HTMLElement;
    React.act(() => {
      // jsdom has no PointerEvent; React keys pointer handlers off the native
      // type name, so a MouseEvent with the pointer type behaves the same.
      stack.dispatchEvent(
        new MouseEvent("pointerdown", { bubbles: true, button: 0 }),
      );
    });

    // The hold promotion lands after HOLD_TO_LIFT_MS and lifts both members.
    await React.act(async () => {
      await vi.waitFor(() => {
        expect(plateOf(first)?.getAttribute("data-dragging")).toBe("true");
        expect(plateOf(second)?.getAttribute("data-dragging")).toBe("true");
      });
    });

    React.act(() => {
      window.dispatchEvent(new MouseEvent("pointerup", { bubbles: true }));
    });

    await React.act(async () => {
      await vi.waitFor(() => {
        expect(plateOf(first)?.getAttribute("data-dragging")).toBe("false");
        expect(plateOf(second)?.getAttribute("data-dragging")).toBe("false");
      });
    });

    React.act(() => first.root.unmount());
    React.act(() => second.root.unmount());
  });
});

function brickAreas(container: HTMLElement): string[] {
  return [
    ...container.querySelectorAll<HTMLElement>('[data-testid="config-brick"]'),
  ].map((brick) => `${brick.style.gridColumn} | ${brick.style.gridRow}`);
}

function enterInputValue(input: HTMLInputElement, value: string): void {
  const valueSetter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  if (!valueSetter) throw new Error("HTML input value setter is unavailable");
  valueSetter.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("WorkflowNode module upgrade", () => {
  it("shows an upgrade affordance when a newer library release exists", () => {
    const onUpgradeModuleCall = vi.fn();
    const data = createWorkflowNodeData({
      operator_id: "graph.module.00000000-0000-4000-8000-000000000001",
      operator_version: 1,
      plugin_slug: "graph.module",
      title: "Normalize text",
      description: "Module call",
      catalog_visible: true,
      config_schema: {},
      input_schema: {},
      output_schema: {},
      inputs: [],
      outputs: [],
      module_graph_id: "00000000-0000-4000-8000-000000000001",
      module_graph_revision: 1,
      module_id: "10000000-0000-4000-8000-000000000001",
      is_current_library_release: false,
    });
    data.moduleUpgradeRelease = 2;
    data.onUpgradeModuleCall = onUpgradeModuleCall;

    const container = document.createElement("div");
    const root = createRoot(container);
    React.act(() => {
      root.render(
        <WorkflowNodeCard
          {...({
            id: "module-call",
            data,
            selected: true,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });

    const upgradeButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Upgrade module call to release 2"]',
    );
    expect(upgradeButton).not.toBeNull();
    expect(upgradeButton?.textContent).toContain("Upgrade to release 2");
    React.act(() => upgradeButton?.click());
    expect(onUpgradeModuleCall).toHaveBeenCalledWith("module-call");
    React.act(() => root.unmount());
  });
});

describe("WorkflowNode compatibility rendering", () => {
  it("renders an unsupported node with inert historical handles and removal", () => {
    const removeNode = vi.fn();
    const input = { portName: "request", plugId: "plug-1" };
    const output = { portName: "result" };
    const data = createWorkflowNodeData(unavailableSpec());
    data.config = { preserved: true };
    data.compatibility = {
      status: "unsupported",
      issues: ["Operator legacy.operator@4 is unavailable."],
      inputs: [input],
      outputs: [output],
      persistedNode: {
        id: "legacy-node",
        operator_id: "legacy.operator",
        operator_version: 4,
        config: { preserved: true },
        position: { x: 10, y: 20 },
        input_plugs: [{ id: "plug-1", port: "request" }],
        artifact_type_bindings: [],
      },
    };
    data.onRemoveNode = removeNode;

    const container = document.createElement("div");
    const root = createRoot(container);
    React.act(() => {
      root.render(
        <WorkflowNodeCard
          {...({
            id: "legacy-node",
            data,
            selected: false,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });

    expect(
      container.querySelector(
        '[aria-label="legacy.operator unsupported node"]',
      ),
    ).not.toBeNull();
    expect(container.textContent).toContain("unsupported");
    expect(container.textContent).toContain(
      "Operator legacy.operator@4 is unavailable.",
    );
    expect(container.textContent).toContain('"preserved": true');

    const handles = [
      ...container.querySelectorAll<HTMLElement>(
        '[data-testid="compatibility-handle"]',
      ),
    ];
    expect(handles).toHaveLength(2);
    expect(handles.map((handle) => handle.dataset.handleId)).toEqual([
      compatibilityHandleId("input", input),
      compatibilityHandleId("output", output),
    ]);
    expect(
      handles.every((handle) => handle.dataset.connectable === "false"),
    ).toBe(true);

    const removeButton = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Remove legacy.operator"]',
    );
    expect(removeButton).not.toBeNull();
    React.act(() => removeButton?.click());
    expect(removeNode).toHaveBeenCalledWith("legacy-node");
    React.act(() => root.unmount());
  });
});

describe("WorkflowNode fixed numeric tuple fields", () => {
  it("renders coordinate inputs and emits a complete number array", () => {
    const onConfigChange = vi.fn();
    const data = createWorkflowNodeData(boundsSpec());
    data.onConfigChange = onConfigChange;

    const container = document.createElement("div");
    const root = createRoot(container);
    React.act(() => {
      root.render(
        <WorkflowNodeCard
          {...({
            id: "wms-layer",
            data,
            selected: false,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });

    const labels = [
      "Bounds: West longitude",
      "Bounds: South latitude",
      "Bounds: East longitude",
      "Bounds: North latitude",
    ];
    const inputs = labels.map((label) => {
      const input = container.querySelector<HTMLInputElement>(
        `input[aria-label="${label}"]`,
      );
      expect(input).not.toBeNull();
      return input!;
    });

    expect(inputs.map((input) => input.step)).toEqual([
      "any",
      "any",
      "any",
      "any",
    ]);
    expect(inputs.map((input) => [input.min, input.max])).toEqual([
      ["-180", "180"],
      ["-90", "90"],
      ["-180", "180"],
      ["-90", "90"],
    ]);

    ["181", "49.97", "19.82", "50.03"].forEach((value, index) => {
      React.act(() => enterInputValue(inputs[index]!, value));
    });

    expect(onConfigChange.mock.calls.map(([, , value]) => value)).toEqual([
      undefined,
      undefined,
      undefined,
      undefined,
    ]);
    React.act(() => enterInputValue(inputs[0]!, "19.75"));

    expect(onConfigChange).toHaveBeenLastCalledWith(
      "wms-layer",
      "bounds",
      [19.75, 49.97, 19.82, 50.03],
    );
    expect(
      onConfigChange.mock.calls.every(
        ([, , configValue]) => typeof configValue !== "string",
      ),
    ).toBe(true);
    React.act(() => root.unmount());
  });
});


describe("WorkflowNode string-list fields", () => {
  it("edits, appends, and removes string values through the node form", () => {
    const onConfigChange = vi.fn();
    const data = createWorkflowNodeData(fuzzyMatchSpec());
    data.config = {
      right_alias_columns: ["candidate_current_name_normalized"],
    };
    data.onConfigChange = onConfigChange;

    const container = document.createElement("div");
    const root = createRoot(container);
    React.act(() => {
      root.render(
        <WorkflowNodeCard
          {...({
            id: "fuzzy-match",
            data,
            selected: false,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });

    const input = container.querySelector<HTMLInputElement>(
      'input[aria-label="Right Alias Columns item 1"]',
    );
    expect(input?.value).toBe("candidate_current_name_normalized");
    React.act(() => enterInputValue(input!, "alternate_name"));
    expect(onConfigChange).toHaveBeenLastCalledWith(
      "fuzzy-match",
      "right_alias_columns",
      ["alternate_name"],
    );

    React.act(() => {
      container.querySelector<HTMLButtonElement>(
        'button[aria-label="Add Right Alias Columns item"]',
      )?.click();
    });
    expect(onConfigChange).toHaveBeenLastCalledWith(
      "fuzzy-match",
      "right_alias_columns",
      ["candidate_current_name_normalized", ""],
    );

    React.act(() => {
      container.querySelector<HTMLButtonElement>(
        'button[aria-label="Remove Right Alias Columns item 1"]',
      )?.click();
    });
    expect(onConfigChange).toHaveBeenLastCalledWith(
      "fuzzy-match",
      "right_alias_columns",
      [],
    );
    React.act(() => root.unmount());
  });
});

describe("WorkflowNode config lattice", () => {
  it("packs bricks in schema order, pairing half-width fields on a shelf", () => {
    const data = createWorkflowNodeData(chatCompletionSpec());
    const { container, root } = renderNode("chat", data);

    const board = container.querySelector<HTMLElement>(
      '[data-testid="config-board"]',
    );
    expect(board?.style.gridTemplateColumns).toBe("repeat(6, minmax(0, 1fr))");
    // 2 shelves of paired fields, a boolean shelf, then the 2-cell secret.
    expect(board?.style.gridTemplateRows).toBe("repeat(5, minmax(50px, auto))");
    expect(brickAreas(container)).toEqual([
      "1 / span 3 | 1 / span 1",
      "4 / span 3 | 1 / span 1",
      "1 / span 3 | 2 / span 1",
      "4 / span 3 | 2 / span 1",
      // Compact 3×1 checkbox grows into the leftover half of its shelf.
      "1 / span 6 | 3 / span 1",
      "1 / span 6 | 4 / span 2",
    ]);
    // Schema order is preserved across the board.
    const labels = [
      ...container.querySelectorAll<HTMLElement>(
        '[data-testid="config-brick"]',
      ),
    ].map((brick) => brick.textContent?.slice(0, 5));
    expect(labels).toEqual([
      "Base ",
      "Model",
      "Tempe",
      "Timeo",
      "Stric",
      "API k",
    ]);

    React.act(() => root.unmount());
  });

  it("renders advertised config fields next to the table file picker", () => {
    const data = createWorkflowNodeData(tableFileImportSpec());
    const { container, root } = renderNode("table-file", data);

    expect(container.textContent).toContain("Choose CSV or XLSX");
    const text = container.textContent ?? "";
    expect(text.indexOf("Choose CSV or XLSX")).toBeGreaterThan(
      text.indexOf("Skip Empty Rows"),
    );
    const bricks = [
      ...container.querySelectorAll<HTMLElement>(
        '[data-testid="config-brick"]',
      ),
    ].map((brick) => brick.textContent);
    expect(bricks.some((text) => text?.includes("Sheet Name"))).toBe(true);
    expect(bricks.some((text) => text?.includes("Header Row"))).toBe(true);
    expect(bricks.some((text) => text?.includes("Delimiter"))).toBe(true);
    expect(bricks.some((text) => text?.includes("Skip Empty Rows"))).toBe(true);
    expect(bricks.some((text) => text?.includes("Uploads"))).toBe(false);

    React.act(() => root.unmount());
  });

  it("keeps the same shelf topology when widened so bricks stretch instead", () => {
    const data = createWorkflowNodeData(chatCompletionSpec());
    data.layout = { width: 600 };
    const { container, root } = renderNode("chat", data);

    const board = container.querySelector<HTMLElement>(
      '[data-testid="config-board"]',
    );
    // 600px is still below 3× comfortable half-brick — packer stays at 6 cols
    // and the 1fr tracks do the growing (labels get more characters).
    expect(board?.style.gridTemplateColumns).toBe("repeat(6, minmax(0, 1fr))");
    expect(board?.style.gridTemplateRows).toBe("repeat(5, minmax(50px, auto))");
    expect(brickAreas(container)).toEqual([
      "1 / span 3 | 1 / span 1",
      "4 / span 3 | 1 / span 1",
      "1 / span 3 | 2 / span 1",
      "4 / span 3 | 2 / span 1",
      "1 / span 6 | 3 / span 1",
      "1 / span 6 | 4 / span 2",
    ]);

    React.act(() => root.unmount());
  });

  it("reflows into more columns once another comfortable half-brick fits", () => {
    const data = createWorkflowNodeData(chatCompletionSpec());
    data.layout = { width: 660 };
    const { container, root } = renderNode("chat", data);

    const board = container.querySelector<HTMLElement>(
      '[data-testid="config-board"]',
    );
    expect(board?.style.gridTemplateColumns).toBe("repeat(9, minmax(0, 1fr))");
    // Three shorts share the first shelf; timeout + short strict share the next
    // and split the leftover three columns (5 + 4).
    expect(brickAreas(container)).toEqual([
      "1 / span 3 | 1 / span 1",
      "4 / span 3 | 1 / span 1",
      "7 / span 3 | 1 / span 1",
      "1 / span 5 | 2 / span 1",
      "6 / span 4 | 2 / span 1",
      "1 / span 9 | 3 / span 2",
    ]);

    React.act(() => root.unmount());
  });

  it("grows the body past a saved height that cannot hold the bricks", () => {
    const data = createWorkflowNodeData(rawSqlStatementSpec());
    data.config = { sql: "select *\nfrom parcels" };
    data.layout = { bodyHeight: 50 };
    const { container, root } = renderNode("sql-statement", data);

    const board = container.querySelector<HTMLElement>(
      '[data-testid="config-board"]',
    );
    // One requested cell cannot hold a two-cell code brick.
    expect(board?.style.gridTemplateRows).toBe("repeat(2, minmax(50px, auto))");
    expect(brickAreas(container)).toEqual(["1 / span 6 | 1 / span 2"]);
    expect(container.querySelector("textarea")?.value).toBe(
      "select *\nfrom parcels",
    );

    React.act(() => root.unmount());
  });

  it("hands a taller saved body to the growable brick", () => {
    const data = createWorkflowNodeData(rawSqlStatementSpec());
    data.config = { sql: "select 1" };
    data.layout = { bodyHeight: 300 };
    const { container, root } = renderNode("sql-statement", data);

    const board = container.querySelector<HTMLElement>(
      '[data-testid="config-board"]',
    );
    expect(board?.style.gridTemplateRows).toBe("repeat(6, minmax(50px, auto))");
    expect(brickAreas(container)).toEqual(["1 / span 6 | 1 / span 6"]);

    React.act(() => root.unmount());
  });
});

describe("configFieldLabelIsRedundant", () => {
  function fieldBrick(
    title: string,
    type: "string" | "boolean" = "string",
  ): ConfigBrick {
    const field = {
      name: "field",
      title,
      type,
      required: false,
      nullable: false,
    } as const;
    return {
      kind: "field",
      field: field as never,
      footprint: fieldFootprint(field as never),
    };
  }

  it("hides a lone field whose title the node title already contains", () => {
    expect(
      configFieldLabelIsRedundant("Text input", [fieldBrick("Text")]),
    ).toBe(true);
    expect(
      configFieldLabelIsRedundant("Text input", [fieldBrick("Prompt")]),
    ).toBe(false);
    expect(
      configFieldLabelIsRedundant("Text input", [
        fieldBrick("Text"),
        fieldBrick("Extra"),
      ]),
    ).toBe(false);
    expect(
      configFieldLabelIsRedundant("Strict mode", [fieldBrick("Strict", "boolean")]),
    ).toBe(false);
  });
});

describe("WorkflowNode header", () => {
  it("keeps unselected chrome to the title and gates actions behind selection", () => {
    const data = createWorkflowNodeData(chatCompletionSpec());
    const unselected = renderNode("chat", data);
    expect(
      unselected.container.querySelector(
        'button[aria-label="Actions for OpenAI-compatible Chat Completion"]',
      ),
    ).toBeNull();
    expect(
      unselected.container.querySelector(
        'button[aria-label="About OpenAI-compatible Chat Completion"]',
      ),
    ).toBeNull();
    expect(unselected.container.textContent).toContain(
      "OpenAI-compatible Chat Completion",
    );
    expect(unselected.container.textContent).not.toContain(
      "llm.openai_compatible.chat_completion@1",
    );
    React.act(() => unselected.root.unmount());

    const removeNode = vi.fn();
    data.onRemoveNode = removeNode;
    const selected = renderNode("chat", data, true);
    expect(
      selected.container.querySelector(
        'button[aria-label="Actions for OpenAI-compatible Chat Completion"]',
      ),
    ).not.toBeNull();
    // Deleting is one level down the overflow menu, never a bare X on the chrome.
    const deleteItem = [
      ...selected.container.querySelectorAll<HTMLButtonElement>("button"),
    ].find((button) => button.textContent === "Delete node");
    expect(deleteItem).toBeDefined();
    React.act(() => deleteItem?.click());
    expect(removeNode).toHaveBeenCalledWith("chat");
    // Provenance now lives in the about popover instead of the card chrome.
    expect(selected.container.textContent).toContain(
      "llm.openai_compatible.chat_completion@1",
    );
    React.act(() => selected.root.unmount());
  });

  it("reports execution status without a badge row", () => {
    const data = createWorkflowNodeData(chatCompletionSpec());
    data.execution = { status: "failed", error: "Provider rejected the request" };
    const { container, root } = renderNode("chat", data);

    const status = container.querySelector('[aria-label="Execution failed"]');
    expect(status).not.toBeNull();
    expect(status?.textContent).toBe("");

    React.act(() => root.unmount());
  });

  it("shows durable generation state while preserving the normal node card", () => {
    const data = createWorkflowNodeData(chatCompletionSpec());
    data.generation = {
      draftId: "draft-1",
      runId: "run-1",
      buildId: "build-1",
      threadId: "thread-1",
      environmentId: "environment-1",
      state: "coding",
      error: null,
      capabilities: null,
      capabilityDigest: null,
      capabilityApprovalId: null,
      releaseRevision: null,
      targetOperatorVersion: 1,
      lastEventSequence: 0,
    };
    const { container, root } = renderNode("generated", data, true);

    expect(container.querySelector('[aria-label="Draft coding"]')).not.toBeNull();
    expect(container.textContent).toContain("Revision 1 · coding");
    expect(container.textContent).toContain("OpenAI-compatible Chat Completion");

    React.act(() => root.unmount());
  });

  it("opens verified review before exposing approval and publication", () => {
    const data = createWorkflowNodeData(chatCompletionSpec());
    const review = vi.fn();
    data.generation = {
      draftId: "draft-1",
      runId: "run-1",
      buildId: "build-1",
      threadId: "thread-1",
      environmentId: "environment-1",
      state: "awaiting_approval",
      error: null,
      capabilities: null,
      capabilityDigest: "a".repeat(64),
      capabilityApprovalId: null,
      releaseRevision: null,
      targetOperatorVersion: 1,
      lastEventSequence: 9,
    };
    data.onReviewGeneratedNode = review;
    const node = renderNode("generated", data, true);
    const reviewButton = node.container.querySelector<HTMLButtonElement>(
      '[aria-label^="Review generated build"]',
    );
    React.act(() => reviewButton?.click());
    expect(review).toHaveBeenCalledWith("generated", data.generation);
    expect(node.container.textContent).not.toContain("Approve capabilities");

    React.act(() => node.root.unmount());
  });

  it("keeps review and approve visible without selecting the node", () => {
    const data = createWorkflowNodeData(chatCompletionSpec());
    data.generation = {
      draftId: "draft-1",
      runId: "run-1",
      buildId: "build-1",
      threadId: "thread-1",
      environmentId: "environment-1",
      state: "awaiting_approval",
      error: null,
      capabilities: null,
      capabilityDigest: "a".repeat(64),
      capabilityApprovalId: null,
      releaseRevision: null,
      targetOperatorVersion: 1,
      lastEventSequence: 9,
    };
    data.onReviewGeneratedNode = vi.fn();
    const node = renderNode("generated", data, false);

    expect(
      node.container.querySelector('[aria-label^="Review generated build"]'),
    ).not.toBeNull();
    expect(node.container.textContent).toContain("awaiting approval");

    React.act(() => node.root.unmount());
  });

  it("keeps the published version runnable while showing the next revision", () => {
    const spec = {
      ...chatCompletionSpec(),
      agent_authoring: {
        draft_node_id: "draft-1",
        status: "published" as const,
        runnable: true,
        release_revision: 1,
      },
    };
    const data = createWorkflowNodeData(spec);
    const iterate = vi.fn();
    data.generation = {
      draftId: "draft-1",
      runId: "run-1",
      buildId: "build-1",
      threadId: "thread-1",
      environmentId: "environment-1",
      state: "published",
      error: null,
      capabilities: null,
      capabilityDigest: null,
      capabilityApprovalId: "approval-1",
      releaseRevision: 1,
      targetOperatorVersion: 1,
      lastEventSequence: 12,
    };
    data.onIterateGeneratedNode = iterate;
    const node = renderNode("generated", data, true);
    const iterateButton = node.container.querySelector<HTMLButtonElement>(
      '[aria-label^="Iterate on"]',
    );
    React.act(() => iterateButton?.click());
    expect(iterate).toHaveBeenCalledWith("generated", data.generation);

    data.generation = {
      ...data.generation,
      runId: "run-2",
      buildId: "build-2",
      state: "coding",
      capabilityApprovalId: null,
      targetOperatorVersion: 2,
      lastEventSequence: 14,
    };
    React.act(() => {
      node.root.render(
        <WorkflowNodeCard
          {...({ id: "generated", data, selected: true } as React.ComponentProps<
            typeof WorkflowNodeCard
          >)}
        />,
      );
    });
    expect(node.container.textContent).toContain("Revision 2 · coding");
    expect(node.container.querySelector('[aria-label^="Iterate on"]')).toBeNull();
    expect(data.spec.operator_version).toBe(1);

    React.act(() => node.root.unmount());
  });
});

describe("WorkflowNode multiline fields", () => {

  it("exposes a textarea field resize grip and hides corner resize by default", () => {
    gridSettingsMocks.allowWorkflowCornerResize = false;
    const data = createWorkflowNodeData(rawSqlStatementSpec());
    data.config = { sql: "select 1" };

    const container = document.createElement("div");
    const root = createRoot(container);
    React.act(() => {
      root.render(
        <WorkflowNodeCard
          {...({
            id: "sql-statement",
            data,
            selected: false,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });

    expect(
      container.querySelector('[data-testid="textarea-body-resize"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="corner-resize"]'),
    ).toBeNull();

    React.act(() => root.unmount());
  });

  it("shows the workflow corner resize handle when the lab flag is on", () => {
    gridSettingsMocks.allowWorkflowCornerResize = true;
    const data = createWorkflowNodeData(rawSqlStatementSpec());
    data.config = { sql: "select 1" };

    const container = document.createElement("div");
    const root = createRoot(container);
    React.act(() => {
      root.render(
        <WorkflowNodeCard
          {...({
            id: "sql-statement",
            data,
            selected: false,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });

    expect(
      container.querySelector('[data-testid="corner-resize"]'),
    ).not.toBeNull();

    gridSettingsMocks.allowWorkflowCornerResize = false;
    React.act(() => root.unmount());
  });
});

describe("WorkflowNode port rail", () => {
  it("pairs inputs and outputs on shared lattice-tall rows before the body", () => {
    const data = createWorkflowNodeData(textPipeSpec());
    const container = document.createElement("div");
    const root = createRoot(container);
    React.act(() => {
      root.render(
        <WorkflowNodeCard
          {...({
            id: "text-pipe",
            data,
            selected: false,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });

    const rail = container.querySelector('[data-testid="port-rail"]');
    expect(rail).not.toBeNull();
    const rows = [
      ...container.querySelectorAll('[data-testid="port-rail-row"]'),
    ] as HTMLElement[];
    expect(rows).toHaveLength(2);
    expect(rows[0]?.style.height).toBe("50px");
    expect(rows[1]?.style.height).toBe("50px");
    // First row carries both the required input and the first output.
    expect(rows[0]?.textContent).toContain("text");
    expect(rows[0]?.textContent).toMatch(/\*/);
    expect(rows[1]?.textContent).toContain("meta");

    React.act(() => root.unmount());
  });

});

describe("WorkflowNode artifact table query relations", () => {
  it("keeps SQL statements as ordinary plugs and edits named table relations", () => {
    const onRelationsChange = vi.fn();
    const data = createWorkflowNodeData(artifactQuerySpec());
    data.onArtifactQueryRelationsChange = onRelationsChange;
    const relationPlug = data.inputPlugs.find(
      (plug) => plug.portName === "relations",
    );

    const container = document.createElement("div");
    const root = createRoot(container);
    React.act(() => {
      root.render(
        <WorkflowNodeCard
          {...({
            id: "artifact-query",
            data,
            selected: false,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });

    expect(container.textContent).toContain("Statements");
    expect(container.textContent).toContain("Relations");
    const aliasInput = container.querySelector<HTMLInputElement>(
      'input[aria-label="Relation 1 SQL alias"]',
    );
    expect(aliasInput?.value).toBe("relation_1");
    expect(
      container.querySelector<HTMLButtonElement>(
        'button[aria-label="Remove relation 1"]',
      )?.disabled,
    ).toBe(true);

    React.act(() => enterInputValue(aliasInput!, "parcels"));
    expect(onRelationsChange).toHaveBeenLastCalledWith(
      "artifact-query",
      [{ id: relationPlug?.id, alias: "parcels" }],
      expect.arrayContaining([
        { id: relationPlug?.id, portName: "relations" },
      ]),
    );

    const addRelationButton = [
      ...container.querySelectorAll<HTMLButtonElement>("button"),
    ].find((button) => button.textContent?.includes("Add relation"));
    expect(addRelationButton).toBeDefined();
    React.act(() => addRelationButton?.click());
    const addedRelations = onRelationsChange.mock.calls.at(-1)?.[1];
    expect(addedRelations).toHaveLength(2);
    expect(addedRelations[0]).toEqual({
      id: relationPlug?.id,
      alias: "relation_1",
    });
    expect(addedRelations[1].alias).toBe("relation_2");
    React.act(() => root.unmount());
  });
});

describe("WorkflowNode execution progress", () => {
  it("integrates the selected execution appendix without remeasuring every event", () => {
    const data = createWorkflowNodeData(boundsSpec());
    const container = document.createElement("div");
    const root = createRoot(container);
    React.act(() => {
      root.render(
        <WorkflowNodeCard
          {...({
            id: "module-1",
            data,
            selected: false,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });
    xyflowMocks.updateNodeInternals.mockClear();

    const materializedRun: NonNullable<typeof data.run> = {
      node_id: "module-1",
      status: "succeeded",
      error: null,
      outputs: [{
        port: "result",
        kind: "single",
        value: {
          artifact_id: "artifact-1",
          artifact_type: "json.object",
          schema_version: 1,
        },
        artifacts: [{
          artifact_id: "artifact-1",
          artifact_type: "json.object",
          schema_version: 1,
          content_type: "application/json",
          text: '{"ready":true}',
        }],
      }],
    };
    const withProgress: typeof data = {
      ...data,
      progress: {
        omittedCount: 1,
        entries: [
          {
            sequence: 1,
            sourceNodePath: [],
            invocationIndex: null,
            invocationPath: [],
            message: "Queued",
            current: null,
            total: null,
          },
          {
            sequence: 3,
            sourceNodePath: ["branch-a", "inner-1"],
            invocationIndex: 3,
            invocationPath: [2, 1],
            message: "<script>Preparing the payload</script>",
            current: 2,
            total: 5,
          },
          {
            sequence: 2,
            sourceNodePath: ["branch-b"],
            invocationIndex: 0,
            invocationPath: [],
            message: "Uploading",
            current: null,
            total: null,
          },
        ],
      },
    };
    React.act(() => {
      root.render(
        <WorkflowNodeCard
          {...({
            id: "module-1",
            data: withProgress,
            selected: true,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });

    const appendix = container.querySelector<HTMLElement>(
      '[aria-label="Remote WMS map layer execution appendix"]',
    );
    expect(appendix).not.toBeNull();
    expect(appendix?.classList).toContain("nodrag");
    expect(appendix?.classList).toContain("nowheel");
    expect(
      [...appendix!.querySelectorAll('[role="tab"]')].map(
        (tab) => tab.textContent,
      ),
    ).toEqual(["Events 4", "History 0"]);
    expect(appendix?.textContent).toContain("1 earlier update omitted");
    expect(appendix?.textContent).toContain(
      "branch-a › inner-1 · items 3 › 2",
    );
    expect(appendix?.textContent).toContain("2 / 5");
    expect(appendix?.textContent).toContain(
      "<script>Preparing the payload</script>",
    );
    expect(appendix?.querySelector("script")).toBeNull();
    expect(appendix?.textContent).not.toContain("Uploading");
    expect(appendix?.textContent).not.toContain("Queued");
    expect(
      appendix?.querySelector<HTMLButtonElement>(
        'button[aria-label="Show 2 earlier events"]',
      )?.textContent,
    ).toBe("+2");
    expect(xyflowMocks.updateNodeInternals).toHaveBeenCalledOnce();

    xyflowMocks.updateNodeInternals.mockClear();
    const withMaterialization: typeof data = {
      ...withProgress,
      run: materializedRun,
    };
    React.act(() => {
      root.render(
        <WorkflowNodeCard
          {...({
            id: "module-1",
            data: withMaterialization,
            selected: true,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });
    expect(container.textContent).not.toContain("Produced artifacts");
    expect(xyflowMocks.updateNodeInternals).toHaveBeenCalledOnce();

    xyflowMocks.updateNodeInternals.mockClear();
    const withMoreProgress: typeof data = {
      ...withMaterialization,
      progress: {
        ...withProgress.progress!,
        entries: [
          ...withProgress.progress!.entries,
          {
            sequence: 4,
            sourceNodePath: ["branch-c"],
            invocationIndex: 1,
            invocationPath: [],
            message: "Completed",
            current: null,
            total: null,
          },
        ],
      },
    };
    React.act(() => {
      root.render(
        <WorkflowNodeCard
          {...({
            id: "module-1",
            data: withMoreProgress,
            selected: true,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      );
    });
    expect(xyflowMocks.updateNodeInternals).not.toHaveBeenCalled();
    expect(appendix?.textContent).toContain("branch-c · item 2 · Completed");
    expect(appendix?.textContent).not.toContain("Preparing the payload");

    const discloseEarlierEvents = appendix?.querySelector<HTMLButtonElement>(
      'button[aria-label="Show 3 earlier events"]',
    );
    expect(discloseEarlierEvents?.textContent).toBe("+3");
    React.act(() => discloseEarlierEvents?.click());

    const earlierEvents = appendix?.querySelector<HTMLOListElement>(
      'ol[aria-label="Earlier events"]',
    );
    expect(
      [...(earlierEvents?.querySelectorAll("li") ?? [])].map(
        (event) => event.textContent,
      ),
    ).toEqual([
      "branch-a › inner-1 · items 3 › 2 · <script>Preparing the payload</script> · 2 / 5",
      "branch-b · item 1 · Uploading",
      "Remote WMS map layer · Queued",
    ]);
    expect(earlierEvents?.querySelector("script")).toBeNull();
    React.act(() => root.unmount());
  });
});
