"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Plus, Trash2 } from "lucide-react";

import { createUuid } from "@/features/workbench/model/uuid";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { Button, IconButton } from "@/components/ui/button";
import { ColorField } from "@/components/ui/color-field";
import { Field, TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select } from "@/components/ui/select";
import type { WorkflowNodeData } from "../types";

type CategoryValue = string | number | boolean;
type CategoryValueKind = "number" | "text" | "boolean";

interface PointStyle {
  enabled: boolean;
  color: string;
  opacity: number;
  radius: number;
  stroke_color: string;
  stroke_width: number;
}

interface LineStyle {
  enabled: boolean;
  color: string;
  opacity: number;
  width: number;
}

interface LabelStyle {
  property: string;
  color: string;
  size: number;
  halo_color: string;
  halo_width: number;
}

interface UniformStyle {
  kind: "vector";
  fill: {
    enabled: boolean;
    color: string;
    opacity: number;
  };
  line: LineStyle;
  outline: LineStyle;
  point: PointStyle;
  label: LabelStyle | null;
}

interface PointCategory {
  id: string;
  title: string;
  values: CategoryValue[];
  point: PointStyle;
  min_zoom: number;
  max_zoom: number;
}

interface CategorizedStyle {
  kind: "categorized_points";
  category_property: string;
  categories: PointCategory[];
  label: LabelStyle | null;
}

type VectorLayerStyle = UniformStyle | CategorizedStyle;

const DEFAULT_POINT_STYLE: PointStyle = {
  enabled: true,
  color: "#dc2626",
  opacity: 1,
  radius: 5,
  stroke_color: "#ffffff",
  stroke_width: 1,
};

const DEFAULT_LABEL_STYLE: LabelStyle = {
  property: "name",
  color: "#111827",
  size: 12,
  halo_color: "#ffffff",
  halo_width: 1,
};

const DEFAULT_UNIFORM_STYLE: UniformStyle = {
  kind: "vector",
  fill: { enabled: true, color: "#2563eb", opacity: 0.45 },
  line: { enabled: true, color: "#1d4ed8", opacity: 1, width: 1.5 },
  outline: { enabled: true, color: "#1d4ed8", opacity: 1, width: 1.5 },
  point: DEFAULT_POINT_STYLE,
  label: null,
};

const DEFAULT_CATEGORIZED_STYLE: CategorizedStyle = {
  kind: "categorized_points",
  category_property: "type",
  categories: [
    {
      id: "category_1",
      title: "Category 1",
      values: [1],
      point: DEFAULT_POINT_STYLE,
      min_zoom: 0,
      max_zoom: 22,
    },
  ],
  label: null,
};

const s = stylex.create({
  body: {
    display: "grid",
    gap: "8px",
    padding: "0 10px 12px",
  },
  header: {
    display: "grid",
    gridTemplateColumns: "auto minmax(0, 1fr)",
    alignItems: "center",
    gap: "8px",
  },
  title: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 750,
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: "6px",
  },
  wide: { gridColumn: "1 / -1" },
  field: {
    minWidth: 0,
    display: "grid",
    gap: "3px",
  },
  label: {
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 650,
  },
  input: {
    width: "100%",
    minWidth: 0,
    height: "28px",
    paddingInline: "8px",
    borderWidth: 0,
    borderRadius: "7px",
    outline: {
      default: "none",
      ":focus": `2px solid ${tokens.colorAccentBorder}`,
    },
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
  },
  select: {
    width: "100%",
    minWidth: 0,
  },
  categories: {
    display: "grid",
    gap: "5px",
  },
  category: {
    display: "grid",
    gap: "6px",
    padding: "7px",
    borderRadius: "8px",
    backgroundColor: tokens.colorSurfaceMuted,
  },
  categoryHeader: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    alignItems: "center",
    gap: "5px",
  },
});

/**
 * The category-title input sits outside a `<Field>` with no label of its own,
 * so React Flow still needs the classes on the control itself. A `<Field>`
 * carries them on its root and React Flow resolves the class by walking up from
 * the event target, so a control inside one does not repeat them; the kit's
 * `ColorField` and `Select` take them through `className` for the same reason.
 */
function interactionProps(props: ReturnType<typeof stylex.props>) {
  return {
    ...props,
    className: `nodrag nopan nowheel${props.className ? ` ${props.className}` : ""}`,
  };
}

function configuredStyle(value: unknown): VectorLayerStyle {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return DEFAULT_UNIFORM_STYLE;
  }
  const candidate = value as Record<string, unknown>;
  if (candidate.kind === "categorized_points") {
    return candidate as unknown as CategorizedStyle;
  }
  if (candidate.kind === "vector") {
    return candidate as unknown as UniformStyle;
  }
  return DEFAULT_UNIFORM_STYLE;
}

function valueKind(values: readonly CategoryValue[]): CategoryValueKind {
  if (values.length && values.every((value) => typeof value === "number")) {
    return "number";
  }
  if (values.length && values.every((value) => typeof value === "boolean")) {
    return "boolean";
  }
  return "text";
}

