// @vitest-environment jsdom

import * as React from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_CELL_GLASS_LOOK,
  DEFAULT_CELL_ROUTING,
  normalizeCellGlassLook,
  normalizeCellRouting,
} from "./cell-look";

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

const settingsMocks = vi.hoisted(() => ({
  patchCellLook: vi.fn(),
  patchCellRouting: vi.fn(),
  resetSettings: vi.fn(),
}));

vi.mock("./canvas-grid-settings", () => ({
  useCanvasGridSettings: () => ({
    cellLook: { ...DEFAULT_CELL_GLASS_LOOK },
    patchCellLook: settingsMocks.patchCellLook,
    cellRouting: { ...DEFAULT_CELL_ROUTING },
    patchCellRouting: settingsMocks.patchCellRouting,
    resetSettings: settingsMocks.resetSettings,
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
  settingsMocks.patchCellLook.mockReset();
  settingsMocks.patchCellRouting.mockReset();
  settingsMocks.resetSettings.mockReset();
  themeMocks.preference = "system";
  themeMocks.setPreference.mockReset();
});

describe("CanvasGridSettingsPanel", () => {
  it("shows glass, blur, frost, pipe, and routing controls", () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    roots.push(root);

    React.act(() => {
      root.render(<CanvasGridSettingsPanel />);
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

  it("switches the app theme from Canvas lab", () => {
    const container = document.createElement("div");
    const root = createRoot(container);
    roots.push(root);

    // A segmented control ignores a click on the selected option, so the
    // mock keeps the chosen preference and each click re-renders, the way the
    // real provider would.
    themeMocks.setPreference.mockImplementation((next) => {
      themeMocks.preference = next;
    });
    const render = () => root.render(<CanvasGridSettingsPanel />);

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
  });

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
