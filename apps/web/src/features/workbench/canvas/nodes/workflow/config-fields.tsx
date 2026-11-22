"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ChevronRight, LoaderCircle, Plus, Trash2 } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ColorField } from "@/components/ui/color-field";
import { Field, TextArea, TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Select } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { createUuid } from "../../../model/uuid";
import {
  buildDefaultForField,
  fieldDisplayTitle,
  visibleSchemaFields,
  type ConnectedInputPortMap,
  type DiscriminatedUnionBranch,
  type DiscriminatedUnionSchemaField,
  type NumberTupleItem,
  type NumberTupleSchemaField,
  type ObjectListSchemaField,
  type ObjectSchemaField,
  type PrimitiveListSchemaField,
  type ScalarSchemaField,
  type SchemaField,
  type StringListSchemaField,
} from "../../config-schema";
import type {
  WorkflowNodeSecretInput,
  WorkflowNodeSecretStatus,
  WorkflowNodeSecretState,
} from "../../node-secrets";
import type { WorkflowNodeLayout } from "../../node-layout";
import type { WorkflowNodeData } from "../../types";
import {
  HALF_WIDTH_CELLS,
  fieldFootprint,
  type FieldFootprint,
} from "../field-footprints";
import { TextareaBodyResizeHandle } from "../TextareaBodyResizeHandle";

import { sharedStyles } from "./styles";

/** React Flow leaves a control alone only when it, or an ancestor, says so. */
const CANVAS_CONTROL = "nodrag nopan nowheel";

const s = stylex.create({
  textareaHost: {
    position: "relative",
    width: "100%",
    minHeight: 0,
  },
  textareaHostFill: {
    flex: "1 1 0%",
    display: "flex",
    flexDirection: "column",
    minHeight: 0,
  },
  textareaFill: {
    flex: "1 1 0%",
    width: "100%",
    // Literal keeps StyleX happy (imported layout constants can't be used here).
    minHeight: "96px",
    height: "auto",
  },
  textareaDefault: {
    height: "96px",
  },
  fieldSized: {
    flex: "1 1 0%",
    minHeight: 0,
    display: "flex",
    flexDirection: "column",
  },
  field: { display: "grid", alignContent: "start", gap: "4px", minWidth: 0 },
  /** A label kept only for assistive tech takes no line, and no gap with it. */
  fieldHiddenLabel: { gap: "0px" },
  tupleField: {
    minWidth: 0,
    margin: 0,
    padding: 0,
    borderWidth: 0,
  },
  tupleGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    gap: "6px",
  },
  tupleItem: { minWidth: 0, display: "grid", gap: "3px" },
  tupleItemLabel: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  stringList: {
    display: "grid",
    gap: "5px",
  },
  stringListRow: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 26px",
    alignItems: "center",
    gap: "5px",
  },
  fieldLabel: {
    minWidth: 0,
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
  },
  /** The flag sits 3px off the title, in a row or inside <Field>'s label. */
  requiredGap: { marginLeft: "3px" },
  fieldLabelText: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    // Schema titles arrive the way the property reads ("api key"); the brick
    // shows them as labels.
    textTransform: "capitalize",
  },
  /**
   * <Field> owns its label element, so a call site cannot give it
   * `min-width: 0` to make an ellipsis work. Its labels wrap instead of
   * clipping, which a dense brick can afford and a bleeding line of text
   * across the neighbouring brick cannot.
   */
  fieldLabelTextWrap: {
    whiteSpace: "normal",
    overflow: "visible",
    textOverflow: "clip",
    overflowWrap: "anywhere",
  },
  srOnly: {
    position: "absolute",
    width: "1px",
    height: "1px",
    margin: "-1px",
    padding: 0,
    overflow: "hidden",
    clipPath: "inset(50%)",
    whiteSpace: "nowrap",
    borderWidth: 0,
  },
  /** A toggle row keeps the input row's height so a shelf of bricks lines up. */
  toggleRow: {
    minWidth: 0,
    minHeight: "31px",
    display: "flex",
    alignItems: "center",
  },
  /**
   * A composite field is a quiet frame: a hairline and the field's own header,
   * so nested settings read as one thing without a second card inside the card.
   */
  section: {
    minWidth: 0,
    display: "grid",
    alignContent: "start",
    gap: "6px",
    margin: 0,
    padding: "5px 7px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: tokens.radiusMd,
  },
  sectionOpen: { paddingBottom: "8px" },
  sectionHeader: {
    minWidth: 0,
    minHeight: "22px",
    display: "flex",
    alignItems: "center",
    gap: "6px",
  },
  sectionToggle: {
    flex: "1 1 auto",
    minWidth: 0,
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
  sectionTitle: {
    minWidth: 0,
    flex: "1 1 auto",
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    textOverflow: "ellipsis",
    textTransform: "capitalize",
    whiteSpace: "nowrap",
  },
  sectionSummary: {
    flexShrink: 0,
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 400,
  },
  swatch: {
    width: "10px",
    height: "10px",
    flexShrink: 0,
    borderRadius: "3px",
    boxShadow: `inset 0 0 0 1px ${tokens.colorBorder}`,
  },
  chevron: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    transitionDuration: "120ms",
    transitionProperty: "transform",
  },
  chevronOpen: { transform: "rotate(90deg)" },
  /** Branch and nested fields: two compact controls a row, wide ones alone. */
  nestedGrid: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
    columnGap: "8px",
    rowGap: "7px",
  },
  nestedWide: { gridColumn: "1 / -1" },
  nestedCell: { minWidth: 0 },
  items: { display: "grid", gap: "5px" },
  item: {
    minWidth: 0,
    display: "grid",
    gap: "6px",
    padding: "7px",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceMuted,
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
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  primitiveList: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "minmax(0, 0.8fr) minmax(0, 1.2fr)",
    gap: "6px",
  },
  primitiveListSingle: { gridTemplateColumns: "minmax(0, 1fr)" },
  wide: { gridColumn: "1 / -1" },
  secretField: { alignContent: "start", gap: "5px" },
  secretStatusConfigured: { color: tokens.colorSuccess },
  secretStatusStale: { color: tokens.colorWarning },
  secretStatusError: { color: tokens.colorDanger },
  secretControl: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: "5px",
  },
  secretSummary: {
    minHeight: "26px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
  },
  secretFooter: {
    minHeight: "18px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
  },
  secretHint: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.35,
  },
});

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

