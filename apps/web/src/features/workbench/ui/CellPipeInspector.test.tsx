// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ARTIFACT_ORIGIN_EDGE_TYPE,
  type ArtifactOriginEdge,
} from "../canvas/artifact-origin-edge";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  type ArtifactViewerEdge,
} from "../canvas/artifact-viewer";
import { WORKFLOW_EDGE_TYPE, type WorkflowEdge } from "../canvas/types";
import { CellCanvasProvider } from "../cell-canvas/CellCanvasContext";
import type { CellViewportApi } from "../cell-canvas/cell-contracts";
import { CellPipeInspector, type CellInspectedPipe } from "./CellPipeInspector";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots: ReturnType<typeof createRoot>[] = [];

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.replaceChildren();
});

function renderInspector(
  pipe: CellInspectedPipe,
  overrides: Partial<React.ComponentProps<typeof CellPipeInspector>> = {},
  viewportApi: CellViewportApi | null = null,
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  const props: React.ComponentProps<typeof CellPipeInspector> = {
    pipe,
    anchor: { x: 400, y: 200 },
    editable: true,
    onClose: vi.fn(),
    onUpdateWorkflowEdge: vi.fn(),
    onUpdateOriginCollectionMode: vi.fn(),
    onUpdateViewerEdge: vi.fn(),
    onRemovePipe: vi.fn(),
    ...overrides,
  };
  React.act(() => {
    root.render(
      <CellCanvasProvider viewportApi={viewportApi}>
        <CellPipeInspector {...props} />
      </CellCanvasProvider>,
    );
  });
  return { container, props };
}

function buttonWithText(
  container: HTMLElement,
  text: string,
): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll("button")).find((btn) =>
    btn.textContent?.includes(text),
  );
  if (!match) throw new Error(`No button matching ${text}`);
  return match;
}

