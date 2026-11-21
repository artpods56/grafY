// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { GeoRenderDescriptor } from "@/lib/api";
import { TiffTextArtifact } from "./artifact-renderers/tiff-text-renderer";
import { createTiffOverlay, TiffArtifactView } from "./TiffArtifactView";

vi.mock("@/features/workspaces/WorkspaceLayout", () => ({
  useWorkspaceContext: () => ({ workspace: { id: "test-space" } }),
}));

vi.mock("./geo-map/GeoMapPreview", () => ({
  GeoMapPreview: ({ descriptor }: { descriptor: GeoRenderDescriptor }) => (
    <div aria-label="Interactive map">{descriptor.artifact_id}</div>
  ),
}));

vi.mock("@/components/ui/button", () => ({
  IconButton: ({
    label,
    pressed,
    ...props
  }: React.ComponentProps<"button"> & {
    label: string;
    pressed?: boolean;
  }) => <button aria-label={label} aria-pressed={pressed} {...props} />,
}));

const open = vi.hoisted(() => ({
  handlers: new Map<string, () => void>(),
  imageRectangle: vi.fn((x: number, y: number, w: number, h: number) => ({
    x: x / 800,
    y: y / 800,
    width: w / 800,
    height: h / 800,
  })),
  overlay: vi.fn((element: Element, _placement: unknown) => {
    document.body.append(element);
  }),
  fitBounds: vi.fn(),
  viewerStart: vi.fn(),
  viewerDestroy: vi.fn(() => open.handlers.clear()),
  options: [] as Record<string, unknown>[],
  viewers: [] as {
    viewport: {
      state: { width: number; height: number; zoom: number };
      bounds: () => { x: number; y: number; width: number; height: number };
      applyConstraints: ReturnType<typeof vi.fn>;
    };
  }[],
  observers: [] as { trigger: () => void; disconnected: boolean }[],
  Point: class OsdPoint {
    readonly x: number;
    readonly y: number;

    constructor(x: number, y: number) {
      this.x = x;
      this.y = y;
    }

    equals(other: { x?: number; y?: number } | null) {
      return other !== null && this.x === other?.x && this.y === other?.y;
    }
  },
  /**
   * The geometry OpenSeadragon keeps, in its own units: the visible width is
   * `1 / zoom`, so a viewport unit costs `container width x zoom` screen pixels.
   * `resize` re-fits the bounds it was given into the new frame, which is the
   * magnification the card has to undo. The page is one unit wide.
   */
  viewport: () => {
    const state = { width: 240, height: 180, zoom: 2, cx: 0.3, cy: 0.3 };
    const bounds = () => {
      const width = 1 / state.zoom;
      const height = width / (state.width / state.height);
      return {
        x: state.cx - width / 2,
        y: state.cy - height / 2,
        width,
        height,
      };
    };
    const fit = (rect: {
      x: number;
      y: number;
      width: number;
      height: number;
    }) => {
      state.zoom = 1 / rect.width;
      state.cx = rect.x + rect.width / 2;
      state.cy = rect.y + rect.height / 2;
    };
    const viewport = {
      state,
      bounds,
      applyConstraints: vi.fn(),
      getContainerSize: () => new open.Point(state.width, state.height),
      getBounds: () => bounds(),
      getZoom: () => state.zoom,
      fitBounds: (
        rect: { x: number; y: number; width: number; height: number },
        immediately?: boolean,
      ) => {
        open.fitBounds(rect, immediately);
        fit(rect);
        return viewport;
      },
      resize: (size: { x: number; y: number }) => {
        const current = bounds();
        state.width = size.x;
        state.height = size.y;
        fit(current);
        return viewport;
      },
      zoomTo: (zoom: number) => {
        state.zoom = zoom;
        return viewport;
      },
      panBy: (delta: { x: number; y: number }) => {
        state.cx += delta.x;
        state.cy += delta.y;
        return viewport;
      },
    };
    return viewport;
  },
}));

vi.mock("openseadragon", () => ({
  default: Object.assign(
    (options: Record<string, unknown>) => {
      open.viewerStart();
      open.options.push(options);
      const viewport = open.viewport();
      const viewer = {
        addHandler: (name: string, handler: () => void) =>
          open.handlers.set(name, handler),
        viewport,
        world: {
          getItemAt: () => ({
            imageToViewportRectangle: open.imageRectangle,
            viewerElementToImageCoordinates: (point: {
              x: number;
              y: number;
            }) => point,
          }),
        },
        addOverlay: open.overlay,
        removeOverlay: (element: Element) => element.remove(),
        destroy: open.viewerDestroy,
      };
      open.viewers.push(viewer);
      return viewer;
    },
    {
      Point: open.Point,
    },
  ),
}));

