"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Checkbox as BaseCheckbox } from "@base-ui/react/checkbox";
import { Check } from "lucide-react";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { phoneTouch } from "./touch-target";

function joinClassNames(...names: Array<string | undefined>) {
  return names.filter(Boolean).join(" ") || undefined;
}

/** `dense` is the canvas-card step; see `switch.tsx` for why the kit has one. */
export type CheckboxSize = "dense" | "sm" | "md";

export type CheckboxProps = {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  /** The visible name, set after the box. Clicking it toggles the box. */
  label?: React.ReactNode;
  disabled?: boolean;
  size?: CheckboxSize;
  /** Identifies the control when a form submits it. */
  name?: string;
  /** Names the control when `label` is an icon or lives elsewhere. */
  "aria-label"?: string;
  /** A native tooltip, for a row whose own text is truncated. */
  title?: string;
  /** Pointer intent on the control itself, e.g. a canvas call site stopping propagation. */
  onClick?: React.MouseEventHandler<HTMLElement>;
  /**
   * For a box in a page rather than a canvas card: the row grows to 44px on the
   * shell's phone breakpoint. Never on a control inside a card, which keeps its
   * pixel size at every viewport.
   */
  phoneTouch?: boolean;
  /** Plain class names added after the StyleX ones, e.g. React Flow's "nodrag nopan". */
  className?: string;
  /** Caller overrides made with stylex.create, applied last so they win. */
  xstyle?: stylex.StyleXStyles;
};

const box = stylex.create({
  root: {
    display: "inline-flex",
    alignItems: "center",
    gap: "7px",
    minWidth: 0,
    margin: 0,
    cursor: "pointer",
    color: tokens.colorText,
    userSelect: "none",
  },
  dense: {
    gap: "5px",
    fontSize: "9px",
    lineHeight: 1.3,
  },
  sm: {
    gap: "6px",
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.35,
  },
  md: {
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.4,
  },
  disabled: {
    cursor: "not-allowed",
    color: tokens.colorTextDisabled,
  },
  label: {
    minWidth: 0,
    overflowWrap: "anywhere",
  },
  control: {
    display: "inline-grid",
    placeItems: "center",
    flexShrink: 0,
    boxSizing: "border-box",
    borderWidth: 1,
    borderStyle: "solid",
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurfaceSunken,
    borderColor: tokens.colorBorderStrong,
    color: tokens.colorOnAccent,
    transitionProperty: "background-color, border-color",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  denseControl: {
    width: "12px",
    height: "12px",
  },
  smControl: {
    width: "14px",
    height: "14px",
  },
  mdControl: {
    width: "16px",
    height: "16px",
  },
  checkedControl: {
    backgroundColor: tokens.colorAccent,
    borderColor: tokens.colorAccent,
  },
  disabledControl: {
    backgroundColor: tokens.colorSurfaceMuted,
    borderColor: tokens.colorDivider,
  },
  mark: {
    display: "block",
  },
  denseMark: {
    width: "9px",
    height: "9px",
  },
  smMark: {
    width: "11px",
    height: "11px",
  },
  mdMark: {
    width: "12px",
    height: "12px",
  },
});

const CONTROL_BY_SIZE = {
  dense: box.denseControl,
  sm: box.smControl,
  md: box.mdControl,
} as const;

const MARK_BY_SIZE = {
  dense: box.denseMark,
  sm: box.smMark,
  md: box.mdMark,
} as const;

/**
 * A ticked box for one value inside a form or a list selection — the thing a
 * `Switch` is not, because a checkbox is applied by something else and a switch
 * takes effect on its own.
 *
 * Reported by the map inspector's "enabled" rows, which had a bare
 * `<input type="checkbox">` in a `<label>`: same DOM contract, kit colours.
 */
export function Checkbox({
  checked,
  onCheckedChange,
  label,
  disabled = false,
  size = "md",
  name,
  phoneTouch: phone = false,
  title,
  onClick,
  className,
  xstyle,
  ...props
}: CheckboxProps) {
  // A `role="checkbox"` is not a labelable element either, so the visible name has
  // to be pointed at from the box, not only wrapped around it.
  const id = React.useId();
  const labelId = label == null ? undefined : id;
  const root = stylex.props(
    box.root,
    box[size],
    phone ? phoneTouch.on : null,
    disabled ? box.disabled : null,
    xstyle,
  );
  const control = stylex.props(
    box.control,
    CONTROL_BY_SIZE[size],
    checked && !disabled ? box.checkedControl : null,
    disabled ? box.disabledControl : null,
  );

  return (
    <label
      className={joinClassNames(root.className, className)}
      style={root.style}
    >
      <BaseCheckbox.Root
        title={title}
        onClick={onClick}
        checked={checked}
        // Base UI hands the change details as a second argument; the kit's own
        // contract is the value alone.
        onCheckedChange={(next) => onCheckedChange(next)}
        disabled={disabled}
        name={name}
        aria-label={props["aria-label"]}
        aria-labelledby={labelId}
        className={control.className}
        style={control.style}
      >
        <BaseCheckbox.Indicator {...stylex.props(box.mark, MARK_BY_SIZE[size])}>
          <Check
            size={size === "dense" ? 9 : size === "sm" ? 11 : 12}
            aria-hidden="true"
            strokeWidth={3}
          />
        </BaseCheckbox.Indicator>
      </BaseCheckbox.Root>
      {label != null ? (
        <span {...stylex.props(box.label)} id={labelId}>
          {label}
        </span>
      ) : null}
    </label>
  );
}
