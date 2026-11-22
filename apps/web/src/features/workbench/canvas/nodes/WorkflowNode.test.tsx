// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, afterEach, it, vi } from "vitest";

import type { CanvasNode } from "../artifact-viewer";
import type { WorkflowEdge, WorkflowNodeData } from "../types";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const xyflowMocks = vi.hoisted(() => ({
  updateNodeInternals: vi.fn(),
  edges: [] as WorkflowEdge[],
  nodes: [] as CanvasNode[],
}));

vi.mock("@xyflow/react", () => ({
  useNodeId: () => null,
  Handle: ({
    id,
    isConnectable,
    children,
  }: {
    id: string;
    isConnectable: boolean;
    children?: React.ReactNode;
  }) => (
    <span
      data-testid="compatibility-handle"
      data-handle-id={id}
      data-connectable={String(isConnectable)}
    >
      {children}
    </span>
  ),
  Position: { Left: "left", Right: "right" },
  useEdges: () => xyflowMocks.edges,
  useNodes: () => xyflowMocks.nodes,
  useNodeConnections: () => [],
  useConnection: (selector: (state: { inProgress: boolean }) => unknown) =>
    selector({ inProgress: false }),
  useStore: (
    selector: (state: {
      edges: unknown[];
      nodeLookup: Map<string, unknown>;
    }) => unknown,
  ) =>
    selector({
      edges: xyflowMocks.edges,
      nodeLookup: new Map(xyflowMocks.nodes.map((node) => [node.id, node])),
    }),
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

vi.mock("@base-ui/react/menu", () => {
  const menuRadio = React.createContext<((value: string) => void) | undefined>(
    undefined,
  );
  return {
    Menu: {
      Root: ({ children }: { children: React.ReactNode }) => <>{children}</>,
      // Like Base UI's: a `render` element becomes the trigger, taking its
      // props and children.
      Trigger: ({
        children,
        render,
        ...props
      }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
        render?: React.ReactElement<Record<string, unknown>>;
      }) =>
        render ? (
          React.cloneElement(render, props, children)
        ) : (
          <button type="button" {...props}>
            {children}
          </button>
        ),
      Portal: ({ children }: { children: React.ReactNode }) => <>{children}</>,
      Positioner: ({ children }: { children: React.ReactNode }) => (
        <>{children}</>
      ),
      Popup: ({ children }: { children: React.ReactNode }) => (
        <div role="menu">{children}</div>
      ),
      Group: ({ children }: { children: React.ReactNode }) => (
        <div role="group">{children}</div>
      ),
      GroupLabel: ({ children }: { children: React.ReactNode }) => (
        <div>{children}</div>
      ),
      Separator: () => <hr />,
      Item: ({
        children,
        ...props
      }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
        <button type="button" {...props}>
          {children}
        </button>
      ),
      RadioGroup: ({
        children,
        onValueChange,
      }: {
        children: React.ReactNode;
        value?: string;
        onValueChange?: (value: string) => void;
      }) => (
        <menuRadio.Provider value={onValueChange}>
          <div role="radiogroup">{children}</div>
        </menuRadio.Provider>
      ),
      RadioItem: ({
        children,
        value,
        ...props
      }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
        value?: string;
      }) => {
        const onValueChange = React.useContext(menuRadio);
        return (
          <button
            type="button"
            {...props}
            onClick={() => {
              if (typeof value === "string") onValueChange?.(value);
            }}
          >
            {children}
          </button>
        );
      },
      RadioItemIndicator: ({ children }: { children?: React.ReactNode }) => (
        <>{children}</>
      ),
    },
  };
});

vi.mock("@base-ui/react/popover", () => {
  // Like Base UI's: the root owns open state (controlled when given `open`),
  // the trigger toggles it and honours `render`, and the popup only mounts
  // while open. A trigger outside any root (a port's inspector, whose root is
  // mocked away below) stays a plain button.
  const popover = React.createContext<{
    open: boolean;
    setOpen: (open: boolean) => void;
  } | null>(null);
  return {
    Popover: {
      Root: ({
        children,
        open,
        onOpenChange,
      }: {
        children: React.ReactNode;
        open?: boolean;
        onOpenChange?: (open: boolean) => void;
      }) => {
        const [localOpen, setLocalOpen] = React.useState(false);
        const current = open ?? localOpen;
        return (
          <popover.Provider
            value={{
              open: current,
              setOpen: (next) => {
                setLocalOpen(next);
                onOpenChange?.(next);
              },
            }}
          >
            {children}
          </popover.Provider>
        );
      },
      Trigger: ({
        children,
        render,
        ...props
      }: React.ButtonHTMLAttributes<HTMLButtonElement> & {
        render?: React.ReactElement<Record<string, unknown>>;
      }) => {
        const state = React.useContext(popover);
        const triggerProps = {
          ...props,
          ...(state
            ? {
                "aria-expanded": state.open,
                onClick: () => state.setOpen(!state.open),
              }
            : {}),
        };
        return render ? (
          React.cloneElement(render, triggerProps, children)
        ) : (
          <button type="button" {...triggerProps}>
            {children}
          </button>
        );
      },
      Portal: ({ children }: { children: React.ReactNode }) => {
        const state = React.useContext(popover);
        return state && !state.open ? null : <>{children}</>;
      },
      Positioner: ({ children }: { children: React.ReactNode }) => (
        <>{children}</>
      ),
      Popup: ({ children, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
        <div role="dialog" {...props}>
          {children}
        </div>
      ),
    },
  };
});

vi.mock("./type-inspector", () => ({
  PortTypePopover: ({ children }: { children: React.ReactNode }) => children,
}));

import type { NodeSpec } from "@/lib/api";
import {
  artifactPortFixture,
  nodeSpecFixture,
  servicePortFixture,
} from "../../test-fixtures";
import {
  WORKFLOW_NODE_TYPE,
  compatibilityHandleId,
  createWorkflowNodeData,
  portMetaForPort,
} from "../types";
import { encodeHandleId } from "../handles";
import WorkflowNodeCard from "./WorkflowNode";
import {
  configFieldLabelIsRedundant,
  type ConfigBrick,
} from "./workflow/config-fields";
import { fieldFootprint } from "./field-footprints";
import { CredentialsPopover } from "./workflow/credentials-popover";
import {
  RASTER_LAYER_CONFIG_SCHEMA,
  VECTOR_LAYER_CONFIG_SCHEMA,
} from "./workflow/geo-layer-schemas.fixture";

function unavailableSpec(): NodeSpec {
  return nodeSpecFixture({
    operator_id: "python.transform",
    operator_version: 4,
    plugin_slug: "unavailable",
    title: "legacy.operator",
    description: "Unavailable operator",
    catalog_visible: false,
  });
}

function boundsSpec(): NodeSpec {
  return nodeSpecFixture({
    operator_id: "gis.map.wms_layer",
    plugin_slug: "gis",
    title: "Remote WMS map layer",
    description: "Adds a remote WMS layer.",
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
  });
}

function fuzzyMatchSpec(): NodeSpec {
  return nodeSpecFixture({
    operator_id: "table.fuzzy_match",
    plugin_slug: "builtin.table",
    title: "Fuzzy match tables",
    description: "Ranks candidate records.",
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
  });
}

/** Two required, variadic instance-plug inputs, so plug rows own their identity. */
function instancePlugsSpec(): NodeSpec {
  return nodeSpecFixture({
    operator_id: "sequence.interleave",
    plugin_slug: "sequence",
    title: "Interleave sequences",
    description: "Pairs the members of two sequences.",
    inputs: [
      artifactPortFixture({
        name: "headings",
        title: "Headings",
        direction: "input",
        artifact_type: { id: "text.markdown", schema_version: 1 },
        instance_plugs: true,
        variadic: true,
      }),
      artifactPortFixture({
        name: "rows",
        title: "Rows",
        direction: "input",
        artifact_type: { id: "table.data", schema_version: 1 },
        instance_plugs: true,
        variadic: true,
      }),
    ],
  });
}

function textPipeSpec(): NodeSpec {
  return nodeSpecFixture({
    operator_id: "text.pipe",
    plugin_slug: "text",
    title: "Text pipe",
    description: "Passes text through.",
    inputs: [
      artifactPortFixture({
        name: "text",
        direction: "input",
        artifact_type: { id: "text.plain", schema_version: 1 },
      }),
    ],
    outputs: [
      artifactPortFixture({
        name: "text",
        direction: "output",
        artifact_type: { id: "text.plain", schema_version: 1 },
        required: false,
      }),
      artifactPortFixture({
        name: "meta",
        direction: "output",
        artifact_type: { id: "json.document", schema_version: 1 },
        required: false,
      }),
    ],
  });
}

function multilineNoteSpec(): NodeSpec {
  return nodeSpecFixture({
    operator_id: "text.note.write",
    plugin_slug: "text",
    title: "Note",
    description: "Stores one long-form note.",
    config_schema: {
      type: "object",
      properties: {
        body: {
          type: "string",
          title: "Body",
          description: "Long-form text edited in the card body.",
          format: "textarea",
        },
      },
      required: ["body"],
    },
  });
}

/** Mirrors llm.openai_compatible.chat_completion: short fields plus a secret. */
function chatCompletionSpec(): NodeSpec {
  return nodeSpecFixture({
    operator_id: "llm.openai_compatible.chat_completion",
    plugin_slug: "llm",
    title: "OpenAI-compatible Chat Completion",
    description: "Calls an OpenAI-compatible Chat Completions endpoint.",
    config_schema: {
      type: "object",
      properties: {
        base_url: {
          type: "string",
          title: "Base Url",
          description:
            "OpenAI-compatible API base URL, including its version path.",
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
          description:
            "Whether the provider must enforce a connected JSON Schema.",
        },
      },
    },
    secret_inputs: [
      {
        name: "api_key",
        title: "API key",
        description:
          "Write-only bearer credential for the configured base URL.",
        config_dependencies: ["base_url"],
      },
    ],
  });
}

function sequenceCollectSpec(): NodeSpec {
  return nodeSpecFixture({
    // Collections render as artifact stacks; any generic operator shows the
    // type-binding row.
    operator_id: "sequence.slice",
    plugin_slug: "sequence",
    title: "Collect",
    description: "Collects one artifact type.",
    inputs: [
      artifactPortFixture({
        name: "items",
        title: "Items",
        direction: "input",
        artifact_type: null,
        artifact_type_variable: "T",
        shape: "many",
        instance_plugs: true,
      }),
    ],
  });
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
      node.container
        .querySelector('[data-canvas-node-shell="true"]')
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
      node.container
        .querySelector('[data-canvas-node-shell="true"]')
        ?.getAttribute("data-picked-up"),
    ).toBe("true");
    // Option C rides a 200ms spring. Nothing is measured while it travels — one
    // store-wide look per tier is worth 6.4ms and the animation crosses it freely —
    // so the measurement lands when the card stops.
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
      node.container
        .querySelector('[data-canvas-node-shell="true"]')
        ?.getAttribute("data-dragging"),
    ).toBe("true");
    // A real drag does not force a layout inside the gesture: the drag loop already
    // tells React Flow where the node is, and this tier is measured when it lands.
    // Counted as a delta because the card's own port motion measures too.
    const beforeDrag = xyflowMocks.updateNodeInternals.mock.calls.length;
    expect(xyflowMocks.updateNodeInternals).not.toHaveBeenCalled();
    await vi.waitFor(() =>
      expect(xyflowMocks.updateNodeInternals.mock.calls.length).toBeGreaterThan(
        beforeDrag,
      ),
    );

    React.act(() => node.root.unmount());
  });

  it("hold-lifts the whole selection when holding one of its members", async () => {
    const data = createWorkflowNodeData(textPipeSpec());
    const first = renderNode("text-a", data, true);
    const second = renderNode("text-b", data, true);

    const plateOf = (node: { container: HTMLElement }) =>
      node.container.querySelector('[data-canvas-node-shell="true"]');
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

describe("WorkflowNode compatibility rendering", () => {
  it("renders an unsupported node with inert historical handles and removal", () => {
    const removeNode = vi.fn();
    const input = { portName: "request", plugId: "plug-1" };
    const output = { portName: "result" };
    const data = createWorkflowNodeData(unavailableSpec());
    data.config = { preserved: true };
    data.compatibility = {
      status: "unsupported",
      issues: ["Operator python.transform@4 is unavailable."],
      inputs: [input],
      outputs: [output],
      persistedNode: {
        id: "legacy-node",
        kind: "builtin",
        operator_id: "python.transform",
        operator_version: 4,
        config: { preserved: true },
        position: { x: 10, y: 20 },
        input_plugs: [{ id: "plug-1", port: "request" }],
        artifact_type_bindings: [],
      },
    };
    data.onRemoveNode = removeNode;

    const { container, root } = renderNode("legacy-node", data);

    expect(
      container.querySelector(
        '[aria-label="legacy.operator unsupported node"]',
      ),
    ).not.toBeNull();
    expect(container.textContent).toContain("Unavailable");
    expect(container.textContent).toContain(
      "Operator python.transform@4 is unavailable.",
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

const BOUNDS_INPUT_LABELS = [
  "Bounds: West longitude",
  "Bounds: South latitude",
  "Bounds: East longitude",
  "Bounds: North latitude",
];

function nullableBoundsSpec(): NodeSpec {
  const spec = boundsSpec();
  const properties = (
    spec.config_schema as { properties: Record<string, unknown> }
  ).properties;
  return {
    ...spec,
    config_schema: {
      type: "object",
      properties: {
        bounds: {
          title: "Bounds",
          description:
            "WGS84 bounds ordered as west longitude, south latitude, east longitude, north latitude.",
          anyOf: [properties.bounds, { type: "null" }],
        },
      },
      required: ["bounds"],
    },
  };
}

function renderBoundsField(
  spec: NodeSpec,
  config: Record<string, unknown> = {},
) {
  const onConfigChange = vi.fn();
  const data = createWorkflowNodeData(spec);
  data.config = { ...data.config, ...config };
  data.onConfigChange = onConfigChange;

  const { container, root } = renderNode("wms-layer", data);

  const inputs = BOUNDS_INPUT_LABELS.map((label) => {
    const input = container.querySelector<HTMLInputElement>(
      `input[aria-label="${label}"]`,
    );
    expect(input).not.toBeNull();
    return input!;
  });
  const committedValues = () =>
    onConfigChange.mock.calls.map((call) => call[2]);
  return { container, inputs, onConfigChange, committedValues, root };
}

describe("WorkflowNode fixed numeric tuple fields", () => {
  it("renders coordinate inputs and emits a complete number array", () => {
    const { inputs, onConfigChange, root } = renderBoundsField(boundsSpec());

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

    ["19.75", "49.97", "19.82", "50.03"].forEach((value, index) => {
      React.act(() => enterInputValue(inputs[index]!, value));
    });

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

  it("keeps partial entry local until all four values are valid", () => {
    const { inputs, onConfigChange, root } = renderBoundsField(boundsSpec());

    ["19.75", "49.97", "19.82"].forEach((value, index) => {
      React.act(() => enterInputValue(inputs[index]!, value));
    });

    expect(onConfigChange).not.toHaveBeenCalled();
    expect(inputs.map((input) => input.value)).toEqual([
      "19.75",
      "49.97",
      "19.82",
      "",
    ]);

    React.act(() => enterInputValue(inputs[3]!, "50.03"));

    expect(onConfigChange).toHaveBeenCalledTimes(1);
    expect(onConfigChange).toHaveBeenCalledWith(
      "wms-layer",
      "bounds",
      [19.75, 49.97, 19.82, 50.03],
    );
    React.act(() => root.unmount());
  });

  it("keeps the last valid tuple while a value is temporarily invalid", () => {
    const { inputs, committedValues, root } = renderBoundsField(boundsSpec(), {
      bounds: [19.75, 49.97, 19.82, 50.03],
    });

    React.act(() => enterInputValue(inputs[0]!, ""));
    expect(committedValues()).toEqual([]);

    React.act(() => enterInputValue(inputs[0]!, "181"));
    expect(committedValues()).toEqual([]);

    React.act(() => enterInputValue(inputs[0]!, "19.5"));
    expect(committedValues()).toEqual([[19.5, 49.97, 19.82, 50.03]]);
    React.act(() => root.unmount());
  });

  it("corrects one value of a complete tuple without erasing the others", () => {
    const { inputs, committedValues, root } = renderBoundsField(boundsSpec(), {
      bounds: [19.75, 49.97, 19.82, 50.03],
    });

    React.act(() => enterInputValue(inputs[3]!, "51.5"));

    expect(committedValues()).toEqual([[19.75, 49.97, 19.82, 51.5]]);
    React.act(() => root.unmount());
  });

  it("never commits an empty value for a required tuple", () => {
    const { inputs, onConfigChange, root } = renderBoundsField(boundsSpec(), {
      bounds: [19.75, 49.97, 19.82, 50.03],
    });

    inputs.forEach((input) => {
      React.act(() => enterInputValue(input, ""));
    });

    expect(onConfigChange).not.toHaveBeenCalled();
    expect(inputs.map((input) => input.value)).toEqual(["", "", "", ""]);
    React.act(() => root.unmount());
  });

  it("commits an intentional all-empty clear for a nullable tuple", () => {
    const { inputs, committedValues, root } = renderBoundsField(
      nullableBoundsSpec(),
      { bounds: [19.75, 49.97, 19.82, 50.03] },
    );

    React.act(() => enterInputValue(inputs[0]!, ""));
    expect(committedValues()).toEqual([]);

    [1, 2, 3].forEach((index) => {
      React.act(() => enterInputValue(inputs[index]!, ""));
    });

    expect(committedValues()).toEqual([null]);
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

    const { container, root } = renderNode("fuzzy-match", data);

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
      container
        .querySelector<HTMLButtonElement>(
          'button[aria-label="Add Right Alias Columns item"]',
        )
        ?.click();
    });
    expect(onConfigChange).toHaveBeenLastCalledWith(
      "fuzzy-match",
      "right_alias_columns",
      ["candidate_current_name_normalized", ""],
    );

    React.act(() => {
      container
        .querySelector<HTMLButtonElement>(
          'button[aria-label="Remove Right Alias Columns item 1"]',
        )
        ?.click();
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
    // 2 shelves of paired fields, then a boolean shelf. The API key lives in
    // the header's credentials popover, not on the board.
    expect(board?.style.gridTemplateRows).toBe("repeat(3, minmax(50px, auto))");
    expect(brickAreas(container)).toEqual([
      "1 / span 3 | 1 / span 1",
      "4 / span 3 | 1 / span 1",
      "1 / span 3 | 2 / span 1",
      "4 / span 3 | 2 / span 1",
      // Compact 3×1 checkbox grows into the leftover half of its shelf.
      "1 / span 6 | 3 / span 1",
    ]);
    // Schema order is preserved across the board.
    const labels = [
      ...container.querySelectorAll<HTMLElement>(
        '[data-testid="config-brick"]',
      ),
    ].map((brick) => brick.textContent?.slice(0, 5));
    expect(labels).toEqual(["Base ", "Model", "Tempe", "Timeo", "Stric"]);
    expect(board?.querySelector('input[type="password"]')).toBeNull();

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
    expect(board?.style.gridTemplateRows).toBe("repeat(3, minmax(50px, auto))");
    expect(brickAreas(container)).toEqual([
      "1 / span 3 | 1 / span 1",
      "4 / span 3 | 1 / span 1",
      "1 / span 3 | 2 / span 1",
      "4 / span 3 | 2 / span 1",
      "1 / span 6 | 3 / span 1",
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
    ]);

    React.act(() => root.unmount());
  });

  it("grows the body past a saved height that cannot hold the bricks", () => {
    const data = createWorkflowNodeData(multilineNoteSpec());
    data.config = { body: "first line\nsecond line" };
    data.layout = { bodyHeight: 50 };
    const { container, root } = renderNode("note", data);

    const board = container.querySelector<HTMLElement>(
      '[data-testid="config-board"]',
    );
    // One requested cell cannot hold a two-cell textarea brick.
    expect(board?.style.gridTemplateRows).toBe("repeat(2, minmax(50px, auto))");
    expect(brickAreas(container)).toEqual(["1 / span 6 | 1 / span 2"]);
    expect(container.querySelector("textarea")?.value).toBe(
      "first line\nsecond line",
    );

    React.act(() => root.unmount());
  });

  it("hands a taller saved body to the growable brick", () => {
    const data = createWorkflowNodeData(multilineNoteSpec());
    data.config = {};
    data.layout = { bodyHeight: 300 };
    const { container, root } = renderNode("note", data);

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
      configFieldLabelIsRedundant("Strict mode", [
        fieldBrick("Strict", "boolean"),
      ]),
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
    // The card menu names the step, not the operator build behind it.
    expect(selected.container.textContent).not.toContain("@1");
    React.act(() => selected.root.unmount());
  });

  it("reports execution status without a badge row", () => {
    const data = createWorkflowNodeData(chatCompletionSpec());
    data.execution = {
      status: "failed",
      error: "Provider rejected the request",
    };
    const { container, root } = renderNode("chat", data);

    const status = container.querySelector(
      '[aria-label="OpenAI-compatible Chat Completion failed"]',
    );
    expect(status).not.toBeNull();
    expect(status?.textContent).toBe("Failed");

    React.act(() => root.unmount());
  });
});

describe("WorkflowNode multiline fields", () => {
  it("exposes a textarea field resize grip and hides corner resize by default", () => {
    gridSettingsMocks.allowWorkflowCornerResize = false;
    const data = createWorkflowNodeData(multilineNoteSpec());
    data.config = { body: "Note body" };

    const { container, root } = renderNode("note", data);

    expect(
      container.querySelector('[data-testid="textarea-body-resize"]'),
    ).not.toBeNull();
    expect(container.querySelector('[data-testid="corner-resize"]')).toBeNull();

    React.act(() => root.unmount());
  });

  it("shows the workflow corner resize handle when the lab flag is on", () => {
    gridSettingsMocks.allowWorkflowCornerResize = true;
    const data = createWorkflowNodeData(multilineNoteSpec());
    data.config = { body: "Note body" };

    const { container, root } = renderNode("note", data);

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
    const { container, root } = renderNode("text-pipe", data);

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

describe("WorkflowNode execution progress", () => {
  it("integrates the selected execution appendix without remeasuring every event", () => {
    const data = createWorkflowNodeData(boundsSpec());
    const { container, root } = renderNode("module-1", data);
    xyflowMocks.updateNodeInternals.mockClear();

    const materializedRun: NonNullable<typeof data.run> = {
      node_id: "module-1",
      status: "succeeded",
      // A result is addressed by the instance that produced it and the
      // fingerprint it stored under.
      result_fingerprint: "fp-module-1",
      created_at: "2026-08-01T00:00:00Z",
      error: null,
      outputs: [
        {
          port: "result",
          kind: "single",
          value: {
            artifact_id: "artifact-1",
            artifact_type: "json.object",
            schema_version: 1,
          },
          artifacts: [
            {
              // A stored result hands the canvas a reference, not a summary:
              // content_type and text were never in it, and nothing here read
              // them.
              artifact_id: "artifact-1",
              artifact_type: "json.object",
              schema_version: 1,
              content_hash: "sha256:artifact-1",
            },
          ],
        },
      ],
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
    ).toEqual(["Events 4", "Result 0"]);
    expect(appendix?.textContent).toContain("1 earlier update omitted");
    expect(appendix?.textContent).toContain("branch-a › inner-1 · items 3 › 2");
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
    expect(appendix?.textContent).toContain("Completed · branch-c · item 2");
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
      "2 / 5 · 3 left · <script>Preparing the payload</script> · branch-a › inner-1 · items 3 › 2",
      "Uploading · branch-b · item 1",
      "Queued · Remote WMS map layer",
    ]);
    expect(earlierEvents?.querySelector("script")).toBeNull();
    React.act(() => root.unmount());
  });
});

describe("WorkflowNode artifact drop rows", () => {
  it("publishes the live identity of a plain input port row", () => {
    const data = createWorkflowNodeData(textPipeSpec());
    const { container, root } = renderNode("text-pipe", data);

    const row = container.querySelector<HTMLElement>(
      '[data-input-port-name="text"]',
    );
    expect(row?.dataset.inputNodeId).toBe("text-pipe");

    React.act(() => root.unmount());
  });

  it("publishes plug identity on plug rows instead of the port header", () => {
    const data = createWorkflowNodeData(instancePlugsSpec());
    const { container, root } = renderNode("interleave", data);

    expect(
      container.querySelector('[data-input-port-name="headings"]'),
    ).toBeNull();
    const plugRow = container.querySelector<HTMLElement>(
      '[data-input-plug-id][data-input-node-id="interleave"]',
    );
    expect(plugRow?.dataset.inputPlugPort).toBe("headings");

    React.act(() => root.unmount());
  });
});

/**
 * The type menus the ports' balls open, each as its choices (the mocked menu
 * renders inline, so every ball's menu is present).
 */
function typeMenus(container: HTMLElement) {
  return [...container.querySelectorAll('[role="menu"]')].map((menu) => [
    ...menu.querySelectorAll("button"),
  ]);
}

describe("WorkflowNode artifact type binding", () => {
  it("binds an artifact type variable from the node card instead of connect only", () => {
    const onBindArtifactTypeBinding = vi.fn();
    const data = {
      ...createWorkflowNodeData(sequenceCollectSpec()),
      onBindArtifactTypeBinding,
      bindableArtifactTypes: [
        { id: "file.jpeg", schema_version: 1 },
        { id: "file.png", schema_version: 1 },
        { id: "image.raster", schema_version: 1 },
      ],
    };
    const { container } = renderNode("collect", data);

    // The ball opens the choices; its ring is dashed while the type is open.
    const [options = []] = typeMenus(container);
    expect(options.map((option) => option.textContent)).toEqual([
      "Any type",
      "file.jpeg@1",
      "file.png@1",
      "image.raster@1",
    ]);
    // Each choice still reveals the full type identity it binds.
    expect(options[1]?.getAttribute("title")).toBe("file.jpeg@1");
    expect(container.querySelector('[data-port-open="true"]')).not.toBeNull();

    React.act(() => {
      options[1]?.click();
    });

    expect(onBindArtifactTypeBinding).toHaveBeenCalledWith("collect", "T", {
      id: "file.jpeg",
      schema_version: 1,
    });
  });

  it("puts each generic port's type choice on that port", () => {
    const generic = (name: string, variable: string) =>
      artifactPortFixture({
        name,
        title: name,
        direction: "input",
        artifact_type: null,
        artifact_type_variable: variable,
      });
    const spec = {
      ...sequenceCollectSpec(),
      operator_id: "test.pair",
      title: "Pair",
      inputs: [generic("left", "L"), generic("right", "R")],
    };
    const data = {
      ...createWorkflowNodeData(spec),
      onBindArtifactTypeBinding: vi.fn(),
      bindableArtifactTypes: [{ id: "file.png", schema_version: 1 }],
    };
    const { container } = renderNode("pair", data);

    // One choice per port, and no separate type row on the node.
    // Each port's ball opens its own choice.
    expect(typeMenus(container)).toHaveLength(2);
    expect(
      container.querySelector('[aria-label="Generic artifact types"]'),
    ).toBeNull();
  });

  it("keeps the static type row when no binding options are supplied", () => {
    const { container } = renderNode(
      "collect",
      createWorkflowNodeData(sequenceCollectSpec()),
    );

    // With nothing to choose from, the ball opens no menu but still reads
    // as open.
    expect(typeMenus(container)).toHaveLength(0);
    expect(container.querySelector('[data-port-open="true"]')).not.toBeNull();
  });
});

function schemaBuilderSpec(): NodeSpec {
  return nodeSpecFixture({
    operator_id: "schema.builder",
    plugin_slug: "builtin",
    title: "Build object",
    description: "Builds an object schema from named fields.",
    config_schema: { type: "object", properties: {} },
    inputs: [
      artifactPortFixture({
        name: "schemas",
        title: "Schemas",
        direction: "input",
        artifact_type: null,
        artifact_type_variable: "T",
        instance_plugs: true,
        variadic: true,
        required: false,
      }),
    ],
  });
}

const PARCELS_FIELD = {
  id: "field-parcels",
  name: "parcels",
  kind: "string",
  required: false,
  description: "",
};

describe("WorkflowNode schema builder toggles", () => {
  function renderBuilder(
    config: Record<string, unknown>,
    onConfigChange = vi.fn(),
  ) {
    const data = createWorkflowNodeData(schemaBuilderSpec());
    data.config = config;
    data.onConfigChange = onConfigChange;
    return { ...renderNode("schema-builder", data), onConfigChange };
  }

  it("writes the extra-fields toggle through config and reports state only through aria-pressed", () => {
    const { container, root, onConfigChange } = renderBuilder({
      additional_properties: false,
      fields: [PARCELS_FIELD],
    });

    const toggle = container.querySelector<HTMLButtonElement>(
      'button[title="Allow properties not declared below"]',
    );
    expect(toggle?.textContent).toBe("Extra fields");
    expect(toggle?.getAttribute("aria-pressed")).toBe("false");

    React.act(() => toggle?.click());
    expect(onConfigChange).toHaveBeenCalledWith(
      "schema-builder",
      "additional_properties",
      true,
    );

    React.act(() => root.unmount());
  });

  it("reads a saved extra-fields setting back as a pressed toggle", () => {
    const { container, root } = renderBuilder({
      additional_properties: true,
      fields: [PARCELS_FIELD],
    });

    expect(
      container
        .querySelector<HTMLButtonElement>(
          'button[title="Allow properties not declared below"]',
        )
        ?.getAttribute("aria-pressed"),
    ).toBe("true");

    React.act(() => root.unmount());
  });

  it("flips a field's required flag and its accessible name together", () => {
    const onSchemaBuilderFieldsChange = vi.fn();
    const data = createWorkflowNodeData(schemaBuilderSpec());
    data.config = { fields: [PARCELS_FIELD] };
    data.onSchemaBuilderFieldsChange = onSchemaBuilderFieldsChange;
    const { container, root } = renderNode("schema-builder", data);

    const required = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Mark field 1 required"]',
    );
    expect(required?.textContent).toBe("Required");
    expect(required?.getAttribute("aria-pressed")).toBe("false");

    React.act(() => required?.click());
    const [nodeId, nextFields] =
      onSchemaBuilderFieldsChange.mock.calls[0] ?? [];
    expect(nodeId).toBe("schema-builder");
    expect(nextFields).toEqual([{ ...PARCELS_FIELD, required: true }]);

    React.act(() => root.unmount());
  });

  it("reorders and removes a field through named row actions", () => {
    const onSchemaBuilderFieldsChange = vi.fn();
    const data = createWorkflowNodeData(schemaBuilderSpec());
    data.config = {
      fields: [
        PARCELS_FIELD,
        { ...PARCELS_FIELD, id: "field-area", name: "area" },
      ],
    };
    data.onSchemaBuilderFieldsChange = onSchemaBuilderFieldsChange;
    const { container, root } = renderNode("schema-builder", data);

    const removeField = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Remove field 2"]',
    );
    expect(removeField).not.toBeNull();
    React.act(() => removeField?.click());
    expect(onSchemaBuilderFieldsChange.mock.calls.at(-1)?.[1]).toEqual([
      PARCELS_FIELD,
    ]);

    onSchemaBuilderFieldsChange.mockClear();
    const moveUp = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Move field 2 up"]',
    );
    expect(moveUp?.disabled).toBe(false);
    React.act(() => moveUp?.click());
    expect(
      (onSchemaBuilderFieldsChange.mock.calls.at(-1)?.[1] as unknown[]).map(
        (field) => (field as { name: string }).name,
      ),
    ).toEqual(["area", "parcels"]);

    const firstMoveUp = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Move field 1 up"]',
    );
    expect(firstMoveUp?.disabled).toBe(true);

    React.act(() => root.unmount());
  });

  it("changes a field kind in its type select and its items in the item select", () => {
    const onSchemaBuilderFieldsChange = vi.fn();
    const data = createWorkflowNodeData(schemaBuilderSpec());
    const sequenceField = {
      id: "field-area",
      name: "area",
      kind: "sequence",
      item_kind: "string",
      required: false,
      description: "",
    };
    data.config = { fields: [PARCELS_FIELD, sequenceField] };
    data.onSchemaBuilderFieldsChange = onSchemaBuilderFieldsChange;
    const { container, root } = renderNode("schema-builder", data);

    const kind = container.querySelector<HTMLSelectElement>(
      'select[aria-label="Field 1 type"]',
    );
    expect([...(kind?.options ?? [])].map((option) => option.value)).toEqual([
      "string",
      "integer",
      "number",
      "boolean",
      "sequence",
      "schema",
    ]);
    React.act(() => {
      kind!.value = "integer";
      kind!.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(onSchemaBuilderFieldsChange.mock.calls.at(-1)?.[1]).toEqual([
      { ...PARCELS_FIELD, kind: "integer" },
      sequenceField,
    ]);

    // The sequence row's own item picker writes the same callback.
    const itemKind = container.querySelector<HTMLSelectElement>(
      'select[aria-label="Field 2 item type"]',
    );
    React.act(() => {
      itemKind!.value = "number";
      itemKind!.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(onSchemaBuilderFieldsChange.mock.calls.at(-1)?.[1]).toEqual([
      PARCELS_FIELD,
      { ...sequenceField, item_kind: "number" },
    ]);

    React.act(() => root.unmount());
  });

  it("wires the schema metadata labels to their inputs", () => {
    const { container, root } = renderBuilder({
      title: "Response",
      fields: [PARCELS_FIELD],
    });

    const title = container.querySelector<HTMLInputElement>(
      'input[placeholder="Response"]',
    );
    expect(title?.labels?.[0]?.textContent).toBe("Schema title · optional");
    expect(title?.value).toBe("Response");
    const description = container.querySelector<HTMLInputElement>(
      'input[placeholder="What this response contains"]',
    );
    expect(description?.labels?.[0]?.textContent).toBe(
      "Description · optional",
    );

    React.act(() => root.unmount());
  });

  it("announces an empty field list as a status message", () => {
    const { container, root } = renderBuilder({ fields: [] });

    const empty = container.querySelector(
      '[aria-label="Schema fields"] [role="status"]',
    );
    expect(empty?.textContent?.trim()).toBe(
      "Add a field to define this object schema.",
    );

    React.act(() => root.unmount());
  });
});

describe("WorkflowNode shared field wiring", () => {
  it("keeps every config brick's label wired to its control", () => {
    const data = createWorkflowNodeData(chatCompletionSpec());
    const { container, root } = renderNode("chat", data);

    const fieldNames = [
      ...container.querySelectorAll<HTMLInputElement>(
        'input:not([aria-hidden="true"])',
      ),
    ].map(
      (input) =>
        input.labels?.[0]?.textContent ?? input.getAttribute("aria-label"),
    );
    // The API key is not a config brick: it waits behind the header trigger.
    expect(fieldNames).toEqual([
      "Base Url",
      "Model",
      "Temperature",
      "Timeout Ms",
    ]);
    // A boolean is the kit's checkbox, named by its label through
    // aria-labelledby because a role="checkbox" is not labelable.
    const strict = container.querySelector<HTMLElement>('[role="checkbox"]');
    expect(
      strict?.parentElement?.querySelector(
        `[id="${strict.getAttribute("aria-labelledby")}"]`,
      )?.textContent,
    ).toBe("Strict");
    expect(strict?.getAttribute("aria-checked")).toBe("false");
    expect(strict?.closest(".nodrag.nopan.nowheel")).not.toBeNull();

    React.act(() => root.unmount());
  });

  it("draws an enum as a native select its label still names", () => {
    const spec: NodeSpec = {
      ...chatCompletionSpec(),
      config_schema: {
        type: "object",
        properties: {
          mode: { type: "string", title: "Mode", enum: ["fast", "safe"] },
        },
        required: ["mode"],
      },
    };
    const data = createWorkflowNodeData(spec);
    data.config = { mode: "fast" };
    const { container, root } = renderNode("chat", data);

    const select = container.querySelector<HTMLSelectElement>("select");
    // <Select> is a native select inside <Field>'s frame, so the control still
    // carries no aria-label of its own and `labels` resolves through the field.
    expect(select?.hasAttribute("aria-label")).toBe(false);
    expect(select?.labels?.[0]?.textContent).toContain("Mode");
    expect([...(select?.options ?? [])].map((option) => option.value)).toEqual([
      "fast",
      "safe",
    ]);
    expect(select?.value).toBe("fast");

    React.act(() => root.unmount());
  });

  it("puts the required flag on the label that <Field> draws", () => {
    const data = createWorkflowNodeData(multilineNoteSpec());
    data.config = { body: "Note body" };
    const { container, root } = renderNode("note", data);

    const textarea = container.querySelector("textarea");
    expect(textarea?.labels?.[0]?.textContent).toBe("Body*");

    React.act(() => root.unmount());
  });

  it("shows a tuple's incomplete entry as an alert beside the inputs", () => {
    const { inputs, container, root } = renderBoundsField(boundsSpec());

    React.act(() => enterInputValue(inputs[0]!, "19.75"));

    const alert = [...container.querySelectorAll<HTMLElement>("[role]")].find(
      (element) => element.textContent?.startsWith("Enter all 4 values"),
    );
    expect(alert?.getAttribute("role")).toBe("alert");

    React.act(() => root.unmount());
  });
});

describe("WorkflowNode credentials popover", () => {
  const TRIGGER = 'button[aria-label^="Credentials for OpenAI-compatible"]';

  function renderCredentials(
    statuses: WorkflowNodeData["secretStatuses"] = {
      api_key: { state: "configured" },
    },
    readiness: Record<string, boolean> = { api_key: true },
  ) {
    const onApplyNodeSecret = vi.fn().mockResolvedValue(true);
    const onRemoveNodeSecret = vi.fn().mockResolvedValue(true);
    const data = createWorkflowNodeData(chatCompletionSpec());
    data.secretInputReadiness = readiness;
    data.secretStatuses = statuses;
    data.onApplyNodeSecret = onApplyNodeSecret;
    data.onRemoveNodeSecret = onRemoveNodeSecret;
    const rendered = renderNode("chat", data);
    const trigger = () =>
      rendered.container.querySelector<HTMLButtonElement>(TRIGGER);
    const open = () => React.act(() => trigger()?.click());
    return {
      ...rendered,
      trigger,
      open,
      onApplyNodeSecret,
      onRemoveNodeSecret,
    };
  }

  it("keeps keys off the config board and behind a header trigger", () => {
    const { container, root, trigger, open } = renderCredentials();
    const board = container.querySelector('[data-testid="config-board"]');
    expect(board?.textContent).not.toContain("API key");
    expect(container.querySelector('input[type="password"]')).toBeNull();
    expect(container.querySelector('[role="dialog"]')).toBeNull();

    // A configured, ready key is a quiet icon in the header.
    expect(trigger()?.closest("header")).not.toBeNull();
    expect(trigger()?.getAttribute("aria-label")).toBe(
      "Credentials for OpenAI-compatible Chat Completion",
    );
    expect(trigger()?.getAttribute("title")).toBe("Credentials configured");
    expect(trigger()?.textContent).toBe("");

    open();
    const popup = container.querySelector('[role="dialog"]');
    expect(popup?.classList.contains("nodrag")).toBe(true);
    expect(popup?.classList.contains("nopan")).toBe(true);
    expect(popup?.classList.contains("nowheel")).toBe(true);
    expect(popup?.textContent).toContain("Credentials");
    expect(popup?.textContent).toContain("API key · Key saved");

    React.act(() => root.unmount());
  });

  it.each([
    [{ api_key: { state: "unconfigured" as const } }, true, "Key needed"],
    [{ api_key: { state: "configured" as const } }, false, "Key out of date"],
    [{ api_key: { state: "error" as const } }, true, "Key error"],
    [{ api_key: { state: "loading" as const } }, true, "Credentials"],
  ])(
    "names a key that needs attention on the card (%o)",
    (statuses, ready, label) => {
      const { root, trigger } = renderCredentials(statuses, { api_key: ready });
      expect(trigger()?.textContent).toBe(label);
      expect(trigger()?.getAttribute("aria-label")).toBe(
        `Credentials for OpenAI-compatible Chat Completion: ${label}`,
      );
      React.act(() => root.unmount());
    },
  );

  it("reports open and close so the shell keeps the ports revealed", () => {
    const data = createWorkflowNodeData(chatCompletionSpec());
    data.secretInputReadiness = { api_key: true };
    data.secretStatuses = { api_key: { state: "configured" } };
    const onOpenChange = vi.fn();
    const container = document.createElement("div");
    const root = createRoot(container);
    React.act(() =>
      root.render(
        <CredentialsPopover
          id="chat"
          data={data}
          onOpenChange={onOpenChange}
        />,
      ),
    );
    const trigger = container.querySelector<HTMLButtonElement>(TRIGGER);
    React.act(() => trigger?.click());
    expect(onOpenChange).toHaveBeenLastCalledWith(true);
    expect(trigger?.getAttribute("aria-expanded")).toBe("true");
    React.act(() => trigger?.click());
    expect(onOpenChange).toHaveBeenLastCalledWith(false);
    expect(container.querySelector('[role="dialog"]')).toBeNull();
    React.act(() => root.unmount());
  });

  it("applies a typed key through the form's submit button", async () => {
    const { container, root, onApplyNodeSecret, open } = renderCredentials();
    open();
    React.act(() =>
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent === "Replace")
        ?.click(),
    );
    const input = container.querySelector<HTMLInputElement>(
      'input[aria-label="API key"]',
    );
    // jsdom only runs a form's submit while the form is attached to a document.
    document.body.append(container);
    const form = input?.closest("form");
    const apply = form?.querySelector<HTMLButtonElement>(
      'button[type="submit"]',
    );

    expect(input?.type).toBe("password");
    expect(input?.getAttribute("placeholder")).toBe("Replace key");
    expect(input?.disabled).toBe(false);
    expect(apply?.textContent).toBe("Apply");
    // Nothing typed yet: the write stays gated the same way it was.
    expect(apply?.disabled).toBe(true);

    React.act(() => enterInputValue(input!, "sk-test"));
    expect(apply?.disabled).toBe(false);

    React.act(() => apply?.click());
    await vi.waitFor(() =>
      expect(onApplyNodeSecret).toHaveBeenCalledWith(
        "chat",
        "api_key",
        "sk-test",
      ),
    );
    // A replaced key folds back to the saved summary.
    await vi.waitFor(() =>
      expect(container.querySelector('input[aria-label="API key"]')).toBeNull(),
    );
    expect(container.textContent).toContain("API key · Key saved");

    React.act(() => root.unmount());
    container.remove();
  });

  it("asks for a key when none is saved yet", () => {
    const { container, root, open } = renderCredentials({
      api_key: { state: "unconfigured" },
    });
    open();
    const input = container.querySelector<HTMLInputElement>(
      'input[aria-label="API key"]',
    );
    expect(input?.getAttribute("placeholder")).toBe("Paste key");
    expect(container.querySelector('[role="dialog"]')?.textContent).toContain(
      "No key",
    );
    React.act(() => root.unmount());
  });

  it("removes a saved key from the popover", async () => {
    const { container, root, onRemoveNodeSecret, open } = renderCredentials();
    open();
    React.act(() =>
      [...container.querySelectorAll("button")]
        .find((button) => button.textContent === "Replace")
        ?.click(),
    );
    const form = container.querySelector("form");

    expect(form?.textContent).toContain("Key saved");
    const remove = [
      ...(form?.querySelectorAll<HTMLButtonElement>("button") ?? []),
    ].find((button) => button.textContent === "Remove");
    expect(remove?.disabled).toBe(false);

    React.act(() => remove?.click());
    await vi.waitFor(() =>
      expect(onRemoveNodeSecret).toHaveBeenCalledWith("chat", "api_key"),
    );

    React.act(() => root.unmount());
  });

  it("gives a key-only node its trigger without an empty config body", () => {
    const spec: NodeSpec = {
      ...chatCompletionSpec(),
      config_schema: { type: "object", properties: {} },
    };
    const data = createWorkflowNodeData(spec);
    data.secretStatuses = { api_key: { state: "unconfigured" } };
    const { container, root } = renderNode("chat", data);

    expect(container.querySelector(TRIGGER)?.textContent).toBe("Key needed");
    expect(container.querySelector('[data-testid="config-board"]')).toBeNull();
    React.act(() => root.unmount());
  });
});

describe("WorkflowNode plug row controls", () => {
  it("keeps every plug control reachable by its accessible name", () => {
    const data = createWorkflowNodeData(instancePlugsSpec());
    const { container, root } = renderNode("interleave", data);

    const names = [
      ...container.querySelectorAll<HTMLButtonElement>(
        '[data-input-plug-port="headings"] button',
      ),
      ...container.querySelectorAll<HTMLButtonElement>("button"),
    ].map(
      (button) =>
        button.getAttribute("aria-label") ?? button.textContent?.trim() ?? "",
    );
    expect(names).toEqual(
      expect.arrayContaining([
        "Inspect Headings type",
        "Drag to reorder Headings input 1",
        "Move Headings input 1 up",
        "Move Headings input 1 down",
        "Remove Headings input 1",
        "Add another",
      ]),
    );
    // The first row cannot move further up, the only row cannot move down.
    expect(
      container.querySelector<HTMLButtonElement>(
        'button[aria-label="Move Headings input 1 up"]',
      )?.disabled,
    ).toBe(true);

    React.act(() => root.unmount());
  });
});

describe("WorkflowNode optional connection switch", () => {
  afterEach(() => {
    xyflowMocks.edges = [];
    xyflowMocks.nodes = [];
  });

  it("writes a wire's enabled flag through the edge and keeps the row still", () => {
    const data = createWorkflowNodeData(textPipeSpec());
    const port = data.spec.inputs.find((input) => input.name === "text");
    if (!port) throw new Error("expected the text input port");
    const onUpdate = vi.fn();
    // A connection left disabled against a required input is the one the row
    // offers to switch back on.
    xyflowMocks.edges = [
      {
        id: "edge-text",
        source: "upstream",
        target: "text-pipe",
        targetHandle: encodeHandleId(portMetaForPort(port)),
        data: { enabled: false, collectionMode: "direct", onUpdate },
      },
    ];

    const { container, root } = renderNode("text-pipe", data);

    const toggle = container.querySelector<HTMLElement>(
      '[role="switch"][aria-label="text is not used"]',
    );
    expect(toggle?.getAttribute("aria-checked")).toBe("false");
    expect(toggle?.closest("div")?.textContent).toContain("· not used");
    // React Flow walks up from the pointer target, so the kit switch's own root
    // has to hold the classes.
    const switchRoot = toggle?.closest("label");
    expect(switchRoot?.className).toContain("nodrag");
    expect(switchRoot?.className).toContain("nowheel");

    React.act(() => {
      toggle?.dispatchEvent(new PointerEvent("click", { bubbles: true }));
    });
    expect(onUpdate).toHaveBeenCalledWith("edge-text", { enabled: true });

    React.act(() => root.unmount());
  });
});

describe("WorkflowNode config validation", () => {
  it("shows a persisted value that is no longer in the enum and an inline error", () => {
    const spec: NodeSpec = {
      ...multilineNoteSpec(),
      title: "Mode selector",
      config_schema: {
        type: "object",
        properties: { mode: { type: "string", enum: ["fast", "safe"] } },
        required: ["mode"],
      },
    };
    const data = createWorkflowNodeData(spec);
    data.config = { mode: "legacy" };
    const { container, root } = renderNode("mode", data);

    expect(container.textContent).toContain(
      "Choose one of the allowed values.",
    );
    expect(container.querySelector('option[value="legacy"]')?.textContent).toBe(
      "Saved value: legacy",
    );
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
    React.act(() => root.unmount());
  });

  it("shows requiredness errors for an incomplete autosaved config", () => {
    const data = createWorkflowNodeData(multilineNoteSpec());
    data.config = {};
    const { container, root } = renderNode("note-required", data);

    expect(container.textContent).toContain("This field is required.");
    expect(container.querySelector('[role="alert"]')).not.toBeNull();
    React.act(() => root.unmount());
  });
});

describe("workflow node execution actions", () => {
  it("runs the node and reveals materialized output", () => {
    const data = createWorkflowNodeData(textPipeSpec());
    data.onRunNode = vi.fn();
    data.onRevealNodeOutput = vi.fn();
    const artifact = {
      artifact_id: "out",
      artifact_type: "text.plain",
      schema_version: 1,
      content_hash: null,
    };
    data.run = {
      node_id: "pipe",
      status: "succeeded",
      error: null,
      result_fingerprint: "fp",
      created_at: null,
      outputs: [
        {
          port: "text",
          kind: "single",
          value: artifact,
          artifacts: [artifact],
        },
      ],
    };
    const { container, root } = renderNode("pipe", data, true);
    const run = container.querySelector<HTMLButtonElement>(
      '[aria-label="Run Text pipe"]',
    );
    const reveal = container.querySelector<HTMLButtonElement>(
      '[aria-label="Show output of Text pipe"]',
    );
    expect(run).not.toBeNull();
    expect(reveal).not.toBeNull();
    React.act(() => {
      run?.click();
      reveal?.click();
    });
    expect(data.onRunNode).toHaveBeenCalledWith("pipe");
    expect(data.onRevealNodeOutput).toHaveBeenCalledWith("pipe");
    React.act(() => root.unmount());
  });
  it("hides reveal when a following card exists and run while busy", () => {
    const data = createWorkflowNodeData(textPipeSpec());
    data.onRunNode = vi.fn();
    data.onRevealNodeOutput = vi.fn();
    data.hasFollowingOutputCard = true;
    data.execution = { status: "running" };
    const { container, root } = renderNode("pipe", data, true);
    expect(container.querySelector('[aria-label="Run Text pipe"]')).toBeNull();
    expect(
      container.querySelector('[aria-label="Show output of Text pipe"]'),
    ).toBeNull();
    React.act(() => root.unmount());
  });
});

function ocrReaderContract() {
  return { id: "ocr.reader", version: 1 } as const;
}

function reductoProviderSpec(): NodeSpec {
  return nodeSpecFixture({
    operator_id: "reducto.ocr.provider",
    plugin_slug: "reducto",
    title: "Reducto",
    description: "OCR provider",
    secret_inputs: [
      {
        name: "api_key",
        title: "API key",
        description: null,
        config_dependencies: [],
      },
    ],
    outputs: [
      servicePortFixture({
        name: "reader",
        title: "Reader",
        direction: "output",
        service_contracts: [ocrReaderContract()],
        features: ["blocks"],
      }),
    ],
  });
}

function ocrNodeSpec(): NodeSpec {
  return nodeSpecFixture({
    operator_id: "ocr.read",
    plugin_slug: "workbench",
    title: "OCR",
    description: "Read a document",
    inputs: [
      artifactPortFixture({
        name: "document",
        title: "Scan or PDF",
        direction: "input",
        artifact_type: { id: "image.raster", schema_version: 1 },
        also_accepts: [{ id: "document.pdf", schema_version: 1 }],
      }),
      servicePortFixture({
        name: "reader",
        title: "Reader",
        direction: "input",
        service_contracts: [ocrReaderContract()],
      }),
    ],
    outputs: [
      artifactPortFixture({
        name: "markdown",
        title: "Transcription",
        direction: "output",
        artifact_type: { id: "text.markdown", schema_version: 1 },
      }),
      artifactPortFixture({
        name: "blocks",
        title: "Text blocks",
        direction: "output",
        artifact_type: { id: "table.data", schema_version: 1 },
        required: false,
      }),
      artifactPortFixture({
        name: "regions",
        title: "Boxes on the page",
        direction: "output",
        artifact_type: { id: "image.regions", schema_version: 1 },
        required: false,
      }),
    ],
  });
}

function drawBoxesSpec(): NodeSpec {
  return nodeSpecFixture({
    operator_id: "test.draw_boxes",
    title: "Draw boxes",
    inputs: [
      artifactPortFixture({
        name: "regions",
        title: "Boxes",
        direction: "input",
        artifact_type: { id: "image.regions", schema_version: 1 },
      }),
    ],
    outputs: [
      artifactPortFixture({
        name: "text",
        title: "Text",
        direction: "output",
      }),
    ],
  });
}

describe("WorkflowNode provider-dependent OCR outputs", () => {
  function workflowNode(id: string, data: WorkflowNodeData): CanvasNode {
    return { id, data, type: WORKFLOW_NODE_TYPE, position: { x: 0, y: 0 } };
  }

  afterEach(() => {
    xyflowMocks.edges = [];
    xyflowMocks.nodes = [];
  });

  it("mutes an OCR output the connected provider does not produce", () => {
    const ocrData = createWorkflowNodeData(ocrNodeSpec());
    const providerData = createWorkflowNodeData(reductoProviderSpec());
    const readerInput = ocrData.spec.inputs.find(
      (port) => port.name === "reader",
    );
    const readerOutput = providerData.spec.outputs.find(
      (port) => port.name === "reader",
    );
    if (!readerInput || !readerOutput) {
      throw new Error("expected reader ports");
    }

    xyflowMocks.nodes = [
      workflowNode("provider", providerData),
      workflowNode("ocr", ocrData),
    ];
    xyflowMocks.edges = [
      {
        id: "provider-to-ocr",
        source: "provider",
        target: "ocr",
        sourceHandle: encodeHandleId(portMetaForPort(readerOutput)),
        targetHandle: encodeHandleId(portMetaForPort(readerInput)),
        data: { enabled: true, collectionMode: "direct" },
      },
    ];

    const { container, root } = renderNode("ocr", ocrData);

    const muted = container.querySelector('[data-unsupported-output="true"]');
    expect(muted?.textContent).toContain("Not produced by Reducto");
    expect(
      container.querySelector('[aria-label*="Boxes on the page"]')?.textContent,
    ).toContain("Not produced by Reducto");
    expect(container.textContent).toContain("Transcription");
    expect(container.textContent).toContain("Text blocks");

    React.act(() => root.unmount());
  });

  it("shows the downstream blocking reason when a muted OCR output is wired", () => {
    const ocrData = createWorkflowNodeData(ocrNodeSpec());
    const providerData = createWorkflowNodeData(reductoProviderSpec());
    const drawData = createWorkflowNodeData(drawBoxesSpec());
    const readerInput = ocrData.spec.inputs.find(
      (port) => port.name === "reader",
    );
    const readerOutput = providerData.spec.outputs.find(
      (port) => port.name === "reader",
    );
    const regionsOutput = ocrData.spec.outputs.find(
      (port) => port.name === "regions",
    );
    const boxesInput = drawData.spec.inputs.find(
      (port) => port.name === "regions",
    );
    if (!readerInput || !readerOutput || !regionsOutput || !boxesInput) {
      throw new Error("expected OCR and boxes ports");
    }

    xyflowMocks.nodes = [
      workflowNode("provider", providerData),
      workflowNode("ocr", ocrData),
      workflowNode("draw", drawData),
    ];
    xyflowMocks.edges = [
      {
        id: "provider-to-ocr",
        source: "provider",
        target: "ocr",
        sourceHandle: encodeHandleId(portMetaForPort(readerOutput)),
        targetHandle: encodeHandleId(portMetaForPort(readerInput)),
        data: { enabled: true, collectionMode: "direct" },
      },
      {
        id: "ocr-to-draw",
        source: "ocr",
        target: "draw",
        sourceHandle: encodeHandleId(portMetaForPort(regionsOutput)),
        targetHandle: encodeHandleId(portMetaForPort(boxesInput)),
        data: { enabled: true, collectionMode: "direct" },
      },
    ];

    const { container, root } = renderNode("draw", drawData);

    expect(container.textContent).toContain(
      "Boxes are not produced by Reducto",
    );
    expect(container.textContent).not.toContain(
      "No result saved for this step yet",
    );

    React.act(() => root.unmount());
  });

  it("keeps a provider card without a result appendix", () => {
    const data = createWorkflowNodeData(reductoProviderSpec());
    data.onRunNode = vi.fn();
    const { container, root } = renderNode("provider", data, true);

    expect(
      container.querySelector('[aria-label="Reducto execution appendix"]'),
    ).toBeNull();
    expect(container.querySelector('[aria-label="Run Reducto"]')).toBeNull();
    expect(container.textContent).not.toContain(
      "No result saved for this step yet",
    );

    React.act(() => root.unmount());
  });
});

describe("WorkflowNode dynamic config fields", () => {
  function rerender(
    root: ReturnType<typeof createRoot>,
    id: string,
    data: WorkflowNodeData,
  ) {
    React.act(() =>
      root.render(
        <WorkflowNodeCard
          {...({
            id,
            data,
            selected: false,
            dragging: false,
          } as React.ComponentProps<typeof WorkflowNodeCard>)}
        />,
      ),
    );
  }

  function dynamicSpec(
    configSchema: Record<string, unknown>,
    extra: Partial<NodeSpec> = {},
  ): NodeSpec {
    return nodeSpecFixture({
      operator_id: "test.dynamic",
      title: "Dynamic step",
      config_schema: configSchema,
      ...extra,
    });
  }

  function brickFields(container: HTMLElement): (string | undefined)[] {
    return [
      ...container.querySelectorAll<HTMLElement>(
        '[data-testid="config-brick"]',
      ),
    ].map((brick) => brick.dataset.configField);
  }

  function radio(scope: ParentNode, name: string): HTMLElement | undefined {
    return [...scope.querySelectorAll<HTMLElement>('[role="radio"]')].find(
      (element) => element.textContent === name,
    );
  }

  function group(scope: ParentNode, name: string): HTMLElement | null {
    return scope.querySelector<HTMLElement>(
      `[role="group"][aria-label="${name}"]`,
    );
  }

  function pressEnter(input: HTMLInputElement) {
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
    );
  }

  const AREA = { field: "scope", eq: "Selected area" };
  const DETECT_TEXT_SCHEMA = {
    type: "object",
    properties: {
      scope: {
        type: "string",
        title: "Scan area",
        enum: ["Selected area", "Whole TIFF page"],
        default: "Selected area",
        "x-grafy-widget": "segmented",
      },
      col: {
        type: "integer",
        title: "Left pixel",
        minimum: 0,
        default: 0,
        "x-grafy-visible-when": AREA,
      },
      row: {
        type: "integer",
        title: "Top pixel",
        minimum: 0,
        default: 0,
        "x-grafy-visible-when": AREA,
      },
      width: {
        type: "integer",
        title: "Width in pixels",
        exclusiveMinimum: 0,
        default: 512,
        "x-grafy-visible-when": AREA,
      },
      height: {
        type: "integer",
        title: "Height in pixels",
        exclusiveMinimum: 0,
        default: 512,
        "x-grafy-visible-when": AREA,
      },
    },
  };

  it("hides area fields for a whole page and brings back their saved values", () => {
    const onConfigChange = vi.fn();
    const data = createWorkflowNodeData(dynamicSpec(DETECT_TEXT_SCHEMA));
    data.config = {
      scope: "Selected area",
      col: 40,
      row: 8,
      width: 256,
      height: 128,
    };
    data.onConfigChange = onConfigChange;
    const { container, root } = renderNode("detect", data);
    expect(brickFields(container)).toEqual([
      "scope",
      "col",
      "row",
      "width",
      "height",
    ]);

    React.act(() => radio(container, "Whole TIFF page")?.click());
    expect(onConfigChange).toHaveBeenCalledWith(
      "detect",
      "scope",
      "Whole TIFF page",
    );

    xyflowMocks.updateNodeInternals.mockClear();
    const whole = {
      ...data,
      config: { ...data.config, scope: "Whole TIFF page" },
    };
    rerender(root, "detect", whole);
    expect(brickFields(container)).toEqual(["scope"]);
    // Hiding a field never writes it away.
    expect(onConfigChange).toHaveBeenCalledTimes(1);
    expect(whole.config).toMatchObject({ col: 40, row: 8, width: 256 });
    // The board changed height under the handles, so they are re-measured.
    expect(xyflowMocks.updateNodeInternals).toHaveBeenCalledWith("detect");

    rerender(root, "detect", data);
    const left = container.querySelector<HTMLInputElement>(
      '[data-config-field="col"] input',
    );
    expect(left?.value).toBe("40");

    React.act(() => root.unmount());
  });

  const CHAT_SCHEMA = {
    type: "object",
    properties: {
      model: { type: "string", title: "Model", default: "gpt-test" },
      max_completion_tokens: {
        type: "integer",
        title: "Max Completion Tokens",
        minimum: 1,
        maximum: 1_000_000,
        default: 2048,
        "x-grafy-advanced": true,
      },
      json_schema_name: {
        type: "string",
        title: "Schema name",
        default: "response",
        "x-grafy-visible-when": { portConnected: "json_schema" },
      },
      strict: {
        type: "boolean",
        title: "Strict",
        default: true,
        "x-grafy-widget": "switch",
        "x-grafy-visible-when": { portConnected: "json_schema" },
      },
    },
  };

  it("shows schema options only while the schema input has a wire", () => {
    const data = createWorkflowNodeData(dynamicSpec(CHAT_SCHEMA));
    data.connectedInputPorts = {
      json_schema: { connected: false, artifactTypeKey: null },
    };
    const { container, root } = renderNode("chat", data);
    expect(brickFields(container)).toEqual(["model"]);

    rerender(root, "chat", {
      ...data,
      connectedInputPorts: {
        json_schema: { connected: true, artifactTypeKey: "json.schema@1" },
      },
    });
    expect(brickFields(container)).toEqual([
      "model",
      "json_schema_name",
      "strict",
    ]);
    const strict = container.querySelector('[role="switch"]');
    // An unset boolean draws its schema default.
    expect(strict?.getAttribute("aria-checked")).toBe("true");

    React.act(() => root.unmount());
  });

  it("reads a wire from the canvas edges when Workbench has not derived one", () => {
    const port = artifactPortFixture({
      name: "json_schema",
      title: "JSON schema",
      direction: "input",
    });
    const data = createWorkflowNodeData(
      dynamicSpec(CHAT_SCHEMA, { inputs: [port] }),
    );
    xyflowMocks.edges = [
      {
        id: "schema-to-chat",
        source: "schema",
        target: "chat",
        targetHandle: encodeHandleId(portMetaForPort(port)),
        data: { enabled: true, collectionMode: "direct" },
      } as WorkflowEdge,
    ];
    const { container, root } = renderNode("chat", data);
    expect(brickFields(container)).toContain("strict");
    React.act(() => root.unmount());
    xyflowMocks.edges = [];
  });

  it("keeps token limits behind options until they leave the default", () => {
    const data = createWorkflowNodeData(dynamicSpec(CHAT_SCHEMA));
    const { container, root } = renderNode("chat", data);
    const options = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.startsWith("Options"),
    );
    expect(options?.textContent).toBe("Options (1)");
    React.act(() => options?.click());
    const tokens = container.querySelector<HTMLInputElement>(
      '[data-config-field="max_completion_tokens"] input',
    );
    expect(tokens?.value).toBe("2048");
    expect(tokens?.min).toBe("1");
    expect(tokens?.max).toBe("1000000");
    React.act(() => root.unmount());

    const tuned = createWorkflowNodeData(dynamicSpec(CHAT_SCHEMA));
    tuned.config = { ...tuned.config, max_completion_tokens: 4096 };
    const rendered = renderNode("chat", tuned);
    expect(brickFields(rendered.container)).toContain("max_completion_tokens");
    React.act(() => rendered.root.unmount());
  });

  it("chooses delimiter or sheet from the file type on the wire", () => {
    const schema = {
      type: "object",
      properties: {
        delimiter: {
          type: "string",
          title: "Delimiter",
          default: ",",
          "x-grafy-visible-when": {
            portArtifactType: { port: "file", notIn: ["file.xlsx@1"] },
          },
        },
        sheet: {
          type: "string",
          title: "Sheet",
          "x-grafy-visible-when": {
            portArtifactType: { port: "file", notIn: ["file.csv@1"] },
          },
        },
      },
    };
    const wired = (artifactTypeKey: string | null) => ({
      file: { connected: artifactTypeKey !== null, artifactTypeKey },
    });
    const data = createWorkflowNodeData(dynamicSpec(schema));
    data.connectedInputPorts = wired(null);
    const { container, root } = renderNode("table", data);
    expect(brickFields(container)).toEqual(["delimiter", "sheet"]);

    rerender(root, "table", {
      ...data,
      connectedInputPorts: wired("file.csv@1"),
    });
    expect(brickFields(container)).toEqual(["delimiter"]);
    rerender(root, "table", {
      ...data,
      connectedInputPorts: wired("file.xlsx@1"),
    });
    expect(brickFields(container)).toEqual(["sheet"]);

    React.act(() => root.unmount());
  });

  it("reveals a hidden or advanced field that holds an invalid value", () => {
    const schema = {
      type: "object",
      properties: {
        mode: { type: "string", enum: ["auto", "custom"], default: "auto" },
        area: {
          type: "integer",
          title: "Area",
          maximum: 3,
          "x-grafy-visible-when": { field: "mode", eq: "custom" },
        },
        retries: {
          type: "integer",
          title: "Retries",
          minimum: 0,
          default: 2,
          "x-grafy-advanced": true,
        },
      },
    };
    const data = createWorkflowNodeData(dynamicSpec(schema));
    data.config = { mode: "auto", area: 9, retries: -1 };
    const { container, root } = renderNode("fix", data);

    expect(brickFields(container)).toEqual(["mode", "area", "retries"]);
    expect(
      container.querySelector('[data-config-field="area"]')?.textContent,
    ).toContain("Must be at most 3.");
    expect(
      container.querySelector('[data-config-field="retries"]')?.textContent,
    ).toContain("Must be at least 0.");
    expect(container.textContent).not.toContain("Options (");
    React.act(() => root.unmount());
  });

  it("prints enum labels while writing the wire value", () => {
    const onConfigChange = vi.fn();
    const data = createWorkflowNodeData(
      dynamicSpec({
        type: "object",
        properties: {
          resampling: {
            type: "string",
            title: "Resampling",
            enum: ["linear", "nearest"],
            default: "linear",
            "x-grafy-enum-labels": { linear: "Smooth", nearest: "Crisp" },
          },
        },
      }),
    );
    data.onConfigChange = onConfigChange;
    const { container, root } = renderNode("enum", data);
    const select = container.querySelector<HTMLSelectElement>("select");
    expect(
      [...(select?.options ?? [])].map((option) => [
        option.value,
        option.textContent,
      ]),
    ).toEqual([
      ["linear", "Smooth"],
      ["nearest", "Crisp"],
    ]);
    React.act(() => {
      select!.value = "nearest";
      select!.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(onConfigChange).toHaveBeenCalledWith(
      "enum",
      "resampling",
      "nearest",
    );
    React.act(() => root.unmount());
  });

  it("shows a zero-based index the way a person counts", () => {
    const onConfigChange = vi.fn();
    const data = createWorkflowNodeData(
      dynamicSpec({
        type: "object",
        properties: {
          page_index: {
            type: "integer",
            title: "Page",
            minimum: 0,
            maximum: 9,
            default: 0,
            "x-grafy-widget": "one-based-integer",
          },
        },
      }),
    );
    data.onConfigChange = onConfigChange;
    const { container, root } = renderNode("page", data);
    const input = container.querySelector<HTMLInputElement>(
      '[data-config-field="page_index"] input',
    );
    expect(input?.value).toBe("1");
    expect(input?.min).toBe("1");
    expect(input?.max).toBe("10");
    React.act(() => enterInputValue(input!, "3"));
    expect(onConfigChange).toHaveBeenLastCalledWith("page", "page_index", 2);
    React.act(() => root.unmount());
  });

  it("folds named groups behind a header that counts their fields", () => {
    const schema = {
      type: "object",
      properties: {
        batch_size: { type: "integer", title: "Batch size", default: 8 },
        url: {
          type: "string",
          title: "Url",
          default: "http://label-studio",
          "x-grafy-group": "Label Studio",
        },
        project: {
          type: "string",
          title: "Project",
          default: "OCR",
          "x-grafy-group": "Label Studio",
        },
        bucket: {
          type: "string",
          title: "Bucket",
          default: "grafy-ocr",
          "x-grafy-group": "Storage",
        },
      },
    };
    const data = createWorkflowNodeData(dynamicSpec(schema));
    const { container, root } = renderNode("studio", data);
    const sections = [
      ...container.querySelectorAll<HTMLElement>("[data-config-group]"),
    ];
    expect(sections.map((section) => section.dataset.configGroup)).toEqual([
      "Label Studio",
      "Storage",
    ]);
    // Schema order: the ungrouped field first, then each group's fields.
    expect(brickFields(container)).toEqual([
      "batch_size",
      "url",
      "project",
      "bucket",
    ]);
    const storageToggle = sections[1]?.querySelector("button");
    expect(storageToggle?.getAttribute("aria-expanded")).toBe("true");
    expect(storageToggle?.textContent).toBe("Storage1");

    xyflowMocks.updateNodeInternals.mockClear();
    React.act(() => storageToggle?.click());
    expect(storageToggle?.getAttribute("aria-expanded")).toBe("false");
    expect(brickFields(container)).toEqual(["batch_size", "url", "project"]);
    expect(xyflowMocks.updateNodeInternals).toHaveBeenCalledWith("studio");
    React.act(() => root.unmount());
  });

  it("edits a raster style as one folded settings group", () => {
    const onConfigChange = vi.fn();
    const data = createWorkflowNodeData(
      dynamicSpec(RASTER_LAYER_CONFIG_SCHEMA, { title: "Raster layer" }),
    );
    data.config = { ...data.config, title: "Scan" };
    data.onConfigChange = onConfigChange;
    const { container, root } = renderNode("raster", data);

    expect(brickFields(container)).toEqual([
      "title",
      "visible",
      "opacity",
      "style",
    ]);
    const style = group(container, "style");
    const toggle = style?.querySelector<HTMLButtonElement>("[aria-expanded]");
    // Seven controls a layer rarely needs stay folded until asked for.
    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    expect(radio(style!, "Crisp")).toBeUndefined();

    xyflowMocks.updateNodeInternals.mockClear();
    React.act(() => toggle?.click());
    expect(toggle?.getAttribute("aria-expanded")).toBe("true");
    expect(xyflowMocks.updateNodeInternals).toHaveBeenCalledWith("raster");
    expect(
      [...style!.querySelectorAll("[data-config-field]")].map(
        (cell) => (cell as HTMLElement).dataset.configField,
      ),
    ).toEqual([
      "opacity",
      "brightness_min",
      "brightness_max",
      "contrast",
      "saturation",
      "hue",
      "resampling",
    ]);

    React.act(() => radio(style!, "Crisp")?.click());
    expect(onConfigChange).toHaveBeenLastCalledWith("raster", "style", {
      kind: "raster",
      opacity: 1,
      brightness_min: 0,
      brightness_max: 1,
      contrast: 0,
      saturation: 0,
      hue: 0,
      resampling: "nearest",
    });
    React.act(() => root.unmount());
  });

  function vectorLayer(config: Record<string, unknown> = {}) {
    const onConfigChange = vi.fn();
    const data = createWorkflowNodeData(
      dynamicSpec(VECTOR_LAYER_CONFIG_SCHEMA, { title: "Vector layer" }),
    );
    data.config = { ...data.config, title: "Parcels", ...config };
    data.onConfigChange = onConfigChange;
    return { data, onConfigChange, ...renderNode("vector", data) };
  }

  it("draws the vector style union through the generic body", () => {
    const { container, root, onConfigChange } = vectorLayer();
    expect(brickFields(container)).toEqual([
      "title",
      "visible",
      "opacity",
      "style",
    ]);
    const style = group(container, "Style")!;
    expect(radio(style, "Uniform")?.getAttribute("aria-checked")).toBe("true");
    expect(
      [...style.querySelectorAll('[role="group"]')].map((section) =>
        section.getAttribute("aria-label"),
      ),
    ).toEqual(["fill", "line", "outline", "point", "label"]);

    // Fill unfolds to its own switch, colour, and opacity.
    const fill = group(style, "fill")!;
    React.act(() =>
      fill.querySelector<HTMLButtonElement>("[aria-expanded]")?.click(),
    );
    const color = fill.querySelector<HTMLInputElement>('input[type="color"]');
    expect(color?.value).toBe("#2563eb");
    React.act(() => enterInputValue(color!, "#ff0000"));
    expect(onConfigChange).toHaveBeenLastCalledWith(
      "vector",
      "style",
      expect.objectContaining({
        kind: "vector",
        fill: { enabled: true, color: "#ff0000", opacity: 0.45 },
        label: null,
      }),
    );

    // An optional label is a switch that writes a whole label style.
    const useLabel = group(style, "label")?.querySelector<HTMLElement>(
      '[role="switch"]',
    );
    expect(useLabel?.getAttribute("aria-label")).toBe("Use label");
    React.act(() => useLabel?.click());
    expect(onConfigChange).toHaveBeenLastCalledWith(
      "vector",
      "style",
      expect.objectContaining({
        label: {
          property: "name",
          color: "#111827",
          size: 12,
          halo_color: "#ffffff",
          halo_width: 1,
        },
      }),
    );

    React.act(() => radio(style, "Categories")?.click());
    expect(onConfigChange).toHaveBeenLastCalledWith("vector", "style", {
      kind: "categorized_points",
      category_property: "type",
      categories: [
        {
          id: expect.stringMatching(/^item_1_[0-9a-f]{8}$/),
          title: "Category 1",
          values: [1],
          point: {
            enabled: true,
            color: "#dc2626",
            opacity: 1,
            radius: 5,
            stroke_color: "#ffffff",
            stroke_width: 1,
          },
          min_zoom: 0,
          max_zoom: 22,
        },
      ],
      label: null,
    });
    React.act(() => root.unmount());
  });

  const CATEGORIZED = {
    kind: "categorized_points",
    category_property: "type",
    categories: [
      {
        id: "category_1",
        title: "Wells",
        values: [1],
        point: {
          enabled: true,
          color: "#dc2626",
          opacity: 1,
          radius: 5,
          stroke_color: "#ffffff",
          stroke_width: 1,
        },
        min_zoom: 0,
        max_zoom: 22,
      },
    ],
    label: null,
  };

  it("edits categories as item cards with typed value lists", () => {
    const { container, root, onConfigChange } = vectorLayer({
      style: CATEGORIZED,
    });
    const style = group(container, "Style")!;
    expect(radio(style, "Categories")?.getAttribute("aria-checked")).toBe(
      "true",
    );
    const card = group(style, "Category 1")!;
    const title = card.querySelector<HTMLInputElement>(
      'input[aria-label="Category 1 title"]',
    );
    expect(title?.value).toBe("Wells");
    // The only category cannot be removed: the schema needs at least one.
    expect(
      card.querySelector<HTMLButtonElement>(
        'button[aria-label="Remove category 1"]',
      )?.disabled,
    ).toBe(true);

    const valueType = card.querySelector<HTMLSelectElement>(
      'select[aria-label="Values value type"]',
    );
    expect(valueType?.value).toBe("number");
    const values = card.querySelector<HTMLInputElement>(
      '[data-config-field="values"] input:not([aria-hidden="true"])',
    );
    expect(values?.value).toBe("1");
    React.act(() => enterInputValue(values!, "1, 2"));
    React.act(() => pressEnter(values!));
    expect(onConfigChange).toHaveBeenLastCalledWith(
      "vector",
      "style",
      expect.objectContaining({
        categories: [
          expect.objectContaining({ id: "category_1", values: [1, 2] }),
        ],
      }),
    );

    React.act(() => enterInputValue(values!, "one"));
    React.act(() => pressEnter(values!));
    expect(card.querySelector('[role="alert"]')?.textContent).toBe(
      "Enter at least one comma-separated value of the selected type.",
    );

    const add = [...style.querySelectorAll("button")].find(
      (button) => button.textContent === "Add category",
    );
    React.act(() => add?.click());
    const next = onConfigChange.mock.lastCall?.[2] as typeof CATEGORIZED;
    expect(next.categories).toHaveLength(2);
    expect(next.categories[0]).toEqual(CATEGORIZED.categories[0]);
    expect(next.categories[1]).toMatchObject({
      id: expect.stringMatching(/^item_2_[0-9a-f]{8}$/),
      title: "Category 2",
      values: [1],
    });
    React.act(() => root.unmount());
  });
});
