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
import { Button } from "@/components/ui/button";
import { ColorField, ColorWell } from "@/components/ui/color-field";
import { Field, TextInput } from "@/components/ui/field";
import { Select } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";

import { clampedNumberChange } from "./control-primitives";
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
      <Switch
        size="dense"
        className="nodrag nopan nowheel"
        label="Enabled"
        checked={value.enabled}
        onCheckedChange={(enabled) => onChange({ ...value, enabled })}
      />
      <div {...stylex.props(s.controlGrid)}>
        <ColorField
          size="dense"
          className="nodrag nopan nowheel"
          label="Color"
          value={value.color}
          onChange={(color) => onChange({ ...value, color })}
        />
        <Slider
          size="dense"
          className="nodrag nopan nowheel"
          xstyle={s.controlWide}
          label="Opacity"
          value={value.opacity}
          min={0}
          max={1}
          step={0.05}
          onValueChange={(opacity) => onChange({ ...value, opacity })}
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
      <Switch
        size="dense"
        className="nodrag nopan nowheel"
        label="Enabled"
        checked={value.enabled}
        onCheckedChange={(enabled) => onChange({ ...value, enabled })}
      />
      <div {...stylex.props(s.controlGrid)}>
        <ColorField
          size="dense"
          className="nodrag nopan nowheel"
          label="Color"
          value={value.color}
          onChange={(color) => onChange({ ...value, color })}
        />
        <Field label="Width" className="nodrag nopan nowheel">
          <TextInput
            type="number"
            value={value.width}
            min={0}
            max={64}
            step={0.5}
            onChange={clampedNumberChange(0, 64, (width) =>
              onChange({ ...value, width }),
            )}
          />
        </Field>
        <Slider
          size="dense"
          className="nodrag nopan nowheel"
          xstyle={s.controlWide}
          label="Opacity"
          value={value.opacity}
          min={0}
          max={1}
          step={0.05}
          onValueChange={(opacity) => onChange({ ...value, opacity })}
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
      <Switch
        size="dense"
        className="nodrag nopan nowheel"
        label="Enabled"
        checked={value.enabled}
        onCheckedChange={(enabled) => onChange({ ...value, enabled })}
      />
      <div {...stylex.props(s.controlGrid)}>
        <ColorField
          size="dense"
          className="nodrag nopan nowheel"
          label="Color"
          value={value.color}
          onChange={(color) => onChange({ ...value, color })}
        />
        <ColorField
          size="dense"
          className="nodrag nopan nowheel"
          label="Stroke"
          value={value.stroke_color}
          onChange={(stroke_color) => onChange({ ...value, stroke_color })}
        />
        <Field label="Radius" className="nodrag nopan nowheel">
          <TextInput
            type="number"
            value={value.radius}
            min={0}
            max={128}
            step={0.5}
            onChange={clampedNumberChange(0, 128, (radius) =>
              onChange({ ...value, radius }),
            )}
          />
        </Field>
        <Field label="Stroke width" className="nodrag nopan nowheel">
          <TextInput
            type="number"
            value={value.stroke_width}
            min={0}
            max={32}
            step={0.5}
            onChange={clampedNumberChange(0, 32, (stroke_width) =>
              onChange({ ...value, stroke_width }),
            )}
          />
        </Field>
        <Slider
          size="dense"
          className="nodrag nopan nowheel"
          xstyle={s.controlWide}
          label="Opacity"
          value={value.opacity}
          min={0}
          max={1}
          step={0.05}
          onValueChange={(opacity) => onChange({ ...value, opacity })}
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
        <Field
          label="Property"
          xstyle={s.controlWide}
          className="nodrag nopan nowheel"
        >
          <TextInput
            value={value.property}
            onChange={(event) =>
              onChange({ ...value, property: event.currentTarget.value })
            }
          />
        </Field>
        <ColorField
          size="dense"
          className="nodrag nopan nowheel"
          label="Color"
          value={value.color}
          onChange={(color) => onChange({ ...value, color })}
        />
        <ColorField
          size="dense"
          className="nodrag nopan nowheel"
          label="Halo"
          value={value.halo_color}
          onChange={(halo_color) => onChange({ ...value, halo_color })}
        />
        <Field label="Size" className="nodrag nopan nowheel">
          <TextInput
            type="number"
            value={value.size}
            min={6}
            max={72}
            step={1}
            onChange={clampedNumberChange(6, 72, (size) =>
              onChange({ ...value, size }),
            )}
          />
        </Field>
        <Field label="Halo width" className="nodrag nopan nowheel">
          <TextInput
            type="number"
            value={value.halo_width}
            min={0}
            max={16}
            step={0.5}
            onChange={clampedNumberChange(0, 16, (halo_width) =>
              onChange({ ...value, halo_width }),
            )}
          />
        </Field>
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
          <Button
            size="xs"
            variant="secondary"
            onClick={() => onChange({ ...value, label: null })}
          >
            Disable labels
          </Button>
        </div>
      ) : (
        <div {...stylex.props(s.section)}>
          <span {...stylex.props(s.sectionTitle)}>Label</span>
          <Button
            size="xs"
            variant="secondary"
            onClick={() =>
              onChange({ ...value, label: { ...DEFAULT_LABEL_STYLE } })
            }
          >
            Enable labels
          </Button>
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
              <ColorWell
                size="dense"
                block={false}
                xstyle={s.categoryColor}
                value={category.point.color}
                label={`${category.title} color`}
                onChange={(color) =>
                  updateCategory(category.id, (current) => ({
                    ...current,
                    point: {
                      ...current.point,
                      color,
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
          <Button
            size="xs"
            variant="secondary"
            onClick={() => onChange({ ...value, label: null })}
          >
            Disable labels
          </Button>
        </div>
      ) : (
        <div {...stylex.props(s.section)}>
          <span {...stylex.props(s.sectionTitle)}>Label</span>
          <Button
            size="xs"
            variant="secondary"
            onClick={() =>
              onChange({ ...value, label: { ...DEFAULT_LABEL_STYLE } })
            }
          >
            Enable labels
          </Button>
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
        <Slider
          size="dense"
          className="nodrag nopan nowheel"
          xstyle={s.controlWide}
          label="Opacity"
          value={value.opacity}
          min={0}
          max={1}
          step={0.05}
          onValueChange={(opacity) => onChange({ ...value, opacity })}
        />
        <Slider
          size="dense"
          className="nodrag nopan nowheel"
          xstyle={s.controlWide}
          label="Brightness min"
          value={value.brightness_min}
          min={0}
          max={value.brightness_max}
          step={0.05}
          onValueChange={(brightness_min) =>
            onChange({ ...value, brightness_min })
          }
        />
        <Slider
          size="dense"
          className="nodrag nopan nowheel"
          xstyle={s.controlWide}
          label="Brightness max"
          value={value.brightness_max}
          min={value.brightness_min}
          max={1}
          step={0.05}
          onValueChange={(brightness_max) =>
            onChange({ ...value, brightness_max })
          }
        />
        <Slider
          size="dense"
          className="nodrag nopan nowheel"
          xstyle={s.controlWide}
          label="Contrast"
          value={value.contrast}
          min={-1}
          max={1}
          step={0.05}
          onValueChange={(contrast) => onChange({ ...value, contrast })}
        />
        <Slider
          size="dense"
          className="nodrag nopan nowheel"
          xstyle={s.controlWide}
          label="Saturation"
          value={value.saturation}
          min={-1}
          max={1}
          step={0.05}
          onValueChange={(saturation) => onChange({ ...value, saturation })}
        />
        <Slider
          size="dense"
          className="nodrag nopan nowheel"
          xstyle={s.controlWide}
          label="Hue"
          value={value.hue}
          min={0}
          max={359}
          step={1}
          onValueChange={(hue) => onChange({ ...value, hue })}
        />
        <Field
          label="Resampling"
          size="dense"
          xstyle={s.controlWide}
          className="nodrag nopan nowheel"
        >
          <Select
            value={value.resampling}
            onChange={(event) =>
              onChange({
                ...value,
                resampling: event.currentTarget.value as "linear" | "nearest",
              })
            }
          >
            <option value="linear">linear</option>
            <option value="nearest">nearest</option>
          </Select>
        </Field>
      </div>
    </div>
  );
}