const host = document.createElement("div");
afterEach(() => {
  document.body.replaceChildren();
  vi.clearAllMocks();
  vi.unstubAllGlobals();
  open.options.length = 0;
  open.viewers.length = 0;
  open.observers.length = 0;
});

type StubObserver = {
  trigger: () => void;
  disconnected: boolean;
};

class StubResizeObserver implements StubObserver {
  disconnected = false;
  private readonly callback: ResizeObserverCallback;

  constructor(callback: ResizeObserverCallback) {
    this.callback = callback;
    open.observers.push(this);
  }

  trigger(): void {
    this.callback([], this as unknown as ResizeObserver);
  }

  observe(): void {}

  disconnect(): void {
    this.disconnected = true;
  }
}

// jsdom lays nothing out, so a surface's size is whatever a test says it is.
function sizeTo(element: HTMLElement, width: number, height: number): void {
  Object.defineProperties(element, {
    clientWidth: { configurable: true, writable: true, value: width },
    clientHeight: { configurable: true, writable: true, value: height },
  });
}

async function openedTiffView(georeferenced?: boolean) {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const geoRenderUrl =
    "/api/v1/workspaces/test-space/artifacts/resized-tiff/geo/render";
  const fetchMock = vi.fn(async (url: string) => {
    if (url === geoRenderUrl) {
      return Response.json({
        artifact_id: "resized-tiff",
        kind: "raster_scan",
        basemap: "none",
        initial_bounds: null,
        layers: [],
      } satisfies GeoRenderDescriptor);
    }
    return Response.json({
      width: 800,
      height: 600,
      page_count: 1,
      tile_size: 256,
      min_level: 8,
      max_level: 10,
      tile_format: "png",
      georeferenced,
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("ResizeObserver", StubResizeObserver);
  document.body.append(host);
  const sizes: [number, number][] = [];
  const root = createRoot(host);
  await act(async () =>
    root.render(
      <TiffArtifactView
        workspaceId="test-space"
        artifactId="resized-tiff"
        name="Scan"
        onSize={(width, height) => sizes.push([width, height])}
      />,
    ),
  );
  await act(async () =>
    host.querySelector("img")?.dispatchEvent(new Event("load")),
  );
  await vi.waitFor(() => expect(open.handlers.has("open")).toBe(true));
  await act(async () => {
    open.handlers.get("open")?.();
    open.handlers.get("tile-loaded")?.();
  });
  const surface = host.querySelector<HTMLElement>("[data-tiff-viewport]");
  if (!surface) throw new Error("Tile surface missing");
  sizeTo(surface, 240, 180);
  return { root, surface, sizes, fetchMock, geoRenderUrl };
}

describe("TIFF map mode", () => {
  it.each([false, undefined])(
    "only offers image controls when georeferenced is %s",
    async (georeferenced) => {
      const { root, fetchMock } = await openedTiffView(georeferenced);
      try {
        expect(host.querySelector('[aria-label="Show map"]')).toBeNull();
        expect(host.querySelector('[aria-label="Zoom in"]')).not.toBeNull();
        expect(fetchMock).toHaveBeenCalledTimes(1);
      } finally {
        await act(async () => root.unmount());
      }
    },
  );

  it("loads the map immediately and reopens the image when switched back", async () => {
    const { root, fetchMock, geoRenderUrl } = await openedTiffView(true);
    const map = () => host.querySelector('[aria-label="Interactive map"]');
    const toggle = (label: string) => {
      const button = host.querySelector<HTMLButtonElement>(
        `button[aria-label="${label}"]`,
      );
      if (!button) throw new Error(`Missing ${label} button`);
      return button;
    };

    try {
      expect(fetchMock).toHaveBeenCalledTimes(1);
      const mapButton = toggle("Show map");
      expect(mapButton.classList.contains("nodrag")).toBe(true);
      expect(mapButton.classList.contains("nopan")).toBe(true);
      await act(async () => mapButton.click());

      expect(open.viewerDestroy).toHaveBeenCalledTimes(1);
      expect(open.observers[0]?.disconnected).toBe(true);
      expect(host.querySelector("[data-tiff-viewport]")).toBeNull();
      expect(host.querySelector('[aria-label="Zoom in"]')).toBeNull();
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(fetchMock.mock.calls[1]?.[0]).toBe(geoRenderUrl);
      await vi.waitFor(() => expect(map()?.textContent).toBe("resized-tiff"));
      expect(map()?.closest(".nodrag.nowheel.nopan")).not.toBeNull();
      expect(toggle("Show image")).toBe(mapButton);

      await act(async () => toggle("Show image").click());
      expect(map()).toBeNull();
      expect(host.querySelector("[data-tiff-viewport]")).not.toBeNull();
      expect(toggle("Show map")).toBe(mapButton);
      await vi.waitFor(() => expect(open.viewerStart).toHaveBeenCalledTimes(2));
      await act(async () => {
        open.handlers.get("open")?.();
        open.handlers.get("tile-loaded")?.();
      });
      expect(host.textContent).not.toContain("Loading image");
      expect(fetchMock).toHaveBeenCalledTimes(2);
    } finally {
      await act(async () => root.unmount());
    }
  });
});

describe("resizing the card", () => {
  it("grows the view rather than the page, and holds it under the top-left", async () => {
    const { root, surface } = await openedTiffView();
    const viewport = open.viewers[0]?.viewport;
    if (!viewport) throw new Error("Viewer never opened");
    // The page is one viewport unit wide, so it costs surface width x zoom
    // screen pixels, and its top-left is where the view starts on it.
    const pagePixels = () => viewport.state.width * viewport.state.zoom;
    const left = () => viewport.bounds().x;
    const top = () => viewport.bounds().y;
    const observer = open.observers[0];
    if (!observer) throw new Error("Surface never watched for resize");
    // Somewhere in the middle of the page, so holding the corner is a claim the
    // test can actually falsify rather than a coincidence of the page's corner.
    const scale = pagePixels();
    const col = left();
    const row = top();
    expect(scale).toBe(480);
    expect(col).toBeCloseTo(0.05, 6);
    expect(row).toBeCloseTo(0.1125, 6);

    sizeTo(surface, 480, 360);
    act(() => observer.trigger());
    expect(pagePixels()).toBeCloseTo(scale, 6);
    expect(left()).toBeCloseTo(col, 6);
    expect(top()).toBeCloseTo(row, 6);
    expect(viewport.applyConstraints).toHaveBeenCalled();

    sizeTo(surface, 120, 90);
    act(() => observer.trigger());
    expect(pagePixels()).toBeCloseTo(scale, 6);
    expect(left()).toBeCloseTo(col, 6);
    expect(top()).toBeCloseTo(row, 6);

    await act(async () => root.unmount());
    expect(observer.disconnected).toBe(true);
  });

  it("says nothing to the viewer when the surface kept its size", async () => {
    const { root } = await openedTiffView();
    const viewport = open.viewers[0]?.viewport;
    const observer = open.observers[0];
    if (!viewport || !observer) throw new Error("Viewer never opened");

    // An observer reports once as soon as it starts watching.
    act(() => observer.trigger());
    expect(viewport.state.zoom).toBe(2);
    expect(viewport.applyConstraints).not.toHaveBeenCalled();

    await act(async () => root.unmount());
  });

  it("sizes itself by the page and leaves OpenSeadragon no magnifying of its own", async () => {
    const { root, sizes } = await openedTiffView();
    expect(sizes).toEqual([[800, 600]]);
    expect(open.options[0]).toMatchObject({
      autoResize: false,
      minZoomImageRatio: 0.25,
      visibilityRatio: 1,
    });
    await act(async () => root.unmount());
  });
});

it("draws and moves a window in source pixels on a scaled canvas and saves once per drag", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json({
        width: 2400,
        height: 1800,
        page_count: 1,
        tile_size: 256,
        min_level: 8,
        max_level: 10,
        tile_format: "png",
      }),
    ),
  );
  document.body.append(host);
  const root = createRoot(host);
  const onChange = vi.fn();
  const render = (
    col: number,
    row = 50,
    singleCrop = false,
    wholePage = false,
  ) => (
    <TiffArtifactView
      workspaceId="test-space"
      artifactId="pick-tiff"
      name="Map"
      selection={{
        window: { page: 0, col, row, width: 100, height: 100 },
        onChange,
        singleCrop,
        wholePage,
      }}
    />
  );
  try {
    await act(async () => root.render(render(100)));
    await act(async () =>
      host.querySelector("img")?.dispatchEvent(new Event("load")),
    );
    await vi.waitFor(() => expect(open.handlers.has("open")).toBe(true));
    await act(async () => {
      open.handlers.get("open")?.();
      open.handlers.get("tile-loaded")?.();
    });
    const button = host.querySelector<HTMLButtonElement>(
      '[aria-label="Edit detection window"]',
    )!;
    await act(async () => button.click());
    const surface = host.querySelector<HTMLElement>(
      '[aria-label="Draw or move the detection window"]',
    )!;
    Object.defineProperties(surface, {
      getBoundingClientRect: {
        value: () => ({ left: 10, top: 20, width: 1200, height: 900 }),
      },
      clientWidth: { value: 2400 },
      clientHeight: { value: 1800 },
      setPointerCapture: { value: vi.fn() },
      hasPointerCapture: { value: () => false },
    });
    async function pointer(type: string, x: number, y: number) {
      const event = new MouseEvent(type, {
        bubbles: true,
        button: 0,
        clientX: x / 2 + 10,
        clientY: y / 2 + 20,
      });
      Object.defineProperty(event, "pointerId", { value: 1 });
      await act(async () => surface.dispatchEvent(event));
    }

    await pointer("pointerdown", 130, 80);
    await pointer("pointermove", 200, 100);
    const rect = () =>
      document.querySelector('svg[aria-label="Detection window"] rect');
    expect(rect()?.getAttribute("x")).toBe("170");
    expect(onChange).not.toHaveBeenCalled();
    await pointer("pointerup", 200, 100);
    expect(onChange).toHaveBeenCalledExactlyOnceWith({
      page: 0,
      col: 170,
      row: 70,
      width: 100,
      height: 100,
    });

    await act(async () => root.render(render(170, 70)));
    expect(rect()?.getAttribute("x")).toBe("170");
    await pointer("pointerdown", 2200, 1700);
    await pointer("pointermove", 2500, 1900);
    expect(rect()?.getAttribute("width")).toBe("200");
    await pointer("pointercancel", 2500, 1900);
    expect(rect()?.getAttribute("x")).toBe("170");
    expect(onChange).toHaveBeenCalledTimes(1);
    await pointer("pointerdown", 2200, 1700);
    await pointer("pointerup", 2500, 1900);
    expect(onChange).toHaveBeenLastCalledWith({
      page: 0,
      col: 2200,
      row: 1700,
      width: 200,
      height: 100,
    });
    await pointer("pointerdown", 400, 500);
    await pointer("pointerup", 2000, 1500);
    expect(onChange).toHaveBeenLastCalledWith({
      page: 0,
      col: 400,
      row: 500,
      width: 1600,
      height: 1000,
    });
    expect(onChange).toHaveBeenCalledTimes(3);

    await act(async () => root.render(render(170, 70, true)));
    await pointer("pointerdown", 400, 500);
    await pointer("pointerup", 2000, 1500);
    expect(host.textContent).toContain(
      "Single crop supports up to 1,000,000 pixels",
    );
    expect(onChange).toHaveBeenCalledTimes(3);

    await act(async () => root.render(render(170, 70, false, true)));
    expect(rect()).toBeNull();
    expect(
      host.querySelector('[aria-label="Edit detection window"]'),
    ).toBeNull();
    expect(open.viewerStart).toHaveBeenCalledTimes(1);
  } finally {
    await act(async () => root.unmount());
  }
});

it("opens the source TIFF page and draws offset polygons in full-image pixels", async () => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  const response = vi.fn(async (url: string) => {
    if (url === "/text-regions") {
      return Response.json({
        source: { artifact_id: "source-tiff" },
        window: { page: 1, col: 300, row: 175, width: 100, height: 50 },
        regions: [
          {
            polygon: [
              [301, 186],
              [320, 179],
              [325, 190],
              [305, 197],
            ],
          },
        ],
      });
    }
    expect(url).toContain("/artifacts/source-tiff/image/info?page=1");
    return Response.json({
      width: 800,
      height: 600,
      page_count: 3,
      tile_size: 256,
      min_level: 8,
      max_level: 10,
      tile_format: "png",
    });
  });
  vi.stubGlobal("fetch", response);
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => {
      root.render(
        <TiffTextArtifact
          workspaceId="test-space"
          url="/text-regions"
          height={300}
        />,
      );
    });
    await vi.waitFor(() => expect(response).toHaveBeenCalledTimes(2));
    const thumbnail = host.querySelector("img");
    expect(thumbnail?.getAttribute("src")).toContain(
      "/artifacts/source-tiff/image/thumbnail",
    );
    await act(async () => thumbnail?.dispatchEvent(new Event("load")));
    await vi.waitFor(() => expect(open.handlers.has("open")).toBe(true));
    await act(async () => {
      open.handlers.get("open")?.();
      open.handlers.get("tile-loaded")?.();
    });

    expect(open.overlay).toHaveBeenCalledWith(expect.any(HTMLDivElement), {
      x: 0,
      y: 0,
      width: 1,
      height: 0.75,
    });
    expect(open.fitBounds).toHaveBeenCalledWith(
      { x: 0.375, y: 0.21875, width: 0.125, height: 0.0625 },
      true,
    );
    const svg = document.querySelector(
      'svg[aria-label="1 detected text regions"]',
    );
    expect(svg?.getAttribute("viewBox")).toBe("0 0 800 600");
    expect(svg?.querySelector("polygon")?.getAttribute("points")).toBe(
      "301,186 320,179 325,190 305,197",
    );
  } finally {
    await act(async () => root.unmount());
  }
});

