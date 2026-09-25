import * as stylex from "@stylexjs/stylex";

/** Style keys used by more than one artifact renderer. */
export const sharedStyles = stylex.create({
  jsonCode: {
    margin: 0,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    lineHeight: 1.55,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
});
