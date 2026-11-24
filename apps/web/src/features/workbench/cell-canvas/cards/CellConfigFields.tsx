"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { AlertTriangle, ChevronRight, Plus, Trash2 } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ColorWell } from "@/components/ui/color-field";
import { Field, TextArea, TextInput } from "@/components/ui/field";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { createUuid } from "../../authoring/uuid";
import {
  buildDefaultForField,
  fieldDisplayTitle,
  type ConnectedInputPortMap,
  type DiscriminatedUnionSchemaField,
  type NumberTupleItem,
  type NumberTupleSchemaField,
  type ObjectListSchemaField,
  type ObjectSchemaField,
  type PrimitiveListSchemaField,
  type ScalarSchemaField,
  type SchemaField,
  type StringListSchemaField,
} from "../../config-ui/config-schema";
import { configControlKind } from "../../config-ui/field-footprints";
import { configShelfPlacements, fieldDenseRows } from "../cell-card-geometry";
import {
  ADVANCED_SECTION_KEY,
  advancedGroupIndices,
  branchDefault,
  childPath,
  nestedFieldPlan,
  objectDefault,
  objectFieldState,
  objectListItemNoun,
  objectListItems,
  objectListTitleField,
  objectSectionKey,
  schemaFieldDenseRows,
  sectionOpen,
  stringListValues,
  titledBranchValue,
  titledNewItem,
  unionFieldState,
  type ShelfPlacement,
} from "../cell-config-plan";
import type { CellConfigFieldSpec } from "../cell-contracts";

/**
 * The controls of an operator card's config band, every kind a config schema
 * declares, drawn on the card's 25px lattice.
 *
 * A field takes the dense rows `cell-config-plan` counted for it, and a
 * composite field (an object, a union, a list of items) places its children
 * on the same rows by the same plan: nothing here is measured, so the band
 * the adapter sized always holds exactly what it draws. Controls use the
 * kit's `dense` step; the segmented control has no dense step, so it takes
 * `sm` (24px), which still fits its row.
 */

/** One dense row: a control row of the band, and one card cell. */
const ROW = 25;
/** A labelled control's block: its 9px/1.3 label, the dense gap, the control. */
const LABELLED_BLOCK_HEIGHT = 12 + 3 + ROW;

/**
 * The space a labelled control keeps under itself when it is centred in a
 * shelf taller than its block. A control shorter than its shelf stands on that
 * same line, so a checkbox joins the select it shares the shelf with instead
 * of floating beside the select's label.
 */
function shelfBottomInset(rows: number): number {
  return Math.max(0, (rows * ROW - LABELLED_BLOCK_HEIGHT) / 2);
}

