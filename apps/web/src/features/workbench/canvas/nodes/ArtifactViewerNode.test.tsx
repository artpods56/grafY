// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const flowMocks = vi.hoisted(() => ({
  edges: [] as Record<string, unknown>[],
  nodes: new Map<string, unknown>(),
  updateNodeInternals: vi.fn(),
}));

const previewMocks = vi.hoisted(() => ({
  render: vi.fn(),
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@xyflow/react", () => ({
  Handle: ({
    id,
    isConnectable,
    ...props
  }: {
    id: string;
    isConnectable?: boolean;
    "aria-label"?: string;
  }) => (
    <span
      data-testid="artifact-viewer-handle"
      data-handle-id={id}
      data-connectable={String(isConnectable)}
      aria-label={props["aria-label"]}
    />
  ),
  Position: { Left: "left", Right: "right" },
  useEdges: () => flowMocks.edges,
  useNodesData: (nodeId: string) => flowMocks.nodes.get(nodeId) ?? null,
  useStore: (
    selector: (state: {
      edges: unknown[];
      nodeLookup: Map<string, unknown>;
    }) => unknown,
  ) => selector({ edges: flowMocks.edges, nodeLookup: new Map() }),
  useUpdateNodeInternals: () => flowMocks.updateNodeInternals,
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
    Positioner: ({ children }: { children: React.ReactNode }) => (
      <>{children}</>
    ),
    Popup: ({ children }: { children: React.ReactNode }) => (
      <div role="dialog">{children}</div>
    ),
  },
}));

