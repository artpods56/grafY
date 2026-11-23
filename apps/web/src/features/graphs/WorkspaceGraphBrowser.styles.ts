import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

/**
 * The graph browser's own layout, type, and spacing.
 *
 * These rules used to live in `apps/web/src/app/globals.css` under the
 * `.grafy-graphs*` class names, in `@layer legacy`. They are reproduced here
 * value for value, including the 860px and 620px breakpoints and the
 * `prefers-reduced-motion` block, so moving them changes nothing on screen.
 *
 * Two things stay in `globals.css` on purpose:
 *
 * - `@keyframes grafy-graphs-enter`, which `@keyframes` cannot leave, and which
 *   this module references by name.
 * - The `:root` declarations of `--grafy-rail-width` and
 *   `--grafy-mobile-page-top`, including their breakpoint overrides. Padding
 *   here reads those variables instead of restating widths.
 */
export const browserStyles = stylex.create({
  /** Keeps the strip's own spacing around the list; Notice carries none. */
  partialNotice: {
    margin: "16px 0 4px",
  },

  root: {
    minHeight: "100svh",
    overflow: "auto",
  },
  main: {
    maxWidth: "1160px",
    minHeight: "100svh",
    margin: "0 auto",
    // The gutter follows the rail's live width, so resizing it moves the copy.
    padding: {
      default: "44px 48px 64px calc(var(--grafy-rail-width, 200px) + 52px)",
      "@media (max-width: 860px)":
        "28px 18px 48px calc(var(--grafy-rail-width, 64px) + 18px)",
      // Below 620px the mobile header replaces the rail gutter entirely.
      "@media (max-width: 620px)":
        "calc(var(--grafy-mobile-page-top) + env(safe-area-inset-top)) calc(16px + env(safe-area-inset-right)) calc(40px + env(safe-area-inset-bottom)) calc(16px + env(safe-area-inset-left))",
    },
    transition: {
      default: "padding 180ms ease",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
  },

  header: {
    display: "flex",
    alignItems: {
      default: "flex-end",
      "@media (max-width: 860px)": "flex-start",
    },
    justifyContent: "space-between",
    flexDirection: {
      default: "row",
      "@media (max-width: 860px)": "column",
    },
    gap: { default: "24px", "@media (max-width: 620px)": "18px" },
    marginBottom: { default: "28px", "@media (max-width: 620px)": "22px" },
    animationName: {
      default: "grafy-graphs-enter",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    animationDuration: "220ms",
    animationTimingFunction: "ease-out",
    animationFillMode: "both",
  },
  /** The workspace name above the page title. */
  eyebrow: {
    marginBottom: "5px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    letterSpacing: "0.09em",
    textTransform: "uppercase",
  },
  pageTitle: {
    color: tokens.colorText,
    fontSize: "clamp(1.9rem, 3.5vw, 2.7rem)",
    fontWeight: 500,
    letterSpacing: "-0.04em",
    lineHeight: 1.08,
  },
  intro: {
    marginTop: "8px",
    color: tokens.colorMuted,
    fontSize: "14px",
  },
  /**
   * The header's `New project`. The kit `Button` keeps its own skin and its
   * 44px phone height; on a phone the row is what stretches, and the kit's
   * `flex-shrink: 0` is left alone because the global shorthand lost to it
   * before this file existed.
   */
  headerAction: {
    minWidth: { default: "auto", "@media (max-width: 620px)": "0" },
    flexGrow: { default: 0, "@media (max-width: 620px)": 1 },
    flexBasis: { default: "auto", "@media (max-width: 620px)": "100%" },
    width: { default: "auto", "@media (max-width: 620px)": "100%" },
  },

  recipes: {
    display: "grid",
    gap: "10px",
    margin: "4px 0 18px",
  },
  recipeHeading: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    fontWeight: 560,
  },
  recipeRow: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
    gap: "10px",
  },
  recipe: {
    display: "grid",
    gap: "4px",
    padding: "12px 14px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default:
        "light-dark(color-mix(in srgb, white 88%, transparent), color-mix(in srgb, white 8%, transparent))",
      ":hover:not(:disabled)": tokens.colorHover,
    },
    color: tokens.colorText,
    fontFamily: "inherit",
    fontSize: tokens.fontSizeSm,
    textAlign: "start",
    cursor: {
      default: "pointer",
      ":disabled": "default",
    },
  },
  recipeTitle: {
    fontWeight: 560,
  },
  recipePath: {
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
  },

  /**
   * The filter strip. Only the single-column form is rendered here, so the
   * retired `--scoped` modifier's column list is the plain value.
   */
  toolbar: {
    display: "grid",
    gridTemplateColumns: {
      default: "minmax(240px, 1fr)",
      "@media (max-width: 620px)": "1fr",
    },
    alignItems: "end",
    gap: { default: "12px", "@media (max-width: 620px)": "14px" },
    marginBottom: { default: "24px", "@media (max-width: 620px)": "18px" },
    animationName: {
      default: "grafy-graphs-enter",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    animationDelay: "40ms",
    animationDuration: "220ms",
    animationTimingFunction: "ease-out",
    animationFillMode: "both",
  },
  /**
   * The search field is drawn here rather than by the kit `Field`, so it keeps
   * the label-as-box look. Its 44px phone floor is this field's own promise,
   * not a kit control's, and it stays keyed to 620px.
   */
  search: {
    minHeight: { default: "40px", "@media (max-width: 620px)": "44px" },
    display: "flex",
    alignItems: "center",
    gap: "10px",
    padding: "0 13px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorBorder,
      ":focus-within": tokens.colorText,
    },
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorBg,
    color: tokens.colorSubtle,
    boxShadow: {
      default: "none",
      ":focus-within":
        "0 0 0 3px light-dark(rgba(17, 17, 17, 0.06), rgba(245, 245, 245, 0.08))",
    },
    transition: "border-color 140ms ease, box-shadow 140ms ease",
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
    fontSize: "14px",
  },

  viewBar: {
    minHeight: "38px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "16px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  count: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
    fontVariantNumeric: "tabular-nums",
  },

  loading: {
    minHeight: "240px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "12px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeMd,
  },

  /** Icon, copy, action: one row each, aligned to the copy's first line. */
  state: {
    minHeight: { default: "220px", "@media (max-width: 620px)": "180px" },
    display: "grid",
    gridTemplateColumns: {
      default: "28px minmax(0, 1fr) auto",
      "@media (max-width: 620px)": "28px minmax(0, 1fr)",
    },
    alignContent: "center",
    alignItems: "start",
    gap: "6px 14px",
    paddingBlock: "42px",
    paddingInline: { default: "8px", "@media (max-width: 620px)": "0" },
    color: tokens.colorMuted,
  },
  /** An end-of-list state, so it closes the surface above it. */
  stateEmpty: {
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
  },
  stateIcon: {
    gridRow: "1 / 3",
    color: tokens.colorText,
  },
  stateTitle: {
    color: tokens.colorText,
    fontSize: "15px",
    fontWeight: 550,
  },
  stateBody: {
    marginTop: "4px",
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
  },
  /** Each row enters on the same clock, the first three staggered by 20ms. */
  listItem: {
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    // Not tokens.colorDivider: this divider sits between list rows.
    borderBottomColor: "light-dark(#e5e5e5, #242424)",
    animationName: {
      default: "grafy-graphs-enter",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    animationDelay: {
      default: "0ms",
      ":nth-child(2)": "20ms",
      ":nth-child(3)": "40ms",
    },
    animationDuration: "180ms",
    animationTimingFunction: "ease-out",
    animationFillMode: "both",
  },
  row: {
    display: "grid",
    gridTemplateColumns: {
      default: "32px minmax(170px, 1fr) minmax(120px, 0.55fr) 86px 174px 18px",
      "@media (max-width: 860px)": "32px minmax(0, 1fr) 18px",
    },
    alignItems: "center",
    gap: { default: "12px", "@media (max-width: 860px)": "3px 10px" },
    minHeight: {
      default: "64px",
      "@media (max-width: 860px)": "62px",
      "@media (max-width: 620px)": "68px",
    },
    padding: "10px 8px",
    color: "inherit",
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": "light-dark(#fafafa, #171717)",
      ":focus-visible": "light-dark(#fafafa, #171717)",
    },
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorText}`,
    },
    outlineOffset: { default: "0", ":focus-visible": "-2px" },
    transition: {
      default: "background-color 140ms ease",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
  },
  rowIcon: {
    width: "30px",
    height: "30px",
    display: "grid",
    placeItems: "center",
    borderRadius: "7px",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
    gridRow: { default: "auto", "@media (max-width: 860px)": "1 / 3" },
  },
  /** A narrow column of one-line copy: it truncates instead of wrapping. */
  rowTruncate: {
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  rowTitle: {
    color: tokens.colorText,
    fontSize: "14px",
    fontWeight: 500,
    gridColumn: { default: "auto", "@media (max-width: 860px)": "2" },
  },
  rowLocation: {
    color: "light-dark(#444444, #d4d4d4)",
    fontSize: tokens.fontSizeSm,
    gridColumn: { default: "auto", "@media (max-width: 860px)": "2" },
    gridRow: { default: "auto", "@media (max-width: 860px)": "2" },
  },
  rowMeta: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontVariantNumeric: "tabular-nums",
    display: { default: "block", "@media (max-width: 860px)": "none" },
  },
  /**
   * The arrow answers the row's own hover and keyboard focus, which is why the
   * row carries `stylex.defaultMarker()`: the marker is what tells this
   * condition which ancestor to watch.
   */
  rowArrow: {
    justifySelf: "end",
    color: {
      default: "light-dark(#8a8a8a, #6b6b6b)",
      [stylex.when.ancestor(":hover")]: "light-dark(#111111, #f5f5f5)",
      [stylex.when.ancestor(":focus-visible")]: "light-dark(#111111, #f5f5f5)",
    },
    transform: {
      default: "none",
      [stylex.when.ancestor(":hover")]: "translate(1px, -1px)",
      [stylex.when.ancestor(":focus-visible")]: "translate(1px, -1px)",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    transition: {
      default: "color 140ms ease, transform 140ms ease",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    gridColumn: { default: "auto", "@media (max-width: 860px)": "3" },
    gridRow: { default: "auto", "@media (max-width: 860px)": "1 / 3" },
  },
});
