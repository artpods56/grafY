"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { LayoutGrid, RotateCcw, Undo2, X } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import {
  SegmentedControl,
  type SegmentedOption,
} from "@/components/ui/segmented-control";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  DEFAULT_CELL_CLEANUP_PARAMS,
  type CellCleanupCardSizePreset,
  type CellCleanupParams,
} from "../cell-canvas/cell-graph-cleanup";
import { CELL_SIZE } from "../cell-canvas/cell-model";

export type CleanupScope = "all" | "selected";

export interface CanvasCleanupPopoverProps {
  readonly params: CellCleanupParams;
  readonly onChange: (next: CellCleanupParams) => void;
  readonly onReset: () => void;
  readonly onApply: (scope: CleanupScope) => void;
  readonly onUndo?: () => void;
  readonly onRevertInitial?: () => void;
  readonly onClose: () => void;
  readonly selectedCount: number;
  readonly canApply: boolean;
  readonly undoCount: number;
}

const CARD_SIZE_OPTIONS: readonly SegmentedOption<CellCleanupCardSizePreset>[] =
  [
    { value: "compact", label: "Compact" },
    { value: "default", label: "Default" },
    { value: "roomy", label: "Roomy" },
  ];

function isDefaultParams(params: CellCleanupParams): boolean {
  return (
    params.resizeCards === DEFAULT_CELL_CLEANUP_PARAMS.resizeCards &&
    params.cardSize === DEFAULT_CELL_CLEANUP_PARAMS.cardSize &&
    params.columnGapCells === DEFAULT_CELL_CLEANUP_PARAMS.columnGapCells &&
    params.laneGapCells === DEFAULT_CELL_CLEANUP_PARAMS.laneGapCells &&
    params.stackGapCells === DEFAULT_CELL_CLEANUP_PARAMS.stackGapCells &&
    params.experimentGapCells ===
      DEFAULT_CELL_CLEANUP_PARAMS.experimentGapCells &&
    params.tuckProviders === DEFAULT_CELL_CLEANUP_PARAMS.tuckProviders &&
    params.alignPorts === DEFAULT_CELL_CLEANUP_PARAMS.alignPorts &&
    params.keepCompanions === DEFAULT_CELL_CLEANUP_PARAMS.keepCompanions &&
    params.clearRouteOffsets === DEFAULT_CELL_CLEANUP_PARAMS.clearRouteOffsets
  );
}

const formatPx = (cells: number) => `${cells * CELL_SIZE}`;

const s = stylex.create({
  panel: {
    position: {
      default: "absolute",
      "@media (max-width: 720px)": "fixed",
    },
    right: {
      default: 0,
      "@media (max-width: 720px)":
        "calc(12px + env(safe-area-inset-right, 0px))",
    },
    left: {
      default: "auto",
      "@media (max-width: 720px)":
        "calc(var(--grafy-rail-width, 0px) + 12px + env(safe-area-inset-left, 0px))",
    },
    bottom: {
      default: "calc(100% + 10px)",
      "@media (max-width: 720px)": "calc(80px + env(safe-area-inset-bottom))",
    },
    zIndex: 45,
    width: {
      default: "296px",
      "@media (max-width: 720px)": "auto",
    },
    maxHeight: "min(520px, calc(100svh - 110px))",
    display: "flex",
    flexDirection: "column",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "light-dark(rgba(15, 23, 42, 0.1), rgba(255, 255, 255, 0.15))",
    borderRadius: tokens.radiusLg,
    backgroundColor:
      "light-dark(rgba(255, 255, 255, 0.96), rgba(30, 35, 44, 0.95))",
    backdropFilter: "blur(14px)",
    WebkitBackdropFilter: "blur(14px)",
    boxShadow: tokens.shadowNodeRaised,
    color: tokens.colorText,
    overflow: "hidden",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    paddingBlock: "9px",
    paddingInline: "12px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    flexShrink: 0,
  },
  titleGroup: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
    minWidth: 0,
  },
  title: {
    margin: 0,
    fontSize: tokens.fontSizeSm,
    fontWeight: 650,
    color: tokens.colorTextEmphasis,
  },
  headerActions: {
    display: "flex",
    alignItems: "center",
    gap: "2px",
    flexShrink: 0,
  },
  body: {
    display: "grid",
    gap: "12px",
    paddingBlock: "10px",
    paddingInline: "12px",
    overflowY: "auto",
    overscrollBehavior: "contain",
    minHeight: 0,
  },
  section: {
    display: "grid",
    gap: "8px",
  },
  sectionHeading: {
    margin: 0,
    fontSize: tokens.fontSizeXs,
    fontWeight: 650,
    letterSpacing: "0.04em",
    textTransform: "uppercase",
    color: tokens.colorSubtle,
  },
  divider: {
    height: "1px",
    backgroundColor: tokens.colorDivider,
  },
  switches: {
    display: "grid",
    gap: "7px",
  },
  footer: {
    display: "grid",
    gap: "6px",
    paddingBlock: "9px",
    paddingInline: "12px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
    flexShrink: 0,
  },
  footerRow: {
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  footerSplitButton: {
    flexGrow: 1,
    flexBasis: 0,
  },
  applyButton: {
    flexGrow: 1,
  },
});