const s = stylex.create({
  band: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gridAutoRows: `${ROW}px`,
    columnGap: "8px",
    rowGap: 0,
    alignItems: "center",
    paddingInline: "10px",
    overflow: "hidden",
  },
  /** A composite's own lattice: rows stay 25px, columns pair up again. */
  lattice: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gridAutoRows: `${ROW}px`,
    columnGap: "6px",
    rowGap: 0,
    alignItems: "center",
  },
  /** A child of a composite, all of its rows, one column or both. */
  cell: { minWidth: 0, minHeight: 0, alignSelf: "stretch", display: "grid" },
  /** A control shorter than its shelf: it stands on the shelf's bottom. */
  cellOnShelfBottom: { alignContent: "end" },
  /**
   * The fields the `Advanced` row discloses, framed as the group it heads: a
   * recessed tray the colour of a well, kept off the plate's edge by less than
   * the band's own gutter so its two columns land on the primary ones. Its
   * counted rows are the tray's whole height, so nothing is clipped and no
   * dead space is left under the last control.
   */
  advancedGroup: {
    minWidth: 0,
    alignSelf: "stretch",
    width: "calc(100% + 12px)",
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gridAutoRows: `${ROW}px`,
    columnGap: "8px",
    rowGap: 0,
    alignItems: "center",
    marginInline: "-6px",
    paddingInline: "6px",
    boxSizing: "border-box",
    borderRadius: tokens.radiusSm,
    backgroundColor: `color-mix(in oklab, ${tokens.colorSurfaceSunken} 45%, transparent)`,
    boxShadow: `inset 2px 0 0 0 ${tokens.colorBorder}, inset -1px 0 0 0 ${tokens.colorDivider}, inset 0 -1px 0 0 ${tokens.colorDivider}`,
  },
  /** A labelled control: the label on the first row, the control under it. */
  labelled: {
    minWidth: 0,
    alignContent: "center",
    gap: "3px",
  },
  label: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "3px",
    color: tokens.colorMuted,
    fontSize: "9px",
    fontWeight: 500,
    lineHeight: 1.3,
  },
  labelText: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  labelInvalid: { color: tokens.colorDanger },
  required: { flexShrink: 0, color: tokens.colorSubtle },
  /**
   * A control that shares its row with the next one's: 3px short of the row
   * so two stacked rows never touch. The kit's dense step is 25px, the whole
   * row; lists and tuples are the only places it is taken down.
   */
  rowControl: { height: "22px" },
  textarea: { height: "78px", minHeight: 0 },
  /** One control row tall, so a boolean shares a shelf row with a select. */
  toggleRow: {
    minWidth: 0,
    height: `${ROW}px`,
    display: "flex",
    alignItems: "center",
  },
  colorRow: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "25px minmax(0, 1fr)",
    alignItems: "center",
    gap: "5px",
  },
  /**
   * A composite field is a quiet frame on the plate: a hairline and a faint
   * sunken tint drawn inside its rows, so the frame costs no height.
   */
  frame: {
    minWidth: 0,
    alignSelf: "stretch",
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr)",
    gridAutoRows: `${ROW}px`,
    paddingInline: "6px",
    borderRadius: tokens.radiusMd,
    backgroundColor: `color-mix(in oklab, ${tokens.colorSurfaceSunken} 55%, transparent)`,
    boxShadow: `inset 0 0 0 1px ${tokens.colorDivider}`,
  },
  frameHeader: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  frameTitle: {
    minWidth: 0,
    flexGrow: 1,
    flexBasis: 0,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: "9px",
    fontWeight: 600,
    textOverflow: "ellipsis",
    textTransform: "capitalize",
    whiteSpace: "nowrap",
  },
  headerToggle: {
    minWidth: 0,
    flexGrow: 1,
    flexBasis: 0,
    height: "22px",
    justifyContent: "flex-start",
    gap: "5px",
    paddingInline: "2px",
    textAlign: "left",
    textDecoration: {
      default: "none",
      ":hover:not(:disabled)": "none",
      ":focus-visible": "none",
    },
  },
  /** The branch picker shares the frame's 25px header row and may not win it. */
  selector: { flexShrink: 0, maxWidth: "62%" },
  /** A segment's label: truncates inside its segment instead of spilling. */
  segmentLabel: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  latticeSingle: { gridTemplateColumns: "minmax(0, 1fr)" },
  summary: {
    flexShrink: 0,
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    color: tokens.colorSubtle,
    fontSize: "9px",
    fontWeight: 400,
  },
  swatch: {
    width: "9px",
    height: "9px",
    flexShrink: 0,
    borderRadius: "3px",
    boxShadow: `inset 0 0 0 1px ${tokens.colorBorder}`,
  },
  chevron: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0s",
    },
    transitionProperty: "transform",
  },
  chevronOpen: { transform: "rotate(90deg)" },
  /** An item of a list: a lighter plate inside the frame. */
  item: {
    minWidth: 0,
    alignSelf: "stretch",
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr)",
    gridAutoRows: `${ROW}px`,
    paddingInline: "5px",
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorHover,
  },
  itemHeader: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    alignItems: "center",
    gap: "5px",
  },
  itemTitle: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: "9px",
    fontWeight: 600,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  listRow: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 20px",
    alignItems: "center",
    gap: "5px",
  },
  addRow: { minWidth: 0, display: "flex", alignItems: "center" },
  tupleRow: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    alignItems: "center",
    columnGap: "6px",
  },
  tupleItem: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "auto minmax(0, 1fr)",
    alignItems: "center",
    gap: "4px",
  },
  tupleItemLabel: {
    maxWidth: "48px",
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: "9px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  primitiveRow: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "minmax(0, 2fr) minmax(0, 3fr)",
    gap: "5px",
  },
  /** A group header: one quiet full-width row above the fields it opens. */
  sectionRow: {
    width: "100%",
    minWidth: 0,
    height: "22px",
    justifyContent: "flex-start",
    gap: "5px",
    paddingInline: "2px",
    color: tokens.colorMuted,
    fontSize: "9px",
    fontWeight: 600,
    textDecoration: {
      default: "none",
      ":hover:not(:disabled)": "none",
      ":focus-visible": "none",
    },
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    borderRadius: 0,
  },
  /**
   * The `Advanced` disclosure. A hairline above it parts the primary
   * parameters from the section it heads, in both states: nothing is left
   * hanging under the row once the fields it discloses appear.
   */
  advancedRow: {
    // Six past the column pair on each side, the gutter the band keeps free:
    // the row's text starts where the fields' do, and its pill and separator
    // read as the card's rather than as a control among the controls.
    minWidth: 0,
    width: "calc(100% + 12px)",
    height: "24px",
    alignSelf: "center",
    justifyContent: "flex-start",
    gap: "5px",
    marginInline: "-6px",
    paddingInline: "6px",
    boxSizing: "border-box",
    borderRadius: tokens.radiusSm,
    color: tokens.colorMuted,
    fontSize: "9px",
    fontWeight: 600,
    textAlign: "left",
    textDecoration: {
      default: "none",
      ":hover:not(:disabled)": "none",
      ":focus-visible": "none",
    },
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
  /** What the disclosure row says about its contents, pushed to the right. */
  sectionAside: {
    flexShrink: 0,
    marginLeft: "auto",
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
  },
  sectionCount: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontWeight: 400,
    fontVariantNumeric: "tabular-nums",
  },
  /** The count of what a disclosure folds away, in a chip of its own. */
  countPill: {
    flexShrink: 0,
    height: "13px",
    paddingInline: "4px",
    boxSizing: "border-box",
    display: "inline-flex",
    alignItems: "center",
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
    fontWeight: 500,
    fontVariantNumeric: "tabular-nums",
    lineHeight: 1,
  },
  /** The open section's quiet way out, shown while the row is hovered. */
  hideHint: { color: tokens.colorSubtle, fontWeight: 500 },
  sectionIssues: { flexShrink: 0, color: tokens.colorDanger },
  issuesRow: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "5px",
    color: tokens.colorDanger,
    fontSize: "9px",
  },
});

type ToggleSection = (key: string, open: boolean) => void;

interface FieldContext {
  sections?: Readonly<Record<string, boolean>>;
  connectedPorts?: ConnectedInputPortMap;
  /** Unset on a card that cannot be edited. */
  onToggleSection?: ToggleSection;
  readOnly: boolean;
}

/**
 * A child's rows on its composite's lattice, from the plan it was counted by.
 * `spareRows` is what its shelf gives it beyond its own rows: a control
 * shorter than the shelf it shares stands on that shelf's bottom.
 */
function placementStyle(
  placement: ShelfPlacement,
  firstRow: number,
  spareRows = 0,
): React.CSSProperties {
  const style: React.CSSProperties = {
    gridRow: `${firstRow + placement.row} / span ${placement.rows}`,
    gridColumn:
      placement.column === null ? "1 / -1" : `${placement.column} / span 1`,
  };
  if (spareRows > 0) {
    style.paddingBottom = `${shelfBottomInset(placement.rows)}px`;
  }
  return style;
}

function rowsStyle(firstRow: number, rows: number): React.CSSProperties {
  return { gridRow: `${firstRow} / span ${Math.max(1, rows)}` };
}

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