vi.mock("@/hooks/use-api", () => ({
  useNodeRegistry: () => ({ data: { artifact_types: [] } }),
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

vi.mock("./ArtifactsAppendix", () => ({
  ArtifactPortPreview: (props: {
    output: {
      port: string;
      kind: "single" | "sequence";
      artifacts?: ArtifactSummary[];
    };
    modeChoice: string | null;
    onModeChoiceChange: (mode: string) => void;
    onFocusedArtifactChange?: (artifact: ArtifactSummary | null) => void;
  }) => {
    previewMocks.render(props);
    const focusedArtifact = props.output.artifacts?.[0] ?? null;
    const { onFocusedArtifactChange } = props;
    React.useEffect(() => {
      onFocusedArtifactChange?.(focusedArtifact);
    }, [focusedArtifact, onFocusedArtifactChange]);
    return (
      <button
        type="button"
        data-testid="artifact-port-preview"
        data-port={props.output.port}
        data-kind={props.output.kind}
        onClick={() => props.onModeChoiceChange("raw")}
      >
        Preview {props.output.port}
      </button>
    );
  },
}));

vi.mock("./LayoutResizeHandle", () => ({
  LayoutResizeHandle: ({ ariaLabel }: { ariaLabel: string }) => (
    <button type="button" data-testid="corner-resize" aria-label={ariaLabel} />
  ),
}));

import type {
  ArtifactSummary,
  NodeSpec,
  RunNodeResult,
  RunPortOutput,
} from "@/lib/api";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INPUT_HANDLE,
  ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE,
  ARTIFACT_VIEWER_INTERACTION_INPUT_HANDLE,
  ARTIFACT_VIEWER_INTERACTION_OUTPUT_HANDLE,
  ARTIFACT_VIEWER_NODE_TYPE,
  type ArtifactViewerEdge,
  type ArtifactViewerNode,
  type ArtifactViewerNodeData,
  type CanvasWorkflowNode,
} from "../artifact-viewer";
import { WORKFLOW_NODE_TYPE, createWorkflowNodeData } from "../types";
import ArtifactViewerNodeCard from "./ArtifactViewerNode";

const roots: Root[] = [];

function sourceSpec(shape: "one" | "many"): NodeSpec {
  return {
    operator_id: "test.render-source",
    operator_version: 1,
    plugin_slug: "test",
    origin: "builtin",
    title: "Prepare map",
    description: "Produces multiple outputs for viewer tests.",
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [
      {
        name: "metadata",
        title: "Metadata",
        description: null,
        direction: "output",
        artifact_type: { id: "json.object", schema_version: 1 },
        artifact_type_variable: null,
        shape: "one",
        accepted_shapes: ["one"],
        instance_plugs: false,
        variadic: false,
        required: true,
      },
      {
        name: "preview",
        title: "Raster preview",
        description: null,
        direction: "output",
        artifact_type: { id: "image.raster", schema_version: 1 },
        artifact_type_variable: null,
        shape,
        accepted_shapes: [shape],
        instance_plugs: false,
        variadic: false,
        required: true,
      },
    ],
  };
}

function artifact(id: string, artifactType: string): ArtifactSummary {
  return {
    artifact_id: id,
    artifact_type: artifactType,
    schema_version: 1,
    content_type: "application/json",
    content_url: `./artifacts/${id}/content`,
    byte_size: 42,
  };
}

function runOutput(
  port: string,
  kind: "single" | "sequence",
  item: ArtifactSummary,
): RunPortOutput {
  const ref = {
    artifact_id: item.artifact_id,
    artifact_type: item.artifact_type,
    schema_version: item.schema_version,
    content_hash: null,
  };
  return {
    port,
    kind,
    value:
      kind === "single"
        ? ref
        : {
            artifact_type: item.artifact_type,
            schema_version: item.schema_version,
            index_key: "order_index",
            ordered: true,
            item_refs: [ref],
          },
    artifacts: [item],
  };
}

function sourceNode(
  shape: "one" | "many",
  run: RunNodeResult | null,
): CanvasWorkflowNode {
  const data = createWorkflowNodeData(sourceSpec(shape));
  data.run = run;
  data.execution = { status: run?.status ?? "idle" };
  return {
    id: "source-node",
    type: WORKFLOW_NODE_TYPE,
    position: { x: 0, y: 0 },
    data,
  };
}

function viewerEdge(): ArtifactViewerEdge {
  return {
    id: "artifact-viewer-edge-1",
    type: ARTIFACT_VIEWER_EDGE_TYPE,
    source: "source-node",
    target: "artifact-viewer-1",
    targetHandle: ARTIFACT_VIEWER_INPUT_HANDLE,
    data: { sourcePortName: "preview" },
  };
}

function renderViewer(
  overrides: Partial<ArtifactViewerNodeData> = {},
  selected = false,
  dragging = false,
): HTMLDivElement {
  const container = document.createElement("div");
  const root = createRoot(container);
  roots.push(root);
  const data: ArtifactViewerNodeData = {
    layout: null,
    mode: null,
    ...overrides,
  };
  const node: ArtifactViewerNode = {
    id: "artifact-viewer-1",
    type: ARTIFACT_VIEWER_NODE_TYPE,
    position: { x: 0, y: 0 },
    data,
  };

  React.act(() => {
    root.render(
      <ArtifactViewerNodeCard
        {...({
          id: node.id,
          data: node.data,
          selected,
          dragging,
          isConnectable: true,
        } as React.ComponentProps<typeof ArtifactViewerNodeCard>)}
      />,
    );
  });
  return container;
}

beforeEach(() => {
  flowMocks.edges = [];
  flowMocks.nodes.clear();
  flowMocks.updateNodeInternals.mockClear();
  previewMocks.render.mockClear();
});

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  vi.restoreAllMocks();
});

