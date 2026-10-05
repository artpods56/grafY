"use client";

import * as stylex from "@stylexjs/stylex";

import { s } from "./styles";

export function NumberControl({
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
    <label {...stylex.props(s.control)}>
      <span>{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        step={step}
        {...stylex.props(s.controlInput)}
        onChange={(event) => {
          const next = Number(event.currentTarget.value);
          if (Number.isFinite(next))
            onChange(Math.max(min, Math.min(max, next)));
        }}
      />
    </label>
  );
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