function sameJson(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/**
 * A field's name. Its description rides the tooltip rather than taking a
 * row: schema documentation is read once, not watched.
 */
function FieldLabel({
  field,
  title = fieldDisplayTitle(field),
  issue,
  id,
}: {
  field: SchemaField;
  title?: string;
  issue?: string;
  id?: string;
}) {
  const tooltip = [title, field.description, issue].filter(Boolean).join(" — ");
  return (
    <span
      id={id}
      title={tooltip}
      {...stylex.props(s.label, issue ? s.labelInvalid : null)}
    >
      <span {...stylex.props(s.labelText)}>{title}</span>
      {field.required ? (
        <span aria-hidden="true" {...stylex.props(s.required)}>
          *
        </span>
      ) : null}
    </span>
  );
}

function enumOptionLabel(field: SchemaField, option: string | number): string {
  return field.enumLabels?.[String(option)] ?? String(option);
}

/** Readable steps for a bounded number: hundredths on 0–1, wholes on 0–359. */
function sliderStep(field: ScalarSchemaField, min: number, max: number) {
  if (field.type === "integer") return 1;
  const range = max - min;
  if (range <= 2) return 0.05;
  if (range <= 10) return 0.1;
  return 1;
}

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

/** A swatch for the picker, a hex input for the exact value. */
function ColorControl({
  field,
  value,
  onChange,
  readOnly,
  issue,
}: {
  field: ScalarSchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
  readOnly: boolean;
  issue?: string;
}) {
  const title = fieldDisplayTitle(field);
  const color =
    typeof value === "string" && HEX_COLOR.test(value)
      ? value
      : typeof field.defaultValue === "string" &&
          HEX_COLOR.test(field.defaultValue)
        ? field.defaultValue
        : "#000000";
  const [draft, setDraft] = React.useState(color);
  const [synced, setSynced] = React.useState(color);
  if (synced !== color) {
    // A collaborator, an undo or the picker changed it: the input follows.
    setSynced(color);
    setDraft(color);
  }
  return (
    <div {...stylex.props(s.cell, s.labelled)}>
      <FieldLabel field={field} issue={issue} />
      <div {...stylex.props(s.colorRow)}>
        <ColorWell
          size="dense"
          block={false}
          label={title}
          value={color}
          disabled={readOnly}
          onChange={(next) => onChange(next)}
        />
        <TextInput
          size="dense"
          mono
          aria-label={`${title} hex`}
          aria-invalid={!HEX_COLOR.test(draft) || Boolean(issue)}
          value={draft}
          disabled={readOnly}
          spellCheck={false}
          onChange={(event) => {
            const next = event.currentTarget.value.trim();
            setDraft(next);
            if (HEX_COLOR.test(next) && next.toLowerCase() !== color) {
              onChange(next.toLowerCase());
            }
          }}
        />
      </div>
    </div>
  );
}

function ScalarControl({
  field,
  value,
  onChange,
  readOnly,
  issue,
}: {
  field: ScalarSchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
  readOnly: boolean;
  issue?: string;
}) {
  // An unset value draws as the schema default the run would use.
  const effective = value === undefined ? field.defaultValue : value;
  const kind = configControlKind(field);

  if (field.type === "boolean") {
    const props = {
      size: "dense" as const,
      checked: effective === true,
      disabled: readOnly,
      title: field.description,
      label: <FieldLabel field={field} issue={issue} />,
      onCheckedChange: (next: boolean) => onChange(next),
    };
    return (
      <div {...stylex.props(s.toggleRow)}>
        {kind === "switch" ? <Switch {...props} /> : <Checkbox {...props} />}
      </div>
    );
  }

  const enumValues = field.enumValues;
  if (
    kind === "segmented" &&
    enumValues &&
    enumValues.length >= 2 &&
    enumValues.length <= 4 &&
    enumValues.every((option) => typeof option === "string") &&
    (effective === undefined ||
      enumValues.some((option) => Object.is(option, effective)))
  ) {
    return (
      <div {...stylex.props(s.cell, s.labelled)}>
        <FieldLabel field={field} issue={issue} />
        <SegmentedControl
          size="dense"
          aria-label={fieldDisplayTitle(field)}
          disabled={readOnly}
          value={typeof effective === "string" ? effective : ""}
          options={enumValues.map((option) => ({
            value: String(option),
            label: enumOptionLabel(field, option),
          }))}
          onValueChange={(next) => onChange(next)}
        />
      </div>
    );
  }

  if (
    kind === "slider" &&
    field.minimum !== undefined &&
    field.maximum !== undefined &&
    !enumValues
  ) {
    const min = field.minimum;
    const max = field.maximum;
    return (
      <Slider
        size="dense"
        label={<FieldLabel field={field} issue={issue} />}
        min={min}
        max={max}
        step={sliderStep(field, min, max)}
        disabled={readOnly}
        value={
          typeof effective === "number"
            ? Math.min(max, Math.max(min, effective))
            : min
        }
        xstyle={s.labelled}
        onValueChange={(next) => onChange(next)}
      />
    );
  }

  if (kind === "color" && !enumValues) {
    return (
      <ColorControl
        field={field}
        value={value}
        onChange={onChange}
        readOnly={readOnly}
        issue={issue}
      />
    );
  }

  let control: React.ReactNode;
  if (enumValues) {
    const saved =
      typeof value === "string" || typeof value === "number" ? value : null;
    const shown =
      saved ??
      (typeof effective === "string" || typeof effective === "number"
        ? effective
        : "");
    control = (
      <Select
        size="dense"
        value={shown}
        disabled={readOnly}
        onChange={(event) => {
          const selected = event.currentTarget.value;
          onChange(
            field.type === "number" || field.type === "integer"
              ? Number(selected)
              : selected,
          );
        }}
      >
        {saved !== null &&
        !enumValues.some((option) => Object.is(option, saved)) ? (
          <option value={saved} disabled>
            Saved value: {String(saved)}
          </option>
        ) : null}
        {shown === "" ? (
          <option value="" disabled>
            Choose an option
          </option>
        ) : null}
        {enumValues.map((option) => (
          <option key={String(option)} value={option}>
            {enumOptionLabel(field, option)}
          </option>
        ))}
      </Select>
    );
  } else if (kind === "textarea") {
    control = (
      <TextArea
        size="dense"
        rows={3}
        value={typeof value === "string" ? value : ""}
        placeholder={
          typeof field.defaultValue === "string"
            ? field.defaultValue
            : undefined
        }
        minLength={field.minLength}
        maxLength={field.maxLength}
        disabled={readOnly}
        xstyle={s.textarea}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
    );
  } else if (field.type === "integer" && field.widget === "one-based-integer") {
    // Stored zero-based, shown the way a person counts: page 1 is index 0.
    control = (
      <TextInput
        size="dense"
        type="number"
        mono
        value={typeof value === "number" ? value + 1 : ""}
        placeholder={
          typeof field.defaultValue === "number"
            ? String(field.defaultValue + 1)
            : undefined
        }
        min={field.minimum !== undefined ? field.minimum + 1 : undefined}
        max={field.maximum !== undefined ? field.maximum + 1 : undefined}
        step={1}
        disabled={readOnly}
        onChange={(event) => {
          const raw = event.currentTarget.value;
          onChange(raw === "" ? undefined : Number(raw) - 1);
        }}
      />
    );
  } else {
    const numeric = field.type === "number" || field.type === "integer";
    control = (
      <TextInput
        size="dense"
        type={numeric ? "number" : "text"}
        mono={numeric}
        value={
          typeof value === "string" || typeof value === "number" ? value : ""
        }
        placeholder={
          typeof field.defaultValue === "string" ||
          typeof field.defaultValue === "number"
            ? String(field.defaultValue)
            : undefined
        }
        min={field.minimum}
        max={field.maximum}
        minLength={field.minLength}
        maxLength={field.maxLength}
        step={field.type === "integer" ? 1 : numeric ? "any" : undefined}
        disabled={readOnly}
        onChange={(event) => {
          const raw = event.currentTarget.value;
          onChange(numeric ? (raw === "" ? undefined : Number(raw)) : raw);
        }}
      />
    );
  }

  return (
    <Field
      size="dense"
      label={<FieldLabel field={field} issue={issue} />}
      xstyle={s.labelled}
    >
      {issue
        ? React.cloneElement(
            control as React.ReactElement<Record<string, unknown>>,
            { "aria-invalid": true },
          )
        : control}
    </Field>
  );
}

// --- Lists and tuples ---------------------------------------------------------

function numberTupleValue(value: unknown, length: number): number[] | null {
  if (
    !Array.isArray(value) ||
    value.length !== length ||
    !value.every(
      (item): item is number =>
        typeof item === "number" && Number.isFinite(item),
    )
  ) {
    return null;
  }
  return value;
}

function parseTupleDraft(
  values: readonly string[],
  items: readonly NumberTupleItem[],
): number[] | null {
  const parsed: number[] = [];
  for (const [index, item] of items.entries()) {
    const raw = values[index] ?? "";
    if (raw === "") return null;
    const number = Number(raw);
    if (!Number.isFinite(number)) return null;
    if (item.type === "integer" && !Number.isInteger(number)) return null;
    if (item.minimum !== undefined && number < item.minimum) return null;
    if (item.maximum !== undefined && number > item.maximum) return null;
    parsed.push(number);
  }
  return parsed;
}

/**
 * A tuple is authored through separate inputs, so a half-typed draft stays
 * here rather than erasing the last whole value; blank goes out only when the
 * schema allows the field to be empty.
 */
function NumberTupleControl({
  field,
  value,
  onChange,
  readOnly,
  issue,
}: {
  field: NumberTupleSchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
  readOnly: boolean;
  issue?: string;
}) {
  const title = fieldDisplayTitle(field);
  const count = field.items.length;
  const tuple = numberTupleValue(
    value === undefined ? field.defaultValue : value,
    count,
  );
  const signature = JSON.stringify(tuple);
  const [synced, setSynced] = React.useState(signature);
  const [draft, setDraft] = React.useState<string[]>(
    () => tuple?.map(String) ?? field.items.map(() => ""),
  );
  if (synced !== signature) {
    setSynced(signature);
    setDraft(tuple?.map(String) ?? field.items.map(() => ""));
  }
  const invalid =
    Boolean(issue) ||
    (parseTupleDraft(draft, field.items) === null &&
      !draft.every((raw) => raw === ""));
  const pairs: NumberTupleItem[][] = [];
  field.items.forEach((item, index) => {
    if (index % 2 === 0) pairs.push([item]);
    else pairs.at(-1)?.push(item);
  });

  return (
    <div
      role="group"
      aria-label={title}
      {...stylex.props(s.cell, s.lattice, s.latticeSingle)}
    >
      <FieldLabel field={field} issue={issue} />
      {pairs.map((pair, pairIndex) => (
        <div key={pairIndex} {...stylex.props(s.tupleRow)}>
          {pair.map((item, offset) => {
            const index = pairIndex * 2 + offset;
            return (
              <label
                key={`${item.title}:${index}`}
                {...stylex.props(s.tupleItem)}
              >
                <span title={item.title} {...stylex.props(s.tupleItemLabel)}>
                  {item.title}
                </span>
                <TextInput
                  size="dense"
                  type="number"
                  mono
                  aria-label={`${title}: ${item.title}`}
                  aria-invalid={invalid}
                  value={draft[index] ?? ""}
                  min={item.minimum}
                  max={item.maximum}
                  step={item.type === "integer" ? 1 : "any"}
                  disabled={readOnly}
                  xstyle={s.rowControl}
                  onChange={(event) => {
                    const next = [...draft];
                    next[index] = event.currentTarget.value;
                    setDraft(next);
                    const parsed = parseTupleDraft(next, field.items);
                    if (parsed) {
                      setSynced(JSON.stringify(parsed));
                      onChange(parsed);
                    } else if (next.every((raw) => raw === "")) {
                      if (field.nullable) onChange(null);
                      else if (!field.required) onChange(undefined);
                    }
                  }}
                />
              </label>
            );
          })}
        </div>
      ))}
    </div>
  );
}

function StringListControl({
  field,
  value,
  onChange,
  readOnly,
  issue,
}: {
  field: StringListSchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
  readOnly: boolean;
  issue?: string;
}) {
  const title = fieldDisplayTitle(field);
  const values = stringListValues(field, value);
  const canAdd =
    !readOnly &&
    (field.maxItems === undefined || values.length < field.maxItems);
  const canRemove = !readOnly && values.length > (field.minItems ?? 0);
  return (
    <div
      role="group"
      aria-label={title}
      {...stylex.props(s.cell, s.lattice, s.latticeSingle)}
    >
      <FieldLabel field={field} issue={issue} />
      {values.map((item, index) => (
        <div key={index} {...stylex.props(s.listRow)}>
          <TextInput
            size="dense"
            aria-label={`${title} item ${index + 1}`}
            value={item}
            minLength={field.itemMinLength}
            maxLength={field.itemMaxLength}
            disabled={readOnly}
            xstyle={s.rowControl}
            onChange={(event) => {
              const next = [...values];
              next[index] = event.currentTarget.value;
              onChange(next);
            }}
          />
          <IconButton
            size="2xs"
            variant="ghost"
            label={`Remove ${title} item ${index + 1}`}
            disabled={!canRemove}
            onClick={() =>
              onChange(values.filter((_, itemIndex) => itemIndex !== index))
            }
          >
            <Trash2 size={11} />
          </IconButton>
        </div>
      ))}
      <div {...stylex.props(s.addRow)}>
        <Button
          size="xs"
          variant="dashed"
          aria-label={`Add ${title} item`}
          disabled={!canAdd}
          onClick={() => onChange([...values, ""])}
        >
          <Plus size={11} />
          Add item
        </Button>
      </div>
    </div>
  );
}

type PrimitiveValue = string | number | boolean;
type PrimitiveKind = "number" | "text" | "boolean";

const PRIMITIVE_KIND_LABEL: Record<PrimitiveKind, string> = {
  number: "Numbers",
  text: "Text",
  boolean: "Booleans",
};

function primitiveKinds(field: PrimitiveListSchemaField): PrimitiveKind[] {
  const allowed = new Set(field.allowedTypes);
  const kinds: PrimitiveKind[] = [];
  if (allowed.has("number") || allowed.has("integer")) kinds.push("number");
  if (allowed.has("string")) kinds.push("text");
  if (allowed.has("boolean")) kinds.push("boolean");
  return kinds;
}

function primitiveKindOf(
  values: readonly PrimitiveValue[],
  kinds: readonly PrimitiveKind[],
): PrimitiveKind {
  const fallback = kinds[0] ?? "text";
  if (!values.length) return fallback;
  if (values.every((value) => typeof value === "number")) return "number";
  if (values.every((value) => typeof value === "boolean")) return "boolean";
  return kinds.includes("text") ? "text" : fallback;
}

/** Every part must parse as the chosen kind; one stray part rejects the draft. */
function parsePrimitiveDraft(
  draft: string,
  kind: PrimitiveKind,
  field: PrimitiveListSchemaField,
): PrimitiveValue[] | null {
  const parts = draft
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean);
  const values: PrimitiveValue[] = [];
  for (const part of parts) {
    if (kind === "text") {
      values.push(part);
      continue;
    }
    if (kind === "boolean") {
      const normalized = part.toLowerCase();
      if (normalized !== "true" && normalized !== "false") return null;
      values.push(normalized === "true");
      continue;
    }
    const number = Number(part);
    if (!Number.isFinite(number)) return null;
    if (!field.allowedTypes.includes("number") && !Number.isInteger(number)) {
      return null;
    }
    values.push(number);
  }
  if (values.length < (field.minItems ?? 0)) return null;
  if (field.maxItems !== undefined && values.length > field.maxItems) {
    return null;
  }
  return values;
}

