"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Toast } from "@base-ui/react/toast";
import {
  CircleAlert,
  CircleCheck,
  LoaderCircle,
  TriangleAlert,
  X,
} from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";

import type { ArtifactViewerActivity } from "../artifacts/artifact-interactions";

const TOAST_ID = "linked-view";

const s = stylex.create({
  viewport: {
    position: "fixed",
    zIndex: 70,
    bottom: {
      default: "78px",
      "@media (max-width: 720px)": "calc(80px + env(safe-area-inset-bottom))",
    },
    left: "50%",
    width: "min(420px, calc(100vw - 24px))",
    transform: "translateX(-50%)",
    outline: "none",
    pointerEvents: "none",
  },
  root: {
    width: "100%",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "12px",
    backgroundColor: tokens.colorSurface,
    boxShadow: tokens.shadowNode,
    color: tokens.colorText,
    pointerEvents: "auto",
  },
  content: {
    display: "grid",
    gridTemplateColumns: "26px minmax(0, 1fr) auto",
    alignItems: "start",
    gap: "10px",
    padding: "11px",
  },
  icon: {
    width: "26px",
    height: "26px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: "8px",
    backgroundColor: tokens.colorAccentSoft,
    color: tokens.colorText,
  },
  iconWarning: {
    backgroundColor: tokens.colorWarningSoft,
    color: tokens.colorWarning,
  },
  iconError: {
    backgroundColor: tokens.colorDangerHover,
    color: tokens.colorDanger,
  },
  copy: {
    minWidth: 0,
    display: "grid",
    gap: "3px",
    paddingTop: "1px",
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
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 720,
    lineHeight: 1.3,
  },
  description: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
    overflowWrap: "anywhere",
  },
  actions: {
    display: "flex",
    alignItems: "center",
    gap: "4px",
  },
  action: {
    height: "28px",
    borderWidth: 0,
    borderRadius: "7px",
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorHover,
      ":focus-visible": tokens.colorHoverStrong,
    },
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    fontWeight: 650,
    paddingInline: "8px",
    cursor: "pointer",
  },
  close: {
    width: "28px",
    height: "28px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 0,
    borderRadius: "7px",
    backgroundColor: {
      default: "transparent",
      ":hover:not(:disabled)": tokens.colorHover,
      ":focus-visible": tokens.colorHoverStrong,
    },
    color: tokens.colorSubtle,
    cursor: "pointer",
  },
});

function ActivityIcon({ state }: { state: ArtifactViewerActivity["state"] }) {
  if (state === "success") return <CircleCheck size={15} />;
  if (state === "warning") return <TriangleAlert size={15} />;
  if (state === "error") return <CircleAlert size={15} />;
  return <LoaderCircle size={15} />;
}

/**
 * Linked-view feedback that used to fall back onto the project activity bar.
 * The bar assumed one project-wide run. This toast does not.
 */
export function LinkedViewActivityToast({
  activity,
  onRetry,
  onDismiss,
}: {
  activity: ArtifactViewerActivity | null;
  onRetry?: () => void;
  onDismiss?: () => void;
}) {
  return (
    <Toast.Provider timeout={0} limit={1}>
      <LinkedViewToast
        activity={activity}
        onRetry={onRetry}
        onDismiss={onDismiss}
      />
    </Toast.Provider>
  );
}

function LinkedViewToast({
  activity,
  onRetry,
  onDismiss,
}: {
  activity: ArtifactViewerActivity | null;
  onRetry?: () => void;
  onDismiss?: () => void;
}) {
  const { add, close, toasts } = Toast.useToastManager();
  const activityRef = React.useRef(activity);
  const onRetryRef = React.useRef(onRetry);
  const onDismissRef = React.useRef(onDismiss);

  React.useLayoutEffect(() => {
    activityRef.current = activity;
    onRetryRef.current = onRetry;
    onDismissRef.current = onDismiss;
  });

  React.useEffect(() => {
    if (!activity) {
      close(TOAST_ID);
      return;
    }
    add({
      id: TOAST_ID,
      title: activity.title,
      description: activity.message,
      timeout: 0,
      onClose: () => {
        if (activityRef.current === null) return;
        onDismissRef.current?.();
      },
    });
  }, [activity, add, close]);

  return (
    <Toast.Portal>
      <Toast.Viewport
        aria-label="Linked view"
        data-linked-view-toast="true"
        {...stylex.props(s.viewport)}
      >
        {toasts.map((toast) => {
          const state = activity?.state ?? "working";
          return (
            <Toast.Root
              key={toast.id}
              toast={toast}
              swipeDirection="right"
              aria-label={
                activity ? `Linked view: ${activity.title}` : "Linked view"
              }
              {...stylex.props(s.root)}
            >
              <Toast.Content {...stylex.props(s.content)}>
                <span
                  aria-hidden="true"
                  {...stylex.props(
                    s.icon,
                    state === "warning" ? s.iconWarning : null,
                    state === "error" ? s.iconError : null,
                  )}
                >
                  <ActivityIcon state={state} />
                </span>
                <span {...stylex.props(s.copy)}>
                  <span {...stylex.props(s.eyebrow)}>Linked view</span>
                  <Toast.Title {...stylex.props(s.title)} />
                  <Toast.Description {...stylex.props(s.description)} />
                </span>
                <span {...stylex.props(s.actions)}>
                  {onRetry ? (
                    <button
                      type="button"
                      aria-label={
                        activity ? `Retry ${activity.title}` : "Retry"
                      }
                      {...stylex.props(s.action)}
                      onClick={() => onRetryRef.current?.()}
                    >
                      Retry
                    </button>
                  ) : null}
                  {onDismiss ? (
                    <button
                      type="button"
                      aria-label={
                        activity
                          ? `Dismiss ${activity.title}`
                          : "Dismiss linked view"
                      }
                      {...stylex.props(s.close)}
                      onClick={() => onDismissRef.current?.()}
                    >
                      <X size={14} />
                    </button>
                  ) : null}
                </span>
              </Toast.Content>
            </Toast.Root>
          );
        })}
      </Toast.Viewport>
    </Toast.Portal>
  );
}
