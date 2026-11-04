"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Field as BaseField } from "@base-ui/react/field";
import { tokens } from "@/lib/stylex/tokens.stylex";

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

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
  error: {
    margin: 0,
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
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
  textarea: {
    height: "auto",
    minHeight: "64px",
    paddingBlock: "8px",
    lineHeight: 1.45,
    resize: "none",
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
   * Plain class names added after the StyleX ones. On a canvas card this is how
   * a field keeps React Flow's `nodrag nopan nowheel`: the root carries them, and
   * React Flow walks up from the event target, so the label row is covered too.
   */
  className?: string;
  /** Caller overrides made with stylex.create, applied last. */
  xstyle?: stylex.StyleXStyles;
};

/** A labelled form row: the label, the control and an optional hint or error, wired together. */
export function Field({
  label,
  description,
  error,
  aside,
  children,
  disabled,
  name,
  className,
  xstyle,
}: FieldProps) {
  const styled = stylex.props(field.root, xstyle);
  // Base UI composes `aria-describedby` from the field's own message parts and
  // ties the label to the control, but it derives `aria-invalid` from browser
  // validity. A rejected name or a server "already exists" is not a validity
  // state, so the invalid flag is the field's to say.
  const control =
    error == null
      ? children
      : React.Children.map(children, (child) =>
          React.isValidElement(child)
            ? React.cloneElement(
                child as React.ReactElement<Record<string, unknown>>,
                { "aria-invalid": true },
              )
            : child,
        );
  return (
    <BaseField.Root
      disabled={disabled}
      name={name}
      className={joinClassNames(styled.className, className)}
      style={styled.style}
    >
      <div {...stylex.props(field.labelRow)}>
        <BaseField.Label {...stylex.props(field.label)}>
          {label}
        </BaseField.Label>
        {aside != null ? (
          <span {...stylex.props(field.aside)}>{aside}</span>
        ) : null}
      </div>
      {control}
      {error != null ? (
        <BaseField.Error match role="alert" {...stylex.props(field.error)}>
          {error}
        </BaseField.Error>
      ) : description != null ? (
        <BaseField.Description {...stylex.props(field.description)}>
          {description}
        </BaseField.Description>
      ) : null}
    </BaseField.Root>
  );
}

export type TextInputProps = Omit<
  React.ComponentPropsWithoutRef<typeof BaseField.Control>,
  "className" | "style"
> & {
  /** Monospace text, for endpoints, model names and keys. */
  mono?: boolean;
  /** Plain class names added after the StyleX ones, e.g. React Flow's "nodrag". */
  className?: string;
  xstyle?: stylex.StyleXStyles;
};

/** A text input that takes part in the surrounding Field's label and description wiring. */
export const TextInput = React.forwardRef<HTMLInputElement, TextInputProps>(
  function TextInput({ mono = false, className, xstyle, ...props }, ref) {
    const styled = stylex.props(
      field.control,
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
  className?: string;
  xstyle?: stylex.StyleXStyles;
};

/** A multiline text control that keeps the same Field wiring as <TextInput>. */
export const TextArea = React.forwardRef<HTMLTextAreaElement, TextAreaProps>(
  function TextArea(
    { mono = false, rows = 4, className, xstyle, ...props },
    ref,
  ) {
    const styled = stylex.props(
      field.control,
      field.textarea,
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
