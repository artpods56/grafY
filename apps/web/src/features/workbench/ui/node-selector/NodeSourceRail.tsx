"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { LayoutGrid, LibraryBig, Settings2 } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";
import type { CatalogFilter } from "../../model/node-catalog";

const REFINEMENTS_ID = "node-selector-refinements";

function nodeCount(count: number): string {
  return `${count} ${count === 1 ? "node" : "nodes"}`;
}

/**
 * Where the picker's nodes come from, and how to narrow them. Wide, the
 * sources are a column with their counts; narrow, they fold into a select and
 * the refinements hide behind a Filters toggle.
 */
export function NodeSourceRail({
  sources,
  counts,
  activeSourceId,
  horizontal,
  artifactOptions,
  artifactFilterId,
  inputNodesOnly,
  filtersOpen,
  hidden,
  onSelectSource,
  onArtifactFilterChange,
  onInputNodesOnlyChange,
  onFiltersOpenChange,
}: {
  sources: readonly CatalogFilter[];
  counts: ReadonlyMap<string, number>;
  activeSourceId: string;
  /** The toolbar runs sideways in the phone layout. */
  horizontal: boolean;
  artifactOptions: readonly CatalogFilter[];
  artifactFilterId: string | null;
  inputNodesOnly: boolean;
  filtersOpen: boolean;
  hidden: boolean;
  onSelectSource: (id: string) => void;
  onArtifactFilterChange: (id: string | null) => void;
  onInputNodesOnlyChange: (inputNodesOnly: boolean) => void;
  onFiltersOpenChange: (open: boolean) => void;
}) {
  const buttons = React.useRef(new Map<string, HTMLButtonElement>());
  const refinementCount =
    Number(artifactFilterId !== null) + Number(inputNodesOnly);

  function focusSourceAt(index: number): void {
    const bounded = Math.max(0, Math.min(index, sources.length - 1));
    const next = sources[bounded];
    if (!next) return;
    onSelectSource(next.id);
    buttons.current.get(next.id)?.focus();
  }

  return (
    <nav
      aria-label="Node filters"
      {...stylex.props(s.pane, hidden && s.hidden)}
    >
      <div {...stylex.props(s.compact)}>
        <select
          aria-label="Node source"
          value={activeSourceId}
          onChange={(event) => onSelectSource(event.currentTarget.value)}
          {...stylex.props(s.select)}
        >
          {sources.map((source) => (
            <option key={source.id} value={source.id}>
              {source.id === "all" ? "All sources" : source.title}
            </option>
          ))}
        </select>
        <button
          type="button"
          aria-expanded={filtersOpen}
          aria-controls={REFINEMENTS_ID}
          onClick={() => onFiltersOpenChange(!filtersOpen)}
          {...stylex.props(s.filtersButton)}
        >
          <Settings2 size={14} aria-hidden="true" />
          Filters{refinementCount ? ` (${refinementCount})` : ""}
        </button>
      </div>

      <div {...stylex.props(s.sources)}>
        <h3 {...stylex.props(s.heading)}>Source</h3>
        <div
          role="toolbar"
          aria-label="Node sources"
          aria-orientation={horizontal ? "horizontal" : "vertical"}
          {...stylex.props(s.toolbar)}
        >
          {sources.map((source, index) => {
            const active = source.id === activeSourceId;
            const count = counts.get(source.id) ?? 0;
            const library = source.id === "workspace-library";
            return (
              <button
                key={source.id}
                ref={(element) => {
                  if (element) buttons.current.set(source.id, element);
                  else buttons.current.delete(source.id);
                }}
                type="button"
                tabIndex={active ? 0 : -1}
                aria-label={`${source.title}, ${nodeCount(count)}`}
                aria-pressed={active}
                data-source-id={source.id}
                onClick={() => onSelectSource(source.id)}
                onKeyDown={(event) => {
                  const step =
                    event.key === "ArrowDown" || event.key === "ArrowRight"
                      ? 1
                      : event.key === "ArrowUp" || event.key === "ArrowLeft"
                        ? -1
                        : 0;
                  if (step !== 0) {
                    event.preventDefault();
                    focusSourceAt(index + step);
                  } else if (event.key === "Home") {
                    event.preventDefault();
                    focusSourceAt(0);
                  } else if (event.key === "End") {
                    event.preventDefault();
                    focusSourceAt(sources.length - 1);
                  }
                }}
                {...stylex.props(
                  s.source,
                  library && s.sourceLibrary,
                  active && s.sourceActive,
                )}
              >
                {source.id === "all" ? (
                  <LayoutGrid
                    size={13}
                    aria-hidden="true"
                    {...stylex.props(s.icon)}
                  />
                ) : library ? (
                  <LibraryBig
                    size={13}
                    aria-hidden="true"
                    {...stylex.props(s.icon)}
                  />
                ) : null}
                <span {...stylex.props(s.sourceTitle)}>{source.title}</span>
                <span aria-hidden="true" {...stylex.props(s.count)}>
                  {count}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      <div
        id={REFINEMENTS_ID}
        {...stylex.props(s.refinements, !filtersOpen && s.refinementsFolded)}
      >
        <label {...stylex.props(s.field)}>
          <span>Artifact</span>
          <select
            aria-label="Artifact type"
            value={artifactFilterId ?? ""}
            onChange={(event) =>
              onArtifactFilterChange(event.currentTarget.value || null)
            }
            {...stylex.props(s.select)}
          >
            <option value="">Any artifact</option>
            {artifactOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.title}
              </option>
            ))}
          </select>
        </label>
        <label {...stylex.props(s.check)}>
          <input
            type="checkbox"
            checked={inputNodesOnly}
            onChange={(event) =>
              onInputNodesOnlyChange(event.currentTarget.checked)
            }
          />
          Input nodes only
        </label>
      </div>
    </nav>
  );
}

const s = stylex.create({
  pane: {
    gridArea: "filters",
    minWidth: 0,
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
    gap: { default: "14px", "@media (max-width: 1024px)": "8px" },
    padding: {
      default: "12px 8px",
      "@media (max-width: 1024px)": "8px 12px",
    },
    borderRightWidth: { default: 1, "@media (max-width: 1024px)": 0 },
    borderRightStyle: "solid",
    borderRightColor: tokens.colorBorder,
    borderBottomWidth: { default: 0, "@media (max-width: 1024px)": 1 },
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
    overflowY: "auto",
  },
  hidden: { display: "none" },
  compact: {
    display: { default: "none", "@media (max-width: 1024px)": "flex" },
    alignItems: "center",
    gap: "8px",
  },
  filtersButton: {
    minHeight: "40px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    flexShrink: 0,
    paddingInline: "10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: tokens.radiusSm,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    cursor: "pointer",
  },
  sources: {
    display: { default: "block", "@media (max-width: 1024px)": "none" },
  },
  heading: {
    margin: "0 0 6px",
    paddingInline: "8px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 760,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  toolbar: { display: "grid", gap: "1px" },
  source: {
    width: "100%",
    minHeight: "30px",
    display: "flex",
    alignItems: "center",
    gap: "7px",
    paddingInline: "8px",
    borderWidth: 0,
    borderRadius: tokens.radiusSm,
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: { default: tokens.colorMuted, ":hover": tokens.colorText },
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
    fontWeight: 540,
    textAlign: "left",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "-2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
  },
  /** The Workspace library is modules, not a plugin: it sits apart. */
  sourceLibrary: {
    marginTop: "8px",
    position: "relative",
    "::before": {
      content: "''",
      position: "absolute",
      insetInline: "8px",
      top: "-5px",
      height: "1px",
      backgroundColor: tokens.colorDivider,
    },
  },
  sourceActive: {
    backgroundColor: {
      default: tokens.colorSurfaceRaised,
      ":hover": tokens.colorSurfaceRaised,
    },
    boxShadow: `inset 0 0 0 1px ${tokens.colorBorder}`,
    color: {
      default: tokens.colorTextEmphasis,
      ":hover": tokens.colorTextEmphasis,
    },
    fontWeight: 620,
  },
  icon: { flexShrink: 0 },
  sourceTitle: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  count: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontSize: "10.5px",
    fontVariantNumeric: "tabular-nums",
  },
  refinements: {
    display: "grid",
    gap: "10px",
    paddingTop: { default: "12px", "@media (max-width: 1024px)": 0 },
    paddingInline: { default: "8px", "@media (max-width: 1024px)": 0 },
    borderTopWidth: { default: 1, "@media (max-width: 1024px)": 0 },
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
  },
  refinementsFolded: {
    display: { default: "grid", "@media (max-width: 1024px)": "none" },
  },
  field: {
    display: "grid",
    gap: "4px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 680,
  },
  select: {
    width: "100%",
    minHeight: { default: "30px", "@media (max-width: 1024px)": "40px" },
    padding: "0 8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    cursor: "pointer",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "2px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
  },
  check: {
    minHeight: { default: "24px", "@media (max-width: 1024px)": "40px" },
    display: "flex",
    alignItems: "center",
    gap: "7px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 640,
    cursor: "pointer",
  },
});
