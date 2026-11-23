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
  "In context",
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
  "Unused & regression guards",
];

const BUTTON_VARIANTS = [
  "primary",
  "secondary",
  "soft",
  "ghost",
  "danger",
  "plain",
  "dashed",
] as const;

const BUTTON_SIZES = ["xs", "sm", "md", "lg", "text"] as const;

function section(container: HTMLElement, id: string) {
  const node = container.querySelector(`section#${id}`);
  expect(node, `section #${id}`).not.toBeNull();
  return node as HTMLElement;
}

function textOf(node: HTMLElement) {
  return node.textContent ?? "";
}

describe("UiKitSpike", () => {
  it("renders a section for every kit part, in context first", async () => {
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

  it("shows each context frame at the pixel width it imitates", async () => {
    const container = await renderSpike();
    const context = textOf(section(container, "contexts"));
    for (const spec of ["300px", "360px", "520px"]) {
      expect(context, `frame spec ${spec}`).toContain(spec);
    }
    // Each frame names the row and control sizes it exists to check.
    expect(context).toContain("25px rows");
    expect(context).toContain("28px controls");
    expect(context).toContain("32px controls");
  });

  it("draws each button variant at each of the five sizes", async () => {
    const container = await renderSpike();
    const buttons = [...container.querySelectorAll("button")].map(
      (node) => node.textContent ?? "",
    );
    for (const variant of BUTTON_VARIANTS) {
      // The matrix holds one per size; the state rows and the regression
      // section add more, so this only fails if a size stops rendering.
      const count = buttons.filter((text) => text.includes(variant)).length;
      expect(
        count,
        `variant ${variant} appears ${count} times`,
      ).toBeGreaterThanOrEqual(BUTTON_SIZES.length);
    }
  });

  it("renders the dense segmented control beside the sizes it is measured against", async () => {
    const container = await renderSpike();
    const segmented = section(container, "segmented");
    for (const size of ["md", "sm", "dense"]) {
      const group = segmented.querySelector(
        `[aria-label="Segmented size ${size}"]`,
      );
      expect(group, `segmented size ${size}`).not.toBeNull();
    }
    expect(textOf(segmented)).toContain("dense · 25px well");
  });

  it("marks a field's control invalid rather than only printing the error", async () => {
    const container = await renderSpike();
    const fields = section(container, "fields");
    const invalid = [...fields.querySelectorAll("input, textarea")].filter(
      (node) => node.getAttribute("aria-invalid") === "true",
    );
    // One input and one textarea carry an `error`.
    expect(invalid).toHaveLength(2);
  });

  it("draws an icon button with title={null} without a tooltip attribute", async () => {
    const container = await renderSpike();
    const button = section(container, "icon-buttons").querySelector(
      'button[aria-label="No tooltip — title={null}"]',
    );
    expect(button).not.toBeNull();
    expect(button?.hasAttribute("title")).toBe(false);
  });

  it("keeps both phoneTouch switch states on the page for regression checks", async () => {
    const container = await renderSpike();
    const unused = section(container, "unused");
    const switches = [...unused.querySelectorAll('[role="switch"]')];
    expect(switches.length).toBeGreaterThanOrEqual(4);
    const states = switches.map((node) => node.getAttribute("aria-checked"));
    expect(states).toContain("true");
    expect(states).toContain("false");
    expect(textOf(unused)).toContain("phoneTouch");
    // The guard section keeps the never-used primary icon buttons visible too.
    expect(
      unused.querySelector('button[aria-label="primary disabled"]'),
    ).not.toBeNull();
  });
});
