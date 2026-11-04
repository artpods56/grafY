// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Checkbox, type CheckboxSize } from "./checkbox";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mountedRoots = new Set<ReturnType<typeof createRoot>>();

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  document.body.replaceChildren();
});

async function mount(element: React.ReactElement) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  await act(async () => root.render(element));
  return container;
}

function box(container: HTMLElement): HTMLElement {
  const el = container.querySelector<HTMLElement>('[role="checkbox"]');
  if (!el) throw new Error("expected a checkbox");
  return el;
}

const sizes: CheckboxSize[] = ["dense", "sm", "md"];

describe("Checkbox", () => {
  it("draws one ticked box and says so", async () => {
    const container = await mount(
      <Checkbox checked label="Include header" onCheckedChange={() => {}} />,
    );
    expect(container.querySelectorAll('[role="checkbox"]')).toHaveLength(1);
    expect(box(container).getAttribute("aria-checked")).toBe("true");
    expect(container.textContent).toContain("Include header");
  });

  it("toggles from the label text, not only from the box", async () => {
    const onCheckedChange = vi.fn();
    const container = await mount(
      <Checkbox
        checked={false}
        label="Include header"
        onCheckedChange={onCheckedChange}
      />,
    );
    const label = Array.from(container.querySelectorAll("span")).find((span) =>
      span.textContent?.includes("Include header"),
    );
    if (!label) throw new Error("expected the label text");

    await act(async () => label.click());
    expect(onCheckedChange).toHaveBeenCalledTimes(1);
    expect(onCheckedChange).toHaveBeenCalledWith(true);
  });

  it("points its accessible name at the label text", async () => {
    const container = await mount(
      <Checkbox
        checked={false}
        label="Include header"
        onCheckedChange={() => {}}
      />,
    );
    const labelId = box(container).getAttribute("aria-labelledby");
    expect(labelId).toBeTruthy();
    expect(container.querySelector(`span[id="${labelId}"]`)?.textContent).toBe(
      "Include header",
    );
  });

  it.each(sizes)("keeps exactly one control at size %s", async (size) => {
    const container = await mount(
      <Checkbox
        checked={false}
        label="Grid"
        size={size}
        onCheckedChange={() => {}}
      />,
    );
    expect(container.querySelectorAll('[role="checkbox"]')).toHaveLength(1);
    // The tick is drawn, not a native box, so it must not add a second control.
    expect(
      container.querySelectorAll("input[type='checkbox']:not([type='hidden'])"),
    ).toHaveLength(1);
  });

  it("does nothing when disabled", async () => {
    const onCheckedChange = vi.fn();
    const container = await mount(
      <Checkbox
        checked={false}
        label="Grid"
        disabled
        onCheckedChange={onCheckedChange}
      />,
    );
    const control = box(container);
    expect(control.hasAttribute("data-disabled")).toBe(true);
    await act(async () => control.click());
    expect(onCheckedChange).not.toHaveBeenCalled();
  });

  it("keeps canvas pointer classes on the row", async () => {
    const container = await mount(
      <Checkbox
        checked={false}
        label="Grid"
        className="nodrag nopan"
        onCheckedChange={() => {}}
      />,
    );
    const root = container.querySelector("label");
    expect(root?.className).toContain("nodrag");
    expect(root?.className).toContain("nopan");
  });
});
