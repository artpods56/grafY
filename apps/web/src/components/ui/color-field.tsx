"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";

function joinClassNames(...names: Array<string | undefined>) {
  return names.filter(Boolean).join(" ") || undefined;
}

/** `dense` is the canvas-card step; see `switch.tsx` for why the kit has one. */
export type ColorWellSize = "dense" | "sm" | "md";

export type ColorWellProps = {
  /** `#rrggbb`. The native well takes nothing else. */
  value: string;
  onChange: (value: string) => void;
  /** Names the well. Required because a bare colour square says nothing on its own. */
  label: string;
  disabled?: boolean;
  size?: ColorWellSize;
  /** Fill the row (`true`, a styled layer) or stay a small square (a toolbar). */
  block?: boolean;
  /** Plain class names added after the StyleX ones, e.g. React Flow's "nodrag nopan". */
  className?: string;
  /** Caller overrides made with stylex.create, applied last so they win. */
  xstyle?: stylex.StyleXStyles;
};

const well = stylex.create({
  input: {
    boxSizing: "border-box",
    minWidth: 0,
    margin: 0,
    padding: "2px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurface,
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccentBorder}`,
    },
    outlineOffset: "-2px",
  },
  block: {
    width: "100%",
  },
  square: {
    width: "32px",
    flexShrink: 0,
  },
  dense: {
    height: "25px",
    borderRadius: tokens.radiusSm,
  },
  sm: {
    height: "28px",
  },
  md: {
    height: "32px",
  },
  disabled: {
    borderColor: tokens.colorDivider,
    cursor: "not-allowed",
  },
});

const SIZE_BY_STEP = {
  dense: well.dense,
  sm: well.sm,
  md: well.md,
} as const;

/**
 * The colour square itself: an `<input type="color">` in the kit's frame.
 *
 * Use `ColorField` when the well has a label of its own, which is the case at
 * every reported call site. The platform picker stays, so the person gets the
 * eyedropper and the recent colours their OS already keeps.
 */
export const ColorWell = React.forwardRef<HTMLInputElement, ColorWellProps>(
  function ColorWell(
    {
      value,
      onChange,
      label,
      disabled = false,
      size = "md",
      block = true,
      className,
      xstyle,
    },
    ref,
  ) {
    const styled = stylex.props(
      well.input,
      SIZE_BY_STEP[size],
      block ? well.block : well.square,
      disabled ? well.disabled : null,
      xstyle,
    );
    return (
      <input
        ref={ref}
        type="color"
        value={value}
        disabled={disabled}
        aria-label={label}
        title={label}
        onChange={(event) => onChange(event.currentTarget.value)}
        className={joinClassNames(styled.className, className)}
        style={styled.style}
      />
    );
  },
);

export type ColorFieldProps = Omit<ColorWellProps, "block" | "label"> & {
  /**
   * The visible name, which is also the well's accessible name. A label that is
   * not plain text is a `ColorWell` with the call site's own markup.
   */
  label: string;
  /** Content at the right end of the label row, e.g. the hex the layer holds. */
  aside?: React.ReactNode;
  /** Plain class names added after the StyleX ones. */
  className?: string;
  xstyle?: stylex.StyleXStyles;
};

const field = stylex.create({
  root: {
    display: "grid",
    gap: "3px",
    minWidth: 0,
    margin: 0,
  },
  dense: {
    color: tokens.colorSubtle,
    fontSize: "9px",
  },
  sm: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  md: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  labelRow: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    minWidth: 0,
  },
  label: {
    minWidth: 0,
    fontWeight: 500,
  },
  aside: {
    flexShrink: 0,
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "inherit",
  },
});

const FIELD_BY_SIZE = {
  dense: field.dense,
  sm: field.sm,
  md: field.md,
} as const;

/**
 * A labelled colour: the name above the well, the well filling the row.
 *
 * `VectorLayerStyleBody` had its own `ColorField`, the map inspector had its
 * `ColorControl`, and both drew the same two lines of markup.
 */
export function ColorField({
  label,
  aside,
  size = "md",
  className,
  xstyle,
  ...props
}: ColorFieldProps) {
  const styled = stylex.props(field.root, FIELD_BY_SIZE[size], xstyle);
  return (
    <label
      className={joinClassNames(styled.className, className)}
      style={styled.style}
    >
      <span {...stylex.props(field.labelRow)}>
        <span {...stylex.props(field.label)}>{label}</span>
        {aside != null ? (
          <span {...stylex.props(field.aside)}>{aside}</span>
        ) : null}
      </span>
      <ColorWell {...props} size={size} label={label} />
    </label>
  );
}
