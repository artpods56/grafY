// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ArtifactRef,
  PlacedLibraryItem,
  TablePage,
  TableSchema,
} from "@/lib/api";
import type { ArtifactCardValue } from "../artifact-card";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INPUT_HANDLE,
  type ArtifactViewerNodeData,
} from "../artifact-viewer";
import { WORKFLOW_NODE_TYPE } from "../types";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const libraryMocks = vi.hoisted(() => ({
  items: [] as PlacedLibraryItem[],
  value: undefined as { text: string; truncated: boolean } | undefined,
}));
const flowMocks = vi.hoisted(() => ({
  edges: [] as unknown[],
  nodes: new Map<string, unknown>(),
}));
const tableMocks = vi.hoisted(
  (): {
    page: TablePage | undefined;
    schema: TableSchema | undefined;
    error: Error | undefined;
    retry: ReturnType<typeof vi.fn>;
  } => ({
    page: undefined,
    schema: undefined,
    error: undefined,
    retry: vi.fn(),
  }),
);

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@xyflow/react", () => ({
  useNodeId: () => null,
  useUpdateNodeInternals: () => vi.fn(),
  useViewport: () => ({ zoom: 1 }),
  useEdges: () => flowMocks.edges,
  useNodesData: (nodeId: string) => flowMocks.nodes.get(nodeId) ?? null,
  useConnection: (selector: (state: { inProgress: boolean }) => unknown) =>
    selector({ inProgress: false }),
  useNodeConnections: () => [],
  useStore: (selector: (state: unknown) => unknown) =>
    selector({ edges: [], nodeLookup: new Map() }),
  Handle: (props: {
    id?: string;
    "aria-label"?: string;
    "aria-disabled"?: boolean;
    type: string;
    style?: React.CSSProperties;
  }) => (
    <span
      data-testid="card-port"
      data-handle-id={props.id}
      data-handle-type={props.type}
      aria-disabled={props["aria-disabled"]}
      style={props.style}
      aria-label={props["aria-label"]}
    />
  ),
  Position: { Left: "left", Right: "right" },
}));

const registryMocks = vi.hoisted(() => ({
  artifactTypes: [] as {
    key: { id: string; schema_version: number };
    title: string;
  }[],
}));

vi.mock("swr", () => ({
  default: (key: readonly unknown[] | string | null) => {
    if (key === null) return { data: undefined };
    if (typeof key === "string") {
      return { data: { artifact_types: registryMocks.artifactTypes } };
    }
    if (key[0] === "table-artifact-schema") {
      return {
        data: tableMocks.schema,
        error: tableMocks.error,
        mutate: tableMocks.retry,
      };
    }
    if (key[0] === "table-artifact-page") return { data: tableMocks.page };
    return key[0] === "artifact-card-text"
      ? { data: libraryMocks.value }
      : { data: { folders: [], items: libraryMocks.items } };
  },
}));

const workspaceMocks = vi.hoisted(() => ({
  value: {
    workspace: {
      id: "workspace-1",
      slug: "team",
      name: "Local",
      kind: "personal" as const,
      role: "owner",
      capabilities: [],
    },
    workspaces: [],
    refreshWorkspaces: async () => undefined,
  },
}));

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  useWorkspaceContext: () => workspaceMocks.value,
  useOptionalWorkspaceContext: () => workspaceMocks.value,
}));

vi.mock("@base-ui/react/menu", () => ({
  Menu: {
    Root: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Trigger: ({
      children,
      ...props
    }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
      <button type="button" {...props}>
        {children}
      </button>
    ),
    Portal: ({ children }: { children: React.ReactNode }) => <>{children}</>,
    Positioner: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    Popup: ({ children }: { children: React.ReactNode }) => (
      <div role="dialog">{children}</div>
    ),
    Item: ({
      children,
      ...props
    }: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
      <button type="button" {...props}>
        {children}
      </button>
    ),
    Group: ({ children }: { children: React.ReactNode }) => (
      <div role="group">{children}</div>
    ),
    GroupLabel: ({ children }: { children: React.ReactNode }) => (
      <div data-testid="menu-info">{children}</div>
    ),
    Separator: () => <hr />,
  },
}));

