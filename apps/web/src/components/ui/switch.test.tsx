// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Switch, type SwitchSize } from "./switch";

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

function switchEl(container: HTMLElement): HTMLElement {
  const el = container.querySelector<HTMLElement>('[role="switch"]');
  if (!el) throw new Error("expected a switch");
  return el;
}

const sizes: SwitchSize[] = ["dense", "sm", "md"];

describe("Switch", () => {
  it("draws a labelled switch and reports state through aria-checked", async () => {
    const container = await mount(
      <Switch checked label="Snap to grid" onCheckedChange={() => {}} />,
    );
    const control = switchEl(container);
    expect(control.getAttribute("aria-checked")).toBe("true");
    expect(container.textContent).toContain("Snap to grid");
  });

  it("toggles when the label text is clicked, not only the track", async () => {
    const onCheckedChange = vi.fn();
    const container = await mount(
      <Switch
        checked={false}
        label="Snap to grid"
        onCheckedChange={onCheckedChange}
      />,
    );
    const label = Array.from(container.querySelectorAll("span")).find((span) =>
      span.textContent?.includes("Snap to grid"),
    );
    if (!label) throw new Error("expected the label text");

    await act(async () => label.click());
    expect(onCheckedChange).toHaveBeenCalledWith(true);

    const control = switchEl(container);
    await act(async () =>
      control.dispatchEvent(new PointerEvent("click", { bubbles: true })),
    );
    expect(onCheckedChange).toHaveBeenCalledTimes(2);
  });

  it("points its accessible name at the label text", async () => {
    // A `role="switch"` is not labelable, so the wrapping <label> alone would
    // leave the switch anonymous and a phone user's screen reader would say
    // "switch" with nothing after it.
    const container = await mount(
      <Switch
        checked={false}
        label="Show grid lines"
        onCheckedChange={() => {}}
      />,
    );
    const labelId = switchEl(container).getAttribute("aria-labelledby");
    expect(labelId).toBeTruthy();
    const named = container.querySelector(`span[id="${labelId}"]`);
    expect(named?.textContent).toBe("Show grid lines");
  });

  it("grows the row and the track on the phone breakpoint when it is in a page", async () => {
    const container = await mount(
      <Switch
        checked={false}
        label="Snap to grid"
        phoneTouch
        onCheckedChange={() => {}}
      />,
    );
    const root = container.querySelector("label");
    const track = switchEl(container);
    expect(root?.className).toContain("on");
    expect(track.className).toContain("phoneTrack");
    expect(track.querySelector('[class*="thumb"]')?.className ?? "").toContain(
      "phoneThumb",
    );
  });

  it("does not grow a switch that lives in a canvas card", async () => {
    const container = await mount(
      <Switch
        checked={false}
        size="dense"
        label="Show"
        onCheckedChange={() => {}}
      />,
    );
    expect(switchEl(container).className).not.toContain("phoneTrack");
    expect(container.querySelector("label")?.className).not.toContain("on");
  });

  it.each(sizes)("keeps one focusable element at size %s", async (size) => {
    const container = await mount(
      <Switch
        checked={false}
        label="Grid"
        size={size}
        onCheckedChange={() => {}}
      />,
    );
    expect(container.querySelectorAll('[role="switch"]')).toHaveLength(1);
    expect(switchEl(container).getAttribute("tabindex")).toBe("0");
  });

  it("leaves the switch alone when it is disabled", async () => {
    const onCheckedChange = vi.fn();
    const container = await mount(
      <Switch
        checked={false}
        label="Grid"
        disabled
        onCheckedChange={onCheckedChange}
      />,
    );
    const control = switchEl(container);
    expect(control.hasAttribute("data-disabled")).toBe(true);

    await act(async () =>
      control.dispatchEvent(new PointerEvent("click", { bubbles: true })),
    );
    await act(async () => control.click());
    expect(onCheckedChange).not.toHaveBeenCalled();
  });

  it("leaves React Flow classes on the root so a canvas row keeps its pointer behaviour", async () => {
    const container = await mount(
      <Switch
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
