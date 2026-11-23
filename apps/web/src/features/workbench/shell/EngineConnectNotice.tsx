"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Toast } from "@base-ui/react/toast";

import { tokens } from "@/lib/stylex/tokens.stylex";

const TOAST_ID = "engine-connect";

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
      ":hover": tokens.colorHover,
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
 * One connect toast. The Undo action lives on the toast, so it expires with
 * the 8 second timeout instead of sitting in a fixed dock.
 */
export function EngineConnectNotice({
  lead,
  onUndo,
  onDismiss,
}: {
  lead: string | null;
  onUndo: () => void;
  onDismiss: () => void;
}) {
  return (
    <Toast.Provider timeout={8000} limit={1}>
      <EngineConnectToast lead={lead} onUndo={onUndo} onDismiss={onDismiss} />
    </Toast.Provider>
  );
}

function EngineConnectToast({
  lead,
  onUndo,
  onDismiss,
}: {
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
    if (lead === null) {
      close(TOAST_ID);
      return;
    }
    add({
      id: TOAST_ID,
      title: lead,
      timeout: 8000,
      actionProps: {
        children: "Undo",
        type: "button",
        onClick: () => {
          onUndoRef.current();
        },
      },
      onClose: () => {
        // close() after undo or a graph switch runs with the lead already
        // cleared. Dismissing again would fight the next notice.
        if (leadRef.current === null) return;
        onDismissRef.current();
      },
    });
  }, [add, close, lead]);

  return (
    <Toast.Portal>
      <Toast.Viewport
        aria-label="Engine connection"
        data-engine-connect-notice="true"
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