describe("CellPipeInspector", () => {
  it("edits workflow enabled state, collection mode, feed routes, and removal", () => {
    const workflowEdge: WorkflowEdge = {
      id: "edge-1",
      type: WORKFLOW_EDGE_TYPE,
      source: "n1",
      target: "n2",
      data: {
        enabled: true,
        collectionMode: "direct",
        sourcePortName: "document",
        projection: undefined,
        conversionPath: [],
        allowedCollectionModes: ["direct", "map"],
        routeOptions: [
          {
            conversionPath: [],
            conversionTitles: [],
          },
          {
            projection: { path: ["title"] },
            projectionTitle: "Title",
            conversionPath: [{ id: "csv.to_table", version: 1 }],
            conversionTitles: ["CSV → Table"],
          },
        ],
      },
    };
    const { container, props } = renderInspector({
      kind: "workflow",
      edge: workflowEdge,
    });

    expect(
      container
        .querySelector('[role="dialog"]')
        ?.getAttribute("data-cell-pipe-inspector"),
    ).toBe("edge-1");

    const enabledSwitch = container.querySelector('[role="switch"]');
    expect(enabledSwitch?.getAttribute("aria-checked")).toBe("true");
    React.act(() => {
      enabledSwitch?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(props.onUpdateWorkflowEdge).toHaveBeenCalledWith("edge-1", {
      enabled: false,
    });

    React.act(() => {
      buttonWithText(container, "Each item (map)").click();
    });
    expect(props.onUpdateWorkflowEdge).toHaveBeenCalledWith("edge-1", {
      collectionMode: "map",
    });

    React.act(() => {
      buttonWithText(container, "Title → CSV → Table").click();
    });
    expect(props.onUpdateWorkflowEdge).toHaveBeenCalledWith("edge-1", {
      route: {
        projection: { path: ["title"] },
        conversionPath: [{ id: "csv.to_table", version: 1 }],
      },
    });

    React.act(() => {
      buttonWithText(container, "Remove connection").click();
    });
    expect(props.onRemovePipe).toHaveBeenCalledWith("edge-1");
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("shows compatibility issues and disables route controls while allowing removal", () => {
    const workflowEdge: WorkflowEdge = {
      id: "edge-bad",
      type: WORKFLOW_EDGE_TYPE,
      source: "n1",
      target: "n2",
      data: {
        enabled: true,
        collectionMode: "direct",
        sourcePortName: "document",
        allowedCollectionModes: ["direct", "map"],
        compatibilityIssues: ["Target port missing"],
      },
    };
    const { container, props } = renderInspector({
      kind: "workflow",
      edge: workflowEdge,
    });

    expect(container.textContent).toContain("Target port missing");
    expect(
      container.querySelector('[role="switch"]')?.getAttribute("aria-disabled"),
    ).toBe("true");
    expect(buttonWithText(container, "Each item (map)").disabled).toBe(true);
    expect(buttonWithText(container, "Remove connection").disabled).toBe(false);

    React.act(() => {
      buttonWithText(container, "Remove connection").click();
    });
    expect(props.onRemovePipe).toHaveBeenCalledWith("edge-bad");
  });

  it("edits origin collection mode and disconnects origin pipes", () => {
    const originEdge: ArtifactOriginEdge = {
      id: "artifact-origin:o1:v1",
      type: ARTIFACT_ORIGIN_EDGE_TYPE,
      source: "v1",
      target: "n1",
      data: {
        originId: "o1",
        collectionMode: "direct",
        allowedCollectionModes: ["direct", "map"],
      },
    };
    const { container, props } = renderInspector({
      kind: "origin",
      edge: originEdge,
    });

    React.act(() => {
      buttonWithText(container, "Each item (map)").click();
    });
    expect(props.onUpdateOriginCollectionMode).toHaveBeenCalledWith(
      "o1",
      "map",
    );

    React.act(() => {
      buttonWithText(container, "Disconnect").click();
    });
    expect(props.onRemovePipe).toHaveBeenCalledWith("artifact-origin:o1:v1");
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("updates viewer feed projection and removes viewer links", () => {
    const viewerEdge: ArtifactViewerEdge = {
      id: "viewer-edge-1",
      type: ARTIFACT_VIEWER_EDGE_TYPE,
      source: "n1",
      target: "v1",
      data: {
        sourcePortName: "output",
        routeOptions: [
          { conversionPath: [], conversionTitles: [] },
          {
            projection: { path: ["summary"] },
            projectionTitle: "Summary",
            conversionPath: [],
            conversionTitles: [],
          },
        ],
      },
    };
    const { container, props } = renderInspector({
      kind: "viewer",
      edge: viewerEdge,
    });

    React.act(() => {
      buttonWithText(container, "Summary").click();
    });
    expect(props.onUpdateViewerEdge).toHaveBeenCalledWith("viewer-edge-1", {
      projection: { path: ["summary"] },
    });

    React.act(() => {
      buttonWithText(container, "Remove link").click();
    });
    expect(props.onRemovePipe).toHaveBeenCalledWith("viewer-edge-1");
    expect(props.onClose).toHaveBeenCalledTimes(1);
  });

  it("uses viewport worldToScreen, closes on Escape and close button", () => {
    const onClose = vi.fn();
    const originEdge: ArtifactOriginEdge = {
      id: "origin-edge",
      type: ARTIFACT_ORIGIN_EDGE_TYPE,
      source: "v1",
      target: "n1",
      data: { originId: "o1" },
    };
    const viewportApi: CellViewportApi = {
      viewport: { x: 0, y: 0, zoom: 1 },
      screenToWorld: (x, y) => ({ x, y }),
      worldToScreen: ({ x, y }) => ({ x: x + 100, y: y + 50 }),
      zoomAtCenter: vi.fn(),
      zoomBy: vi.fn(),
      fitRect: vi.fn(),
      viewAt: vi.fn(() => ({ x: 0, y: 0, zoom: 1 })),
    };

    const { container } = renderInspector(
      { kind: "origin", edge: originEdge },
      { anchor: { x: 300, y: 150 }, onClose },
      viewportApi,
    );

    const dialog = container.querySelector<HTMLElement>('[role="dialog"]');
    // screen = (400, 200); left = 400 - 264/2 = 268px; top = 200 + 16 = 216px
    expect(dialog?.style.left).toBe("268px");
    expect(dialog?.style.top).toBe("216px");

    React.act(() => {
      window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    });
    expect(onClose).toHaveBeenCalledTimes(1);

    React.act(() => {
      container
        .querySelector<HTMLButtonElement>(
          '[aria-label="Close connection editor"]',
        )
        ?.click();
    });
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
