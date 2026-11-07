"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { RadioGroup } from "@base-ui/react/radio-group";
import { Radio } from "@base-ui/react/radio";
import { tokens } from "@/lib/stylex/tokens.stylex";

function joinClassNames(...names: Array<string | undefined>) {
  return names.filter(Boolean).join(" ") || undefined;
}

export type SegmentedOption<Value extends string> = {
  value: Value;
  label: React.ReactNode;
  disabled?: boolean;
  /**
   * A colour chip before the label: an annotation's colour, a layer's fill.
   * No kit part took a per-option colour, so an annotation picker had to paint
   * its own chip inside the label.
   */
  swatch?: string;
  /**
   * A colour the person chose, applied to the segment itself. StyleX cannot carry
   * a value that only exists at runtime, so this is the one place a segment takes
   * an inline style, and it is merged last.
   */
  style?: React.CSSProperties;
};

export type SegmentedControlProps<Value extends string> = {
  /** Names the group for assistive tech, e.g. "Model". */
  "aria-label": string;
  value: Value;
  onValueChange: (value: Value) => void;
  options: readonly SegmentedOption<Value>[];
  size?: "sm" | "md";
  disabled?: boolean;
  /** Plain class names added after the StyleX ones, e.g. React Flow's "nodrag". */
  className?: string;
  /** Caller overrides made with stylex.create, applied last. */
  xstyle?: stylex.StyleXStyles;
};

const segmented = stylex.create({
  root: {
    display: "grid",
    gridAutoFlow: "column",
    gridAutoColumns: "minmax(0, 1fr)",
    gap: "2px",
    padding: "2px",
    position: "relative",
    boxSizing: "border-box",
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorSurfaceRaised,
  },
  segment: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    // A label may be an icon and a word; they space themselves without a wrapper.
    gap: "6px",
    minWidth: 0,
    boxSizing: "border-box",
    paddingInline: "10px",
    borderRadius: tokens.radiusMd,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    whiteSpace: "nowrap",
    userSelect: "none",
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccentBorder}`,
    },
    outlineOffset: "-2px",
    transitionProperty: "background-color, color, box-shadow",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  sm: {
    height: "24px",
  },
  md: {
    height: "28px",
  },
  enabled: {
    cursor: "pointer",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
    },
    color: {
      default: tokens.colorMuted,
      ":hover": tokens.colorText,
    },
  },
  disabled: {
    cursor: "not-allowed",
    backgroundColor: "transparent",
    color: tokens.colorTextDisabled,
  },
  on: {
    backgroundColor: {
      default: tokens.colorChrome,
      ":hover": tokens.colorChrome,
    },
    boxShadow: tokens.shadowNode,
    color: {
      default: tokens.colorTextEmphasis,
      ":hover": tokens.colorTextEmphasis,
    },
  },
  swatch: {
    display: "block",
    width: "8px",
    height: "8px",
    flexShrink: 0,
    borderRadius: "2px",
    // A colour the person picked can be anything, so it keeps a hairline to stay
    // visible against a surface of the same colour.
    boxShadow: `inset 0 0 0 1px ${tokens.colorBorder}`,
  },
});

/** A one-of-several choice drawn as joined segments, with radio semantics and arrow-key movement from Base UI. */
export function SegmentedControl<Value extends string>({
  "aria-label": ariaLabel,
  value,
  onValueChange,
  options,
  size = "md",
  disabled = false,
  className,
  xstyle,
}: SegmentedControlProps<Value>) {
  const styled = stylex.props(segmented.root, xstyle);
  return (
    <RadioGroup
      aria-label={ariaLabel}
      value={value}
      onValueChange={(next) => onValueChange(next as Value)}
      disabled={disabled}
      className={joinClassNames(styled.className, className)}
      style={styled.style}
    >
      {options.map((option) => {
        const off = disabled || option.disabled === true;
        const segment = stylex.props(
          segmented.segment,
          segmented[size],
          off ? segmented.disabled : segmented.enabled,
          option.value === value ? segmented.on : null,
        );
        return (
          <Radio.Root
            key={option.value}
            value={option.value}
            disabled={option.disabled}
            className={segment.className}
            style={{ ...segment.style, ...option.style }}
          >
            {option.swatch != null ? (
              <span
                aria-hidden="true"
                {...stylex.props(segmented.swatch)}
                style={{ backgroundColor: option.swatch }}
              />
            ) : null}
            {option.label}
          </Radio.Root>
        );
      })}
    </RadioGroup>
  );
}