/** "GeoPointCategory" → "Category": the noun a list adds one of. */
function itemNoun(field: ObjectListSchemaField): string {
  if (!/^(?:[A-Z][a-z0-9]+){2,}$/.test(field.itemTitle)) return field.itemTitle;
  return field.itemTitle.match(/[A-Z][a-z0-9]+$/)?.[0] ?? field.itemTitle;
}

function sameJson(left: unknown, right: unknown): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

/**
 * Descriptions ride the label tooltip instead of taking a line in the brick:
 * they are schema documentation you read once, not state you monitor.
 */
function FieldLabelText({
  title,
  description,
  wrap = false,
}: {
  title: string;
  description?: string | null;
  /** Set when <Field> draws the label: its label element cannot ellipsize. */
  wrap?: boolean;
}) {
  return (
    <span
      title={description ? `${title} — ${description}` : title}
      {...stylex.props(s.fieldLabelText, wrap ? s.fieldLabelTextWrap : null)}
    >
      {title}
    </span>
  );
}

function RequiredMark({ field }: { field: SchemaField }) {
  return field.required ? (
    <span {...stylex.props(sharedStyles.required, s.requiredGap)}>*</span>
  ) : null;
}

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

function numberTupleValueSignature(value: unknown, length: number): string {
  const tuple = numberTupleValue(value, length);
  if (tuple) return `tuple:${JSON.stringify(tuple)}`;
  return value === null ? `null:${length}` : `unset:${length}`;
}

function parseNumberTupleDraft(
  values: readonly string[],
  items: readonly NumberTupleItem[],
): number[] | null {
  if (values.length !== items.length) return null;
  const parsedValues: number[] = [];
  for (const [index, item] of items.entries()) {
    const raw = values[index] ?? "";
    if (raw === "") return null;
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return null;
    if (item.type === "integer" && !Number.isInteger(parsed)) return null;
    if (item.minimum !== undefined && parsed < item.minimum) return null;
    if (item.maximum !== undefined && parsed > item.maximum) return null;
    parsedValues.push(parsed);
  }
  return parsedValues;
}

const INCOMPLETE_TUPLE = Symbol("incomplete-tuple");

/**
 * A required tuple cannot be authored atomically through its separate inputs,
 * so an incomplete draft stays local to the editor instead of erasing the last
 * valid value. Emptiness only reaches the graph when the schema allows it.
 */
function numberTupleCommitValue(
  draftValues: readonly string[],
  field: NumberTupleSchemaField,
): number[] | null | undefined | typeof INCOMPLETE_TUPLE {
  const parsedValues = parseNumberTupleDraft(draftValues, field.items);
  if (parsedValues) return parsedValues;
  if (!draftValues.every((raw) => raw === "")) return INCOMPLETE_TUPLE;
  if (field.nullable) return null;
  if (field.required) return INCOMPLETE_TUPLE;
  return undefined;
}

