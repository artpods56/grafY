import * as stylex from "@stylexjs/stylex";

/**
 * Global design tokens for Grafy.
 *
 * Monochrome, graph-native system: near-black ink, white surfaces, neutral
 * gray hierarchy. Color tokens use CSS `light-dark()` so the active palette
 * follows the resolved `color-scheme` on `<html>` (`light` or `dark` — never
 * the dual `light dark` value, which makes `light-dark()` inside these
 * variables compute to transparent).
 */
export const tokens = stylex.defineVars({
  // surfaces
  colorBg: "light-dark(#FFFFFF, #111111)",
  colorSurface: "light-dark(#FAFAFA, #1A1A1A)",
  colorSurfaceRaised: "light-dark(#F4F4F4, #222222)",
  colorSurfaceSunken: "light-dark(#F4F4F4, #1A1A1A)",
  colorSurfaceMuted: "light-dark(#FAFAFA, #181818)",
  colorChrome: "light-dark(#FFFFFF, #1A1A1A)",
  // borders
  colorBorder: "light-dark(#D9D9D9, #333333)",
  colorBorderStrong: "light-dark(#6B6B6B, #555555)",
  colorDivider: "light-dark(#D9D9D9, #2A2A2A)",
  // text
  colorText: "light-dark(#111111, #F5F5F5)",
  colorTextEmphasis: "light-dark(#111111, #FFFFFF)",
  colorMuted: "light-dark(#6B6B6B, #A3A3A3)",
  colorSubtle: "light-dark(#6B6B6B, #8A8A8A)",
  colorTextDisabled: "light-dark(#D9D9D9, #555555)",
  colorOnAccent: "light-dark(#FFFFFF, #111111)",
  // interaction
  colorHover: "light-dark(rgba(17, 17, 17, 0.05), rgba(255, 255, 255, 0.07))",
  colorHoverStrong: "light-dark(rgba(17, 17, 17, 0.08), rgba(255, 255, 255, 0.1))",
  colorDangerHover: "light-dark(rgba(220, 92, 92, 0.1), rgba(232, 105, 105, 0.12))",
  // accents — primary ink, not a brand hue
  colorAccent: "light-dark(#111111, #FFFFFF)",
  colorAccentHover: "light-dark(#2A2A2A, #E8E8E8)",
  colorAccentDisabled: "light-dark(#D9D9D9, #333333)",
  colorAccentSoft: "light-dark(rgba(17, 17, 17, 0.06), rgba(255, 255, 255, 0.1))",
  colorAccentBorder: "light-dark(rgba(17, 17, 17, 0.35), rgba(255, 255, 255, 0.4))",
  colorProjectionPath: "light-dark(#111111, #D9D9D9)",
  // status (functional, not brand)
  colorSuccess: "light-dark(#2a9d7c, #43c59e)",
  colorWarning: "light-dark(#c9920f, #fbbf24)",
  colorDanger: "light-dark(#dc5c5c, #f87171)",
  colorInfo: "light-dark(#4a8fd4, #60a5fa)",
  // canvas
  colorGrid: "light-dark(rgba(17, 17, 17, 0.06), rgba(255, 255, 255, 0.05))",
  colorFlowControls: "light-dark(#FFFFFF, rgba(26, 26, 26, 0.94))",
  // elevation — prefer borders; keep shadows minimal for overlays only
  /**
   * Two transparent padding layers keep the layer count equal to
   * `shadowNodeRaised` so the pickup cross-fade interpolates instead of
   * falling back to a discrete swap.
   */
  shadowNode:
    "0 1px 2px light-dark(rgba(17, 17, 17, 0.06), rgba(0, 0, 0, 0.35)), 0 0 0 0 light-dark(rgba(17, 17, 17, 0), rgba(0, 0, 0, 0)), 0 0 0 0 light-dark(rgba(17, 17, 17, 0), rgba(0, 0, 0, 0))",
  /**
   * Near-card pickup shadow. Three layers match `shadowNodeDragged` so the
   * shadow transition stays smooth.
   */
  shadowNodeRaised:
    "0 1px 2px light-dark(rgba(17, 17, 17, 0.06), rgba(0, 0, 0, 0.4)), 0 6px 16px light-dark(rgba(17, 17, 17, 0.07), rgba(0, 0, 0, 0.3)), 0 14px 32px light-dark(rgba(17, 17, 17, 0), rgba(0, 0, 0, 0))",
  /**
   * Active-tier ground pool (selected or held): a soft separation shadow
   * painted by a geometry-neutral layer beneath the card. Three layers keep
   * the tier cross-fade smooth.
   */
  shadowNodeActive:
    "0 4px 8px light-dark(rgba(17, 17, 17, 0.07), rgba(0, 0, 0, 0.28)), 0 10px 20px light-dark(rgba(17, 17, 17, 0.09), rgba(0, 0, 0, 0.32)), 0 18px 36px light-dark(rgba(17, 17, 17, 0.07), rgba(0, 0, 0, 0.26))",
  /**
   * Dragged-tier ground pool: deeper and wider so the node reads as carried
   * above the canvas.
   */
  shadowNodeDragged:
    "0 12px 24px light-dark(rgba(17, 17, 17, 0.12), rgba(0, 0, 0, 0.4)), 0 28px 52px light-dark(rgba(17, 17, 17, 0.18), rgba(0, 0, 0, 0.45)), 0 60px 110px light-dark(rgba(17, 17, 17, 0.16), rgba(0, 0, 0, 0.4))",
  /** Floating chrome (menus, toolbars) — hard edge + light drop. */
  shadowNodeSelected:
    "0 0 0 1px light-dark(#111111, #FFFFFF), 0 1px 2px light-dark(rgba(17, 17, 17, 0.08), rgba(0, 0, 0, 0.4))",
  // geometry — Grafy radii
  radiusSm: "4px",
  radiusMd: "6px",
  radiusLg: "8px",
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
