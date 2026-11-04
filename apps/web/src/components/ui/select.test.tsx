// @vitest-environment jsdom

import * as React from "react";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Field } from "./field";
import { Select } from "./select";

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

function selectEl(container: HTMLElement): HTMLSelectElement {
  const el = container.querySelector("select");
  if (!el) throw new Error("expected a select");
  return el;
}

const options = (
  <>
    <option value="nearest">Nearest</option>
    <option value="linear">Linear</option>
  </>
);

describe("Select", () => {
  it("is a native select holding the caller's options", async () => {
    const container = await mount(
      <Select value="linear" onChange={() => {}} aria-label="Resampling">
        {options}
      </Select>,
    );
    const control = selectEl(container);
    expect(control.options).toHaveLength(2);
    expect(control.value).toBe("linear");
    // The platform popup stays: no wrapper element between the field and the control.
    expect(control.parentElement?.querySelectorAll("select")).toHaveLength(1);
  });

  it("reports a chosen option as the value the caller asked for", async () => {
    const picked: string[] = [];
    const onChange = vi.fn((event: React.ChangeEvent<HTMLSelectElement>) => {
      picked.push(event.currentTarget.value);
    });
    const container = await mount(
      <Select value="nearest" onChange={onChange} aria-label="Resampling">
        {options}
      </Select>,
    );
    const control = selectEl(container);
    await act(async () => {
      control.value = "linear";
      control.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(picked).toEqual(["linear"]);
  });

  it("takes its name and its error from the surrounding Field", async () => {
    const container = await mount(
      <Field label="Rows per page" description="How many rows a page holds">
        <Select defaultValue="25" aria-label="Rows per page">
          <option value="25">25</option>
        </Select>
      </Field>,
    );
    const control = selectEl(container);
    const label = container.querySelector("label");
    expect(label?.htmlFor).toBeTruthy();
    expect(label?.htmlFor).toBe(control.id);
    const describedBy = control.getAttribute("aria-describedby");
    expect(describedBy).toBeTruthy();
    for (const id of describedBy?.split(" ") ?? []) {
      expect(document.getElementById(id)).not.toBeNull();
    }
    expect(container.textContent).toContain("How many rows a page holds");
  });

  it("marks the control invalid when the Field has an error", async () => {
    const container = await mount(
      <Field label="Value type" error="That type is not in the schema">
        <Select defaultValue="text">
          <option value="text">text</option>
        </Select>
      </Field>,
    );
    expect(selectEl(container).getAttribute("aria-invalid")).toBe("true");
    expect(container.textContent).toContain("That type is not in the schema");
  });

  it("marks the control invalid when the caller says so directly", async () => {
    const container = await mount(
      <Select value="x" onChange={() => {}} invalid aria-label="Column">
        <option value="x">x</option>
      </Select>,
    );
    expect(selectEl(container).getAttribute("aria-invalid")).toBe("true");
  });

  it("is inert when disabled and keeps canvas pointer classes", async () => {
    const container = await mount(
      <Select
        value="x"
        onChange={() => {}}
        disabled
        className="nodrag nopan"
        aria-label="Column"
      >
        <option value="x">x</option>
      </Select>,
    );
    expect(selectEl(container).disabled).toBe(true);
    expect(selectEl(container).className).toContain("nodrag");
    expect(selectEl(container).className).toContain("nopan");
  });
});
