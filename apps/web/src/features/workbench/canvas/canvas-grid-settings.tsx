"use client";

import * as React from "react";

import {
  DEFAULT_CANVAS_GRID_SETTINGS,
  normalizeCanvasGridSettings,
  type CanvasGridSettings,
} from "./grid-layout";

const STORAGE_KEY = "grafy.workbench.canvasGridSettings.v2";

type CanvasGridSettingsContextValue = {
  settings: CanvasGridSettings;
  setSettings: React.Dispatch<React.SetStateAction<CanvasGridSettings>>;
  patchSettings: (patch: Partial<CanvasGridSettings>) => void;
  resetSettings: () => void;
  /** True while Alt is held — bypasses snap for A/B free placement. */
  bypassSnap: boolean;
  panelOpen: boolean;
  setPanelOpen: React.Dispatch<React.SetStateAction<boolean>>;
};

const CanvasGridSettingsContext =
  React.createContext<CanvasGridSettingsContextValue | null>(null);

function readStoredSettings(): CanvasGridSettings {
  if (typeof window === "undefined") return { ...DEFAULT_CANVAS_GRID_SETTINGS };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_CANVAS_GRID_SETTINGS };
    return normalizeCanvasGridSettings(
      JSON.parse(raw) as Partial<CanvasGridSettings>,
    );
  } catch {
    return { ...DEFAULT_CANVAS_GRID_SETTINGS };
  }
}

export function CanvasGridSettingsProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [settings, setSettings] = React.useState<CanvasGridSettings>(() =>
    readStoredSettings(),
  );
  const [panelOpen, setPanelOpen] = React.useState(false);
  const [bypassSnap, setBypassSnap] = React.useState(false);

  React.useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      // Ignore quota / private-mode failures; in-memory settings still work.
    }
  }, [settings]);

  React.useEffect(() => {
    const syncAlt = (event: KeyboardEvent) => {
      setBypassSnap(event.altKey);
    };
    const clearAlt = () => setBypassSnap(false);
    window.addEventListener("keydown", syncAlt);
    window.addEventListener("keyup", syncAlt);
    window.addEventListener("blur", clearAlt);
    return () => {
      window.removeEventListener("keydown", syncAlt);
      window.removeEventListener("keyup", syncAlt);
      window.removeEventListener("blur", clearAlt);
    };
  }, []);

  const patchSettings = React.useCallback(
    (patch: Partial<CanvasGridSettings>) => {
      setSettings((current) =>
        normalizeCanvasGridSettings({ ...current, ...patch }),
      );
    },
    [],
  );

  const resetSettings = React.useCallback(() => {
    setSettings({ ...DEFAULT_CANVAS_GRID_SETTINGS });
  }, []);

  const value = React.useMemo(
    () => ({
      settings,
      setSettings,
      patchSettings,
      resetSettings,
      bypassSnap,
      panelOpen,
      setPanelOpen,
    }),
    [bypassSnap, panelOpen, patchSettings, resetSettings, settings],
  );

  return (
    <CanvasGridSettingsContext.Provider value={value}>
      {children}
    </CanvasGridSettingsContext.Provider>
  );
}

export function useCanvasGridSettings(): CanvasGridSettingsContextValue {
  const value = React.useContext(CanvasGridSettingsContext);
  if (!value) {
    throw new Error(
      "useCanvasGridSettings must be used within CanvasGridSettingsProvider",
    );
  }
  return value;
}

/** Safe for node chrome that may render outside the provider in tests. */
export function useOptionalCanvasGridSettings(): CanvasGridSettingsContextValue | null {
  return React.useContext(CanvasGridSettingsContext);
}
