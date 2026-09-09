// @vitest-environment jsdom

import * as React from "react";
import { createRoot } from "react-dom/client";
import { act } from "react";
import { describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

import { SchemaDrill } from "./type-inspector";

const SCHEMA = {
  title: "GeoMapLayer",
  type: "object",
  required: ["title", "source"],
  properties: {
    title: { type: "string" },
    source: {
      oneOf: [
        {
          title: "GeoWmsSource",
          type: "object",
          properties: {
            kind: { const: "wms", type: "string" },
            url: { type: "string" },
          },
        },
        {
          title: "GeoRasterArtifactSource",
          type: "object",
          properties: {
            kind: { const: "raster_scan", type: "string" },
            artifact: {
              type: "object",
              properties: { id: { type: "string" } },
            },
          },
        },
      ],
    },
  },
};

async function render(ui: React.ReactElement) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(ui);
  });
  return {
    container,
    unmount: async () => {
      await act(async () => {
        root.unmount();
      });
      container.remove();
    },
  };
}

describe("SchemaDrill", () => {
  it("shows the root object and union type labels", async () => {
    const { container, unmount } = await render(
      <SchemaDrill schema={SCHEMA} />,
    );
    expect(container.textContent).toContain("GeoMapLayer");
    expect(container.textContent).toContain("title");
    expect(container.textContent).toContain("source");
    expect(container.textContent).toContain("wms | raster_scan");
    expect(
      container.querySelector('[aria-label="Payload schema path"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[aria-label="Payload schema fields"]'),
    ).not.toBeNull();
    expect(container.querySelector('[aria-current="page"]')?.textContent).toBe(
      "GeoMapLayer",
    );
    await unmount();
  });

  it("drills into a union without putting as-prefix in the crumb", async () => {
    const { container, unmount } = await render(
      <SchemaDrill schema={SCHEMA} />,
    );
    const source = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("source"),
    );
    expect(source).toBeDefined();
    await act(async () => {
      source!.click();
    });
    const raster = Array.from(container.querySelectorAll("button")).find(
      (button) => button.textContent?.includes("as raster_scan"),
    );
    expect(raster).toBeDefined();
    await act(async () => {
      raster!.click();
    });
    const crumbs = Array.from(container.querySelectorAll("button")).map(
      (button) => button.textContent,
    );
    expect(crumbs).toContain("GeoMapLayer");
    expect(crumbs).toContain("source");
    expect(crumbs).toContain("raster_scan");
    expect(crumbs.some((label) => label?.includes("as raster_scan"))).toBe(
      false,
    );
    expect(container.textContent).toContain("artifact");
    expect(container.querySelector('[aria-current="page"]')?.textContent).toBe(
      "raster_scan",
    );
    await unmount();
  });

  it("explains opaque artifacts", async () => {
    const { container, unmount } = await render(<SchemaDrill schema={{}} />);
    expect(container.textContent).toContain("No declared payload schema");
    await unmount();
  });
});
