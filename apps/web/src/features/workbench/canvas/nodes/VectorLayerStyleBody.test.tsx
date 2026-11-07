// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

import type { NodeSpec } from "@/lib/api";
import { createWorkflowNodeData } from "../types";
import { VectorLayerStyleBody } from "./VectorLayerStyleBody";

function vectorLayerSpec(): NodeSpec {
  return {
    operator_id: "gis.map.vector_layer",
    operator_version: 1,
    plugin_slug: "external.gis",
    origin: "builtin",
    title: "Vector map layer",
    description: "Styles one feature collection.",
    catalog_visible: true,
    runnable: true,
    config_schema: {},
    input_schema: {},
    output_schema: {},
    inputs: [],
    outputs: [],
  };
}

function segments(container: HTMLElement) {
  return [...container.querySelectorAll<HTMLElement>('[role="radio"]')];
}

/**
 * The body is stateless: it writes through `onConfigChange`, so a mode switch
 * only shows in the markup when the host keeps the node config it is given.
 */
function VectorLayerNode({
  onConfigChange,
}: {
  onConfigChange: (nodeId: string, name: string, value: unknown) => void;
}) {
  const base = createWorkflowNodeData(vectorLayerSpec());
  const [style, setStyle] = React.useState<unknown>(null);
  const data = {
    ...base,
    config: { ...base.config, ...(style ? { style } : {}) },
    onConfigChange: (nodeId: string, name: string, value: unknown) => {
      setStyle(value);
      onConfigChange(nodeId, name, value);
    },
  };
  return <VectorLayerStyleBody id="vector-layer" data={data} />;
}

describe("VectorLayerStyleBody", () => {
  it("authors categorized styling as structured vector-layer config", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const onConfigChange = vi.fn();

    React.act(() => {
      root.render(<VectorLayerNode onConfigChange={onConfigChange} />);
    });

    // The mode switch is the kit's segmented control: a named radio group, not
    // a pair of buttons and not a select.
    const group = container.querySelector<HTMLElement>(
      '[role="radiogroup"][aria-label="Feature style mode"]',
    );
    expect(group).not.toBeNull();
    const modes = segments(container);
    expect(modes.map((segment) => segment.textContent)).toEqual([
      "Uniform",
      "Categories",
    ]);
    expect(modes[0]?.getAttribute("aria-checked")).toBe("true");
    expect(modes[1]?.getAttribute("aria-checked")).toBe("false");

    await React.act(async () => {
      modes[1]?.click();
    });

    expect(modes[1]?.getAttribute("aria-checked")).toBe("true");

    expect(onConfigChange).toHaveBeenCalledWith(
      "vector-layer",
      "style",
      expect.objectContaining({
        kind: "categorized_points",
        category_property: "type",
        categories: [
          expect.objectContaining({
            id: "category_1",
            values: [1],
          }),
        ],
      }),
    );

    React.act(() => root.unmount());
    container.remove();
  });

  it("labels every authored value and writes through the config writer", async () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root = createRoot(container);
    const data = {
      ...createWorkflowNodeData(vectorLayerSpec()),
      onConfigChange: vi.fn(),
    };

    React.act(() => {
      root.render(<VectorLayerStyleBody id="vector-layer" data={data} />);
    });

    // <Field> draws a <label> bound to its control, so a value keeps its
    // accessible name without an aria-label on the input.
    const labels = [...container.querySelectorAll("label")];
    const named = (text: string) =>
      labels.find((label) => label.textContent?.trim() === text);
    for (const text of ["Point radius", "Line width", "Fill opacity"]) {
      const label = named(text);
      const inputId = label?.htmlFor;
      expect(label, text).toBeDefined();
      expect(inputId, text).toBeTruthy();
      const input = inputId
        ? container.querySelector<HTMLInputElement>(`[id="${inputId}"]`)
        : null;
      expect(input?.getAttribute("type"), text).toBe("number");

      // React Flow resolves `nodrag` by walking up from the event target, so the
      // classes belong to the <Field> root and the control inside it says
      // nothing. The nearest class-carrying element has to be the very field
      // that names this input — a stray ancestor would pass for the field.
      const field = input?.closest<HTMLElement>("[class*='nodrag']");
      expect(field, text).not.toBeNull();
      expect(field?.querySelector("label")?.htmlFor, text).toBe(inputId);
      expect(input?.className.includes("nodrag"), text).toBe(false);
    }

    // The kit's ColorField is a labelled group, not a <Field>: it carries
    // React Flow's classes on its own root <label>, and the well inside it
    // says nothing. Without those classes React Flow would drag the card.
    const colorWell = container.querySelector<HTMLInputElement>(
      'input[type="color"]',
    );
    expect(colorWell).not.toBeNull();
    expect(colorWell?.className.includes("nodrag")).toBe(false);
    const colorRow = colorWell?.closest<HTMLElement>("[class*='nodrag']");
    expect(colorRow?.tagName).toBe("LABEL");
    expect(colorRow?.textContent?.trim()).toBe("Point color");

    // The kit's control still writes through the node's config writer.
    const radius = named("Point radius");
    const radiusInput = radius?.htmlFor
      ? container.querySelector<HTMLInputElement>(`[id="${radius.htmlFor}"]`)
      : null;
    expect(radiusInput).not.toBeNull();
    const onConfigChange = data.onConfigChange;
    await React.act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )?.set;
      setValue?.call(radiusInput, "9");
      radiusInput?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(onConfigChange).toHaveBeenCalledWith(
      "vector-layer",
      "style",
      expect.objectContaining({
        kind: "vector",
        point: expect.objectContaining({ radius: 9 }),
      }),
    );

    React.act(() => root.unmount());
    container.remove();
  });
});
