import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

/**
 * Simple, calm, full-width Projects browser styles on the Tier 3 surface.
 *
 * Content sits beside the primary dark rail using `--grafy-rail-width` and
 * `--grafy-rail-transition` from `globals.css`.
 */
export const browserStyles = stylex.create({
  partialNotice: {
    margin: "12px 0 0",
  },

  root: {
    height: {
      default: "100svh",
      "@media (max-width: 620px)":
        "calc(100svh - var(--grafy-mobile-header-height) - env(safe-area-inset-top))",
    },
    marginTop: {
      default: "0",
      "@media (max-width: 620px)":
        "calc(var(--grafy-mobile-header-height) + env(safe-area-inset-top))",
    },
    overflow: "auto",
    display: "flex",
    flexDirection: "column",
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
    paddingLeft: {
      default: "var(--grafy-rail-width, 220px)",
      "@media (max-width: 860px)": "var(--grafy-rail-width, 64px)",
      "@media (max-width: 620px)": "0",
    },
    transitionProperty: "padding-left",
    transitionDuration: "var(--grafy-rail-transition, 180ms)",
    transitionTimingFunction: "ease",
  },

  topBar: {
    position: {
      default: "sticky",
      "@media (max-width: 620px)": "static",
    },
    top: 0,
    zIndex: 10,
    flexShrink: 0,
    backgroundColor: tokens.colorSurface,
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
    padding: {
      default: "10px 32px",
      "@media (max-width: 860px)": "10px 20px",
      "@media (max-width: 620px)": "12px 16px",
    },
  },
  topBarInner: {
    width: "100%",
    maxWidth: "1120px",
    minHeight: "36px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    flexWrap: "wrap",
    gap: "12px 20px",
  },
  topBarTitleGroup: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    minWidth: 0,
  },
  pageTitle: {
    margin: 0,
    color: tokens.colorTextEmphasis,
    fontSize: "16px",
    fontWeight: 600,
    letterSpacing: "-0.01em",
    lineHeight: 1.3,
  },
  workspaceBadge: {
    display: "inline-flex",
    alignItems: "center",
    height: "22px",
    paddingInline: "9px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
    whiteSpace: "nowrap",
    overflow: "hidden",
    textOverflow: "ellipsis",
    maxWidth: "220px",
  },
  topBarActions: {
    display: "flex",
    alignItems: "center",
    gap: "10px",
    flexWrap: "wrap",
    width: {
      default: "auto",
      "@media (max-width: 620px)": "100%",
    },
  },
  search: {
    height: { default: "32px", "@media (max-width: 620px)": "44px" },
    flex: {
      default: "0 1 250px",
      "@media (max-width: 620px)": "1 1 100%",
    },
    minWidth: { default: "210px", "@media (max-width: 620px)": "0" },
    display: "flex",
    alignItems: "center",
    gap: "8px",
    paddingInline: "10px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorBorder,
      ":focus-within": tokens.colorAccentBorder,
    },
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorBg,
    color: tokens.colorSubtle,
    transitionProperty: "border-color, background-color",
    transitionDuration: "120ms",
    transitionTimingFunction: "ease",
  },
  searchInput: {
    width: "100%",
    minWidth: 0,
    borderWidth: 0,
    borderStyle: "none",
    outline: "none",
    backgroundColor: "transparent",
    color: tokens.colorText,
    font: "inherit",
    fontSize: tokens.fontSizeMd,
    "::placeholder": {
      color: tokens.colorSubtle,
    },
  },
  headerAction: {
    width: { default: "auto", "@media (max-width: 620px)": "100%" },
  },

  main: {
    width: "100%",
    maxWidth: "1120px",
    flex: "1 0 auto",
    display: "grid",
    alignContent: "start",
    gap: "24px",
    padding: {
      default: "24px 32px 56px",
      "@media (max-width: 860px)": "20px 20px 44px",
      "@media (max-width: 620px)":
        "16px calc(16px + env(safe-area-inset-right)) calc(36px + env(safe-area-inset-bottom)) calc(16px + env(safe-area-inset-left))",
    },
  },

  recipes: {
    display: "grid",
    gap: "10px",
  },
  recipeHeading: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
    letterSpacing: "0.01em",
  },
  recipeRow: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))",
    gap: "12px",
  },
  recipe: {
    display: "grid",
    gridTemplateColumns: "32px minmax(0, 1fr)",
    alignItems: "start",
    gap: "12px",
    padding: "14px 16px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorBorder,
      ":hover:not(:disabled)": tokens.colorBorderStrong,
    },
    borderRadius: tokens.radiusLg,
    backgroundColor: {
      default: tokens.colorSurface,
      ":hover:not(:disabled)": tokens.colorSurfaceRaised,
    },
    color: tokens.colorText,
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
    textAlign: "start",
    cursor: {
      default: "pointer",
      ":disabled": "default",
    },
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccentBorder}`,
    },
    outlineOffset: "-2px",
    transitionProperty: "background-color, border-color",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  recipeIcon: {
    width: "32px",
    height: "32px",
    display: "grid",
    placeItems: "center",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
  },
  recipeBody: {
    display: "grid",
    gap: "3px",
    minWidth: 0,
  },
  recipeTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 600,
    lineHeight: 1.35,
  },
  recipePath: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },

  card: {
    backgroundColor: tokens.colorSurface,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    overflow: "hidden",
  },

  viewBar: {
    minHeight: "48px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "16px",
    padding: "10px 16px",
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    backgroundColor: tokens.colorSurface,
  },
  count: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
    fontVariantNumeric: "tabular-nums",
  },

  loading: {
    minHeight: "220px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "12px",
    padding: "32px 20px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeMd,
  },

  state: {
    minHeight: { default: "200px", "@media (max-width: 620px)": "172px" },
    display: "grid",
    gridTemplateColumns: {
      default: "32px minmax(0, 1fr) auto",
      "@media (max-width: 620px)": "32px minmax(0, 1fr)",
    },
    alignContent: "center",
    alignItems: "start",
    gap: "6px 14px",
    padding: { default: "36px 24px", "@media (max-width: 620px)": "28px 16px" },
    color: tokens.colorMuted,
  },
  stateEmpty: {},
  stateIcon: {
    gridRow: "1 / 3",
    width: "32px",
    height: "32px",
    display: "grid",
    placeItems: "center",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
  },
  stateTitle: {
    margin: 0,
    color: tokens.colorTextEmphasis,
    fontSize: "14px",
    fontWeight: 600,
  },
  stateBody: {
    marginTop: "3px",
    fontSize: tokens.fontSizeMd,
    lineHeight: 1.5,
  },
  stateAction: {
    alignSelf: "center",
    gridColumn: { default: "3", "@media (max-width: 620px)": "2" },
    gridRow: { default: "1 / 3", "@media (max-width: 620px)": "auto" },
    justifySelf: { default: "auto", "@media (max-width: 620px)": "start" },
    marginTop: { default: "0", "@media (max-width: 620px)": "8px" },
  },

  list: {
    display: "grid",
    listStyle: "none",
    margin: 0,
    padding: 0,
  },
  listItem: {
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: {
      default: tokens.colorDivider,
      ":first-child": "transparent",
    },
  },
  row: {
    display: "grid",
    gridTemplateColumns: {
      default: "30px minmax(180px, 1fr) auto 92px 16px",
      "@media (max-width: 860px)": "30px minmax(0, 1fr) auto 16px",
    },
    alignItems: "center",
    gap: { default: "12px", "@media (max-width: 860px)": "2px 10px" },
    minHeight: {
      default: "56px",
      "@media (max-width: 620px)": "62px",
    },
    padding: { default: "10px 16px", "@media (max-width: 620px)": "10px 14px" },
    color: "inherit",
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorHover,
      ":focus-visible": tokens.colorHover,
    },
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccentBorder}`,
    },
    outlineOffset: { default: "0", ":focus-visible": "-2px" },
    transitionProperty: "background-color",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  rowIcon: {
    width: "30px",
    height: "30px",
    display: "grid",
    placeItems: "center",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
    gridRow: { default: "auto", "@media (max-width: 860px)": "1 / 3" },
  },
  rowTruncate: {
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  rowTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: "13.5px",
    fontWeight: 550,
    gridColumn: { default: "auto", "@media (max-width: 860px)": "2" },
  },
  rowMeta: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    fontVariantNumeric: "tabular-nums",
    display: { default: "block", "@media (max-width: 860px)": "none" },
  },
  rowAge: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
    fontVariantNumeric: "tabular-nums",
    textAlign: "right",
    gridColumn: { default: "auto", "@media (max-width: 860px)": "2" },
    gridRow: { default: "auto", "@media (max-width: 860px)": "2" },
    justifySelf: { default: "end", "@media (max-width: 860px)": "start" },
  },
  rowArrow: {
    justifySelf: "end",
    color: {
      default: tokens.colorSubtle,
      [stylex.when.ancestor(":hover")]: tokens.colorTextEmphasis,
      [stylex.when.ancestor(":focus-visible")]: tokens.colorTextEmphasis,
    },
    transform: {
      default: "none",
      [stylex.when.ancestor(":hover")]: "translate(1px, -1px)",
      [stylex.when.ancestor(":focus-visible")]: "translate(1px, -1px)",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    transitionProperty: "color, transform",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
    gridColumn: { default: "auto", "@media (max-width: 860px)": "4" },
    gridRow: { default: "auto", "@media (max-width: 860px)": "1 / 3" },
  },
});