function primitiveValues(value: unknown): PrimitiveValue[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (item): item is PrimitiveValue =>
      typeof item === "string" ||
      typeof item === "boolean" ||
      (typeof item === "number" && Number.isFinite(item)),
  );
}

/**
 * Typed values as one comma-separated line: the draft stays here while the
 * person types, and only a list of the chosen kind reaches the graph.
 */
function PrimitiveListControl({
  field,
  value,
  onChange,
  readOnly,
  issue,
}: {
  field: PrimitiveListSchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
  readOnly: boolean;
  issue?: string;
}) {
  const title = fieldDisplayTitle(field);
  const kinds = primitiveKinds(field);
  const values = primitiveValues(
    Array.isArray(value) ? value : buildDefaultForField(field),
  );
  const signature = JSON.stringify(values);
  const [synced, setSynced] = React.useState(signature);
  const [draft, setDraft] = React.useState(() => values.join(", "));
  const [kind, setKind] = React.useState(() => primitiveKindOf(values, kinds));
  const [invalid, setInvalid] = React.useState(false);
  if (synced !== signature) {
    // A collaborator or an undo changed the list: the draft follows it.
    setSynced(signature);
    setDraft(values.join(", "));
    setKind(primitiveKindOf(values, kinds));
    setInvalid(false);
  }
  const commit = (nextDraft: string, nextKind: PrimitiveKind) => {
    const parsed = parsePrimitiveDraft(nextDraft, nextKind, field);
    if (!parsed) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    if (!sameJson(parsed, values)) onChange(parsed);
  };
  const input = (
    <TextInput
      size="dense"
      aria-label={title}
      aria-invalid={invalid || Boolean(issue)}
      value={draft}
      disabled={readOnly}
      placeholder={
        kind === "number" ? "1, 2, 3" : kind === "boolean" ? "true" : "a, b"
      }
      onChange={(event) => {
        setDraft(event.currentTarget.value);
        setInvalid(false);
      }}
      onBlur={() => commit(draft, kind)}
      onKeyDown={(event) => {
        if (event.key === "Enter") {
          event.preventDefault();
          commit(draft, kind);
        }
      }}
    />
  );
  return (
    <div {...stylex.props(s.cell, s.labelled)}>
      <FieldLabel
        field={field}
        issue={
          invalid ? "Enter comma-separated values of the selected type." : issue
        }
      />
      {kinds.length > 1 ? (
        <div {...stylex.props(s.primitiveRow)}>
          <Select
            size="dense"
            aria-label={`${title} value type`}
            value={kind}
            disabled={readOnly}
            onChange={(event) => {
              const nextKind = event.currentTarget.value as PrimitiveKind;
              setKind(nextKind);
              commit(draft, nextKind);
            }}
          >
            {kinds.map((option) => (
              <option key={option} value={option}>
                {PRIMITIVE_KIND_LABEL[option]}
              </option>
            ))}
          </Select>
          {input}
        </div>
      ) : (
        input
      )}
    </div>
  );
}