import { ArtifactCardBody } from "./ArtifactCardBody";

function libraryItem(artifactId: string, name: string): PlacedLibraryItem {
  return {
    name,
    folder_id: null,
    provenance: {
      source: "upload",
      saved_at: "2026-01-01T00:00:00Z",
      original_filename: name,
    },
    artifact: {
      artifact_id: artifactId,
      artifact_type: "file.jpeg",
      schema_version: 1,
      content_type: "image/jpeg",
      byte_size: 2_516_586,
    },
  };
}

function single(artifactId: string): ArtifactRef {
  return {
    artifact_id: artifactId,
    artifact_type: "file.jpeg",
    schema_version: 1,
  };
}

function sequence(artifactIds: readonly string[]): ArtifactCardValue {
  return {
    artifact_type: "file.jpeg",
    schema_version: 1,
    item_refs: artifactIds.map(single),
    ordered: true,
    index_key: "order_index",
    sequence_id: "22222222-2222-4222-8222-222222222222",
  };
}

const mountedRoots: ReturnType<typeof createRoot>[] = [];

function mount(
  value: ArtifactCardValue,
  data: Partial<ArtifactViewerNodeData> = {},
  selected = false,
) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const _ = mountedRoots.push(root);
  const nodeData: ArtifactViewerNodeData = {
    layout: { width: 264 },
    mode: null,
    ...data,
  };
  React.act(() => {
    root.render(
      <ArtifactCardBody
        id="artifact-viewer-1"
        data={nodeData}
        value={value}
        selected={selected}
      />,
    );
  });
  return { container, root };
}

