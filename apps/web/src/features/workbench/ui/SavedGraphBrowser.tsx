"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  Check,
  LoaderCircle,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  X,
} from "lucide-react";

import { graphCountLabel } from "@/features/workspaces/WorkspaceGraphPanel";
import type { SavedGraphSummary } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";

const s = stylex.create({
  browser: {
    position: "absolute",
    zIndex: 30,
    top: "66px",
    left: "13px",
    width: "350px",
    maxHeight: "min(650px, calc(100vh - 92px))",
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "9px",
    backgroundColor: tokens.colorSurface,
    boxShadow: tokens.shadowNode,
    color: tokens.colorText,
  },
  header: {
    minHeight: "43px",
    display: "flex",
    alignItems: "center",
    gap: "7px",
    padding: "6px 7px 6px 11px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  title: { flex: 1, fontSize: tokens.fontSizeSm, fontWeight: 750 },
  headerButton: {
    minWidth: "26px",
    height: "27px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "5px",
    paddingInline: "7px",
    borderWidth: 0,
    borderRadius: "4px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
      ":disabled": "transparent",
    },
    color: { default: tokens.colorMuted, ":disabled": tokens.colorTextDisabled },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
  },
  searchWrap: {
    position: "relative",
    padding: "9px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  searchIcon: {
    position: "absolute",
    top: "19px",
    left: "19px",
    color: tokens.colorSubtle,
  },
  search: {
    width: "100%",
    height: "32px",
    padding: "0 9px 0 29px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: { default: tokens.colorBorderStrong, ":focus": tokens.colorAccent },
    borderRadius: "5px",
    outline: "none",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
  },
  list: { minHeight: 0, overflowY: "auto", padding: "4px 0" },
  item: {
    display: "grid",
    gridTemplateColumns: "minmax(0,1fr) 32px",
    alignItems: "stretch",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  itemActive: { backgroundColor: tokens.colorAccentSoft },
  openButton: {
    minWidth: 0,
    minHeight: "57px",
    display: "grid",
    gridTemplateColumns: "16px minmax(0,1fr)",
    alignItems: "center",
    gap: "8px",
    padding: "8px 4px 8px 11px",
    borderWidth: 0,
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
      ":disabled": "transparent",
    },
    color: { default: tokens.colorText, ":disabled": tokens.colorTextDisabled },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    textAlign: "left",
  },
  stateIcon: { color: tokens.colorAccent },
  copy: { minWidth: 0, display: "grid", gap: "3px" },
  name: {
    overflow: "hidden",
    fontSize: tokens.fontSizeSm,
    fontWeight: 720,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  meta: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.3,
  },
  deleteButton: {
    width: "32px",
    borderWidth: 0,
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorDangerHover,
      ":disabled": "transparent",
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorDanger, ":disabled": tokens.colorTextDisabled },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
  },
  message: {
    padding: "22px 18px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
    textAlign: "center",
  },
  error: { color: tokens.colorDanger },
  spinner: {
    animationName: "grafy-spin",
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});

function updatedLabel(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "updated recently";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export interface SavedGraphBrowserProps {
  graphs: readonly SavedGraphSummary[];
  activeGraphId: string | null;
  openingGraphId: string | null;
  deletingGraphId: string | null;
  busy: boolean;
  loading: boolean;
  refreshing: boolean;
  error: string | null;
  onClose: () => void;
  onNew: () => void;
  onOpen: (graphId: string) => void;
  onDelete: (graph: SavedGraphSummary) => void;
  onRefresh: () => void;
}

export function SavedGraphBrowser({
  graphs,
  activeGraphId,
  openingGraphId,
  deletingGraphId,
  busy,
  loading,
  refreshing,
  error,
  onClose,
  onNew,
  onOpen,
  onDelete,
  onRefresh,
}: SavedGraphBrowserProps) {
  const [query, setQuery] = React.useState("");
  const normalizedQuery = query.trim().toLowerCase();
  const filteredGraphs = graphs.filter(
    (graph) =>
      !normalizedQuery || graph.name.toLowerCase().includes(normalizedQuery),
  );

  return (
    <aside aria-label="Saved graphs" {...stylex.props(s.browser)}>
      <header {...stylex.props(s.header)}>
        <h2 {...stylex.props(s.title)}>Saved graphs</h2>
        <button
          type="button"
          disabled={busy}
          {...stylex.props(s.headerButton)}
          onClick={onNew}
        >
          <Plus size={12} /> New
        </button>
        <button
          type="button"
          aria-label="Refresh saved graphs"
          title="Refresh saved graphs"
          disabled={refreshing}
          {...stylex.props(s.headerButton)}
          onClick={onRefresh}
        >
          <RefreshCw size={12} {...stylex.props(refreshing ? s.spinner : null)} />
        </button>
        <button
          type="button"
          aria-label="Close saved graphs"
          {...stylex.props(s.headerButton)}
          onClick={onClose}
        >
          <X size={13} />
        </button>
      </header>

      <div {...stylex.props(s.searchWrap)}>
        <Search size={12} {...stylex.props(s.searchIcon)} />
        <input
          autoFocus
          aria-label="Search saved graphs"
          value={query}
          placeholder="Search saved graphs…"
          {...stylex.props(s.search)}
          onChange={(event) => setQuery(event.currentTarget.value)}
        />
      </div>

      <div role="list" {...stylex.props(s.list)}>
        {error ? (
          <p {...stylex.props(s.message, s.error)}>{error}</p>
        ) : loading ? (
          <p {...stylex.props(s.message)}>Loading saved graphs…</p>
        ) : filteredGraphs.length ? (
          filteredGraphs.map((graph) => {
            const active = graph.id === activeGraphId;
            const opening = graph.id === openingGraphId;
            const deleting = graph.id === deletingGraphId;
            return (
              <div
                key={graph.id}
                role="listitem"
                {...stylex.props(s.item, active ? s.itemActive : null)}
              >
                <button
                  type="button"
                  disabled={busy || opening || deleting}
                  title={`Updated ${updatedLabel(graph.updated_at)}`}
                  {...stylex.props(s.openButton)}
                  onClick={() => onOpen(graph.id)}
                >
                  {opening || deleting ? (
                    <LoaderCircle size={13} {...stylex.props(s.stateIcon, s.spinner)} />
                  ) : active ? (
                    <Check size={13} {...stylex.props(s.stateIcon)} />
                  ) : (
                    <span />
                  )}
                  <span {...stylex.props(s.copy)}>
                    <span {...stylex.props(s.name)}>{graph.name}</span>
                    <span {...stylex.props(s.meta)}>
                      {graphCountLabel(graph)} · r{graph.revision}
                    </span>
                  </span>
                </button>
                <button
                  type="button"
                  aria-label={`Delete ${graph.name}`}
                  title={`Delete ${graph.name}`}
                  disabled={busy || opening || deleting}
                  {...stylex.props(s.deleteButton)}
                  onClick={() => onDelete(graph)}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            );
          })
        ) : (
          <p {...stylex.props(s.message)}>
            {normalizedQuery ? "No saved graphs match your search." : "No saved graphs yet."}
          </p>
        )}
      </div>
    </aside>
  );
}
