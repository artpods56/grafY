import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

/**
 * The chrome the side panel's parts share.
 *
 * The numbers are the Workspace rail's on purpose: 8px row padding, a 6px
 * radius, 12–13px labels, `colorSurfaceSunken` hover, and no shadow. The rail
 * and the panel are one sidebar with two panes, and the only way they read that
 * way is by agreeing about every one of these. Each part keeps the rest of its
 * styles beside its markup.
 */
export const panelStyles = stylex.create({
  // The rail's colours on the shared IconButton: pass it as `xstyle`.
  iconButton: {
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorSurfaceSunken,
    },
    color: {
      default: tokens.colorMuted,
      ":hover:not(:disabled)": tokens.colorText,
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
