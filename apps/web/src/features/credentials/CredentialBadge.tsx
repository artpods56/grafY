"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  Ban,
  CircleCheck,
  CircleDashed,
  CircleHelp,
  ShieldAlert,
  TriangleAlert,
} from "lucide-react";

import type { CredentialVerificationStatus } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  credentialStatusDescription,
  credentialStatusLabel,
  credentialStatusTone,
  type CredentialTone,
} from "./credential-display";

const badge = stylex.create({
  root: {
    flexShrink: 0,
    display: "inline-flex",
    alignItems: "center",
    gap: "3px",
    boxSizing: "border-box",
    borderRadius: "9999px",
    fontWeight: 600,
    lineHeight: 1,
    whiteSpace: "nowrap",
  },
  dense: { height: "15px", paddingInline: "5px", fontSize: "8.5px" },
  md: { height: "20px", paddingInline: "7px", fontSize: tokens.fontSizeXs },
  success: {
    backgroundColor: `color-mix(in oklab, ${tokens.colorSuccess} 14%, transparent)`,
    color: tokens.colorSuccess,
  },
  warning: {
    backgroundColor: tokens.colorWarningSoft,
    color: tokens.colorWarning,
  },
  danger: {
    backgroundColor: `color-mix(in oklab, ${tokens.colorDanger} 14%, transparent)`,
    color: tokens.colorDanger,
  },
  neutral: {
    backgroundColor: tokens.colorHover,
    color: tokens.colorMuted,
  },
  /** A scope or provider: an outline, so it never reads as a status. */
  outline: {
    backgroundColor: "transparent",
    color: tokens.colorMuted,
    boxShadow: `inset 0 0 0 1px ${tokens.colorBorder}`,
  },
});

export type BadgeTone = CredentialTone | "outline";

/** A small pill: a status in a tone, or an outlined scope or provider. */
export function CredentialBadge({
  tone,
  size = "md",
  icon,
  title,
  children,
  ...data
}: {
  tone: BadgeTone;
  size?: "dense" | "md";
  icon?: React.ReactNode;
  title?: string;
  children: React.ReactNode;
} & { [key: `data-${string}`]: string | undefined }) {
  return (
    <span
      title={title}
      {...data}
      {...stylex.props(badge.root, badge[size], badge[tone])}
    >
      {icon}
      {children}
    </span>
  );
}

const STATUS_ICON: Record<CredentialVerificationStatus, typeof CircleCheck> = {
  valid: CircleCheck,
  invalid: ShieldAlert,
  egress_blocked: Ban,
  unreachable: TriangleAlert,
  unverified: CircleDashed,
  unsupported: CircleHelp,
};

/** A verification result as a toned badge, with its meaning as a tooltip. */
export function VerificationBadge({
  status,
  size = "md",
}: {
  status: CredentialVerificationStatus;
  size?: "dense" | "md";
}) {
  const Icon = STATUS_ICON[status];
  return (
    <CredentialBadge
      tone={credentialStatusTone(status)}
      size={size}
      title={credentialStatusDescription[status]}
      data-verification={status}
      icon={<Icon size={size === "dense" ? 8 : 11} aria-hidden="true" />}
    >
      {credentialStatusLabel[status]}
    </CredentialBadge>
  );
}

const callout = stylex.create({
  root: {
    display: "grid",
    gridTemplateColumns: "auto minmax(0, 1fr)",
    alignItems: "start",
    columnGap: "6px",
    margin: 0,
    borderRadius: tokens.radiusMd,
    borderWidth: "1px",
    borderStyle: "solid",
    lineHeight: 1.4,
  },
  dense: { padding: "5px 7px", fontSize: "9px" },
  md: { padding: "8px 10px", fontSize: tokens.fontSizeSm },
  icon: { marginTop: "1px" },
  title: { fontWeight: 600 },
  message: { color: tokens.colorText, overflowWrap: "anywhere" },
  success: {
    borderColor: `color-mix(in oklab, ${tokens.colorSuccess} 30%, transparent)`,
    backgroundColor: `color-mix(in oklab, ${tokens.colorSuccess} 8%, transparent)`,
    color: tokens.colorSuccess,
  },
  warning: {
    borderColor: `color-mix(in oklab, ${tokens.colorWarning} 30%, transparent)`,
    backgroundColor: tokens.colorWarningSoft,
    color: tokens.colorWarning,
  },
  danger: {
    borderColor: `color-mix(in oklab, ${tokens.colorDanger} 30%, transparent)`,
    backgroundColor: `color-mix(in oklab, ${tokens.colorDanger} 8%, transparent)`,
    color: tokens.colorDanger,
  },
  neutral: {
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorHover,
    color: tokens.colorMuted,
  },
});

const TONE_ICON: Record<CredentialTone, typeof CircleCheck> = {
  success: CircleCheck,
  warning: TriangleAlert,
  danger: ShieldAlert,
  neutral: CircleHelp,
};

/**
 * One verification outcome, spelled out: `Verified · 42 models available`.
 * A danger or warning outcome is announced as an alert.
 */
export function CredentialCallout({
  tone,
  title,
  children,
  size = "md",
}: {
  tone: CredentialTone;
  title: string;
  children?: React.ReactNode;
  size?: "dense" | "md";
}) {
  const Icon = TONE_ICON[tone];
  return (
    <p
      role={tone === "danger" || tone === "warning" ? "alert" : "status"}
      data-credential-callout={tone}
      {...stylex.props(callout.root, callout[size], callout[tone])}
    >
      <Icon
        size={size === "dense" ? 10 : 13}
        aria-hidden="true"
        {...stylex.props(callout.icon)}
      />
      <span>
        <span {...stylex.props(callout.title)}>{title}</span>
        {children != null && children !== "" ? (
          <span {...stylex.props(callout.message)}> · {children}</span>
        ) : null}
      </span>
    </p>
  );
}