export function CanvasCleanupPopover({
  params,
  onChange,
  onReset,
  onApply,
  onUndo,
  onRevertInitial,
  onClose,
  selectedCount,
  canApply,
  undoCount,
}: CanvasCleanupPopoverProps) {
  const hasSelection = selectedCount > 1;
  const [scope, setScope] = React.useState<CleanupScope>(
    hasSelection ? "selected" : "all",
  );
  const effectiveScope: CleanupScope = hasSelection ? scope : "all";
  const atDefaults = isDefaultParams(params);

  const patch = <K extends keyof CellCleanupParams>(
    key: K,
    value: CellCleanupParams[K],
  ) => {
    onChange({ ...params, [key]: value });
  };

  return (
    <div
      role="dialog"
      aria-label="Clean up canvas options"
      data-canvas-cleanup-panel="true"
      {...stylex.props(s.panel)}
    >
      <div {...stylex.props(s.header)}>
        <div {...stylex.props(s.titleGroup)}>
          <LayoutGrid size={13} />
          <h2 {...stylex.props(s.title)}>Clean up canvas</h2>
        </div>
        <div {...stylex.props(s.headerActions)}>
          <IconButton
            size="xs"
            variant="ghost"
            label="Reset cleanup defaults"
            title="Reset to default parameters"
            disabled={atDefaults}
            onClick={onReset}
          >
            <RotateCcw size={12} />
          </IconButton>
          <IconButton
            size="xs"
            variant="ghost"
            label="Close cleanup options"
            onClick={onClose}
          >
            <X size={13} />
          </IconButton>
        </div>
      </div>

      <div {...stylex.props(s.body)}>
        {hasSelection ? (
          <>
            <div {...stylex.props(s.section)}>
              <p {...stylex.props(s.sectionHeading)}>Scope</p>
              <SegmentedControl
                aria-label="Cleanup scope"
                size="sm"
                value={effectiveScope}
                onValueChange={setScope}
                options={[
                  { value: "all", label: "Whole canvas" },
                  { value: "selected", label: `Selection (${selectedCount})` },
                ]}
              />
            </div>
            <span aria-hidden="true" {...stylex.props(s.divider)} />
          </>
        ) : null}

        <div {...stylex.props(s.section)}>
          <p {...stylex.props(s.sectionHeading)}>Spacing (px)</p>
          <Slider
            label="Column gap"
            value={params.columnGapCells}
            min={2}
            max={10}
            step={1}
            format={formatPx}
            onValueChange={(value) => patch("columnGapCells", value)}
          />
          <Slider
            label="Branch gap"
            value={params.laneGapCells}
            min={1}
            max={8}
            step={1}
            format={formatPx}
            onValueChange={(value) => patch("laneGapCells", value)}
          />
          <Slider
            label="Stack gap"
            value={params.stackGapCells}
            min={1}
            max={6}
            step={1}
            format={formatPx}
            onValueChange={(value) => patch("stackGapCells", value)}
          />
          <Slider
            label="Experiment gap"
            value={params.experimentGapCells}
            min={2}
            max={12}
            step={1}
            format={formatPx}
            onValueChange={(value) => patch("experimentGapCells", value)}
          />
        </div>

        <span aria-hidden="true" {...stylex.props(s.divider)} />

        <div {...stylex.props(s.section)}>
          <p {...stylex.props(s.sectionHeading)}>Card size</p>
          <Switch
            size="sm"
            label="Resize cards to canonical sizes"
            checked={params.resizeCards}
            onCheckedChange={(checked) => patch("resizeCards", checked)}
          />
          <SegmentedControl
            aria-label="Card size preset"
            size="sm"
            value={params.cardSize}
            disabled={!params.resizeCards}
            onValueChange={(value) => patch("cardSize", value)}
            options={CARD_SIZE_OPTIONS}
          />
        </div>

        <span aria-hidden="true" {...stylex.props(s.divider)} />

        <div {...stylex.props(s.section)}>
          <p {...stylex.props(s.sectionHeading)}>Flow</p>
          <div {...stylex.props(s.switches)}>
            <Switch
              size="sm"
              label="Tuck single-use providers"
              checked={params.tuckProviders}
              onCheckedChange={(checked) => patch("tuckProviders", checked)}
            />
            <Switch
              size="sm"
              label="Align straight ports"
              checked={params.alignPorts}
              onCheckedChange={(checked) => patch("alignPorts", checked)}
            />
            <Switch
              size="sm"
              label="Keep side-by-side pairs"
              checked={params.keepCompanions}
              onCheckedChange={(checked) => patch("keepCompanions", checked)}
            />
            <Switch
              size="sm"
              label="Clear manual wire bends"
              checked={params.clearRouteOffsets}
              onCheckedChange={(checked) => patch("clearRouteOffsets", checked)}
            />
          </div>
        </div>
      </div>

      <div {...stylex.props(s.footer)}>
        {undoCount > 1 && onUndo && onRevertInitial ? (
          <div {...stylex.props(s.footerRow)}>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              title="Undo the last cleanup step"
              xstyle={s.footerSplitButton}
              onClick={onUndo}
            >
              <Undo2 size={13} />
              Undo step
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              title="Restore the original layout from before cleanup"
              xstyle={s.footerSplitButton}
              onClick={onRevertInitial}
            >
              <RotateCcw size={12} />
              Restore initial
            </Button>
          </div>
        ) : null}
        <div {...stylex.props(s.footerRow)}>
          {undoCount === 1 && onUndo ? (
            <Button
              type="button"
              variant="secondary"
              size="sm"
              title="Restore the layout from before cleanup"
              onClick={onUndo}
            >
              <Undo2 size={13} />
              Undo
            </Button>
          ) : null}
          <Button
            type="button"
            variant="primary"
            size="sm"
            disabled={!canApply}
            xstyle={s.applyButton}
            onClick={() => onApply(effectiveScope)}
          >
            <LayoutGrid size={13} />
            {effectiveScope === "selected"
              ? `Tidy ${selectedCount} selected`
              : "Clean up canvas"}
          </Button>
        </div>
      </div>
    </div>
  );
}
