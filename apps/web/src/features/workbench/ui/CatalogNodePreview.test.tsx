// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

import { CatalogNodePreview, portKey } from "./CatalogNodePreview";

const roots: Root[] = [];

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.replaceChildren();
});

function port(
  name: string,
  direction: Port["direction"],
  artifactTypeId: string,
): Port {
  return {
    name,
    title: name[0]?.toUpperCase() + name.slice(1),
    description: `${name} port`,
    direction,
    artifact_type: { id: artifactTypeId, schema_version: 1 },
    artifact_type_variable: null,
    shape: "one",
    accepted_shapes: ["one"],
    instance_plugs: false,
    variadic: false,
    required: true,
  };
}

const INPUT = port("payload", "input", "scalar.text");
const OUTPUT = port("result", "output", "scalar.text");

const SPEC = {
  operator_id: "text.transform",
  operator_version: 1,
  plugin_slug: "builtin",
  title: "Transform text",
  description: "Transform text description",
  config_schema: {},
  input_schema: {},
  output_schema: {},
  inputs: [INPUT],
  outputs: [OUTPUT],
  catalog_visible: true,
  origin: "builtin",
  runnable: true,
} as unknown as NodeSpec;

const REGISTRY = {
  plugins: [],
  artifact_types: [],
  artifact_conversions: [],
  nodes: [],
} as unknown as NodeRegistry;

function renderPreview(element: React.ReactElement): HTMLElement {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  roots.push(root);
  React.act(() => root.render(element));
  return container;
}

function portTabs(container: HTMLElement): HTMLButtonElement[] {
  return [
    ...container.querySelectorAll<HTMLButtonElement>(
      'button[aria-label^="Show nodes that work with "]',
    ),
  ];
}

describe("CatalogNodePreview", () => {
  it("marks the chosen port as a pressed tab and reports the next one", () => {
    const onSelectPort = vi.fn();
    const container = renderPreview(
      <CatalogNodePreview
        spec={SPEC}
        registry={REGISTRY}
        fields={[]}
        selectedPortKey={portKey(INPUT)}
        onSelectPort={onSelectPort}
      />,
    );

    const tabs = portTabs(container);
    expect(tabs.map((tab) => tab.getAttribute("aria-label"))).toEqual([
      "Show nodes that work with Payload",
      "Show nodes that work with Result",
    ]);
    expect(tabs.map((tab) => tab.getAttribute("aria-pressed"))).toEqual([
      "true",
      "false",
    ]);

    const next = tabs[1];
    if (!next) throw new Error("the preview shows the node's output port");
    React.act(() => next.click());

    expect(onSelectPort).toHaveBeenCalledWith(
      expect.objectContaining({ name: "result" }),
    );
  });

  it("shows the chosen port without a control where nothing can be chosen", () => {
    const container = renderPreview(
      <CatalogNodePreview
        spec={SPEC}
        registry={REGISTRY}
        fields={[]}
        selectedPortKey={portKey(INPUT)}
      />,
    );

    // The same accent tint as the interactive preview, so a chosen port reads
    // the same whether or not it can be clicked.
    expect(portTabs(container)).toHaveLength(0);
    const chosen = container.querySelector('[class~="previewTabSelected"]');
    expect(chosen?.textContent).toContain("Payload");
    expect(chosen?.tagName).toBe("SPAN");
  });
});
