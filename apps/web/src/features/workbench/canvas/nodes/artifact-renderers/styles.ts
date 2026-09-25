import * as stylex from "@stylexjs/stylex";

export const MONO = "ui-monospace, SFMono-Regular, Menlo, monospace";

/** Style keys used by more than one artifact renderer. */
export const sharedStyles = stylex.create({
  jsonCode: {
    margin: 0,
    fontFamily: MONO,
    fontSize: "10px",
    lineHeight: 1.55,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
});
