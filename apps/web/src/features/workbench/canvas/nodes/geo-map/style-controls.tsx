"use client";

import * as stylex from "@stylexjs/stylex";

import type {
  GeoRenderCategorizedPointStyle,
  GeoRenderFillStyle,
  GeoRenderLabelStyle,
  GeoRenderLineStyle,
  GeoRenderPointCategory,
  GeoRenderPointStyle,
  GeoRenderRasterStyle,
  GeoRenderVectorStyle,
} from "@/lib/api";

import {
  ColorControl,
  EnabledControl,
  NumberControl,
  RangeControl,
} from "./control-primitives";
import { s } from "./styles";
import { DEFAULT_LABEL_STYLE } from "./style-constants";

export function FillControls({
  title,
  value,
  onChange,
}: {
  title: string;
  value: GeoRenderFillStyle;
  onChange: (value: GeoRenderFillStyle) => void;
}) {
  return (
    <div {...stylex.props(s.section)}>
      <span {...stylex.props(s.sectionTitle)}>{title}</span>
      <EnabledControl
        label="Enabled"
        checked={value.enabled}
        onChange={(enabled) => onChange({ ...value, enabled })}
      />
      <div {...stylex.props(s.controlGrid)}>
        <ColorControl
          label="Color"
          value={value.color}
          onChange={(color) => onChange({ ...value, color })}
        />
        <RangeControl
          label="Opacity"
          value={value.opacity}
          min={0}
          max={1}
          step={0.05}
          onChange={(opacity) => onChange({ ...value, opacity })}
        />
      </div>
    </div>
  );
}

export function LineControls({
  title,
  value,
  onChange,
}: {
  title: string;
  value: GeoRenderLineStyle;
  onChange: (value: GeoRenderLineStyle) => void;
}) {
  return (
    <div {...stylex.props(s.section)}>
      <span {...stylex.props(s.sectionTitle)}>{title}</span>
      <EnabledControl
        label="Enabled"
        checked={value.enabled}
        onChange={(enabled) => onChange({ ...value, enabled })}
      />
      <div {...stylex.props(s.controlGrid)}>
        <ColorControl
          label="Color"
          value={value.color}
          onChange={(color) => onChange({ ...value, color })}
        />
        <NumberControl
          label="Width"
          value={value.width}
          min={0}
          max={64}
          step={0.5}
          onChange={(width) => onChange({ ...value, width })}
        />
        <RangeControl
          label="Opacity"
          value={value.opacity}
          min={0}
          max={1}
          step={0.05}
          onChange={(opacity) => onChange({ ...value, opacity })}
        />
      </div>
    </div>
  );
}

export function PointControls({
  value,
  onChange,
}: {
  value: GeoRenderPointStyle;
  onChange: (value: GeoRenderPointStyle) => void;
}) {
  return (
    <div {...stylex.props(s.section)}>
      <span {...stylex.props(s.sectionTitle)}>Point</span>
      <EnabledControl
        label="Enabled"
        checked={value.enabled}
        onChange={(enabled) => onChange({ ...value, enabled })}
      />
      <div {...stylex.props(s.controlGrid)}>
        <ColorControl
          label="Color"
          value={value.color}
          onChange={(color) => onChange({ ...value, color })}
        />
        <ColorControl
          label="Stroke"
          value={value.stroke_color}
          onChange={(stroke_color) => onChange({ ...value, stroke_color })}
        />
        <NumberControl
          label="Radius"
          value={value.radius}
          min={0}
          max={128}
          step={0.5}
          onChange={(radius) => onChange({ ...value, radius })}
        />
        <NumberControl
          label="Stroke width"
          value={value.stroke_width}
          min={0}
          max={32}
          step={0.5}
          onChange={(stroke_width) => onChange({ ...value, stroke_width })}
        />
        <RangeControl
          label="Opacity"
          value={value.opacity}
          min={0}
          max={1}
          step={0.05}
          onChange={(opacity) => onChange({ ...value, opacity })}
        />
      </div>
    </div>
  );
}

