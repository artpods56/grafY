"use client";

import * as React from "react";

import { useMediaQuery } from "@/hooks/use-media-query";

/**
 * Where the workbench side panel is and what it shows.
 *
 * The panel is a fixed column beside the Workspace rail, so its width has to
 * reach the workbench shell, which reserves the space with the same
 * custom-property mechanism the rail already uses. Preferences live in local
 * storage and are mirrored onto `<html>`, so CSS can lay out the shell before
 * React paints the next frame.
 *
 * A wide viewport docks the panel and keeps the user's open choice. A narrow one
 * slides it over the canvas and forgets it, because a drawer remembered as open
 * would cover the canvas on every visit.
 */

export const SIDE_PANEL_DEFAULT_WIDTH = 276;
export const SIDE_PANEL_MIN_WIDTH = 240;
export const SIDE_PANEL_MAX_WIDTH = 420;

/** Below this width the panel slides over the canvas instead of docking. */
export const SIDE_PANEL_DOCK_QUERY = "(min-width: 1100px)";
/** Above this width the panel opens on its own the first time. */
export const SIDE_PANEL_AUTO_OPEN_QUERY = "(min-width: 1280px)";

export const SIDE_PANEL_VIEWS = ["artifacts", "templates"] as const;
export type SidePanelViewId = (typeof SIDE_PANEL_VIEWS)[number];

const OPEN_KEY = "grafy-side-panel-open";
const VIEW_KEY = "grafy-side-panel-view";
const WIDTH_KEY = "grafy-side-panel-width";
const COLLAPSED_FOLDERS_KEY = "grafy-library-folders-collapsed";

const listeners = new Set<() => void>();
let overlayOpen = false;

function notify(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStored(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Ignore storage errors.
  }
}

export function clampSidePanelWidth(width: number): number {
  if (!Number.isFinite(width)) return SIDE_PANEL_DEFAULT_WIDTH;
  return Math.min(SIDE_PANEL_MAX_WIDTH, Math.max(SIDE_PANEL_MIN_WIDTH, width));
}

function readDockedOpen(): boolean {
  const stored = readStored(OPEN_KEY);
  if (stored === "1") return true;
  if (stored === "0") return false;
  return (
    typeof window.matchMedia === "function" &&
    window.matchMedia(SIDE_PANEL_AUTO_OPEN_QUERY).matches
  );
}

function readView(): SidePanelViewId {
  const stored = readStored(VIEW_KEY);
  return SIDE_PANEL_VIEWS.find((view) => view === stored) ?? "artifacts";
}

function readWidth(): number {
  const stored = Number(readStored(WIDTH_KEY));
  return Number.isFinite(stored) && stored > 0
    ? clampSidePanelWidth(stored)
    : SIDE_PANEL_DEFAULT_WIDTH;
}

/** Mirrors the docked state onto `<html>` so the shell can reserve its width. */
function publishToDocument(dockedAndOpen: boolean, width: number): void {
  const root = document.documentElement;
  root.dataset.sidePanel = dockedAndOpen ? "open" : "closed";
  if (dockedAndOpen) {
    root.style.setProperty(
      "--grafy-side-panel-expanded-width",
      `${Math.round(width)}px`,
    );
  }
}

export interface WorkbenchSidePanelState {
  /** The viewport is wide enough to dock the panel beside the canvas. */
  docked: boolean;
  /** Docked preference on a wide viewport, slide-over state on a narrow one. */
  open: boolean;
  width: number;
  view: SidePanelViewId;
  setOpen: (next: boolean) => void;
  toggle: () => void;
  setWidth: (next: number) => void;
  setView: (next: SidePanelViewId) => void;
}

export function useWorkbenchSidePanel(): WorkbenchSidePanelState {
  const docked = useMediaQuery(SIDE_PANEL_DOCK_QUERY);
  const dockedOpen = React.useSyncExternalStore(
    subscribe,
    readDockedOpen,
    () => false,
  );
  const slidOpen = React.useSyncExternalStore(
    subscribe,
    () => overlayOpen,
    () => false,
  );
  const view = React.useSyncExternalStore(
    subscribe,
    readView,
    (): SidePanelViewId => "artifacts",
  );
  const width = React.useSyncExternalStore(
    subscribe,
    readWidth,
    () => SIDE_PANEL_DEFAULT_WIDTH,
  );

  const open = docked ? dockedOpen : slidOpen;

  React.useEffect(() => {
    publishToDocument(docked && open, width);
  }, [docked, open, width]);

  // A panel that slides over the canvas must not survive the trip to a wide
  // viewport, where it would otherwise open as a docked column nobody asked for.
  React.useEffect(() => {
    if (docked && overlayOpen) {
      overlayOpen = false;
      notify();
    }
  }, [docked]);

  const setOpen = React.useCallback(
    (next: boolean) => {
      if (docked) writeStored(OPEN_KEY, next ? "1" : "0");
      else overlayOpen = next;
      notify();
    },
    [docked],
  );

  const toggle = React.useCallback(() => setOpen(!open), [open, setOpen]);

  const setWidth = React.useCallback((next: number) => {
    writeStored(WIDTH_KEY, String(Math.round(clampSidePanelWidth(next))));
    notify();
  }, []);

  const setView = React.useCallback((next: SidePanelViewId) => {
    writeStored(VIEW_KEY, next);
    notify();
  }, []);

  return { docked, open, width, view, setOpen, toggle, setWidth, setView };
}

/** Writes a width straight to the document while a resize drag is running. */
export function previewSidePanelWidth(width: number): void {
  document.documentElement.style.setProperty(
    "--grafy-side-panel-expanded-width",
    `${Math.round(clampSidePanelWidth(width))}px`,
  );
}

export function beginSidePanelResize(): void {
  document.body.classList.add("grafy-side-panel-resizing");
}

export function endSidePanelResize(): void {
  document.body.classList.remove("grafy-side-panel-resizing");
}

/**
 * Which Library folders are collapsed. Expansion defaults to open, so only the
 * exceptions are stored and a folder that appears later starts expanded.
 */
export function useCollapsedFolderKeys(): [
  Set<string>,
  (key: string, collapsed: boolean) => void,
] {
  const collapsed = React.useSyncExternalStore(
    subscribe,
    readCollapsedKeys,
    () => EMPTY_KEYS,
  );

  const setCollapsed = React.useCallback((key: string, next: boolean) => {
    const current = readCollapsedKeys();
    if (next) current.add(key);
    else current.delete(key);
    writeStored(COLLAPSED_FOLDERS_KEY, JSON.stringify([...current]));
    notify();
  }, []);

  return [collapsed, setCollapsed];
}

const EMPTY_KEYS = new Set<string>();
let collapsedCache: { raw: string | null; keys: Set<string> } | null = null;

function readCollapsedKeys(): Set<string> {
  const raw = readStored(COLLAPSED_FOLDERS_KEY);
  if (collapsedCache?.raw === raw) return collapsedCache.keys;
  const keys = new Set<string>(raw === null ? [] : parseKeys(raw));
  collapsedCache = { raw, keys };
  return keys;
}

function parseKeys(raw: string): string[] {
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((key): key is string => typeof key === "string")
      : [];
  } catch {
    return [];
  }
}
