// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ColorField, ColorWell, type ColorWellSize } from "./color-field";

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

function well(container: HTMLElement): HTMLInputElement {
  const el = container.querySelector<HTMLInputElement>('input[type="color"]');
  if (!el) throw new Error("expected a colour well");
  return el;
}

async function pick(container: HTMLElement, next: string) {
  const input = well(container);
  const setter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  await act(async () => {
    setter?.call(input, next);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

const sizes: ColorWellSize[] = ["dense", "sm", "md"];

describe("ColorWell", () => {
  it("is a native colour input, so the platform picker stays", async () => {
    const container = await mount(
      <ColorWell value="#2a9d7c" label="Fill" onChange={() => {}} />,
    );
    expect(well(container).type).toBe("color");
    expect(well(container).value).toBe("#2a9d7c");
  });

  it("never draws an anonymous square", async () => {
    const container = await mount(
      <ColorWell value="#000000" label="Stroke" onChange={() => {}} />,
    );
    expect(well(container).getAttribute("aria-label")).toBe("Stroke");
    expect(well(container).title).toBe("Stroke");
  });

  it("reports the picked colour as a string", async () => {
    const onChange = vi.fn();
    const container = await mount(
      <ColorWell value="#000000" label="Fill" onChange={onChange} />,
    );
    await pick(container, "#ff0000");
    expect(onChange).toHaveBeenCalledWith("#ff0000");
  });

  it.each(sizes)("keeps one control at size %s", async (size) => {
    const container = await mount(
      <ColorWell
        value="#000000"
        label="Fill"
        size={size}
        onChange={() => {}}
      />,
    );
    expect(container.querySelectorAll('input[type="color"]')).toHaveLength(1);
  });

  it("is inert when disabled", async () => {
    const onChange = vi.fn();
    const container = await mount(
      <ColorWell value="#000000" label="Fill" disabled onChange={onChange} />,
    );
    expect(well(container).disabled).toBe(true);
  });
});

describe("ColorField", () => {
  it("puts the name above the well and makes the whole row clickable", async () => {
    const container = await mount(
      <ColorField label="Fill" value="#000000" onChange={() => {}} />,
    );
    const row = container.querySelector("label");
    expect(row?.textContent).toContain("Fill");
    expect(row?.contains(well(container))).toBe(true);
  });

  it("shows the value the layer holds beside the name", async () => {
    const container = await mount(
      <ColorField
        label="Fill"
        value="#2a9d7c"
        aside="#2a9d7c"
        onChange={() => {}}
      />,
    );
    expect(container.textContent).toContain("#2a9d7c");
  });

  it("keeps canvas pointer classes on the row", async () => {
    const container = await mount(
      <ColorField
        label="Fill"
        value="#000000"
        className="nodrag nopan"
        onChange={() => {}}
      />,
    );
    const row = container.querySelector("label");
    expect(row?.className).toContain("nodrag");
    expect(row?.className).toContain("nopan");
  });
});
