import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

export const workbenchStyles = stylex.create({
  /*
   * Sits beside the two docked sidebar panes — the workspace rail and the workbench
   * side panel — and gives up exactly their width, so the canvas is never covered.
   * Floating chrome anchors to this box.
   */
  shell: {
    position: "relative",
    marginInlineStart:
      "calc(var(--grafy-rail-width, 0px) + var(--grafy-side-panel-width, 0px))",
    width:
      "calc(100% - var(--grafy-rail-width, 0px) - var(--grafy-side-panel-width, 0px))",
    // The canvas edge moves with the side panel's edge, on the same clock.
    transitionProperty: "margin-inline-start, width",
    transitionDuration: "var(--grafy-side-panel-duration, 0ms)",
    transitionTimingFunction: "var(--grafy-side-panel-ease, ease)",
    minWidth: 0,
    height: "100svh",
    overflow: "hidden",
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
  },
  canvas: { position: "absolute", inset: 0 },
  /* Canvas tools dock over the canvas; the left edge belongs to app navigation. */
  toolDock: {
    position: "absolute",
    zIndex: 20,
    bottom: {
      default: "18px",
      "@media (max-width: 720px)": "max(12px, env(safe-area-inset-bottom))",
    },
    left: {
      default: "50%",
      "@media (max-width: 720px)":
        "calc(12px + env(safe-area-inset-left, 0px))",
    },
    right: {
      default: "auto",
      "@media (max-width: 720px)":
        "calc(12px + env(safe-area-inset-right, 0px))",
    },
    display: "flex",
    alignItems: "center",
    gap: "2px",
    padding: "6px",
    overflowX: {
      default: "visible",
      "@media (max-width: 720px)": "auto",
    },
    overscrollBehaviorX: "contain",
    scrollbarWidth: "none",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "12px",
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNode,
    transform: {
      default: "translateX(-50%)",
      "@media (max-width: 720px)": "none",
    },
  },
  railMenuButton: {
    width: "100%",
    justifyContent: "flex-start",
    gap: "8px",
    paddingInline: "9px",
    fontSize: tokens.fontSizeSm,
    fontWeight: 650,
    textAlign: "left",
  },
  /* Kept in the DOM so each icon button still has an accessible name. */
  railDivider: {
    width: "1px",
    height: {
      default: "20px",
      "@media (max-width: 720px)": "28px",
    },
    flexShrink: 0,
    marginInline: {
      default: "4px",
      "@media (max-width: 720px)": "2px",
    },
    backgroundColor: tokens.colorDivider,
  },
  shapesMenuWrap: {
    position: "relative",
    display: "flex",
  },
  shapesMenu: {
    position: {
      default: "absolute",
      "@media (max-width: 720px)": "fixed",
    },
    left: {
      default: 0,
      "@media (max-width: 720px)":
        "calc(var(--grafy-rail-width, 0px) + 12px + env(safe-area-inset-left, 0px))",
    },
    bottom: {
      default: "calc(100% + 8px)",
      "@media (max-width: 720px)": "calc(80px + env(safe-area-inset-bottom))",
    },
    zIndex: 45,
    display: "grid",
    gap: "3px",
    minWidth: "132px",
    padding: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "12px",
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNode,
  },
  selectionToolbar: {
    zIndex: 25,
    minHeight: "42px",
    maxWidth: {
      default: "none",
      "@media (max-width: 720px)":
        "calc(100vw - 24px - env(safe-area-inset-left, 0px) - env(safe-area-inset-right, 0px))",
    },
    display: "flex",
    alignItems: "center",
    gap: "3px",
    padding: "5px",
    overflowX: {
      default: "visible",
      "@media (max-width: 720px)": "auto",
    },
    overscrollBehaviorX: "contain",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "12px",
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNodeRaised,
    pointerEvents: "auto",
  },
  selectionLabel: {
    paddingInline: "7px 9px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
    whiteSpace: "nowrap",
  },
  selectionDivider: {
    width: "1px",
    height: "24px",
    marginInline: "2px",
    backgroundColor: tokens.colorDivider,
  },
  visuallyHidden: {
    position: "absolute",
    width: "1px",
    height: "1px",
    padding: 0,
    margin: "-1px",
    overflow: "hidden",
    borderWidth: 0,
    clip: "rect(0, 0, 0, 0)",
    whiteSpace: "nowrap",
  },
  spinner: {
    animationName: "grafy-spin",
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});
