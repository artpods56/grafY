import * as stylex from "@stylexjs/stylex";

/**
 * The phone touch target this app's own CSS has promised since before the shared
 * kit existed: a control that lives in a page or a panel grows to 44px under the
 * shell's 620px breakpoint, which `globals.css` repeats for the rail, the search
 * fields, the selects and the member rows.
 *
 * The kit's own sizes stay as designed, and only `Button lg` grows: a control
 * that has to be reachable with a thumb has to be bigger than a pixel grid.
 * Where a surface carried the rule itself and then moved onto the kit, pass one
 * of these as `xstyle` instead of copying the media query. They set `min` sizes
 * with `unset` below the breakpoint, so the control keeps its own size on a
 * desktop and reaches 44px on a phone.
 *
 * Deliberately not added to controls inside canvas cards: a card keeps its pixel
 * size at any zoom and at any viewport. Surfaces that already carried the phone
 * rule before the kit existed keep it through this export, unchanged.
 *
 * ## Three breakpoints ask for 44px, and this covers one of them
 *
 * The tree has three families, and they are not the same question:
 *
 * - `max-width: 620px` — the shell: rail, search fields, selects, member rows.
 *   This export covers this family, and only this family.
 * - `max-width: 720px` — the workbench chrome: activity bar, rail button, drawer
 *   header. Collapsing it to 620 would leave a control in a 620-720px window with
 *   no 44px floor at all, so the kit does not do it silently.
 * - `pointer: coarse` — the node inspector and the node result list. Collapsing it
 *   to a width would take the target away from a tablet at 1024px, which is the
 *   opposite of the rule.
 *
 * Which of the three the app promises is a product decision, not a mechanical one
 * (issue #211). Until it is taken, a surface whose rule is not the 620px family keeps
 * its own media query and stays out of here; `phoneTouch.on` is not the answer to
 * "make this control bigger on a small window".
 *
 * ## One property, so one owner
 *
 * StyleX keys a rule by its CSS property and keeps only the last one that sets it,
 * so composing this with a recipe that sets `minHeight` / `minWidth` silently drops
 * that recipe's floor — the control falls to its content height on a desktop and
 * nobody sees it in a test. Express the control's own desktop size as `height` /
 * `width`, which is a different key: the kit's `Button` and `IconButton` sizes
 * already do, so `xstyle={phoneTouch.on}` composes cleanly with any of them.
 *
 * Where a control genuinely needs a growing floor — a row whose label can wrap —
 * do not compose. Keep that control's own media rule and leave it out of here.
 */
export const phoneTouch = stylex.create({
  /** For a control that only has to get taller: a `Button`, a chip, a row. */
  on: {
    minHeight: { default: "unset", "@media (max-width: 620px)": "44px" },
  },
  /** For a square control that has to grow on both axes: an `IconButton`. */
  square: {
    minWidth: { default: "unset", "@media (max-width: 620px)": "44px" },
    minHeight: { default: "unset", "@media (max-width: 620px)": "44px" },
  },
});