export function LabelControls({
  value,
  onChange,
}: {
  value: GeoRenderLabelStyle;
  onChange: (value: GeoRenderLabelStyle) => void;
}) {
  return (
    <div {...stylex.props(s.section)}>
      <span {...stylex.props(s.sectionTitle)}>Label</span>
      <div {...stylex.props(s.controlGrid)}>
        <label {...stylex.props(s.control, s.controlWide)}>
          <span>Property</span>
          <input
            type="text"
            value={value.property}
            {...stylex.props(s.controlInput)}
            onChange={(event) =>
              onChange({ ...value, property: event.currentTarget.value })
            }
          />
        </label>
        <ColorControl
          label="Color"
          value={value.color}
          onChange={(color) => onChange({ ...value, color })}
        />
        <ColorControl
          label="Halo"
          value={value.halo_color}
          onChange={(halo_color) => onChange({ ...value, halo_color })}
        />
        <NumberControl
          label="Size"
          value={value.size}
          min={6}
          max={72}
          step={1}
          onChange={(size) => onChange({ ...value, size })}
        />
        <NumberControl
          label="Halo width"
          value={value.halo_width}
          min={0}
          max={16}
          step={0.5}
          onChange={(halo_width) => onChange({ ...value, halo_width })}
        />
      </div>
    </div>
  );
}

export function VectorControls({
  value,
  onChange,
}: {
  value: GeoRenderVectorStyle;
  onChange: (value: GeoRenderVectorStyle) => void;
}) {
  return (
    <>
      <FillControls
        title="Fill"
        value={value.fill}
        onChange={(fill) => onChange({ ...value, fill })}
      />
      <LineControls
        title="Line"
        value={value.line}
        onChange={(line) => onChange({ ...value, line })}
      />
      <LineControls
        title="Outline"
        value={value.outline}
        onChange={(outline) => onChange({ ...value, outline })}
      />
      <PointControls
        value={value.point}
        onChange={(point) => onChange({ ...value, point })}
      />
      {value.label ? (
        <div {...stylex.props(s.section)}>
          <LabelControls
            value={value.label}
            onChange={(label) => onChange({ ...value, label })}
          />
          <button
            type="button"
            {...stylex.props(s.resetButton)}
            onClick={() => onChange({ ...value, label: null })}
          >
            Disable labels
          </button>
        </div>
      ) : (
        <div {...stylex.props(s.section)}>
          <span {...stylex.props(s.sectionTitle)}>Label</span>
          <button
            type="button"
            {...stylex.props(s.resetButton)}
            onClick={() =>
              onChange({ ...value, label: { ...DEFAULT_LABEL_STYLE } })
            }
          >
            Enable labels
          </button>
        </div>
      )}
    </>
  );
}

