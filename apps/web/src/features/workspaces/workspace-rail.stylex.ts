import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

/**
 * Tier 1 Primary Dark Sidebar (`WorkspaceRail`) and shell frame styles.
 *
 * The rail is always dark charcoal (`tokens.colorRailBg`) in both light and
 * dark palettes, preserving `--grafy-rail-width`, `--grafy-mobile-header-height`,
 * and `--grafy-mobile-overlay-top` from `globals.css` as the single width
 * contract shared with the workbench and page layouts.
 */

/**
 * Applied to a graph row (in the rail's recent list or in `WorkspaceGraphPanel`)
 * so the row's menu trigger can reveal on row hover / focus.
 */
export const graphRowMarker = stylex.defaultMarker();

export const railStyles = stylex.create({
  frame: {
    minHeight: "100svh",
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
  },
  frameMain: {
    minHeight: "100svh",
  },

  mobileNav: {
    display: {
      default: "none",
      "@media (max-width: 620px)": "grid",
    },
    "@media (max-width: 620px)": {
      position: "fixed",
      zIndex: 80,
      top: 0,
      right: 0,
      left: 0,
      minHeight:
        "calc(var(--grafy-mobile-header-height) + env(safe-area-inset-top))",
      gridTemplateColumns: "44px auto minmax(0, 1fr)",
      alignItems: "end",
      gap: "10px",
      padding:
        "env(safe-area-inset-top) calc(12px + env(safe-area-inset-right)) 6px calc(12px + env(safe-area-inset-left))",
      borderBottomWidth: "1px",
      borderBottomStyle: "solid",
      borderBottomColor: tokens.colorBorder,
      backgroundColor: tokens.colorSurface,
    },
  },
  mobileBrand: {
    "@media (max-width: 620px)": {
      height: "44px",
      display: "inline-flex",
      alignItems: "center",
      justifyContent: "center",
      paddingInline: "4px",
      borderWidth: 0,
      borderStyle: "none",
      borderRadius: tokens.radiusMd,
      backgroundColor: "transparent",
      color: tokens.colorTextEmphasis,
      cursor: "pointer",
    },
  },
  mobileLocation: {
    "@media (max-width: 620px)": {
      minWidth: 0,
      alignSelf: "center",
      overflow: "hidden",
      color: tokens.colorMuted,
      fontSize: tokens.fontSizeSm,
      fontWeight: 500,
      textAlign: "right",
      textOverflow: "ellipsis",
      whiteSpace: "nowrap",
    },
  },
  mobileBackdrop: {
    display: {
      default: "none",
      "@media (max-width: 620px)": "block",
    },
    "@media (max-width: 620px)": {
      position: "fixed",
      zIndex: 55,
      inset: 0,
      width: "100%",
      height: "100%",
      borderWidth: 0,
      borderStyle: "none",
      backgroundColor:
        "light-dark(rgba(15, 23, 42, 0.36), rgba(0, 0, 0, 0.62))",
      cursor: "pointer",
      opacity: 0,
      pointerEvents: "none",
      transition: "opacity 180ms ease",
    },
    "@media (prefers-reduced-motion: reduce)": {
      transition: "none",
    },
  },
  mobileBackdropOpen: {
    "@media (max-width: 620px)": {
      opacity: 1,
      pointerEvents: "auto",
    },
  },

  rail: {
    "--grafy-rail-expanded": "220px",
    "--grafy-rail-pad": "12px",
    "--grafy-rail-item-pad": "12px",
    "--grafy-rail-icon": "15px",
    "--grafy-rail-icon-center":
      "calc(var(--grafy-rail-item-pad) + var(--grafy-rail-icon) / 2)",
    "--grafy-rail-content":
      "calc(var(--grafy-rail-expanded) - 2 * var(--grafy-rail-pad))",
    "--grafy-rail-text":
      "calc(var(--grafy-rail-content) - 2 * var(--grafy-rail-item-pad) - var(--grafy-rail-icon) - 10px)",
    "--grafy-rail-avatar": "28px",
    "--grafy-rail-avatar-pad":
      "calc(var(--grafy-rail-icon-center) - var(--grafy-rail-avatar) / 2)",
    "--grafy-rail-account-text":
      "calc(var(--grafy-rail-content) - 2 * var(--grafy-rail-avatar-pad) - var(--grafy-rail-avatar) - 10px)",
    "--grafy-rail-copy": "1",
    "--grafy-rail-copy-delay": "70ms",
    position: "fixed",
    zIndex: 50,
    inset: "0 auto 0 0",
    width: "var(--grafy-rail-width)",
    display: "flex",
    flexDirection: "column",
    gap: "16px",
    padding: "16px var(--grafy-rail-pad) 12px",
    overflow: "hidden",
    borderRightWidth: "1px",
    borderRightStyle: "solid",
    borderRightColor: tokens.colorRailBorder,
    backgroundColor: tokens.colorRailBg,
    color: tokens.colorRailText,
    transition: "width 180ms ease",
    "@media (min-width: 621px) and (max-width: 860px)": {
      "--grafy-rail-copy": "0",
      "--grafy-rail-copy-delay": "0ms",
    },
    "@media (max-width: 620px)": {
      "--grafy-rail-expanded": "min(300px, calc(100vw - 24px))",
      "--grafy-rail-copy": "1",
      "--grafy-rail-copy-delay": "50ms",
      zIndex: 70,
      width: "var(--grafy-rail-expanded)",
      maxWidth: "calc(100vw - 24px)",
      gap: "16px",
      padding:
        "calc(var(--grafy-mobile-overlay-top) + env(safe-area-inset-top)) calc(12px + env(safe-area-inset-right)) calc(14px + env(safe-area-inset-bottom)) calc(12px + env(safe-area-inset-left))",
      overflowX: "hidden",
      overflowY: "auto",
      boxShadow: "18px 0 48px rgba(0, 0, 0, 0.48)",
      transform: "translateX(calc(-100% - 12px))",
      visibility: "hidden",
      transition: "transform 180ms ease, visibility 0s linear 180ms",
      "@media (prefers-reduced-motion: reduce)": {
        transition: "none",
      },
    },
    "@media (prefers-reduced-motion: reduce)": {
      transition: "none",
    },
  },
  railCollapsed: {
    "--grafy-rail-copy": "0",
    "--grafy-rail-copy-delay": "0ms",
  },
  railMobileOpen: {
    "@media (max-width: 620px)": {
      transform: "translateX(0)",
      visibility: "visible",
      transitionDelay: "0s",
    },
  },
  /** Dragging the resize handle moves the width on the pointer's clock. */
  railNoTransition: {
    transition: "none",
  },

  railHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "6px",
    minHeight: "36px",
    flexShrink: 0,
    "@media (max-width: 620px)": {
      display: "none",
    },
  },
  railHeaderCollapsed: {
    flexDirection: "column",
    alignItems: "center",
    gap: "6px",
    minHeight: "auto",
    "@media (min-width: 621px) and (max-width: 860px)": {
      flexDirection: "row",
      minHeight: "36px",
    },
  },
  railBrand: {
    position: "relative",
    flex: "1 1 auto",
    minWidth: 0,
    height: "36px",
    padding: 0,
    borderWidth: 0,
    borderStyle: "none",
    borderRadius: tokens.radiusSm,
    backgroundColor: "transparent",
    cursor: "pointer",
    outline: {
      default: "none",
      ":focus-visible": "2px solid rgba(255, 255, 255, 0.35)",
    },
  },
  railBrandCollapsed: {
    flex: "0 0 36px",
    width: "100%",
    height: "36px",
  },
  brandWordmark: {
    position: "absolute",
    top: "50%",
    display: "block",
    maxWidth: "none",
    left: "var(--grafy-rail-item-pad)",
    width: "auto",
    height: "22px",
    transform: "translateY(-50%)",
    opacity: "var(--grafy-rail-copy)",
    transition: "opacity 140ms ease var(--grafy-rail-copy-delay)",
    "@media (prefers-reduced-motion: reduce)": {
      transition: "none",
    },
  },
  brandIcon: {
    position: "absolute",
    top: "50%",
    display: "block",
    maxWidth: "none",
    left: "var(--grafy-rail-icon-center)",
    width: "26px",
    height: "26px",
    transform: "translate(-50%, -50%)",
    opacity: "calc(1 - var(--grafy-rail-copy))",
    transition: "opacity 140ms ease var(--grafy-rail-copy-delay)",
    "@media (prefers-reduced-motion: reduce)": {
      transition: "none",
    },
  },
  collapseToggle: {
    display: {
      default: "inline-grid",
      "@media (max-width: 860px)": "none",
    },
    placeItems: "center",
    flexShrink: 0,
    width: "28px",
    height: "28px",
    padding: 0,
    borderWidth: 0,
    borderStyle: "none",
    borderRadius: tokens.radiusSm,
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorRailHover,
    },
    color: {
      default: tokens.colorRailMuted,
      ":hover:not(:disabled)": tokens.colorRailTextEmphasis,
    },
    cursor: "pointer",
    outline: {
      default: "none",
      ":focus-visible": "2px solid rgba(255, 255, 255, 0.35)",
    },
    transition: "background-color 140ms ease, color 140ms ease",
    "@media (prefers-reduced-motion: reduce)": {
      transition: "none",
    },
  },

  railResize: {
    position: "absolute",
    top: 0,
    right: "-3px",
    bottom: 0,
    zIndex: 2,
    width: "6px",
    cursor: "col-resize",
    touchAction: "none",
    "@media (max-width: 860px)": {
      display: "none",
    },
    "::after": {
      content: '""',
      position: "absolute",
      top: 0,
      bottom: 0,
      left: "2px",
      width: "1px",
      backgroundColor: "transparent",
      transition: "background-color 140ms ease",
    },
    ":hover::after": {
      backgroundColor: tokens.colorRailMuted,
    },
  },
  /** The `body.grafy-rail-resizing` half of the resize-handle rule. */
  railResizeActive: {
    "::after": {
      backgroundColor: tokens.colorRailTextEmphasis,
    },
  },

  railNav: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr)",
    gap: "2px",
    minWidth: 0,
  },
  railNavOpen: {
    "@media (max-width: 620px)": {
      display: "none",
    },
  },
  thisProjectGroup: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr)",
    gap: "2px",
    minWidth: 0,
    marginTop: "10px",
    paddingTop: "12px",
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: tokens.colorRailBorder,
  },

  sectionLabel: {
    margin: "0 var(--grafy-rail-item-pad) 4px",
    overflow: "hidden",
    color: tokens.colorRailSubtle,
    fontSize: "10px",
    fontWeight: 600,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
    whiteSpace: "nowrap",
    opacity: "var(--grafy-rail-copy)",
    transition: "opacity 140ms ease var(--grafy-rail-copy-delay)",
    pointerEvents: {
      default: "auto",
      "@media (min-width: 621px) and (max-width: 860px)": "none",
    },
    "@media (prefers-reduced-motion: reduce)": {
      transition: "none",
    },
    "@media (max-width: 620px)": {
      opacity: "1",
      pointerEvents: "auto",
    },
  },
  /** The collapsed state's `pointer-events: none` on the fading copy. */
  copyHidden: {
    pointerEvents: "none",
  },

  railItems: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr)",
    gap: "2px",
    overflowX: "hidden",
    overflowY: "auto",
    maxHeight: "28vh",
  },

  railItem: {
    borderWidth: 0,
    borderStyle: "none",
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorRailHover,
    },
    color: {
      default: tokens.colorRailMuted,
      ":hover:not(:disabled)": tokens.colorRailTextEmphasis,
      ":disabled": tokens.colorRailSubtle,
    },
    cursor: {
      default: "pointer",
      ":disabled": "default",
    },
    width: "100%",
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-start",
    gap: "10px",
    padding: "7px var(--grafy-rail-item-pad)",
    overflow: "hidden",
    borderRadius: tokens.radiusSm,
    textAlign: "left",
    fontSize: tokens.fontSizeMd,
    fontWeight: 450,
    outline: {
      default: "none",
      ":focus-visible": "2px solid rgba(255, 255, 255, 0.35)",
    },
    outlineOffset: "-2px",
    transition: "background-color 140ms ease, color 140ms ease",
    "@media (prefers-reduced-motion: reduce)": {
      transition: "none",
    },
    "@media (max-width: 620px)": {
      minHeight: "44px",
    },
  },
  railItemActive: {
    backgroundColor: {
      default: tokens.colorRailActive,
      ":hover:not(:disabled)": tokens.colorRailActive,
    },
    color: {
      default: tokens.colorRailTextEmphasis,
      ":hover:not(:disabled)": tokens.colorRailTextEmphasis,
    },
    fontWeight: 550,
  },
  railSettings: {
    flexShrink: 0,
    marginTop: "auto",
    marginBottom: "-8px",
  },
  // Sits under Settings at the project list's row rhythm (Settings already pulls 8px
  // of the rail gap), and is now the last item, so it tucks against the account footer.
  railFeedback: {
    flexShrink: 0,
    marginTop: "-6px",
    marginBottom: "-8px",
  },
  itemSpan: {
    flex: "0 0 auto",
    width: "var(--grafy-rail-text)",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    opacity: "var(--grafy-rail-copy)",
    transition: "opacity 140ms ease var(--grafy-rail-copy-delay)",
    pointerEvents: {
      default: "auto",
      "@media (min-width: 621px) and (max-width: 860px)": "none",
    },
    "@media (prefers-reduced-motion: reduce)": {
      transition: "none",
    },
    "@media (max-width: 620px)": {
      opacity: "1",
      pointerEvents: "auto",
    },
  },
  mobileClose: {
    display: "none",
    "@media (max-width: 620px)": {
      display: "flex",
      minHeight: "44px",
      justifyContent: "space-between",
      color: tokens.colorRailTextEmphasis,
    },
  },
  mobileCloseSpan: {
    "@media (max-width: 620px)": {
      width: "auto",
    },
  },

  railIcon: {
    flex: "0 0 var(--grafy-rail-icon)",
    width: "var(--grafy-rail-icon)",
    height: "var(--grafy-rail-icon)",
    maxWidth: "none",
  },

  workspaceTrigger: {
    width: "100%",
    minWidth: 0,
    height: { default: "34px", "@media (max-width: 620px)": "44px" },
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    gap: "10px",
    // The 1px border comes out of the padding, so the icon lines up with the rows.
    paddingInlineStart: "calc(var(--grafy-rail-item-pad) - 1px)",
    paddingInlineEnd: "7px",
    overflow: "hidden",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorRailBorder,
      ":hover": "rgba(255, 255, 255, 0.18)",
      ":focus-visible": "rgba(255, 255, 255, 0.3)",
      ":is([data-popup-open])": "rgba(255, 255, 255, 0.3)",
      "@media (min-width: 621px) and (max-width: 860px)": "transparent",
    },
    borderRadius: tokens.radiusMd,
    outline: {
      default: "none",
      ":focus-visible": "2px solid rgba(255, 255, 255, 0.35)",
    },
    outlineOffset: "-2px",
    backgroundColor: {
      default: tokens.colorRailSurface,
      ":hover": tokens.colorRailHover,
      ":is([data-popup-open])": tokens.colorRailActive,
      "@media (min-width: 621px) and (max-width: 860px)": {
        default: "transparent",
        ":hover": tokens.colorRailHover,
        ":focus-visible": tokens.colorRailHover,
        ":is([data-popup-open])": tokens.colorRailActive,
      },
    },
    color: {
      default: tokens.colorRailMuted,
      ":hover": tokens.colorRailTextEmphasis,
      ":focus-visible": tokens.colorRailTextEmphasis,
      ":is([data-popup-open])": tokens.colorRailTextEmphasis,
    },
    cursor: "pointer",
    fontSize: tokens.fontSizeMd,
    fontWeight: 500,
    textAlign: "left",
    transitionProperty: "background-color, border-color, color",
    transitionDuration: {
      default: "140ms",
      "@media (prefers-reduced-motion: reduce)": "0s",
    },
    transitionTimingFunction: "ease",
  },
  /** Collapsed rail (React state). The phone drawer keeps the full control. */
  workspaceTriggerCollapsed: {
    borderColor: {
      default: "transparent",
      "@media (max-width: 620px)": tokens.colorRailBorder,
    },
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorRailHover,
      ":focus-visible": tokens.colorRailHover,
      ":is([data-popup-open])": tokens.colorRailActive,
      "@media (max-width: 620px)": tokens.colorRailSurface,
    },
  },
  workspaceName: {
    flex: 1,
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorRailTextEmphasis,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    opacity: "var(--grafy-rail-copy)",
    transition: "opacity 140ms ease var(--grafy-rail-copy-delay)",
    "@media (prefers-reduced-motion: reduce)": {
      transition: "none",
    },
    "@media (max-width: 620px)": {
      opacity: "1",
    },
  },
  workspaceChevron: {
    flexShrink: 0,
    opacity: "var(--grafy-rail-copy)",
    transition: "opacity 140ms ease var(--grafy-rail-copy-delay)",
    "@media (prefers-reduced-motion: reduce)": {
      transition: "none",
    },
    "@media (max-width: 620px)": {
      opacity: "1",
    },
  },
  /** At least as wide as the switcher; long names widen it up to the kit's cap. */
  workspaceMenu: {
    minWidth: "max(var(--anchor-width), 190px)",
  },

  badge: {
    minWidth: "18px",
    marginLeft: "auto",
    padding: "1px 6px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorRailTextEmphasis,
    color: tokens.colorRailBg,
    fontSize: "10px",
    fontWeight: 600,
    lineHeight: "16px",
    textAlign: "center",
    fontVariantNumeric: "tabular-nums",
  },

  railSpin: {
    animationName: {
      default: "grafy-spin",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },

  railFooter: {
    marginInline: "calc(-1 * var(--grafy-rail-pad))",
    padding: "10px var(--grafy-rail-pad) 0",
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: tokens.colorRailBorder,
  },
  railAccount: {
    borderWidth: 0,
    borderStyle: "none",
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorRailHover,
    },
    color: tokens.colorRailMuted,
    cursor: "pointer",
    width: "100%",
    display: "flex",
    alignItems: "center",
    gap: "10px",
    padding: "6px var(--grafy-rail-avatar-pad)",
    overflow: "hidden",
    borderRadius: tokens.radiusMd,
    textAlign: "left",
    outline: {
      default: "none",
      ":focus-visible": "2px solid rgba(255, 255, 255, 0.35)",
    },
    transition: "background-color 140ms ease",
    "[data-popup-open]": {
      backgroundColor: tokens.colorRailActive,
    },
    "@media (max-width: 620px)": {
      minHeight: "44px",
    },
  },
  railAvatar: {
    flex: "0 0 var(--grafy-rail-avatar)",
    width: "var(--grafy-rail-avatar)",
    height: "var(--grafy-rail-avatar)",
    display: "grid",
    placeItems: "center",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorRailBorder,
    borderRadius: "7px",
    backgroundColor: tokens.colorRailActive,
    color: tokens.colorRailTextEmphasis,
    fontFamily: "var(--font-geist-sans)",
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
    letterSpacing: "0.02em",
  },
  accountCopy: {
    flex: "0 0 auto",
    width: "var(--grafy-rail-account-text)",
    minWidth: 0,
    display: "grid",
    gap: "1px",
    opacity: "var(--grafy-rail-copy)",
    transition: "opacity 140ms ease var(--grafy-rail-copy-delay)",
    pointerEvents: {
      default: "auto",
      "@media (min-width: 621px) and (max-width: 860px)": "none",
    },
    "@media (prefers-reduced-motion: reduce)": {
      transition: "none",
    },
    "@media (max-width: 620px)": {
      opacity: "1",
      pointerEvents: "auto",
    },
  },
  accountName: {
    overflow: "hidden",
    color: tokens.colorRailTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 500,
    lineHeight: 1.3,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  accountEmail: {
    overflow: "hidden",
    color: tokens.colorRailMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.3,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },

  accountPositioner: {
    zIndex: 80,
  },
  accountMenu: {
    minWidth: "212px",
    padding: "6px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    boxShadow: tokens.shadowNodeRaised,
  },
  accountThemeBlock: {
    display: "grid",
    gap: "6px",
    padding: "4px 4px 6px",
  },
  accountThemeLabel: {
    paddingInline: "4px",
    color: tokens.colorSubtle,
    fontSize: "10px",
    fontWeight: 600,
    letterSpacing: "0.08em",
    textTransform: "uppercase",
  },
  accountMenuDivider: {
    height: "1px",
    margin: "4px 2px",
    backgroundColor: tokens.colorDivider,
  },
  accountMenuItem: {
    width: "100%",
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "7px 10px",
    borderWidth: 0,
    borderStyle: "none",
    borderRadius: tokens.radiusSm,
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorHover,
    },
    color: tokens.colorText,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
    textAlign: "left",
    "@media (max-width: 620px)": {
      minHeight: "44px",
    },
  },
  accountMenuItemDanger: {
    color: tokens.colorDanger,
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorDangerHover,
    },
  },

  graphRow: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    alignItems: "center",
    minWidth: 0,
    borderRadius: tokens.radiusSm,
    ":hover": {
      backgroundColor: tokens.colorRailHover,
    },
  },
  graphRowActive: {
    backgroundColor: {
      default: tokens.colorRailActive,
      ":hover": tokens.colorRailActive,
    },
  },
  /** Keeps the row's own hover background from painting under the item. */
  graphRowItem: {
    backgroundColor: "transparent",
    ":hover:not(:disabled)": {
      backgroundColor: "transparent",
    },
  },
  graphRowItemActive: {
    color: {
      default: tokens.colorRailTextEmphasis,
      ":hover:not(:disabled)": tokens.colorRailTextEmphasis,
    },
    fontWeight: 550,
  },
  graphRowOpen: {
    minWidth: 0,
  },
  menuTrigger: {
    width: "24px",
    height: "24px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    marginRight: "4px",
    borderWidth: 0,
    borderStyle: "none",
    borderRadius: tokens.radiusSm,
    backgroundColor: "transparent",
    color: tokens.colorRailMuted,
    cursor: "pointer",
    opacity: 0,
    transition:
      "opacity 120ms ease, background-color 120ms ease, color 120ms ease",
    [stylex.when.ancestor(":hover")]: {
      opacity: 1,
    },
    [stylex.when.ancestor(":focus-within")]: {
      opacity: 1,
    },
    "[data-popup-open]": {
      opacity: 1,
    },
    '[aria-expanded="true"]': {
      opacity: 1,
    },
    ":hover:not(:disabled)": {
      backgroundColor: tokens.colorRailActive,
      color: tokens.colorRailTextEmphasis,
    },
    "@media (max-width: 620px)": {
      width: "44px",
      height: "44px",
      marginRight: 0,
      opacity: 1,
    },
  },
  menuTriggerSurface: {
    color: tokens.colorSubtle,
    ":hover:not(:disabled)": {
      backgroundColor: tokens.colorHoverStrong,
      color: tokens.colorTextEmphasis,
    },
  },
});
