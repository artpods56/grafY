"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { SlidersHorizontal } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Menu,
  MenuCheckboxItem,
  MenuContent,
  MenuGroup,
  MenuLabel,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
  MenuTrigger,
} from "@/components/ui/menu";
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
            <Button
              key={source.id}
              ref={(element) => {
                if (element) chips.current.set(source.id, element);
                else chips.current.delete(source.id);
              }}
              variant="ghost"
              size="sm"
              tabIndex={active ? 0 : -1}
              aria-label={`${source.title}, ${nodeCount(count)}`}
              pressed={active}
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
              xstyle={[s.chip, active ? s.chipActive : null]}
            >
              {source.title}
              <span aria-hidden="true" {...stylex.props(s.count)}>
                {count}
              </span>
            </Button>
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
  return (
    <Menu>
      <MenuTrigger
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
      </MenuTrigger>
      <MenuContent
        side="bottom"
        align="end"
        sideOffset={6}
        positionerXstyle={s.aboveDialog}
      >
        <MenuCheckboxItem
          checked={inputNodesOnly}
          onCheckedChange={(checked) => onInputNodesOnlyChange(checked)}
          closeOnClick={false}
        >
          Starts a workflow
        </MenuCheckboxItem>
        <MenuSeparator />
        <MenuGroup>
          <MenuLabel>Takes or makes</MenuLabel>
          <MenuRadioGroup
            value={artifactFilterId ?? ""}
            onValueChange={(value: string) =>
              onArtifactFilterChange(value || null)
            }
          >
            {[{ id: "", title: "Any type" }, ...artifactOptions].map(
              (option) => (
                <MenuRadioItem key={option.id} value={option.id} closeOnClick>
                  {option.title}
                </MenuRadioItem>
              ),
            )}
          </MenuRadioGroup>
        </MenuGroup>
      </MenuContent>
    </Menu>
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
  /** The node picker is a dialog at z-index 100, so its menu has to paint above that. */
  aboveDialog: { zIndex: 110 },
});