function parseValues(value: string, kind: CategoryValueKind): CategoryValue[] {
  const parts = value
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  if (kind === "number") {
    return parts.flatMap((part) => {
      const number = Number(part);
      return Number.isFinite(number) ? [number] : [];
    });
  }
  if (kind === "boolean") {
    return parts.flatMap((part) => {
      const normalized = part.toLowerCase();
      return normalized === "true"
        ? [true]
        : normalized === "false"
          ? [false]
          : [];
    });
  }
  return parts;
}

function LabelPropertyField({
  label,
  onChange,
}: {
  label: LabelStyle | null;
  onChange: (label: LabelStyle | null) => void;
}) {
  return (
    <Field label="Label property" className="nodrag nopan nowheel">
      <TextInput
        value={label?.property ?? ""}
        placeholder="No labels"
        onChange={(event) => {
          const property = event.currentTarget.value;
          onChange(
            property ? { ...(label ?? DEFAULT_LABEL_STYLE), property } : null,
          );
        }}
      />
    </Field>
  );
}

function CategoryValuesField({
  category,
  onChange,
}: {
  category: PointCategory;
  onChange: (category: PointCategory) => void;
}) {
  const kind = valueKind(category.values);
  const [draft, setDraft] = React.useState(() => category.values.join(", "));
  const [invalid, setInvalid] = React.useState(false);

  const commitDraft = () => {
    const values = parseValues(draft, kind);
    if (!values.length) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    onChange({ ...category, values });
  };

  return (
    <>
      <label {...stylex.props(s.field)}>
        <span {...stylex.props(s.label)}>Value type</span>
        <Select
          size="sm"
          xstyle={s.select}
          value={kind}
          className="nodrag nopan nowheel"
          onChange={(event) => {
            const nextKind = event.currentTarget.value as CategoryValueKind;
            const values = parseValues(draft, nextKind);
            if (!values.length) {
              setInvalid(true);
              return;
            }
            setInvalid(false);
            onChange({ ...category, values });
          }}
        >
          <option value="number">Numbers</option>
          <option value="text">Text</option>
          <option value="boolean">Booleans</option>
        </Select>
      </label>
      <Field label="Values" className="nodrag nopan nowheel">
        <TextInput
          aria-invalid={invalid}
          value={draft}
          placeholder="1, 2, 3"
          onChange={(event) => {
            setDraft(event.currentTarget.value);
            setInvalid(false);
          }}
          onBlur={commitDraft}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commitDraft();
            }
          }}
        />
      </Field>
      {invalid ? (
        <Notice tone="danger" xstyle={s.wide}>
          Enter at least one comma-separated value of the selected type.
        </Notice>
      ) : null}
    </>
  );
}

const STYLE_MODE_OPTIONS = [
  { value: "vector", label: "Uniform" },
  { value: "categorized_points", label: "Categories" },
] as const;

