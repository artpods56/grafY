import { afterEach, describe, expect, it, vi } from "vitest";

import type { CellViewportApi } from "../cell-canvas/cell-contracts";
import {
  createViewportHandleFromCellApi,
  defaultCapabilitiesForEngine,
  readCanvasEnginePreference,
  WORKBENCH_CANVAS_ENGINE_STORAGE_KEY,
  writeCanvasEnginePreference,
} from "./canvas-surface-port";

function memoryStorage() {
  const entries = new Map<string, string>();
  return {
    getItem: (key: string) => entries.get(key) ?? null,
    setItem: (key: string, value: string) => {
      entries.set(key, value);
    },
  };
}

describe("canvas engine preference", () => {
  afterEach(() => vi.unstubAllGlobals());

  function expectStorageFallback() {
    expect(readCanvasEnginePreference()).toBe("cell-canvas");
    expect(() => writeCanvasEnginePreference("react-flow")).not.toThrow();
  }

  it("falls back outside the browser", () => {
    vi.stubGlobal("window", undefined);
    expectStorageFallback();
  });

  it("falls back when localStorage is missing", () => {
    vi.stubGlobal("window", {});
    expectStorageFallback();
  });

  it("falls back when accessing localStorage throws", () => {
    vi.stubGlobal("window", {
      get localStorage() {
        throw new Error("Storage access denied");
      },
    });
    expectStorageFallback();
  });

  it("handles storage methods throwing", () => {
    const storage = {
      getItem() {
        throw new Error("Storage read denied");
      },
      setItem() {
        throw new Error("Storage write denied");
      },
    };

    expect(readCanvasEnginePreference(storage)).toBe("cell-canvas");
    expect(() =>
      writeCanvasEnginePreference("react-flow", storage),
    ).not.toThrow();
  });

  it("roundtrips a preference through injected storage", () => {
    const storage = memoryStorage();
    expect(readCanvasEnginePreference(storage)).toBe("cell-canvas");

    writeCanvasEnginePreference("react-flow", storage);
    expect(storage.getItem(WORKBENCH_CANVAS_ENGINE_STORAGE_KEY)).toBe(
      "react-flow",
    );
    expect(readCanvasEnginePreference(storage)).toBe("react-flow");

    writeCanvasEnginePreference("cell-canvas", storage);
    expect(readCanvasEnginePreference(storage)).toBe("cell-canvas");
  });

  it("roundtrips a preference through window.localStorage", () => {
    const storage = memoryStorage();
    vi.stubGlobal("window", { localStorage: storage });

    writeCanvasEnginePreference("react-flow");
    expect(readCanvasEnginePreference()).toBe("react-flow");

    writeCanvasEnginePreference("cell-canvas");
    expect(storage.getItem(WORKBENCH_CANVAS_ENGINE_STORAGE_KEY)).toBe(
      "cell-canvas",
    );
    expect(readCanvasEnginePreference()).toBe("cell-canvas");
  });

  it("honors explicit null storage", () => {
    const storage = memoryStorage();
    vi.stubGlobal("window", { localStorage: storage });
    writeCanvasEnginePreference("react-flow");

    expect(readCanvasEnginePreference(null)).toBe("cell-canvas");
    writeCanvasEnginePreference("cell-canvas", null);
    expect(readCanvasEnginePreference()).toBe("react-flow");
  });

  it("falls back when storage contains an unknown engine", () => {
    const storage = memoryStorage();
    storage.setItem(WORKBENCH_CANVAS_ENGINE_STORAGE_KEY, "unknown-engine");
    expect(readCanvasEnginePreference(storage)).toBe("cell-canvas");
  });
});

it("adapts all viewport operations from the cell API", () => {
  const api = {
    viewport: { x: 12, y: 24, zoom: 0.5 },
    fitRect: vi.fn(),
    screenToWorld: vi.fn(() => ({ x: 8, y: 4 })),
    worldToScreen: vi.fn(() => ({ x: 16, y: 26 })),
    zoomBy: vi.fn(),
    zoomAtCenter: vi.fn(),
    viewAt: vi.fn(() => ({ x: 0, y: 0, zoom: 1 })),
  } satisfies CellViewportApi;
  const handle = createViewportHandleFromCellApi(api);
  const bounds = { x: 32, y: 16, width: 480, height: 320 };

  expect(handle.getViewport()).toEqual({ x: 12, y: 24, zoom: 0.5 });
  api.viewport = { x: 18, y: 36, zoom: 1 };
  expect(handle.getViewport()).toEqual({ x: 18, y: 36, zoom: 1 });

  handle.fitBounds(bounds, 0.2, 1.25);
  expect(api.fitRect).toHaveBeenCalledWith(bounds, 0.2, 1.25);

  expect(handle.screenToWorld(16, 26)).toEqual({ x: 8, y: 4 });
  expect(api.screenToWorld).toHaveBeenCalledWith(16, 26);

  expect(handle.worldToScreen({ x: 8, y: 4 })).toEqual({ x: 16, y: 26 });
  expect(api.worldToScreen).toHaveBeenCalledWith({ x: 8, y: 4 });

  handle.zoomBy(1.5);
  expect(api.zoomBy).toHaveBeenCalledWith(1.5);
});

it("reports the capabilities of React Flow", () => {
  expect(defaultCapabilitiesForEngine("react-flow")).toEqual({
    supportsGroupDrag: true,
    supportsCellResize: false,
    supportsDockedJoins: false,
    supportsRemoteCursors: true,
    supportsUnderCardsAnnotations: true,
  });
});

it("reports the capabilities of the cell canvas", () => {
  expect(defaultCapabilitiesForEngine("cell-canvas")).toEqual({
    supportsGroupDrag: true,
    supportsCellResize: true,
    supportsDockedJoins: true,
    supportsRemoteCursors: true,
    supportsUnderCardsAnnotations: true,
  });
});
