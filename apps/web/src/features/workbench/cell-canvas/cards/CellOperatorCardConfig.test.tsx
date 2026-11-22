// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NodeSpec } from "@/lib/api";

import {
  askModelSpec,
  fixtureDocument,
  fixtureNode,
  richRegistry,
  vectorLayerSpec,
} from "../cell-config-fixtures.test-support";
import type { CellSecretInputSpec } from "../cell-contracts";
import { buildOperatorCardsAndSurfaces } from "../cell-operator-adapter";
import {
  CellOperatorCard,
  type CellOperatorCardProps,
} from "./CellOperatorCard";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const roots: ReturnType<typeof createRoot>[] = [];

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.replaceChildren();
});

function mount(
  spec: NodeSpec,
  config: Record<string, unknown>,
  props: Partial<CellOperatorCardProps> = {},
  secretInputs?: readonly CellSecretInputSpec[],
) {
  const { cards, surfaces } = buildOperatorCardsAndSurfaces(
    fixtureDocument([fixtureNode("node", spec, config)]),
    richRegistry,
  );
  const surface = surfaces.get("node");
  if (surface?.kind !== "operator") throw new Error("operator surface");
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  React.act(() => {
    root.render(
      <CellOperatorCard
        card={cards[0]!}
        surface={secretInputs ? { ...surface, secretInputs } : surface}
        selected
        dragging={false}
        {...props}
      />,
    );
  });
  return container;
}

function click(element: Element | null) {
  expect(element).not.toBeNull();
  React.act(() => {
    (element as HTMLElement).click();
  });
}

