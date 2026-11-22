// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_CELL_GLASS_LOOK,
  DEFAULT_CELL_ROUTING,
  normalizeCellGlassLook,
  normalizeCellRouting,
} from "../cell-canvas/cell-look";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const settingsMocks = vi.hoisted(() => ({
  canvasEngine: "cell-canvas" as "cell-canvas" | "react-flow",
  patchSettings: vi.fn(),
  patchCellLook: vi.fn(),
  patchCellRouting: vi.fn(),
  resetSettings: vi.fn(),
  setCanvasEngine: vi.fn(),
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
    cellLook: { ...DEFAULT_CELL_GLASS_LOOK },
    patchCellLook: settingsMocks.patchCellLook,
    cellRouting: { ...DEFAULT_CELL_ROUTING },
    patchCellRouting: settingsMocks.patchCellRouting,
    resetSettings: settingsMocks.resetSettings,
    canvasEngine: settingsMocks.canvasEngine,
    setCanvasEngine: settingsMocks.setCanvasEngine,
    bypassSnap: false,
    panelOpen: true,
    setPanelOpen: vi.fn(),
  }),
}));

const themeMocks = vi.hoisted(() => ({
  preference: "system" as "light" | "dark" | "system",
  setPreference: vi.fn<(next: "light" | "dark" | "system") => void>(),
}));

// `useTheme` throws outside `ThemeProvider`; the panel only needs the preference.
vi.mock("@/components/theme", () => ({
  useTheme: () => ({
    preference: themeMocks.preference,
    setPreference: themeMocks.setPreference,
  }),
}));

import { CanvasGridSettingsPanel } from "./CanvasGridSettingsPanel";

const roots: Root[] = [];

/**
 * The panel's switches are the kit's `Switch`, whose accessible name comes from
 * the label through `aria-labelledby` — a `role="switch"` is not a labelable
 * element, so the label text is not in the control's own subtree. Resolving the
 * reference is what "named by its label" means here.
 */
function switchNamed(container: HTMLElement, name: string) {
  return (
    [...container.querySelectorAll('[role="switch"]')].find((control) => {
      const id = control.getAttribute("aria-labelledby");
      return (
        id != null && container.querySelector(`#${id}`)?.textContent === name
      );
    }) ?? null
  );
}

function radioNamed(
  container: HTMLElement,
  groupLabel: string,
  option: string,
) {
  const group = container.querySelector(`[aria-label="${groupLabel}"]`);
  if (!group) return null;
  return (
    [...group.querySelectorAll('[role="radio"]')].find(
      (candidate) => candidate.textContent?.trim() === option,
    ) ?? null
  );
}

afterEach(() => {
  React.act(() => {
    for (const root of roots.splice(0)) root.unmount();
  });
  settingsMocks.canvasEngine = "cell-canvas";
  settingsMocks.patchSettings.mockReset();
  settingsMocks.patchCellLook.mockReset();
  settingsMocks.patchCellRouting.mockReset();
  settingsMocks.resetSettings.mockReset();
  settingsMocks.setCanvasEngine.mockReset();
  themeMocks.preference = "system";
  themeMocks.setPreference.mockReset();
});

