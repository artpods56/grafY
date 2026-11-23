import * as stylex from "@stylexjs/stylex";
import type { ReactNode } from "react";

import { BrandLoader, BrandWordmark } from "@/components/brand";
import { tokens } from "@/lib/stylex/tokens.stylex";

/**
 * The sign-in / route-resolution screen that stands in before any product
 * surface paints.
 *
 * The panel is a row on a wide window and a column at the screen's own 640px
 * step. That step is neither `phoneTouch`'s 620px shell breakpoint nor the
 * workbench's 720px one, so it stays here as its own media query rather than
 * being folded into either (issue #211).
 *
 * The action is a kit `Button` handed in by the caller. The kit owns its border,
 * background, colour and hover; this module only sizes the row it sits in, which
 * is what the retired global rule still contributed.
 */
const styles = stylex.create({
  screen: {
    height: "100dvh",
    minHeight: "100svh",
    display: "grid",
    // A short window (landscape phone, folded laptop) top-aligns the panel so
    // the action stays on screen instead of being centred out of it.
    alignContent: {
      default: "center",
      "@media (max-height: 520px)": "start",
    },
    justifyContent: "center",
    justifyItems: "center",
    gap: "8px",
    padding: {
      default: "32px",
      "@media (max-width: 640px)":
        "calc(24px + env(safe-area-inset-top)) calc(20px + env(safe-area-inset-right)) calc(24px + env(safe-area-inset-bottom)) calc(20px + env(safe-area-inset-left))",
    },
    overflow: "auto",
    backgroundColor: tokens.colorBg,
    color: tokens.colorText,
  },
  panel: {
    display: "flex",
    alignItems: {
      default: "center",
      "@media (max-width: 640px)": "flex-start",
    },
    gap: { default: "36px", "@media (max-width: 640px)": "20px" },
    maxWidth: "720px",
    flexDirection: {
      default: "row",
      "@media (max-width: 640px)": "column",
    },
  },
  brand: {
    flexShrink: 0,
    display: "grid",
    placeItems: "center",
  },
  rule: {
    alignSelf: "stretch",
    width: { default: "1px", "@media (max-width: 640px)": "100%" },
    height: { default: "auto", "@media (max-width: 640px)": "1px" },
    backgroundColor: tokens.colorBorder,
  },
  copy: {
    display: "grid",
    gap: "10px",
    justifyItems: "start",
    minWidth: 0,
  },
  title: {
    fontSize: "clamp(1.45rem, 2.4vw, 1.9rem)",
    fontWeight: 500,
    letterSpacing: "-0.03em",
    lineHeight: 1.1,
  },
  detail: {
    maxWidth: "520px",
    color: tokens.colorMuted,
    fontSize: "14px",
    lineHeight: 1.5,
  },
  /**
   * The action row. A one-cell grid so the 640px step can give a height-auto
   * child (the test's link, any future anchor) the whole 44px row. A kit
   * `Button lg` still paints its own height, 36px until its own 620px step,
   * because that height is set on the button and stretch does not override it.
   */
  action: {
    marginTop: "6px",
    display: "grid",
    alignItems: {
      default: "center",
      "@media (max-width: 640px)": "stretch",
    },
    justifyItems: { default: "start", "@media (max-width: 640px)": "stretch" },
    width: { default: "auto", "@media (max-width: 640px)": "100%" },
    minHeight: { default: "auto", "@media (max-width: 640px)": "44px" },
  },
});

type ThresholdStatusProps = {
  title: string;
  detail: string;
  action?: ReactNode;
  loading?: boolean;
};

export function ThresholdStatus({
  title,
  detail,
  action,
  loading = false,
}: ThresholdStatusProps) {
  return (
    <main {...stylex.props(styles.screen)}>
      <div {...stylex.props(styles.panel)}>
        <div {...stylex.props(styles.brand)}>
          {loading ? (
            <BrandLoader size={88} label={title} />
          ) : (
            <BrandWordmark height={72} />
          )}
        </div>
        <div {...stylex.props(styles.rule)} aria-hidden="true" />
        <div {...stylex.props(styles.copy)}>
          <h1 {...stylex.props(styles.title)}>{title}</h1>
          <p {...stylex.props(styles.detail)}>{detail}</p>
          {action ? <div {...stylex.props(styles.action)}>{action}</div> : null}
        </div>
      </div>
    </main>
  );
}
