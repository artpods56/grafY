// @vitest-environment jsdom

import { act, type ComponentProps, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { MapOptions } from "maplibre-gl";
import { SWRConfig } from "swr";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { GeoRenderDescriptor } from "@/lib/api";

import { GeoMapArtifactRenderer } from "../geo-map-artifact-renderer";
import { GeoMapPreview } from "./GeoMapPreview";

const map = vi.hoisted(() => ({
  construct: vi.fn<(options: MapOptions) => void>(),
  addControl: vi.fn(),
  fitBounds: vi.fn(),
  remove: vi.fn(),
  resize: vi.fn(),
  zoomIn: vi.fn(),
  zoomOut: vi.fn(),
  resetNorthPitch: vi.fn(),
}));

vi.mock("maplibre-gl", () => ({
  default: {
    Map: class {
      constructor(options: MapOptions) {
        map.construct(options);
      }
      addControl = map.addControl;
      fitBounds = map.fitBounds;
      remove = map.remove;
      resize = map.resize;
      zoomIn = map.zoomIn;
      zoomOut = map.zoomOut;
      resetNorthPitch = map.resetNorthPitch;
      on = vi.fn();
      getCanvasContainer = () => document.createElement("div");
    },
    AttributionControl: class {
      readonly options: { compact: boolean };
      constructor(options: { compact: boolean }) {
        this.options = options;
      }
    },
  },
}));

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  useWorkspaceContext: () => ({ workspace: { id: "workspace-1" } }),
}));

const DESCRIPTOR: GeoRenderDescriptor = {
  artifact_id: "map-artifact",
  kind: "map_document",
  basemap: "openstreetmap",
  initial_bounds: [30, 54, 31, 55],
  layers: [
    {
      id: "scan",
      title: "Survey scan",
      visible: true,
      opacity: 1,
      min_zoom: 0,
      max_zoom: 22,
      source: {
        kind: "raster",
        artifact_id: "scan-artifact",
        tilejson_url: "/tiles.json",
        bounds: [30, 54, 31, 55],
        attribution: "Survey office",
      },
      style: {
        kind: "raster",
        opacity: 1,
        brightness_min: 0,
        brightness_max: 1,
        contrast: 0,
        saturation: 0,
        hue: 0,
        resampling: "linear",
      },
    },
  ],
};

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
});

async function mount(view: ReactNode) {
  await act(async () => {
    root.render(
      <SWRConfig
        value={{ provider: () => new Map(), shouldRetryOnError: false }}
      >
        {view}
      </SWRConfig>,
    );
  });
}

function button(name: string, scope: Element = container) {
  return [...scope.querySelectorAll("button")].find(
    (candidate) =>
      (candidate.getAttribute("aria-label") ?? candidate.textContent) === name,
  );
}

async function click(name: string, scope?: Element) {
  const control = button(name, scope);
  if (!control) throw new Error(`Missing button "${name}"`);
  await act(async () => control.click());
}

function mockDescriptorFetch() {
  const fetchMock = vi.fn(async () => Response.json(DESCRIPTOR));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("GeoMapPreview", () => {
  it("offers camera and layer controls in a single canvas-safe strip", async () => {
    await mount(<GeoMapPreview descriptor={DESCRIPTOR} />);

    const controls = container.querySelector('[aria-label="Map controls"]');
    if (!controls) throw new Error("Missing map controls");
    expect([...controls.classList]).toEqual(
      expect.arrayContaining(["nodrag", "nowheel", "nopan"]),
    );
    expect(map.construct).toHaveBeenCalledWith(
      expect.objectContaining({ attributionControl: false }),
    );
    expect(map.addControl).toHaveBeenCalledExactlyOnceWith(
      expect.objectContaining({ options: { compact: true } }),
      "bottom-right",
    );

    await click("Zoom out", controls);
    await click("Zoom in", controls);
    await click("Fit descriptor bounds", controls);
    await click("Reset orientation", controls);
    expect(map.zoomOut).toHaveBeenCalledExactlyOnceWith({ duration: 200 });
    expect(map.zoomIn).toHaveBeenCalledExactlyOnceWith({ duration: 200 });
    expect(map.fitBounds).toHaveBeenCalledExactlyOnceWith(
      [
        [30, 54],
        [31, 55],
      ],
      { padding: 28, maxZoom: 14, duration: 450 },
    );
    expect(map.resetNorthPitch).toHaveBeenCalledExactlyOnceWith({
      duration: 200,
    });

    const layers = button("1 layer", controls);
    const inspector = () =>
      container.querySelector('[aria-label="Map layer inspector"]');
    expect(layers?.getAttribute("aria-expanded")).toBe("false");
    expect(inspector()).toBeNull();
    await click("1 layer", controls);
    expect(layers?.getAttribute("aria-expanded")).toBe("true");
    expect(inspector()?.textContent).toContain("Survey scan");
    await click("1 layer", controls);
    expect(inspector()).toBeNull();
    expect(button("Unload interactive map", controls)).toBeUndefined();

    const shell = container.querySelector<HTMLElement>("[data-grafy-geo-map]");
    if (!shell) throw new Error("Missing map shell");
    expect(shell.draggable).toBe(false);
    const dragStart = new Event("dragstart", {
      bubbles: true,
      cancelable: true,
    });
    shell.dispatchEvent(dragStart);
    expect(dragStart.defaultPrevented).toBe(true);
  });

  it("fills its host and resizes MapLibre when the container changes size", async () => {
    const observe = vi.fn();
    const disconnect = vi.fn();
    let notifyResize: (() => void) | undefined;
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          notifyResize = callback;
        }
        observe = observe;
        disconnect = disconnect;
      },
    );

    await mount(<GeoMapPreview descriptor={DESCRIPTOR} />);

    expect(
      container.querySelector<HTMLElement>("[data-grafy-geo-map]")?.style
        .height,
    ).toBe("100%");
    expect(observe).toHaveBeenCalledExactlyOnceWith(
      map.construct.mock.calls[0]?.[0].container,
    );
    act(() => notifyResize?.());
    expect(map.resize).toHaveBeenCalledTimes(1);

    act(() => root.render(null));
    expect(disconnect).toHaveBeenCalledTimes(1);
    expect(map.remove).toHaveBeenCalledTimes(1);
  });
});

describe("GeoMapArtifactRenderer", () => {
  type LoadProps = Pick<
    ComponentProps<typeof GeoMapArtifactRenderer>,
    "presentation" | "autoLoad"
  >;

  it.each([
    { presentation: "canvas" },
    { autoLoad: true },
  ] satisfies LoadProps[])(
    "loads immediately for %j without an unload control",
    async (props) => {
      const fetchMock = mockDescriptorFetch();
      await mount(
        <GeoMapArtifactRenderer artifact={DESCRIPTOR} mode="map" {...props} />,
      );

      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(map.construct).toHaveBeenCalledTimes(1);
      expect(button("Load interactive map")).toBeUndefined();
      expect(button("Unload interactive map")).toBeUndefined();
    },
  );

  it("loads an inspector map on demand and returns to the gate on unload", async () => {
    const fetchMock = mockDescriptorFetch();
    await mount(<GeoMapArtifactRenderer artifact={DESCRIPTOR} mode="map" />);

    expect(fetchMock).not.toHaveBeenCalled();
    expect(map.construct).not.toHaveBeenCalled();
    await click("Load interactive map");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(map.construct).toHaveBeenCalledTimes(1);
    await click("Unload interactive map");
    expect(map.remove).toHaveBeenCalledTimes(1);
    expect(button("Load interactive map")).toBeDefined();
  });
});
