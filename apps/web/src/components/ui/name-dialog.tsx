"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { tokens } from "@/lib/stylex/tokens.stylex";

export const NAME_MAX_LENGTH = 160;

interface NameDialogProps {
  open: boolean;
  title: string;
  description?: string;
  /** Accessible name of the field. */
  label: string;
  placeholder?: string;
  initialName: string;
  submitLabel?: string;
  onSubmit: (name: string) => void;
  onClose: () => void;
}

const s = stylex.create({
  form: { display: "grid", gap: "12px" },
  input: {
    minHeight: "36px",
    paddingInline: "10px",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: {
      default: tokens.colorBorder,
      ":focus": tokens.colorAccent,
    },
    borderRadius: "6px",
    outline: "none",
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
  },
  actions: { display: "flex", justifyContent: "flex-end", gap: "8px" },
  cancel: {
    minHeight: "32px",
    paddingInline: "12px",
    borderWidth: 0,
    borderRadius: "6px",
    backgroundColor: { default: "transparent", ":hover": tokens.colorHover },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
  },
  save: {
    minHeight: "32px",
    paddingInline: "14px",
    borderWidth: 0,
    borderRadius: "6px",
    backgroundColor: tokens.colorAccent,
    color: tokens.colorOnAccent,
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    opacity: { default: 1, ":disabled": 0.5 },
    fontSize: tokens.fontSizeSm,
    fontWeight: 650,
  },
});

/**
 * Asks for a name in a modal. It stands in for `window.prompt`, which embedded
 * browsers and webviews refuse to show. Submitted names are trimmed and held to
 * `NAME_MAX_LENGTH`; a blank name cannot be submitted.
 */
export function NameDialog({ open, onClose, ...form }: NameDialogProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent size="compact">
        {/* Remounts per opening so the field starts from the current name. */}
        {open ? <NameForm {...form} onClose={onClose} /> : null}
      </DialogContent>
    </Dialog>
  );
}

function NameForm({
  title,
  description,
  label,
  placeholder,
  initialName,
  submitLabel = "Save",
  onSubmit,
  onClose,
}: Omit<NameDialogProps, "open">) {
  const [name, setName] = React.useState(initialName);
  const trimmed = name.trim();
  return (
    <>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        {description ? (
          <DialogDescription>{description}</DialogDescription>
        ) : null}
      </DialogHeader>
      <DialogBody>
        <form
          {...stylex.props(s.form)}
          onSubmit={(event) => {
            event.preventDefault();
            if (!trimmed) return;
            onSubmit(trimmed.slice(0, NAME_MAX_LENGTH));
          }}
        >
          <input
            {...stylex.props(s.input)}
            autoFocus
            aria-label={label}
            maxLength={NAME_MAX_LENGTH}
            placeholder={placeholder}
            value={name}
            onChange={(event) => setName(event.target.value)}
            onFocus={(event) => event.currentTarget.select()}
          />
          <div {...stylex.props(s.actions)}>
            <button type="button" {...stylex.props(s.cancel)} onClick={onClose}>
              Cancel
            </button>
            <button type="submit" disabled={!trimmed} {...stylex.props(s.save)}>
              {submitLabel}
            </button>
          </div>
        </form>
      </DialogBody>
    </>
  );
}
