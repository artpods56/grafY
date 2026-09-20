// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  SIDE_PANEL_MAX_WIDTH,
  clampSidePanelWidth,
  useWorkbenchSidePanel,
  type WorkbenchSidePanelState,
} from "./workbench-side-panel-state";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots: ReturnType<typeof createRoot>[] = [];
let store = new Map<string, string>();
let viewportWidth = 1_600;

/** Mounts the hook and hands back a reader, so assertions see the live state. */
async function mountPanel(): Promise<() => WorkbenchSidePanelState> {
  let latest!: WorkbenchSidePanelState;
  function Probe(): React.ReactElement {
    latest = useWorkbenchSidePanel();
    return React.createElement("span");
  }
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  await React.act(async () => {
    root.render(React.createElement(Probe));
  });
  return () => latest;
}

beforeEach(() => {
  store = new Map();
  viewportWidth = 1_600;
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => {
      store.set(key, value);
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => store.clear(),
  });
  vi.stubGlobal(
    "matchMedia",
    vi.fn(
      (query: string): MediaQueryList =>
        ({
          get matches() {
            const minWidth = /min-width:\s*(\d+)px/.exec(query)?.[1];
            return minWidth
              ? viewportWidth >= Number(minWidth)
              : viewportWidth < Number.MAX_SAFE_INTEGER;
          },
          media: query,
          onchange: null,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
          addListener: vi.fn(),
          removeListener: vi.fn(),
          dispatchEvent: vi.fn(),
        }) satisfies MediaQueryList,
    ),
  );
});

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.replaceChildren();
  document.documentElement.removeAttribute("data-side-panel");
  document.documentElement.style.removeProperty(
    "--grafy-side-panel-expanded-width",
  );
  vi.unstubAllGlobals();
});

describe("clampSidePanelWidth", () => {
  it("keeps the panel between a usable minimum and maximum", () => {
    expect(clampSidePanelWidth(100)).toBe(240);
    expect(clampSidePanelWidth(4_000)).toBe(SIDE_PANEL_MAX_WIDTH);
    expect(clampSidePanelWidth(Number.NaN)).toBe(276);
  });
});

describe("useWorkbenchSidePanel", () => {
  it("opens on a wide canvas and mirrors the state onto the document", async () => {
    const current = await mountPanel();

    expect(current().docked).toBe(true);
    expect(current().open).toBe(true);
    expect(document.documentElement.dataset.sidePanel).toBe("open");
  });

  it("keeps a stored choice over the default", async () => {
    store.set("grafy-side-panel-open", "0");
    const current = await mountPanel();

    expect(current().open).toBe(false);
    expect(document.documentElement.dataset.sidePanel).toBe("closed");
  });

  it("docks without auto-opening on a canvas too narrow to spare a pane", async () => {
    viewportWidth = 1_200;
    const current = await mountPanel();

    expect(current().docked).toBe(true);
    expect(current().open).toBe(false);
  });

  it("persists the opened view and the panel width", async () => {
    const current = await mountPanel();

    await React.act(async () => {
      current().setView("templates");
    });
    await React.act(async () => {
      current().setWidth(333.6);
    });

    expect(store.get("grafy-side-panel-view")).toBe("templates");
    expect(store.get("grafy-side-panel-width")).toBe("334");
    expect(current().width).toBe(334);
  });

  it("slides over a narrow canvas and never persists the slide-over", async () => {
    viewportWidth = 900;
    const current = await mountPanel();

    expect(current().docked).toBe(false);
    expect(current().open).toBe(false);

    await React.act(async () => {
      current().setOpen(true);
    });
    expect(current().open).toBe(true);
    expect(store.has("grafy-side-panel-open")).toBe(false);
  });
});
