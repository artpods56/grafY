import * as stylex from "@stylexjs/stylex";
import { tokens } from "@/lib/stylex/tokens.stylex";

/**
 * Editable visual directions for iterating on grafY's app chrome and UI kit.
 *
 * Every override flows through `tokens` (`src/lib/stylex/tokens.stylex.ts`), so
 * changing a single value here updates `Button`, `Field`, `Select`, `Switch`,
 * `Checkbox`, `Slider`, `SegmentedControl`, `Surface`, `Notice`, `Menu`, and
 * `Dialog` simultaneously in `/sandbox/studio-theme`.
 */

/**
 * Canvas-aligned cool studio palette:
 * - Whisper-cool mist ground (`#F6F7F9`) with pure crisp white floating plates (`#FFFFFF`)
 * - Hairline alpha borders instead of heavy `#D9D9D9` boxes
 * - Softer ambient card elevation + slightly rounder `6/8/12px` corners
 * - Refined charcoal ink (`#1F2328`) instead of stark `#111111`
 */
export const studioTheme = stylex.createTheme(tokens, {
  // surfaces
  colorBg: "light-dark(#F6F7F9, #0F1114)",
  colorSurface: "light-dark(#FFFFFF, #171A1F)",
  colorSurfaceRaised: "light-dark(#F1F3F6, #1F232A)",
  colorSurfaceSunken: "light-dark(#E9ECF0, #121519)",
  colorSurfaceElevated: "light-dark(#FFFFFF, #2A2F38)",
  colorSurfaceMuted: "light-dark(#F6F7F9, #15181D)",
  colorChrome: "light-dark(#FFFFFF, #171A1F)",
  // borders — whisper hairlines so elevation & typography do the grouping
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
  // accent — refined charcoal (zero pure-black harshness)
  colorAccent: "light-dark(#24292F, #EEF1F6)",
  colorAccentHover: "light-dark(#353C45, #DCE1EA)",
  colorAccentDisabled: "light-dark(#E2E6EC, #292E36)",
  colorAccentSoft:
    "light-dark(rgba(36, 41, 47, 0.06), rgba(238, 241, 246, 0.1))",
  colorAccentBorder:
    "light-dark(rgba(36, 41, 47, 0.28), rgba(238, 241, 246, 0.34))",
  // canvas & chrome elevation — soft diffused depth matching the node cards
  colorGrid: "light-dark(rgba(15, 23, 42, 0.045), rgba(255, 255, 255, 0.045))",
  colorFlowControls:
    "light-dark(rgba(255, 255, 255, 0.92), rgba(23, 26, 31, 0.9))",
  shadowNode:
    "0 1px 2px light-dark(rgba(15, 23, 42, 0.04), rgba(0, 0, 0, 0.35)), 0 4px 12px light-dark(rgba(15, 23, 42, 0.04), rgba(0, 0, 0, 0.22)), 0 0 0 0 light-dark(rgba(15, 23, 42, 0), rgba(0, 0, 0, 0))",
  shadowNodeRaised:
    "0 2px 6px light-dark(rgba(15, 23, 42, 0.045), rgba(0, 0, 0, 0.4)), 0 12px 28px light-dark(rgba(15, 23, 42, 0.07), rgba(0, 0, 0, 0.32)), 0 0 0 0 light-dark(rgba(15, 23, 42, 0), rgba(0, 0, 0, 0))",
  // geometry — softer radii matching the canvas cards
  radiusSm: "6px",
  radiusMd: "8px",
  radiusLg: "12px",
});

/**
 * Same cool studio surface system, with the canvas's own emerald-sage port
 * colour (`#238A6C` / `#3EC49D`) promoted to the primary interactive accent.
 */
export const studioEmeraldTheme = stylex.createTheme(tokens, {
  colorBg: "light-dark(#F6F7F9, #0F1114)",
  colorSurface: "light-dark(#FFFFFF, #171A1F)",
  colorSurfaceRaised: "light-dark(#F1F3F6, #1F232A)",
  colorSurfaceSunken: "light-dark(#E9ECF0, #121519)",
  colorSurfaceElevated: "light-dark(#FFFFFF, #2A2F38)",
  colorSurfaceMuted: "light-dark(#F6F7F9, #15181D)",
  colorChrome: "light-dark(#FFFFFF, #171A1F)",
  colorBorder: "light-dark(rgba(15, 23, 42, 0.09), rgba(255, 255, 255, 0.1))",
  colorBorderStrong:
    "light-dark(rgba(15, 23, 42, 0.2), rgba(255, 255, 255, 0.22))",
  colorDivider:
    "light-dark(rgba(15, 23, 42, 0.065), rgba(255, 255, 255, 0.075))",
  colorText: "light-dark(#1F2328, #ECEFF4)",
  colorTextEmphasis: "light-dark(#111317, #FFFFFF)",
  colorMuted: "light-dark(#5E6673, #9AA2B1)",
  colorSubtle: "light-dark(#7A828F, #7D8594)",
  colorTextDisabled: "light-dark(#B0B7C3, #4D535E)",
  colorOnAccent: "light-dark(#FFFFFF, #0D1613)",
  colorHover: "light-dark(rgba(15, 23, 42, 0.04), rgba(255, 255, 255, 0.06))",
  colorHoverStrong:
    "light-dark(rgba(15, 23, 42, 0.075), rgba(255, 255, 255, 0.1))",
  colorAccent: "light-dark(#238A6C, #3EC49D)",
  colorAccentHover: "light-dark(#1D775C, #52D1AC)",
  colorAccentDisabled: "light-dark(#D7E6E0, #233831)",
  colorAccentSoft:
    "light-dark(rgba(35, 138, 108, 0.09), rgba(62, 196, 157, 0.14))",
  colorAccentBorder:
    "light-dark(rgba(35, 138, 108, 0.42), rgba(62, 196, 157, 0.48))",
  colorGrid: "light-dark(rgba(15, 23, 42, 0.045), rgba(255, 255, 255, 0.045))",
  colorFlowControls:
    "light-dark(rgba(255, 255, 255, 0.92), rgba(23, 26, 31, 0.9))",
  shadowNode:
    "0 1px 2px light-dark(rgba(15, 23, 42, 0.04), rgba(0, 0, 0, 0.35)), 0 4px 12px light-dark(rgba(15, 23, 42, 0.04), rgba(0, 0, 0, 0.22)), 0 0 0 0 light-dark(rgba(15, 23, 42, 0), rgba(0, 0, 0, 0))",
  shadowNodeRaised:
    "0 2px 6px light-dark(rgba(15, 23, 42, 0.045), rgba(0, 0, 0, 0.4)), 0 12px 28px light-dark(rgba(15, 23, 42, 0.07), rgba(0, 0, 0, 0.32)), 0 0 0 0 light-dark(rgba(15, 23, 42, 0), rgba(0, 0, 0, 0))",
  radiusSm: "6px",
  radiusMd: "8px",
  radiusLg: "12px",
});
