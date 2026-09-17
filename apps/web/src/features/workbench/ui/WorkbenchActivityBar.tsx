"use client";

import * as stylex from "@stylexjs/stylex";
import {
  CircleAlert,
  CircleCheck,
  LoaderCircle,
  RotateCcw,
  Square,
  TriangleAlert,
  X,
} from "lucide-react";

import { BrandLoader } from "@/components/brand";
import { tokens } from "@/lib/stylex/tokens.stylex";

export type WorkbenchActivityTone =
  | "working"
  | "cancelling"
  | "success"
  | "warning"
  | "error";

export interface WorkbenchActivityAction {
  kind: "cancel" | "retry" | "dismiss";
  label: string;
  ariaLabel: string;
  disabled?: boolean;
  onInvoke: () => void;
}

export interface WorkbenchActivity {
  eyebrow: string;
  title: string;
  message: string;
  tone: WorkbenchActivityTone;
  action?: WorkbenchActivityAction;
}

const s = stylex.create({
  bar: {
    position: "absolute",
    zIndex: 30,
    bottom: {
      default: "78px",
      "@media (max-width: 720px)": "calc(80px + env(safe-area-inset-bottom))",
    },
    left: {
      default: "50%",
      // Centre on the canvas, not on the canvas plus the docked Runs drawer.
      "@media (min-width: 721px)":
        "calc(50% - (var(--grafy-generated-drawer-width, 0px) / 2))",
    },
    width: {
      default: "min(460px, calc(100% - 24px))",
      "@media (max-width: 720px)":
        "min(460px, calc(100% - 24px - env(safe-area-inset-left, 0px) - env(safe-area-inset-right, 0px)))",
    },
    minHeight: "52px",
    display: "grid",
    gridTemplateColumns: "28px minmax(0, 1fr)",
    alignItems: "center",
    gap: "10px",
    padding: "8px 9px 8px 11px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "13px",
    backgroundColor: tokens.colorChrome,
    boxShadow: tokens.shadowNodeRaised,
    transform: "translateX(-50%)",
  },
  barWithAction: {
    gridTemplateColumns: "28px minmax(0, 1fr) auto",
  },
  indicator: {
    width: "28px",
    height: "28px",
    display: "grid",
    placeItems: "center",
    borderRadius: "9px",
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorAccent,
  },
  indicatorBrand: {
    backgroundColor: "transparent",
    color: tokens.colorText,
  },
  indicatorSuccess: {
    backgroundColor: "light-dark(rgba(42, 157, 124, 0.12), rgba(67, 197, 158, 0.15))",
    color: tokens.colorSuccess,
  },
  indicatorWarning: {
    backgroundColor: "light-dark(rgba(201, 146, 15, 0.12), rgba(251, 191, 36, 0.15))",
    color: tokens.colorWarning,
  },
  indicatorError: {
    backgroundColor: tokens.colorDangerHover,
    color: tokens.colorDanger,
  },
  copy: {
    minWidth: 0,
    display: "grid",
    gap: "2px",
  },
  eyebrow: {
    color: tokens.colorSubtle,
    fontSize: "9px",
    fontWeight: 800,
    letterSpacing: 0,
    lineHeight: 1,
    textTransform: "uppercase",
  },
  title: {
    overflow: "hidden",
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 720,
    lineHeight: 1.25,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  message: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontSize: "10px",
    lineHeight: 1.2,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  messageWarning: { color: tokens.colorWarning },
  messageError: { color: tokens.colorDanger },
  action: {
    height: {
      default: "32px",
      "@media (max-width: 720px)": "44px",
    },
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    gap: "6px",
    paddingInline: "10px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorBorderStrong,
      ":hover": tokens.colorAccent,
      ":disabled": tokens.colorBorder,
    },
    borderRadius: "8px",
    outlineWidth: { default: 0, ":focus-visible": "2px" },
    outlineStyle: "solid",
    outlineColor: tokens.colorAccent,
    outlineOffset: "2px",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
      ":disabled": "transparent",
    },
    color: {
      default: tokens.colorMuted,
      ":hover": tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    fontSize: tokens.fontSizeXs,
    fontWeight: 700,
  },
  actionCancel: {
    borderColor: {
      default: tokens.colorBorderStrong,
      ":hover": tokens.colorDanger,
      ":disabled": tokens.colorBorder,
    },
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorDangerHover,
      ":disabled": "transparent",
    },
    color: {
      default: tokens.colorMuted,
      ":hover": tokens.colorDanger,
      ":disabled": tokens.colorTextDisabled,
    },
  },
  spinner: {
    animationName: "grafy-spin",
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
});

function ActivityIcon({ tone }: { tone: WorkbenchActivityTone }) {
  if (tone === "success") return <CircleCheck size={15} />;
  if (tone === "warning") return <TriangleAlert size={15} />;
  if (tone === "error") return <CircleAlert size={15} />;
  return <BrandLoader size={28} decorative />;
}

function ActionIcon({ kind }: { kind: WorkbenchActivityAction["kind"] }) {
  if (kind === "cancel") return <Square size={11} fill="currentColor" />;
  if (kind === "retry") return <RotateCcw size={12} />;
  return <X size={13} />;
}

export function WorkbenchActivityBar({
  activity,
}: {
  activity: WorkbenchActivity;
}) {
  const { action } = activity;
  const brandIndicator =
    activity.tone === "working" || activity.tone === "cancelling";
  return (
    <aside
      aria-label={`${activity.eyebrow}: ${activity.title}`}
      {...stylex.props(s.bar, action ? s.barWithAction : null)}
    >
      <span
        aria-hidden="true"
        {...stylex.props(
          s.indicator,
          brandIndicator ? s.indicatorBrand : null,
          activity.tone === "success" ? s.indicatorSuccess : null,
          activity.tone === "warning" ? s.indicatorWarning : null,
          activity.tone === "error" ? s.indicatorError : null,
        )}
      >
        <ActivityIcon tone={activity.tone} />
      </span>
      <span
        role="status"
        aria-live="polite"
        aria-atomic="true"
        {...stylex.props(s.copy)}
      >
        <span {...stylex.props(s.eyebrow)}>{activity.eyebrow}</span>
        <span {...stylex.props(s.title)}>{activity.title}</span>
        <span
          {...stylex.props(
            s.message,
            activity.tone === "warning" ? s.messageWarning : null,
            activity.tone === "error" ? s.messageError : null,
          )}
        >
          {activity.message}
        </span>
      </span>
      {action ? (
        <button
          type="button"
          disabled={action.disabled}
          aria-label={action.ariaLabel}
          {...stylex.props(
            s.action,
            action.kind === "cancel" ? s.actionCancel : null,
          )}
          onClick={action.onInvoke}
        >
          {activity.tone === "cancelling" ? (
            <LoaderCircle size={12} {...stylex.props(s.spinner)} />
          ) : (
            <ActionIcon kind={action.kind} />
          )}
          {action.label}
        </button>
      ) : null}
    </aside>
  );
}