function type(input: HTMLInputElement | null, value: string) {
  expect(input).not.toBeNull();
  React.act(() => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )?.set?.call(input, value);
    input!.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

describe("CellOperatorCard config interactions", () => {
  it("asks to open the advanced fold for its own card", () => {
    const onToggleConfigSection = vi.fn();
    const container = mount(
      vectorLayerSpec,
      { title: "Roads" },
      { onToggleConfigSection, onConfigChange: vi.fn() },
    );
    click(container.querySelector('[data-config-section="advanced"]'));
    expect(onToggleConfigSection).toHaveBeenCalledWith(
      "node",
      "advanced",
      true,
    );
  });

  it("commits the whole `Style` value when the branch changes", () => {
    const onConfigChange = vi.fn();
    const container = mount(
      vectorLayerSpec,
      { title: "Roads" },
      { onConfigChange },
    );
    const byCategory = [
      ...container.querySelectorAll('[aria-label="Style mode"] [role="radio"]'),
    ].find((radio) => radio.textContent === "By category");
    click(byCategory ?? null);
    expect(onConfigChange).toHaveBeenCalledTimes(1);
    const [cardId, fieldId, value] = onConfigChange.mock.calls[0]!;
    expect([cardId, fieldId]).toEqual(["node", "style"]);
    expect(value).toMatchObject({
      kind: "categorized_points",
      categories: [{ title: "Category 1", color: "#ff8800" }],
    });
  });

  it("adds an item to an object list with a fresh id and a numbered title", () => {
    const onConfigChange = vi.fn();
    const style = {
      kind: "categorized_points",
      categories: [{ id: "c1", title: "Roads", color: "#ff0000" }],
    };
    const container = mount(
      vectorLayerSpec,
      { title: "Roads", style },
      { onConfigChange },
    );
    const add = [...container.querySelectorAll("button")].find(
      (button) => button.textContent === "Add category",
    );
    click(add ?? null);
    const [, fieldId, value] = onConfigChange.mock.calls[0]!;
    expect(fieldId).toBe("style");
    const categories = (value as typeof style).categories;
    expect(categories).toHaveLength(2);
    expect(categories[1]).toMatchObject({ title: "Category 2" });
    expect(typeof (categories[1] as { id?: unknown }).id).toBe("string");
  });

  it("commits a nested colour once its hex is whole", () => {
    const onConfigChange = vi.fn();
    const container = mount(
      vectorLayerSpec,
      { title: "Roads" },
      { onConfigChange },
    );
    const hex = container.querySelector<HTMLInputElement>(
      'input[aria-label="Fill hex"]',
    );
    type(hex, "#12");
    expect(onConfigChange).not.toHaveBeenCalled();
    type(hex, "#1188FF");
    expect(onConfigChange).toHaveBeenLastCalledWith(
      "node",
      "style",
      expect.objectContaining({ kind: "simple", fill: "#1188ff" }),
    );
  });

  it("draws every control disabled on a card that cannot be edited", () => {
    const container = mount(vectorLayerSpec, { title: "Roads" });
    const title = container.querySelector<HTMLInputElement>(
      '[data-config-field="title"] input',
    );
    expect(title?.disabled).toBe(true);
  });
});

describe("CellOperatorCard credentials popover", () => {
  const configured: CellSecretInputSpec = {
    name: "api_key",
    title: "API key",
    state: "configured",
    ready: true,
    revision: "graph:1",
  };

  function openPopover(
    inputs: readonly CellSecretInputSpec[],
    props: Partial<CellOperatorCardProps> = {},
  ) {
    const container = mount(askModelSpec, {}, props, inputs);
    click(container.querySelector("[data-credentials-trigger]"));
    const popup = document.querySelector('[data-credentials-popover="node"]');
    expect(popup).not.toBeNull();
    return { container, popup: popup as HTMLElement };
  }

  it("opens from the header key and lists each key with its status", () => {
    const { container, popup } = openPopover([configured]);
    expect(
      container.querySelector('[data-credentials-trigger="configured"]'),
    ).not.toBeNull();
    expect(popup.textContent).toContain("Credentials");
    expect(popup.textContent).toContain("API key");
    expect(
      popup.querySelector('[data-secret-status="configured"]')?.textContent,
    ).toBe("Configured");
    const input = popup.querySelector<HTMLInputElement>(
      'input[type="password"]',
    );
    expect(input?.value).toBe("");
    expect(input?.autocomplete).toBe("off");
  });

  it("applies a pasted key and clears the input once it is saved", async () => {
    let resolve: (applied: boolean) => void = () => {};
    const applied = new Promise<boolean>((done) => {
      resolve = done;
    });
    const onApplySecret = vi.fn(() => applied);
    const { popup } = openPopover([{ ...configured, state: "unconfigured" }], {
      onApplySecret,
    });
    expect(popup.textContent).toContain("Not set");
    const input = popup.querySelector<HTMLInputElement>(
      'input[type="password"]',
    );
    type(input, "sk-test");
    const apply = [...popup.querySelectorAll("button")].find(
      (button) => button.textContent === "Apply",
    );
    expect(apply?.disabled).toBe(false);
    click(apply ?? null);
    expect(onApplySecret).toHaveBeenCalledWith("node", "api_key", "sk-test");
    await React.act(async () => {
      resolve(true);
      await applied;
    });
    expect(input?.value).toBe("");
  });

  it("removes a configured key", () => {
    const onRemoveSecret = vi.fn(() => Promise.resolve(true));
    const { popup } = openPopover([configured], { onRemoveSecret });
    const remove = [...popup.querySelectorAll("button")].find(
      (button) => button.textContent === "Remove",
    );
    expect(remove?.disabled).toBe(false);
    click(remove ?? null);
    expect(onRemoveSecret).toHaveBeenCalledWith("node", "api_key");
  });

  it("asks for a save before a key can be written to an unsaved node", () => {
    const { container, popup } = openPopover(
      [{ ...configured, state: "unknown", ready: false }],
      { onApplySecret: vi.fn(), onRemoveSecret: vi.fn() },
    );
    expect(
      container.querySelector('[data-credentials-trigger="needed"]'),
    ).not.toBeNull();
    expect(popup.textContent).toContain("Save node first");
    expect(popup.textContent).toContain("Save this node before adding a key.");
    expect(
      popup.querySelector<HTMLInputElement>('input[type="password"]')?.disabled,
    ).toBe(true);
    const remove = [...popup.querySelectorAll("button")].find(
      (button) => button.textContent === "Remove",
    );
    expect(remove?.disabled).toBe(true);
  });

  it("closes on Escape", () => {
    const { popup } = openPopover([configured]);
    React.act(() => {
      popup.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
    });
    expect(
      document.querySelector('[data-credentials-popover="node"]'),
    ).toBeNull();
  });
});
