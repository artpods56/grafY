"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Slider as BaseSlider } from "@base-ui/react/slider";
import { tokens } from "@/lib/stylex/tokens.stylex";

function joinClassNames(...names: Array<string | undefined>) {
  return names.filter(Boolean).join(" ") || undefined;
}

/** `dense` is the canvas-card step; see `switch.tsx` for why the kit has one. */
export type SliderSize = "dense" | "md";

export type SliderProps = {
  /** Names the group and the thumb for assistive tech. */
  label: React.ReactNode;
  value: number;
  min: number;
  max: number;
  step: number;
  onValueChange: (value: number) => void;
  /**
   * How the number beside the track is printed. Defaults to two decimals below
   * 1 and whole numbers above it, which is what a style value wants.
   */
  format?: (value: number) => string;
  disabled?: boolean;
  size?: SliderSize;
  /** Plain class names added after the StyleX ones, e.g. React Flow's "nodrag nopan". */
  className?: string;
  /** Caller overrides made with stylex.create, applied last so they win. */
  xstyle?: stylex.StyleXStyles;
};

function formatForStep(step: number) {
  // A step below 1 is a style value (opacity, stroke width) and wants its
  // decimals; a step of 1 or more is a count or a pixel measure.
  const digits = step < 1 ? 2 : 0;
  return (value: number) => value.toFixed(digits);
}

const slider = stylex.create({
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
  md: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  disabled: {
    color: tokens.colorTextDisabled,
  },
  label: {
    minWidth: 0,
    overflowWrap: "anywhere",
  },
  row: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 34px",
    alignItems: "center",
    gap: "5px",
  },
  control: {
    width: "100%",
    minWidth: 0,
  },
  track: {
    position: "relative",
    width: "100%",
    boxSizing: "border-box",
    borderRadius: "9999px",
    backgroundColor: tokens.colorDivider,
    cursor: { default: "pointer", ":disabled": "not-allowed" },
  },
  denseTrack: {
    height: "3px",
  },
  mdTrack: {
    height: "4px",
  },
  filled: {
    borderRadius: "9999px",
    backgroundColor: tokens.colorAccent,
  },
  thumb: {
    boxSizing: "border-box",
    borderWidth: 1,
    borderStyle: "solid",
    borderRadius: "9999px",
    backgroundColor: tokens.colorChrome,
    borderColor: tokens.colorBorderStrong,
    boxShadow: tokens.shadowNode,
    outline: {
      default: "none",
      // Base UI puts the keyboard focus on the range input inside the thumb, so
      // the ring has to be drawn by the element holding it.
      ":focus-within": `2px solid ${tokens.colorAccentBorder}`,
    },
    outlineOffset: "1px",
    cursor: "grab",
  },
  denseThumb: {
    width: "10px",
    height: "10px",
  },
  mdThumb: {
    width: "14px",
    height: "14px",
  },
  value: {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    color: tokens.colorText,
    textAlign: "right",
    fontVariantNumeric: "tabular-nums",
  },
  denseValue: {
    fontSize: "9px",
  },
  mdValue: {
    fontSize: tokens.fontSizeXs,
  },
});

const TRACK_BY_SIZE = {
  dense: slider.denseTrack,
  md: slider.mdTrack,
} as const;

const THUMB_BY_SIZE = {
  dense: slider.denseThumb,
  md: slider.mdThumb,
} as const;

const VALUE_BY_SIZE = {
  dense: slider.denseValue,
  md: slider.mdValue,
} as const;

/**
 * A draggable number in a known range, with its value printed beside the track.
 *
 * The map inspector had a hand-built `RangeControl` around a bare
 * `<input type="range">`; this is that control with the kit's colours, keyboard
 * behaviour from Base UI, and the same readout the native element had.
 */
export function Slider({
  label,
  value,
  min,
  max,
  step,
  onValueChange,
  format = formatForStep(step),
  disabled = false,
  size = "md",
  className,
  xstyle,
}: SliderProps) {
  const root = stylex.props(
    slider.root,
    slider[size],
    disabled ? slider.disabled : null,
    xstyle,
  );

  return (
    <BaseSlider.Root
      value={value}
      min={min}
      max={max}
      step={step}
      disabled={disabled}
      onValueChange={(next) =>
        onValueChange(Array.isArray(next) ? next[0] : next)
      }
      className={joinClassNames(root.className, className)}
      style={root.style}
    >
      <BaseSlider.Label {...stylex.props(slider.label)}>
        {label}
      </BaseSlider.Label>
      <div {...stylex.props(slider.row)}>
        <BaseSlider.Control {...stylex.props(slider.control)}>
          <BaseSlider.Track
            {...stylex.props(slider.track, TRACK_BY_SIZE[size])}
          >
            <BaseSlider.Indicator {...stylex.props(slider.filled)} />
            <BaseSlider.Thumb
              {...stylex.props(slider.thumb, THUMB_BY_SIZE[size])}
            />
          </BaseSlider.Track>
        </BaseSlider.Control>
        <BaseSlider.Value {...stylex.props(slider.value, VALUE_BY_SIZE[size])}>
          {(_formatted, values) => format(values[0] ?? value)}
        </BaseSlider.Value>
      </div>
    </BaseSlider.Root>
  );
}