// --- Composite fields -----------------------------------------------------------

/** The children of a composite field, placed on its lattice from `firstRow`. */
function NestedFields({
  fields,
  value,
  path,
  firstRow,
  context,
  onFieldChange,
}: {
  fields: readonly SchemaField[];
  value: Readonly<Record<string, unknown>>;
  path: string;
  firstRow: number;
  context: FieldContext;
  onFieldChange: (name: string, value: unknown) => void;
}) {
  const plan = nestedFieldPlan(fields, value, path, context);
  if (plan.fields.length === 0) return null;
  return (
    <div
      {...stylex.props(s.lattice)}
      style={rowsStyle(firstRow, plan.totalRows)}
    >
      {plan.fields.map((child, index) => {
        const placement = plan.placements[index];
        if (!placement) return null;
        const ownRows = schemaFieldDenseRows(
          child,
          value[child.name],
          childPath(path, child.name),
          context,
        );
        const spareRows = placement.rows - ownRows;
        return (
          <div
            key={child.name}
            data-config-field={childPath(path, child.name)}
            {...stylex.props(
              s.cell,
              spareRows > 0 ? s.cellOnShelfBottom : null,
            )}
            style={placementStyle(placement, 1, spareRows)}
          >
            <SchemaFieldControl
              field={child}
              value={value[child.name]}
              path={childPath(path, child.name)}
              context={context}
              onChange={(next) => onFieldChange(child.name, next)}
            />
          </div>
        );
      })}
    </div>
  );
}

