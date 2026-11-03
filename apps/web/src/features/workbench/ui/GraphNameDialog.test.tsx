// @vitest-environment jsdom

import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles extends Record<string, object>>(styles: Styles) => styles,
  defineVars: <Variables,>(variables: Variables) => variables,
  props: () => ({ className: "" }),
}));

import { GraphNameDialog } from "./GraphNameDialog";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const mountedRoots = new Set<ReturnType<typeof createRoot>>();

afterEach(async () => {
  await act(async () => {
    for (const root of mountedRoots) root.unmount();
  });
  mountedRoots.clear();
  document.body.replaceChildren();
});

async function mount(props: {
  onSubmit: (name: string) => void;
  onClose: () => void;
}) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  mountedRoots.add(root);
  await act(async () => {
    root.render(<GraphNameDialog open initialName="" {...props} />);
  });
}

function typeName(input: HTMLInputElement, value: string) {
  const setValue = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )?.set;
  setValue?.call(input, value);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("GraphNameDialog", () => {
  it("submits the trimmed name", async () => {
    const onSubmit = vi.fn();
    await mount({ onSubmit, onClose: vi.fn() });
    const input = document.querySelector<HTMLInputElement>(
      'input[aria-label="Graph name"]',
    )!;
    await act(async () => typeName(input, "  Quarterly report  "));
    await act(async () => {
      input.form!.requestSubmit();
    });
    expect(onSubmit).toHaveBeenCalledWith("Quarterly report");
  });

  it("does not submit a blank name", async () => {
    const onSubmit = vi.fn();
    await mount({ onSubmit, onClose: vi.fn() });
    const input = document.querySelector<HTMLInputElement>(
      'input[aria-label="Graph name"]',
    )!;
    await act(async () => typeName(input, "   "));
    await act(async () => {
      input.form!.requestSubmit();
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
