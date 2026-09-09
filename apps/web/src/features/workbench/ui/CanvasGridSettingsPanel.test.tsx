// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const settingsMocks = vi.hoisted(() => ({
  patchSettings: vi.fn(),
}));

vi.mock("@stylexjs/stylex", () => ({
  create: <Styles,>(styles: Styles) => styles,
  props: () => ({}),
}));

vi.mock("../canvas/canvas-grid-settings", () => ({
  useCanvasGridSettings: () => ({
    settings: {
      enabled: true,
      showBackground: true,
      onlyRenderVisibleElements: false,
      snapPosition: true,
      snapSize: true,
      snapWhileDragging: false,
      snapWhileResizing: true,
      allowWorkflowCornerResize: false,
      cellSize: 50,
    },
    patchSettings: settingsMocks.patchSettings,
    resetSettings: vi.fn(),
    bypassSnap: false,
    panelOpen: true,
    setPanelOpen: vi.fn(),
  }),
}));

import { CanvasGridSettingsPanel } from "./CanvasGridSettingsPanel";

const roots: Root[] = [];

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  settingsMocks.patchSettings.mockReset();
});

describe("CanvasGridSettingsPanel", () => {
  it("keeps primary controls visible and groups detailed controls under Advanced", () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    roots.push(root);

    React.act(() => {
      root.render(
        <CanvasGridSettingsPanel
          selectedCount={0}
          onSnapSelection={() => undefined}
        />,
      );
    });

    const toggle = container.querySelector<HTMLButtonElement>(
      'button[aria-label="Render visible elements only"]',
    );
    const advanced = toggle?.closest("details");
    expect(container.textContent).toContain("Grid and snapping controls");
    expect(
      container.querySelector('button[aria-label="Enable snapping"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('button[aria-label="Show grid lines"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('input[aria-label="Grid cell size"]'),
    ).not.toBeNull();
    expect(container.querySelector("summary")?.textContent).toContain(
      "Advanced",
    );
    expect(advanced?.open).toBe(false);
    expect(toggle?.getAttribute("aria-checked")).toBe("false");
    expect(container.textContent).toContain("Offscreen view state may reset");

    React.act(() => {
      container.querySelector("summary")?.click();
    });
    expect(advanced?.open).toBe(true);

    React.act(() => {
      toggle?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(settingsMocks.patchSettings).toHaveBeenCalledWith({
      onlyRenderVisibleElements: true,
    });
  });
});
