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
  iconButton: {
    width: "26px",
    height: "26px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    borderWidth: 0,
    borderStyle: "none",
    borderRadius: "6px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorSurfaceSunken,
      ":disabled": "transparent",
    },
    color: {
      default: tokens.colorMuted,
      ":hover": tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
  },
  spinner: {
    animationName: "grafy-spin",
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});
