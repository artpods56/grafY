"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ArrowLeft, ExternalLink, Pencil, Plus, Trash2 } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import type { GraphDefinition } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { graphDeleteRefusal } from "../model/project-graphs";

/**
 * The floating bar that switches between the Graphs of the open Project.
 *
 * It is controlled: it owns no Graph state and sends no command of its own, so
 * the Workbench stays the only writer of the Project. Rename and delete go
 * through `window`, which is what the rest of this app does for a one-field
 * question; a delete that another Graph still calls is refused here, in the
 * same words the caller would get from the server.
 *
 * Call navigation is likewise reported, not decided: when the canvas holds one
 * selected call node the bar offers to open the callee Graph, and when this view
 * was reached through calls a Back row offers the way out. The Workbench keeps
 * the trail.
 */
export interface GraphSwitcherProps {
  graphs: readonly GraphDefinition[];
  openGraphId: string | null;
  /** False while the room cannot take commands or the person may not edit. */
  canEdit: boolean;
  onOpen: (graphId: string) => void;
  onAdd: () => void;
  onRename: (graphId: string, name: string) => void;
  onDelete: (graphId: string) => void;
  /** The one call node that is selected on the canvas, if exactly one is. */
  selectedCall?: {
    nodeId: string;
    calleeGraphId: string;
    calleeName: string;
  } | null;
  /** Given alongside `selectedCall`: looking into the callee Graph is always allowed. */
  onOpenCall?: (nodeId: string, calleeGraphId: string) => void;
  /**
   * The Graphs this view was reached through, outermost first. Empty or absent
   * when the open Graph was opened directly.
   */
  callTrail?: readonly { graphId: string; nodeId: string; name: string }[];
  /** Given alongside a non-empty `callTrail`: return to the caller Graph. */
  onBackFromCall?: () => void;
}

const s = stylex.create({
  root: {
    position: "absolute",
    // On a phone the app's own header sits over the canvas; stay below it.
    top: {
      default: "12px",
      "@media (max-width: 720px)":
        "calc(var(--grafy-mobile-overlay-top, 68px) + env(safe-area-inset-top))",
    },
    left: "12px",
    zIndex: 20,
    display: "flex",
    flexDirection: "column",
    gap: "6px",
    maxWidth: "calc(100% - 24px)",
  },
  bar: {
    display: "flex",
    alignItems: "center",
    gap: "2px",
    padding: "3px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorSurfaceRaised,
  },
  /**
   * The Back row, above the bar. Same surface so the two read as one floating
   * group rather than two unrelated widgets.
   */
  backRow: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "3px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorSurfaceRaised,
  },
  /** Where the call came from, spelled out: `Main › Report › Clean`. */
  trail: {
    fontSize: tokens.fontSizeXs,
    color: tokens.colorMuted,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  /** The Graphs row. It takes the leftover width and scrolls when they overflow. */
  tabs: {
    display: "flex",
    alignItems: "center",
    overflowX: "auto",
    minWidth: 0,
  },
  tab: {
    margin: 0,
    boxSizing: "border-box",
    height: "28px",
    paddingInline: "10px",
    maxWidth: "160px",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
    lineHeight: 1,
    cursor: "pointer",
  },
  tabSelected: {
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorTextEmphasis,
  },
  tabUnselected: {
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorHover,
    },
    color: tokens.colorMuted,
  },
});

export function GraphSwitcher({
  graphs,
  openGraphId,
  canEdit,
  onOpen,
  onAdd,
  onRename,
  onDelete,
  selectedCall,
  onOpenCall,
  callTrail,
  onBackFromCall,
}: GraphSwitcherProps): React.ReactElement {
  /** Which Graph the last refused delete was for, or none. */
  const [refusalFor, setRefusalFor] = React.useState<string | null>(null);
  const openGraph = graphs.find((graph) => graph.id === openGraphId) ?? null;

  // Derived, never stored: the words follow the current `graphs`, and the
  // notice goes away by itself once another Graph is open.
  const refusal =
    refusalFor !== null && refusalFor === openGraphId
      ? graphDeleteRefusal(graphs, refusalFor)
      : null;

  // The Back row goes home to the innermost caller, and only the trail beyond
  // it is worth spelling out — with one entry the button already names it.
  const backTo = callTrail?.[callTrail.length - 1];
  const trailText =
    callTrail !== undefined && callTrail.length >= 2
      ? [...callTrail.map((entry) => entry.name), openGraph?.name ?? ""].join(
          " › ",
        )
      : null;

  return (
    <div {...stylex.props(s.root)}>
      {backTo !== undefined && onBackFromCall !== undefined ? (
        <div {...stylex.props(s.backRow)}>
          <Button variant="ghost" size="xs" onClick={onBackFromCall}>
            <ArrowLeft size={12} />
            Back to “{backTo.name}”
          </Button>
          {trailText !== null ? (
            <span {...stylex.props(s.trail)}>{trailText}</span>
          ) : null}
        </div>
      ) : null}
      <div {...stylex.props(s.bar)}>
        <div
          role="tablist"
          aria-label="Graphs in this Project"
          {...stylex.props(s.tabs)}
        >
          {graphs.map((graph) => {
            const selected = graph.id === openGraphId;
            return (
              <button
                key={graph.id}
                type="button"
                role="tab"
                aria-selected={selected}
                {...stylex.props(
                  s.tab,
                  selected ? s.tabSelected : s.tabUnselected,
                )}
                onClick={() => {
                  if (!selected) onOpen(graph.id);
                }}
              >
                {graph.name}
              </button>
            );
          })}
        </div>
        <IconButton label="Add Graph" disabled={!canEdit} onClick={onAdd}>
          <Plus size={14} />
        </IconButton>
        <IconButton
          label="Rename Graph"
          disabled={!canEdit || openGraph === null}
          onClick={() => {
            if (openGraph === null) return;
            const answer = window.prompt("Rename Graph", openGraph.name);
            if (answer === null) return;
            const name = answer.trim().slice(0, 160);
            if (name === "" || name === openGraph.name) return;
            onRename(openGraph.id, name);
          }}
        >
          <Pencil size={14} />
        </IconButton>
        <IconButton
          label="Delete Graph"
          disabled={!canEdit || openGraph === null}
          onClick={() => {
            if (openGraph === null) return;
            const reason = graphDeleteRefusal(graphs, openGraph.id);
            if (reason !== null) {
              setRefusalFor(openGraph.id);
              return;
            }
            if (
              window.confirm(
                `Delete “${openGraph.name}”? You can bring it back by restoring an earlier checkpoint.`,
              )
            ) {
              onDelete(openGraph.id);
            }
          }}
        >
          <Trash2 size={14} />
        </IconButton>
        {selectedCall && onOpenCall ? (
          <IconButton
            label={`Open call to “${selectedCall.calleeName}”`}
            onClick={() => {
              onOpenCall(selectedCall.nodeId, selectedCall.calleeGraphId);
            }}
          >
            <ExternalLink size={14} />
          </IconButton>
        ) : null}
      </div>
      {refusal !== null ? (
        <Notice tone="warning" onDismiss={() => setRefusalFor(null)}>
          {refusal}
        </Notice>
      ) : null}
    </div>
  );
}
