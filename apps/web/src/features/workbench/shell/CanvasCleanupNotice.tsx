"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Toast } from "@base-ui/react/toast";

import { tokens } from "@/lib/stylex/tokens.stylex";

const TOAST_ID = "canvas-cleanup";

const s = stylex.create({
  viewport: {
    position: "fixed",
    zIndex: 80,
    right: "24px",
    bottom: "24px",
    width: "min(420px, calc(100vw - 48px))",
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
    display: "flex",
    alignItems: "center",
    gap: "12px",
    paddingBlock: "10px",
    paddingInline: "12px",
  },
  title: {
    flexGrow: 1,
    flexShrink: 1,
    flexBasis: "0%",
    minWidth: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.4,
  },
  undo: {
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
    paddingBlock: "4px",
    paddingInline: "8px",
    cursor: "pointer",
  },
});

/**
 * Undo toast shown after a canvas or selection cleanup. Lives on a 10s timer
 * so accidental layout/size changes can be reverted in one click without a
 * persistent dock banner.
 */
export function CanvasCleanupNotice({
  noticeKey,
  lead,
  onUndo,
  onDismiss,
}: {
  noticeKey: string | null;
  lead: string | null;
  onUndo: () => void;
  onDismiss: () => void;
}) {
  return (
    <Toast.Provider timeout={10_000} limit={1}>
      <CanvasCleanupToast
        noticeKey={noticeKey}
        lead={lead}
        onUndo={onUndo}
        onDismiss={onDismiss}
      />
    </Toast.Provider>
  );
}

function CanvasCleanupToast({
  noticeKey,
  lead,
  onUndo,
  onDismiss,
}: {
  noticeKey: string | null;
  lead: string | null;
  onUndo: () => void;
  onDismiss: () => void;
}) {
  const { add, close, toasts } = Toast.useToastManager();
  const leadRef = React.useRef(lead);
  const onUndoRef = React.useRef(onUndo);
  const onDismissRef = React.useRef(onDismiss);

  React.useLayoutEffect(() => {
    leadRef.current = lead;
    onUndoRef.current = onUndo;
    onDismissRef.current = onDismiss;
  });

  React.useEffect(() => {
    if (lead === null || noticeKey === null) {
      close(TOAST_ID);
      return;
    }
    add({
      id: TOAST_ID,
      title: lead,
      timeout: 10_000,
      actionProps: {
        children: "Undo",
        type: "button",
        onClick: () => {
          onUndoRef.current();
        },
      },
      onClose: () => {
        if (leadRef.current === null) return;
        onDismissRef.current();
      },
    });
  }, [add, close, lead, noticeKey]);

  return (
    <Toast.Portal>
      <Toast.Viewport
        aria-label="Canvas cleanup"
        data-canvas-cleanup-notice="true"
        {...stylex.props(s.viewport)}
      >
        {toasts.map((toast) => {
          const root = stylex.props(s.root);
          return (
            <Toast.Root
              key={toast.id}
              toast={toast}
              swipeDirection="right"
              className={root.className}
              style={root.style}
            >
              <Toast.Content {...stylex.props(s.content)}>
                <Toast.Title {...stylex.props(s.title)} />
                <Toast.Action {...stylex.props(s.undo)} />
              </Toast.Content>
            </Toast.Root>
          );
        })}
      </Toast.Viewport>
    </Toast.Portal>
  );
}