describe("ArtifactViewerNode", () => {
  it("drives pickup depth from selection and active dragging", () => {
    const resting = renderViewer();
    const selected = renderViewer({}, true);
    const dragging = renderViewer({}, false, true);

    expect(
      resting
        .querySelector('[data-node-pickup-shadow="true"]')
        ?.getAttribute("data-picked-up"),
    ).toBe("false");
    expect(
      selected
        .querySelector('[data-node-pickup-shadow="true"]')
        ?.getAttribute("data-picked-up"),
    ).toBe("true");
    expect(
      dragging
        .querySelector('[data-node-pickup-shadow="true"]')
        ?.getAttribute("data-dragging"),
    ).toBe("true");
  });

  it("invites a generic artifact connection while disconnected", () => {
    const container = renderViewer();

    expect(container.textContent).toContain("Artifact Viewer");
    expect(container.textContent).toContain("Artifact");
    expect(container.textContent).toContain("any");
    expect(container.textContent).not.toContain("linked input");
    expect(container.textContent).not.toContain("Follow selection");
    expect(container.querySelector('[data-testid="port-rail"]')).not.toBeNull();
    expect(
      container.querySelector(
        '[aria-label="Input port Artifact, accepts Any artifact"]',
      ),
    ).not.toBeNull();
    expect(
      container.querySelector('[aria-label="Remove Artifact viewer"]'),
    ).toBeNull();
    expect(container.querySelector('[data-testid="corner-resize"]')).toBeNull();
    expect(previewMocks.render).not.toHaveBeenCalled();
  });

  it("uses the shared header actions when selected", () => {
    const container = renderViewer({}, true);
    const remove = vi.fn();
    const selected = renderViewer({ onRemoveNode: remove }, true);

    expect(
      container.querySelector('[aria-label="About Artifact Viewer"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[aria-label="Actions for Artifact Viewer"]'),
    ).not.toBeNull();
    const deleteNode = [...selected.querySelectorAll("button")].find(
      (button) => button.textContent === "Delete node",
    );
    expect(deleteNode).toBeDefined();
    React.act(() => {
      deleteNode?.click();
    });
    expect(remove).toHaveBeenCalledWith("artifact-viewer-1");
  });

  it("offers download formats for the focused artifact in the overflow menu", () => {
    let clickedHref: string | null = null;
    let clickedHadDownload = false;
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clickedHref = this.getAttribute("href");
      clickedHadDownload = this.hasAttribute("download");
    });
    const artifactWithFormats: ArtifactSummary = {
      ...artifact("download-artifact", "text.markdown"),
      download_formats: [
        {
          format: "json",
          content_type: "application/json",
          filename: "artifact.json",
        },
        {
          format: "txt",
          content_type: "text/plain; charset=utf-8",
          filename: "text.txt",
        },
      ],
    };
    const preview = runOutput("preview", "single", artifactWithFormats);
    flowMocks.edges = [viewerEdge()];
    flowMocks.nodes.set(
      "source-node",
      sourceNode("one", {
        node_id: "source-node",
        status: "succeeded",
        error: null,
        outputs: [preview],
      }),
    );

    const container = renderViewer({}, true);

    expect(
      container.querySelector('[aria-label="Actions for Artifact Viewer"]'),
    ).not.toBeNull();

    const menuButtons = [...container.querySelectorAll("button")];
    const jsonDownload = menuButtons.find(
      (button) => button.textContent === "Download as JSON",
    );
    const txtDownload = menuButtons.find(
      (button) => button.textContent === "Download as TXT",
    );
    expect(jsonDownload).toBeDefined();
    expect(txtDownload).toBeDefined();

    React.act(() => {
      jsonDownload?.click();
    });
    expect(clickedHref).toBe(
      "/api/v1/workspaces/workspace-1/artifacts/download-artifact/download?format=json",
    );
    expect(clickedHadDownload).toBe(true);
    expect(document.querySelector("a[download]")).toBeNull();
  });

  it("shows provenance but no preview until the named output succeeds", () => {
    const preview = runOutput(
      "preview",
      "single",
      artifact("failed-preview", "image.raster"),
    );
    flowMocks.edges = [viewerEdge()];
    flowMocks.nodes.set(
      "source-node",
      sourceNode("one", {
        node_id: "source-node",
        status: "failed",
        outputs: [preview],
        error: "Rendering failed",
      }),
    );

    const container = renderViewer({}, true);

    expect(container.textContent).toContain("Prepare map → Raster preview");
    expect(container.textContent).toContain("image.raster@1 · single");
    expect(container.textContent).toContain("Waiting for artifact");
    expect(container.textContent).not.toContain("Follow selection");
    expect(container.textContent).not.toContain("Selected rows");
    expect(previewMocks.render).not.toHaveBeenCalled();
  });

  it.each([
    ["one", "single"],
    ["many", "sequence"],
  ] as const)(
    "renders only the connected %s output as a %s contract and forwards mode changes",
    (shape, kind) => {
      const metadata = runOutput(
        "metadata",
        "single",
        artifact("metadata-artifact", "json.object"),
      );
      const preview = runOutput(
        "preview",
        kind,
        artifact("preview-artifact", "image.raster"),
      );
      flowMocks.edges = [viewerEdge()];
      flowMocks.nodes.set(
        "source-node",
        sourceNode(shape, {
          node_id: "source-node",
          status: "succeeded",
          outputs: [metadata, preview],
          error: null,
        }),
      );
      const onModeChange = vi.fn();

      const container = renderViewer(
        {
          mode: "map",
          onModeChange,
        },
        true,
      );

      expect(container.textContent).toContain("Prepare map → Raster preview");
      expect(container.textContent).toContain(`image.raster@1 · ${kind}`);
      expect(container.textContent).not.toContain("Materialized");
      expect(
        container.querySelector('[data-testid="artifact-port-preview"]'),
      ).not.toBeNull();
      expect(
        container
          .querySelector('[data-testid="artifact-port-preview"]')
          ?.getAttribute("data-port"),
      ).toBe("preview");
      const previewProps = previewMocks.render.mock.calls.at(-1)?.[0];
      expect(previewProps?.output).toBe(preview);
      expect(previewProps?.output).not.toBe(metadata);
      expect(previewProps?.modeChoice).toBe("map");

      React.act(() => {
        container
          .querySelector<HTMLButtonElement>(
            '[data-testid="artifact-port-preview"]',
          )
          ?.click();
      });
      expect(onModeChange).toHaveBeenCalledWith("artifact-viewer-1", "raw");
    },
  );

  it("keeps a corner resize handle once a preview is showing", () => {
    const preview = runOutput(
      "preview",
      "single",
      artifact("preview-artifact", "image.raster"),
    );
    flowMocks.edges = [viewerEdge()];
    flowMocks.nodes.set(
      "source-node",
      sourceNode("one", {
        node_id: "source-node",
        status: "succeeded",
        outputs: [preview],
        error: null,
      }),
    );

    const container = renderViewer();
    expect(
      container.querySelector('[data-testid="corner-resize"]'),
    ).not.toBeNull();
    expect(container.textContent).not.toContain("Follow selection");
    expect(container.textContent).not.toContain("Selected rows");
  });

  it("shows follow ports when the live renderer can brush", () => {
    const preview = runOutput(
      "preview",
      "single",
      artifact("parcels", "table.data"),
    );
    flowMocks.edges = [viewerEdge()];
    flowMocks.nodes.set(
      "source-node",
      sourceNode("one", {
        node_id: "source-node",
        status: "succeeded",
        outputs: [preview],
        error: null,
      }),
    );

    const container = renderViewer();
    expect(container.textContent).toContain("Follow selection");
    expect(container.textContent).toContain("Selected rows");
    expect(
      container.querySelector(
        '[aria-label="Follow selection from another Artifact Viewer"]',
      ),
    ).not.toBeNull();
    expect(
      container.querySelector(
        '[aria-label="Selected rows from this Artifact Viewer"]',
      ),
    ).not.toBeNull();
  });

  it("keeps follow ports when a binding already exists", () => {
    const preview = runOutput(
      "preview",
      "single",
      artifact("notes", "text.markdown"),
    );
    flowMocks.edges = [
      viewerEdge(),
      {
        id: "artifact-viewer-binding-1",
        type: ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE,
        source: "artifact-viewer-1",
        target: "artifact-viewer-2",
        sourceHandle: ARTIFACT_VIEWER_INTERACTION_OUTPUT_HANDLE,
        targetHandle: ARTIFACT_VIEWER_INTERACTION_INPUT_HANDLE,
      },
    ];
    flowMocks.nodes.set(
      "source-node",
      sourceNode("one", {
        node_id: "source-node",
        status: "succeeded",
        outputs: [preview],
        error: null,
      }),
    );

    const container = renderViewer();
    expect(container.textContent).toContain("Follow selection");
    expect(container.textContent).toContain("Selected rows");
  });
});
