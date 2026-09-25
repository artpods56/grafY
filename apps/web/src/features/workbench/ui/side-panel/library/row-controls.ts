import * as React from "react";

/**
 * Whether a click belongs to a control inside the row rather than to the row.
 * The row action menu is rendered inside its row, so a click on the ⋯ or on one
 * of its items would otherwise fold the folder or select the artifact too.
 */
export const ROW_CONTROL_SELECTOR =
  'button, [role="button"], [role="menu"], [role="menuitem"]';

export function isRowAction(event: React.MouseEvent): boolean {
  const target = event.target;
  return (
    target instanceof Element && target.closest(ROW_CONTROL_SELECTOR) !== null
  );
}
