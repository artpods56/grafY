"use client";

import * as stylex from "@stylexjs/stylex";
import { ArrowDown, ArrowUp, Eye, EyeOff, RotateCcw } from "lucide-react";

import type { GeoRenderLayer } from "@/lib/api";

import { NumberControl, RangeControl } from "./control-primitives";
import { s } from "./styles";
import {
  CategorizedPointControls,
  RasterControls,
  VectorControls,
} from "./style-controls";

export function LayerInspector({
  layer,
  index,
  count,
  expanded,
  onExpandedChange,
  onChange,
  onMove,
  onReset,
}: {
  layer: GeoRenderLayer;
  index: number;
  count: number;
  expanded: boolean;
  onExpandedChange: () => void;
  onChange: (layer: GeoRenderLayer) => void;
  onMove: (direction: -1 | 1) => void;
  onReset: () => void;
}) {
  return (
    <section {...stylex.props(s.layer)}>
      <div {...stylex.props(s.layerHeader)}>
        <button
          type="button"
          aria-expanded={expanded}
          title={layer.title}
          {...stylex.props(s.layerTitleButton)}
          onClick={onExpandedChange}
        >
          {index + 1}. {layer.title}
        </button>
        <span {...stylex.props(s.layerActions)}>
          <button
            type="button"
            disabled={index === 0}
            aria-label={`Move ${layer.title} down in the map stack`}
            title="Move down"
            {...stylex.props(s.iconButton)}
            onClick={() => onMove(1)}
          >
            <ArrowDown size={12} aria-hidden="true" />
          </button>
          <button
            type="button"
            disabled={index === count - 1}
            aria-label={`Move ${layer.title} up in the map stack`}
            title="Move up"
            {...stylex.props(s.iconButton)}
            onClick={() => onMove(-1)}
          >
            <ArrowUp size={12} aria-hidden="true" />
          </button>
          <button
            type="button"
            aria-label={`${layer.visible ? "Hide" : "Show"} ${layer.title}`}
            {...stylex.props(s.iconButton)}
            onClick={() => onChange({ ...layer, visible: !layer.visible })}
          >
            {layer.visible ? (
              <Eye size={13} aria-hidden="true" />
            ) : (
              <EyeOff size={13} aria-hidden="true" />
            )}
          </button>
        </span>
      </div>
      {expanded ? (
        <div {...stylex.props(s.controls)}>
          <div {...stylex.props(s.controlGrid)}>
            <RangeControl
              label="Layer opacity"
              value={layer.opacity}
              min={0}
              max={1}
              step={0.05}
              onChange={(opacity) => onChange({ ...layer, opacity })}
            />
            <NumberControl
              label="Min zoom"
              value={layer.min_zoom}
              min={0}
              max={layer.max_zoom}
              step={1}
              onChange={(min_zoom) => onChange({ ...layer, min_zoom })}
            />
            <NumberControl
              label="Max zoom"
              value={layer.max_zoom}
              min={layer.min_zoom}
              max={24}
              step={1}
              onChange={(max_zoom) => onChange({ ...layer, max_zoom })}
            />
          </div>
          {layer.style.kind === "vector" ? (
            <VectorControls
              value={layer.style}
              onChange={(style) => onChange({ ...layer, style })}
            />
          ) : layer.style.kind === "categorized_points" ? (
            <CategorizedPointControls
              value={layer.style}
              onChange={(style) => onChange({ ...layer, style })}
            />
          ) : (
            <RasterControls
              value={layer.style}
              onChange={(style) => onChange({ ...layer, style })}
            />
          )}
          <button
            type="button"
            {...stylex.props(s.resetButton)}
            onClick={onReset}
          >
            <RotateCcw size={11} aria-hidden="true" />
            Reset layer
          </button>
        </div>
      ) : null}
    </section>
  );
}