export function VectorLayerStyleBody({
  id,
  data,
}: {
  id: string;
  data: WorkflowNodeData;
}) {
  const style = configuredStyle(data.config.style);
  const commit = (next: VectorLayerStyle) =>
    data.onConfigChange?.(id, "style", next);

  return (
    <section aria-label="Vector layer style" {...stylex.props(s.body)}>
      <div {...stylex.props(s.header)}>
        <span {...stylex.props(s.title)}>Feature style</span>
        <SegmentedControl
          aria-label="Feature style mode"
          size="sm"
          className="nodrag nopan nowheel"
          value={style.kind}
          options={STYLE_MODE_OPTIONS}
          onValueChange={(kind) =>
            commit(
              kind === "categorized_points"
                ? DEFAULT_CATEGORIZED_STYLE
                : DEFAULT_UNIFORM_STYLE,
            )
          }
        />
      </div>

      {style.kind === "vector" ? (
        <div {...stylex.props(s.grid)}>
          <ColorField
            size="sm"
            className="nodrag nopan nowheel"
            label="Point color"
            value={style.point.color}
            onChange={(color) =>
              commit({ ...style, point: { ...style.point, color } })
            }
          />
          <Field label="Point radius" className="nodrag nopan nowheel">
            <TextInput
              type="number"
              min={0}
              max={128}
              value={style.point.radius}
              onChange={(event) =>
                commit({
                  ...style,
                  point: {
                    ...style.point,
                    radius: Number(event.currentTarget.value),
                  },
                })
              }
            />
          </Field>
          <ColorField
            size="sm"
            className="nodrag nopan nowheel"
            label="Line color"
            value={style.line.color}
            onChange={(color) =>
              commit({ ...style, line: { ...style.line, color } })
            }
          />
          <Field label="Line width" className="nodrag nopan nowheel">
            <TextInput
              type="number"
              min={0}
              max={64}
              step="0.5"
              value={style.line.width}
              onChange={(event) =>
                commit({
                  ...style,
                  line: {
                    ...style.line,
                    width: Number(event.currentTarget.value),
                  },
                })
              }
            />
          </Field>
          <ColorField
            size="sm"
            className="nodrag nopan nowheel"
            label="Fill color"
            value={style.fill.color}
            onChange={(color) =>
              commit({ ...style, fill: { ...style.fill, color } })
            }
          />
          <Field label="Fill opacity" className="nodrag nopan nowheel">
            <TextInput
              type="number"
              min={0}
              max={1}
              step="0.05"
              value={style.fill.opacity}
              onChange={(event) =>
                commit({
                  ...style,
                  fill: {
                    ...style.fill,
                    opacity: Number(event.currentTarget.value),
                  },
                })
              }
            />
          </Field>
          <div {...stylex.props(s.wide)}>
            <LabelPropertyField
              label={style.label}
              onChange={(label) => commit({ ...style, label })}
            />
          </div>
        </div>
      ) : (
        <>
          <div {...stylex.props(s.grid)}>
            <Field label="Category property" className="nodrag nopan nowheel">
              <TextInput
                value={style.category_property}
                onChange={(event) =>
                  commit({
                    ...style,
                    category_property: event.currentTarget.value,
                  })
                }
              />
            </Field>
            <LabelPropertyField
              label={style.label}
              onChange={(label) => commit({ ...style, label })}
            />
          </div>

          <div {...stylex.props(s.categories)}>
            {style.categories.map((category, categoryIndex) => {
              const replaceCategory = (next: PointCategory) =>
                commit({
                  ...style,
                  categories: style.categories.map((candidate, index) =>
                    index === categoryIndex ? next : candidate,
                  ),
                });
              return (
                <div key={category.id} {...stylex.props(s.category)}>
                  <div {...stylex.props(s.categoryHeader)}>
                    {/* Named by its aria-label, and naked in the category row. */}
                    <input
                      type="text"
                      aria-label={`Category ${categoryIndex + 1} title`}
                      value={category.title}
                      {...interactionProps(stylex.props(s.input))}
                      onChange={(event) =>
                        replaceCategory({
                          ...category,
                          title: event.currentTarget.value,
                        })
                      }
                    />
                    <IconButton
                      label={`Remove category ${categoryIndex + 1}`}
                      title="Remove category"
                      variant="danger"
                      size="sm"
                      className="nodrag nopan nowheel"
                      disabled={style.categories.length === 1}
                      onClick={() =>
                        commit({
                          ...style,
                          categories: style.categories.filter(
                            (_, index) => index !== categoryIndex,
                          ),
                        })
                      }
                    >
                      <Trash2 size={11} />
                    </IconButton>
                  </div>
                  <div {...stylex.props(s.grid)}>
                    <CategoryValuesField
                      key={`${category.id}:${JSON.stringify(category.values)}`}
                      category={category}
                      onChange={replaceCategory}
                    />
                    <ColorField
                      size="sm"
                      className="nodrag nopan nowheel"
                      label="Color"
                      value={category.point.color}
                      onChange={(color) =>
                        replaceCategory({
                          ...category,
                          point: { ...category.point, color },
                        })
                      }
                    />
                    <Field label="Radius" className="nodrag nopan nowheel">
                      <TextInput
                        type="number"
                        min={0}
                        max={128}
                        value={category.point.radius}
                        onChange={(event) =>
                          replaceCategory({
                            ...category,
                            point: {
                              ...category.point,
                              radius: Number(event.currentTarget.value),
                            },
                          })
                        }
                      />
                    </Field>
                    <Field label="Min zoom" className="nodrag nopan nowheel">
                      <TextInput
                        type="number"
                        min={0}
                        max={24}
                        value={category.min_zoom}
                        onChange={(event) =>
                          replaceCategory({
                            ...category,
                            min_zoom: Number(event.currentTarget.value),
                          })
                        }
                      />
                    </Field>
                    <Field label="Max zoom" className="nodrag nopan nowheel">
                      <TextInput
                        type="number"
                        min={0}
                        max={24}
                        value={category.max_zoom}
                        onChange={(event) =>
                          replaceCategory({
                            ...category,
                            max_zoom: Number(event.currentTarget.value),
                          })
                        }
                      />
                    </Field>
                  </div>
                </div>
              );
            })}
          </div>

          <Button
            size="sm"
            variant="secondary"
            className="nodrag nopan nowheel"
            disabled={style.categories.length >= 128}
            onClick={() => {
              const number = style.categories.length + 1;
              commit({
                ...style,
                categories: [
                  ...style.categories,
                  {
                    id: `category_${number}_${createUuid().slice(0, 8)}`,
                    title: `Category ${number}`,
                    values: [number],
                    point: {
                      ...DEFAULT_POINT_STYLE,
                      color: "#d6a700",
                    },
                    min_zoom: 0,
                    max_zoom: 22,
                  },
                ],
              });
            }}
          >
            <Plus size={11} />
            Add category
          </Button>
        </>
      )}
    </section>
  );
}
