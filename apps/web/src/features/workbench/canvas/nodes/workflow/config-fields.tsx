"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Check, LoaderCircle, Plus, Trash2 } from "lucide-react";

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
    resize: "none",
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
  tupleError: {
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
  stringList: {
    display: "grid",
    gap: "5px",
  },
  stringListRow: {
    minWidth: 0,
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 31px",
    alignItems: "center",
    gap: "5px",
  },
  stringListRemove: {
    width: "31px",
    height: "31px",
    display: "grid",
    placeItems: "center",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorDangerHover,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorDanger },
    cursor: "pointer",
    opacity: { ":disabled": 0.4 },
  },
  stringListAdd: {
    minHeight: "29px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "5px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: tokens.colorSurfaceMuted,
      ":hover": tokens.colorHover,
    },
    color: tokens.colorTextEmphasis,
    cursor: "pointer",
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
    opacity: { ":disabled": 0.4 },
  },
  fieldLabel: {
    minWidth: 0,
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    gap: "3px",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
    textTransform: "capitalize",
  },
  fieldLabelText: {
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
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
  input: {
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
  textarea: {
    paddingBlock: "8px",
    lineHeight: 1.45,
    resize: "none",
  },
  codeTextarea: {
    fontFamily:
      "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    fontSize: tokens.fontSizeXs,
    tabSize: 2,
  },
  /**
   * Same silhouette as text inputs: full-width 31px bar, check on the
   * trailing edge. Checked state lives on the well, not the bar.
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
  secretField: { display: "grid", alignContent: "start", gap: "5px" },
  secretHeader: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
  },
  secretStatus: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 600,
  },
  secretStatusConfigured: { color: tokens.colorSuccess },
  secretStatusStale: { color: tokens.colorWarning },
  secretStatusError: { color: tokens.colorDanger },
  secretControl: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    gap: "5px",
  },
  secretInput: { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace" },
  secretButton: {
    minWidth: "54px",
    height: "31px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "5px",
    paddingInline: "9px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: tokens.colorAccentSoft,
      ":hover": tokens.colorHoverStrong,
    },
    color: tokens.colorTextEmphasis,
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 600,
  },
  secretButtonDisabled: {
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorTextDisabled,
    cursor: "not-allowed",
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
  secretRemove: {
    flexShrink: 0,
    padding: 0,
    borderWidth: 0,
    backgroundColor: "transparent",
    color: {
      default: tokens.colorSubtle,
      ":hover": tokens.colorDanger,
    },
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 500,
  },
  secretRemoveDisabled: {
    color: tokens.colorTextDisabled,
    cursor: "not-allowed",
  },
});

/**
 * Descriptions ride the label tooltip instead of taking a line in the brick:
 * they are schema documentation you read once, not state you monitor.
 */
function FieldLabelText({
  title,
  description,
}: {
  title: string;
  description?: string | null;
}) {
  return (
    <span
      title={description ? `${title} — ${description}` : title}
      {...stylex.props(s.fieldLabelText)}
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
          <span {...stylex.props(sharedStyles.required)}>*</span>
        ) : null}
      </legend>
      <div {...stylex.props(s.tupleGrid)}>
        {field.items.map((item, index) => (
          <label key={`${item.title}:${index}`} {...stylex.props(s.tupleItem)}>
            <span title={item.title} {...stylex.props(s.tupleItemLabel)}>
              {item.title}
            </span>
            <input
              type="number"
              aria-label={`${field.title}: ${item.title}`}
              aria-invalid={showError}
              value={draftValues[index] ?? ""}
              min={item.minimum}
              max={item.maximum}
              step={item.type === "integer" ? 1 : "any"}
              {...nodeInteractionProps(stylex.props(s.input))}
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
        <span role="alert" {...stylex.props(s.tupleError)}>
          Enter all {itemCount} values as numbers within the shown ranges.
        </span>
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
          <span {...stylex.props(sharedStyles.required)}>*</span>
        ) : null}
      </legend>
      <div {...stylex.props(s.stringList)}>
        {values.map((item, index) => (
          <div key={index} {...stylex.props(s.stringListRow)}>
            <input
              type="text"
              aria-label={`${field.title} item ${index + 1}`}
              value={item}
              minLength={field.itemMinLength}
              maxLength={field.itemMaxLength}
              {...nodeInteractionProps(stylex.props(s.input))}
              onChange={(event) => {
                const nextValues = [...values];
                nextValues[index] = event.currentTarget.value;
                onChange(nextValues);
              }}
            />
            <button
              type="button"
              aria-label={`Remove ${field.title} item ${index + 1}`}
              title="Remove item"
              disabled={!canRemove}
              {...nodeInteractionProps(stylex.props(s.stringListRemove))}
              onClick={() => {
                onChange(values.filter((_, itemIndex) => itemIndex !== index));
              }}
            >
              <Trash2 size={13} />
            </button>
          </div>
        ))}
        <button
          type="button"
          aria-label={`Add ${field.title} item`}
          disabled={!canAdd}
          {...nodeInteractionProps(stylex.props(s.stringListAdd))}
          onClick={() => onChange([...values, ""])}
        >
          <Plus size={13} />
          Add item
        </button>
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
            <span {...stylex.props(sharedStyles.required)}>*</span>
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

  return (
    <label {...fieldProps}>
      <span {...labelProps}>
        <FieldLabelText title={field.title} description={field.description} />
        {field.required ? (
          <span {...stylex.props(sharedStyles.required)}>*</span>
        ) : null}
      </span>
      {field.enumValues ? (
        <select
          value={
            typeof value === "string" || typeof value === "number" ? value : ""
          }
          {...nodeInteractionProps(stylex.props(s.input))}
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
      ) : field.type === "string" && field.format === "textarea" ? (
        <div
          {...stylex.props(
            s.textareaHost,
            fillHeight ? s.textareaHostFill : null,
          )}
        >
          <textarea
            value={typeof value === "string" ? value : ""}
            minLength={field.minLength}
            maxLength={field.maxLength}
            {...nodeInteractionProps(
              stylex.props(
                s.input,
                s.textarea,
                field.codeLanguage ? s.codeTextarea : null,
                fillHeight ? s.textareaFill : s.textareaDefault,
              ),
            )}
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
        <input
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
          {...nodeInteractionProps(stylex.props(s.input))}
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
    </label>
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
      {...nodeInteractionProps(stylex.props(s.secretField))}
      onSubmit={(event) => {
        event.preventDefault();
        if (!canApply) return;
        void data.onApplyNodeSecret?.(id, input.name, value).then((applied) => {
          if (applied) setValue("");
        });
      }}
    >
      <div {...stylex.props(s.secretHeader)}>
        <span {...stylex.props(s.fieldLabel)}>
          <FieldLabelText title={input.title} />
        </span>
        <span
          role="status"
          {...stylex.props(
            s.secretStatus,
            status.state === "configured" ? s.secretStatusConfigured : null,
            status.state === "stale" ? s.secretStatusStale : null,
            status.state === "error" ? s.secretStatusError : null,
          )}
        >
          {SECRET_STATUS_LABEL[status.state]}
        </span>
      </div>
      <div {...stylex.props(s.secretControl)}>
        <input
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
          {...nodeInteractionProps(stylex.props(s.input, s.secretInput))}
          onChange={(event) => setValue(event.currentTarget.value)}
        />
        <button
          type="submit"
          disabled={!canApply}
          {...nodeInteractionProps(
            stylex.props(
              s.secretButton,
              canApply ? null : s.secretButtonDisabled,
            ),
          )}
        >
          {status.state === "applying" ? (
            <LoaderCircle size={11} {...stylex.props(sharedStyles.spinner)} />
          ) : null}
          Apply
        </button>
      </div>
      <div {...stylex.props(s.secretFooter)}>
        <p {...stylex.props(s.secretHint)}>{hint}</p>
        <button
          type="button"
          disabled={!canRemove}
          {...nodeInteractionProps(
            stylex.props(
              s.secretRemove,
              canRemove ? null : s.secretRemoveDisabled,
            ),
          )}
          onClick={() => {
            if (!canRemove) return;
            void data.onRemoveNodeSecret?.(id, input.name).then((removed) => {
              if (removed) setValue("");
            });
          }}
        >
          Remove
        </button>
      </div>
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
