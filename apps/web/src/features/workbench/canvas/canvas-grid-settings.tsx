"use client";

import * as React from "react";

import {
  DEFAULT_CELL_GLASS_LOOK,
  DEFAULT_CELL_ROUTING,
  normalizeCellGlassLook,
  normalizeCellRouting,
} from "../cell-canvas/cell-look";
import type { CellGlassLook } from "../cell-canvas/cell-glass-stage";
import type { CellRoutingOptions } from "../cell-canvas/cell-model";
import {
  DEFAULT_CANVAS_GRID_SETTINGS,
  normalizeCanvasGridSettings,
  type CanvasGridSettings,
} from "./grid-layout";
import {
  DEFAULT_WORKBENCH_CANVAS_ENGINE,
  readCanvasEnginePreference,
  writeCanvasEnginePreference,
  type WorkbenchCanvasEngineKind,
} from "./canvas-surface-port";

const STORAGE_KEY = "grafy.workbench.canvasGridSettings.v2";
const CELL_SETTINGS_STORAGE_KEY = "grafy.workbench.cellCanvasSettings.v1";

interface StoredCellCanvasSettings {
  look?: Partial<CellGlassLook>;
  routing?: Partial<CellRoutingOptions>;
}

function subscribeToNothing(): () => void {
  return () => {};
}

function serverCanvasEngine(): WorkbenchCanvasEngineKind {
  return DEFAULT_WORKBENCH_CANVAS_ENGINE;
}

type CanvasGridSettingsContextValue = {
  settings: CanvasGridSettings;
  setSettings: React.Dispatch<React.SetStateAction<CanvasGridSettings>>;
  patchSettings: (patch: Partial<CanvasGridSettings>) => void;
  cellLook: CellGlassLook;
  patchCellLook: (patch: Partial<CellGlassLook>) => void;
  cellRouting: CellRoutingOptions;
  patchCellRouting: (patch: Partial<CellRoutingOptions>) => void;
  resetSettings: () => void;
  /** Active canvas surface implementation ("react-flow" | "cell-canvas"). */
  canvasEngine: WorkbenchCanvasEngineKind;
  setCanvasEngine: (engine: WorkbenchCanvasEngineKind) => void;
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

function readStoredCellSettings(): {
  look: CellGlassLook;
  routing: CellRoutingOptions;
} {
  if (typeof window === "undefined") {
    return {
      look: { ...DEFAULT_CELL_GLASS_LOOK },
      routing: { ...DEFAULT_CELL_ROUTING },
    };
  }
  try {
    const raw = window.localStorage.getItem(CELL_SETTINGS_STORAGE_KEY);
    if (!raw) {
      return {
        look: { ...DEFAULT_CELL_GLASS_LOOK },
        routing: { ...DEFAULT_CELL_ROUTING },
      };
    }
    const parsed = JSON.parse(raw) as StoredCellCanvasSettings | null;
    return {
      look: normalizeCellGlassLook(parsed?.look),
      routing: normalizeCellRouting(parsed?.routing),
    };
  } catch {
    return {
      look: { ...DEFAULT_CELL_GLASS_LOOK },
      routing: { ...DEFAULT_CELL_ROUTING },
    };
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
  const [cellSettings, setCellSettings] = React.useState(() =>
    readStoredCellSettings(),
  );
  // The server renders the default engine; hydration then switches to the stored engine.
  const storedCanvasEngine = React.useSyncExternalStore(
    subscribeToNothing,
    readCanvasEnginePreference,
    serverCanvasEngine,
  );
  const [chosenCanvasEngine, setCanvasEngineState] =
    React.useState<WorkbenchCanvasEngineKind | null>(null);
  const canvasEngine = chosenCanvasEngine ?? storedCanvasEngine;
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
    try {
      window.localStorage.setItem(
        CELL_SETTINGS_STORAGE_KEY,
        JSON.stringify(cellSettings),
      );
    } catch {
      // Ignore quota / private-mode failures; in-memory settings still work.
    }
  }, [cellSettings]);

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

  const setCanvasEngine = React.useCallback(
    (engine: WorkbenchCanvasEngineKind) => {
      setCanvasEngineState(engine);
      writeCanvasEnginePreference(engine);
    },
    [],
  );

  const patchSettings = React.useCallback(
    (patch: Partial<CanvasGridSettings>) => {
      setSettings((current) =>
        normalizeCanvasGridSettings({ ...current, ...patch }),
      );
    },
    [],
  );

  const patchCellLook = React.useCallback((patch: Partial<CellGlassLook>) => {
    setCellSettings((current) => ({
      ...current,
      look: normalizeCellGlassLook({ ...current.look, ...patch }),
    }));
  }, []);

  const patchCellRouting = React.useCallback(
    (patch: Partial<CellRoutingOptions>) => {
      setCellSettings((current) => ({
        ...current,
        routing: normalizeCellRouting({ ...current.routing, ...patch }),
      }));
    },
    [],
  );

  const resetSettings = React.useCallback(() => {
    setSettings({ ...DEFAULT_CANVAS_GRID_SETTINGS });
    setCellSettings({
      look: { ...DEFAULT_CELL_GLASS_LOOK },
      routing: { ...DEFAULT_CELL_ROUTING },
    });
    setCanvasEngine(DEFAULT_WORKBENCH_CANVAS_ENGINE);
  }, [setCanvasEngine]);

  const value = React.useMemo(
    () => ({
      settings,
      setSettings,
      patchSettings,
      cellLook: cellSettings.look,
      patchCellLook,
      cellRouting: cellSettings.routing,
      patchCellRouting,
      resetSettings,
      canvasEngine,
      setCanvasEngine,
      bypassSnap,
      panelOpen,
      setPanelOpen,
    }),
    [
      bypassSnap,
      canvasEngine,
      cellSettings.look,
      cellSettings.routing,
      panelOpen,
      patchCellLook,
      patchCellRouting,
      patchSettings,
      resetSettings,
      setCanvasEngine,
      settings,
    ],
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
