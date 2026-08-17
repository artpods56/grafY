// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeProvider, useTheme } from "./theme";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mountedRoots = new Set<Root>();
const storage = new Map<string, string>();
const localStorageStub = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => {
    storage.set(key, value);
  },
  removeItem: (key: string) => {
    storage.delete(key);
  },
  clear: () => storage.clear(),
  key: (index: number) => [...storage.keys()][index] ?? null,
  get length() {
    return storage.size;
  },
};

function Probe() {
  const { preference, resolved, cycleTheme } = useTheme();
  return (
    <div>
      <output data-testid="preference">{preference}</output>
      <output data-testid="resolved">{resolved}</output>
      <button type="button" onClick={cycleTheme}>
        Cycle
      </button>
    </div>
  );
}

function stubMatchMedia(matches: boolean) {
  const listeners = new Set<EventListener>();
  const mediaQuery = {
    matches,
    media: "(prefers-color-scheme: dark)",
    onchange: null,
    addEventListener: ((_type: string, listener: EventListener) => {
      listeners.add(listener);
    }) as MediaQueryList["addEventListener"],
    removeEventListener: ((_type: string, listener: EventListener) => {
      listeners.delete(listener);
    }) as MediaQueryList["removeEventListener"],
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
    setMatches(next: boolean) {
      mediaQuery.matches = next;
      for (const listener of listeners) listener(new Event("change"));
    },
  };
  vi.stubGlobal("matchMedia", vi.fn(() => mediaQuery));
  return mediaQuery;
}

beforeEach(() => {
  storage.clear();
  vi.stubGlobal("localStorage", localStorageStub);
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: localStorageStub,
  });
  document.documentElement.style.removeProperty("color-scheme");
  delete document.documentElement.dataset.theme;
});

afterEach(async () => {
  for (const root of mountedRoots) {
    await React.act(async () => root.unmount());
  }
  mountedRoots.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  document.body.replaceChildren();
  storage.clear();
  document.documentElement.style.removeProperty("color-scheme");
  delete document.documentElement.dataset.theme;
});

async function renderTheme() {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  await React.act(async () =>
    root.render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    ),
  );
  return container;
}

describe("ThemeProvider", () => {
  it("pins a single dark color-scheme when following a dark OS preference", async () => {
    stubMatchMedia(true);
    const container = await renderTheme();

    expect(container.querySelector("[data-testid=preference]")?.textContent).toBe(
      "system",
    );
    expect(container.querySelector("[data-testid=resolved]")?.textContent).toBe(
      "dark",
    );
    expect(document.documentElement.style.colorScheme).toBe("dark");
    expect(document.documentElement.dataset.theme).toBe("dark");
  });

  it("cycles system to an explicit light scheme so token fills can resolve", async () => {
    stubMatchMedia(true);
    const container = await renderTheme();
    const button = container.querySelector("button");
    expect(button).not.toBeNull();

    await React.act(async () => button!.click());

    expect(container.querySelector("[data-testid=preference]")?.textContent).toBe(
      "light",
    );
    expect(container.querySelector("[data-testid=resolved]")?.textContent).toBe(
      "light",
    );
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("grafy-theme")).toBe("light");
  });

  it("keeps a single scheme when returning to system from dark", async () => {
    stubMatchMedia(false);
    window.localStorage.setItem("grafy-theme", "dark");
    const container = await renderTheme();
    const button = container.querySelector("button");

    await React.act(async () => button!.click());

    expect(container.querySelector("[data-testid=preference]")?.textContent).toBe(
      "system",
    );
    expect(container.querySelector("[data-testid=resolved]")?.textContent).toBe(
      "light",
    );
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
  });
});
