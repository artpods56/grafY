"use client";

import * as React from "react";

import type { TransientNodePosition } from "./protocol";
import type {
  PresenceCollaborator,
  PresenceCursorSample,
  ProjectRoomPresenceStore,
} from "./presence-store";

export function usePresenceCollaborators(
  store: ProjectRoomPresenceStore,
  graphId: string | null,
): readonly PresenceCollaborator[] {
  const getSnapshot = React.useCallback(
    () => store.getCollaborators(graphId),
    [graphId, store],
  );
  return React.useSyncExternalStore(store.subscribe, getSnapshot, getSnapshot);
}

export function usePresenceCursorSamples(
  store: ProjectRoomPresenceStore,
  graphId: string | null,
): readonly PresenceCursorSample[] {
  const getSnapshot = React.useCallback(
    () => store.getCursorSamples(graphId),
    [graphId, store],
  );
  return React.useSyncExternalStore(store.subscribe, getSnapshot, getSnapshot);
}

export function useRemoteSelectionColors(
  store: ProjectRoomPresenceStore,
  graphId: string | null,
): ReadonlyMap<string, string> {
  const getSnapshot = React.useCallback(
    () => store.getRemoteSelectionColors(graphId),
    [graphId, store],
  );
  return React.useSyncExternalStore(store.subscribe, getSnapshot, getSnapshot);
}

export function useRemoteDragTargets(
  store: ProjectRoomPresenceStore,
  graphId: string | null,
): ReadonlyMap<string, TransientNodePosition> {
  const getSnapshot = React.useCallback(
    () => store.getRemoteDragTargets(graphId),
    [graphId, store],
  );
  return React.useSyncExternalStore(store.subscribe, getSnapshot, getSnapshot);
}
