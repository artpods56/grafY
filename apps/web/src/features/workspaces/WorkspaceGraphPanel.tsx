"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Search, X } from "lucide-react";
import { useRouter } from "next/navigation";

import { IconButton } from "@/components/ui/button";
import { phoneTouch } from "@/components/ui/touch-target";
import { useWorkspaceProjects } from "@/hooks/use-api";
import { FINE_POINTER_QUERY, useMediaQuery } from "@/hooks/use-media-query";
import type { SavedGraphSummary } from "@/lib/api";
import { workbenchProjectPath } from "@/features/workbench/routes";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { GraphRowMenu } from "./GraphRowMenu";
import { graphRowMarker } from "./workspace-rail.stylex";

/**
 * Floating quick-project switcher panel beside the rail.
 */
const panelStyles = stylex.create({
  panel: {
    position: "fixed",
    zIndex: 60,
    top: "12px",
    left: "calc(var(--grafy-rail-width) + 10px)",
    width: "276px",
    maxHeight: "calc(100svh - 24px)",
    display: "flex",
    flexDirection: "column",
    gap: "8px",
    padding: "14px 12px 12px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    boxShadow: tokens.shadowNodeDragged,
    "@media (max-width: 620px)": {
      top: "calc(var(--grafy-mobile-header-height) + 8px + env(safe-area-inset-top))",
      right: "calc(12px + env(safe-area-inset-right))",
      left: "calc(12px + env(safe-area-inset-left))",
      width: "auto",
      maxHeight:
        "calc(100dvh - var(--grafy-mobile-header-height) - 20px - env(safe-area-inset-top) - env(safe-area-inset-bottom))",
    },
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    paddingInline: "4px",
  },
  title: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 600,
  },
  count: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
    fontVariantNumeric: "tabular-nums",
  },
  search: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    minHeight: "34px",
    paddingInline: "10px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorBorder,
      ":focus-within": tokens.colorAccentBorder,
    },
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorBg,
    color: tokens.colorSubtle,
    "@media (max-width: 620px)": {
      minHeight: "44px",
    },
  },
  searchInput: {
    width: "100%",
    minWidth: 0,
    border: 0,
    outline: "none",
    background: "transparent",
    color: tokens.colorText,
    fontFamily: "inherit",
    fontSize: tokens.fontSizeMd,
    "@media (max-width: 620px)": {
      height: "44px",
    },
  },
  list: {
    display: "grid",
    alignContent: "start",
    gap: "1px",
    overflowX: "hidden",
    overflowY: "auto",
    marginTop: "2px",
    paddingTop: "8px",
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  empty: {
    padding: "10px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
  },
  row: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    alignItems: "center",
    gap: "2px",
    padding: "2px 4px 2px 2px",
    borderRadius: tokens.radiusSm,
    ":hover": {
      backgroundColor: tokens.colorHover,
    },
  },
  rowActive: {
    backgroundColor: tokens.colorAccentSoft,
  },
  rowOpen: {
    display: "grid",
    gap: "2px",
    minWidth: 0,
    padding: "5px 6px",
    border: 0,
    borderRadius: tokens.radiusSm,
    background: "transparent",
    cursor: "pointer",
    textAlign: "left",
    "@media (max-width: 620px)": {
      minHeight: "44px",
    },
  },
  rowName: {
    overflow: "hidden",
    color: tokens.colorText,
    fontSize: tokens.fontSizeMd,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  rowNameActive: {
    color: tokens.colorTextEmphasis,
    fontWeight: 500,
  },
  rowMeta: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
});

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

/** Node and edge counts describe the durable live head. */
export function graphCountLabel(graph: {
  node_count: number;
  edge_count: number;
}): string {
  const nodes = `${graph.node_count} ${graph.node_count === 1 ? "node" : "nodes"}`;
  const edges = `${graph.edge_count} ${graph.edge_count === 1 ? "edge" : "edges"}`;
  return `${nodes} · ${edges}`;
}

