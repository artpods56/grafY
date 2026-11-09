"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Field as BaseField } from "@base-ui/react/field";
import { tokens } from "@/lib/stylex/tokens.stylex";

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

/**
 * `dense` is the canvas-card step. `Field` and its controls bottomed out at 32px,
 * which is right for a form and wrong for a layer inspector whose rows were 25px:
 * the card's own scroll area then holds fewer controls per screenful, and the
 * person scrolls instead of seeing the layer.
 *
 * A `Field` hands its size to the control it is given, so a call site says it once.
 */
export type FieldSize = "dense" | "md";

function joinClassNames(...names: Array<string | undefined>) {
  return names.filter(Boolean).join(" ") || undefined;
}

const field = stylex.create({
  root: {
    display: "grid",
    gap: "5px",
    minWidth: 0,
    margin: 0,
  },
  rootDense: {
    gap: "3px",
  },
  labelRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    minWidth: 0,
  },
  label: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  labelDense: {
    fontSize: "9px",
  },
  aside: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 600,
  },
  description: {
    margin: 0,
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.4,
  },
  descriptionDense: {
    fontSize: "9px",
  },
  error: {
    margin: 0,
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
  errorDense: {
    fontSize: "9px",
  },
  control: {
    width: "100%",
    minWidth: 0,
    height: "32px",
    boxSizing: "border-box",
    margin: 0,
    paddingInline: "10px",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceRaised,
    color: {
      default: tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
    cursor: { default: "text", ":disabled": "not-allowed" },
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
    outline: {
      default: "none",
      ":focus": `2px solid ${tokens.colorAccentBorder}`,
    },
    outlineOffset: "-2px",
    "::placeholder": { color: tokens.colorSubtle },
  },
  /** The canvas-card step: the row a control sits in is 25px and its type is 9px. */
  controlDense: {
    height: "25px",
    paddingInline: "6px",
    borderRadius: tokens.radiusSm,
    fontSize: "9px",
  },
  textarea: {
    height: "auto",
    minHeight: "64px",
    paddingBlock: "8px",
    lineHeight: 1.45,
    resize: "none",
  },
  textareaDense: {
    minHeight: "46px",
    paddingBlock: "5px",
    lineHeight: 1.4,
  },
  mono: {
    fontFamily: MONO,
  },
});

export type FieldProps = {
  /** The visible label; Base UI ties it to the control inside. */
  label: React.ReactNode;
  /** Optional hint under the control; the control is described by it. */
  description?: React.ReactNode;
  /**
   * What went wrong, under the control. Takes the place of `description` while it
   * is set: the control is described by the message and marked invalid, so a form
   * error needs nothing else at the call site — including one the server reported.
   */
  error?: React.ReactNode | null;
  /** Optional content at the right end of the label row, e.g. a status like "Configured". */
  aside?: React.ReactNode;
  /** The control: a <TextInput> or <TextArea> from this file. */
  children: React.ReactNode;
  disabled?: boolean;
  name?: string;
  /**
   * `dense` shrinks the label, the messages, and the control inside this field, so
   * a canvas card keeps the row height it had before the kit. A control given its
   * own `size` keeps it.
   */
  size?: FieldSize;
  /**
   * Plain class names added after the StyleX ones. On a canvas card this is how
   * a field keeps React Flow's `nodrag nopan nowheel`: the root carries them, and
   * React Flow walks up from the event target, so the label row is covered too.
   */
  className?: string;
  /** Caller overrides made with stylex.create, applied last. */
  xstyle?: stylex.StyleXStyles;
};

/**
 * A labelled form row: the label, the control and an optional hint or error, wired
 * together. `TextInput`, `TextArea` and `Select` take part in the wiring, and take
 * this field's `size` unless they were given one of their own.
 */
