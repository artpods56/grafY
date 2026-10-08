// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const flowMocks = vi.hoisted(() => ({
  baseEdgeStyle: undefined as React.CSSProperties | undefined,
}));

const dockMocks = vi.hoisted(() => ({
  docked: false,
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("@xyflow/react", () => ({
  Position: { Left: "left", Right: "right", Top: "top", Bottom: "bottom" },
  BaseEdge: ({ style }: { style?: React.CSSProperties }) => {
    flowMocks.baseEdgeStyle = style;
    return null;
  },
  EdgeLabelRenderer: () => null,
  useReactFlow: () => ({ deleteElements: vi.fn() }),
}));

vi.mock("../canvas-grid-settings", () => ({
  useOptionalCanvasGridSettings: () => null,
}));

vi.mock("./useDockedConnection", () => ({
  useEdgeIsDocked: () => dockMocks.docked,
}));

vi.mock("./useEdgeFanOffsets", () => ({
  useEdgeFanOffsets: () => ({ source: 0, target: 0 }),
}));

vi.mock("./useEdgeRouteBend", () => ({
  useEdgeRouteBendHandlers: () => ({}),
  useResolvedEdgeRouteOffset: (
    _anchor: unknown,
    offset: { x: number; y: number },
  ) => offset,
}));

import type { WorkflowEdgeData } from "../types";
import WorkflowEdgeControl from "./WorkflowEdge";

// jsdom drops light-dark() from inline styles, so named colors stand in.
const SOURCE_STROKE = "purple";
const TARGET_STROKE = "orange";

const roots: Root[] = [];
const containers: HTMLElement[] = [];

function renderEdge(data: Partial<WorkflowEdgeData>) {
  const container = document.createElement("div");
  document.body.append(container);
  containers.push(container);
  const root = createRoot(container);
  roots.push(root);
  React.act(() => {
    root.render(
      <svg>
        <WorkflowEdgeControl
          {...({
            id: "edge-1",
            source: "ocr",
            target: "prompt",
            data: { enabled: true, collectionMode: "direct", ...data },
            sourceX: 0,
            sourceY: 10,
            targetX: 200,
            targetY: 90,
            sourcePosition: "right",
            targetPosition: "left",
            selected: false,
            style: { stroke: SOURCE_STROKE, strokeWidth: 2 },
          } as React.ComponentProps<typeof WorkflowEdgeControl>)}
        />
      </svg>,
    );
  });
  return container;
}

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  for (const container of containers.splice(0)) container.remove();
  flowMocks.baseEdgeStyle = undefined;
  dockMocks.docked = false;
});

describe("WorkflowEdge type blend", () => {
  it("fades a converting edge from the source type into the delivered type", () => {
    const container = renderEdge({ targetStroke: TARGET_STROKE });

    const gradient = container.querySelector("linearGradient");
    expect(gradient?.id).toBe("edge-1-type-blend");
    expect(flowMocks.baseEdgeStyle?.stroke).toBe("url(#edge-1-type-blend)");
    expect(
      ["x1", "y1", "x2", "y2"].map((name) => gradient?.getAttribute(name)),
    ).toEqual(["0", "10", "200", "90"]);
    expect(
      [...(gradient?.querySelectorAll("stop") ?? [])].map((stop) => [
        stop.getAttribute("offset"),
        stop.style.stopColor,
      ]),
    ).toEqual([
      ["30%", SOURCE_STROKE],
      ["70%", TARGET_STROKE],
    ]);
  });

  it("keeps a solid stroke when the route delivers the source type", () => {
    for (const targetStroke of [undefined, SOURCE_STROKE]) {
      const container = renderEdge({ targetStroke });

      expect(container.querySelector("linearGradient")).toBeNull();
      expect(flowMocks.baseEdgeStyle?.stroke).toBe(SOURCE_STROKE);
    }
  });

  it("skips the blend while the edge is docked", () => {
    dockMocks.docked = true;
    const container = renderEdge({ targetStroke: TARGET_STROKE });

    expect(container.querySelector("linearGradient")).toBeNull();
    expect(flowMocks.baseEdgeStyle?.stroke).toBe(SOURCE_STROKE);
  });
});