export function WorkspaceGraphPanel({
  workspaceId,
  workspaceSlug,
  activeGraphId,
  busyGraphId = null,
  onExport,
  onRename,
  onDelete,
  onClose,
}: {
  workspaceId: string;
  workspaceSlug: string;
  activeGraphId: string | null;
  busyGraphId?: string | null;
  onExport?: (graph: SavedGraphSummary) => void;
  onRename: (graph: SavedGraphSummary) => void;
  onDelete: (graph: SavedGraphSummary) => void;
  onClose: (reason: WorkspaceGraphPanelCloseReason) => void;
}) {
  const router = useRouter();
  const { data, isLoading, isValidating } = useWorkspaceProjects(workspaceId);
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
          target.closest("[data-account-menu]"))
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

  // A browser row is a Project: it lists by name and opens at the Project's own
  // address. How many Graphs it holds is shown on the row, not walked here.
  const projects = React.useMemo(
    () => filterGraphsByQuery(sortGraphsByRecency(data?.projects ?? []), query),
    [data, query],
  );
  const total = data?.projects.length ?? 0;

  const openProject = (projectId: string) => {
    router.push(workbenchProjectPath(workspaceSlug, projectId));
    onClose("graph-selected");
  };

  return (
    <div
      ref={panelRef}
      role="dialog"
      aria-label="Quick project switcher"
      className={stylex.props(panelStyles.panel).className}
    >
      <div className={stylex.props(panelStyles.header).className}>
        <p className={stylex.props(panelStyles.title).className}>
          Quick switch
          {total > 0 ? (
            <span className={stylex.props(panelStyles.count).className}>
              {total}
            </span>
          ) : null}
          {isRefreshing ? (
            <span
              className={stylex.props(panelStyles.count).className}
              role="status"
              aria-live="polite"
            >
              Refreshing…
            </span>
          ) : null}
        </p>
        <IconButton
          label="Close quick project switcher"
          size="sm"
          xstyle={phoneTouch.square}
          onClick={() => onClose("close-button")}
        >
          <X size={14} aria-hidden="true" />
        </IconButton>
      </div>

      <div className={stylex.props(panelStyles.search).className}>
        <Search size={14} aria-hidden="true" />
        <input
          ref={searchRef}
          type="search"
          value={query}
          placeholder="Search projects"
          aria-label="Search projects"
          onChange={(event) => setQuery(event.currentTarget.value)}
          className={stylex.props(panelStyles.searchInput).className}
        />
      </div>

      <div className={stylex.props(panelStyles.list).className}>
        {isLoading ? (
          <p className={stylex.props(panelStyles.empty).className}>
            Loading projects…
          </p>
        ) : projects.length === 0 ? (
          <p className={stylex.props(panelStyles.empty).className}>
            {query.trim()
              ? "No projects match that search."
              : "No projects in this location yet. Use New project in the sidebar to start one."}
          </p>
        ) : (
          projects.map((project) => (
            <div
              key={project.id}
              className={
                stylex.props(
                  panelStyles.row,
                  graphRowMarker,
                  activeGraphId === project.id && panelStyles.rowActive,
                ).className
              }
              data-active={activeGraphId === project.id ? true : undefined}
            >
              <button
                type="button"
                className={stylex.props(panelStyles.rowOpen).className}
                onClick={() => openProject(project.id)}
              >
                <span
                  className={
                    stylex.props(
                      panelStyles.rowName,
                      activeGraphId === project.id && panelStyles.rowNameActive,
                    ).className
                  }
                >
                  {project.name}
                </span>
                <span className={stylex.props(panelStyles.rowMeta).className}>
                  {`${graphAgeLabel(project.updated_at)} · ${graphCountLabel(project)}`}
                </span>
              </button>
              <GraphRowMenu
                graph={project}
                busy={busyGraphId === project.id}
                tone="surface"
                onExport={onExport}
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