afterEach(() => {
  React.act(() => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.length = 0;
  document.body.replaceChildren();
  libraryMocks.items = [];
  libraryMocks.value = undefined;
  tableMocks.page = undefined;
  tableMocks.schema = undefined;
  tableMocks.error = undefined;
  const _ = tableMocks.retry.mockClear();
  registryMocks.artifactTypes = [];
  flowMocks.edges = [];
  flowMocks.nodes = new Map();
});

describe("artifact on the canvas", () => {
  beforeEach(() => {
    libraryMocks.items = [libraryItem("a1", "boat.jpg")];
  });

  const table: ArtifactRef = {
    artifact_id: "table-1",
    artifact_type: "table.data",
    schema_version: 1,
  };

  function loadTable() {
    libraryMocks.items = [
      {
        ...libraryItem(table.artifact_id, "Survey results"),
        artifact: { ...table, content_type: "application/json" },
      },
    ];
    tableMocks.schema = {
      columns: [
        { id: "name", title: "Result", value_type: "text" },
        { id: "count", title: "Result", value_type: "integer" },
        { id: "active", title: "Active", value_type: "boolean" },
      ],
      total_rows: 80,
    };
    tableMocks.page = {
      ...tableMocks.schema,
      rows: [
        {
          name: { display: "<strong>River</strong>", truncated: false },
          count: { display: 42, truncated: false },
          active: { display: false, truncated: false },
        },
        {
          name: { display: null, truncated: false },
          count: { display: 0, truncated: false },
          active: { display: true, truncated: false },
        },
      ],
      offset: 0,
      limit: 50,
      column_offset: 0,
      column_limit: 25,
      total_columns: 3,
    };
  }

  it("renders table cells below the label with the same artifact rails", () => {
    loadTable();
    const { container } = mount(table, { layout: null });
    const body = container.querySelector<HTMLElement>(
      "[data-artifact-table-body]",
    );
    expect(
      container.querySelector("[data-artifact-head]")?.textContent,
    ).toContain("Survey results");
    expect(
      container.querySelector("[data-artifact-card-id]")?.getAttribute("style"),
    ).toContain("width: 600px");
    expect(body?.style.height).toBe("360px");
    expect(body?.querySelectorAll("thead th")).toHaveLength(4);
    expect(body?.querySelectorAll("tbody td")).toHaveLength(6);
    expect(body?.textContent).toContain("<strong>River</strong>");
    expect(body?.querySelector("strong")).toBeNull();
    expect(body?.textContent).toContain("42");
    expect(body?.textContent).toContain("false");
    expect(body?.textContent).toContain("—");
    expect(body?.querySelector('[aria-label="Next page"]')).not.toBeNull();
    expect(
      body?.querySelector('[aria-label="Choose visible table columns"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-artifact-rail="right"]'),
    ).not.toBeNull();
    expect(container.querySelector('[data-artifact-rail="left"]')).toBeNull();
    expect(container.querySelector("[data-artifact-file-body]")).toBeNull();
  });

  it("keeps the input rail on an output table and honors its saved dimensions", () => {
    loadTable();
    const { container } = mount(table, {
      mode: "artifact",
      layout: { width: 280, bodyHeight: 520 },
    });
    expect(
      container.querySelector('[data-artifact-rail="left"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-artifact-rail="right"]'),
    ).not.toBeNull();
    expect(
      container.querySelector<HTMLElement>("[data-artifact-table-body]")?.style
        .height,
    ).toBe("520px");
    expect(
      container.querySelector<HTMLElement>("[data-artifact-card-id]")?.style
        .width,
    ).toBe("280px");
    const narrow = mount(table, { layout: { width: 150, bodyHeight: 80 } });
    expect(
      narrow.container.querySelector<HTMLElement>("[data-artifact-card-id]")
        ?.style.width,
    ).toBe("260px");
    expect(
      narrow.container.querySelector<HTMLElement>("[data-artifact-table-body]")
        ?.style.height,
    ).toBe("160px");
  });

  it("keeps the table frame while its page loads and offers retry for an error", () => {
    libraryMocks.items = [];
    const loading = mount(table);
    expect(
      loading.container.querySelector('[role="status"]')?.textContent,
    ).toContain("Loading table page");
    expect(
      loading.container.querySelector("[data-artifact-table-body]"),
    ).not.toBeNull();
    tableMocks.error = new Error("Table unavailable");
    const failed = mount(table);
    expect(
      failed.container.querySelector('[role="alert"]')?.textContent,
    ).toContain("Could not load the table columns");
    const retry = Array.from(failed.container.querySelectorAll("button")).find(
      (button) => button.textContent === "Retry",
    );
    if (!retry) throw new Error("Table retry missing");
    React.act(() => retry.click());
    expect(tableMocks.retry).toHaveBeenCalledOnce();
  });

  it("renders an empty table with column headers and a clear empty state", () => {
    loadTable();
    if (!tableMocks.page) throw new Error("Table page missing");
    tableMocks.page = { ...tableMocks.page, rows: [], total_rows: 0 };
    const { container } = mount(table);
    expect(container.querySelector("thead")?.textContent).toContain("Active");
    expect(container.textContent).toContain("This table has no rows");
    expect(
      container.querySelector<HTMLButtonElement>('[aria-label="Next page"]')
        ?.disabled,
    ).toBe(true);
  });

  it("keeps CSV containers and unsupported table versions as file tiles", () => {
    loadTable();
    for (const ref of [
      { ...table, artifact_type: "file.csv" },
      { ...table, schema_version: 2 },
    ]) {
      const { container } = mount(ref);
      expect(container.querySelector("table")).toBeNull();
      expect(
        container.querySelector("[data-artifact-file-body]"),
      ).not.toBeNull();
    }
  });

  it("keeps filename and type above the image in both selection states", () => {
    const { container } = mount(single("a1"));
    const image = container.querySelector("img");
    const content = container.querySelector("[data-artifact-content]");
    const media = container.querySelector<HTMLElement>("[data-artifact-media]");

    expect(image?.getAttribute("src")).toContain("/artifacts/a1/content");
    expect(content?.querySelector("[data-artifact-media] img")).toBe(image);
    // Placed from the library, the card holds its own artifact: output only.
    expect(content?.querySelectorAll("[data-artifact-port-side]")).toHaveLength(
      1,
    );
    expect(content?.querySelector("[data-testid='port-rail']")).toBeNull();
    expect(
      container.querySelector("[data-artifact-image-header]"),
    ).not.toBeNull();
    expect(media?.querySelector("[data-artifact-image-header]")).toBeNull();
    expect(container.textContent).toContain("boat.jpg");
    expect(container.querySelector("ol")).toBeNull();
    expect(
      container.querySelector('[data-node-pickup-shadow="true"]'),
    ).toBeNull();
    expect(
      container.querySelector('[data-artifact-shadow-scope="image"]'),
    ).toBe(media);
    const picked = mount(single("a1"), {}, true);
    expect(picked.container.textContent).toContain("boat.jpg");
    expect(picked.container.textContent).toContain("file.jpeg");
    expect(
      picked.container.querySelector("[data-artifact-image-header]"),
    ).not.toBeNull();
    // Use a stable placeholder size until the image dimensions are known.
    expect(media?.style.height).toBe("198px");
  });

  it("shows readable content as text instead of a file tile", () => {
    libraryMocks.value = { text: '{"value":42}', truncated: false };
    const count = {
      artifact_id: "count-1",
      artifact_type: "scalar.integer",
      schema_version: 1,
    };
    flowMocks.nodes = new Map<string, unknown>([
      [
        "node-count",
        {
          id: "node-count",
          type: WORKFLOW_NODE_TYPE,
          data: {
            spec: {
              title: "Count",
              outputs: [{ name: "count", title: "count" }],
            },
            run: {
              status: "succeeded",
              outputs: [
                {
                  port: "count",
                  kind: "single",
                  value: count,
                  artifacts: [
                    {
                      ...count,
                      content_type: "application/json",
                      byte_size: 12,
                    },
                  ],
                },
              ],
            },
          },
        },
      ],
    ]);
    flowMocks.edges = [
      {
        id: "artifact-viewer-edge-1",
        type: ARTIFACT_VIEWER_EDGE_TYPE,
        source: "node-count",
        target: "artifact-viewer-1",
        targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
        data: { sourcePortName: "count" },
      },
    ];

    const { container } = mount(single("library-1"), { mode: "artifact" });

    expect(container.querySelector("[data-artifact-value]")?.textContent).toBe(
      '{\n  "value": 42\n}',
    );
    expect(container.querySelector("[data-artifact-file-body]")).toBeNull();
    // The wire names where the value comes from; the card has no name row.
    expect(container.querySelector("[data-artifact-head]")).toBeNull();
    libraryMocks.value = undefined;
  });

  it("bounds long text and scrolls it only once the card is selected", () => {
    // jsdom does no layout: say the text renders 400px tall in a 180px box.
    const scrollHeight = vi
      .spyOn(HTMLElement.prototype, "scrollHeight", "get")
      .mockReturnValue(400);
    const clientHeight = vi
      .spyOn(HTMLElement.prototype, "clientHeight", "get")
      .mockReturnValue(180);
    // One logical line that wraps: a newline count would call it short.
    libraryMocks.value = { text: "x".repeat(900), truncated: true };
    const long = {
      artifact_id: "long-1",
      artifact_type: "json.schema",
      schema_version: 1,
    };

    const idle = mount(long);
    const idleText = idle.container.querySelector<HTMLElement>(
      "[data-artifact-value] pre",
    );
    expect(idleText?.className).not.toContain("nowheel");
    expect(idleText?.style.maxHeight).toBe("180px");
    // At the top, only the bottom edge has more beyond it.
    expect(idleText?.style.maskImage).toBe(
      "linear-gradient(to bottom, black, black calc(100% - 32px), transparent)",
    );

    const picked = mount(long, {}, true);
    expect(
      picked.container.querySelector("[data-artifact-value] pre")?.className,
    ).toContain("nodrag nowheel");

    // Scrolled into the middle, both edges fade.
    const pickedText = picked.container.querySelector<HTMLElement>(
      "[data-artifact-value] pre",
    );
    const scrollTop = vi
      .spyOn(HTMLElement.prototype, "scrollTop", "get")
      .mockReturnValue(100);
    React.act(() => {
      pickedText?.dispatchEvent(new Event("scroll"));
    });
    expect(pickedText?.style.maskImage).toBe(
      "linear-gradient(to bottom, transparent, black 32px, black calc(100% - 32px), transparent)",
    );
    scrollTop.mockRestore();

    // The operator's height replaces the default cap.
    const tall = mount(long, { layout: { width: 264, bodyHeight: 900 } });
    expect(
      tall.container.querySelector<HTMLElement>("[data-artifact-value] pre")
        ?.style.maxHeight,
    ).toBe("900px");

    // Text that fits does not fade and does not take the wheel.
    scrollHeight.mockReturnValue(100);
    const short = mount(long, {}, true);
    expect(
      short.container.querySelector<HTMLElement>("[data-artifact-value] pre")
        ?.style.maskImage,
    ).toBe("");
    expect(
      short.container.querySelector("[data-artifact-value] pre")?.className,
    ).not.toContain("nowheel");
    scrollHeight.mockRestore();
    clientHeight.mockRestore();
    libraryMocks.value = undefined;
  });

  it("follows the output port wired into it", () => {
    flowMocks.nodes = new Map<string, unknown>([
      [
        "node-producer",
        {
          id: "node-producer",
          type: WORKFLOW_NODE_TYPE,
          data: {
            spec: {
              title: "Resize image",
              outputs: [{ name: "image", title: "Resized" }],
            },
            run: {
              status: "succeeded",
              outputs: [
                {
                  port: "image",
                  kind: "single",
                  value: {
                    artifact_id: "produced-9",
                    artifact_type: "file.png",
                    schema_version: 1,
                  },
                  artifacts: [
                    {
                      artifact_id: "produced-9",
                      artifact_type: "file.png",
                      schema_version: 1,
                    },
                  ],
                },
              ],
            },
          },
        },
      ],
    ]);
    flowMocks.edges = [
      {
        id: "artifact-viewer-edge-1",
        type: ARTIFACT_VIEWER_EDGE_TYPE,
        source: "node-producer",
        target: "artifact-viewer-1",
        targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
        data: { sourcePortName: "image" },
      },
    ];

    const { container } = mount(single("library-1"), {}, true);

    expect(container.querySelector("img")?.getAttribute("src")).toContain(
      "produced-9",
    );
    expect(container.textContent).toContain("Resize image → Resized");
    expect(
      container.querySelector(
        `[data-handle-id="${ARTIFACT_VIEWER_INPUT_HANDLE}"]`,
      ),
    ).not.toBeNull();
  });

  it("waits while the wired port has produced nothing", () => {
    flowMocks.nodes = new Map<string, unknown>([
      [
        "node-producer",
        {
          id: "node-producer",
          type: WORKFLOW_NODE_TYPE,
          data: {
            spec: {
              title: "Resize image",
              outputs: [{ name: "image", title: "Resized" }],
            },
            run: { status: "failed", outputs: [] },
          },
        },
      ],
    ]);
    flowMocks.edges = [
      {
        id: "artifact-viewer-edge-1",
        type: ARTIFACT_VIEWER_EDGE_TYPE,
        source: "node-producer",
        target: "artifact-viewer-1",
        targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
        data: { sourcePortName: "image" },
      },
    ];

    const { container } = mount(single("library-1"), {}, true);

    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("Waiting for Resized");
    expect(
      [...container.querySelectorAll("button")].find(
        (button) => button.textContent?.trim() === "Open original",
      )?.disabled,
    ).toBe(true);
    expect(
      container
        .querySelector('[aria-label^="Connect "]')
        ?.getAttribute("aria-disabled"),
    ).toBe("true");
  });

  it("exposes a graph output handle for the artifact", () => {
    const { container } = mount(single("a1"));
    const port = container.querySelector(
      '[aria-label="Connect file.jpeg@1 to a node input"]',
    );
    expect(port?.getAttribute("data-handle-id")).toBe("artifact-card-output");
    expect(port?.getAttribute("data-handle-type")).toBe("source");
    expect(port?.getAttribute("aria-disabled")).toBe("false");
  });

  it("shows a run of artifacts as a stack counted by item", () => {
    const { container } = mount(sequence(["a1", "a2", "a3"]), {}, true);

    const stack = container.querySelector('[aria-label="3 items in sequence"]');
    const thumbs = stack?.querySelectorAll("img");
    expect(container.textContent).toContain("3 items");
    expect(container.textContent).toContain("Sequence<file.jpeg@1>");
    expect(thumbs).toHaveLength(3);
    expect(thumbs![0]?.parentElement?.style.left).toBe("0px");
    expect(thumbs![2]?.parentElement?.style.left).toBe("24px");
    expect(stack?.closest("[data-artifact-content]")).not.toBeNull();
  });

  it("stacks file items the same way: first in front at the top-left", () => {
    const ref = (artifactId: string): ArtifactRef => ({
      artifact_id: artifactId,
      artifact_type: "file.csv",
      schema_version: 1,
    });
    const { container } = mount(
      {
        artifact_type: "file.csv",
        schema_version: 1,
        item_refs: [ref("f1"), ref("f2")],
        ordered: true,
        index_key: "order_index",
        sequence_id: "22222222-2222-4222-8222-222222222222",
      },
      {},
      true,
    );

    const stack = container.querySelector<HTMLElement>(
      '[aria-label="2 items in sequence"]',
    );
    const layers = [
      ...(stack?.querySelectorAll<HTMLElement>(
        '[data-artifact-shadow-scope="sequence-item"]',
      ) ?? []),
    ];
    expect(layers).toHaveLength(2);
    if (!layers[0] || !layers[1]) throw new Error("expected two stack layers");
    expect(layers[0].style.left).toBe("0px");
    expect(layers[0].style.top).toBe("0px");
    expect(layers[0].style.zIndex).toBe("2");
    expect(layers[1].style.left).toBe("12px");
    expect(layers[1].style.top).toBe("8px");
    // The back layer ends at the stack's bottom-right, where the output port is.
    expect(layers[1].style.width).toBe("calc(100% - 12px)");
    expect(stack?.style.height).toBe("113px");
  });

  it("takes an input only when pulled out of a node's output port", () => {
    const placed = mount(single("a1"), {}, true);
    expect(
      placed.container.querySelector('[data-artifact-port-side="input"]'),
    ).toBeNull();

    const pulled = mount(single("a1"), { mode: "artifact" }, true);
    expect(
      pulled.container.querySelector(
        `[data-artifact-port-side="input"] [data-handle-id="${ARTIFACT_VIEWER_INPUT_HANDLE}"]`,
      ),
    ).not.toBeNull();
  });

  it("hides ports and actions until the card is picked up", () => {
    const quiet = mount(single("a1"), { mode: "artifact" });
    expect(
      quiet.container.querySelector('[data-artifact-chrome="off"]'),
    ).not.toBeNull();
    expect(
      quiet.container.querySelectorAll('[data-port-out="false"]'),
    ).toHaveLength(2);

    React.act(() => {
      quiet.container
        .querySelector("[data-artifact-card-id]")
        ?.dispatchEvent(new Event("pointerover", { bubbles: true }));
    });
    expect(
      quiet.container.querySelector('[data-artifact-chrome="off"]'),
    ).not.toBeNull();
    expect(
      quiet.container.querySelectorAll('[data-port-out="false"]'),
    ).toHaveLength(2);

    const picked = mount(single("a1"), { mode: "artifact" }, true);
    expect(
      picked.container.querySelector('[data-artifact-chrome="on"]'),
    ).not.toBeNull();
    expect(
      picked.container.querySelectorAll('[data-port-out="true"]'),
    ).toHaveLength(2);
  });

  it("reorders the run it passes on", () => {
    libraryMocks.items = [
      libraryItem("a1", "boat.jpg"),
      libraryItem("a2", "coast.jpg"),
    ];
    const onRefsChange = vi.fn();
    const { container } = mount(sequence(["a1", "a2"]), { onRefsChange }, true);
    const reorder = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Reorder items"),
    );

    React.act(() => {
      reorder?.click();
    });
    const moveLater = container.querySelector<HTMLButtonElement>(
      '[aria-label="Move later in the order"]',
    );

    React.act(() => {
      moveLater?.click();
    });

    expect(onRefsChange).toHaveBeenCalledTimes(1);
    const committed = onRefsChange.mock.calls[0]![1];
    expect(
      "item_refs" in committed
        ? committed.item_refs.map(
            (ref: { artifact_id: string }) => ref.artifact_id,
          )
        : null,
    ).toEqual(["a2", "a1"]);
    expect("sequence_id" in committed ? committed.sequence_id : null).toBe(
      "22222222-2222-4222-8222-222222222222",
    );
  });

  it("paints a produced artifact the library never listed", () => {
    const { container } = mount(single("zz"), {}, true);

    expect(container.querySelector("img")?.getAttribute("src")).toContain(
      "/artifacts/zz/content",
    );
    expect(container.querySelector('[title="file.jpeg@1"]')).not.toBeNull();
  });

  it("names the card's type by catalog title, identity in the tooltip", () => {
    registryMocks.artifactTypes = [
      { key: { id: "file.jpeg", schema_version: 1 }, title: "Image file" },
    ];

    const { container } = mount(single("a1"), {}, true);

    expect(container.textContent).toContain("Image file");
    expect(container.querySelector('[title="file.jpeg@1"]')).not.toBeNull();
    expect(
      container.querySelector('[aria-label="Actions for Image file"]'),
    ).not.toBeNull();
  });

  it("shows the schema version only once it is past the first", () => {
    registryMocks.artifactTypes = [
      { key: { id: "file.jpeg", schema_version: 2 }, title: "Image file" },
    ];

    const { container } = mount(
      { artifact_id: "a2", artifact_type: "file.jpeg", schema_version: 2 },
      {},
      true,
    );

    expect(container.textContent).toContain("Image file · v2");
    expect(container.querySelector('[title="file.jpeg@2"]')).not.toBeNull();
  });

  it("shows a compact file row for a type it cannot preview", () => {
    const { container } = mount({
      artifact_id: "csv1",
      artifact_type: "file.csv",
      schema_version: 1,
    });

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[data-artifact-media]")).toBeNull();
    expect(
      container.querySelector(
        "[data-artifact-content] [data-artifact-port-side='output']",
      ),
    ).not.toBeNull();
    const label = container.querySelector("[data-artifact-label]");
    const body = container.querySelector("[data-artifact-file-body]");
    expect(label?.textContent).toContain("File");
    expect(label?.textContent).toContain("file.csv");
    // The plate states the format, never the contract.
    expect(body?.textContent).toBe("Table");
    expect(body?.textContent).not.toContain("file.csv@1");
    expect(container.querySelector('[title="file.csv@1"]')).not.toBeNull();
    expect(container.textContent).not.toContain("not in this library");
  });

  it("uses a PDF file glyph without a preview frame", () => {
    libraryMocks.items = [
      {
        ...libraryItem("pdf1", "report.pdf"),
        artifact: {
          artifact_id: "pdf1",
          artifact_type: "file.pdf",
          schema_version: 1,
          content_type: "application/pdf",
          byte_size: 3_200_000,
        },
      },
    ];
    const { container } = mount({
      artifact_id: "pdf1",
      artifact_type: "file.pdf",
      schema_version: 1,
    });

    expect(container.querySelector(".lucide-file-text")).not.toBeNull();
    expect(container.querySelector("[data-artifact-media]")).toBeNull();
    expect(container.textContent).toContain("report.pdf");
    // One line beside the mark: format first, then size.
    expect(
      container.querySelector("[data-artifact-file-body]")?.textContent,
    ).toMatch(/^PDF · \d+(\.\d)? [KM]B$/);
  });

  it("shows image dimensions in info and fits the preview to its aspect ratio", async () => {
    const { container } = mount(single("a1"), {}, true);
    const image = container.querySelector("img");
    if (!image) throw new Error("Image preview missing");
    Object.defineProperties(image, {
      naturalWidth: { value: 1920 },
      naturalHeight: { value: 1080 },
    });
    React.act(() => image.dispatchEvent(new Event("load")));

    // The info heads the one actions menu; there is no separate info button.
    expect(
      container.querySelector('[aria-label="Inspect file.jpeg artifact"]'),
    ).toBeNull();
    expect(
      container.querySelector('[aria-label="Actions for file.jpeg@1"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="menu-info"]')?.textContent,
    ).toContain("2.4 MB · 1920 × 1080");
    expect(
      container.querySelector<HTMLElement>("[data-artifact-media]")?.style
        .height,
    ).toBe("149px");
    expect(image.draggable).toBe(false);
  });

  it("keeps the image's aspect ratio when a saved height is larger", () => {
    const { container } = mount(single("a1"), {
      layout: { width: 264, bodyHeight: 220 },
    });
    const image = container.querySelector("img");
    if (!image) throw new Error("Image preview missing");
    Object.defineProperties(image, {
      naturalWidth: { value: 1920 },
      naturalHeight: { value: 1080 },
    });
    React.act(() => image.dispatchEvent(new Event("load")));
    expect(
      container.querySelector<HTMLElement>("[data-artifact-media]")?.style
        .height,
    ).toBe("149px");
  });

  it("preserves the filename and drag action when an image fails to load", () => {
    const { container } = mount(single("a1"), {}, true);
    const image = container.querySelector("img");
    if (!image) throw new Error("Image preview missing");
    React.act(() => image.dispatchEvent(new Event("error")));

    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("boat.jpg");
    expect(container.textContent).toContain("Preview unavailable");
    expect(
      container
        .querySelector('[aria-label="Connect file.jpeg@1 to a node input"]')
        ?.getAttribute("aria-disabled"),
    ).toBe("false");
  });

  it("uses file thumbnails for a non-image sequence", () => {
    const { container } = mount(
      {
        artifact_type: "file.csv",
        schema_version: 1,
        item_refs: ["csv1", "csv2"].map((artifact_id) => ({
          artifact_id,
          artifact_type: "file.csv",
          schema_version: 1,
        })),
        ordered: true,
        index_key: "order_index",
        sequence_id: "csv-sequence",
      },
      {},
      true,
    );
    expect(container.querySelectorAll("img")).toHaveLength(0);
    expect(container.textContent).toContain("File sequence");
    expect(container.textContent).toContain("Sequence<file.csv@1>");
    const reorder = [...container.querySelectorAll("button")].find((button) =>
      button.textContent?.includes("Reorder items"),
    );
    React.act(() => reorder?.click());
    expect(container.querySelectorAll("img")).toHaveLength(0);
    expect(container.textContent).toContain("2 items · use arrows to reorder");
    React.act(() =>
      container
        .querySelector<HTMLButtonElement>('[aria-label="Close sequence order"]')
        ?.click(),
    );
    expect(
      container.querySelector('[aria-label="Move earlier in the order"]'),
    ).toBeNull();
  });
});
