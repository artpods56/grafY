// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Slider } from "./slider";

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

function rangeInput(container: HTMLElement): HTMLInputElement {
  const el = container.querySelector<HTMLInputElement>('input[type="range"]');
  if (!el) throw new Error("expected a range input");
  return el;
}

/** The way a browser changes an input: set the value, then let the framework see it. */
async function setRange(container: HTMLElement, next: string) {
  const input = rangeInput(container);
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  await act(async () => {
    setter?.call(input, next);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
}

describe("Slider", () => {
  it("gives the range input the bounds it was given", async () => {
    const container = await mount(
      <Slider
        label="Opacity"
        value={0.4}
        min={0}
        max={1}
        step={0.05}
        onValueChange={() => {}}
      />,
    );
    const input = rangeInput(container);
    expect(input.getAttribute("min")).toBe("0");
    expect(input.getAttribute("max")).toBe("1");
    expect(input.getAttribute("step")).toBe("0.05");
    expect(input.getAttribute("aria-valuenow")).toBe("0.4");
  });

  it("names the control with its label", async () => {
    const container = await mount(
      <Slider
        label="Stroke width"
        value={2}
        min={0}
        max={12}
        step={1}
        onValueChange={() => {}}
      />,
    );
    const label = Array.from(container.querySelectorAll("span,div")).find(
      (el) => el.textContent?.includes("Stroke width"),
    );
    expect(label?.id).toBeTruthy();
    expect(
      rangeInput(container).getAttribute("aria-labelledby") ?? "",
    ).toContain(label?.id ?? "missing");
  });

  it("prints the value beside the track, with decimals when the step has them", async () => {
    const fine = await mount(
      <Slider
        label="Opacity"
        value={0.4}
        min={0}
        max={1}
        step={0.05}
        onValueChange={() => {}}
      />,
    );
    expect(fine.querySelector("output")?.textContent).toBe("0.40");

    const coarse = await mount(
      <Slider
        label="Radius"
        value={7}
        min={0}
        max={40}
        step={1}
        onValueChange={() => {}}
      />,
    );
    expect(coarse.querySelector("output")?.textContent).toBe("7");
  });

  it("prints it the caller's way when they say how", async () => {
    const container = await mount(
      <Slider
        label="Opacity"
        value={0.4}
        min={0}
        max={1}
        step={0.05}
        format={(value) => `${Math.round(value * 100)}%`}
        onValueChange={() => {}}
      />,
    );
    expect(container.querySelector("output")?.textContent).toBe("40%");
  });

  it("reports a change as a number, not as an event or a one-value array", async () => {
    const onValueChange = vi.fn();
    const container = await mount(
      <Slider
        label="Radius"
        value={7}
        min={0}
        max={40}
        step={1}
        onValueChange={onValueChange}
      />,
    );
    await setRange(container, "12");
    expect(onValueChange).toHaveBeenCalledWith(12);
  });

  it("is inert when disabled", async () => {
    const onValueChange = vi.fn();
    const container = await mount(
      <Slider
        label="Radius"
        value={7}
        min={0}
        max={40}
        step={1}
        disabled
        onValueChange={onValueChange}
      />,
    );
    expect(rangeInput(container).disabled).toBe(true);
  });

  it("keeps canvas pointer classes on the control", async () => {
    const container = await mount(
      <Slider
        label="Radius"
        value={7}
        min={0}
        max={40}
        step={1}
        className="nodrag nopan"
        onValueChange={() => {}}
      />,
    );
    const group =
      container.querySelector('[role="group"]') ?? container.firstElementChild;
    expect(group?.className).toContain("nodrag");
    expect(group?.className).toContain("nopan");
  });
});
