import * as stylex from "@stylexjs/stylex";

import { tokens } from "@/lib/stylex/tokens.stylex";

/** Style keys used by more than one workflow node module. */
export const sharedStyles = stylex.create({
  operatorCopy: {
    minWidth: 0,
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  /** Structural schema metadata, so it stays out of the port/type colour range. */
  required: { color: tokens.colorSubtle, fontSize: tokens.fontSizeSm },
  schemaBody: {
    display: "grid",
    gap: "10px",
    padding: "0 8px 12px",
  },
  /**
   * Size override for a shared `TextInput` inside a schema row: the kit's
   * 32px control is a page-sized field, a schema brick is a dense grid.
   * Colours, focus ring and radius stay the kit's.
   */
  denseControl: {
    height: "28px",
    paddingInline: "7px",
    fontSize: "10px",
  },
  schemaFieldsSection: { display: "grid", gap: "5px" },
  schemaFieldsHeader: {
    minHeight: "24px",
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: "8px",
    paddingInline: "5px",
  },
  schemaFieldsTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeXs,
    fontWeight: 600,
  },
  schemaFieldsCount: { color: tokens.colorSubtle, fontSize: "10px" },
  // Field rows sit 8px in from the plate; their balls hang that much further
  // out.
  schemaFieldList: {
    display: "grid",
    gap: "5px",
    ["--port-inset" as string]: "8px",
  },
  schemaFieldRow: {
    position: "relative",
    minWidth: 0,
    display: "grid",
    gap: "5px",
    padding: "6px 6px 6px 8px",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceMuted,
  },
  schemaFieldIndex: {
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    textAlign: "center",
  },
  schemaFieldActions: { display: "flex", alignItems: "center", gap: "1px" },
  spinner: {
    animationName: "grafy-spin",
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});