export function Field({
  label,
  description,
  error,
  aside,
  children,
  disabled,
  name,
  size = "md",
  className,
  xstyle,
}: FieldProps) {
  const dense = size === "dense";
  const styled = stylex.props(
    field.root,
    dense ? field.rootDense : null,
    xstyle,
  );
  // Base UI composes `aria-describedby` from the field's own message parts and
  // ties the label to the control, but it derives `aria-invalid` from browser
  // validity. A rejected name or a server "already exists" is not a validity
  // state, so the invalid flag is the field's to say.
  //
  // The same pass hands the control this field's size, because a row drawn at
  // 9px type with a 32px input in it is neither.
  const control = React.Children.map(children, (child) => {
    if (!React.isValidElement(child)) return child;
    const element = child as React.ReactElement<Record<string, unknown>>;
    const extra: Record<string, unknown> = {};
    if (dense && element.props.size == null) extra.size = size;
    if (error != null) extra["aria-invalid"] = true;
    return Object.keys(extra).length === 0
      ? child
      : React.cloneElement(element, extra);
  });
  return (
    <BaseField.Root
      disabled={disabled}
      name={name}
      className={joinClassNames(styled.className, className)}
      style={styled.style}
    >
      <div {...stylex.props(field.labelRow)}>
        <BaseField.Label
          {...stylex.props(field.label, dense ? field.labelDense : null)}
        >
          {label}
        </BaseField.Label>
        {aside != null ? (
          <span {...stylex.props(field.aside)}>{aside}</span>
        ) : null}
      </div>
      {control}
      {error != null ? (
        <BaseField.Error
          match
          role="alert"
          {...stylex.props(field.error, dense ? field.errorDense : null)}
        >
          {error}
        </BaseField.Error>
      ) : description != null ? (
        <BaseField.Description
          {...stylex.props(
            field.description,
            dense ? field.descriptionDense : null,
          )}
        >
          {description}
        </BaseField.Description>
      ) : null}
    </BaseField.Root>
  );
}

export type TextInputProps = Omit<
  React.ComponentPropsWithoutRef<typeof BaseField.Control>,
  "className" | "style" | "size"
> & {
  /** Monospace text, for endpoints, model names and keys. */
  mono?: boolean;
  /** The canvas-card step. Inside a <Field size="dense"> it comes from the field. */
  size?: FieldSize;
  /** Plain class names added after the StyleX ones, e.g. React Flow's "nodrag". */
  className?: string;
  xstyle?: stylex.StyleXStyles;
};

/** A text input that takes part in the surrounding Field's label and description wiring. */
export const TextInput = React.forwardRef<HTMLInputElement, TextInputProps>(
  function TextInput(
    { mono = false, size = "md", className, xstyle, ...props },
    ref,
  ) {
    const styled = stylex.props(
      field.control,
      size === "dense" ? field.controlDense : null,
      mono ? field.mono : null,
      xstyle,
    );
    return (
      <BaseField.Control
        ref={ref}
        {...props}
        className={joinClassNames(styled.className, className)}
        style={styled.style}
      />
    );
  },
);

export type TextAreaProps = Omit<
  React.ComponentPropsWithoutRef<"textarea">,
  "className" | "style"
> & {
  mono?: boolean;
  /** The canvas-card step. Inside a <Field size="dense"> it comes from the field. */
  size?: FieldSize;
  className?: string;
  xstyle?: stylex.StyleXStyles;
};

/** A multiline text control that keeps the same Field wiring as <TextInput>. */
export const TextArea = React.forwardRef<HTMLTextAreaElement, TextAreaProps>(
  function TextArea(
    { mono = false, rows = 4, size = "md", className, xstyle, ...props },
    ref,
  ) {
    const styled = stylex.props(
      field.control,
      field.textarea,
      size === "dense" ? field.controlDense : null,
      size === "dense" ? field.textareaDense : null,
      mono ? field.mono : null,
      xstyle,
    );
    return (
      <BaseField.Control
        // Field.Control's props are typed for an <input>; they drive the <textarea> rendered below.
        {...(props as unknown as React.ComponentPropsWithoutRef<
          typeof BaseField.Control
        >)}
        ref={ref as unknown as React.Ref<HTMLElement>}
        className={joinClassNames(styled.className, className)}
        style={styled.style}
        render={(controlProps) => (
          <textarea
            {...(controlProps as React.ComponentPropsWithRef<"textarea">)}
            rows={rows}
          />
        )}
      />
    );
  },
);
