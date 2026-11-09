import type * as React from "react";

/**
 * The one behaviour an `<input type="number">` does not give you for free.
 *
 * The controls themselves — slider, colour well, switch, select, labelled
 * fields — are the shared kit's (`@/components/ui`). This file keeps only the
 * clamp, which is a value rule, not chrome.
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
