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
const CELL_SETTINGS_STORAGE_KEY = "grafy.workbench.cellCanvasSettings.v1";

interface StoredCellCanvasSettings {
  look?: Partial<CellGlassLook>;
  routing?: Partial<CellRoutingOptions>;
}

type CanvasGridSettingsContextValue = {
  cellLook: CellGlassLook;
  patchCellLook: (patch: Partial<CellGlassLook>) => void;
  cellRouting: CellRoutingOptions;
  patchCellRouting: (patch: Partial<CellRoutingOptions>) => void;
  resetSettings: () => void;
  panelOpen: boolean;
  setPanelOpen: React.Dispatch<React.SetStateAction<boolean>>;
};

const CanvasGridSettingsContext =
  React.createContext<CanvasGridSettingsContextValue | null>(null);

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
  const [cellSettings, setCellSettings] = React.useState(() =>
    readStoredCellSettings(),
  );
  const [panelOpen, setPanelOpen] = React.useState(false);
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
    setCellSettings({
      look: { ...DEFAULT_CELL_GLASS_LOOK },
      routing: { ...DEFAULT_CELL_ROUTING },
    });
  }, []);

  const value = React.useMemo(
    () => ({
      cellLook: cellSettings.look,
      patchCellLook,
      cellRouting: cellSettings.routing,
      patchCellRouting,
      resetSettings,
      panelOpen,
      setPanelOpen,
    }),
    [
      cellSettings.look,
      cellSettings.routing,
      panelOpen,
      patchCellLook,
      patchCellRouting,
      resetSettings,
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
