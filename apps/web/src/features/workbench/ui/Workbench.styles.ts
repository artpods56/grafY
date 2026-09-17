import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

/**
 * Width of the docked Runs drawer. The shell publishes it as
 * `--grafy-generated-drawer-width`; the canvas, the chrome anchored to the
 * canvas, and the drawer itself read it back, so one place decides how much
 * room the drawer takes. It stays local to this module because a named import
 * of a plain value from a styles module reads to StyleX as a theme variable.
 */
const GENERATED_DRAWER_WIDTH = "320px";

export const workbenchStyles = stylex.create({
  /* Sits beside the docked workspace rail; floating chrome anchors to this box. */
  shell: {
    position: "relative",
    marginInlineStart: "var(--grafy-rail-width, 0px)",
    width: "calc(100% - var(--grafy-rail-width, 0px))",
    minWidth: 0,
    height: "100svh",
    overflow: "hidden",
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
  },
  shellWithGeneratedDrawer: {
    "--grafy-generated-drawer-width": GENERATED_DRAWER_WIDTH,
  },
  /* The canvas keeps its own box; the docked drawer takes width off its right. */
  canvas: {
    position: "absolute",
    top: 0,
    bottom: 0,
    left: 0,
    right: {
      default: "var(--grafy-generated-drawer-width, 0px)",
      "@media (max-width: 720px)": 0,
    },
  },
  toolButton: {
    height: {
      default: "31px",
      "@media (max-width: 720px)": "44px",
    },
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    paddingInline: "9px",
    borderWidth: 0,
    borderRadius: "5px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover, ":disabled": "transparent" },
    color: { default: tokens.colorMuted, ":disabled": tokens.colorTextDisabled },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    fontSize: tokens.fontSizeSm,
  },
  primaryButton: {
    backgroundColor: {
      default: tokens.colorAccent,
      ":hover": tokens.colorAccentHover,
      ":disabled": tokens.colorAccentDisabled,
    },
    color: { default: tokens.colorOnAccent, ":disabled": tokens.colorTextDisabled },
    fontWeight: 700,
  },
  /* Canvas tools dock over the canvas; the left edge belongs to app navigation. */
  toolDock: {
    position: "absolute",
    zIndex: 20,
    bottom: {
      default: "18px",
      "@media (max-width: 720px)": "max(12px, env(safe-area-inset-bottom))",
    },
    left: {
      default: "calc(50% - (var(--grafy-generated-drawer-width, 0px) / 2))",
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
  railButton: {
    position: "relative",
    flexShrink: 0,
    width: {
      default: "34px",
      "@media (max-width: 720px)": "44px",
    },
    height: {
      default: "34px",
      "@media (max-width: 720px)": "44px",
    },
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    paddingInline: 0,
    borderWidth: 0,
    borderRadius: "6px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
      ":disabled": "transparent",
    },
    color: {
      default: tokens.colorMuted,
      ":hover": tokens.colorTextEmphasis,
      ":disabled": tokens.colorTextDisabled,
    },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    transitionDuration: "120ms",
    transitionProperty: "background-color, color",
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
  railPrimary: {
    backgroundColor: {
      default: tokens.colorAccentSoft,
      ":hover": tokens.colorAccentSoft,
    },
    color: { default: tokens.colorAccent, ":hover": tokens.colorAccent },
  },
  railDanger: {
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorDangerHover,
      ":disabled": "transparent",
    },
    color: {
      default: tokens.colorMuted,
      ":hover": tokens.colorDanger,
      ":disabled": tokens.colorTextDisabled,
    },
  },
  /* Kept in the DOM so each icon button still has an accessible name. */
  railLabel: {
    position: "absolute",
    width: "1px",
    height: "1px",
    margin: "-1px",
    padding: 0,
    overflow: "hidden",
    clipPath: "inset(50%)",
    whiteSpace: "nowrap",
  },
  railMenuLabel: {
    position: "static",
    width: "auto",
    height: "auto",
    margin: 0,
    overflow: "visible",
    clipPath: "none",
  },
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
