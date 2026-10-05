"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Menu } from "@base-ui/react/menu";
import { Check, SlidersHorizontal } from "lucide-react";

import { overlay } from "@/lib/stylex/overlay.stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { CatalogFilter } from "../../model/node-catalog";

function nodeCount(count: number): string {
  return `${count} ${count === 1 ? "node" : "nodes"}`;
}

/**
 * Where the nodes come from, as one row of chips with their counts, and the
 * rarely needed refinements folded into a Filters menu at its end. The same
 * row serves every width: on a phone it scrolls sideways.
 */
export function NodeSourceBar({
  sources,
  counts,
  activeSourceId,
  artifactOptions,
  artifactFilterId,
  inputNodesOnly,
  onSelectSource,
  onArtifactFilterChange,
  onInputNodesOnlyChange,
}: {
  sources: readonly CatalogFilter[];
  counts: ReadonlyMap<string, number>;
  activeSourceId: string;
  artifactOptions: readonly CatalogFilter[];
  artifactFilterId: string | null;
  inputNodesOnly: boolean;
  onSelectSource: (id: string) => void;
  onArtifactFilterChange: (id: string | null) => void;
  onInputNodesOnlyChange: (inputNodesOnly: boolean) => void;
}) {
  const chips = React.useRef(new Map<string, HTMLButtonElement>());

  function focusSourceAt(index: number): void {
    const bounded = Math.max(0, Math.min(index, sources.length - 1));
    const next = sources[bounded];
    if (!next) return;
    onSelectSource(next.id);
    const chip = chips.current.get(next.id);
    chip?.focus();
    chip?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }

  return (
    <div {...stylex.props(s.bar)}>
      <div
        role="toolbar"
        aria-label="Node sources"
        aria-orientation="horizontal"
        {...stylex.props(s.chips)}
      >
        {sources.map((source, index) => {
          const active = source.id === activeSourceId;
          const count = counts.get(source.id) ?? 0;
          return (
            <button
              key={source.id}
              ref={(element) => {
                if (element) chips.current.set(source.id, element);
                else chips.current.delete(source.id);
              }}
              type="button"
              tabIndex={active ? 0 : -1}
              aria-label={`${source.title}, ${nodeCount(count)}`}
              aria-pressed={active}
              data-source-id={source.id}
              onClick={() => onSelectSource(source.id)}
              onKeyDown={(event) => {
                const step =
                  event.key === "ArrowRight" || event.key === "ArrowDown"
                    ? 1
                    : event.key === "ArrowLeft" || event.key === "ArrowUp"
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
              {...stylex.props(s.chip, active && s.chipActive)}
            >
              {source.title}
              <span aria-hidden="true" {...stylex.props(s.count)}>
                {count}
              </span>
            </button>
          );
        })}
      </div>
      <FiltersMenu
        artifactOptions={artifactOptions}
        artifactFilterId={artifactFilterId}
        inputNodesOnly={inputNodesOnly}
        onArtifactFilterChange={onArtifactFilterChange}
        onInputNodesOnlyChange={onInputNodesOnlyChange}
      />
    </div>
  );
}

function FiltersMenu({
  artifactOptions,
  artifactFilterId,
  inputNodesOnly,
  onArtifactFilterChange,
  onInputNodesOnlyChange,
}: {
  artifactOptions: readonly CatalogFilter[];
  artifactFilterId: string | null;
  inputNodesOnly: boolean;
  onArtifactFilterChange: (id: string | null) => void;
  onInputNodesOnlyChange: (inputNodesOnly: boolean) => void;
}) {
  const active = Number(artifactFilterId !== null) + Number(inputNodesOnly);
  const popup = stylex.props(overlay.popup, s.menu);
  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label={active ? `Filters, ${active} on` : "Filters"}
        title="Filters"
        {...stylex.props(s.filtersButton, active > 0 && s.filtersButtonOn)}
      >
        <SlidersHorizontal size={14} aria-hidden="true" />
        {active ? (
          <span aria-hidden="true" {...stylex.props(s.badge)}>
            {active}
          </span>
        ) : null}
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner
          side="bottom"
          align="end"
          sideOffset={6}
          collisionPadding={8}
          {...stylex.props(s.positioner)}
        >
          <Menu.Popup {...popup}>
            <Menu.CheckboxItem
              checked={inputNodesOnly}
              onCheckedChange={(checked) => onInputNodesOnlyChange(checked)}
              closeOnClick={false}
              {...stylex.props(overlay.item, s.item)}
            >
              <span {...stylex.props(s.check)}>
                <Menu.CheckboxItemIndicator>
                  <Check size={13} aria-hidden="true" />
                </Menu.CheckboxItemIndicator>
              </span>
              Starts a workflow
            </Menu.CheckboxItem>
            <Menu.Separator {...stylex.props(s.separator)} />
            <Menu.Group>
              <Menu.GroupLabel {...stylex.props(s.groupLabel)}>
                Takes or makes
              </Menu.GroupLabel>
              <Menu.RadioGroup
                value={artifactFilterId ?? ""}
                onValueChange={(value: string) =>
                  onArtifactFilterChange(value || null)
                }
              >
                {[{ id: "", title: "Any type" }, ...artifactOptions].map(
                  (option) => (
                    <Menu.RadioItem
                      key={option.id}
                      value={option.id}
                      closeOnClick
                      {...stylex.props(overlay.item, s.item)}
                    >
                      <span {...stylex.props(s.check)}>
                        <Menu.RadioItemIndicator>
                          <Check size={13} aria-hidden="true" />
                        </Menu.RadioItemIndicator>
                      </span>
                      {option.title}
                    </Menu.RadioItem>
                  ),
                )}
              </Menu.RadioGroup>
            </Menu.Group>
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}

const s = stylex.create({
  bar: {
    flexShrink: 0,
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "0 12px 10px",
  },
  chips: {
    minWidth: 0,
    flex: 1,
    display: "flex",
    gap: "4px",
    overflowX: "auto",
    scrollbarWidth: "none",
    // Room for a chip's focus ring inside the scroller.
    padding: "2px",
    margin: "-2px",
  },
  chip: {
    flexShrink: 0,
    height: { default: "28px", "@media (pointer: coarse)": "36px" },
    display: "inline-flex",
    alignItems: "center",
    gap: "6px",
    paddingInline: "10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "transparent",
    borderRadius: "99px",
    backgroundColor: {
      default: tokens.colorSurfaceSunken,
      ":hover": tokens.colorHoverStrong,
    },
    color: { default: tokens.colorMuted, ":hover": tokens.colorText },
    cursor: "pointer",
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
    fontWeight: 540,
    whiteSpace: "nowrap",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "1px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
  },
  chipActive: {
    borderColor: tokens.colorBorderStrong,
    backgroundColor: {
      default: tokens.colorBg,
      ":hover": tokens.colorBg,
    },
    color: {
      default: tokens.colorTextEmphasis,
      ":hover": tokens.colorTextEmphasis,
    },
  },
  count: {
    color: tokens.colorSubtle,
    fontSize: "10.5px",
    fontVariantNumeric: "tabular-nums",
  },
  filtersButton: {
    position: "relative",
    flexShrink: 0,
    width: { default: "30px", "@media (pointer: coarse)": "38px" },
    height: { default: "28px", "@media (pointer: coarse)": "36px" },
    display: "grid",
    placeItems: "center",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "8px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: { default: tokens.colorMuted, ":hover": tokens.colorText },
    cursor: "pointer",
    outlineColor: tokens.colorAccent,
    outlineStyle: "solid",
    outlineOffset: "1px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
  },
  filtersButtonOn: {
    borderColor: tokens.colorBorderStrong,
    color: tokens.colorTextEmphasis,
  },
  badge: {
    position: "absolute",
    top: "-6px",
    right: "-6px",
    minWidth: "16px",
    height: "16px",
    display: "grid",
    placeItems: "center",
    paddingInline: "4px",
    borderRadius: "99px",
    backgroundColor: tokens.colorAccent,
    color: tokens.colorOnAccent,
    fontSize: "10px",
    fontWeight: 700,
  },
  positioner: { zIndex: 100, outline: "none" },
  menu: {
    display: "grid",
    gap: "1px",
    minWidth: "220px",
    maxHeight: "min(420px, var(--available-height))",
    overflowY: "auto",
    padding: "4px",
    outline: "none",
  },
  item: {
    minHeight: { default: "28px", "@media (pointer: coarse)": "40px" },
    display: "flex",
    alignItems: "center",
    gap: "6px",
    padding: "0 10px 0 6px",
    borderRadius: "5px",
    color: tokens.colorText,
    cursor: "default",
    fontSize: tokens.fontSizeSm,
    outline: "none",
    userSelect: "none",
    backgroundColor: {
      default: "transparent",
      ":is([data-highlighted])": tokens.colorHover,
    },
  },
  check: {
    width: "16px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
  },
  separator: {
    height: "1px",
    margin: "4px 2px",
    backgroundColor: tokens.colorDivider,
  },
  groupLabel: {
    padding: "6px 8px 4px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 720,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
});
