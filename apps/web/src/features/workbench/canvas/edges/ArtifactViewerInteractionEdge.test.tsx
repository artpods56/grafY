// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const flowMocks = vi.hoisted(() => ({
  deleteElements: vi.fn(),
}));

const dockMocks = vi.hoisted(() => ({
  docked: false,
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@xyflow/react", () => ({
  BaseEdge: () => <svg data-testid="base-edge" />,
  EdgeLabelRenderer: ({ children }: { children: React.ReactNode }) => children,
  getBezierPath: () => ["M 0 0 C 0 0 100 100 100 100", 50, 50],
  useReactFlow: () => ({ deleteElements: flowMocks.deleteElements }),
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
      <div data-testid="edge-selector-menu">{children}</div>
    ),
  },
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
      allowWorkflowCornerResize: false,
      cellSize: 50,
    },
  }),
}));

vi.mock("./useDockedConnection", () => ({
  useEdgeIsDocked: () => dockMocks.docked,
  useHandleIsDocked: () => false,
}));

vi.mock("./useEdgeFanOffsets", () => ({
  useEdgeFanOffsets: () => ({ source: 0, target: 0 }),
}));

import {
  ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE,
  ARTIFACT_VIEWER_INTERACTION_INPUT_HANDLE,
  ARTIFACT_VIEWER_INTERACTION_OUTPUT_HANDLE,
  type ArtifactViewerInteractionEdge,
  type ArtifactViewerInteractionEdgeData,
} from "../artifact-viewer";
import ArtifactViewerInteractionEdgeControl from "./ArtifactViewerInteractionEdge";

const roots: Root[] = [];
const containers: HTMLElement[] = [];

function bindingEdge(): ArtifactViewerInteractionEdge & {
  data: ArtifactViewerInteractionEdgeData;
} {
  return {
    id: "artifact-viewer-binding-1",
    type: ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE,
    source: "artifact-viewer-table",
    sourceHandle: ARTIFACT_VIEWER_INTERACTION_OUTPUT_HANDLE,
    target: "artifact-viewer-map",
    targetHandle: ARTIFACT_VIEWER_INTERACTION_INPUT_HANDLE,
    data: {
      binding: {
        id: "artifact-viewer-binding-1",
        sourceViewerId: "artifact-viewer-table",
        targetViewerId: "artifact-viewer-map",
        mappings: [{ sourceField: "", targetField: "" }],
        effects: ["highlight", "focus"],
        emptySelection: "show_all",
      },
      sourceFields: [
        {
          id: "normalized_name",
          title: "Normalized name",
          valueType: "text",
        },
      ],
      targetFields: [
        {
          id: "transliteration",
          title: "Transliteration",
          valueType: "text",
        },
      ],
    },
  };
}

function renderEdge(edge: ArtifactViewerInteractionEdge) {
  const container = document.createElement("div");
  document.body.append(container);
  containers.push(container);
  const root = createRoot(container);
  roots.push(root);
  React.act(() => {
    root.render(
      <ArtifactViewerInteractionEdgeControl
        {...({
          id: edge.id,
          data: edge.data,
          sourceX: 0,
          sourceY: 0,
          targetX: 12,
          targetY: 0,
          sourcePosition: "right",
          targetPosition: "left",
          selected: false,
        } as React.ComponentProps<typeof ArtifactViewerInteractionEdgeControl>)}
      />,
    );
  });
  return container;
}

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  for (const container of containers.splice(0)) container.remove();
  flowMocks.deleteElements.mockReset();
  dockMocks.docked = false;
});

describe("ArtifactViewerInteractionEdge", () => {
  it("authors field mappings from a closed set of discovered viewer fields", () => {
    const onBindingChange = vi.fn();
    const edge = bindingEdge();
    edge.data = { ...edge.data, onBindingChange };
    renderEdge(edge);

    const sourceSelect = document.body.querySelector<HTMLSelectElement>(
      '[aria-label="Source field 1"]',
    );
    const targetSelect = document.body.querySelector<HTMLSelectElement>(
      '[aria-label="Target field 1"]',
    );
    expect(sourceSelect?.tagName).toBe("SELECT");
    expect(targetSelect?.tagName).toBe("SELECT");
    expect(
      [...(sourceSelect?.options ?? [])].map((option) => [
        option.value,
        option.textContent,
      ]),
    ).toEqual([
      ["", "Choose field"],
      ["normalized_name", "Normalized name · text"],
    ]);
    expect(
      [...(targetSelect?.options ?? [])].map((option) => [
        option.value,
        option.textContent,
      ]),
    ).toEqual([
      ["", "Choose field"],
      ["transliteration", "Transliteration · text"],
    ]);

    React.act(() => {
      if (!sourceSelect) return;
      sourceSelect.value = "normalized_name";
      sourceSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(onBindingChange).toHaveBeenLastCalledWith(
      "artifact-viewer-binding-1",
      expect.objectContaining({
        mappings: [
          {
            sourceField: "normalized_name",
            targetField: "",
          },
        ],
      }),
    );

    const filter = [...document.body.querySelectorAll("label")]
      .find((label) => label.textContent?.trim() === "filter")
      ?.querySelector<HTMLInputElement>("input");
    React.act(() => filter?.click());
    expect(onBindingChange).toHaveBeenLastCalledWith(
      "artifact-viewer-binding-1",
      expect.objectContaining({
        effects: ["highlight", "focus", "filter"],
      }),
    );
  });

  it("keeps a persisted field visible until it exists in the discovered set", () => {
    const edge = bindingEdge();
    edge.data = {
      ...edge.data,
      binding: {
        ...edge.data!.binding!,
        mappings: [{ sourceField: "legacy_id", targetField: "" }],
      },
    };
    renderEdge(edge);

    const sourceSelect = document.body.querySelector<HTMLSelectElement>(
      '[aria-label="Source field 1"]',
    );
    expect(
      [...(sourceSelect?.options ?? [])].map((option) => option.value),
    ).toEqual(["", "legacy_id", "normalized_name"]);
    expect(sourceSelect?.value).toBe("legacy_id");
  });

  it("disables mapping until the viewer has published fields", () => {
    const edge = bindingEdge();
    edge.data = {
      ...edge.data,
      sourceFields: [],
      targetFields: [],
    };
    renderEdge(edge);

    const sourceSelect = document.body.querySelector<HTMLSelectElement>(
      '[aria-label="Source field 1"]',
    );
    expect(sourceSelect?.disabled).toBe(true);
    expect(sourceSelect?.options[0]?.textContent).toBe("No fields yet");
  });

  it("removes the persisted binding through the canvas edge contract", () => {
    const container = renderEdge(bindingEdge());
    React.act(() => {
      container
        .querySelector<HTMLButtonElement>(
          '[aria-label="Remove viewer interaction"]',
        )
        ?.click();
    });
    expect(flowMocks.deleteElements).toHaveBeenCalledWith({
      edges: [{ id: "artifact-viewer-binding-1" }],
    });
  });

  it("docks into the lattice gutter with the shared selector pill", () => {
    dockMocks.docked = true;
    const container = renderEdge(bindingEdge());
    const block = container.querySelector(
      '[data-testid="edge-selector-block"]',
    );
    expect(block?.getAttribute("data-docked")).toBe("true");
    expect(container.textContent).toContain("follow · highlight + focus");
  });
});
