import * as stylex from "@stylexjs/stylex";

/**
 * StyleX port of the `.grafy-workspace-frame*`, `.grafy-mobile-nav*`,
 * `.grafy-workspace-rail*`, and `.grafy-graph-row*` rules that used to live in
 * globals.css. Values are copied verbatim, including the 860px / 620px
 * breakpoints and the prefers-reduced-motion overrides. The 860px rules that
 * the 620px block restores are expressed as a `min-width: 621px and max-width:
 * 860px` range so the two never compete for the same property.
 *
 * `--grafy-rail-width`, `--grafy-mobile-header-height`, and
 * `--grafy-mobile-overlay-top` stay as `:root` variables in globals.css; the
 * `--grafy-rail-*` geometry below is scoped to the rail element as before.
 */

/**
 * The default marker, applied to a graph row (in the rail's recent list or in
 * the graph panel) so the row's menu trigger can reveal on row hover / focus,
 * as the old `.grafy-graph-row:hover .grafy-graph-row__menu-trigger` rules
 * did. `graphRowMarker` is passed to `stylex.props` next to the row style.
 */
export const graphRowMarker = stylex.defaultMarker();

export const railStyles = stylex.create({
  frame: {
    minHeight: "100svh",
    backgroundColor: "light-dark(#ffffff, #111111)",
    color: "light-dark(#111111, #f5f5f5)",
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
      borderBottomColor: "light-dark(#d9d9d9, #2a2a2a)",
      backgroundColor:
        "light-dark(rgba(255, 255, 255, 0.96), rgba(17, 17, 17, 0.96))",
      backdropFilter: "blur(14px)",
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
      borderRadius: "8px",
      backgroundColor: "transparent",
      color: "light-dark(#111111, #f5f5f5)",
      cursor: "pointer",
    },
  },
  mobileLocation: {
    "@media (max-width: 620px)": {
      minWidth: 0,
      alignSelf: "center",
      overflow: "hidden",
      color: "light-dark(#6b6b6b, #a3a3a3)",
      fontSize: "12px",
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
        "light-dark(rgba(17, 17, 17, 0.28), rgba(0, 0, 0, 0.56))",
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
    "--grafy-rail-expanded": "200px",
    "--grafy-rail-pad": "12px",
    "--grafy-rail-item-pad": "10px",
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
    gap: "20px",
    padding: "20px var(--grafy-rail-pad) 14px",
    overflow: "hidden",
    borderRightWidth: "1px",
    borderRightStyle: "solid",
    borderRightColor: "light-dark(#d9d9d9, #2a2a2a)",
    backgroundColor: "light-dark(#ffffff, #111111)",
    transition: "width 180ms ease",
    // The 860px block only re-faded the copy; its other declarations restated
    // the base values, so only the copy variables are ported here.
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
      boxShadow:
        "18px 0 48px light-dark(rgba(17, 17, 17, 0.12), rgba(0, 0, 0, 0.45))",
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

  railBrand: {
    position: "relative",
    flex: "0 0 36px",
    width: "100%",
    padding: 0,
    borderWidth: 0,
    borderStyle: "none",
    backgroundColor: "transparent",
    cursor: "pointer",
    "@media (max-width: 620px)": {
      display: "none",
    },
  },
  brandWordmark: {
    position: "absolute",
    top: "50%",
    display: "block",
    maxWidth: "none",
    left: "var(--grafy-rail-item-pad)",
    width: "auto",
    height: "24px",
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
    width: "28px",
    height: "28px",
    transform: "translate(-50%, -50%)",
    opacity: "calc(1 - var(--grafy-rail-copy))",
    transition: "opacity 140ms ease var(--grafy-rail-copy-delay)",
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
      backgroundColor: "light-dark(#111111, #ffffff)",
    },
  },
  /** The `body.grafy-rail-resizing` half of the old resize-handle rule. */
  railResizeActive: {
    "::after": {
      backgroundColor: "light-dark(#111111, #ffffff)",
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

  sectionLabel: {
    margin: "0 var(--grafy-rail-item-pad) 6px",
    overflow: "hidden",
    color: "light-dark(#6b6b6b, #8a8a8a)",
    fontSize: "11px",
    fontWeight: 500,
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
    backgroundColor: "transparent",
    color: "light-dark(#6b6b6b, #a3a3a3)",
    cursor: "pointer",
    width: "100%",
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    justifyContent: "flex-start",
    gap: "10px",
    padding: "8px var(--grafy-rail-item-pad)",
    overflow: "hidden",
    borderRadius: "6px",
    textAlign: "left",
    fontSize: "13px",
    fontWeight: 400,
    transition: "background-color 140ms ease, color 140ms ease",
    ":hover:not(:disabled)": {
      backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
      color: "light-dark(#111111, #f5f5f5)",
    },
    "@media (prefers-reduced-motion: reduce)": {
      transition: "none",
    },
    "@media (max-width: 620px)": {
      minHeight: "44px",
    },
  },
  railItemActive: {
    backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
    color: "light-dark(#111111, #ffffff)",
    fontWeight: 500,
    ":hover:not(:disabled)": {
      color: "light-dark(#111111, #ffffff)",
    },
  },
  railSettings: {
    flexShrink: 0,
    marginTop: "auto",
    // Pull back most of the rail's 20px gap so it sits close to the divider.
    marginBottom: "-12px",
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
      color: "light-dark(#111111, #f5f5f5)",
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

  workspaceSelect: {
    position: "relative",
    display: "block",
    minWidth: 0,
    padding: 0,
    borderWidth: 0,
    borderStyle: "none",
    backgroundColor: "transparent",
    // The icon and chevron inherit this colour, which is how the old
    // `.workspace-select:hover .icon` rules reached them.
    color: "light-dark(#6b6b6b, #a3a3a3)",
    ":hover": {
      color: "light-dark(#111111, #f5f5f5)",
    },
    ":focus-within": {
      color: "light-dark(#111111, #f5f5f5)",
    },
  },
  selectIcon: {
    position: "absolute",
    top: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    pointerEvents: "none",
    left: "var(--grafy-rail-icon-center)",
    transform: "translate(-50%, -50%)",
    transition: "color 140ms ease",
  },
  selectIconSvg: {
    width: "var(--grafy-rail-icon)",
    height: "var(--grafy-rail-icon)",
    maxWidth: "none",
  },
  selectChevron: {
    position: "absolute",
    top: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    pointerEvents: "none",
    right: "8px",
    transform: "translateY(-50%)",
    opacity: "var(--grafy-rail-copy)",
    transition: "opacity 140ms ease var(--grafy-rail-copy-delay)",
    "@media (prefers-reduced-motion: reduce)": {
      transition: "none",
    },
    "@media (max-width: 620px)": {
      opacity: "1",
    },
  },
  selectChevronSvg: {
    width: "12px",
    height: "12px",
    maxWidth: "none",
  },

  /**
   * The rail's face on the kit `Select`, passed as `xstyle`. The old unlayered
   * `.grafy-workspace-rail__workspace-select select` rules in globals.css are
   * deleted; this replaces them, including the icon inset, the 36px height,
   * the collapsed transparency (React state and the 621–860px range), and the
   * 44px phone row at 620px.
   */
  workspaceSelectControl: {
    appearance: "none",
    width: "100%",
    height: "36px",
    paddingBlock: 0,
    paddingInlineStart:
      "calc(var(--grafy-rail-icon-center) + var(--grafy-rail-icon) / 2 + 10px)",
    paddingInlineEnd: "28px",
    overflow: "hidden",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "light-dark(#e8e8e8, #2a2a2a)",
    borderRadius: "8px",
    outline: {
      default: "none",
      ":focus-visible": "none",
    },
    backgroundColor: "light-dark(#fafafa, #171717)",
    color: "light-dark(#111111, #f5f5f5)",
    fontFamily: "inherit",
    fontSize: "13px",
    fontWeight: 500,
    textAlign: "left",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    cursor: "pointer",
    // `color-scheme: inherit` from the old rule: the property inherits, so the
    // page's `:root { color-scheme: light dark }` already reaches the control.
    transitionProperty: "background-color, border-color, color",
    transitionDuration: {
      default: "140ms",
      "@media (prefers-reduced-motion: reduce)": "0s",
    },
    transitionTimingFunction: "ease",
    ":hover:not(:disabled)": {
      borderColor: "light-dark(#d0d0d0, #3a3a3a)",
      backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
    },
    ":focus": {
      borderColor: "light-dark(#111111, #f5f5f5)",
      backgroundColor: "light-dark(#ffffff, #111111)",
    },
    ":focus-visible": {
      borderColor: "light-dark(#111111, #f5f5f5)",
      backgroundColor: "light-dark(#ffffff, #111111)",
    },
    // Collapsed rail between 621px and 860px (at 620px the phone block below
    // restores the visible chrome).
    "@media (min-width: 621px) and (max-width: 860px)": {
      color: "transparent",
      borderColor: "transparent",
      backgroundColor: "transparent",
      paddingInlineEnd: "var(--grafy-rail-item-pad)",
      ":hover:not(:disabled)": {
        backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
      },
      ":focus": {
        backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
      },
      ":focus-visible": {
        backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
      },
    },
    "@media (max-width: 620px)": {
      minHeight: "44px",
      color: "light-dark(#111111, #f5f5f5)",
      borderColor: "light-dark(#e8e8e8, #2a2a2a)",
      backgroundColor: "light-dark(#fafafa, #171717)",
      paddingInlineEnd: "32px",
    },
  },
  /** Collapsed rail (React state) at any width above 620px. */
  workspaceSelectCollapsed: {
    color: "transparent",
    borderColor: "transparent",
    backgroundColor: "transparent",
    paddingInlineEnd: "var(--grafy-rail-item-pad)",
    ":hover:not(:disabled)": {
      backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
    },
    ":focus": {
      backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
    },
    ":focus-visible": {
      backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
    },
  },

  badge: {
    minWidth: "18px",
    marginLeft: "auto",
    padding: "1px 5px",
    borderRadius: "999px",
    backgroundColor: "light-dark(#111111, #f5f5f5)",
    color: "light-dark(#ffffff, #111111)",
    fontSize: "10px",
    lineHeight: "16px",
    textAlign: "center",
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
    borderTopColor: "light-dark(#d9d9d9, #2a2a2a)",
  },
  railAccount: {
    borderWidth: 0,
    borderStyle: "none",
    backgroundColor: "transparent",
    color: "light-dark(#6b6b6b, #a3a3a3)",
    cursor: "pointer",
    width: "100%",
    display: "flex",
    alignItems: "center",
    gap: "10px",
    padding: "6px var(--grafy-rail-avatar-pad)",
    overflow: "hidden",
    borderRadius: "8px",
    textAlign: "left",
    transition: "background-color 140ms ease",
    ":hover:not(:disabled)": {
      backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
    },
    "[data-popup-open]": {
      backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
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
    borderRadius: "7px",
    backgroundColor: "light-dark(#111111, #f5f5f5)",
    color: "light-dark(#ffffff, #111111)",
    fontFamily: "var(--font-geist-sans)",
    fontSize: "11px",
    fontWeight: 500,
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
    color: "light-dark(#111111, #f5f5f5)",
    fontSize: "13px",
    fontWeight: 500,
    lineHeight: 1.3,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  accountEmail: {
    overflow: "hidden",
    color: "light-dark(#6b6b6b, #8a8a8a)",
    fontSize: "11px",
    lineHeight: 1.3,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },

  accountPositioner: {
    zIndex: 80,
  },
  accountMenu: {
    minWidth: "148px",
    padding: "6px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: "light-dark(#d9d9d9, #333333)",
    borderRadius: "8px",
    backgroundColor: "light-dark(#ffffff, #1a1a1a)",
    color: "light-dark(#111111, #f5f5f5)",
    boxShadow:
      "0 8px 24px light-dark(rgba(17, 17, 17, 0.08), rgba(0, 0, 0, 0.4))",
  },
  accountMenuItem: {
    width: "100%",
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "8px 10px",
    borderWidth: 0,
    borderStyle: "none",
    borderRadius: "6px",
    backgroundColor: "transparent",
    color: "light-dark(#111111, #f5f5f5)",
    cursor: "pointer",
    fontSize: "13px",
    textAlign: "left",
    ":hover:not(:disabled)": {
      backgroundColor: "light-dark(#f4f4f4, #222222)",
    },
    "@media (max-width: 620px)": {
      minHeight: "44px",
    },
  },
  accountMenuItemDanger: {
    color: "light-dark(#dc5c5c, #f87171)",
  },

  graphRow: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) auto",
    alignItems: "center",
    minWidth: 0,
    borderRadius: "6px",
    ":hover": {
      backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
    },
  },
  graphRowActive: {
    backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
  },
  /** Keeps the row's own hover background from painting under the item. */
  graphRowItem: {
    backgroundColor: "transparent",
    ":hover:not(:disabled)": {
      backgroundColor: "transparent",
    },
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
    borderRadius: "6px",
    backgroundColor: "transparent",
    color: "light-dark(#6b6b6b, #8a8a8a)",
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
      backgroundColor: "light-dark(#ededed, #242424)",
      color: "light-dark(#111111, #f5f5f5)",
    },
    // The phone row: the panel's trigger grows to 44px at 620px. (Rail rows
    // are hidden inside the closed drawer at 620px, so this is inert there.)
    "@media (max-width: 620px)": {
      width: "44px",
      height: "44px",
      marginRight: 0,
      opacity: 1,
    },
  },
});
