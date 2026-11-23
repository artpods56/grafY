import * as stylex from "@stylexjs/stylex";

/**
 * The workspace settings screen's own layout, moved off the
 * `.grafy-workspace-settings` rules in `globals.css` onto StyleX.
 * `WorkspaceSettings`, `WorkspacePacks`, and `WorkspaceCredentials` share the
 * section contract from here; each component keeps the rest of its styles
 * beside its markup.
 */

const MONO =
  "var(--font-geist-mono), ui-monospace, SFMono-Regular, Menlo, monospace";

export const workspaceSettingsStyles = stylex.create({
  main: {
    maxWidth: "960px",
    minHeight: "100svh",
    margin: "0 auto",
    padding: {
      default: "40px 40px 72px calc(var(--grafy-rail-width, 200px) + 48px)",
      "@media (max-width: 860px)":
        "28px 18px 40px calc(var(--grafy-rail-width, 64px) + 16px)",
      "@media (max-width: 620px)":
        "calc(var(--grafy-mobile-page-top) + env(safe-area-inset-top)) calc(16px + env(safe-area-inset-right)) calc(40px + env(safe-area-inset-bottom)) calc(16px + env(safe-area-inset-left))",
    },
    transition: {
      default: "padding 180ms ease",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
  },
  header: {
    paddingBottom: "22px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: "light-dark(#d9d9d9, #2a2a2a)",
  },
  eyebrow: {
    color: "light-dark(#6b6b6b, #a3a3a3)",
    fontSize: "11px",
    fontWeight: 500,
    letterSpacing: "0.12em",
    textTransform: "uppercase",
  },
  headerTitle: {
    marginTop: "5px",
    fontSize: "30px",
    fontWeight: 560,
    letterSpacing: "0",
  },
  headerText: {
    marginTop: "8px",
    color: "light-dark(#6b6b6b, #a3a3a3)",
    fontSize: "14px",
  },
  headerStrong: {
    color: "light-dark(#111111, #f5f5f5)",
    fontWeight: 500,
  },
  section: {
    padding: "28px 0",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: "light-dark(#d9d9d9, #2a2a2a)",
  },
  sectionHeading: {
    display: "flex",
    alignItems: "start",
    justifyContent: "space-between",
    gap: "24px",
  },
  headingIcon: {
    flex: "0 0 auto",
    color: "light-dark(#777777, #999999)",
  },
  headingTitle: {
    fontSize: "16px",
    fontWeight: 560,
    letterSpacing: "0",
  },
  headingText: {
    marginTop: "6px",
    color: "light-dark(#6b6b6b, #a3a3a3)",
    fontSize: "13px",
    lineHeight: 1.5,
  },
  muted: {
    marginTop: "6px",
    color: "light-dark(#6b6b6b, #a3a3a3)",
    fontSize: "13px",
    lineHeight: 1.5,
  },
  details: {
    display: "grid",
    marginTop: "18px",
  },
  detailsRow: {
    display: "grid",
    gridTemplateColumns: {
      default: "minmax(120px, 0.38fr) 1fr",
      "@media (max-width: 620px)": "96px minmax(0, 1fr)",
    },
    gap: "20px",
    padding: "11px 0",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: "light-dark(#ececec, #242424)",
    fontSize: "13px",
  },
  detailsTerm: {
    color: "light-dark(#6b6b6b, #999999)",
  },
  detailsValue: {
    color: "light-dark(#111111, #f5f5f5)",
    fontWeight: 500,
    textTransform: "capitalize",
  },
  sectionAction: {
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
    gap: "20px",
    marginTop: "18px",
  },
  sectionActionText: {
    marginTop: "0",
    color: "light-dark(#6b6b6b, #a3a3a3)",
    fontSize: "13px",
    lineHeight: 1.5,
  },
  /** The section action's own button: full width on a phone. Pass as `xstyle`. */
  action: {
    width: {
      default: "unset",
      "@media (max-width: 620px)": "100%",
    },
  },
  tokenForm: {
    display: "grid",
    gridTemplateColumns: {
      default: "minmax(180px, 1fr) minmax(150px, 0.8fr) 132px auto",
      "@media (max-width: 860px)": "1fr 132px",
      "@media (max-width: 620px)": "1fr",
    },
    alignItems: "end",
    gap: "10px",
    marginTop: "20px",
  },
  tokenFormLabel: {
    display: "grid",
    gap: "6px",
    color: "light-dark(#6b6b6b, #a3a3a3)",
    fontSize: "12px",
    fontWeight: 500,
  },
  tokenInput: {
    width: "100%",
    minHeight: "36px",
    padding: "0 10px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: {
      default: "light-dark(#d9d9d9, #333333)",
      ":focus": "light-dark(#111111, #ffffff)",
    },
    borderRadius: "6px",
    outline: "0",
    backgroundColor: "light-dark(#ffffff, #111111)",
    color: "light-dark(#111111, #f5f5f5)",
    fontFamily: "inherit",
    fontWeight: "inherit",
    lineHeight: "inherit",
    fontSize: "13px",
  },
  /** The token form's submit button: full width from the 860px breakpoint down. */
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
    padding: "9px 10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "light-dark(#cde2d3, #2c543b)",
    borderRadius: "5px",
    backgroundColor: "light-dark(#ffffff, #0c170f)",
    color: "light-dark(#183321, #d7f2df)",
    fontFamily: MONO,
    fontSize: "12px",
    userSelect: "all",
  },
  tokenList: {
    display: "grid",
    marginTop: "20px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: "light-dark(#e5e5e5, #2a2a2a)",
  },
  tokenRow: {
    display: "grid",
    gridTemplateColumns: {
      default: "minmax(180px, 0.8fr) minmax(240px, 1.2fr) 34px",
      "@media (max-width: 860px)": "minmax(0, 1fr) 34px",
    },
    alignItems: "center",
    gap: "18px",
    minHeight: "66px",
    padding: "10px 0",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: "light-dark(#e5e5e5, #2a2a2a)",
  },
  tokenRowMain: {
    minWidth: 0,
    display: "grid",
    gap: "5px",
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
    color: "light-dark(#111111, #f5f5f5)",
    fontSize: "13px",
    fontWeight: 550,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  tokenRowPrefix: {
    color: "light-dark(#6b6b6b, #999999)",
    fontFamily: MONO,
    fontSize: "11px",
  },
  tokenStatus: {
    padding: "2px 5px",
    borderRadius: "4px",
    backgroundColor: {
      default: "light-dark(#f1f1f1, #242424)",
      ":is([data-state='active'])": "light-dark(#eaf6ed, #173020)",
    },
    color: {
      default: "light-dark(#555555, #bbbbbb)",
      ":is([data-state='active'])": "light-dark(#28623a, #93d0a3)",
    },
    fontSize: "10px",
    fontWeight: 600,
    textTransform: "uppercase",
  },
  tokenMeta: {
    minWidth: 0,
    display: "grid",
    gap: "5px",
    color: "light-dark(#6b6b6b, #999999)",
    fontSize: "11px",
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
});
