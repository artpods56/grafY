"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { AlertTriangle } from "lucide-react";

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { tokens } from "@/lib/stylex/tokens.stylex";

const s = stylex.create({
  form: { display: "flex", flexDirection: "column", gap: tokens.space3 },
  label: {
    display: "flex",
    flexDirection: "column",
    gap: tokens.space2,
    color: tokens.colorText,
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
  },
  textarea: {
    minHeight: "130px",
    resize: "vertical",
    padding: tokens.space3,
    border: `1px solid ${tokens.colorBorder}`,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    font: "inherit",
    lineHeight: 1.5,
  },
  note: { margin: 0, color: tokens.colorMuted, fontSize: tokens.fontSizeXs, lineHeight: 1.5 },
  error: { display: "flex", gap: tokens.space2, margin: 0, color: tokens.colorDanger, fontSize: tokens.fontSizeSm },
  actions: { display: "flex", justifyContent: "flex-end", marginTop: tokens.space2 },
});

interface AgentIterationDialogProps {
  open: boolean;
  nodeTitle: string;
  currentVersion: number;
  pending: boolean;
  error: string | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (prompt: string) => void;
}

export function AgentIterationDialog({
  open,
  nodeTitle,
  currentVersion,
  pending,
  error,
  onOpenChange,
  onSubmit,
}: AgentIterationDialogProps) {
  const [prompt, setPrompt] = React.useState("");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent size="form">
        <DialogHeader>
          <DialogTitle>Iterate on {nodeTitle}</DialogTitle>
          <DialogDescription>
            Continue the existing agent thread with a focused change request.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          <form
            {...stylex.props(s.form)}
            onSubmit={(event) => {
              event.preventDefault();
              const normalized = prompt.trim();
              if (normalized) onSubmit(normalized);
            }}
          >
            <label {...stylex.props(s.label)}>
              What should change?
              <textarea
                autoFocus
                maxLength={20_000}
                value={prompt}
                disabled={pending}
                placeholder="For example: preserve empty values and add a regression test."
                {...stylex.props(s.textarea)}
                onChange={(event) => setPrompt(event.currentTarget.value)}
              />
            </label>
            <p {...stylex.props(s.note)}>
              Version {currentVersion} stays runnable while the next revision is
              authored, tested, reviewed, and approved.
            </p>
            {error ? (
              <p role="alert" {...stylex.props(s.error)}>
                <AlertTriangle size={14} aria-hidden="true" /> {error}
              </p>
            ) : null}
            <div {...stylex.props(s.actions)}>
              <button
                type="submit"
                className="grafy-workspace-button grafy-workspace-button--primary"
                disabled={pending || prompt.trim().length === 0}
              >
                {pending ? "Starting revision…" : `Build version ${currentVersion + 1}`}
              </button>
            </div>
          </form>
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