export function CategorizedPointControls({
  value,
  onChange,
}: {
  value: GeoRenderCategorizedPointStyle;
  onChange: (value: GeoRenderCategorizedPointStyle) => void;
}) {
  const updateCategory = (
    categoryId: string,
    update: (category: GeoRenderPointCategory) => GeoRenderPointCategory,
  ) => {
    onChange({
      ...value,
      categories: value.categories.map((category) =>
        category.id === categoryId ? update(category) : category,
      ),
    });
  };

  return (
    <>
      <div {...stylex.props(s.section)}>
        <span {...stylex.props(s.sectionTitle)}>
          Categories · {value.category_property}
        </span>
        <div {...stylex.props(s.categoryList)}>
          {value.categories.map((category) => (
            <div key={category.id} {...stylex.props(s.categoryRow)}>
              <input
                type="checkbox"
                checked={category.point.enabled}
                aria-label={`Show ${category.title}`}
                onChange={(event) =>
                  updateCategory(category.id, (current) => ({
                    ...current,
                    point: {
                      ...current.point,
                      enabled: event.currentTarget.checked,
                    },
                  }))
                }
              />
              <input
                type="color"
                value={category.point.color}
                aria-label={`${category.title} color`}
                {...stylex.props(s.categoryColor)}
                onChange={(event) =>
                  updateCategory(category.id, (current) => ({
                    ...current,
                    point: {
                      ...current.point,
                      color: event.currentTarget.value,
                    },
                  }))
                }
              />
              <span {...stylex.props(s.categoryText)}>
                <span title={category.title} {...stylex.props(s.categoryTitle)}>
                  {category.title}
                </span>
                <span
                  title={`${category.values.join(", ")} · zoom ${category.min_zoom}–${category.max_zoom}`}
                  {...stylex.props(s.categoryMeta)}
                >
                  {category.values.join(", ")} · z{category.min_zoom}–
                  {category.max_zoom}
                </span>
              </span>
              <input
                type="number"
                value={category.point.radius}
                min={0}
                max={128}
                step={0.5}
                aria-label={`${category.title} radius`}
                title="Point radius"
                {...stylex.props(s.categoryRadius)}
                onChange={(event) => {
                  const radius = Number(event.currentTarget.value);
                  if (!Number.isFinite(radius)) return;
                  updateCategory(category.id, (current) => ({
                    ...current,
                    point: {
                      ...current.point,
                      radius: Math.max(0, Math.min(128, radius)),
                    },
                  }));
                }}
              />
            </div>
          ))}
        </div>
      </div>
      {value.label ? (
        <div {...stylex.props(s.section)}>
          <LabelControls
            value={value.label}
            onChange={(label) => onChange({ ...value, label })}
          />
          <button
            type="button"
            {...stylex.props(s.resetButton)}
            onClick={() => onChange({ ...value, label: null })}
          >
            Disable labels
          </button>
        </div>
      ) : (
        <div {...stylex.props(s.section)}>
          <span {...stylex.props(s.sectionTitle)}>Label</span>
          <button
            type="button"
            {...stylex.props(s.resetButton)}
            onClick={() =>
              onChange({ ...value, label: { ...DEFAULT_LABEL_STYLE } })
            }
          >
            Enable labels
          </button>
        </div>
      )}
    </>
  );
}

export function RasterControls({
  value,
  onChange,
}: {
  value: GeoRenderRasterStyle;
  onChange: (value: GeoRenderRasterStyle) => void;
}) {
  return (
    <div {...stylex.props(s.section)}>
      <span {...stylex.props(s.sectionTitle)}>Raster</span>
      <div {...stylex.props(s.controlGrid)}>
        <RangeControl
          label="Opacity"
          value={value.opacity}
          min={0}
          max={1}
          step={0.05}
          onChange={(opacity) => onChange({ ...value, opacity })}
        />
        <RangeControl
          label="Brightness min"
          value={value.brightness_min}
          min={0}
          max={value.brightness_max}
          step={0.05}
          onChange={(brightness_min) => onChange({ ...value, brightness_min })}
        />
        <RangeControl
          label="Brightness max"
          value={value.brightness_max}
          min={value.brightness_min}
          max={1}
          step={0.05}
          onChange={(brightness_max) => onChange({ ...value, brightness_max })}
        />
        <RangeControl
          label="Contrast"
          value={value.contrast}
          min={-1}
          max={1}
          step={0.05}
          onChange={(contrast) => onChange({ ...value, contrast })}
        />
        <RangeControl
          label="Saturation"
          value={value.saturation}
          min={-1}
          max={1}
          step={0.05}
          onChange={(saturation) => onChange({ ...value, saturation })}
        />
        <RangeControl
          label="Hue"
          value={value.hue}
          min={0}
          max={359}
          step={1}
          onChange={(hue) => onChange({ ...value, hue })}
        />
        <label {...stylex.props(s.control, s.controlWide)}>
          <span>Resampling</span>
          <select
            value={value.resampling}
            {...stylex.props(s.controlInput)}
            onChange={(event) =>
              onChange({
                ...value,
                resampling: event.currentTarget.value as "linear" | "nearest",
              })
            }
          >
            <option value="linear">linear</option>
            <option value="nearest">nearest</option>
          </select>
        </label>
      </div>
    </div>
  );
}
