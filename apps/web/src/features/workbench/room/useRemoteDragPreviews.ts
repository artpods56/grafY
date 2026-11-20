"use client";

import * as React from "react";

import type { ProjectRoomPresenceStore } from "./presence-store";
import { REMOTE_DRAG_RELEASE_HOLD_MS } from "./remote-drag-preview";
import { useRemoteDragTargets } from "./usePresenceStore";

/**
 * Remote drag preview positions at presence sample rate (~20Hz).
 * Avoids per-frame React updates (which break React Flow drag init / #015).
 * Visual easing between samples is handled with a short CSS transition on the node.
 */
export function useRemoteDragPreviews(
  store: ProjectRoomPresenceStore,
  graphId: string | null,
  localDraggingNodeIds: ReadonlySet<string>,
): Record<string, { x: number; y: number }> {
  const targets = useRemoteDragTargets(store, graphId);
  const [positions, setPositions] = React.useState<
    Record<string, { x: number; y: number }>
  >({});
  const heldRef = React.useRef<Record<string, { x: number; y: number }>>({});
  const releaseTimersRef = React.useRef(new Map<string, number>());

  React.useEffect(() => {
    const releaseTimers = releaseTimersRef.current;
    return () => {
      for (const timer of releaseTimers.values()) {
        window.clearTimeout(timer);
      }
      releaseTimers.clear();
    };
  }, []);

  React.useEffect(() => {
    const live: Record<string, { x: number; y: number }> = {
      ...heldRef.current,
    };

    for (const [nodeId, position] of targets) {
      if (localDraggingNodeIds.has(nodeId)) continue;
      const timer = releaseTimersRef.current.get(nodeId);
      if (timer !== undefined) {
        window.clearTimeout(timer);
        releaseTimersRef.current.delete(nodeId);
      }
      live[nodeId] = { x: position.x, y: position.y };
      delete heldRef.current[nodeId];
    }

    for (const nodeId of Object.keys(live)) {
      if (targets.has(nodeId) || localDraggingNodeIds.has(nodeId)) continue;
      if (releaseTimersRef.current.has(nodeId)) continue;
      heldRef.current[nodeId] = live[nodeId]!;
      const timer = window.setTimeout(() => {
        releaseTimersRef.current.delete(nodeId);
        delete heldRef.current[nodeId];
        setPositions((current) => {
          if (!(nodeId in current)) return current;
          const next = { ...current };
          delete next[nodeId];
          return next;
        });
      }, REMOTE_DRAG_RELEASE_HOLD_MS);
      releaseTimersRef.current.set(nodeId, timer);
    }

    for (const nodeId of localDraggingNodeIds) {
      delete live[nodeId];
      delete heldRef.current[nodeId];
      const timer = releaseTimersRef.current.get(nodeId);
      if (timer !== undefined) {
        window.clearTimeout(timer);
        releaseTimersRef.current.delete(nodeId);
      }
    }

    setPositions((current) => (samePositions(current, live) ? current : live));
  }, [localDraggingNodeIds, targets]);

  return positions;
}

function samePositions(
  left: Record<string, { x: number; y: number }>,
  right: Record<string, { x: number; y: number }>,
): boolean {
  const leftKeys = Object.keys(left);
  const rightKeys = Object.keys(right);
  if (leftKeys.length !== rightKeys.length) return false;
  for (const key of leftKeys) {
    const a = left[key];
    const b = right[key];
    if (!b || a!.x !== b.x || a!.y !== b.y) return false;
  }
  return true;
}
