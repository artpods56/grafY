// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeProvider } from "@/components/theme";
import { StudioThemeSpike } from "./StudioThemeSpike";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

beforeEach(() => {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  });
});

const mountedRoots = new Set<ReturnType<typeof createRoot>>();

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  document.body.replaceChildren();
});

async function renderSpike() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  await act(async () => {
    root.render(
      <ThemeProvider>
        <StudioThemeSpike />
      </ThemeProvider>,
    );
  });
  return container;
}

describe("StudioThemeSpike", () => {
  it("renders all three app slices and lets the user switch theme presets", async () => {
    const container = await renderSpike();
    const headings = [...container.querySelectorAll("h2")].map(
      (node) => node.textContent,
    );
    expect(headings).toEqual([
      "1 · Project chrome",
      "2 · Projects list",
      "3 · Panel, kit controls & canvas harmony",
    ]);

    const radios = [
      ...container.querySelectorAll<HTMLElement>('[role="radio"]'),
    ];
    const emerald = radios.find((el) =>
      el.textContent?.includes("Studio (Emerald)"),
    );
    expect(emerald).toBeTruthy();
    await act(async () => emerald?.click());
    expect(emerald?.getAttribute("aria-checked")).toBe("true");
  });
});
