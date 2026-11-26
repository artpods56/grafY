// @vitest-environment jsdom

import { act, Profiler, useReducer } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  TiffRegionsEditOverlay,
  type TiffRegionsEditOverlayProps,
} from "./TiffRegionsEditOverlay";
import {
  createTiffTextRegionsEditorState,
  tiffTextRegionsEditorReducer,
  type TiffTextRegionsEditorAction,
  type TiffTextRegionsEditorState,
} from "./tiff-text-regions-editor-reducer";
import { parseTiffTextRegionsPayload } from "./types";

const size = { width: 800, height: 600 };

class Point {
  readonly x: number;
  readonly y: number;

  constructor(x: number, y: number) {
    this.x = x;
    this.y = y;
  }
}

const polygon = [
  [10, 20],
  [30, 20],
  [30, 40],
  [10, 40],
];

async function mount({
  count = 2,
  scale = 1,
  initialOverlayWidth = 400 * scale,
}: { count?: number; scale?: number; initialOverlayWidth?: number } = {}) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const element = document.createElement("div");
  const canvas = document.createElement("div");
  element.append(canvas);
  document.body.append(element);
  Object.defineProperties(element, {
    clientWidth: { value: size.width },
    clientHeight: { value: size.height },
    getBoundingClientRect: {
      value: () => ({
        left: 10,
        top: 20,
        width: size.width * scale,
        height: size.height * scale,
      }),
    },
  });
  let overlayWidth = initialOverlayWidth;
  const layers: HTMLElement[] = [];
  const handlers = new Map<string, () => void>();
  const setMouseNavEnabled = vi.fn();
  const viewer = {
    element,
    canvas,
    container: element,
    viewport: { getZoom: () => 2 },
    setMouseNavEnabled,
    world: {
      getItemAt: () => ({
        imageToViewportRectangle: () => ({}),
        viewerElementToImageCoordinates: (point: Point) =>
          new Point(point.x * 2, point.y * 2),
        imageToViewerElementCoordinates: (point: Point) =>
          new Point(point.x / 2, point.y / 2),
      }),
    },
    addOverlay: (layer: HTMLElement) => {
      layers.push(layer);
      layer.getBoundingClientRect = () =>
        DOMRect.fromRect({ width: overlayWidth });
      const wrapper = document.createElement("div");
      wrapper.className = "openseadragon-overlay-wrapper";
      wrapper.append(layer);
      canvas.append(wrapper);
    },
    removeOverlay: (layer: HTMLElement) => layer.parentElement?.remove(),
    addHandler: (event: string, listener: () => void) =>
      handlers.set(event, listener),
    removeHandler: (event: string) => handlers.delete(event),
  };
  const parsed = parseTiffTextRegionsPayload({
    source: { artifact_id: "scan" },
    window: { page: 0, col: 0, row: 0, ...size },
    regions: Array.from({ length: count }, (_, index) => ({
      polygon,
      reading: { text: `Region ${index}`, confidence: null },
    })),
  });
  if (!parsed.ok) throw new Error(parsed.reason);
  const commits = vi.fn();
  let state = createTiffTextRegionsEditorState(parsed.payload);
  let send: React.Dispatch<TiffTextRegionsEditorAction> = () => {};
  function Harness() {
    [state, send] = useReducer(tiffTextRegionsEditorReducer, state);
    return (
      <Profiler id="overlay" onRender={commits}>
        <TiffRegionsEditOverlay
          viewer={viewer as unknown as TiffRegionsEditOverlayProps["viewer"]}
          PixelPoint={
            Point as unknown as TiffRegionsEditOverlayProps["PixelPoint"]
          }
          pageSize={size}
          state={state}
          dispatch={send}
        />
      </Profiler>
    );
  }
  await act(() => root.render(<Harness />));
  function target(selector: string) {
    const node =
      host.querySelector(selector) ?? element.querySelector(selector);
    if (!node) throw new Error(`Missing ${selector}`);
    return node;
  }
  async function pointer(
    node: Element,
    type: string,
    x: number,
    y: number,
    init: MouseEventInit = {},
  ) {
    for (const target of [
      node,
      node instanceof SVGElement ? node.ownerSVGElement : null,
    ]) {
      if (target && !target.setPointerCapture) {
        Object.defineProperty(target, "setPointerCapture", { value: vi.fn() });
      }
    }
    const event = new MouseEvent(type, {
      bubbles: true,
      cancelable: true,
      button: 0,
      clientX: 10 + (x * scale) / 2,
      clientY: 20 + (y * scale) / 2,
      ...init,
    });
    Object.defineProperty(event, "pointerId", { value: 1 });
    await act(() => {
      node.dispatchEvent(event);
    });
    return event;
  }
  return {
    target,
    element,
    canvas,
    layers,
    commits,
    handlers,
    pointer,
    setMouseNavEnabled,
    state: (): TiffTextRegionsEditorState => state,
    dispatch: (action: TiffTextRegionsEditorAction) => act(() => send(action)),
    viewerWidth: (width: number) => {
      overlayWidth = width;
    },
    unmount: () => act(() => root.unmount()),
  };
}