/** What a folded object says: its colour, and whether it is off. */
function ObjectSummary({
  fields,
  value,
}: {
  fields: readonly SchemaField[];
  value: Readonly<Record<string, unknown>>;
}) {
  const colorField = fields.find(
    (field) => field.type === "string" && field.widget === "color",
  );
  const color = colorField ? value[colorField.name] : undefined;
  const off = fields.some(
    (field) =>
      field.name === "enabled" &&
      field.type === "boolean" &&
      value.enabled === false,
  );
  if (!off && !(typeof color === "string" && HEX_COLOR.test(color))) {
    return null;
  }
  return (
    <span {...stylex.props(s.summary)}>
      {typeof color === "string" && HEX_COLOR.test(color) ? (
        <span
          aria-hidden="true"
          {...stylex.props(s.swatch)}
          style={{ backgroundColor: color }}
        />
      ) : null}
      {off ? "Off" : null}
    </span>
  );
}

function ObjectControl({
  field,
  value,
  path,
  context,
  onChange,
}: {
  field: ObjectSchemaField;
  value: unknown;
  path: string;
  context: FieldContext;
  onChange: (value: unknown) => void;
}) {
  const title = fieldDisplayTitle(field);
  const { enabled, base } = objectFieldState(field, value);
  const key = objectSectionKey(path);
  const commitChild = (name: string, next: unknown) =>
    onChange({ ...field.constFields, ...base, [name]: next });

  if (field.nullable) {
    // An optional settings group is there or not: the switch is the whole
    // decision, and turning it on writes a complete object.
    return (
      <div role="group" aria-label={title} {...stylex.props(s.frame)}>
        <div {...stylex.props(s.frameHeader)}>
          <span
            title={
              field.description ? `${title} — ${field.description}` : title
            }
            {...stylex.props(s.frameTitle)}
          >
            {title}
          </span>
          <Switch
            size="dense"
            checked={enabled}
            aria-label={`Use ${title}`}
            disabled={context.readOnly}
            onCheckedChange={(on) =>
              onChange(on ? objectDefault(field, createUuid) : null)
            }
          />
        </div>
        {enabled ? (
          <NestedFields
            fields={field.fields}
            value={base}
            path={path}
            firstRow={2}
            context={context}
            onFieldChange={commitChild}
          />
        ) : null}
      </div>
    );
  }

  // Settings groups start folded: a raster style is seven sliders a layer
  // rarely needs, and the summary says enough to scan a stack of them.
  const open = sectionOpen(context.sections, key, false);
  return (
    <div
      role="group"
      aria-label={title}
      data-config-section={key}
      {...stylex.props(s.frame)}
    >
      <div {...stylex.props(s.frameHeader)}>
        <Button
          variant="plain"
          size="text"
          aria-expanded={open}
          title={field.description ? `${title} — ${field.description}` : title}
          disabled={!context.onToggleSection}
          xstyle={s.headerToggle}
          onClick={() => context.onToggleSection?.(key, !open)}
        >
          <ChevronRight
            size={11}
            aria-hidden="true"
            {...stylex.props(s.chevron, open ? s.chevronOpen : null)}
          />
          <span {...stylex.props(s.frameTitle)}>{title}</span>
          {open ? null : <ObjectSummary fields={field.fields} value={base} />}
        </Button>
      </div>
      {open ? (
        <NestedFields
          fields={field.fields}
          value={base}
          path={path}
          firstRow={2}
          context={context}
          onFieldChange={commitChild}
        />
      ) : null}
    </div>
  );
}

/**
 * Whether a union's branch titles fit as segments in the header row's picker,
 * which has 62% of a 300px card. A schema's `$defs` title is often a class name
 * (`GeoCategorizedPointStyle`), and two of those collide in one segmented
 * track, so a long title set draws the dense select instead — whatever widget
 * the schema asked for.
 */
export function unionBranchesFitSegments(labels: readonly string[]): boolean {
  if (labels.length < 2 || labels.length > 3) return false;
  let total = 0;
  for (const label of labels) {
    if (label.length > UNION_SEGMENT_MAX_CHARS) return false;
    total += label.length;
  }
  return total <= UNION_SEGMENTS_MAX_CHARS;
}

const UNION_SEGMENT_MAX_CHARS = 12;
const UNION_SEGMENTS_MAX_CHARS = 20;

function UnionControl({
  field,
  value,
  path,
  context,
  onChange,
}: {
  field: DiscriminatedUnionSchemaField;
  value: unknown;
  path: string;
  context: FieldContext;
  onChange: (value: unknown) => void;
}) {
  const title = fieldDisplayTitle(field);
  const state = unionFieldState(field, value);
  if (!state) return null;
  const { branch, base } = state;
  const selectBranch = (tag: string) => {
    const next = field.branches.find((candidate) => candidate.tag === tag);
    if (!next || next.tag === branch.tag) return;
    onChange(titledBranchValue(next, branchDefault(field, next, createUuid)));
  };
  const segmented = unionBranchesFitSegments(
    field.branches.map((option) => option.label),
  );
  return (
    <div
      role="group"
      aria-label={title}
      data-config-union={path}
      data-config-branch={branch.tag}
      {...stylex.props(s.frame)}
    >
      <div {...stylex.props(s.frameHeader)}>
        <span
          title={field.description ? `${title} — ${field.description}` : title}
          {...stylex.props(s.frameTitle)}
        >
          {title}
        </span>
        {segmented ? (
          <SegmentedControl
            size="dense"
            aria-label={`${title} mode`}
            disabled={context.readOnly}
            value={branch.tag}
            options={field.branches.map((option) => ({
              value: option.tag,
              label: (
                <span title={option.label} {...stylex.props(s.segmentLabel)}>
                  {option.label}
                </span>
              ),
            }))}
            xstyle={s.selector}
            onValueChange={selectBranch}
          />
        ) : (
          <Select
            size="dense"
            aria-label={`${title} mode`}
            disabled={context.readOnly}
            block={false}
            value={branch.tag}
            title={branch.label}
            xstyle={s.selector}
            onChange={(event) => selectBranch(event.currentTarget.value)}
          >
            {field.branches.map((option) => (
              <option key={option.tag} value={option.tag}>
                {option.label}
              </option>
            ))}
          </Select>
        )}
      </div>
      <NestedFields
        fields={branch.fields}
        value={base}
        path={path}
        firstRow={2}
        context={context}
        onFieldChange={(name, next) =>
          onChange({ ...branch.constFields, ...base, [name]: next })
        }
      />
    </div>
  );
}

