"use client";

import * as React from "react";

import type {
  PresenceCollaborator,
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