it("inspects OCR text on the source polygon by pointer or keyboard", () => {
  const select = vi.fn();
  const layer = createTiffOverlay(
    120,
    90,
    [
      [
        [12, 15],
        [56, 15],
        [50, 25],
      ],
      [
        [62, 15],
        [96, 15],
        [85, 25],
      ],
    ],
    { readings: ["Бѣлыничи", null], onSelect: select },
  );
  const polygon = layer.querySelector('[role="button"][aria-label="Бѣлыничи"]');
  expect(polygon?.getAttribute("points")).toBe("12,15 56,15 50,25");
  const label = layer.querySelector("text");
  expect(label?.textContent).toBe("Бѣлыничи");
  expect(label?.getAttribute("x")).toBe("12");
  expect(label?.getAttribute("y")).toBe("15");
  expect(label?.getAttribute("fill")).toBe("darkorange");
  expect(label?.getAttribute("dominant-baseline")).toBe("auto");
  // Half the region's 10-pixel depth, and no turn: its longest edge is level.
  expect(Number(label?.getAttribute("font-size"))).toBeCloseTo(4, 5);
  expect(label?.getAttribute("transform")).toBeNull();
  expect(layer.querySelectorAll("text")).toHaveLength(1);
  polygon?.dispatchEvent(new MouseEvent("click"));
  expect(select).toHaveBeenCalledWith("Бѣлыничи");
  layer
    .querySelector('[role="button"][aria-label="No text recognized"]')
    ?.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
  expect(select).toHaveBeenLastCalledWith("No text recognized");
});

