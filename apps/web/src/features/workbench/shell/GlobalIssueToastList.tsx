"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Toast } from "@base-ui/react/toast";
import { CircleAlert, X } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";

export type GlobalIssueId = "registry" | "graph" | "run";

export interface GlobalIssue {
  id: GlobalIssueId;
  title: string;
  message: string;
}

interface GlobalIssueToastListProps {
  issues: readonly GlobalIssue[];
  onDismiss: (issue: GlobalIssue) => void;
}

const s = stylex.create({
  toastViewport: {
    position: "fixed",
    zIndex: 80,
    top: "70px",
    right: "13px",
    width: "min(380px, calc(100vw - 26px))",
    maxHeight: "calc(100svh - 84px)",
    display: "flex",
    flexDirection: "column",
    alignItems: "stretch",
    gap: "8px",
    outline: "none",
    pointerEvents: "none",
  },
  toastRoot: {
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
  toastContent: {
    display: "grid",
    gridTemplateColumns: "26px minmax(0, 1fr) 28px",
    alignItems: "start",
    gap: "10px",
    padding: "11px",
  },
  toastIcon: {
    width: "26px",
    height: "26px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    borderRadius: "8px",
    backgroundColor: tokens.colorDangerHover,
    color: tokens.colorDanger,
  },
  toastCopy: {
    minWidth: 0,
    display: "grid",
    gap: "3px",
    paddingTop: "1px",
  },
  toastTitle: {
    color: tokens.colorTextEmphasis,
    fontSize: tokens.fontSizeSm,
    fontWeight: 750,
    lineHeight: 1.35,
  },
  toastDescription: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
    overflowWrap: "anywhere",
    userSelect: "text",
    whiteSpace: "pre-wrap",
  },
  toastClose: {
    width: "28px",
    height: "28px",
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 0,
    borderRadius: "7px",
    outline: "none",
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorHover,
      ":focus-visible": tokens.colorHoverStrong,
    },
    color: {
      default: tokens.colorSubtle,
      ":hover": tokens.colorText,
      ":focus-visible": tokens.colorText,
    },
    cursor: "pointer",
  },
});

export function GlobalIssueToastList({
  issues,
  onDismiss,
}: GlobalIssueToastListProps) {
  const { toasts, add, close } = Toast.useToastManager();
  const activeIssueIds = React.useRef<Set<string>>(new Set());

  React.useEffect(() => {
    const nextIssueIds = new Set<string>();
    for (const issue of issues) {
      const toastId = `workflow-${issue.id}`;
      nextIssueIds.add(toastId);
      add({
        id: toastId,
        title: issue.id === "run" ? "Workflow issue" : `${issue.title} issue`,
        description: issue.message,
        type: "error",
        priority: "high",
        timeout: issue.id === "registry" ? 0 : 8000,
        onClose: () => onDismiss(issue),
      });
    }
    for (const toastId of activeIssueIds.current) {
      if (!nextIssueIds.has(toastId)) close(toastId);
    }
    activeIssueIds.current = nextIssueIds;
  }, [add, close, issues, onDismiss]);

  return (
    <Toast.Portal>
      <Toast.Viewport
        aria-label="Workflow notifications"
        {...stylex.props(s.toastViewport)}
      >
        {toasts.map((toast) => (
          <Toast.Root
            key={toast.id}
            toast={toast}
            swipeDirection="right"
            className={`grafy-workbench-toast ${stylex.props(s.toastRoot).className}`}
          >
            <Toast.Content {...stylex.props(s.toastContent)}>
              <span aria-hidden="true" {...stylex.props(s.toastIcon)}>
                <CircleAlert size={15} />
              </span>
              <span {...stylex.props(s.toastCopy)}>
                <Toast.Title {...stylex.props(s.toastTitle)} />
                <Toast.Description {...stylex.props(s.toastDescription)} />
              </span>
              <Toast.Close
                aria-label="Dismiss workflow notification"
                {...stylex.props(s.toastClose)}
              >
                <X size={14} />
              </Toast.Close>
            </Toast.Content>
          </Toast.Root>
        ))}
      </Toast.Viewport>
    </Toast.Portal>
  );
}
