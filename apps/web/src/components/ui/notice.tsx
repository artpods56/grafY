"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { X } from "lucide-react";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { IconButton } from "./button";

function joinClassNames(...names: Array<string | undefined>) {
  return names.filter(Boolean).join(" ") || undefined;
}

export type NoticeTone = "danger" | "warning" | "neutral";

export type NoticeProps = {
  /** Sets the element's id, so `aria-describedby` can point at the notice itself. */
  id?: string;
  /** danger and warning are announced as alerts; neutral as a status. Default "neutral". */
  tone?: NoticeTone;
  /**
   * "inline": a rounded box inside content. "banner": a full-width strip with
   * a bottom hairline, for the top of a panel. Default "inline".
   */
  variant?: "inline" | "banner";
  /** A trailing action, e.g. a Retry button. */
  action?: React.ReactNode;
  /** When given, a Dismiss button closes the notice. */
  onDismiss?: () => void;
  /** The dismiss button's label. Default "Dismiss". */
  dismissLabel?: string;
  children: React.ReactNode;
  /** Plain class names added after the StyleX ones. */
  className?: string;
  /** Caller overrides made with stylex.create, applied last. */
  xstyle?: stylex.StyleXStyles;
};

const notice = stylex.create({
  base: {
    display: "flex",
    alignItems: "flex-start",
    gap: "8px",
    margin: 0,
    boxSizing: "border-box",
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
    overflowWrap: "anywhere",
  },
  inline: {
    padding: "6px 8px",
    borderRadius: tokens.radiusMd,
  },
  banner: {
    flexShrink: 0,
    padding: "7px 10px",
    borderBottomWidth: 1,
    borderBottomStyle: "solid",
    borderBottomColor: tokens.colorBorder,
  },
  danger: {
    backgroundColor: tokens.colorDangerHover,
    color: tokens.colorDanger,
  },
  warning: {
    backgroundColor: tokens.colorWarningSoft,
    color: tokens.colorWarning,
  },
  neutral: {
    backgroundColor: tokens.colorSurfaceRaised,
    color: tokens.colorMuted,
  },
  text: {
    flex: 1,
    minWidth: 0,
  },
  action: {
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    gap: "6px",
    marginBlock: "-3px",
  },
  dismiss: {
    marginBlock: "-3px",
    marginRight: "-4px",
    color: "inherit",
    opacity: 0.8,
  },
});

/** A short message: an error, a warning or neutral information, with an optional action and dismiss. */
export function Notice({
  id,
  tone = "neutral",
  variant = "inline",
  action,
  onDismiss,
  dismissLabel = "Dismiss",
  children,
  className,
  xstyle,
}: NoticeProps) {
  const styled = stylex.props(
    notice.base,
    notice[variant],
    notice[tone],
    xstyle,
  );
  return (
    <div
      id={id}
      role={tone === "neutral" ? "status" : "alert"}
      className={joinClassNames(styled.className, className)}
      style={styled.style}
    >
      <div {...stylex.props(notice.text)}>{children}</div>
      {action != null ? (
        <div {...stylex.props(notice.action)}>{action}</div>
      ) : null}
      {onDismiss ? (
        <IconButton
          label={dismissLabel}
          size="xs"
          xstyle={notice.dismiss}
          onClick={onDismiss}
        >
          <X size={12} />
        </IconButton>
      ) : null}
    </div>
  );
}
