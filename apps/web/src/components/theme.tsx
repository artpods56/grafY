"use client";

import * as React from "react";

export type ThemePreference = "light" | "dark" | "system";
export type ResolvedTheme = "light" | "dark";

const STORAGE_KEY = "grafy-theme";
const LEGACY_STORAGE_KEY = "ns-theme";

interface ThemeContextValue {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (preference: ThemePreference) => void;
  cycleTheme: () => void;
}

const ThemeContext = React.createContext<ThemeContextValue | null>(null);

/*
 * Both theme inputs live outside React (localStorage and the OS color
 * scheme), so they are exposed through useSyncExternalStore. The server
 * snapshots return the defaults ("system", light), which keeps SSR output
 * deterministic; the inline script in layout.tsx applies the real
 * color-scheme before first paint so there is no visible flash.
 */

const preferenceListeners = new Set<() => void>();

function subscribePreference(listener: () => void): () => void {
  preferenceListeners.add(listener);
  return () => preferenceListeners.delete(listener);
}

function readStoredPreference(): ThemePreference {
  try {
    const stored =
      window.localStorage.getItem(STORAGE_KEY) ??
      window.localStorage.getItem(LEGACY_STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "system") {
      return stored;
    }
  } catch {
    // Ignore storage errors.
  }
  return "system";
}

function writeStoredPreference(next: ThemePreference) {
  try {
    window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Ignore storage errors.
  }
  for (const listener of preferenceListeners) listener();
}

const SYSTEM_DARK_QUERY = "(prefers-color-scheme: dark)";

function subscribeSystemDark(listener: () => void): () => void {
  const media = window.matchMedia(SYSTEM_DARK_QUERY);
  media.addEventListener("change", listener);
  return () => media.removeEventListener("change", listener);
}

function applyResolvedTheme(resolved: ResolvedTheme) {
  const root = document.documentElement;
  // StyleX tokens store `light-dark()` inside CSS variables. Engines treat
  // that as an invalid color (transparent fills) when the used scheme is the
  // dual `light dark` value from `:root`. Always pin a single scheme.
  root.style.colorScheme = resolved;
  root.dataset.theme = resolved;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const preference = React.useSyncExternalStore(
    subscribePreference,
    readStoredPreference,
    () => "system" as const,
  );
  const systemDark = React.useSyncExternalStore(
    subscribeSystemDark,
    () => window.matchMedia(SYSTEM_DARK_QUERY).matches,
    () => false,
  );

  const resolved: ResolvedTheme =
    preference === "system" ? (systemDark ? "dark" : "light") : preference;

  React.useEffect(() => {
    applyResolvedTheme(resolved);
  }, [resolved]);

  const setPreference = React.useCallback((next: ThemePreference) => {
    writeStoredPreference(next);
  }, []);

  const cycleTheme = React.useCallback(() => {
    setPreference(
      preference === "light" ? "dark" : preference === "dark" ? "system" : "light",
    );
  }, [preference, setPreference]);

  const value = React.useMemo(
    () => ({ preference, resolved, setPreference, cycleTheme }),
    [preference, resolved, setPreference, cycleTheme],
  );

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = React.useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within ThemeProvider");
  }
  return context;
}
