import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

export const executionHistoryDrawerStyles = stylex.create({
  drawer: {
    position: "absolute",
    zIndex: 35,
    top: {
      default: "66px",
      "@media (max-width: 720px)": "12px",
      "@media (max-width: 620px)":
        "calc(var(--grafy-mobile-overlay-top, 68px) + env(safe-area-inset-top, 0px))",
    },
    right: {
      default: "13px",
      "@media (max-width: 720px)":
        "calc(12px + env(safe-area-inset-right, 0px))",
    },
    bottom: {
      default: "12px",
      "@media (max-width: 720px)":
        "calc(12px + env(safe-area-inset-bottom, 0px))",
    },
    left: {
      default: "auto",
      "@media (max-width: 720px)":
        "calc(12px + env(safe-area-inset-left, 0px))",
    },
    width: {
      default: "min(880px, calc(100% - 26px))",
      "@media (max-width: 720px)": "auto",
    },
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorderStrong,
    borderRadius: "12px",
    backgroundColor: tokens.colorSurface,
    boxShadow: tokens.shadowNodeSelected,
    color: tokens.colorText,
  },
  header: {
    minHeight: "52px",
    display: "flex",
    alignItems: "center",
    gap: "9px",
    padding: "8px 9px 8px 14px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  headerIcon: {
    width: "28px",
    height: "28px",
    display: "grid",
    placeItems: "center",
    flexShrink: 0,
    borderRadius: "8px",
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorAccent,
  },
  headerCopy: { minWidth: 0, flex: 1, display: "grid", gap: "1px" },
  title: {
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeMd,
    fontWeight: 760,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  subtitle: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  /**
   * The box the header's IconButtons keep: 30px on desktop, a 44px touch target
   * on a phone. Colour, focus ring and the disabled state come from the kit.
   */
  headerButton: {
    width: {
      default: "30px",
      "@media (max-width: 720px)": "44px",
    },
    height: {
      default: "30px",
      "@media (max-width: 720px)": "44px",
    },
  },
  content: {
    minHeight: 0,
    flex: 1,
    display: "flex",
    flexDirection: "column",
  },
  listPane: { minHeight: 0, flex: 1, display: "flex", flexDirection: "column" },
  list: { minHeight: 0, flex: 1, overflowY: "auto", padding: "5px" },
  listItem: {
    width: "100%",
    display: "grid",
    padding: "10px",
    borderWidth: 0,
    borderRadius: "8px",
    color: tokens.colorText,
    textAlign: "left",
  },
  listCopy: { minWidth: 0, display: "grid", gap: "5px" },
  listTop: { display: "flex", alignItems: "center", gap: "6px" },
  timestamp: {
    minWidth: 0,
    flex: 1,
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 690,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  status: {
    flexShrink: 0,
    padding: "2px 6px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceMuted,
    color: tokens.colorMuted,
    fontSize: "9px",
    fontWeight: 780,
    letterSpacing: "0.03em",
    textTransform: "uppercase",
  },
  statusSuccess: {
    backgroundColor:
      "light-dark(rgba(42, 157, 124, 0.11), rgba(67, 197, 158, 0.14))",
    color: tokens.colorSuccess,
  },
  statusFailure: {
    backgroundColor: tokens.colorDangerHover,
    color: tokens.colorDanger,
  },
  statusActive: {
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorAccent,
  },
  statusCancelled: {
    backgroundColor:
      "light-dark(rgba(201, 146, 15, 0.12), rgba(251, 191, 36, 0.15))",
    color: tokens.colorWarning,
  },
  meta: {
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.35,
  },
  id: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontFamily: MONO,
    fontSize: "9px",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  noticeWrap: {
    padding: "7px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
  },
  runError: {
    padding: "7px 8px",
    borderRadius: "6px",
    backgroundColor: tokens.colorDangerHover,
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
    whiteSpace: "pre-wrap",
  },
  /** The tall centred block the list shows in place of its rows. */
  message: {
    minHeight: "150px",
    display: "grid",
    placeItems: "center",
    alignContent: "center",
    gap: "8px",
    padding: "28px 18px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.5,
    textAlign: "center",
  },
  spinner: {
    animationName: "grafy-spin",
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});
