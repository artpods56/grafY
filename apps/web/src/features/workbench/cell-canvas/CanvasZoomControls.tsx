"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Maximize2, Minus, Plus } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { MAX_CELL_ZOOM, MIN_CELL_ZOOM } from "./use-cell-viewport";

const ZOOM_BOUND_EPSILON = 0.001;

export interface CanvasZoomControlsProps {
  zoom: number;
  minZoom?: number;
  maxZoom?: number;
  disabled?: boolean;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onResetZoom: () => void;
  onFitView: () => void;
}

const s = stylex.create({
  root: {
    position: "absolute",
    right: "18px",
    bottom: "18px",
    zIndex: 20,
    display: {
      default: "flex",
      "@media (max-width: 720px)": "none",
    },
    alignItems: "center",
    gap: "2px",
    paddingBlock: "5px",
    paddingInline: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorFlowControls,
    backdropFilter: "blur(12px)",
    WebkitBackdropFilter: "blur(12px)",
    boxShadow: tokens.shadowNodeRaised,
  },
  zoomReset: {
    minWidth: "50px",
    paddingInline: "7px",
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
    fontVariantNumeric: "tabular-nums",
    color: {
      default: tokens.colorText,
      ":hover:not(:disabled)": tokens.colorTextEmphasis,
      ":disabled": tokens.colorTextDisabled,
    },
  },
  divider: {
    width: "1px",
    height: "18px",
    flexShrink: 0,
    marginInline: "4px",
    backgroundColor: tokens.colorDivider,
  },
});

/**
 * Floating bottom-right zoom and fit control pill for the cell canvas.
 */
export function CanvasZoomControls({
  zoom,
  minZoom = MIN_CELL_ZOOM,
  maxZoom = MAX_CELL_ZOOM,
  disabled = false,
  onZoomIn,
  onZoomOut,
  onResetZoom,
  onFitView,
}: CanvasZoomControlsProps): React.ReactElement {
  const safeZoom = Number.isFinite(zoom) ? zoom : 1;
  const zoomPercent = Math.round(safeZoom * 100);
  const atMinZoom = safeZoom <= minZoom + ZOOM_BOUND_EPSILON;
  const atMaxZoom = safeZoom >= maxZoom - ZOOM_BOUND_EPSILON;

  return (
    <div
      role="group"
      aria-label="Canvas zoom controls"
      {...stylex.props(s.root)}
    >
      <IconButton
        size="lg"
        variant="ghost"
        label="Zoom out"
        title="Zoom out"
        disabled={disabled || atMinZoom}
        onClick={onZoomOut}
      >
        <Minus size={14} />
      </IconButton>
      <Button
        type="button"
        variant="ghost"
        size="md"
        aria-label="Reset zoom to 100%"
        title="Reset zoom to 100%"
        disabled={disabled}
        xstyle={s.zoomReset}
        onClick={onResetZoom}
      >
        {zoomPercent}%
      </Button>
      <IconButton
        size="lg"
        variant="ghost"
        label="Zoom in"
        title="Zoom in"
        disabled={disabled || atMaxZoom}
        onClick={onZoomIn}
      >
        <Plus size={14} />
      </IconButton>
      <span aria-hidden="true" {...stylex.props(s.divider)} />
      <IconButton
        size="lg"
        variant="ghost"
        label="Fit view"
        title="Fit workflow"
        disabled={disabled}
        onClick={onFitView}
      >
        <Maximize2 size={14} />
      </IconButton>
    </div>
  );
}
