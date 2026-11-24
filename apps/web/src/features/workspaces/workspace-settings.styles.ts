import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

const MONO =
  "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace";

/**
 * Tier 2 (gray subsidebar) + Tier 3 (clean surface) single-page Settings styles.
 */
export const workspaceSettingsStyles = stylex.create({
  page: {
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
    backgroundColor: tokens.colorSurface,
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
    zIndex: 20,
    flexShrink: 0,
    minHeight: "56px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "16px",
    flexWrap: "wrap",
    padding: {
      default: "10px 28px",
      "@media (max-width: 860px)": "10px 20px",
      "@media (max-width: 620px)": "12px 16px",
    },
    backgroundColor: tokens.colorSurface,
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  headerTitle: {
    margin: 0,
    color: tokens.colorTextEmphasis,
    fontSize: "16px",
    fontWeight: 600,
    letterSpacing: "-0.01em",
    lineHeight: 1.3,
  },
  workspacePill: {
    display: "inline-flex",
    alignItems: "center",
    height: "24px",
    paddingInline: "10px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
    whiteSpace: "nowrap",
    maxWidth: "240px",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },

  body: {
    flex: "1 0 auto",
    display: "grid",
    gridTemplateColumns: {
      default: "220px minmax(0, 1fr)",
      "@media (max-width: 860px)": "minmax(0, 1fr)",
    },
    alignItems: "stretch",
    minHeight: 0,
  },

  subrail: {
    position: "sticky",
    top: {
      default: "56px",
      "@media (max-width: 620px)": "0",
    },
    zIndex: 15,
    alignSelf: "start",
    height: {
      default: "calc(100svh - 56px)",
      "@media (max-width: 860px)": "auto",
    },
    overflowY: { default: "auto", "@media (max-width: 860px)": "visible" },
    overflowX: { default: "hidden", "@media (max-width: 860px)": "auto" },
    backgroundColor: tokens.colorSubrailBg,
    borderRightWidth: { default: "1px", "@media (max-width: 860px)": "0" },
    borderRightStyle: "solid",
    borderRightColor: tokens.colorSubrailBorder,
    borderBottomWidth: { default: "0", "@media (max-width: 860px)": "1px" },
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorSubrailBorder,
    padding: {
      default: "20px 12px",
      "@media (max-width: 860px)": "8px 16px",
    },
  },
  subrailNav: {
    display: {
      default: "grid",
      "@media (max-width: 860px)": "flex",
    },
    alignItems: {
      default: "stretch",
      "@media (max-width: 860px)": "center",
    },
    gap: {
      default: "2px",
      "@media (max-width: 860px)": "6px",
    },
    minWidth: {
      default: "0",
      "@media (max-width: 860px)": "max-content",
    },
  },
  subrailItem: {
    display: "flex",
    alignItems: "center",
    gap: "9px",
    flexShrink: 0,
    width: {
      default: "100%",
      "@media (max-width: 860px)": "auto",
    },
    minHeight: {
      default: "34px",
      "@media (max-width: 620px)": "44px",
    },
    padding: {
      default: "7px 10px",
      "@media (max-width: 860px)": "6px 12px",
    },
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: "transparent",
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorSubrailHover,
    },
    color: {
      default: tokens.colorMuted,
      ":hover:not(:disabled)": tokens.colorText,
    },
    fontSize: tokens.fontSizeMd,
    fontWeight: 450,
    textAlign: "left",
    whiteSpace: "nowrap",
    cursor: "pointer",
    outline: {
      default: "none",
      ":focus-visible": `2px solid ${tokens.colorAccentBorder}`,
    },
    outlineOffset: "-2px",
    transitionProperty: "background-color, color, border-color",
    transitionDuration: {
      default: "120ms",
      "@media (prefers-reduced-motion: reduce)": "0ms",
    },
  },
  subrailItemActive: {
    backgroundColor: {
      default: tokens.colorSubrailActive,
      ":hover:not(:disabled)": tokens.colorSubrailActive,
    },
    borderColor: tokens.colorSubrailBorder,
    boxShadow: tokens.shadowNode,
    color: {
      default: tokens.colorTextEmphasis,
      ":hover:not(:disabled)": tokens.colorTextEmphasis,
    },
    fontWeight: 550,
  },
  subrailIcon: {
    flexShrink: 0,
  },

  main: {
    minWidth: 0,
    backgroundColor: tokens.colorSurface,
  },
  content: {
    width: "100%",
    maxWidth: "820px",
    padding: {
      default: "24px 40px 80px",
      "@media (max-width: 860px)": "20px 20px 56px",
      "@media (max-width: 620px)":
        "18px calc(16px + env(safe-area-inset-right)) calc(48px + env(safe-area-inset-bottom)) calc(16px + env(safe-area-inset-left))",
    },
  },

  section: {
    padding: "28px 0",
    borderBottomWidth: "1px",
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorDivider,
    scrollMarginTop: {
      default: "72px",
      "@media (max-width: 860px)": "124px",
      "@media (max-width: 620px)": "68px",
    },
  },
  sectionFirst: {
    paddingTop: "4px",
  },
  sectionLast: {
    borderBottomWidth: 0,
  },
  sectionHeading: {
    display: "flex",
    alignItems: "start",
    justifyContent: "space-between",
    gap: "20px",
    marginBottom: "18px",
  },
  headingIcon: {
    flex: "0 0 auto",
    color: tokens.colorSubtle,
    marginTop: "2px",
  },
  headingTitle: {
    margin: 0,
    color: tokens.colorTextEmphasis,
    fontSize: "16px",
    fontWeight: 600,
    letterSpacing: "-0.01em",
  },
  headingText: {
    margin: 0,
    marginTop: "4px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeMd,
    lineHeight: 1.5,
  },
  muted: {
    margin: 0,
    marginTop: "6px",
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeMd,
    lineHeight: 1.5,
  },

  details: {
    display: "grid",
    margin: 0,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    overflow: "hidden",
  },
  detailsRow: {
    display: "grid",
    gridTemplateColumns: {
      default: "minmax(0, 1fr) auto",
      "@media (max-width: 620px)": "minmax(0, 1fr)",
    },
    alignItems: "center",
    gap: "8px 24px",
    padding: "14px 16px",
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: {
      default: tokens.colorDivider,
      ":first-child": "transparent",
    },
    backgroundColor: tokens.colorSurface,
  },
  detailsLabelGroup: {
    display: "grid",
    gap: "2px",
    minWidth: 0,
  },
  detailsTerm: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 550,
  },
  detailsHint: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.45,
  },
  detailsValue: {
    margin: 0,
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 500,
    textTransform: "capitalize",
  },
  detailsBadge: {
    display: "inline-flex",
    alignItems: "center",
    height: "24px",
    paddingInline: "10px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorDivider,
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 500,
    textTransform: "capitalize",
  },

  sectionActionCard: {
    display: "flex",
    alignItems: {
      default: "center",
      "@media (max-width: 620px)": "stretch",
    },
    justifyContent: "space-between",
    flexDirection: {
      default: "row",
      "@media (max-width: 620px)": "column",
    },
    gap: "16px 24px",
    padding: "16px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorSurface,
  },
  sectionActionCopy: {
    display: "grid",
    gap: "2px",
    minWidth: 0,
  },
  sectionActionTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 550,
  },
  sectionActionText: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
  },
  /** The section action's own button: full width on a phone. Pass as `xstyle`. */
  action: {
    width: {
      default: "unset",
      "@media (max-width: 620px)": "100%",
    },
  },

  tokenFormCard: {
    padding: "16px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorBg,
  },
  tokenForm: {
    display: "grid",
    gridTemplateColumns: {
      default: "minmax(180px, 1fr) minmax(150px, 0.8fr) 128px auto",
      "@media (max-width: 860px)": "1fr 132px",
      "@media (max-width: 620px)": "1fr",
    },
    alignItems: "end",
    gap: "10px",
  },
  tokenFormButton: {
    width: {
      default: "unset",
      "@media (max-width: 860px)": "100%",
    },
  },
  /** The slot a token Notice sits in; a Notice brings no outer margin. */
  tokenMessage: {
    marginBlock: "12px",
  },
  tokenSecret: {
    display: "block",
    minWidth: 0,
    overflowWrap: "anywhere",
    marginTop: "8px",
    padding: "9px 10px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: `color-mix(in oklab, ${tokens.colorSuccess} 32%, transparent)`,
    borderRadius: tokens.radiusSm,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorTextEmphasis,
    fontFamily: MONO,
    fontSize: tokens.fontSizeSm,
    userSelect: "all",
  },
  tokenList: {
    display: "grid",
    marginTop: "16px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusLg,
    overflow: "hidden",
  },
  tokenRow: {
    display: "grid",
    gridTemplateColumns: {
      default: "minmax(180px, 0.85fr) minmax(220px, 1.15fr) 34px",
      "@media (max-width: 860px)": "minmax(0, 1fr) 34px",
    },
    alignItems: "center",
    gap: "14px 18px",
    minHeight: "62px",
    padding: "12px 16px",
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: {
      default: tokens.colorDivider,
      ":first-child": "transparent",
    },
    backgroundColor: tokens.colorSurface,
  },
  tokenRowMain: {
    minWidth: 0,
    display: "grid",
    gap: "4px",
  },
  tokenRowMainLine: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "8px",
  },
  tokenRowLabel: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 550,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  tokenRowPrefix: {
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: tokens.fontSizeXs,
  },
  tokenStatus: {
    padding: "2px 6px",
    borderRadius: "4px",
    backgroundColor: {
      default: tokens.colorSurfaceRaised,
      ":is([data-state='active'])": `color-mix(in oklab, ${tokens.colorSuccess} 14%, transparent)`,
    },
    color: {
      default: tokens.colorMuted,
      ":is([data-state='active'])": tokens.colorSuccess,
    },
    fontSize: "10px",
    fontWeight: 600,
    textTransform: "uppercase",
  },
  tokenMeta: {
    minWidth: 0,
    display: "grid",
    gap: "4px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    gridColumn: {
      default: "auto",
      "@media (max-width: 860px)": "1",
    },
    gridRow: {
      default: "auto",
      "@media (max-width: 860px)": "2",
    },
  },
  tokenMetaWhen: {
    display: "flex",
    alignItems: "center",
    gap: "5px",
  },
  /** The token row's revoke button: spans both rows from the 860px breakpoint down. */
  tokenRowAction: {
    gridColumn: {
      default: "auto",
      "@media (max-width: 860px)": "2",
    },
    gridRow: {
      default: "auto",
      "@media (max-width: 860px)": "1 / span 2",
    },
  },
  tokenEmpty: {
    margin: 0,
    padding: "16px",
    backgroundColor: tokens.colorSurface,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
  },
});
