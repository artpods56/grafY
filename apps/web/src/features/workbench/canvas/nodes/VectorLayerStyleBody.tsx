"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Plus, Trash2 } from "lucide-react";

import { createUuid } from "@/features/workbench/model/uuid";
import { tokens } from "@/lib/stylex/tokens.stylex";
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
    height: "28px",
    paddingInline: "7px",
    borderWidth: 0,
    borderRadius: "7px",
    outline: {
      default: "none",
      ":focus": `2px solid ${tokens.colorAccentBorder}`,
    },
    backgroundColor: tokens.colorSurface,
    color: tokens.colorTextEmphasis,
    fontSize: "10px",
    fontWeight: 650,
  },
  color: {
    width: "100%",
    height: "28px",
    padding: "3px",
    borderWidth: 0,
    borderRadius: "7px",
    backgroundColor: tokens.colorSurfaceMuted,
    cursor: "pointer",
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
  iconButton: {
    width: "24px",
    height: "24px",
    display: "grid",
    placeItems: "center",
    padding: 0,
    borderWidth: 0,
    borderRadius: "6px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorDangerHover,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorDanger },
    cursor: "pointer",
  },
  iconButtonDisabled: {
    color: tokens.colorTextDisabled,
    cursor: "not-allowed",
  },
  addButton: {
    minHeight: "28px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "5px",
    paddingInline: "9px",
    borderWidth: 1,
    borderStyle: "dashed",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "7px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 700,
  },
  error: {
    color: tokens.colorDanger,
    fontSize: "10px",
  },
});

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
  const parts = value.split(",").map((part) => part.trim()).filter(Boolean);
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
    <label {...stylex.props(s.field)}>
      <span {...stylex.props(s.label)}>Label property</span>
      <input
        type="text"
        value={label?.property ?? ""}
        placeholder="No labels"
        {...interactionProps(stylex.props(s.input))}
        onChange={(event) => {
          const property = event.currentTarget.value;
          onChange(
            property
              ? { ...(label ?? DEFAULT_LABEL_STYLE), property }
              : null,
          );
        }}
      />
    </label>
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
        <select
          value={kind}
          {...interactionProps(stylex.props(s.select))}
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
        </select>
      </label>
      <label {...stylex.props(s.field)}>
        <span {...stylex.props(s.label)}>Values</span>
        <input
          type="text"
          aria-invalid={invalid}
          value={draft}
          placeholder="1, 2, 3"
          {...interactionProps(stylex.props(s.input))}
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
      </label>
      {invalid ? (
        <span role="alert" {...stylex.props(s.error, s.wide)}>
          Enter at least one comma-separated value of the selected type.
        </span>
      ) : null}
    </>
  );
}

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
        <select
          aria-label="Feature style mode"
          value={style.kind}
          {...interactionProps(stylex.props(s.select))}
          onChange={(event) =>
            commit(
              event.currentTarget.value === "categorized_points"
                ? DEFAULT_CATEGORIZED_STYLE
                : DEFAULT_UNIFORM_STYLE,
            )
          }
        >
          <option value="vector">Uniform</option>
          <option value="categorized_points">Categories</option>
        </select>
      </div>

      {style.kind === "vector" ? (
        <div {...stylex.props(s.grid)}>
          <label {...stylex.props(s.field)}>
            <span {...stylex.props(s.label)}>Point color</span>
            <input
              type="color"
              value={style.point.color}
              {...interactionProps(stylex.props(s.color))}
              onChange={(event) =>
                commit({
                  ...style,
                  point: { ...style.point, color: event.currentTarget.value },
                })
              }
            />
          </label>
          <label {...stylex.props(s.field)}>
            <span {...stylex.props(s.label)}>Point radius</span>
            <input
              type="number"
              min={0}
              max={128}
              value={style.point.radius}
              {...interactionProps(stylex.props(s.input))}
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
          </label>
          <label {...stylex.props(s.field)}>
            <span {...stylex.props(s.label)}>Line color</span>
            <input
              type="color"
              value={style.line.color}
              {...interactionProps(stylex.props(s.color))}
              onChange={(event) =>
                commit({
                  ...style,
                  line: { ...style.line, color: event.currentTarget.value },
                })
              }
            />
          </label>
          <label {...stylex.props(s.field)}>
            <span {...stylex.props(s.label)}>Line width</span>
            <input
              type="number"
              min={0}
              max={64}
              step="0.5"
              value={style.line.width}
              {...interactionProps(stylex.props(s.input))}
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
          </label>
          <label {...stylex.props(s.field)}>
            <span {...stylex.props(s.label)}>Fill color</span>
            <input
              type="color"
              value={style.fill.color}
              {...interactionProps(stylex.props(s.color))}
              onChange={(event) =>
                commit({
                  ...style,
                  fill: { ...style.fill, color: event.currentTarget.value },
                })
              }
            />
          </label>
          <label {...stylex.props(s.field)}>
            <span {...stylex.props(s.label)}>Fill opacity</span>
            <input
              type="number"
              min={0}
              max={1}
              step="0.05"
              value={style.fill.opacity}
              {...interactionProps(stylex.props(s.input))}
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
          </label>
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
            <label {...stylex.props(s.field)}>
              <span {...stylex.props(s.label)}>Category property</span>
              <input
                type="text"
                value={style.category_property}
                {...interactionProps(stylex.props(s.input))}
                onChange={(event) =>
                  commit({
                    ...style,
                    category_property: event.currentTarget.value,
                  })
                }
              />
            </label>
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
                    index === categoryIndex ? next : candidate
                  ),
                });
              return (
                <div key={category.id} {...stylex.props(s.category)}>
                  <div {...stylex.props(s.categoryHeader)}>
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
                    <button
                      type="button"
                      disabled={style.categories.length === 1}
                      aria-label={`Remove category ${categoryIndex + 1}`}
                      title="Remove category"
                      {...interactionProps(
                        stylex.props(
                          s.iconButton,
                          style.categories.length === 1
                            ? s.iconButtonDisabled
                            : null,
                        ),
                      )}
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
                    </button>
                  </div>
                  <div {...stylex.props(s.grid)}>
                    <CategoryValuesField
                      key={`${category.id}:${JSON.stringify(category.values)}`}
                      category={category}
                      onChange={replaceCategory}
                    />
                    <label {...stylex.props(s.field)}>
                      <span {...stylex.props(s.label)}>Color</span>
                      <input
                        type="color"
                        value={category.point.color}
                        {...interactionProps(stylex.props(s.color))}
                        onChange={(event) =>
                          replaceCategory({
                            ...category,
                            point: {
                              ...category.point,
                              color: event.currentTarget.value,
                            },
                          })
                        }
                      />
                    </label>
                    <label {...stylex.props(s.field)}>
                      <span {...stylex.props(s.label)}>Radius</span>
                      <input
                        type="number"
                        min={0}
                        max={128}
                        value={category.point.radius}
                        {...interactionProps(stylex.props(s.input))}
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
                    </label>
                    <label {...stylex.props(s.field)}>
                      <span {...stylex.props(s.label)}>Min zoom</span>
                      <input
                        type="number"
                        min={0}
                        max={24}
                        value={category.min_zoom}
                        {...interactionProps(stylex.props(s.input))}
                        onChange={(event) =>
                          replaceCategory({
                            ...category,
                            min_zoom: Number(event.currentTarget.value),
                          })
                        }
                      />
                    </label>
                    <label {...stylex.props(s.field)}>
                      <span {...stylex.props(s.label)}>Max zoom</span>
                      <input
                        type="number"
                        min={0}
                        max={24}
                        value={category.max_zoom}
                        {...interactionProps(stylex.props(s.input))}
                        onChange={(event) =>
                          replaceCategory({
                            ...category,
                            max_zoom: Number(event.currentTarget.value),
                          })
                        }
                      />
                    </label>
                  </div>
                </div>
              );
            })}
          </div>

          <button
            type="button"
            disabled={style.categories.length >= 128}
            {...interactionProps(stylex.props(s.addButton))}
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
          </button>
        </>
      )}
    </section>
  );
}