afterEach(() => {
  document.body.replaceChildren();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("TIFF region edit overlay", () => {
  it("delegates 1,600 regions and updates only the handle DOM during viewer events", async () => {
    const listeners = vi.spyOn(SVGSVGElement.prototype, "addEventListener");
    const view = await mount({ count: 1600 });
    try {
      const svg = view.layers[0]?.querySelector("svg");
      expect(
        view.layers.map((layer) => layer.parentElement?.style.pointerEvents),
      ).toEqual(["none", "none"]);
      expect(svg?.querySelectorAll("[data-region-index]")).toHaveLength(1600);
      expect(svg?.querySelector("text")?.textContent).toBe("Region 0");
      expect(
        listeners.mock.calls.filter(
          ([event], index) =>
            event === "pointerdown" && listeners.mock.contexts[index] === svg,
        ),
      ).toHaveLength(1);
      const unselected = view.target('[data-region-index="1599"]');
      await view.pointer(
        view.target('[data-region-index="0"]'),
        "pointerdown",
        15,
        25,
      );
      expect(view.target('[data-region-index="1599"]')).not.toBe(unselected);
      const unchanged = view.target('[data-region-index="1599"]');
      const vertex = view.target('[data-vertex-handle="0"]');
      expect(vertex.getAttribute("r")).toBe("12");

      view.commits.mockClear();
      view.viewerWidth(800);
      for (const event of ["zoom", "pan", "animation", "resize", "open"]) {
        await act(() => view.handlers.get(event)?.());
        expect(view.target('[data-region-index="1599"]')).toBe(unchanged);
      }
      expect(view.commits).not.toHaveBeenCalled();
      expect(vertex.getAttribute("r")).toBe("6");
      expect(
        Number(view.target('[data-midpoint-handle="0"]').getAttribute("r")),
      ).toBeCloseTo(4.2);

      await view.pointer(vertex, "pointerdown", 11, 21);
      await view.pointer(vertex, "pointerup", 11, 21);
      expect(view.state().payload.regions[0]?.polygon[0]).toEqual([10, 20]);
      expect(view.state().isDirty).toBe(false);
      await view.pointer(vertex, "pointerdown", 11, 21);
      await view.pointer(vertex, "pointermove", 21, 25);
      await view.pointer(vertex, "pointerup", 21, 25);
      expect(view.state().payload.regions[0]?.polygon[0]).toEqual([20, 24]);
      expect(view.target('[data-region-index="1599"]')).toBe(unchanged);
    } finally {
      await view.unmount();
    }
    expect(view.handlers.size).toBe(0);
    expect(view.canvas.childElementCount).toBe(0);
  });

  it("selects, translates, inserts a vertex and deselects only on an empty click", async () => {
    const view = await mount({ scale: 1.69 });
    try {
      await view.pointer(
        view.target('[data-region-index="1"]'),
        "pointerdown",
        15,
        25,
      );
      const active = view.target("[data-active-region] polygon");
      expect(view.state().selection).toEqual({ region: 1, vertex: null });
      await view.pointer(active, "pointerdown", 20, 30);
      await view.pointer(active, "pointermove", 25, 35);
      await view.pointer(active, "pointerup", 30, 40);
      expect(view.state().payload.regions[1]?.polygon[0]?.[0]).toBeCloseTo(20);
      expect(view.state().payload.regions[1]?.polygon[0]?.[1]).toBeCloseTo(30);
      expect(view.state().past).toHaveLength(1);
      expect(view.state().coalesce).toBeNull();

      const edge = view.target('[data-midpoint-handle="0"]');
      await view.pointer(edge, "pointerdown", 30, 30);
      await view.pointer(
        view.target("[data-active-region]").closest("svg") ?? edge,
        "pointerup",
        30,
        30,
      );
      expect(view.state().payload.regions[1]?.polygon).toHaveLength(5);
      expect(
        view.target('[data-vertex-handle="1"]').getAttribute("r"),
      ).not.toBeNull();
      expect(view.state().payload.regions[1]?.polygon[1]?.[0]).toBeCloseTo(30);

      await view.pointer(view.element, "pointerdown", 100, 100);
      await view.pointer(view.element, "pointermove", 120, 100);
      await view.pointer(view.element, "pointerup", 100, 100);
      expect(view.state().selection?.region).toBe(1);
      await view.pointer(view.element, "pointerdown", 100, 100);
      await view.pointer(view.element, "pointerup", 103, 100);
      expect(view.state().selection).toBeNull();
    } finally {
      await view.unmount();
    }
  });

  it.each([
    ["[data-vertex-handle='0']", "pointerup"],
    ["[data-midpoint-handle='0']", "lostpointercapture"],
    ["[data-active-region] polygon", "pointercancel"],
  ])(
    "keeps a %s press out of the viewer canvas and restores navigation on %s",
    async (selector, finish) => {
      const view = await mount();
      const canvasPress = vi.fn();
      view.canvas.addEventListener("pointerdown", canvasPress);
      view.canvas.addEventListener("mousedown", canvasPress);
      try {
        const inactive = view.target("[data-region-index='0']");
        await view.pointer(inactive, "mousedown", 15, 25);
        await view.pointer(inactive, "pointerdown", 15, 25);
        expect(canvasPress).not.toHaveBeenCalled();
        expect(view.state().selectedRegions).toEqual([0]);

        const hit = view.target(selector);
        const pressReachedTarget = vi.fn();
        hit.addEventListener("pointerdown", pressReachedTarget);
        await view.pointer(hit, "pointerdown", 15, 25);
        await view.pointer(hit, "mousedown", 15, 25);
        expect(pressReachedTarget).toHaveBeenCalledOnce();
        expect(canvasPress).not.toHaveBeenCalled();
        expect(view.setMouseNavEnabled.mock.calls).toEqual([[false]]);

        const captureTarget = selector.endsWith("polygon")
          ? hit
          : hit.closest("svg");
        if (!captureTarget) throw new Error("Missing pointer capture target");
        expect(captureTarget.setPointerCapture).toHaveBeenCalledWith(1);
        await view.pointer(captureTarget, finish, 15, 25);
        expect(view.setMouseNavEnabled.mock.calls).toEqual([[false], [true]]);
      } finally {
        await view.unmount();
      }
    },
  );

  it("restores navigation when unmounted during a drag", async () => {
    const view = await mount();
    await view.dispatch({ type: "select_region", index: 0 });
    await view.pointer(
      view.target("[data-active-region] polygon"),
      "pointerdown",
      15,
      25,
    );
    await view.unmount();
    expect(view.setMouseNavEnabled.mock.calls).toEqual([[false], [true]]);
  });

  it("shows the handles before OpenSeadragon has laid out the overlay", async () => {
    const view = await mount({ initialOverlayWidth: 0 });
    try {
      await view.dispatch({ type: "select_region", index: 0 });
      expect(
        Number(view.target("[data-vertex-handle='0']").getAttribute("r")),
      ).toBe(3);
      expect(
        Number(view.target("[data-midpoint-handle='0']").getAttribute("r")),
      ).toBeCloseTo(2.1);
    } finally {
      await view.unmount();
    }
  });

  it("drags from a midpoint into a new corner in a single undo step", async () => {
    const view = await mount();
    try {
      await view.dispatch({ type: "select_region", index: 0 });
      const midpoint = view.target("[data-midpoint-handle='0']");
      const captureTarget = midpoint.closest("svg");
      if (!captureTarget) throw new Error("Missing pointer capture target");
      await view.pointer(midpoint, "pointerdown", 20, 20);
      expect(view.state().selection).toEqual({ region: 0, vertex: 1 });
      expect(view.state().payload.regions[0]?.polygon[1]).toEqual([20, 20]);
      expect(captureTarget.setPointerCapture).toHaveBeenCalledWith(1);
      await view.pointer(captureTarget, "pointermove", 20, 8);
      await view.pointer(captureTarget, "pointerup", 22, 6);
      expect(view.state().payload.regions[0]?.polygon).toEqual([
        [10, 20],
        [22, 6],
        [30, 20],
        [30, 40],
        [10, 40],
      ]);
      expect(view.state().past).toHaveLength(1);
      await view.dispatch({ type: "undo" });
      expect(view.state().payload.regions[0]?.polygon).toEqual(polygon);
    } finally {
      await view.unmount();
    }
  });

  it("deletes a right-clicked corner and keeps the triangle intact", async () => {
    const view = await mount();
    try {
      await view.dispatch({ type: "select_region", index: 0 });
      const vertex = view.target("[data-vertex-handle='1']");
      const contextMenu = await view.pointer(vertex, "contextmenu", 30, 20, {
        button: 2,
      });
      expect(contextMenu.defaultPrevented).toBe(true);
      expect(view.state().payload.regions[0]?.polygon).toEqual([
        [10, 20],
        [30, 40],
        [10, 40],
      ]);
      await view.pointer(vertex, "contextmenu", 30, 40, { button: 2 });
      expect(view.state().payload.regions[0]?.polygon).toHaveLength(3);
      expect(view.state().past).toHaveLength(1);
      expect(view.setMouseNavEnabled).not.toHaveBeenCalled();
    } finally {
      await view.unmount();
    }
  });

  it("Shift-clicks static and active polygons into and out of the selection", async () => {
    const view = await mount({ count: 3 });
    try {
      const press = (selector: string, shiftKey: boolean) =>
        view.pointer(view.target(selector), "pointerdown", 15, 25, {
          shiftKey,
        });
      await press("[data-region-index='2']", false);
      await press("[data-region-index='0']", true);
      expect(view.state().selectedRegions).toEqual([0, 2]);
      expect(view.element.querySelectorAll("[data-region-index]")).toHaveLength(
        1,
      );
      expect(
        view.element.querySelectorAll("[data-active-region]"),
      ).toHaveLength(2);
      expect(
        view.element.querySelectorAll(
          "[data-vertex-handle], [data-midpoint-handle]",
        ),
      ).toHaveLength(0);
      expect(
        view
          .target("[data-active-region='2'] polygon")
          .getAttribute("fill-opacity"),
      ).toBe("0.22");
      await press("[data-region-index='1']", true);
      await press("[data-active-region='2'] polygon", true);
      expect(view.state().selectedRegions).toEqual([0, 1]);
      await press("[data-active-region='1'] polygon", false);
      expect(view.state().selectedRegions).toEqual([1]);
      await press("[data-active-region='1'] polygon", true);
      expect(view.state().selectedRegions).toEqual([]);
      expect(view.setMouseNavEnabled).not.toHaveBeenCalled();
    } finally {
      await view.unmount();
    }
  });

  it("erases static and active polygons without intercepting an empty canvas drag", async () => {
    const view = await mount({ count: 3 });
    const canvasPress = vi.fn();
    view.canvas.addEventListener("pointerdown", canvasPress);
    view.canvas.addEventListener("mousedown", canvasPress);
    try {
      await view.dispatch({ type: "select_region", index: 2 });
      await view.dispatch({ type: "set_mode", mode: "eraser" });
      expect(
        document.querySelector("[aria-label='Draw text region']"),
      ).toBeNull();
      expect(view.element.querySelector("[data-vertex-handle]")).toBeNull();
      const inactive = view.target("[data-region-index='0']");
      await view.pointer(inactive, "mousedown", 15, 25);
      await view.pointer(inactive, "pointerdown", 15, 25);
      expect(
        view.state().payload.regions.map((region) => region.reading?.text),
      ).toEqual(["Region 1", "Region 2"]);
      const active = view.target("[data-active-region='1'] polygon");
      await view.pointer(active, "mousedown", 15, 25);
      await view.pointer(active, "pointerdown", 15, 25);
      expect(
        view.state().payload.regions.map((region) => region.reading?.text),
      ).toEqual(["Region 1"]);
      expect(view.state().selectedRegions).toEqual([]);
      expect(view.state().past).toHaveLength(2);
      expect(canvasPress).not.toHaveBeenCalled();

      await view.pointer(view.canvas, "pointerdown", 100, 100);
      await view.pointer(view.canvas, "mousedown", 100, 100);
      await view.pointer(view.canvas, "pointermove", 140, 140);
      await view.pointer(view.canvas, "pointerup", 140, 140);
      expect(canvasPress).toHaveBeenCalledTimes(2);
      expect(view.setMouseNavEnabled).not.toHaveBeenCalled();
    } finally {
      await view.unmount();
    }
  });

  it("draws a box in page pixels and discards a cancelled box", async () => {
    const view = await mount({ scale: 1.69 });
    try {
      await view.dispatch({ type: "set_mode", mode: "draw_box" });
      const target = view.target('[aria-label="Draw text region"]');
      const unselected = view.target('[data-region-index="0"]');
      await view.pointer(target, "pointerdown", 100, 120);
      await view.pointer(target, "pointermove", 149, 164);
      expect(view.state().draft?.kind).toBe("box");
      expect(view.target('[data-region-index="0"]')).toBe(unselected);
      await view.pointer(target, "pointercancel", 150, 160);
      expect(view.state().draft).toBeNull();
      expect(view.state().payload.regions).toHaveLength(2);

      await view.pointer(target, "pointerdown", 100, 120);
      await view.pointer(target, "pointerup", 150, 160);
      const drawn = view.state().payload.regions[2]?.polygon;
      expect(drawn).toHaveLength(4);
      expect(drawn?.[0]?.[0]).toBeCloseTo(100);
      expect(drawn?.[0]?.[1]).toBeCloseTo(120);
      expect(drawn?.[2]?.[0]).toBeCloseTo(150);
      expect(drawn?.[2]?.[1]).toBeCloseTo(160);
      expect(view.setMouseNavEnabled.mock.calls).toEqual([
        [false],
        [true],
        [false],
        [true],
      ]);
    } finally {
      await view.unmount();
    }
  });

  it.each(["near first vertex", "double click"])(
    "closes a polygon by %s",
    async (finish) => {
      const view = await mount({ scale: 1.69 });
      try {
        await view.dispatch({ type: "set_mode", mode: "draw_polygon" });
        const target = view.target('[aria-label="Draw text region"]');
        await view.pointer(target, "pointerdown", 100, 100);
        await view.pointer(target, "pointerdown", 200, 100);
        await view.pointer(target, "pointermove", 200, 200);
        expect(
          Number(view.target("[stroke-dasharray]").getAttribute("x1")),
        ).toBeCloseTo(200);
        await view.pointer(target, "pointerdown", 200, 200);
        if (finish === "double click") {
          await view.pointer(target, "pointerdown", 200, 200);
          await view.pointer(target, "dblclick", 200, 200);
        } else {
          await view.pointer(target, "pointerdown", 104, 100);
        }
        expect(view.state().draft).toBeNull();
        expect(view.state().payload.regions[2]?.polygon).toHaveLength(3);
      } finally {
        await view.unmount();
      }
    },
  );
});
