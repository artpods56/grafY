// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { UiKitSpike } from "./UiKitSpike";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

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
    root.render(<UiKitSpike />);
  });
  return container;
}

const SECTIONS = [
  "Button",
  "IconButton",
  "ButtonLink",
  "Field · TextInput · TextArea",
  "Select",
  "Checkbox · Switch",
  "SegmentedControl",
  "Slider",
  "ColorWell · ColorField",
  "Notice",
  "Surface",
  "Menu",
  "Dialog",
];

describe("UiKitSpike", () => {
  it("renders a section for every kit part", async () => {
    const container = await renderSpike();
    const headings = [...container.querySelectorAll("h2")].map(
      (node) => node.textContent,
    );
    expect(headings).toEqual(SECTIONS);
  });

  it("paints its root with a stylesheet rather than leaving it bare", async () => {
    const container = await renderSpike();
    const root = container.firstElementChild as HTMLElement;
    expect(root.className.trim()).not.toBe("");
  });

  it("draws each button variant at each of the five sizes", async () => {
    const container = await renderSpike();
    const buttons = [...container.querySelectorAll("button")].map(
      (node) => node.textContent ?? "",
    );
    // 7 variants × 5 sizes, plus the state samples below the grid.
    for (const variant of ["primary", "secondary", "soft", "ghost", "dashed"]) {
      const count = buttons.filter((text) => text.includes(variant)).length;
      expect(
        count,
        `variant ${variant} appears ${count} times`,
      ).toBeGreaterThanOrEqual(5);
    }
  });
});
