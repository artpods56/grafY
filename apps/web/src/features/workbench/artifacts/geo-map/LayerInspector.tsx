"use client";

import * as stylex from "@stylexjs/stylex";
import { ArrowDown, ArrowUp, Eye, EyeOff, RotateCcw } from "lucide-react";

import type { GeoRenderLayer } from "@/lib/api";
import { Button, IconButton } from "@/components/ui/button";
import { Field, TextInput } from "@/components/ui/field";
import { Slider } from "@/components/ui/slider";

import { clampedNumberChange } from "./control-primitives";
import { s } from "./styles";
import {
  CategorizedPointControls,
  RasterControls,
  VectorControls,
} from "./style-controls";

/** The layer's name is the disclosure control, so it has to truncate in one line. */
const local = stylex.create({
  disclosure: {
    minWidth: 0,
    justifyContent: "flex-start",
    textAlign: "left",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
});

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
        <Button
          variant="ghost"
          size="xs"
          aria-expanded={expanded}
          title={layer.title}
          xstyle={local.disclosure}
          onClick={onExpandedChange}
        >
          {index + 1}. {layer.title}
        </Button>
        <span {...stylex.props(s.layerActions)}>
          <IconButton
            label={`Move ${layer.title} down in the map stack`}
            title="Move down"
            disabled={index === 0}
            onClick={() => onMove(1)}
          >
            <ArrowDown size={12} />
          </IconButton>
          <IconButton
            label={`Move ${layer.title} up in the map stack`}
            title="Move up"
            disabled={index === count - 1}
            onClick={() => onMove(-1)}
          >
            <ArrowUp size={12} />
          </IconButton>
          {/* The icon and its name say which way it toggles, so no `pressed`. */}
          <IconButton
            label={`${layer.visible ? "Hide" : "Show"} ${layer.title}`}
            onClick={() => onChange({ ...layer, visible: !layer.visible })}
          >
            {layer.visible ? <Eye size={13} /> : <EyeOff size={13} />}
          </IconButton>
        </span>
      </div>
      {expanded ? (
        <div {...stylex.props(s.controls)}>
          <div {...stylex.props(s.controlGrid)}>
            <Slider
              size="dense"
              className="nodrag nopan nowheel"
              xstyle={s.controlWide}
              label="Layer opacity"
              value={layer.opacity}
              min={0}
              max={1}
              step={0.05}
              onValueChange={(opacity) => onChange({ ...layer, opacity })}
            />
            <Field label="Min zoom" className="nodrag nopan nowheel">
              <TextInput
                type="number"
                value={layer.min_zoom}
                min={0}
                max={layer.max_zoom}
                step={1}
                onChange={clampedNumberChange(0, layer.max_zoom, (min_zoom) =>
                  onChange({ ...layer, min_zoom }),
                )}
              />
            </Field>
            <Field label="Max zoom" className="nodrag nopan nowheel">
              <TextInput
                type="number"
                value={layer.max_zoom}
                min={layer.min_zoom}
                max={24}
                step={1}
                onChange={clampedNumberChange(layer.min_zoom, 24, (max_zoom) =>
                  onChange({ ...layer, max_zoom }),
                )}
              />
            </Field>
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
          <Button size="xs" variant="secondary" onClick={onReset}>
            <RotateCcw size={11} />
            Reset layer
          </Button>
        </div>
      ) : null}
    </section>
  );
}
