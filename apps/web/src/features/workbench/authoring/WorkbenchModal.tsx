"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogBody,
  DialogContent,
  type DialogContentSize,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { tokens } from "@/lib/stylex/tokens.stylex";

import {
  workbenchModalInitialState,
  workbenchModalReducer,
} from "./workbench-modal-reducer";

/**
 * The shared shell for workbench editors that need more room than a canvas
 * card: a textarea config field popped out, a fullscreen TIFF view, a future
 * direct artifact editor. It owns the frame — header, body, optional sticky
 * footer — and the dismiss guard: with `dirty`, Escape, the backdrop, and the
 * Close button all route through `workbench-modal-reducer.ts`, which asks
 * before discarding.
 *
 * The popup geometry belongs to `DialogContent`'s `size` prop; this component
 * never overrides width, height, or the responsive frame inline. `bodyLayout`
 * only picks the body's own layout: `"scroll"` keeps the kit's padded scroll
 * area, `"fill"` makes it a full-bleed flex column for surfaces (OpenSeadragon,
 * editors) that draw their own chrome.
 */
const s = stylex.create({
  headerRow: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: tokens.space3,
  },
  headerText: {
    flexGrow: 1,
    minWidth: 0,
  },
  headerActions: {
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    gap: tokens.space2,
    // `DialogContent`'s Close button is anchored 12px from the right edge and
    // is 28px wide, so actions stop 20px past the header's own padding and
    // stay clear of it.
    marginRight: "20px",
  },
  discard: {
    display: "grid",
    gap: "8px",
    padding: "10px 12px",
    marginTop: 0,
    marginBottom: tokens.space2,
    marginLeft: {
      default: tokens.space4,
      "@media (max-width: 620px)": `calc(${tokens.space4} + env(safe-area-inset-left, 0px))`,
    },
    marginRight: {
      default: tokens.space4,
      "@media (max-width: 620px)": `calc(${tokens.space4} + env(safe-area-inset-right, 0px))`,
    },
    borderRadius: tokens.radiusMd,
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: `color-mix(in oklab, ${tokens.colorWarning} 30%, transparent)`,
    backgroundColor: tokens.colorWarningSoft,
  },
  discardTitle: {
    margin: 0,
    color: tokens.colorWarning,
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
  },
  discardBody: {
    margin: 0,
    color: tokens.colorText,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  discardActions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: "8px",
  },
  /** Full-bleed body: no scroll, no padding, children fill the modal. */
  bodyFill: {
    flex: 1,
    minHeight: 0,
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
    paddingTop: 0,
    paddingRight: 0,
    paddingBottom: 0,
    paddingLeft: 0,
  },
  footer: {
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    gap: tokens.space3,
    paddingTop: tokens.space2,
    paddingBottom: {
      default: tokens.space3,
      "@media (max-width: 620px)": `calc(${tokens.space3} + env(safe-area-inset-bottom, 0px))`,
    },
    paddingLeft: {
      default: tokens.space4,
      "@media (max-width: 620px)": `calc(${tokens.space4} + env(safe-area-inset-left, 0px))`,
    },
    paddingRight: {
      default: tokens.space4,
      "@media (max-width: 620px)": `calc(${tokens.space4} + env(safe-area-inset-right, 0px))`,
    },
    borderTopWidth: "1px",
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
  },
});

export interface WorkbenchModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  /** Passed straight to `DialogContent`; the frame geometry stays there. */
  size?: DialogContentSize;
  /**
   * `"scroll"` (default) keeps the kit body's padded scroll area; `"fill"`
   * turns the body into a full-bleed flex column for interactive surfaces.
   */
  bodyLayout?: "scroll" | "fill";
  /** When true, close attempts ask before discarding unsaved edits. */
  dirty?: boolean;
  discardTitle?: string;
  discardBody?: string;
  /** Called when the person confirms the discard, right before closing. */
  onDiscard?: () => void;
  /** Right-aligned actions in the header row, clear of the Close button. */
  headerActions?: React.ReactNode;
  /** Sticky bar pinned to the bottom of the modal. */
  footer?: React.ReactNode;
  children: React.ReactNode;
}

/** The popup is portalled out of a canvas card's DOM but not out of its React tree. */
const stopCanvasGesture = (event: React.SyntheticEvent) => {
  event.stopPropagation();
};

export function WorkbenchModal({
  open,
  onOpenChange,
  title,
  description,
  size = "wide",
  bodyLayout = "scroll",
  dirty = false,
  discardTitle = "Unsaved changes",
  discardBody = "Closing now will discard your unsaved edits.",
  onDiscard,
  headerActions,
  footer,
  children,
}: WorkbenchModalProps) {
  const [state, dispatch] = React.useReducer(
    workbenchModalReducer,
    open,
    workbenchModalInitialState,
  );

  // The controlled `open` prop is authoritative from the outside.
  React.useEffect(() => {
    dispatch({ type: "sync_open", open });
  }, [open]);

  // A close the reducer accepted is reported back through `onOpenChange`.
  React.useEffect(() => {
    if (state.phase === "closed" && open) onOpenChange(false);
  }, [state.phase, open, onOpenChange]);

  return (
    <Dialog
      open={state.phase !== "closed"}
      onOpenChange={(next) => {
        if (next) {
          dispatch({ type: "sync_open", open: true });
        } else {
          dispatch({ type: "request_close", dirty });
        }
      }}
    >
      <DialogContent
        size={size}
        className="nodrag nopan nowheel"
        data-workbench-modal=""
        onPointerDown={stopCanvasGesture}
        onWheel={stopCanvasGesture}
      >
        <DialogHeader>
          <div {...stylex.props(s.headerRow)}>
            <div {...stylex.props(s.headerText)}>
              <DialogTitle>{title}</DialogTitle>
              {description ? (
                <DialogDescription>{description}</DialogDescription>
              ) : null}
            </div>
            {headerActions ? (
              <div {...stylex.props(s.headerActions)}>{headerActions}</div>
            ) : null}
          </div>
        </DialogHeader>
        {state.phase === "confirming_discard" ? (
          <div
            role="alert"
            data-workbench-modal-discard=""
            {...stylex.props(s.discard)}
          >
            <p {...stylex.props(s.discardTitle)}>{discardTitle}</p>
            <p {...stylex.props(s.discardBody)}>{discardBody}</p>
            <div {...stylex.props(s.discardActions)}>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                onClick={() => dispatch({ type: "keep_editing" })}
              >
                Keep editing
              </Button>
              <Button
                type="button"
                size="sm"
                variant="danger"
                onClick={() => {
                  onDiscard?.();
                  dispatch({ type: "confirm_discard" });
                }}
              >
                Discard
              </Button>
            </div>
          </div>
        ) : null}
        <DialogBody
          className={
            bodyLayout === "fill"
              ? stylex.props(s.bodyFill).className
              : undefined
          }
          data-body-layout={bodyLayout}
        >
          {children}
        </DialogBody>
        {footer ? (
          <div {...stylex.props(s.footer)} data-workbench-modal-footer="">
            {footer}
          </div>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