function NumberTupleConfigField({
  field,
  value,
  onChange,
}: {
  field: NumberTupleSchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const itemCount = field.items.length;
  const valueSignature = numberTupleValueSignature(value, itemCount);
  const [draftValues, setDraftValues] = React.useState<string[]>(() => {
    const tuple = numberTupleValue(value, itemCount);
    return tuple?.map(String) ?? Array.from({ length: itemCount }, () => "");
  });
  const [touched, setTouched] = React.useState(false);
  const previousValueSignature = React.useRef(valueSignature);
  const pendingValueSignature = React.useRef<string | null>(null);

  React.useEffect(() => {
    if (previousValueSignature.current === valueSignature) return;
    previousValueSignature.current = valueSignature;
    if (pendingValueSignature.current === valueSignature) {
      pendingValueSignature.current = null;
      return;
    }

    pendingValueSignature.current = null;
    const tuple = numberTupleValue(value, itemCount);
    setDraftValues(
      tuple?.map(String) ?? Array.from({ length: itemCount }, () => ""),
    );
    setTouched(false);
  }, [itemCount, value, valueSignature]);

  const draftIsEmpty = draftValues.every((raw) => raw === "");
  const draftIsValid = parseNumberTupleDraft(draftValues, field.items) !== null;
  const showError =
    touched &&
    !draftIsValid &&
    (!draftIsEmpty || (field.required && !field.nullable));
  const title = fieldDisplayTitle(field);

  return (
    <fieldset {...stylex.props(s.field, s.tupleField)}>
      <legend {...stylex.props(s.fieldLabel)}>
        <FieldLabelText
          title={title}
          description={
            field.nullable
              ? `${field.description ?? ""} Leave every value blank to use no bounds.`.trim()
              : field.description
          }
        />
        <RequiredMark field={field} />
      </legend>
      <div {...stylex.props(s.tupleGrid)}>
        {field.items.map((item, index) => (
          <label key={`${item.title}:${index}`} {...stylex.props(s.tupleItem)}>
            <span title={item.title} {...stylex.props(s.tupleItemLabel)}>
              {item.title}
            </span>
            <TextInput
              type="number"
              aria-label={`${title}: ${item.title}`}
              aria-invalid={showError}
              value={draftValues[index] ?? ""}
              min={item.minimum}
              max={item.maximum}
              step={item.type === "integer" ? 1 : "any"}
              className={CANVAS_CONTROL}
              onChange={(event) => {
                const nextDraftValues = [...draftValues];
                nextDraftValues[index] = event.currentTarget.value;
                setDraftValues(nextDraftValues);
                setTouched(true);

                const nextValue = numberTupleCommitValue(
                  nextDraftValues,
                  field,
                );
                if (nextValue === INCOMPLETE_TUPLE) return;
                pendingValueSignature.current = numberTupleValueSignature(
                  nextValue,
                  itemCount,
                );
                onChange(nextValue);
              }}
            />
          </label>
        ))}
      </div>
      {showError ? (
        <Notice tone="danger">
          Enter all {itemCount} values as numbers within the shown ranges.
        </Notice>
      ) : null}
    </fieldset>
  );
}

function StringListConfigField({
  field,
  value,
  onChange,
}: {
  field: StringListSchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const values =
    Array.isArray(value) &&
    value.every((item): item is string => typeof item === "string")
      ? value
      : [];
  const minimumItems = field.minItems ?? 0;
  const canAdd = field.maxItems === undefined || values.length < field.maxItems;
  const canRemove = values.length > minimumItems;
  const title = fieldDisplayTitle(field);

  return (
    <fieldset {...stylex.props(s.field, s.tupleField)}>
      <legend {...stylex.props(s.fieldLabel)}>
        <FieldLabelText title={title} description={field.description} />
        <RequiredMark field={field} />
      </legend>
      <div {...stylex.props(s.stringList)}>
        {values.map((item, index) => (
          <div key={index} {...stylex.props(s.stringListRow)}>
            <TextInput
              type="text"
              aria-label={`${title} item ${index + 1}`}
              value={item}
              minLength={field.itemMinLength}
              maxLength={field.itemMaxLength}
              className={CANVAS_CONTROL}
              onChange={(event) => {
                const nextValues = [...values];
                nextValues[index] = event.currentTarget.value;
                onChange(nextValues);
              }}
            />
            <IconButton
              label={`Remove ${title} item ${index + 1}`}
              title="Remove item"
              variant="danger"
              size="sm"
              className={CANVAS_CONTROL}
              disabled={!canRemove}
              onClick={() => {
                onChange(values.filter((_, itemIndex) => itemIndex !== index));
              }}
            >
              <Trash2 size={13} />
            </IconButton>
          </div>
        ))}
        <Button
          variant="dashed"
          size="sm"
          aria-label={`Add ${title} item`}
          className={CANVAS_CONTROL}
          disabled={!canAdd}
          onClick={() => onChange([...values, ""])}
        >
          <Plus size={13} />
          Add item
        </Button>
      </div>
    </fieldset>
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
  return (["number", "text", "boolean"] as const).filter((kind) =>
    kind === "number"
      ? allowed.has("number") || allowed.has("integer")
      : kind === "text"
        ? allowed.has("string")
        : allowed.has("boolean"),
  );
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
    } else if (kind === "boolean") {
      const normalized = part.toLowerCase();
      if (normalized !== "true" && normalized !== "false") return null;
      values.push(normalized === "true");
    } else {
      const number = Number(part);
      if (!Number.isFinite(number)) return null;
      if (!field.allowedTypes.includes("number") && !Number.isInteger(number)) {
        return null;
      }
      values.push(number);
    }
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
 * Typed values typed as one comma-separated line: the draft stays local while
 * the person types and only a list of the chosen kind reaches the graph.
 */
function PrimitiveListConfigField({
  field,
  value,
  onChange,
}: {
  field: PrimitiveListSchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
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
  const title = fieldDisplayTitle(field);

  const commit = (nextDraft: string, nextKind: PrimitiveKind) => {
    const parsed = parsePrimitiveDraft(nextDraft, nextKind, field);
    if (!parsed) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    if (!sameJson(parsed, values)) onChange(parsed);
  };

  return (
    <div
      {...stylex.props(
        s.primitiveList,
        kinds.length > 1 ? null : s.primitiveListSingle,
      )}
    >
      {kinds.length > 1 ? (
        <Field label="Value type" className={CANVAS_CONTROL}>
          <Select
            size="sm"
            value={kind}
            aria-label={`${title} value type`}
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
        </Field>
      ) : null}
      <Field
        label={
          <>
            <FieldLabelText
              title={title}
              description={field.description}
              wrap
            />
            <RequiredMark field={field} />
          </>
        }
        className={CANVAS_CONTROL}
      >
        <TextInput
          aria-invalid={invalid}
          value={draft}
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
      </Field>
      {invalid ? (
        <Notice tone="danger" xstyle={s.wide}>
          {(field.minItems ?? 0) >= 1
            ? "Enter at least one comma-separated value of the selected type."
            : "Enter comma-separated values of the selected type."}
        </Notice>
      ) : null}
    </div>
  );
}

interface CompositeProps {
  connectedPorts?: ConnectedInputPortMap;
  onStructureChange?: () => void;
}

/** Wide kinds take the whole row of a nested grid; compact ones pair up. */
function nestedFieldIsWide(field: SchemaField): boolean {
  return fieldFootprint(field).columns > HALF_WIDTH_CELLS;
}

function NestedFieldGrid({
  fields,
  value,
  onFieldChange,
  connectedPorts,
  onStructureChange,
}: CompositeProps & {
  fields: readonly SchemaField[];
  value: Readonly<Record<string, unknown>>;
  onFieldChange: (name: string, value: unknown) => void;
}) {
  const visible = visibleSchemaFields(fields, {
    config: value,
    connectedPorts,
  });
  if (!visible.length) return null;
  return (
    <div {...stylex.props(s.nestedGrid)}>
      {visible.map((child) => (
        <div
          key={child.name}
          data-config-field={child.name}
          {...stylex.props(
            s.nestedCell,
            nestedFieldIsWide(child) ? s.nestedWide : null,
          )}
        >
          <ConfigField
            field={child}
            value={value[child.name]}
            connectedPorts={connectedPorts}
            onStructureChange={onStructureChange}
            onChange={(next) => onFieldChange(child.name, next)}
          />
        </div>
      ))}
    </div>
  );
}

/** A schema default, or one built from the object's own field defaults. */
function objectDefault(field: ObjectSchemaField): Record<string, unknown> {
  return (
    record(buildDefaultForField(field)) ??
    record(
      buildDefaultForField({
        ...field,
        defaultValue: undefined,
        examples: undefined,
      }),
    ) ?? { ...field.constFields }
  );
}

/** What a collapsed section shows: its colour, and whether it is off. */
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
  if (!off && typeof color !== "string") return null;
  return (
    <span {...stylex.props(s.sectionSummary)}>
      {typeof color === "string" && /^#[0-9a-fA-F]{6}$/.test(color) ? (
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

function ObjectConfigField({
  field,
  value,
  onChange,
  connectedPorts,
  onStructureChange,
}: CompositeProps & {
  field: ObjectSchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const bodyId = React.useId();
  const title = fieldDisplayTitle(field);
  const effective = value === undefined ? field.defaultValue : value;
  const current = record(effective);
  const enabled = !field.nullable || current !== null;
  const base = current ?? objectDefault(field);
  const commitChild = (name: string, next: unknown) =>
    onChange({ ...field.constFields, ...base, [name]: next });

  if (field.nullable) {
    // An optional settings group is either there or not: the switch is the
    // whole decision, and turning it on writes a complete object.
    return (
      <div
        role="group"
        aria-label={title}
        {...stylex.props(s.section, enabled ? s.sectionOpen : null)}
      >
        <div {...stylex.props(s.sectionHeader)}>
          <span
            title={
              field.description ? `${title} — ${field.description}` : title
            }
            {...stylex.props(s.sectionTitle)}
          >
            {title}
          </span>
          <Switch
            size="dense"
            checked={enabled}
            aria-label={`Use ${title}`}
            className={CANVAS_CONTROL}
            onCheckedChange={(on) => {
              onChange(on ? objectDefault(field) : null);
              onStructureChange?.();
            }}
          />
        </div>
        {enabled ? (
          <NestedFieldGrid
            fields={field.fields}
            value={base}
            connectedPorts={connectedPorts}
            onStructureChange={onStructureChange}
            onFieldChange={commitChild}
          />
        ) : null}
      </div>
    );
  }

  // Settings groups start folded: a raster style is seven sliders a layer
  // rarely needs, and the summary says enough to scan a stack of them.
  return (
    <div
      role="group"
      aria-label={title}
      {...stylex.props(s.section, open ? s.sectionOpen : null)}
    >
      <div {...stylex.props(s.sectionHeader)}>
        <Button
          variant="plain"
          size="text"
          aria-expanded={open}
          aria-controls={open ? bodyId : undefined}
          title={field.description ? `${title} — ${field.description}` : title}
          className={CANVAS_CONTROL}
          xstyle={s.sectionToggle}
          onClick={() => {
            setOpen((next) => !next);
            onStructureChange?.();
          }}
        >
          <ChevronRight
            size={12}
            aria-hidden="true"
            {...stylex.props(s.chevron, open ? s.chevronOpen : null)}
          />
          <span {...stylex.props(s.sectionTitle)}>{title}</span>
          {open ? null : <ObjectSummary fields={field.fields} value={base} />}
        </Button>
      </div>
      {open ? (
        <div id={bodyId}>
          <NestedFieldGrid
            fields={field.fields}
            value={base}
            connectedPorts={connectedPorts}
            onStructureChange={onStructureChange}
            onFieldChange={commitChild}
          />
        </div>
      ) : null}
    </div>
  );
}

function branchObjectField(
  field: DiscriminatedUnionSchemaField,
  branch: DiscriminatedUnionBranch,
): ObjectSchemaField {
  return {
    type: "object",
    name: field.name,
    title: branch.label,
    required: true,
    nullable: false,
    fields: branch.fields,
    constFields: branch.constFields,
    ...(branch.autoIdFields ? { autoIdFields: branch.autoIdFields } : {}),
  };
}

function branchDefault(
  field: DiscriminatedUnionSchemaField,
  branch: DiscriminatedUnionBranch,
): Record<string, unknown> {
  const declared = record(field.defaultValue);
  if (declared?.[field.discriminator] === branch.tag) {
    return structuredClone(declared);
  }
  return (
    record(
      buildDefaultForField(branchObjectField(field, branch), {
        generateId: createUuid,
      }),
    ) ?? { ...branch.constFields }
  );
}

function UnionConfigField({
  field,
  value,
  onChange,
  connectedPorts,
  onStructureChange,
}: CompositeProps & {
  field: DiscriminatedUnionSchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const title = fieldDisplayTitle(field);
  const current = record(value) ?? record(buildDefaultForField(field));
  const activeTag = current?.[field.discriminator];
  const branch =
    field.branches.find((candidate) => candidate.tag === activeTag) ??
    field.branches[0];
  if (!branch) return null;
  const base =
    current?.[field.discriminator] === branch.tag
      ? current
      : branchDefault(field, branch);
  const selectBranch = (tag: string) => {
    const next = field.branches.find((candidate) => candidate.tag === tag);
    if (!next || next.tag === branch.tag) return;
    onChange(branchDefault(field, next));
    onStructureChange?.();
  };
  const segmented = field.widget === "segmented" || field.branches.length <= 3;

  return (
    <div
      role="group"
      aria-label={title}
      {...stylex.props(s.section, s.sectionOpen)}
    >
      <div {...stylex.props(s.sectionHeader)}>
        <span
          title={field.description ? `${title} — ${field.description}` : title}
          {...stylex.props(s.sectionTitle)}
        >
          {title}
        </span>
        {segmented ? (
          <SegmentedControl
            size="sm"
            aria-label={`${title} mode`}
            className={CANVAS_CONTROL}
            value={branch.tag}
            options={field.branches.map((option) => ({
              value: option.tag,
              label: option.label,
            }))}
            onValueChange={selectBranch}
          />
        ) : (
          <Select
            size="sm"
            aria-label={`${title} mode`}
            className={CANVAS_CONTROL}
            value={branch.tag}
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
      <NestedFieldGrid
        fields={branch.fields}
        value={base}
        connectedPorts={connectedPorts}
        onStructureChange={onStructureChange}
        onFieldChange={(name, next) =>
          onChange({ ...branch.constFields, ...base, [name]: next })
        }
      />
    </div>
  );
}

function ObjectListConfigField({
  field,
  value,
  onChange,
  connectedPorts,
  onStructureChange,
}: CompositeProps & {
  field: ObjectListSchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const title = fieldDisplayTitle(field);
  const noun = itemNoun(field);
  const source = Array.isArray(value) ? value : buildDefaultForField(field);
  const items = (Array.isArray(source) ? source : []).map(
    (item) => record(item) ?? {},
  );
  const titleField = field.itemFields.find(
    (child): child is ScalarSchemaField =>
      child.name === "title" && child.type === "string" && !child.enumValues,
  );
  const bodyFields = field.itemFields.filter((child) => child !== titleField);
  const canAdd = field.maxItems === undefined || items.length < field.maxItems;
  const canRemove = items.length > (field.minItems ?? 0);
  const itemShape: ObjectSchemaField = {
    type: "object",
    name: field.name,
    title: noun,
    required: true,
    nullable: false,
    fields: field.itemFields,
    ...(field.itemConstFields ? { constFields: field.itemConstFields } : {}),
    ...(field.itemAutoIdFields ? { autoIdFields: field.itemAutoIdFields } : {}),
  };
  const commitItem = (index: number, name: string, next: unknown) =>
    onChange(
      items.map((item, itemIndex) =>
        itemIndex === index
          ? { ...field.itemConstFields, ...item, [name]: next }
          : item,
      ),
    );

  return (
    <fieldset {...stylex.props(s.field, s.tupleField)}>
      <legend {...stylex.props(s.fieldLabel)}>
        <FieldLabelText title={title} description={field.description} />
        <RequiredMark field={field} />
      </legend>
      <div {...stylex.props(s.items)}>
        {items.map((item, index) => {
          const itemName = `${noun} ${index + 1}`;
          return (
            <div
              key={typeof item.id === "string" ? item.id : index}
              role="group"
              aria-label={itemName}
              {...stylex.props(s.item)}
            >
              <div {...stylex.props(s.itemHeader)}>
                {titleField ? (
                  <TextInput
                    aria-label={`${itemName} title`}
                    value={typeof item.title === "string" ? item.title : ""}
                    minLength={titleField.minLength}
                    maxLength={titleField.maxLength}
                    className={CANVAS_CONTROL}
                    onChange={(event) =>
                      commitItem(index, "title", event.currentTarget.value)
                    }
                  />
                ) : (
                  <span {...stylex.props(s.itemTitle)}>{itemName}</span>
                )}
                <IconButton
                  label={`Remove ${itemName.toLowerCase()}`}
                  title={`Remove ${noun.toLowerCase()}`}
                  variant="danger"
                  size="sm"
                  className={CANVAS_CONTROL}
                  disabled={!canRemove}
                  onClick={() => {
                    onChange(
                      items.filter((_, itemIndex) => itemIndex !== index),
                    );
                    onStructureChange?.();
                  }}
                >
                  <Trash2 size={12} />
                </IconButton>
              </div>
              <NestedFieldGrid
                fields={bodyFields}
                value={item}
                connectedPorts={connectedPorts}
                onStructureChange={onStructureChange}
                onFieldChange={(name, next) => commitItem(index, name, next)}
              />
            </div>
          );
        })}
        <Button
          variant="dashed"
          size="sm"
          className={CANVAS_CONTROL}
          disabled={!canAdd}
          onClick={() => {
            const next =
              record(
                buildDefaultForField(itemShape, {
                  index: items.length,
                  generateId: createUuid,
                }),
              ) ?? {};
            // Every new item would otherwise read the schema's one example.
            if (
              titleField &&
              (next.title === undefined ||
                next.title === "" ||
                sameJson(next.title, titleField.examples?.[0]))
            ) {
              next.title = `${noun} ${items.length + 1}`;
            }
            onChange([...items, next]);
            onStructureChange?.();
          }}
        >
          <Plus size={13} />
          Add {noun.toLowerCase()}
        </Button>
      </div>
    </fieldset>
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

export function ConfigField({
  field,
  value,
  onChange,
  fillHeight = false,
  labelHidden = false,
  layout = null,
  onLayoutDraft,
  onLayoutCommit,
  connectedPorts,
  onStructureChange,
}: CompositeProps & {
  field: SchemaField;
  value: unknown;
  onChange: (value: unknown) => void;
  fillHeight?: boolean;
  /** Kept for assistive tech when the node title already names the field. */
  labelHidden?: boolean;
  layout?: WorkflowNodeLayout | null;
  onLayoutDraft?: (layout: WorkflowNodeLayout | null) => void;
  onLayoutCommit?: (layout: WorkflowNodeLayout | null) => void;
}) {
  const composite = { connectedPorts, onStructureChange };
  switch (field.type) {
    case "number-tuple":
      return (
        <NumberTupleConfigField
          field={field}
          value={value}
          onChange={onChange}
        />
      );
    case "string-list":
      return (
        <StringListConfigField
          field={field}
          value={value}
          onChange={onChange}
        />
      );
    case "primitive-list":
      return (
        <PrimitiveListConfigField
          field={field}
          value={value}
          onChange={onChange}
        />
      );
    case "object":
      return (
        <ObjectConfigField
          field={field}
          value={value}
          onChange={onChange}
          {...composite}
        />
      );
    case "discriminated-union":
      return (
        <UnionConfigField
          field={field}
          value={value}
          onChange={onChange}
          {...composite}
        />
      );
    case "object-list":
      return (
        <ObjectListConfigField
          field={field}
          value={value}
          onChange={onChange}
          {...composite}
        />
      );
  }

  const title = fieldDisplayTitle(field);
  // An unset value draws as the schema default the run would use.
  const effective = value === undefined ? field.defaultValue : value;
  const labelNode = (
    <>
      <FieldLabelText title={title} description={field.description} />
      <RequiredMark field={field} />
    </>
  );

  if (field.type === "boolean") {
    const checked = effective === true;
    const toggleProps = {
      checked,
      label: labelNode,
      size: "sm" as const,
      title: field.description,
      className: CANVAS_CONTROL,
      onCheckedChange: (next: boolean) => onChange(next),
    };
    return (
      <div {...stylex.props(s.toggleRow)}>
        {field.widget === "switch" ? (
          <Switch {...toggleProps} />
        ) : (
          <Checkbox {...toggleProps} />
        )}
      </div>
    );
  }

  const enumValues = field.enumValues;
  const knownEnumValue =
    effective === undefined ||
    enumValues?.some((option) => Object.is(option, effective));
  if (
    enumValues &&
    field.widget === "segmented" &&
    enumValues.length >= 2 &&
    enumValues.length <= 4 &&
    enumValues.every((option) => typeof option === "string") &&
    knownEnumValue
  ) {
    return (
      <div {...stylex.props(s.field)}>
        <span {...stylex.props(s.fieldLabel, labelHidden ? s.srOnly : null)}>
          {labelNode}
        </span>
        <SegmentedControl
          size="sm"
          aria-label={title}
          className={CANVAS_CONTROL}
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
    (field.type === "number" || field.type === "integer") &&
    field.widget === "slider" &&
    field.minimum !== undefined &&
    field.maximum !== undefined &&
    !enumValues
  ) {
    const min = field.minimum;
    const max = field.maximum;
    return (
      <Slider
        size="md"
        label={labelNode}
        min={min}
        max={max}
        step={sliderStep(field, min, max)}
        value={
          typeof value === "number"
            ? value
            : typeof field.defaultValue === "number"
              ? field.defaultValue
              : min
        }
        className={CANVAS_CONTROL}
        onValueChange={(next) => onChange(next)}
      />
    );
  }

  if (field.type === "string" && field.widget === "color" && !enumValues) {
    return (
      <ColorField
        size="sm"
        label={title}
        className={CANVAS_CONTROL}
        value={
          typeof value === "string" && /^#[0-9a-fA-F]{6}$/.test(value)
            ? value
            : typeof field.defaultValue === "string"
              ? field.defaultValue
              : "#000000"
        }
        onChange={(next) => onChange(next)}
      />
    );
  }

  const isTextarea =
    field.type === "string" &&
    (field.widget === "textarea" || field.format === "textarea");
  const canResizeBody = isTextarea && onLayoutDraft && onLayoutCommit;
  const oneBased =
    field.type === "integer" && field.widget === "one-based-integer";
  const fieldLabel = (
    <>
      <FieldLabelText title={title} description={field.description} wrap />
      <RequiredMark field={field} />
    </>
  );

  let control: React.ReactNode;
  if (enumValues) {
    const saved =
      typeof value === "string" || typeof value === "number" ? value : null;
    control = (
      <Select
        value={
          saved ??
          (typeof effective === "string" || typeof effective === "number"
            ? effective
            : "")
        }
        className={CANVAS_CONTROL}
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
        {saved === null &&
        typeof effective !== "string" &&
        typeof effective !== "number" ? (
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
  } else if (isTextarea) {
    control = (
      <div
        {...stylex.props(
          s.textareaHost,
          fillHeight ? s.textareaHostFill : null,
        )}
      >
        <TextArea
          value={typeof value === "string" ? value : ""}
          minLength={field.minLength}
          maxLength={field.maxLength}
          className={CANVAS_CONTROL}
          xstyle={fillHeight ? s.textareaFill : s.textareaDefault}
          onChange={(event) => onChange(event.currentTarget.value)}
        />
        {canResizeBody ? (
          <TextareaBodyResizeHandle
            layout={layout}
            ariaLabel={`Resize ${title} field`}
            onDraft={onLayoutDraft}
            onCommit={onLayoutCommit}
          />
        ) : null}
      </div>
    );
  } else if (oneBased) {
    // Stored zero-based, shown the way a person counts: page 1 is index 0.
    control = (
      <TextInput
        type="number"
        value={typeof value === "number" ? value + 1 : ""}
        placeholder={
          typeof field.defaultValue === "number"
            ? String(field.defaultValue + 1)
            : undefined
        }
        min={field.minimum !== undefined ? field.minimum + 1 : undefined}
        max={field.maximum !== undefined ? field.maximum + 1 : undefined}
        step={1}
        className={CANVAS_CONTROL}
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
        type={numeric ? "number" : "text"}
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
        step={field.type === "integer" ? 1 : undefined}
        className={CANVAS_CONTROL}
        onChange={(event) => {
          const raw = event.currentTarget.value;
          onChange(numeric ? (raw === "" ? undefined : Number(raw)) : raw);
        }}
      />
    );
  }

  return (
    <Field
      label={
        labelHidden ? (
          <span {...stylex.props(s.srOnly)}>{fieldLabel}</span>
        ) : (
          fieldLabel
        )
      }
      xstyle={[
        s.field,
        labelHidden ? s.fieldHiddenLabel : null,
        fillHeight ? s.fieldSized : null,
      ]}
    >
      {control}
    </Field>
  );
}

const SECRET_STATUS_LABEL: Record<WorkflowNodeSecretState, string> = {
  unknown: "Status unavailable",
  loading: "Checking…",
  unconfigured: "No key",
  configured: "Key saved",
  stale: "Key out of date",
  applying: "Saving…",
  removing: "Removing…",
  error: "Could not save the key",
};

/**
 * A key saved for an older endpoint or an unsaved node cannot be trusted, so a
 * configured status only counts once the binding it was saved for still holds.
 */
export function effectiveSecretStatus(
  data: WorkflowNodeData,
  input: WorkflowNodeSecretInput,
): WorkflowNodeSecretStatus {
  const storedStatus = data.secretStatuses[input.name] ?? { state: "unknown" };
  const ready = data.secretInputReadiness[input.name] ?? false;
  return !ready && storedStatus.state === "configured"
    ? { state: "stale" }
    : storedStatus;
}

export function SecretInputField({
  id,
  data,
  input,
}: {
  id: string;
  data: WorkflowNodeData;
  input: WorkflowNodeSecretInput;
}) {
  const [value, setValue] = React.useState("");
  const [changing, setChanging] = React.useState(false);
  const ready = data.secretInputReadiness[input.name] ?? false;
  const status = effectiveSecretStatus(data, input);
  const busy = status.state === "applying" || status.state === "removing";
  const canApply =
    ready && !busy && value.length > 0 && Boolean(data.onApplyNodeSecret);
  const canRemove =
    ready &&
    !busy &&
    status.state === "configured" &&
    Boolean(data.onRemoveNodeSecret);
  const hint = !ready
    ? status.state === "stale"
      ? "Save the changed settings, then paste a new key."
      : "Save this node before adding a key."
    : status.state === "stale"
      ? "Paste a key for the current endpoint."
      : status.state === "error"
        ? (status.message ?? "The key could not be saved.")
        : (input.description ??
          "Write-only · a saved key cannot be read back.");

  if (status.state === "configured" && !changing) {
    return (
      <div className={CANVAS_CONTROL} {...stylex.props(s.secretSummary)}>
        <span>
          {input.title} ·{" "}
          <span role="status" {...stylex.props(s.secretStatusConfigured)}>
            {SECRET_STATUS_LABEL.configured}
          </span>
        </span>
        <Button size="xs" variant="ghost" onClick={() => setChanging(true)}>
          Replace
        </Button>
      </div>
    );
  }

  return (
    <form
      className={CANVAS_CONTROL}
      onSubmit={(event) => {
        event.preventDefault();
        if (!canApply) return;
        void data.onApplyNodeSecret?.(id, input.name, value).then((applied) => {
          if (applied) {
            setValue("");
            setChanging(false);
          }
        });
      }}
    >
      <Field
        label={<FieldLabelText title={input.title} wrap />}
        aside={
          <span
            role="status"
            {...stylex.props(
              status.state === "configured" ? s.secretStatusConfigured : null,
              status.state === "stale" ? s.secretStatusStale : null,
              status.state === "error" ? s.secretStatusError : null,
            )}
          >
            {SECRET_STATUS_LABEL[status.state]}
          </span>
        }
        xstyle={s.secretField}
      >
        <div {...stylex.props(s.secretControl)}>
          <TextInput
            mono
            type="password"
            name={`${id}-${input.name}`}
            value={value}
            autoComplete="off"
            autoCapitalize="none"
            spellCheck={false}
            data-1p-ignore
            data-lpignore="true"
            data-bwignore
            aria-label={input.title}
            placeholder={
              status.state === "configured" ? "Replace key" : "Paste key"
            }
            disabled={!ready || busy}
            className={CANVAS_CONTROL}
            onChange={(event) => setValue(event.currentTarget.value)}
          />
          <Button
            type="submit"
            variant="soft"
            size="sm"
            className={CANVAS_CONTROL}
            disabled={!canApply}
          >
            {status.state === "applying" ? (
              <LoaderCircle size={11} {...stylex.props(sharedStyles.spinner)} />
            ) : null}
            Apply
          </Button>
        </div>
        <div {...stylex.props(s.secretFooter)}>
          <p {...stylex.props(s.secretHint)}>{hint}</p>
          {status.state === "configured" ? (
            <Button
              size="xs"
              variant="ghost"
              className={CANVAS_CONTROL}
              onClick={() => {
                setValue("");
                setChanging(false);
              }}
            >
              Done
            </Button>
          ) : null}
          <Button
            variant="danger"
            size="xs"
            className={CANVAS_CONTROL}
            disabled={!canRemove}
            onClick={() => {
              if (!canRemove) return;
              void data.onRemoveNodeSecret?.(id, input.name).then((removed) => {
                if (removed) setValue("");
              });
            }}
          >
            Remove
          </Button>
        </div>
      </Field>
    </form>
  );
}

export interface ConfigBrick {
  kind: "field";
  field: SchemaField;
  footprint: FieldFootprint;
}

/**
 * A lone field whose title the node title already contains ("Text" on a "Text
 * input" node) names the same thing twice. The label stays in the accessibility
 * tree; only its row is reclaimed. Booleans keep theirs — a bare checkbox
 * reads as nothing at all — and so do composite fields, whose title heads a
 * section rather than a control.
 */
export function configFieldLabelIsRedundant(
  nodeTitle: string,
  bricks: readonly ConfigBrick[],
): boolean {
  const only = bricks.length === 1 ? bricks[0] : undefined;
  if (!only) return false;
  const { field } = only;
  if (
    field.type !== "string" &&
    field.type !== "number" &&
    field.type !== "integer"
  ) {
    return false;
  }
  const squash = (value: string) =>
    value.toLowerCase().replace(/[^a-z0-9]/g, "");
  const title = squash(fieldDisplayTitle(field));
  return title.length > 0 && squash(nodeTitle).includes(title);
}

export function configBricks(fields: readonly SchemaField[]): ConfigBrick[] {
  return fields.map((field) => ({
    kind: "field",
    field,
    footprint: fieldFootprint(field),
  }));
}
