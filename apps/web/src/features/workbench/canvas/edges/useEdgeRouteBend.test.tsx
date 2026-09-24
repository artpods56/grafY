// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

import { renderHook } from "../../ui/test/renderHook";

const flowMocks = vi.hoisted(() => ({
  sourceDragging: false,
  targetDragging: false,
}));

const gridMocks = vi.hoisted(() => ({
  snapWhileDragging: false,
}));

vi.mock("@xyflow/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@xyflow/react")>();
  return {
    ...actual,
    useStore: <Value,>(
      selector: (state: {
        nodeLookup: ReadonlyMap<string, { dragging?: boolean }>;
      }) => Value,
    ): Value =>
      selector({
        nodeLookup: new Map([
          ["source", { dragging: flowMocks.sourceDragging }],
          ["target", { dragging: flowMocks.targetDragging }],
        ]),
      }),
  };
});

vi.mock("../canvas-grid-settings", () => ({
  useOptionalCanvasGridSettings: () => ({
    settings: {
      enabled: true,
      showBackground: true,
      snapPosition: true,
      snapSize: true,
      snapWhileDragging: gridMocks.snapWhileDragging,
      snapWhileResizing: true,
      allowWorkflowCornerResize: false,
      cellSize: 50,
    },
    bypassSnap: false,
  }),
}));

import { useResolvedEdgeRouteOffset } from "./useEdgeRouteBend";

interface DragState {
  source: boolean;
  target: boolean;
}

afterEach(() => {
  flowMocks.sourceDragging = false;
  flowMocks.targetDragging = false;
  gridMocks.snapWhileDragging = false;
});

describe("useResolvedEdgeRouteOffset", () => {
  it("leaves the route unsnapped while either endpoint moves and settles on release", async () => {
    const hook = await renderHook(
      (dragging: DragState) => {
        flowMocks.sourceDragging = dragging.source;
        flowMocks.targetDragging = dragging.target;
        return useResolvedEdgeRouteOffset(
          { x: 13, y: 17 },
          { x: 4, y: 6 },
          false,
          "source",
          "target",
        );
      },
      { source: false, target: false },
    );

    expect(hook.result.current).toEqual({ x: 12, y: 8 });

    await hook.rerender({ source: true, target: false });
    expect(hook.result.current).toEqual({ x: 4, y: 6 });

    await hook.rerender({ source: false, target: true });
    expect(hook.result.current).toEqual({ x: 4, y: 6 });

    await hook.rerender({ source: false, target: false });
    expect(hook.result.current).toEqual({ x: 12, y: 8 });
  });

  it("keeps live snapping when the grid explicitly enables it", async () => {
    gridMocks.snapWhileDragging = true;
    const hook = await renderHook(() => {
      flowMocks.sourceDragging = true;
      flowMocks.targetDragging = false;
      return useResolvedEdgeRouteOffset(
        { x: 13, y: 17 },
        { x: 4, y: 6 },
        false,
        "source",
        "target",
      );
    }, undefined);

    expect(hook.result.current).toEqual({ x: 12, y: 8 });
  });
});
