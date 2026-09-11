"use client";

import * as React from "react";
import { Search, X } from "lucide-react";
import { useRouter } from "next/navigation";

import { useSavedGraphs } from "@/hooks/use-api";
import {
  FINE_POINTER_QUERY,
  useMediaQuery,
} from "@/hooks/use-media-query";
import type { SavedGraphSummary } from "@/lib/api";
import { workbenchGraphPath } from "@/features/workbench/routes";
import { GraphRowMenu } from "./GraphRowMenu";

export type WorkspaceGraphPanelCloseReason =
  "close-button" | "escape" | "graph-selected" | "outside-pointer";


export function sortGraphsByRecency(
  graphs: readonly SavedGraphSummary[],
): readonly SavedGraphSummary[] {
  return [...graphs].sort(
    (left, right) => Date.parse(right.updated_at) - Date.parse(left.updated_at),
  );
}

export function filterGraphsByQuery(
  graphs: readonly SavedGraphSummary[],
  query: string,
): readonly SavedGraphSummary[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return graphs;
  return graphs.filter((graph) => graph.name.toLowerCase().includes(needle));
}

/** Relative age, coarse enough to stay stable without a re-render timer. */
export function graphAgeLabel(updatedAt: string, now = Date.now()): string {
  const elapsed = now - Date.parse(updatedAt);
  if (!Number.isFinite(elapsed)) return "";
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(updatedAt).toLocaleDateString();
}

/**
 * The one node/edge summary line every graph discovery surface renders.
 *
 * Counts describe the collaborative draft head, so a head that is ahead of the
 * saved checkpoint is labelled instead of being presented as saved metadata.
 */
export function graphCountLabel(graph: {
  node_count: number;
  edge_count: number;
  draft_pending?: boolean;
}): string {
  const nodes = `${graph.node_count} ${graph.node_count === 1 ? "node" : "nodes"}`;
  const edges = `${graph.edge_count} ${graph.edge_count === 1 ? "edge" : "edges"}`;
  const summary = `${nodes} · ${edges}`;
  return graph.draft_pending ? `${summary} · unsaved draft` : summary;
}

export function WorkspaceGraphPanel({
  workspaceId,
  workspaceSlug,
  activeGraphId,
  busyGraphId = null,
  onRename,
  onDelete,
  onClose,
}: {
  workspaceId: string;
  workspaceSlug: string;
  activeGraphId: string | null;
  busyGraphId?: string | null;
  onRename: (graph: SavedGraphSummary) => void;
  onDelete: (graph: SavedGraphSummary) => void;
  onClose: (reason: WorkspaceGraphPanelCloseReason) => void;
}) {
  const router = useRouter();
  const { data, isLoading, isValidating } = useSavedGraphs(workspaceId);
  const isRefreshing = isValidating && Boolean(data);
  const finePointer = useMediaQuery(FINE_POINTER_QUERY);
  const [query, setQuery] = React.useState("");
  const panelRef = React.useRef<HTMLDivElement | null>(null);
  const searchRef = React.useRef<HTMLInputElement | null>(null);
  const autoFocusAttemptedRef = React.useRef(false);

  React.useEffect(() => {
    if (autoFocusAttemptedRef.current) return;
    autoFocusAttemptedRef.current = true;
    if (finePointer) searchRef.current?.focus();
  }, [finePointer]);

  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose("escape");
    };
    const onPointerDown = (event: PointerEvent) => {
      const panel = panelRef.current;
      if (!panel) return;
      const target = event.target;
      if (!(target instanceof Node) || panel.contains(target)) return;
      // The rail trigger toggles itself; closing here would re-open it.
      if (
        target instanceof Element &&
        (target.closest("[data-graph-panel-trigger]") ||
          target.closest(".grafy-workspace-rail__account-menu"))
      ) {
        return;
      }
      onClose("outside-pointer");
    };
    document.addEventListener("keydown", onKeyDown);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [onClose]);

  const graphs = React.useMemo(
    () => filterGraphsByQuery(sortGraphsByRecency(data?.graphs ?? []), query),
    [data, query],
  );
  const total = data?.graphs.length ?? 0;

  const openGraph = (graphId: string) => {
    router.push(workbenchGraphPath(workspaceSlug, graphId));
    onClose("graph-selected");
  };

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label="Quick graph switcher"
      className="grafy-graph-panel"
    >
      <div className="grafy-graph-panel__header">
        <p className="grafy-graph-panel__title">
          Quick switch
          {total > 0 ? (
            <span className="grafy-graph-panel__count">{total}</span>
          ) : null}
          {isRefreshing ? (
            <span
              className="grafy-graph-panel__count"
              role="status"
              aria-live="polite"
            >
              Refreshing…
            </span>
          ) : null}
        </p>
        <button
          type="button"
          className="grafy-graph-panel__icon-button"
          aria-label="Close quick graph switcher"
          onClick={() => onClose("close-button")}
        >
          <X size={14} aria-hidden="true" />
        </button>
      </div>

      <div className="grafy-graph-panel__search">
        <Search size={14} aria-hidden="true" />
        <input
          ref={searchRef}
          type="search"
          value={query}
          placeholder="Search graphs"
          aria-label="Search graphs"
          onChange={(event) => setQuery(event.currentTarget.value)}
        />
      </div>

      <div className="grafy-graph-panel__list">
        {isLoading ? (
          <p className="grafy-graph-panel__empty">Loading graphs…</p>
        ) : graphs.length === 0 ? (
          <p className="grafy-graph-panel__empty">
            {query.trim()
              ? "No graphs match that search."
              : "No graphs in this location yet. Use New graph in the sidebar to start one."}
          </p>
        ) : (
          graphs.map((graph) => (
            <div
              key={graph.id}
              className={`grafy-graph-panel__row${activeGraphId === graph.id ? " is-active" : ""}`}
            >
              <button
                type="button"
                className="grafy-graph-panel__row-open"
                onClick={() => openGraph(graph.id)}
              >
                <span className="grafy-graph-panel__row-name">{graph.name}</span>
                <span className="grafy-graph-panel__row-meta">
                  {`${graphAgeLabel(graph.updated_at)} · ${graphCountLabel(graph)}`}
                </span>
              </button>
              <GraphRowMenu
                graph={graph}
                busy={busyGraphId === graph.id}
                onRename={onRename}
                onDelete={onDelete}
              />
            </div>
          ))
        )}
      </div>
    </div>
  );
}
