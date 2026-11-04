"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Check, LoaderCircle, Plus, Trash2 } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { Field, TextArea, TextInput } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  schemaFields,
  type NumberTupleItem,
  type NumberTupleSchemaField,
  type SchemaField,
  type StringListSchemaField,
} from "../../config-schema";
import {
  nodeSecretInputs,
  type WorkflowNodeSecretInput,
  type WorkflowNodeSecretState,
} from "../../node-secrets";
import type { WorkflowNodeLayout } from "../../node-layout";
import type { WorkflowNodeData } from "../../types";
import {
  fieldFootprint,
  secretFootprint,
  type FieldFootprint,
} from "../field-footprints";
import { TextareaBodyResizeHandle } from "../TextareaBodyResizeHandle";

import { nodeInteractionProps } from "./ports";
import { sharedStyles } from "./styles";

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
  field: { display: "grid", alignContent: "start", gap: "4px" },
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
  /**
   * The kit has no select, so the enum field keeps a native one drawn to the
   * same silhouette as the shared inputs beside it.
   */
  select: {
    width: "100%",
    height: "31px",
    paddingInline: "10px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    outline: {
      default: "none",
      ":focus": `2px solid ${tokens.colorAccentBorder}`,
    },
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
  },
  /** <TextArea mono> carries the family; the size and the tab stop stay here. */
  codeTextarea: { fontSize: tokens.fontSizeXs, tabSize: 2 },
  /**
   * The kit has no checkbox. This is the config brick's own treatment: the
   * same silhouette as a text input, with the checked state on the well.
   */
  checkBox: {
    position: "relative",
    width: "100%",
    height: "31px",
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-end",
    paddingInline: "10px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceMuted,
    cursor: "pointer",
    outline: {
      default: "none",
      ":focus-within": `2px solid ${tokens.colorAccentBorder}`,
    },
  },
  checkWell: {
    width: "18px",
    height: "18px",
    flexShrink: 0,
    display: "grid",
    placeItems: "center",
    borderRadius: tokens.radiusSm,
    color: tokens.colorOnAccent,
    boxShadow: `inset 0 0 0 1px ${tokens.colorBorder}`,
  },
  checkWellChecked: {
    backgroundColor: tokens.colorAccent,
    boxShadow: "none",
  },
  checkInput: {
    position: "absolute",
    inset: 0,
    margin: 0,
    opacity: 0,
    cursor: "pointer",
  },
  checkMark: {
    opacity: 0,
    transform: "scale(0.85)",
  },
  checkMarkChecked: {
    opacity: 1,
    transform: "scale(1)",
  },
  secretField: { alignContent: "start", gap: "5px" },
  secretStatusConfigured: { color: tokens.colorSuccess },
  secretStatusStale: { color: tokens.colorWarning },
  secretStatusError: { color: tokens.colorDanger },
  secretControl: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: "5px",
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

  return (
    <fieldset {...stylex.props(s.field, s.tupleField)}>
      <legend {...stylex.props(s.fieldLabel)}>
        <FieldLabelText
          title={field.title}
          description={
            field.nullable
              ? `${field.description ?? ""} Leave every value blank to use no bounds.`.trim()
              : field.description
          }
        />
        {field.required ? (
          <span {...stylex.props(sharedStyles.required, s.requiredGap)}>*</span>
        ) : null}
      </legend>
      <div {...stylex.props(s.tupleGrid)}>
        {field.items.map((item, index) => (
          <label key={`${item.title}:${index}`} {...stylex.props(s.tupleItem)}>
            <span title={item.title} {...stylex.props(s.tupleItemLabel)}>
              {item.title}
            </span>
            <TextInput
              type="number"
              aria-label={`${field.title}: ${item.title}`}
              aria-invalid={showError}
              value={draftValues[index] ?? ""}
              min={item.minimum}
              max={item.maximum}
              step={item.type === "integer" ? 1 : "any"}
              className="nodrag nowheel"
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

  return (
    <fieldset {...stylex.props(s.field, s.tupleField)}>
      <legend {...stylex.props(s.fieldLabel)}>
        <FieldLabelText title={field.title} description={field.description} />
        {field.required ? (
          <span {...stylex.props(sharedStyles.required, s.requiredGap)}>*</span>
        ) : null}
      </legend>
      <div {...stylex.props(s.stringList)}>
        {values.map((item, index) => (
          <div key={index} {...stylex.props(s.stringListRow)}>
            <TextInput
              type="text"
              aria-label={`${field.title} item ${index + 1}`}
              value={item}
              minLength={field.itemMinLength}
              maxLength={field.itemMaxLength}
              className="nodrag nowheel"
              onChange={(event) => {
                const nextValues = [...values];
                nextValues[index] = event.currentTarget.value;
                onChange(nextValues);
              }}
            />
            <IconButton
              label={`Remove ${field.title} item ${index + 1}`}
              title="Remove item"
              variant="danger"
              size="sm"
              className="nodrag nowheel"
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
          variant="soft"
          size="sm"
          aria-label={`Add ${field.title} item`}
          className="nodrag nowheel"
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

export function ConfigField({
  field,
  value,
  onChange,
  fillHeight = false,
  labelHidden = false,
  layout = null,
  onLayoutDraft,
  onLayoutCommit,
}: {
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
  const fieldProps = stylex.props(s.field, fillHeight ? s.fieldSized : null);
  const labelProps = stylex.props(s.fieldLabel, labelHidden ? s.srOnly : null);
  const canResizeBody =
    field.type === "string" &&
    field.format === "textarea" &&
    onLayoutDraft &&
    onLayoutCommit;
  if (field.type === "number-tuple") {
    return (
      <NumberTupleConfigField field={field} value={value} onChange={onChange} />
    );
  }
  if (field.type === "string-list") {
    return (
      <StringListConfigField field={field} value={value} onChange={onChange} />
    );
  }
  if (field.type === "boolean") {
    const checked = value === true;
    return (
      <label {...fieldProps}>
        <span {...labelProps}>
          <FieldLabelText title={field.title} description={field.description} />
          {field.required ? (
            <span {...stylex.props(sharedStyles.required, s.requiredGap)}>
              *
            </span>
          ) : null}
        </span>
        <span {...stylex.props(s.checkBox)}>
          <input
            type="checkbox"
            checked={checked}
            aria-label={field.title}
            {...nodeInteractionProps(stylex.props(s.checkInput))}
            onChange={(event) => onChange(event.currentTarget.checked)}
          />
          <span
            {...stylex.props(s.checkWell, checked ? s.checkWellChecked : null)}
          >
            <Check
              size={13}
              strokeWidth={2.5}
              aria-hidden
              {...stylex.props(
                s.checkMark,
                checked ? s.checkMarkChecked : null,
              )}
            />
          </span>
        </span>
      </label>
    );
  }

  const requiredMark = field.required ? (
    <span {...stylex.props(sharedStyles.required, s.requiredGap)}>*</span>
  ) : null;

  if (field.enumValues) {
    // The kit has no select, and a native one cannot take part in <Field>'s
    // label wiring, so this field keeps its own label wrapping the control.
    return (
      <label {...fieldProps}>
        <span {...labelProps}>
          <FieldLabelText title={field.title} description={field.description} />
          {requiredMark}
        </span>
        <select
          value={
            typeof value === "string" || typeof value === "number" ? value : ""
          }
          className="nodrag nowheel"
          {...stylex.props(s.select)}
          onChange={(event) => {
            const selected = event.currentTarget.value;
            onChange(
              field.type === "number" || field.type === "integer"
                ? Number(selected)
                : selected,
            );
          }}
        >
          {typeof value === "string" || typeof value === "number" ? (
            field.enumValues.some((option) =>
              Object.is(option, value),
            ) ? null : (
              <option value={value} disabled>
                Saved value: {String(value)}
              </option>
            )
          ) : null}
          {typeof value !== "string" && typeof value !== "number" ? (
            <option value="" disabled>
              Choose an option
            </option>
          ) : null}
          {field.enumValues.map((option) => (
            <option key={String(option)} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
    );
  }

  const fieldLabel = (
    <>
      <FieldLabelText
        title={field.title}
        description={field.description}
        wrap
      />
      {requiredMark}
    </>
  );

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
      {field.type === "string" && field.format === "textarea" ? (
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
            mono={Boolean(field.codeLanguage)}
            className="nodrag nowheel"
            xstyle={[
              field.codeLanguage ? s.codeTextarea : null,
              fillHeight ? s.textareaFill : s.textareaDefault,
            ]}
            onChange={(event) => onChange(event.currentTarget.value)}
          />
          {canResizeBody ? (
            <TextareaBodyResizeHandle
              layout={layout}
              ariaLabel={`Resize ${field.title} field`}
              onDraft={onLayoutDraft}
              onCommit={onLayoutCommit}
            />
          ) : null}
        </div>
      ) : (
        <TextInput
          type={
            field.type === "number" || field.type === "integer"
              ? "number"
              : "text"
          }
          value={
            typeof value === "string" || typeof value === "number" ? value : ""
          }
          min={field.minimum}
          max={field.maximum}
          minLength={field.minLength}
          maxLength={field.maxLength}
          step={field.type === "integer" ? 1 : undefined}
          className="nodrag nowheel"
          onChange={(event) => {
            const raw = event.currentTarget.value;
            onChange(
              field.type === "number" || field.type === "integer"
                ? raw === ""
                  ? undefined
                  : Number(raw)
                : raw,
            );
          }}
        />
      )}
    </Field>
  );
}

const SECRET_STATUS_LABEL: Record<WorkflowNodeSecretState, string> = {
  unknown: "Status unavailable",
  loading: "Checking…",
  unconfigured: "Not configured",
  configured: "Configured",
  stale: "Stale",
  applying: "Applying…",
  removing: "Removing…",
  error: "Action failed",
};

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
  const storedStatus = data.secretStatuses[input.name] ?? { state: "unknown" };
  const ready = data.secretInputReadiness[input.name] ?? false;
  const status =
    !ready && storedStatus.state === "configured"
      ? { state: "stale" as const }
      : storedStatus;
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
      ? "Save the changed secret settings, then apply a new secret."
      : "Save this node before configuring this secret."
    : status.state === "stale"
      ? "Apply a key for the current endpoint."
      : status.state === "error"
        ? (status.message ?? "The secret action could not be completed.")
        : (input.description ??
          "Write-only · the stored value cannot be read back.");

  return (
    <form
      className="nodrag nowheel"
      onSubmit={(event) => {
        event.preventDefault();
        if (!canApply) return;
        void data.onApplyNodeSecret?.(id, input.name, value).then((applied) => {
          if (applied) setValue("");
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
              status.state === "configured" ? "Replace secret" : "Enter secret"
            }
            disabled={!ready || busy}
            className="nodrag nowheel"
            onChange={(event) => setValue(event.currentTarget.value)}
          />
          <Button
            type="submit"
            variant="soft"
            size="sm"
            className="nodrag nowheel"
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
          <Button
            variant="danger"
            size="xs"
            className="nodrag nowheel"
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

export type ConfigBrick =
  | { kind: "field"; field: SchemaField; footprint: FieldFootprint }
  | {
      kind: "secret";
      input: WorkflowNodeSecretInput;
      footprint: FieldFootprint;
    };

/**
 * A lone field whose title the node title already contains ("Text" on a "Text
 * input" node) names the same thing twice. The label stays in the accessibility
 * tree; only its row is reclaimed. Booleans keep theirs — a bare checkbox
 * reads as nothing at all.
 */
export function configFieldLabelIsRedundant(
  nodeTitle: string,
  bricks: readonly ConfigBrick[],
): boolean {
  const only = bricks.length === 1 ? bricks[0] : undefined;
  if (only?.kind !== "field" || only.field.type === "boolean") return false;
  const squash = (value: string) =>
    value.toLowerCase().replace(/[^a-z0-9]/g, "");
  const title = squash(only.field.title);
  return title.length > 0 && squash(nodeTitle).includes(title);
}

export function configBricks(data: WorkflowNodeData): ConfigBrick[] {
  return [
    ...schemaFields(data.spec.config_schema).map((field): ConfigBrick => ({
      kind: "field",
      field,
      footprint: fieldFootprint(field),
    })),
    ...nodeSecretInputs(data.spec).map((input): ConfigBrick => ({
      kind: "secret",
      input,
      footprint: secretFootprint(),
    })),
  ];
}
