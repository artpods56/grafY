"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Minus, Plus } from "lucide-react";

import { useTheme, type ResolvedTheme } from "@/components/theme";
import { Button, IconButton } from "@/components/ui/button";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Slider } from "@/components/ui/slider";
import { Surface } from "@/components/ui/surface";
import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  PIPE_FAMILIES,
  type PipeFamily,
} from "@/features/workbench/cell-canvas/pipe-visuals";
import type {
  CellCorners,
  CellGlassLook,
  CellGlassMaterial,
  CellWellStyle,
} from "@/features/workbench/cell-canvas/cell-glass-stage";
import type {
  CellExits,
  CellRoutingOptions,
  UnderCardsMode,
} from "@/features/workbench/cell-canvas/cell-model";

export type CellGraphKind = "demo" | "showcase" | "stress";

export interface CellLookPanelProps {
  graph: CellGraphKind;
  onGraph: (value: CellGraphKind) => void;
  counts: { cards: number; pipes: number; deepCount: number; reroutes: number };
  fps: number | null;
  look: CellGlassLook;
  onLook: (value: CellGlassLook) => void;
  routing: CellRoutingOptions;
  onRouting: (value: CellRoutingOptions) => void;
}

export interface CellZoomBarProps {
  zoom: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onZoomPreset: (zoom: number) => void;
  onFit: () => void;
}

type OnOff = "on" | "off";

const ON_OFF = [
  { value: "on", label: "On" },
  { value: "off", label: "Off" },
] satisfies { value: OnOff; label: string }[];

const s = stylex.create({
  // Scrolls once its rows outgrow the window, clear of the zoom bar.
  panel: {
    display: "grid",
    gap: "12px",
    width: "244px",
    maxHeight: "calc(100svh - 110px)",
    overflowY: "auto",
    overscrollBehavior: "contain",
  },
  row: { display: "grid", gap: "5px" },
  rowLabel: {
    color: tokens.colorMuted,
    fontSize: "10px",
    fontWeight: 800,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  measure: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "baseline",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  rate: {
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 700,
    fontVariantNumeric: "tabular-nums",
  },
  stats: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontVariantNumeric: "tabular-nums",
  },
  hint: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
  zoomBar: {
    display: "flex",
    alignItems: "center",
    gap: "2px",
  },
  zoomReadout: {
    minWidth: "40px",
    paddingInline: "4px",
    textAlign: "right",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontVariantNumeric: "tabular-nums",
  },
});

/** Keep a drag on a slider or a scroll in the panel off the canvas below. */
function stopPropagation(event: React.SyntheticEvent) {
  event.stopPropagation();
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div {...stylex.props(s.row)}>
      <span {...stylex.props(s.rowLabel)}>{label}</span>
      {children}
    </div>
  );
}