describe("CanvasGridSettingsPanel", () => {
  it("shows glass, blur, frost, pipe, and routing controls when Cell canvas is active", () => {
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

    expect(container.textContent).toContain("Glass, pipe and routing controls");
    const sliders = [
      ...container.querySelectorAll<HTMLInputElement>('input[type="range"]'),
    ];
    expect(sliders).toHaveLength(3);
    expect(sliders[0]?.getAttribute("aria-valuenow")).toBe("0.3");
    expect(sliders[1]?.getAttribute("aria-valuenow")).toBe("0.5");
    // Card fill: see-through by default, so pipes show under the plates.
    expect(sliders[2]?.getAttribute("aria-valuenow")).toBe("0.58");
    expect(container.textContent).toContain("Card fill");
    expect(container.textContent).toContain("58%");

    React.act(() => {
      radioNamed(container, "Glass", "Frost")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
      radioNamed(container, "Wells", "Flat")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
      radioNamed(container, "Wells", "Punched")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
      radioNamed(container, "Pipe", "Fibre")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
      radioNamed(container, "Corners", "Sharp")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
      radioNamed(container, "Stack style", "Deck")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
      radioNamed(container, "Cell grid", "Off")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
      radioNamed(container, "Exit", "Free")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
      radioNamed(container, "Under cards", "Avoid")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
      radioNamed(container, "Depth layers", "Off")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });

    expect(settingsMocks.patchCellLook).toHaveBeenCalledWith({
      material: "frost",
    });
    expect(settingsMocks.patchCellLook).toHaveBeenCalledWith({ well: "flat" });
    expect(settingsMocks.patchCellLook).toHaveBeenCalledWith({
      well: "punched",
    });
    expect(settingsMocks.patchCellLook).toHaveBeenCalledWith({ pipe: "fibre" });
    expect(settingsMocks.patchCellLook).toHaveBeenCalledWith({
      corners: "sharp",
    });
    expect(settingsMocks.patchCellLook).toHaveBeenCalledWith({
      stackStyle: "deck",
    });
    expect(settingsMocks.patchCellLook).toHaveBeenCalledWith({ grid: false });
    expect(settingsMocks.patchCellRouting).toHaveBeenCalledWith({
      exits: "free",
    });
    expect(settingsMocks.patchCellRouting).toHaveBeenCalledWith({
      underCards: "avoid",
    });
    expect(settingsMocks.patchCellRouting).toHaveBeenCalledWith({
      depth: false,
    });
  });

  it("keeps primary controls visible and groups detailed controls under Advanced in React Flow mode", () => {
    settingsMocks.canvasEngine = "react-flow";
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

    const toggle = switchNamed(container, "Render visible elements only");
    const advanced = toggle?.closest("details");
    expect(container.textContent).toContain("Grid and snapping controls");
    expect(switchNamed(container, "Enable snapping")).not.toBeNull();
    expect(switchNamed(container, "Show grid lines")).not.toBeNull();
    const cellSize = container.querySelector<HTMLInputElement>(
      'input[type="range"]',
    );
    expect(cellSize).not.toBeNull();
    expect(cellSize?.getAttribute("aria-valuenow")).toBe("50");
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

  it("applies a cell-size preset through its button in React Flow mode", () => {
    settingsMocks.canvasEngine = "react-flow";
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

    const preset = [...container.querySelectorAll("button")].find(
      (candidate) =>
        candidate.tagName === "BUTTON" &&
        candidate.textContent?.trim() === "72",
    );
    expect(preset).toBeDefined();

    React.act(() => {
      preset?.click();
    });

    expect(settingsMocks.patchSettings).toHaveBeenCalledWith({ cellSize: 72 });
  });

  it("switches the canvas engine when selected in Canvas lab", () => {
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

    const reactFlowButton = radioNamed(
      container,
      "Canvas engine",
      "React Flow",
    );
    expect(reactFlowButton).not.toBeNull();

    React.act(() => {
      reactFlowButton?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
      );
    });

    expect(settingsMocks.setCanvasEngine).toHaveBeenCalledWith("react-flow");
  });

  it.each(["cell-canvas", "react-flow"] as const)(
    "switches the app theme from Canvas lab in %s mode",
    (engine) => {
      settingsMocks.canvasEngine = engine;
      const container = document.createElement("div");
      const root = createRoot(container);
      roots.push(root);

      // A segmented control ignores a click on the selected option, so the
      // mock keeps the chosen preference and each click re-renders, the way the
      // real provider would.
      themeMocks.setPreference.mockImplementation((next) => {
        themeMocks.preference = next;
      });
      const render = () =>
        root.render(
          <CanvasGridSettingsPanel
            selectedCount={0}
            onSnapSelection={() => undefined}
          />,
        );

      React.act(render);

      expect(
        radioNamed(container, "Theme", "System")?.getAttribute("aria-checked"),
      ).toBe("true");

      for (const [option, preference] of [
        ["Dark", "dark"],
        ["Light", "light"],
        ["System", "system"],
      ] as const) {
        const radio = radioNamed(container, "Theme", option);
        expect(radio).not.toBeNull();
        React.act(() => {
          radio?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        });
        React.act(render);
        expect(themeMocks.setPreference).toHaveBeenLastCalledWith(preference);
      }
    },
  );

  it("normalizes and clamps persisted cell look and routing values", () => {
    expect(
      normalizeCellGlassLook({
        material: "frost",
        blur: 99,
        frost: -1,
        grid: false,
      }),
    ).toEqual({
      ...DEFAULT_CELL_GLASS_LOOK,
      material: "frost",
      blur: 12,
      frost: 0,
      grid: false,
    });
    expect(normalizeCellGlassLook({ well: "punched" })).toEqual({
      ...DEFAULT_CELL_GLASS_LOOK,
      well: "punched",
    });
    expect(
      normalizeCellGlassLook({ well: "drilled" as unknown as "punched" }).well,
    ).toBe(DEFAULT_CELL_GLASS_LOOK.well);
    expect(DEFAULT_CELL_GLASS_LOOK.well).toBe("recessed");
    expect(DEFAULT_CELL_GLASS_LOOK.stackStyle).toBe("fan");
    expect(normalizeCellGlassLook({ stackStyle: "deck" }).stackStyle).toBe(
      "deck",
    );
    expect(
      normalizeCellGlassLook({
        stackStyle: "pile" as unknown as "deck",
      }).stackStyle,
    ).toBe("fan");
    expect(DEFAULT_CELL_GLASS_LOOK.cardFill).toBe(0.58);
    expect(normalizeCellGlassLook({ cardFill: 5 }).cardFill).toBe(1);
    expect(normalizeCellGlassLook({ cardFill: 0 }).cardFill).toBe(0.2);
    expect(
      normalizeCellGlassLook({ cardFill: "solid" as unknown as number })
        .cardFill,
    ).toBe(0.58);
    expect(
      normalizeCellRouting({
        exits: "free",
        underCards: "avoid",
        depth: false,
      }),
    ).toEqual({
      exits: "free",
      underCards: "avoid",
      depth: false,
    });
  });
});
