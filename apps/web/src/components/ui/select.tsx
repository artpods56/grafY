"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Field as BaseField } from "@base-ui/react/field";
import { tokens } from "@/lib/stylex/tokens.stylex";

function joinClassNames(...names: Array<string | undefined>) {
  return names.filter(Boolean).join(" ") || undefined;
}

/**
 * `dense` is the canvas-card step: a layer inspector's row is 25px and its type
 * is 9px, and the desktop steps put fewer controls per screenful inside the
 * card's own scroll area.
 */
export type SelectSize = "dense" | "sm" | "md";

export type SelectProps = Omit<
  React.ComponentPropsWithoutRef<"select">,
  "className" | "style" | "onChange" | "size"
> & {
  onChange?: (event: React.ChangeEvent<HTMLSelectElement>) => void;
  /**
   * Marks the control and its message as failed without a browser validity state:
   * a value the server rejected is not a `required` miss. `Field` sets this when
   * it is given an `error`, so a call site inside a `Field` does not pass it.
   */
  invalid?: boolean;
  /** Monospace text, for schema paths, type names and column ids. */
  mono?: boolean;
  /** Fill the row (`true`, the form case) or take the width of the longest option. */
  block?: boolean;
  size?: SelectSize;
  /** Plain class names added after the StyleX ones, e.g. React Flow's "nodrag nopan". */
  className?: string;
  /** Caller overrides made with stylex.create, applied last so they win. */
  xstyle?: stylex.StyleXStyles;
};

const select = stylex.create({
  base: {
    boxSizing: "border-box",
    minWidth: 0,
    margin: 0,
    paddingInline: "8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceRaised,
    color: {
      default: tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
    fontFamily: "inherit",
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccentBorder}`,
    },
    outlineOffset: "-2px",
    transitionProperty: "background-color, border-color",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  block: {
    width: "100%",
  },
  /** The popup stays the platform's, so the option list is readable at any zoom. */
  inline: {
    width: "auto",
    maxWidth: "100%",
  },
  dense: {
    height: "25px",
    fontSize: "9px",
    paddingInline: "6px",
    borderRadius: tokens.radiusSm,
  },
  sm: {
    height: "28px",
    fontSize: tokens.fontSizeXs,
  },
  md: {
    height: "32px",
    fontSize: tokens.fontSizeSm,
  },
  mono: {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
  },
  invalid: {
    borderColor: tokens.colorDanger,
  },
});

/**
 * A choose-one-from-a-list control that matches `Field`'s other controls.
 *
 * It is a native `<select>` on purpose. Every reported site — Resampling, Value
 * type, Rows per page, the workflow enum brick — is a short list of values the
 * person can already read at a glance, and inside a canvas card a popup the app
 * draws has to be measured against the viewport while the platform's is not. The
 * arrow stays the browser's for the same reason: a kit-drawn arrow would need a
 * wrapper element between `Field` and the control, and `Field` puts its
 * `aria-invalid` on the child it is handed.
 *
 * Renders as `Field`'s control, so `<Field label="Rows per page"><Select …>` gets
 * the label wiring, the description, and the error message for free; standalone
 * it is a plain select and the call site names it.
 */
export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  function Select(
    {
      mono = false,
      block = true,
      size = "md",
      className,
      xstyle,
      invalid,
      "aria-invalid": ariaInvalid,
      ...props
    },
    ref,
  ) {
    const invalidSet =
      invalid === true || ariaInvalid === true || ariaInvalid === "true";
    const styled = stylex.props(
      select.base,
      select[size],
      block ? select.block : select.inline,
      mono ? select.mono : null,
      invalidSet ? select.invalid : null,
      xstyle,
    );
    return (
      <BaseField.Control
        // Field.Control's props are typed for an <input>; they drive the <select>
        // rendered below, the same way <TextArea> drives a <textarea>.
        {...(props as unknown as React.ComponentPropsWithoutRef<
          typeof BaseField.Control
        >)}
        ref={ref as unknown as React.Ref<HTMLElement>}
        aria-invalid={invalidSet ? true : undefined}
        className={joinClassNames(styled.className, className)}
        style={styled.style}
        render={(controlProps) => (
          <select
            {...(controlProps as React.ComponentPropsWithRef<"select">)}
          />
        )}
      />
    );
  },
);
