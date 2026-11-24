import * as stylex from "@stylexjs/stylex";

/**
 * Global design tokens for Grafy.
 *
 * Cool neutral studio palette: crisp white floating plates over a subtle mist
 * canvas ground, whisper alpha hairlines, and refined charcoal ink. Color
 * tokens use CSS `light-dark()` so the active palette follows
 * `document.documentElement.style.colorScheme` (set by ThemeProvider).
 */
export const tokens = stylex.defineVars({
  // surfaces
  colorBg: "light-dark(#F6F7F9, #0F1114)",
  colorSurface: "light-dark(#FFFFFF, #171A1F)",
  colorSurfaceRaised: "light-dark(#F1F3F6, #1F232A)",
  // A well the controls sit in. It has to read as recessed in both palettes, or
  // a borderless control on it disappears: #F1F3F6 is `colorSurfaceRaised`.
  colorSurfaceSunken: "light-dark(#E9ECF0, #121519)",
  /**
   * The pill that lifts out of a sunken well — the active segment of a
   * `SegmentedControl`. Crisp white in light mode and lifted above the well in
   * dark mode, unlike `colorChrome` (which sank into `#222222`) or
   * `colorSurfaceRaised` (which stays grey in light mode).
   */
  colorSurfaceElevated: "light-dark(#FFFFFF, #2A2F38)",
  colorSurfaceMuted: "light-dark(#F6F7F9, #15181D)",
  colorChrome: "light-dark(#FFFFFF, #171A1F)",
  // primary dark rail (always dark charcoal; deepens in dark mode)
  colorRailBg: "light-dark(#14171B, #0B0D10)",
  colorRailSurface: "light-dark(#1D2128, #13161B)",
  colorRailActive:
    "light-dark(rgba(255, 255, 255, 0.11), rgba(255, 255, 255, 0.09))",
  colorRailHover:
    "light-dark(rgba(255, 255, 255, 0.065), rgba(255, 255, 255, 0.055))",
  colorRailBorder:
    "light-dark(rgba(255, 255, 255, 0.09), rgba(255, 255, 255, 0.08))",
  colorRailText: "light-dark(#E5E9F0, #E5E9F0)",
  colorRailTextEmphasis: "light-dark(#FFFFFF, #FFFFFF)",
  colorRailMuted: "light-dark(#949CA9, #87909E)",
  colorRailSubtle: "light-dark(#6C7484, #636B7A)",
  // secondary subsidebar (gray in light mode, depth-1 slate in dark mode)
  colorSubrailBg: "light-dark(#F3F4F6, #12151A)",
  colorSubrailActive: "light-dark(#FFFFFF, #1F242D)",
  colorSubrailHover:
    "light-dark(rgba(15, 23, 42, 0.045), rgba(255, 255, 255, 0.055))",
  colorSubrailBorder:
    "light-dark(rgba(15, 23, 42, 0.085), rgba(255, 255, 255, 0.08))",
  // borders — whisper hairlines so elevation and typography do the grouping
  colorBorder: "light-dark(rgba(15, 23, 42, 0.09), rgba(255, 255, 255, 0.1))",
  colorBorderStrong:
    "light-dark(rgba(15, 23, 42, 0.2), rgba(255, 255, 255, 0.22))",
  colorDivider:
    "light-dark(rgba(15, 23, 42, 0.065), rgba(255, 255, 255, 0.075))",
  // text
  colorText: "light-dark(#1F2328, #ECEFF4)",
  colorTextEmphasis: "light-dark(#111317, #FFFFFF)",
  colorMuted: "light-dark(#5E6673, #9AA2B1)",
  colorSubtle: "light-dark(#7A828F, #7D8594)",
  colorTextDisabled: "light-dark(#B0B7C3, #4D535E)",
  colorOnAccent: "light-dark(#FFFFFF, #111317)",
  // interaction
  colorHover: "light-dark(rgba(15, 23, 42, 0.04), rgba(255, 255, 255, 0.06))",
  colorHoverStrong:
    "light-dark(rgba(15, 23, 42, 0.075), rgba(255, 255, 255, 0.1))",
  colorDangerHover:
    "light-dark(rgba(220, 92, 92, 0.1), rgba(232, 105, 105, 0.12))",
  colorWarningSoft:
    "light-dark(rgba(201, 146, 15, 0.1), rgba(251, 191, 36, 0.12))",
  // accents — refined charcoal ink, not a brand hue
  colorAccent: "light-dark(#24292F, #EEF1F6)",
  colorAccentHover: "light-dark(#353C45, #DCE1EA)",
  colorAccentDisabled: "light-dark(#E2E6EC, #292E36)",
  colorAccentSoft:
    "light-dark(rgba(36, 41, 47, 0.06), rgba(238, 241, 246, 0.1))",
  colorAccentBorder:
    "light-dark(rgba(36, 41, 47, 0.28), rgba(238, 241, 246, 0.34))",
  colorProjectionPath: "light-dark(#24292F, #D9DFE8)",
  // status (functional, not brand)
  colorSuccess: "light-dark(#2a9d7c, #43c59e)",
  colorWarning: "light-dark(#c9920f, #fbbf24)",
  colorDanger: "light-dark(#dc5c5c, #f87171)",
  colorInfo: "light-dark(#4a8fd4, #60a5fa)",
  // canvas
  colorGrid: "light-dark(rgba(15, 23, 42, 0.045), rgba(255, 255, 255, 0.045))",
  colorFlowControls:
    "light-dark(rgba(255, 255, 255, 0.92), rgba(23, 26, 31, 0.9))",
  // elevation — soft ambient depth matching floating canvas cards
  /**
   * Three layers keep the layer count equal to `shadowNodeRaised` so the pickup
   * cross-fade interpolates instead of falling back to a discrete swap.
   */
  shadowNode:
    "0 1px 2px light-dark(rgba(15, 23, 42, 0.04), rgba(0, 0, 0, 0.35)), 0 4px 12px light-dark(rgba(15, 23, 42, 0.04), rgba(0, 0, 0, 0.22)), 0 0 0 0 light-dark(rgba(15, 23, 42, 0), rgba(0, 0, 0, 0))",
  /**
   * Near-card pickup shadow. Three layers match `shadowNodeDragged` so the
   * shadow transition stays smooth.
   */
  shadowNodeRaised:
    "0 2px 6px light-dark(rgba(15, 23, 42, 0.045), rgba(0, 0, 0, 0.4)), 0 12px 28px light-dark(rgba(15, 23, 42, 0.07), rgba(0, 0, 0, 0.32)), 0 14px 32px light-dark(rgba(15, 23, 42, 0), rgba(0, 0, 0, 0))",
  /**
   * Active-tier ground pool (selected or held): a soft separation shadow
   * painted by a geometry-neutral layer beneath the card. Three layers keep
   * the tier cross-fade smooth.
   */
  shadowNodeActive:
    "0 4px 8px light-dark(rgba(15, 23, 42, 0.06), rgba(0, 0, 0, 0.28)), 0 10px 20px light-dark(rgba(15, 23, 42, 0.08), rgba(0, 0, 0, 0.32)), 0 18px 36px light-dark(rgba(15, 23, 42, 0.06), rgba(0, 0, 0, 0.26))",
  /**
   * Dragged-tier ground pool: deeper and wider so the node reads as carried
   * above the canvas.
   */
  shadowNodeDragged:
    "0 12px 24px light-dark(rgba(15, 23, 42, 0.1), rgba(0, 0, 0, 0.4)), 0 28px 52px light-dark(rgba(15, 23, 42, 0.15), rgba(0, 0, 0, 0.45)), 0 60px 110px light-dark(rgba(15, 23, 42, 0.14), rgba(0, 0, 0, 0.4))",
  /** Floating chrome (menus, toolbars) — crisp ring + light drop. */
  shadowNodeSelected:
    "0 0 0 1px light-dark(#24292F, #EEF1F6), 0 1px 2px light-dark(rgba(15, 23, 42, 0.08), rgba(0, 0, 0, 0.4))",
  // geometry — Grafy radii
  radiusSm: "6px",
  radiusMd: "8px",
  radiusLg: "12px",
  space1: "4px",
  space2: "8px",
  space3: "12px",
  space4: "16px",
  space5: "20px",
  space6: "24px",
  fontSizeXs: "11px",
  fontSizeSm: "12px",
  fontSizeMd: "13px",
  fontSizeLg: "1.125rem",
  fontSizeXl: "1.5rem",
});
