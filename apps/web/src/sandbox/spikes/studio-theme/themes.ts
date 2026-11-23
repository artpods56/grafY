import * as stylex from "@stylexjs/stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";

/**
 * Comparison themes for `/sandbox/studio-theme`.
 *
 * `Studio (Charcoal)` is now the default token set in
 * `src/lib/stylex/tokens.stylex.ts`. These overrides keep the previous stark
 * monochrome palette and an emerald-accent alternative available for A/B checks.
 */

export const previousMonochromeTheme = stylex.createTheme(tokens, {
  colorBg: "light-dark(#FFFFFF, #111111)",
  colorSurface: "light-dark(#FAFAFA, #1A1A1A)",
  colorSurfaceRaised: "light-dark(#F4F4F4, #222222)",
  colorSurfaceSunken: "light-dark(#ECECEC, #141414)",
  colorSurfaceElevated: "light-dark(#FFFFFF, #2B2B2B)",
  colorSurfaceMuted: "light-dark(#FAFAFA, #181818)",
  colorChrome: "light-dark(#FFFFFF, #1A1A1A)",
  colorBorder: "light-dark(#D9D9D9, #333333)",
  colorBorderStrong: "light-dark(#6B6B6B, #555555)",
  colorDivider: "light-dark(#D9D9D9, #2A2A2A)",
  colorText: "light-dark(#111111, #F5F5F5)",
  colorTextEmphasis: "light-dark(#111111, #FFFFFF)",
  colorMuted: "light-dark(#6B6B6B, #A3A3A3)",
  colorSubtle: "light-dark(#6B6B6B, #8A8A8A)",
  colorTextDisabled: "light-dark(#D9D9D9, #555555)",
  colorOnAccent: "light-dark(#FFFFFF, #111111)",
  colorHover: "light-dark(rgba(17, 17, 17, 0.05), rgba(255, 255, 255, 0.07))",
  colorHoverStrong:
    "light-dark(rgba(17, 17, 17, 0.08), rgba(255, 255, 255, 0.1))",
  colorAccent: "light-dark(#111111, #FFFFFF)",
  colorAccentHover: "light-dark(#2A2A2A, #E8E8E8)",
  colorAccentDisabled: "light-dark(#D9D9D9, #333333)",
  colorAccentSoft:
    "light-dark(rgba(17, 17, 17, 0.06), rgba(255, 255, 255, 0.1))",
  colorAccentBorder:
    "light-dark(rgba(17, 17, 17, 0.35), rgba(255, 255, 255, 0.4))",
  colorGrid: "light-dark(rgba(17, 17, 17, 0.06), rgba(255, 255, 255, 0.05))",
  colorFlowControls: "light-dark(#FFFFFF, rgba(26, 26, 26, 0.94))",
  shadowNode:
    "0 1px 2px light-dark(rgba(17, 17, 17, 0.06), rgba(0, 0, 0, 0.35)), 0 0 0 0 light-dark(rgba(17, 17, 17, 0), rgba(0, 0, 0, 0)), 0 0 0 0 light-dark(rgba(17, 17, 17, 0), rgba(0, 0, 0, 0))",
  shadowNodeRaised:
    "0 1px 2px light-dark(rgba(17, 17, 17, 0.06), rgba(0, 0, 0, 0.4)), 0 6px 16px light-dark(rgba(17, 17, 17, 0.07), rgba(0, 0, 0, 0.3)), 0 14px 32px light-dark(rgba(17, 17, 17, 0), rgba(0, 0, 0, 0))",
  radiusSm: "4px",
  radiusMd: "6px",
  radiusLg: "8px",
});

export const studioEmeraldTheme = stylex.createTheme(tokens, {
  colorOnAccent: "light-dark(#FFFFFF, #0D1613)",
  colorAccent: "light-dark(#238A6C, #3EC49D)",
  colorAccentHover: "light-dark(#1D775C, #52D1AC)",
  colorAccentDisabled: "light-dark(#D7E6E0, #233831)",
  colorAccentSoft:
    "light-dark(rgba(35, 138, 108, 0.09), rgba(62, 196, 157, 0.14))",
  colorAccentBorder:
    "light-dark(rgba(35, 138, 108, 0.42), rgba(62, 196, 157, 0.48))",
});
