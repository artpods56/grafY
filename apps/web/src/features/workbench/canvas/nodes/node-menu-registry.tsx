"use client";

import * as React from "react";
import { useNodeId } from "@xyflow/react";

import type { NodeMenuInfo, NodeMenuItem } from "./NodeMenu";

/**
 * What each card's "⋯" menu says, by node id, so the canvas right-click menu
 * can open on the same facts and actions without knowing how any card builds
 * them. A card's menu is mounted while the card is selected; right-clicking a
 * card selects it first, so its entry arrives a render later.
 */

export interface NodeMenuEntry {
  info: NodeMenuInfo;
  items: readonly NodeMenuItem[];
}

export class NodeMenuRegistry {
  private entries = new Map<string, NodeMenuEntry>();
  private listeners = new Set<() => void>();

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  get(nodeId: string): NodeMenuEntry | null {
    return this.entries.get(nodeId) ?? null;
  }

  set(nodeId: string, entry: NodeMenuEntry): void {
    this.entries.set(nodeId, entry);
    this.notify();
  }

  /** Forgets `entry` only if it is still the one on file for `nodeId`. */
  release(nodeId: string, entry: NodeMenuEntry): void {
    if (this.entries.get(nodeId) !== entry) return;
    this.entries.delete(nodeId);
    this.notify();
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}

export const NodeMenuRegistryContext =
  React.createContext<NodeMenuRegistry | null>(null);

/** Files a card's menu under its node. Outside a canvas node it does nothing. */
export function useRegisterNodeMenu(
  info: NodeMenuInfo,
  items: readonly NodeMenuItem[],
): void {
  const registry = React.useContext(NodeMenuRegistryContext);
  const nodeId = useNodeId();
  React.useEffect(() => {
    if (!registry || !nodeId) return;
    const entry = { info, items };
    registry.set(nodeId, entry);
    return () => registry.release(nodeId, entry);
  }, [info, items, nodeId, registry]);
}

export function useNodeMenuEntry(
  registry: NodeMenuRegistry,
  nodeId: string | null,
): NodeMenuEntry | null {
  const getSnapshot = React.useCallback(
    () => (nodeId === null ? null : registry.get(nodeId)),
    [nodeId, registry],
  );
  return React.useSyncExternalStore(
    registry.subscribe,
    getSnapshot,
    () => null,
  );
}