function ObjectListControl({
  field,
  value,
  path,
  context,
  onChange,
  issue,
}: {
  field: ObjectListSchemaField;
  value: unknown;
  path: string;
  context: FieldContext;
  onChange: (value: unknown) => void;
  issue?: string;
}) {
  const title = fieldDisplayTitle(field);
  const noun = objectListItemNoun(field);
  const items = objectListItems(field, value);
  const titleField = objectListTitleField(field);
  const bodyFields = field.itemFields.filter((child) => child !== titleField);
  const canAdd =
    !context.readOnly &&
    (field.maxItems === undefined || items.length < field.maxItems);
  const canRemove = !context.readOnly && items.length > (field.minItems ?? 0);
  const commitItem = (index: number, name: string, next: unknown) =>
    onChange(
      items.map((item, itemIndex) =>
        itemIndex === index
          ? { ...field.itemConstFields, ...item, [name]: next }
          : item,
      ),
    );
  const addItem = () => {
    const shape: ObjectSchemaField = {
      type: "object",
      name: field.name,
      title: noun,
      required: true,
      nullable: false,
      fields: field.itemFields,
      ...(field.itemConstFields ? { constFields: field.itemConstFields } : {}),
      ...(field.itemAutoIdFields
        ? { autoIdFields: field.itemAutoIdFields }
        : {}),
    };
    const next =
      record(
        buildDefaultForField(shape, {
          index: items.length,
          generateId: createUuid,
        }),
      ) ?? {};
    onChange([...items, titledNewItem(field, next, items.length)]);
  };

  // Each item is its header row and its body's rows, one after another
  // under the list's title row.
  const itemRows = items.map(
    (item, index) =>
      1 +
      nestedFieldPlan(bodyFields, item, childPath(path, index), context)
        .totalRows,
  );
  const firstRows: number[] = [];
  let nextRow = 2;
  for (const rows of itemRows) {
    firstRows.push(nextRow);
    nextRow += rows;
  }
  const addRow = nextRow;
  return (
    <div
      role="group"
      aria-label={title}
      data-config-list={path}
      {...stylex.props(s.frame)}
    >
      <FieldLabel field={field} issue={issue} />
      {items.map((item, index) => {
        const itemPath = childPath(path, index);
        const firstRow = firstRows[index] ?? 2;
        const bodyRows = (itemRows[index] ?? 1) - 1;
        const itemName = `${noun} ${index + 1}`;
        return (
          <div
            key={typeof item.id === "string" ? item.id : index}
            role="group"
            aria-label={itemName}
            data-config-item={itemPath}
            {...stylex.props(s.item)}
            style={rowsStyle(firstRow, 1 + bodyRows)}
          >
            <div {...stylex.props(s.itemHeader)}>
              {titleField ? (
                <TextInput
                  size="dense"
                  aria-label={`${itemName} title`}
                  value={typeof item.title === "string" ? item.title : ""}
                  disabled={context.readOnly}
                  xstyle={s.rowControl}
                  onChange={(event) =>
                    commitItem(index, "title", event.currentTarget.value)
                  }
                />
              ) : (
                <span {...stylex.props(s.itemTitle)}>{itemName}</span>
              )}
              <IconButton
                size="2xs"
                variant="ghost"
                label={`Remove ${itemName.toLowerCase()}`}
                disabled={!canRemove}
                onClick={() =>
                  onChange(items.filter((_, itemIndex) => itemIndex !== index))
                }
              >
                <Trash2 size={11} />
              </IconButton>
            </div>
            <NestedFields
              fields={bodyFields}
              value={item}
              path={itemPath}
              firstRow={2}
              context={context}
              onFieldChange={(name, next) => commitItem(index, name, next)}
            />
          </div>
        );
      })}
      <div {...stylex.props(s.addRow)} style={rowsStyle(addRow, 1)}>
        <Button size="xs" variant="dashed" disabled={!canAdd} onClick={addItem}>
          <Plus size={11} />
          Add {noun.toLowerCase()}
        </Button>
      </div>
    </div>
  );
}

function SchemaFieldControl({
  field,
  value,
  path,
  context,
  onChange,
  issue,
}: {
  field: SchemaField;
  value: unknown;
  path: string;
  context: FieldContext;
  onChange: (value: unknown) => void;
  issue?: string;
}) {
  const shared = { value, onChange, issue, readOnly: context.readOnly };
  switch (field.type) {
    case "number-tuple":
      return <NumberTupleControl field={field} {...shared} />;
    case "string-list":
      return <StringListControl field={field} {...shared} />;
    case "primitive-list":
      return <PrimitiveListControl field={field} {...shared} />;
    case "object":
      return (
        <ObjectControl
          field={field}
          value={value}
          path={path}
          context={context}
          onChange={onChange}
        />
      );
    case "discriminated-union":
      return (
        <UnionControl
          field={field}
          value={value}
          path={path}
          context={context}
          onChange={onChange}
        />
      );
    case "object-list":
      return (
        <ObjectListControl
          field={field}
          path={path}
          context={context}
          {...shared}
        />
      );
    default:
      return <ScalarControl field={field} {...shared} />;
  }
}

// --- Plain fields, for surfaces built without a schema --------------------------

