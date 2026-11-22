"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";
import type { CellRoutingOptions } from "./cell-model";
import {
  DEFAULT_CANVAS_LAB,
  encodeCanvasLab,
  readCanvasLab,
  type CanvasLabSettings,
} from "./canvas-lab";

type CanvasLabContextValue = {
  enabled: boolean;
  settings: CanvasLabSettings;
  routing: CellRoutingOptions;
  showHelp: boolean;
  change: (patch: Partial<CanvasLabSettings>) => void;
  reset: () => void;
  panelOpen: boolean;
  setPanelOpen: React.Dispatch<React.SetStateAction<boolean>>;
};

const CanvasLabContext = React.createContext<CanvasLabContextValue | null>(
  null,
);
const LEGACY_SETTINGS_KEY = "grafy.workbench.cellCanvasSettings.v1";

export function replaceLabQuery(update: (params: URLSearchParams) => void) {
  const url = new URL(window.location.href);
  update(url.searchParams);
  if (url.href !== window.location.href) {
    window.history.replaceState(null, "", url);
  }
}

function readGridPreference() {
  try {
    const stored = window.localStorage.getItem(LEGACY_SETTINGS_KEY);
    const settings: { look?: { grid?: unknown } } | null = JSON.parse(
      stored ?? "null",
    );
    if (typeof settings?.look?.grid === "boolean") return settings.look.grid;
  } catch {
    // Storage is optional.
  }
  return DEFAULT_CANVAS_LAB.grid;
}

const subscribeGrid = (notify: () => void) => {
  window.addEventListener("storage", notify);
  return () => window.removeEventListener("storage", notify);
};

export function CanvasLabProvider({
  sandbox = false,
  children,
}: {
  sandbox?: boolean;
  children: React.ReactNode;
}) {
  const [panelOpen, setPanelOpen] = React.useState(false);
  const params = useSearchParams();
  const lab = params.get("lab");
  const showHelp = params.get("help") === "1";
  const enabled =
    sandbox ||
    (process.env.NODE_ENV === "development" &&
      (process.env.NEXT_PUBLIC_GRAFY_DEV_LO === "1" ||
        lab === "1" ||
        lab?.startsWith("1:") === true));
  const grid = React.useSyncExternalStore(
    subscribeGrid,
    readGridPreference,
    () => DEFAULT_CANVAS_LAB.grid,
  );
  const defaults = React.useMemo(
    () => (sandbox ? DEFAULT_CANVAS_LAB : { ...DEFAULT_CANVAS_LAB, grid }),
    [grid, sandbox],
  );
  const settings = React.useMemo(
    () => readCanvasLab(enabled ? lab : null, defaults),
    [defaults, enabled, lab],
  );
  const { exits, underCards, depth } = settings;
  const routing = React.useMemo(
    () => ({ exits, underCards, depth }),
    [exits, underCards, depth],
  );
  const change = React.useCallback(
    (patch: Partial<CanvasLabSettings>) => {
      if (!enabled) return;
      replaceLabQuery((query) => {
        const current = readCanvasLab(query.get("lab"), defaults);
        query.set("lab", encodeCanvasLab({ ...current, ...patch }, defaults));
      });
    },
    [defaults, enabled],
  );
  const reset = React.useCallback(() => {
    if (enabled) replaceLabQuery((query) => query.set("lab", "1"));
  }, [enabled]);
  return (
    <CanvasLabContext.Provider
      value={{
        enabled,
        settings,
        routing,
        showHelp,
        change,
        reset,
        panelOpen,
        setPanelOpen,
      }}
    >
      {children}
    </CanvasLabContext.Provider>
  );
}

export function useCanvasLab(): CanvasLabContextValue {
  const value = React.useContext(CanvasLabContext);
  if (!value) throw new Error("useCanvasLab requires a CanvasLabProvider");
  return value;
}
