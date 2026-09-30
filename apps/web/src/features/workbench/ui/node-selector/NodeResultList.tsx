"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Cable } from "lucide-react";

import type { NodeRegistry, NodeSpec, Port } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { artifactTypeColor } from "../../canvas/nodes.css";
import { portArtifactType } from "../../canvas/types";
import { catalogNodeKey } from "../../model/node-catalog";
import { artifactTitleFor } from "../CatalogNodePreview";

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
 * The listbox of nodes. Keyboard focus normally stays in the search field and
 * the active row is announced through `aria-activedescendant`; a row takes
 * focus itself only when the phone layout returns to the list.
 */
export function NodeResultList({
  title,
  status,
  errorMessage,
  loading,
  groups,
  registry,
  activeKey,
  compatibilityNote,
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
  title: string;
  status: string;
  errorMessage: string | null;
  loading: boolean;
  groups: readonly NodeResultGroup[];
  registry: NodeRegistry;
  activeKey: string | null;
  compatibilityNote: React.ReactNode;
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
    <section
      aria-labelledby="node-selector-results-heading"
      {...stylex.props(s.pane, hidden && s.hidden)}
    >
      <header {...stylex.props(s.header)}>
        <h3 id="node-selector-results-heading" {...stylex.props(s.title)}>
          {title}
        </h3>
        <span
          role={errorMessage ? "alert" : "status"}
          aria-live={errorMessage ? "assertive" : "polite"}
          aria-atomic="true"
          {...stylex.props(s.status)}
        >
          {status}
        </span>
      </header>
      {compatibilityNote}
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
                  <span {...stylex.props(s.groupCount)}>
                    {group.nodes.length}
                  </span>
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
        <span {...stylex.props(s.copy)}>
          <span {...stylex.props(s.rowTitleLine)}>
            <span {...stylex.props(s.rowTitle)}>{spec.title}</span>
            <NodeSignature spec={spec} registry={registry} />
          </span>
          <span {...stylex.props(s.rowDescription)}>
            {spec.description || "No description is available."}
          </span>
        </span>
      </div>
    );
  }
}

/** What a node takes and what it makes, as the canvas colours them. */
function NodeSignature({
  spec,
  registry,
}: {
  spec: NodeSpec;
  registry: NodeRegistry;
}) {
  if (!spec.inputs.length && !spec.outputs.length) return null;
  return (
    <span {...stylex.props(s.signature)}>
      {spec.inputs.length ? (
        <SignatureSide ports={spec.inputs} registry={registry} />
      ) : null}
      <span aria-hidden="true" {...stylex.props(s.arrow)}>
        →
      </span>
      {spec.outputs.length ? (
        <SignatureSide ports={spec.outputs} registry={registry} />
      ) : (
        <span {...stylex.props(s.sideLabel)}>end</span>
      )}
    </span>
  );
}

function SignatureSide({
  ports,
  registry,
}: {
  ports: readonly Port[];
  registry: NodeRegistry;
}) {
  const first = ports[0]!;
  const artifactType = portArtifactType(first);
  const color = artifactType
    ? artifactTypeColor(artifactType.id, tokens.colorSubtle)
    : tokens.colorSubtle;
  return (
    <span {...stylex.props(s.side)}>
      <span
        aria-hidden="true"
        {...stylex.props(s.dot, first.shape === "many" && s.dotMany)}
        style={{ color }}
      />
      <span {...stylex.props(s.sideLabel)}>
        {artifactTitleFor(registry, first)}
        {ports.length > 1 ? ` +${ports.length - 1}` : ""}
      </span>
    </span>
  );
}

const s = stylex.create({
  pane: {
    gridArea: "nodes",
    minWidth: 0,
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
    borderRightWidth: { default: 1, "@media (max-width: 720px)": 0 },
    borderRightStyle: "solid",
    borderRightColor: tokens.colorBorder,
  },
  hidden: { display: "none" },
  header: {
    minWidth: 0,
    display: "flex",
    alignItems: "baseline",
    gap: "10px",
    padding: "10px 14px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  title: {
    margin: 0,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 700,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  status: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    whiteSpace: "nowrap",
  },
  list: {
    minHeight: 0,
    flex: 1,
    overflowY: "auto",
    overscrollBehavior: "contain",
    display: "flex",
    flexDirection: "column",
    gap: "1px",
    padding: "4px 6px 8px",
    outline: "none",
  },
  group: { display: "flex", flexDirection: "column", gap: "1px" },
  groupHeading: {
    position: "sticky",
    top: "-4px",
    zIndex: 1,
    display: "flex",
    alignItems: "center",
    gap: "6px",
    marginInline: "-6px",
    padding: "10px 16px 4px",
    backgroundColor: tokens.colorSurface,
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 760,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  groupCount: {
    color: tokens.colorSubtle,
    fontVariantNumeric: "tabular-nums",
    letterSpacing: 0,
    opacity: 0.7,
  },
  row: {
    width: "100%",
    minHeight: "48px",
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    padding: "7px 10px",
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
      default: tokens.colorSurfaceRaised,
      ":hover": tokens.colorSurfaceRaised,
    },
    boxShadow: `inset 0 0 0 1px ${tokens.colorBorderStrong}`,
  },
  copy: { minWidth: 0, flex: 1, display: "grid", gap: "2px" },
  rowTitleLine: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "10px",
  },
  rowTitle: {
    minWidth: 0,
    flexShrink: 1,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 660,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  rowDescription: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  signature: {
    minWidth: 0,
    flexShrink: 100,
    marginLeft: "auto",
    display: "inline-flex",
    alignItems: "center",
    gap: "5px",
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: "10.5px",
    whiteSpace: "nowrap",
  },
  side: {
    minWidth: 0,
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    overflow: "hidden",
  },
  sideLabel: { overflow: "hidden", textOverflow: "ellipsis" },
  arrow: { flexShrink: 0, opacity: 0.7 },
  /** A port's type colour; the canvas draws a sequence as a stack. */
  dot: {
    width: "6px",
    height: "6px",
    flexShrink: 0,
    borderRadius: "99px",
    backgroundColor: "currentColor",
  },
  dotMany: {
    marginRight: "3px",
    boxShadow: "3px 0 0 -1px currentColor",
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
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
  },
});

/** The strip under the header when the picker was opened from a port. */
export function CompatibilityNote({
  direction,
  portTitle,
}: {
  direction: "upstream" | "downstream";
  portTitle: string;
}) {
  return (
    <div id="node-selector-compatibility" {...stylex.props(n.note)}>
      <Cable size={12} aria-hidden="true" />
      <span>
        Showing nodes that can connect{" "}
        {direction === "upstream" ? "to" : "from"} <strong>{portTitle}</strong>.
      </span>
    </div>
  );
}

const n = stylex.create({
  note: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    padding: "7px 14px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },
});
