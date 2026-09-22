// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ArtifactRef, PlacedLibraryItem } from "@/lib/api";
import type { ArtifactCardValue } from "../artifact-card";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INPUT_HANDLE,
  type ArtifactViewerNodeData,
} from "../artifact-viewer";
import { WORKFLOW_NODE_TYPE } from "../types";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const libraryMocks = vi.hoisted(() => ({ items: [] as PlacedLibraryItem[] }));
const flowMocks = vi.hoisted(() => ({
  edges: [] as unknown[],
  nodes: new Map<string, unknown>(),
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@xyflow/react", () => ({
  useUpdateNodeInternals: () => vi.fn(),
  useViewport: () => ({ zoom: 1 }),
  useEdges: () => flowMocks.edges,
  useNodesData: (nodeId: string) => flowMocks.nodes.get(nodeId) ?? null,
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

vi.mock("swr", () => ({
  default: () => ({ data: { folders: [], items: libraryMocks.items } }),
}));

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  useWorkspaceContext: () => ({
    workspace: {
      id: "workspace-1",
      slug: "team",
      name: "Local",
      kind: "personal",
      role: "owner",
      capabilities: [],
    },
    workspaces: [],
    refreshWorkspaces: async () => undefined,
  }),
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

function mount(
  value: ArtifactCardValue,
  data: Partial<ArtifactViewerNodeData> = {},
  selected = false,
) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
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
  document.body.replaceChildren();
  libraryMocks.items = [];
  flowMocks.edges = [];
  flowMocks.nodes = new Map();
});

describe("artifact on the canvas", () => {
  beforeEach(() => {
    libraryMocks.items = [libraryItem("a1", "boat.jpg")];
  });

  it("paints a single image with its name floating above it", () => {
    const { container } = mount(single("a1"));
    const image = container.querySelector("img");

    expect(image?.getAttribute("src")).toContain("/artifacts/a1/content");
    expect(container.textContent).toContain("boat.jpg");
    expect(container.querySelector('[title="file.jpeg@1"]')).not.toBeNull();
    expect(container.querySelector("ol")).toBeNull();
    expect(
      container.querySelector('[data-node-pickup-shadow="true"]'),
    ).not.toBeNull();
    expect(container.textContent).toContain("2.4 MB · Image");
    // Use a stable placeholder size until the image dimensions are known.
    const media = container.querySelector<HTMLElement>("[data-artifact-media]");
    expect(media?.style.height).toBe("198px");
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

    const { container } = mount(single("library-1"));

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
        (button) => button.textContent === "Open original",
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
    const { container } = mount(sequence(["a1", "a2", "a3"]));

    expect(container.textContent).toContain("3 artifacts");
    expect(container.textContent).toContain("3 items");
    expect(container.textContent).toContain("Image sequence · 3 items");
  });

  it("hides its actions menu until the card is selected", () => {
    const actions = (container: HTMLElement) =>
      container.querySelector('[aria-label="Actions for file.jpeg@1"]');

    const quiet = mount(single("a1"));
    expect(actions(quiet.container)).toBeNull();

    const picked = mount(single("a1"), {}, true);
    expect(actions(picked.container)).not.toBeNull();
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
    const committed = onRefsChange.mock.calls[0][1];
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
    const { container } = mount(single("zz"));

    expect(container.querySelector("img")?.getAttribute("src")).toContain(
      "/artifacts/zz/content",
    );
    expect(container.querySelector('[title="file.jpeg@1"]')).not.toBeNull();
  });

  it("shows a compact file row for a type it cannot preview", () => {
    const { container } = mount({
      artifact_id: "csv1",
      artifact_type: "file.csv",
      schema_version: 1,
    });

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[data-artifact-media]")).toBeNull();
    expect(container.querySelector('[title="file.csv@1"]')).not.toBeNull();
    expect(container.textContent).not.toContain("not in this library");
  });

  it("shows image dimensions and fits the preview to its aspect ratio", () => {
    const { container } = mount(single("a1"));
    const image = container.querySelector("img");
    if (!image) throw new Error("Image preview missing");
    Object.defineProperties(image, {
      naturalWidth: { value: 1920 },
      naturalHeight: { value: 1080 },
    });
    React.act(() => image.dispatchEvent(new Event("load")));

    expect(container.textContent).toContain("2.4 MB · 1920 × 1080");
    expect(
      container.querySelector<HTMLElement>("[data-artifact-media]")?.style
        .height,
    ).toBe("149px");
    expect(image.draggable).toBe(false);
  });

  it("keeps an explicitly resized preview height when the image loads", () => {
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
    ).toBe("220px");
  });

  it("preserves the filename and drag action when an image fails to load", () => {
    const { container } = mount(single("a1"));
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
    expect(container.textContent).toContain("Sequence · 2 items");
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
