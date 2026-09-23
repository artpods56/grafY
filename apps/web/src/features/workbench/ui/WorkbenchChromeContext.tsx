"use client";

import * as React from "react";

import type { SavedGraphSummary } from "@/lib/api";

export interface WorkbenchChromeValue {
  activeGraphId: string | null;
  graphName: string;
  isDirty: boolean;
  saving: boolean;
  canSave: boolean;
  save: () => Promise<void>;
  renameGraph: (graph: SavedGraphSummary, name: string) => Promise<void>;
  deleteGraph: (graph: SavedGraphSummary) => Promise<void>;
}

/**
 * The workbench and the workspace rail are siblings under WorkspaceLayout, so
 * chrome cannot travel through React context. The open workbench publishes here;
 * the rail reads it with useSyncExternalStore.
 */
let publishedChrome: WorkbenchChromeValue | null = null;
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot(): WorkbenchChromeValue | null {
  return publishedChrome;
}

export function publishWorkbenchChrome(
  value: WorkbenchChromeValue | null,
): void {
  publishedChrome = value;
  for (const listener of listeners) listener();
}

export function useWorkbenchChrome(): WorkbenchChromeValue | null {
  return React.useSyncExternalStore(subscribe, getSnapshot, () => null);
}

/** Keeps the rail's chrome store in sync for the lifetime of the workbench. */
export function usePublishWorkbenchChrome(value: WorkbenchChromeValue): void {
  React.useEffect(() => {
    publishWorkbenchChrome(value);
  }, [value]);

  React.useEffect(() => {
    return () => {
      publishWorkbenchChrome(null);
    };
  }, []);
}