export function CellLookPanel({
  graph,
  onGraph,
  counts,
  fps,
  look,
  onLook,
  routing,
  onRouting,
}: CellLookPanelProps) {
  const { resolved, setPreference } = useTheme();
  return (
    <Surface
      tone="floating"
      padding="md"
      shape="lg"
      xstyle={s.panel}
      onPointerDown={stopPropagation}
      onWheel={stopPropagation}
    >
      <Row label="Theme">
        <SegmentedControl<ResolvedTheme>
          aria-label="Theme"
          size="sm"
          value={resolved}
          onValueChange={setPreference}
          options={[
            { value: "light", label: "Light" },
            { value: "dark", label: "Dark" },
          ]}
        />
      </Row>
      <Row label="Graph">
        <SegmentedControl<CellGraphKind>
          aria-label="Graph"
          size="sm"
          value={graph}
          onValueChange={onGraph}
          options={[
            { value: "demo", label: "Demo" },
            { value: "showcase", label: "Showcase" },
            { value: "stress", label: "Stress" },
          ]}
        />
        <div {...stylex.props(s.measure)}>
          <span>
            {counts.cards} cards · {counts.pipes} pipes
          </span>
          <span>
            <span {...stylex.props(s.rate)}>{fps ?? "–"}</span> fps
          </span>
        </div>
        <span {...stylex.props(s.stats)}>
          {counts.deepCount} deep · {counts.reroutes} reroutes
        </span>
      </Row>
      <Row label="Glass">
        <SegmentedControl<CellGlassMaterial>
          aria-label="Glass"
          size="sm"
          value={look.material}
          onValueChange={(material) => onLook({ ...look, material })}
          options={[
            { value: "frost", label: "Frost" },
            { value: "liquid", label: "Liquid" },
          ]}
        />
      </Row>
      <Row label="Wells">
        <SegmentedControl<CellWellStyle>
          aria-label="Wells"
          size="sm"
          value={look.well}
          onValueChange={(well) => onLook({ ...look, well })}
          options={[
            { value: "recessed", label: "Recessed" },
            { value: "flat", label: "Flat" },
          ]}
        />
      </Row>
      <Row label="Pipe">
        <SegmentedControl<PipeFamily>
          aria-label="Pipe"
          size="sm"
          value={look.pipe}
          onValueChange={(pipe) => onLook({ ...look, pipe })}
          options={PIPE_FAMILIES}
        />
      </Row>
      <Row label="Exit">
        <SegmentedControl<CellExits>
          aria-label="Exit"
          size="sm"
          value={routing.exits}
          onValueChange={(exits) => onRouting({ ...routing, exits })}
          options={[
            { value: "side", label: "Side" },
            { value: "free", label: "Free" },
          ]}
        />
      </Row>
      <Row label="Under cards">
        <SegmentedControl<UnderCardsMode>
          aria-label="Under cards"
          size="sm"
          value={routing.underCards}
          onValueChange={(underCards) => onRouting({ ...routing, underCards })}
          options={[
            { value: "free", label: "Free" },
            { value: "gaps", label: "Prefer gaps" },
            { value: "avoid", label: "Avoid" },
          ]}
        />
      </Row>
      <Row label="Depth layers">
        <SegmentedControl<OnOff>
          aria-label="Depth layers"
          size="sm"
          value={routing.depth ? "on" : "off"}
          onValueChange={(value) =>
            onRouting({ ...routing, depth: value === "on" })
          }
          options={ON_OFF}
        />
      </Row>
      <Row label="Corners">
        <SegmentedControl<CellCorners>
          aria-label="Corners"
          size="sm"
          value={look.corners}
          onValueChange={(corners) => onLook({ ...look, corners })}
          options={[
            { value: "rounded", label: "Rounded" },
            { value: "sharp", label: "Sharp" },
          ]}
        />
      </Row>
      <Row label="Cell grid">
        <SegmentedControl<OnOff>
          aria-label="Cell grid"
          size="sm"
          value={look.grid ? "on" : "off"}
          onValueChange={(value) => onLook({ ...look, grid: value === "on" })}
          options={[
            { value: "on", label: "Subtle" },
            { value: "off", label: "Off" },
          ]}
        />
      </Row>
      <Slider
        label="Blur"
        min={0}
        max={12}
        step={0.1}
        format={(blur) => blur.toFixed(1)}
        value={look.blur}
        onValueChange={(blur) => onLook({ ...look, blur })}
      />
      <Slider
        label="Frost"
        min={0}
        max={0.9}
        step={0.05}
        value={look.frost}
        onValueChange={(frost) => onLook({ ...look, frost })}
      />
      <p {...stylex.props(s.hint)}>
        Drag cards to snap cell by cell; Shift+drag to marquee or group-drag.
        Hover a pipe or pill to wipe frost; drag a corner grip to resize.
      </p>
    </Surface>
  );
}

/** A preset counts as current within this much zoom of it. */
const PRESET_TOLERANCE = 0.02;

export function CellZoomBar({
  zoom,
  onZoomIn,
  onZoomOut,
  onZoomPreset,
  onFit,
}: CellZoomBarProps) {
  return (
    <Surface
      tone="floating"
      padding="xs"
      shape="lg"
      xstyle={s.zoomBar}
      onPointerDown={stopPropagation}
      onWheel={stopPropagation}
    >
      <IconButton label="Zoom out" size="xs" onClick={onZoomOut}>
        <Minus size={14} />
      </IconButton>
      <Button
        variant="ghost"
        size="xs"
        pressed={Math.abs(zoom - 0.5) < PRESET_TOLERANCE}
        onClick={() => onZoomPreset(0.5)}
      >
        50%
      </Button>
      <Button
        variant="ghost"
        size="xs"
        pressed={Math.abs(zoom - 1) < PRESET_TOLERANCE}
        onClick={() => onZoomPreset(1)}
      >
        100%
      </Button>
      <IconButton label="Zoom in" size="xs" onClick={onZoomIn}>
        <Plus size={14} />
      </IconButton>
      <Button variant="ghost" size="xs" onClick={onFit}>
        Fit
      </Button>
      <span aria-live="polite" {...stylex.props(s.zoomReadout)}>
        {Math.round(zoom * 100)}%
      </span>
    </Surface>
  );
}
