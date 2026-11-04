"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { s } from "./styles";

/**
 * The controls the shared kit cannot draw: a colour well, a slider with its
 * value, and a checkbox. Labelled text and number fields are the kit's
 * `<Field>` + `<TextInput>` at their call sites, so they are not repeated here.
 */

/**
 * An `<input type="number">` does not hold itself inside `min`/`max`, and a map
 * style value must stay in the range the renderer accepts. `<Field>` +
 * `<TextInput>` draws the control; this keeps only that clamp.
 */
export function clampedNumberChange(
  min: number,
  max: number,
  onChange: (value: number) => void,
) {
  return (event: React.ChangeEvent<HTMLInputElement>) => {
    const next = Number(event.currentTarget.value);
    if (Number.isFinite(next)) onChange(Math.max(min, Math.min(max, next)));
  };
}

export function RangeControl({
  label,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
}) {
  return (
    <label {...stylex.props(s.control, s.controlWide)}>
      <span>{label}</span>
      <span {...stylex.props(s.rangeRow)}>
        <input
          type="range"
          value={value}
          min={min}
          max={max}
          step={step}
          {...stylex.props(s.range)}
          onChange={(event) => onChange(Number(event.currentTarget.value))}
        />
        <output {...stylex.props(s.rangeValue)}>
          {value.toFixed(step < 1 ? 2 : 0)}
        </output>
      </span>
    </label>
  );
}

export function ColorControl({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label {...stylex.props(s.control)}>
      <span>{label}</span>
      <input
        type="color"
        value={value}
        {...stylex.props(s.controlInput, s.colorInput)}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
    </label>
  );
}

export function EnabledControl({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label {...stylex.props(s.toggle)}>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.currentTarget.checked)}
      />
      {label}
    </label>
  );
}
