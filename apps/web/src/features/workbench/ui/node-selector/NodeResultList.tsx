"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Cable } from "lucide-react";

import type { NodeSpec } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { catalogNodeKey } from "../../model/node-catalog";

export const RESULTS_ID = "node-selector-results";

export function resultOptionId(spec: NodeSpec): string {
  return `node-selector-result-${catalogNodeKey(spec)}`;
}

/** A run of results under one heading; an untitled group is a flat list. */
export interface NodeResultGroup {
  key: string;
  title: string | null;
  nodes: readonly NodeSpec[];
}

/**
 * The listbox of nodes: one line each, the name and what it does. Keyboard
 * focus normally stays in the search field and the active row is announced
 * through `aria-activedescendant`; a row takes focus itself only when the
 * phone layout returns to the list.
 */
export function NodeResultList({
  label,
  status,
  errorMessage,
  loading,
  groups,
  activeKey,
  empty,
  footer,
  hidden,
  keepSearchFocus,
  registerOption,
  onActivate,
  onChoose,
  onInsert,
  onRetry,
  onKeyDown,
}: {
  /** What the list holds, for assistive tech: "All nodes", "Text nodes". */
  label: string;
  status: string;
  errorMessage: string | null;
  loading: boolean;
  groups: readonly NodeResultGroup[];
  activeKey: string | null;
  /** What an empty, loaded list says instead of rows. */
  empty: React.ReactNode;
  footer: React.ReactNode;
  hidden: boolean;
  /** With a mouse, pressing a row must not pull focus out of the search. */
  keepSearchFocus: boolean;
  registerOption: (key: string) => (element: HTMLElement | null) => void;
  onActivate: (key: string) => void;
  onChoose: (key: string) => void;
  onInsert: (spec: NodeSpec) => void;
  onRetry?: () => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void;
}) {
  const hasResults = groups.some((group) => group.nodes.length > 0);
  const active = groups
    .flatMap((group) => group.nodes)
    .find((spec) => catalogNodeKey(spec) === activeKey);

  return (
    <section aria-label={label} {...stylex.props(s.pane, hidden && s.hidden)}>
      {/* The count is for screen readers; the chips already show it. */}
      <span
        role={errorMessage ? "alert" : "status"}
        aria-live={errorMessage ? "assertive" : "polite"}
        aria-atomic="true"
        {...stylex.props(s.visuallyHidden)}
      >
        {status}
      </span>
      <div
        id={RESULTS_ID}
        role="listbox"
        aria-label="Node results"
        aria-busy={loading}
        aria-activedescendant={active ? resultOptionId(active) : undefined}
        onKeyDown={onKeyDown}
        {...stylex.props(s.list)}
      >
        {errorMessage ? (
          <div {...stylex.props(s.empty)}>
            <span>Nodes couldn’t be loaded. {errorMessage}</span>
            {onRetry ? (
              <button
                type="button"
                onClick={onRetry}
                {...stylex.props(s.textButton)}
              >
                Try again
              </button>
            ) : null}
          </div>
        ) : loading ? (
          <div {...stylex.props(s.empty)}>Loading nodes…</div>
        ) : hasResults ? (
          groups.map((group) =>
            group.title === null ? (
              <React.Fragment key={group.key}>
                {group.nodes.map((spec) => renderRow(spec))}
              </React.Fragment>
            ) : (
              <div
                key={group.key}
                role="group"
                aria-labelledby={`node-selector-group-${group.key}`}
                {...stylex.props(s.group)}
              >
                <div
                  id={`node-selector-group-${group.key}`}
                  role="presentation"
                  {...stylex.props(s.groupHeading)}
                >
                  {group.title}
                </div>
                {group.nodes.map((spec) => renderRow(spec))}
              </div>
            ),
          )
        ) : (
          <div {...stylex.props(s.empty)}>{empty}</div>
        )}
      </div>
      {footer}
    </section>
  );

  function renderRow(spec: NodeSpec) {
    const key = catalogNodeKey(spec);
    const selected = key === activeKey;
    return (
      <div
        key={key}
        ref={registerOption(key)}
        id={resultOptionId(spec)}
        role="option"
        tabIndex={-1}
        aria-selected={selected}
        title={spec.description || undefined}
        onMouseDown={(event) => {
          if (keepSearchFocus) event.preventDefault();
        }}
        onMouseMove={() => {
          if (!selected && keepSearchFocus) onActivate(key);
        }}
        onClick={() => onChoose(key)}
        onDoubleClick={() => onInsert(spec)}
        {...stylex.props(s.row, selected && s.rowSelected)}
      >
        <span {...stylex.props(s.rowTitle)}>{spec.title}</span>
        {spec.description ? (
          <span {...stylex.props(s.rowDescription)}>{spec.description}</span>
        ) : null}
      </div>
    );
  }
}

/** The strip under the sources when the picker was opened from a port. */
export function CompatibilityNote({
  direction,
  portTitle,
}: {
  direction: "upstream" | "downstream";
  portTitle: string;
}) {
  return (
    <div id="node-selector-compatibility" {...stylex.props(s.note)}>
      <Cable size={12} aria-hidden="true" />
      <span>
        Showing nodes that can connect{" "}
        {direction === "upstream" ? "to" : "from"} <strong>{portTitle}</strong>.
      </span>
    </div>
  );
}

const s = stylex.create({
  pane: {
    gridArea: "nodes",
    minWidth: 0,
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
  },
  hidden: { display: "none" },
  visuallyHidden: {
    position: "absolute",
    width: "1px",
    height: "1px",
    padding: 0,
    margin: "-1px",
    overflow: "hidden",
    clip: "rect(0, 0, 0, 0)",
    whiteSpace: "nowrap",
    borderWidth: 0,
  },
  list: {
    minHeight: 0,
    flex: 1,
    overflowY: "auto",
    overscrollBehavior: "contain",
    display: "flex",
    flexDirection: "column",
    padding: "4px 8px 12px",
    outline: "none",
  },
  group: { display: "flex", flexDirection: "column" },
  groupHeading: {
    position: "sticky",
    top: 0,
    zIndex: 1,
    padding: "12px 10px 4px",
    // The dialog's own surface, so a pinned heading reads as part of the list.
    backgroundColor: tokens.colorSurface,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
  },
  row: {
    width: "100%",
    minWidth: 0,
    minHeight: { default: "34px", "@media (pointer: coarse)": "44px" },
    flexShrink: 0,
    display: "flex",
    alignItems: "baseline",
    gap: "10px",
    padding: "8px 10px",
    borderRadius: "7px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorText,
    cursor: "pointer",
    outline: "none",
    userSelect: "none",
    ":focus-visible": {
      outline: `2px solid ${tokens.colorAccent}`,
      outlineOffset: "-2px",
    },
  },
  rowSelected: {
    backgroundColor: {
      default: tokens.colorHoverStrong,
      ":hover": tokens.colorHoverStrong,
    },
  },
  rowTitle: {
    flexShrink: 0,
    maxWidth: "60%",
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 560,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  rowDescription: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  empty: {
    minHeight: "160px",
    display: "grid",
    placeItems: "center",
    alignContent: "center",
    gap: "10px",
    padding: "24px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
    textAlign: "center",
  },
  textButton: {
    minHeight: "29px",
    paddingInline: "10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "6px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
  },
  note: {
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    gap: "6px",
    margin: "0 12px 8px",
    padding: "6px 10px",
    borderRadius: "7px",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
});