function PlainFieldControl({
  field,
  onChange,
}: {
  field: CellConfigFieldSpec;
  onChange: (value: string | number | boolean) => void;
}) {
  const text = String(field.value ?? "");
  switch (field.kind) {
    case "toggle":
      return (
        <div {...stylex.props(s.toggleRow)}>
          <Switch
            size="dense"
            checked={Boolean(field.value)}
            label={field.label}
            onCheckedChange={onChange}
          />
        </div>
      );
    case "multiline":
      return (
        <Field size="dense" label={field.label} xstyle={s.labelled}>
          <TextArea
            size="dense"
            rows={2}
            value={text}
            placeholder={field.placeholder}
            onChange={(event) => onChange(event.target.value)}
          />
        </Field>
      );
    case "select":
      return (
        <Field size="dense" label={field.label} xstyle={s.labelled}>
          <Select
            size="dense"
            value={text}
            onChange={(event) => onChange(event.target.value)}
          >
            {(field.options ?? []).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        </Field>
      );
    case "number":
      return (
        <Field size="dense" label={field.label} xstyle={s.labelled}>
          <TextInput
            size="dense"
            type="number"
            mono
            value={text}
            placeholder={field.placeholder}
            onChange={(event) => onChange(Number(event.target.value))}
          />
        </Field>
      );
    default:
      return (
        <Field size="dense" label={field.label} xstyle={s.labelled}>
          <TextInput
            size="dense"
            value={text}
            placeholder={field.placeholder}
            onChange={(event) => onChange(event.target.value)}
          />
        </Field>
      );
  }
}

/** A group header or the advanced fold: chevron, name, and what it holds. */
function SectionRow({
  field,
  onToggleSection,
}: {
  field: CellConfigFieldSpec;
  onToggleSection?: ToggleSection;
}) {
  const section = field.section;
  // The way out of an open section stays quiet until the row is hovered or
  // focused, so the row reads as the section's name first and "Hide" second.
  const [revealed, setRevealed] = React.useState(false);
  if (!section) return null;
  const advanced = field.kind === "advanced";
  const reveal = () => setRevealed(true);
  const conceal = () => setRevealed(false);
  return (
    <Button
      variant="plain"
      size="text"
      aria-expanded={section.open}
      aria-label={
        advanced
          ? `${section.open ? "Hide" : "Show"} ${field.label.toLowerCase()} parameters`
          : undefined
      }
      title={
        advanced
          ? `${section.count} advanced ${
              section.count === 1 ? "parameter" : "parameters"
            } at their default`
          : field.description
      }
      disabled={!onToggleSection}
      data-config-section={section.key}
      {...(advanced
        ? {
            "data-config-advanced": section.open ? "open" : "closed",
            onPointerEnter: reveal,
            onPointerLeave: conceal,
            onFocus: reveal,
            onBlur: conceal,
          }
        : {})}
      xstyle={advanced ? s.advancedRow : s.sectionRow}
      onClick={() => onToggleSection?.(section.key, !section.open)}
    >
      <ChevronRight
        size={advanced ? 10 : 11}
        aria-hidden="true"
        {...stylex.props(s.chevron, section.open ? s.chevronOpen : null)}
      />
      <span {...stylex.props(s.labelText)}>{field.label}</span>
      <span {...stylex.props(s.sectionAside)}>
        {section.issueCount > 0 ? (
          <span {...stylex.props(s.sectionIssues)}>
            {section.issueCount === 1
              ? "1 issue"
              : `${section.issueCount} issues`}
          </span>
        ) : null}
        {advanced && section.open && revealed ? (
          <span aria-hidden="true" {...stylex.props(s.hideHint)}>
            Hide
          </span>
        ) : null}
        <span {...stylex.props(advanced ? s.countPill : s.sectionCount)}>
          {section.count}
        </span>
      </span>
    </Button>
  );
}

export interface CellConfigBandProps {
  fields: readonly CellConfigFieldSpec[];
  sections?: Readonly<Record<string, boolean>>;
  connectedPorts?: ConnectedInputPortMap;
  /** The band's top and height on the plate, from the card's layout plan. */
  style: React.CSSProperties;
  /** Unset on a card that cannot be edited: its controls draw disabled. */
  onChange?: (fieldId: string, value: unknown) => void;
  onToggleSection?: ToggleSection;
  /** Stops a press on a control from starting a card drag. */
  onPointerDown?: (event: React.PointerEvent) => void;
  className?: string;
}

/**
 * The config band: each entry on the shelves its row count was planned for.
 * A schema entry draws its real control; an entry without a schema (a test
 * fixture, a sandbox surface) draws the plain control its `kind` names.
 *
 * The fields the `Advanced` row discloses are drawn last, but never below it:
 * they share one recessed tray that starts on the row under the disclosure and
 * spans exactly the rows the plan counted for them, so opening the section
 * grows the card by those rows and nothing else.
 */
export function CellConfigBand({
  fields,
  sections,
  connectedPorts,
  style,
  onChange,
  onToggleSection,
  onPointerDown,
  className,
}: CellConfigBandProps) {
  const { placements } = configShelfPlacements(fields);
  const context: FieldContext = {
    sections,
    connectedPorts,
    onToggleSection,
    readOnly: onChange === undefined,
  };
  const band = stylex.props(s.band);

  const groupIndices = advancedGroupIndices(fields);
  const groupHead = groupIndices[0];
  const groupStart =
    groupHead === undefined ? 0 : (placements[groupHead]?.row ?? 0);
  let groupRows = 0;
  for (const index of groupIndices) {
    const placement = placements[index];
    if (placement) {
      groupRows = Math.max(
        groupRows,
        placement.row + placement.rows - groupStart,
      );
    }
  }
  const inGroup = new Set(groupIndices);

  const entryCell = (index: number, firstRow: number): React.ReactNode => {
    const field = fields[index];
    const placement = placements[index];
    if (!field || !placement) return null;
    let control: React.ReactNode;
    if (field.kind === "group" || field.kind === "advanced") {
      control = <SectionRow field={field} onToggleSection={onToggleSection} />;
    } else if (field.kind === "issues") {
      control = (
        <span role="alert" {...stylex.props(s.issuesRow)}>
          <AlertTriangle size={11} aria-hidden="true" />
          <span {...stylex.props(s.labelText)} title={field.label}>
            {field.label}
          </span>
        </span>
      );
    } else if (field.schemaField) {
      control = (
        <SchemaFieldControl
          field={field.schemaField}
          value={field.rawValue}
          path={field.id}
          context={context}
          issue={field.issue}
          onChange={(next) => onChange?.(field.id, next)}
        />
      );
    } else {
      control = (
        <PlainFieldControl
          field={field}
          onChange={(next) => onChange?.(field.id, next)}
        />
      );
    }
    const spareRows = placement.rows - fieldDenseRows(field);
    return (
      <div
        key={field.id}
        data-config-field={field.id}
        data-config-rows={fieldDenseRows(field)}
        {...stylex.props(s.cell, spareRows > 0 ? s.cellOnShelfBottom : null)}
        style={placementStyle(placement, firstRow, spareRows)}
      >
        {control}
      </div>
    );
  };

  return (
    <div
      data-config-band="true"
      onPointerDown={onPointerDown}
      className={[band.className, className].filter(Boolean).join(" ")}
      style={{ ...band.style, ...style }}
    >
      {fields.map((field, index) => {
        if (!inGroup.has(index)) return entryCell(index, 1);
        // One tray for the whole section, drawn where its first field sits.
        if (index !== groupHead || groupRows <= 0) return null;
        return (
          <div
            key={`:${ADVANCED_SECTION_KEY}:group`}
            data-config-advanced-group={ADVANCED_SECTION_KEY}
            {...stylex.props(s.advancedGroup)}
            style={{
              gridRow: `${groupStart + 1} / span ${groupRows}`,
              gridColumn: "1 / -1",
            }}
          >
            {groupIndices.map((grouped) => entryCell(grouped, 1 - groupStart))}
          </div>
        );
      })}
    </div>
  );
}