it("writes a reading along the tilt of the region it was recognized in", () => {
  const layer = createTiffOverlay(
    400,
    300,
    [
      [
        [301, 186],
        [320, 179],
        [325, 190],
        [305, 197],
      ],
    ],
    { readings: ["Глаголем"], onSelect: () => undefined },
  );
  const label = layer.querySelector("text");
  // The box runs up to the right, so the word does too, from the corner it
  // starts at rather than from a level line across the box.
  expect(label?.getAttribute("x")).toBe("301");
  expect(label?.getAttribute("y")).toBe("186");
  expect(label?.getAttribute("transform")).toBe("rotate(-20.22 301 186)");
  expect(Number(label?.getAttribute("font-size"))).toBeCloseTo(4.82, 2);
});

it("turns a reading right side up when its region was found backwards", () => {
  const layer = createTiffOverlay(
    400,
    300,
    [
      [
        [325, 190],
        [305, 197],
        [301, 186],
        [320, 179],
      ],
    ],
    { readings: ["Глаголем"], onSelect: () => undefined },
  );
  const label = layer.querySelector("text");
  // The same quadrangle entered from another corner: the word still starts at
  // the left end of the top edge and tilts up to the right, not down.
  expect(label?.getAttribute("x")).toBe("301");
  expect(label?.getAttribute("y")).toBe("186");
  expect(label?.getAttribute("transform")).toBe("rotate(-20.22 301 186)");
});
