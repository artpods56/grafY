import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

/**
 * The chrome the side panel's parts share.
 *
 * Designed for the Tier 2 Gray Subsidebar (`colorSubrailBg`), sitting cleanly
 * between the always-dark left rail and the main workflow canvas.
 */
export const panelStyles = stylex.create({
  iconButton: {
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorSubrailHover,
    },
    color: {
      default: tokens.colorMuted,
      ":hover:not(:disabled)": tokens.colorTextEmphasis,
      ":disabled": tokens.colorTextDisabled,
    },
  },
  spinner: {
    animationName: "grafy-spin",
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});
