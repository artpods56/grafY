import * as stylex from "@stylexjs/stylex";

/**
 * StyleX port of the `.grafy-workspace-directory*` rules that used to live in
 * globals.css. Values are copied verbatim, including the 860px / 620px
 * breakpoints and the prefers-reduced-motion overrides, so this page renders
 * exactly as before. `.grafy-workspace-overview__eyebrow` is styled here for
 * this page only; the settings page keeps its own global rule.
 */
export const workspacesPageStyles = stylex.create({
  directory: {
    minHeight: "100svh",
    height: "100svh",
    overflow: "auto",
    backgroundColor: "light-dark(#ffffff, #111111)",
    color: "light-dark(#111111, #f5f5f5)",
  },
  main: {
    maxWidth: "1080px",
    minHeight: "100svh",
    margin: "0 auto",
    padding: {
      default: "40px 40px 56px calc(var(--grafy-rail-width, 200px) + 48px)",
      "@media (max-width: 860px)":
        "28px 18px 40px calc(var(--grafy-rail-width, 64px) + 16px)",
      "@media (max-width: 620px)":
        "calc(var(--grafy-mobile-page-top) + env(safe-area-inset-top)) calc(16px + env(safe-area-inset-right)) calc(40px + env(safe-area-inset-bottom)) calc(16px + env(safe-area-inset-left))",
    },
    transitionProperty: {
      default: "padding",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    transitionDuration: "180ms",
    transitionTimingFunction: "ease",
  },
  header: {
    display: "flex",
    alignItems: {
      default: "end",
      "@media (max-width: 860px)": "start",
    },
    justifyContent: "space-between",
    gap: {
      default: "24px",
      "@media (max-width: 620px)": "18px",
    },
    paddingBottom: "24px",
    flexDirection: {
      default: "row",
      "@media (max-width: 860px)": "column",
    },
  },
  eyebrow: {
    color: "light-dark(#6b6b6b, #a3a3a3)",
    fontSize: "11px",
    fontWeight: 500,
    letterSpacing: "0.12em",
    textTransform: "uppercase",
  },
  headerTitle: {
    fontSize: "clamp(1.7rem, 3vw, 2.45rem)",
    fontWeight: 500,
    letterSpacing: "-0.03em",
    lineHeight: 1.1,
  },
  // Also matches the eyebrow <p>: in the global stylesheet
  // `.grafy-workspace-directory__header p` outranks `.grafy-workspace-overview__eyebrow`
  // on specificity, so the eyebrow is passed this style last.
  headerText: {
    maxWidth: "520px",
    marginTop: "8px",
    color: "light-dark(#6b6b6b, #a3a3a3)",
    fontSize: "14px",
    lineHeight: 1.5,
  },
  actions: {
    display: "flex",
    flexWrap: "wrap",
    gap: "8px",
    width: {
      "@media (max-width: 620px)": "100%",
    },
    justifyContent: {
      "@media (max-width: 620px)": "flex-start",
    },
  },
  // Was `.grafy-workspace-directory__actions > *` at 620px (`min-width: 0;
  // flex: 1 1 100%`). The actions are the two kit Buttons, so the rule lands on
  // them through `xstyle`. Longhands with initial-value defaults keep the kit's
  // own flex-shrink: 0, which already won the old legacy shorthand.
  actionItem: {
    minWidth: { default: "auto", "@media (max-width: 620px)": 0 },
    flexGrow: { default: 0, "@media (max-width: 620px)": 1 },
    flexBasis: { default: "auto", "@media (max-width: 620px)": "100%" },
  },
  createForm: {
    display: "flex",
    alignItems: {
      default: "end",
      "@media (max-width: 860px)": "stretch",
    },
    flexWrap: "wrap",
    gap: "10px",
    marginBottom: "8px",
    padding: "16px 0",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: "light-dark(#d9d9d9, #2a2a2a)",
    flexDirection: {
      "@media (max-width: 860px)": "column",
    },
  },
  createLabel: {
    display: "grid",
    flex: 1,
    gap: "5px",
    color: "light-dark(#6b6b6b, #a3a3a3)",
    fontSize: "12px",
    fontWeight: 500,
  },
  createInput: {
    minHeight: {
      default: "36px",
      "@media (max-width: 620px)": "44px",
    },
    padding: "0 10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: {
      default: "light-dark(#d9d9d9, #333333)",
      ":focus": "light-dark(#111111, #ffffff)",
    },
    borderRadius: "6px",
    outline: "0",
    backgroundColor: "light-dark(#ffffff, #1a1a1a)",
    color: "light-dark(#111111, #f5f5f5)",
    fontSize: "13px",
  },
  joinForm: {
    display: "flex",
    alignItems: {
      default: "center",
      "@media (max-width: 860px)": "stretch",
    },
    flexWrap: "wrap",
    gap: "10px",
    marginBottom: "8px",
    padding: "16px 0",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: "light-dark(#d9d9d9, #2a2a2a)",
    flexDirection: {
      "@media (max-width: 860px)": "column",
    },
  },
  joinText: {
    flex: 1,
    minWidth: "220px",
    color: "light-dark(#6b6b6b, #a3a3a3)",
    fontSize: "13px",
  },
  toolbar: {
    display: "flex",
    alignItems: {
      default: "center",
      "@media (max-width: 860px)": "stretch",
    },
    gap: "12px",
    margin: {
      default: "8px 0 28px",
      "@media (max-width: 620px)": "8px 0 20px",
    },
    flexDirection: {
      "@media (max-width: 860px)": "column",
    },
  },
  search: {
    flex: 1,
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "8px",
    minHeight: {
      default: "36px",
      "@media (max-width: 620px)": "44px",
    },
    padding: "0 12px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: {
      default: "light-dark(#d9d9d9, #333333)",
      ":focus-within": "light-dark(#111111, #ffffff)",
    },
    borderRadius: "6px",
    backgroundColor: "light-dark(#ffffff, #111111)",
    color: "light-dark(#6b6b6b, #a3a3a3)",
  },
  searchInput: {
    width: "100%",
    borderWidth: 0,
    outline: "0",
    backgroundColor: "transparent",
    color: "light-dark(#111111, #f5f5f5)",
    fontFamily: "inherit",
    fontStyle: "inherit",
    fontWeight: "inherit",
    lineHeight: "inherit",
    fontSize: "14px",
  },
  section: {
    marginBottom: "32px",
  },
  sectionHeading: {
    display: "flex",
    alignItems: "baseline",
    justifyContent: "space-between",
    gap: "16px",
    marginBottom: "4px",
  },
  sectionTitle: {
    fontSize: "15px",
    fontWeight: 500,
    letterSpacing: "-0.01em",
  },
  sectionMeta: {
    color: "light-dark(#6b6b6b, #8a8a8a)",
    fontSize: "12px",
  },
  list: {
    display: "grid",
  },
  row: {
    display: "grid",
    gridTemplateColumns: {
      default: "32px minmax(0, 1fr) auto 18px",
      "@media (max-width: 860px)": "32px minmax(0, 1fr) 18px",
    },
    alignItems: "center",
    gap: "12px",
    padding: "14px 4px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: "light-dark(#d9d9d9, #2a2a2a)",
    color: "inherit",
    transitionProperty: {
      default: "background-color",
      "@media (prefers-reduced-motion: reduce)": "none",
    },
    transitionDuration: "140ms",
    transitionTimingFunction: "ease",
    minHeight: {
      "@media (max-width: 620px)": "68px",
    },
    backgroundColor: {
      ":hover:not(:disabled)": "light-dark(#fafafa, #1a1a1a)",
    },
  },
  rowIcon: {
    width: "28px",
    height: "28px",
    display: "grid",
    placeItems: "center",
    borderRadius: "6px",
    backgroundColor: "light-dark(#f4f4f4, #1a1a1a)",
    color: "light-dark(#111111, #f5f5f5)",
  },
  rowCopy: {
    display: "grid",
    gap: "3px",
  },
  rowName: {
    color: "light-dark(#111111, #f5f5f5)",
    fontSize: "14px",
    fontWeight: 500,
  },
  rowHint: {
    color: "light-dark(#6b6b6b, #8a8a8a)",
    fontSize: "12px",
  },
  rowOpen: {
    padding: "4px 8px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "light-dark(#d9d9d9, #333333)",
    borderRadius: "4px",
    color: "light-dark(#111111, #f5f5f5)",
    fontSize: "12px",
    fontWeight: 500,
    display: {
      "@media (max-width: 860px)": "none",
    },
  },
  loading: {
    display: "inline-flex",
    alignItems: "center",
    gap: "12px",
    color: "light-dark(#6b6b6b, #8a8a8a)",
    fontSize: "14px",
  },
  empty: {
    display: "grid",
    justifyItems: "start",
    gap: "10px",
    padding: "20px 4px 8px",
    color: "light-dark(#6b6b6b, #a3a3a3)",
    fontSize: "13px",
  },
  edu: {
    display: "flex",
    alignItems: "start",
    justifyContent: "space-between",
    gap: "24px",
    marginTop: "16px",
    padding: "20px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: "light-dark(#d9d9d9, #2a2a2a)",
    borderRadius: "8px",
    backgroundColor: "light-dark(#fafafa, #1a1a1a)",
    flexDirection: {
      "@media (max-width: 620px)": "column",
    },
  },
  eduTitle: {
    marginBottom: "6px",
    fontSize: "14px",
    fontWeight: 500,
  },
  eduText: {
    maxWidth: "520px",
    color: "light-dark(#6b6b6b, #a3a3a3)",
    fontSize: "13px",
    lineHeight: 1.5,
  },
  eduMark: {
    width: "42px",
    height: "42px",
    borderRadius: "9999px",
    backgroundImage: [
      "radial-gradient(circle at 30% 35%, light-dark(#111111, #ffffff) 0 3px, transparent 3.5px)",
      "radial-gradient(circle at 70% 30%, light-dark(#111111, #ffffff) 0 3px, transparent 3.5px)",
      "radial-gradient(circle at 50% 70%, light-dark(#111111, #ffffff) 0 3px, transparent 3.5px)",
      "linear-gradient(115deg, transparent 0 38%, light-dark(#111111, #ffffff) 38% 39%, transparent 39% 61%, light-dark(#111111, #ffffff) 61% 62%, transparent 62%)",
      "linear-gradient(65deg, transparent 0 45%, light-dark(#111111, #ffffff) 45% 46%, transparent 46%)",
    ].join(", "),
    opacity: 0.85,
  },
});
