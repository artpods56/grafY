"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { cx } from "@/lib/utils";

const s = stylex.create({
  overlay: {
    position: "fixed",
    zIndex: 100,
    inset: 0,
    backgroundColor: "light-dark(rgba(17, 17, 17, 0.32), rgba(0, 0, 0, 0.55))",
  },
  content: {
    position: "fixed",
    zIndex: 100,
    left: "50%",
    top: "50%",
    transform: "translate(-50%, -50%)",
    borderRadius: tokens.radiusLg,
    backgroundColor: tokens.colorSurface,
    border: `1px solid ${tokens.colorBorder}`,
    display: "flex",
    flexDirection: "column",
    overflow: "hidden",
    maxWidth: {
      default: "92vw",
      "@media (max-width: 620px)": "calc(100vw - 24px)",
    },
    height: "auto",
    maxHeight: {
      default: "85vh",
      "@media (max-width: 620px)": "calc(100dvh - 32px)",
    },
  },
  sizeCompact: {
    width: {
      default: "430px",
      "@media (max-width: 620px)": "100vw",
    },
  },
  sizeDefault: {
    width: {
      default: "640px",
      "@media (max-width: 620px)": "100vw",
    },
  },
  sizeForm: {
    width: {
      default: "520px",
      "@media (max-width: 620px)": "100vw",
    },
  },
  sizeWide: {
    width: {
      default: "min(960px, 94vw)",
      "@media (max-width: 620px)": "calc(100vw - 24px)",
    },
    maxWidth: {
      default: "94vw",
      "@media (max-width: 620px)": "calc(100vw - 24px)",
    },
    maxHeight: {
      default: "90vh",
      "@media (max-width: 620px)": "calc(100dvh - 32px)",
    },
  },
  sizeViewport: {
    width: {
      default: "min(1340px, calc(100vw - 28px))",
      "@media (max-width: 720px)": "calc(100vw - 16px)",
    },
    maxWidth: "none",
    height: {
      default: "min(900px, calc(100svh - 28px))",
      "@media (max-width: 720px)": "calc(100svh - 16px)",
    },
    maxHeight: "none",
  },
  sizeCatalog: {
    width: "min(1040px, calc(100vw - 24px))",
    maxWidth: "none",
    height: "min(680px, calc(100dvh - 40px))",
    maxHeight: "none",
  },
  header: {
    paddingTop: {
      default: tokens.space4,
      "@media (max-width: 620px)": `calc(${tokens.space4} + env(safe-area-inset-top, 0px))`,
    },
    paddingRight: {
      default: tokens.space6,
      "@media (max-width: 620px)": `calc(60px + env(safe-area-inset-right, 0px))`,
    },
    paddingBottom: tokens.space2,
    paddingLeft: {
      default: tokens.space4,
      "@media (max-width: 620px)": `calc(${tokens.space4} + env(safe-area-inset-left, 0px))`,
    },
  },
  title: {
    fontSize: tokens.fontSizeLg,
    fontWeight: 700,
    color: tokens.colorText,
    lineHeight: 1.3,
  },
  description: {
    fontSize: tokens.fontSizeSm,
    color: tokens.colorMuted,
    marginTop: tokens.space1,
  },
  body: {
    paddingTop: tokens.space2,
    paddingRight: {
      default: tokens.space4,
      "@media (max-width: 620px)": `calc(${tokens.space4} + env(safe-area-inset-right, 0px))`,
    },
    paddingBottom: {
      default: tokens.space4,
      "@media (max-width: 620px)": `calc(${tokens.space4} + env(safe-area-inset-bottom, 0px))`,
    },
    paddingLeft: {
      default: tokens.space4,
      "@media (max-width: 620px)": `calc(${tokens.space4} + env(safe-area-inset-left, 0px))`,
    },
    overflow: "auto",
    flex: 1,
  },
  close: {
    position: "absolute",
    top: {
      default: tokens.space3,
      "@media (max-width: 620px)": `calc(${tokens.space1} + env(safe-area-inset-top, 0px))`,
    },
    right: {
      default: tokens.space3,
      "@media (max-width: 620px)": `calc(${tokens.space1} + env(safe-area-inset-right, 0px))`,
    },
    display: "inline-flex",
    alignItems: "center",
    justifyContent: "center",
    height: {
      default: "28px",
      "@media (max-width: 620px)": "44px",
    },
    width: {
      default: "28px",
      "@media (max-width: 620px)": "44px",
    },
    borderRadius: tokens.radiusSm,
    color: tokens.colorMuted,
    backgroundColor: "transparent",
    border: "none",
    cursor: "pointer",
  },
});

export const Dialog = DialogPrimitive.Root;

export type DialogContentSize =
  "compact" | "default" | "form" | "wide" | "catalog" | "viewport";

const dialogSizeStyles = {
  compact: s.sizeCompact,
  default: s.sizeDefault,
  form: s.sizeForm,
  wide: s.sizeWide,
  catalog: s.sizeCatalog,
  viewport: s.sizeViewport,
} satisfies Record<DialogContentSize, stylex.StyleXStyles>;

export const DialogContent = React.forwardRef<
  HTMLDivElement,
  Omit<
    React.ComponentPropsWithoutRef<typeof DialogPrimitive.Popup>,
    "className"
  > & {
    className?: string;
    size?: DialogContentSize;
  }
>(({ className, children, size = "default", ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Backdrop
      className={cx(stylex.props(s.overlay).className, "grafy-dialog-backdrop")}
    />
    <DialogPrimitive.Popup
      ref={ref}
      className={cx(
        stylex.props(s.content, dialogSizeStyles[size]).className,
        "grafy-dialog-popup",
        className,
      )}
      {...props}
    >
      {children}
      <DialogPrimitive.Close {...stylex.props(s.close)} aria-label="Close">
        <X size={16} />
      </DialogPrimitive.Close>
    </DialogPrimitive.Popup>
  </DialogPrimitive.Portal>
));
DialogContent.displayName = "DialogContent";

export function DialogHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cx(stylex.props(s.header).className, className)}
      {...props}
    />
  );
}

export const DialogTitle = React.forwardRef<
  HTMLHeadingElement,
  Omit<
    React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>,
    "className"
  > & {
    className?: string;
  }
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cx(stylex.props(s.title).className, className)}
    {...props}
  />
));
DialogTitle.displayName = "DialogTitle";

export const DialogDescription = React.forwardRef<
  HTMLParagraphElement,
  Omit<
    React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>,
    "className"
  > & {
    className?: string;
  }
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cx(stylex.props(s.description).className, className)}
    {...props}
  />
));
DialogDescription.displayName = "DialogDescription";

export function DialogBody({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx(stylex.props(s.body).className, className)} {...props} />
  );
}
