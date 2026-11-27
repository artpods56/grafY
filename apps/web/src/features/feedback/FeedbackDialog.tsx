"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Crosshair } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, TextArea } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { SegmentedControl } from "@/components/ui/segmented-control";
import type { FeedbackKind } from "@/lib/api/contract";
import { tokens } from "@/lib/stylex/tokens.stylex";

import type { FeedbackDraft, FeedbackState } from "./feedback-reducer";

export type OpenFeedbackState = Extract<
  FeedbackState,
  { phase: "composing" | "sending" }
>;

const KIND_OPTIONS = [
  { value: "bug", label: "Problem" },
  { value: "idea", label: "Idea" },
  { value: "other", label: "Other" },
] as const satisfies readonly { value: FeedbackKind; label: string }[];

const MESSAGE_LABEL: Record<FeedbackKind, string> = {
  bug: "What went wrong?",
  idea: "What would help?",
  other: "What would you like to tell us?",
};

const s = stylex.create({
  form: { display: "grid", gap: tokens.space3 },
  target: {
    display: "flex",
    alignItems: "center",
    gap: tokens.space2,
    minWidth: 0,
  },
  targetLabel: {
    flexShrink: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeSm,
  },
  targetName: {
    flexGrow: 1,
    minWidth: 0,
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
    fontSize: tokens.fontSizeSm,
    fontWeight: 600,
  },
  shot: { margin: 0, display: "grid", gap: tokens.space2 },
  shotImage: {
    display: "block",
    width: "100%",
    maxHeight: "220px",
    objectFit: "contain",
    borderWidth: "1px",
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceSunken,
    transitionProperty: "opacity",
    transitionDuration: "120ms",
  },
  shotExcluded: { opacity: 0.35 },
  shotCaption: {
    display: "flex",
    flexWrap: "wrap",
    alignItems: "center",
    justifyContent: "space-between",
    gap: tokens.space2,
  },
  hint: { margin: 0, color: tokens.colorMuted, fontSize: tokens.fontSizeXs },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: tokens.space2,
    paddingTop: tokens.space1,
  },
});

/** Write the report. Open while composing or sending; `state` is null otherwise. */
export function FeedbackDialog({
  state,
  onEdit,
  onRepick,
  onSubmit,
  onCancel,
}: {
  state: OpenFeedbackState | null;
  onEdit: (draft: Partial<FeedbackDraft>) => void;
  onRepick: () => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  // Keep the last content on screen while the dialog animates closed.
  const [shown, setShown] = React.useState(state);
  if (state !== null && state !== shown) setShown(state);
  const sending = state?.phase === "sending";

  return (
    <Dialog
      open={state !== null}
      onOpenChange={(open) => {
        if (!open && !sending) onCancel();
      }}
    >
      <DialogContent size="form" data-feedback-ui="">
        <DialogHeader>
          <DialogTitle>Send feedback</DialogTitle>
          <DialogDescription>
            The people who run this Grafy deployment read every report.
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          {shown ? (
            <form
              {...stylex.props(s.form)}
              onSubmit={(event) => {
                event.preventDefault();
                onSubmit();
              }}
            >
              <div {...stylex.props(s.target)}>
                <span {...stylex.props(s.targetLabel)}>About</span>
                <span
                  {...stylex.props(s.targetName)}
                  title={shown.target?.element.selector}
                >
                  {shown.target ? shown.target.name : "The whole page"}
                </span>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={onRepick}
                  disabled={sending}
                >
                  <Crosshair size={13} aria-hidden="true" />
                  {shown.target ? "Pick again" : "Pick an element"}
                </Button>
              </div>

              {shown.screenshot.status === "ready" ? (
                <figure {...stylex.props(s.shot)}>
                  <img /* eslint-disable-line @next/next/no-img-element -- blob: URL of a screenshot taken in this tab */
                    src={shown.screenshot.url}
                    alt={`Screenshot of ${shown.target?.name ?? "the page"}`}
                    {...stylex.props(
                      s.shotImage,
                      !shown.draft.includeScreenshot && s.shotExcluded,
                    )}
                  />
                  <figcaption {...stylex.props(s.shotCaption)}>
                    <Checkbox
                      checked={shown.draft.includeScreenshot}
                      onCheckedChange={(checked) =>
                        onEdit({ includeScreenshot: checked })
                      }
                      label="Include screenshot"
                      disabled={sending}
                    />
                    {shown.screenshot.mayMissCanvas ? (
                      <span {...stylex.props(s.hint)}>
                        Maps and scans can come out blank.
                      </span>
                    ) : null}
                  </figcaption>
                </figure>
              ) : null}
              {shown.screenshot.status === "failed" ? (
                <p {...stylex.props(s.hint)}>
                  A screenshot could not be taken. Describe what you see
                  instead.
                </p>
              ) : null}

              <SegmentedControl<FeedbackKind>
                aria-label="Kind of feedback"
                size="md"
                value={shown.draft.kind}
                options={KIND_OPTIONS}
                onValueChange={(kind) => onEdit({ kind })}
                disabled={sending}
              />
              <Field label={MESSAGE_LABEL[shown.draft.kind]}>
                <TextArea
                  autoFocus
                  rows={5}
                  maxLength={4000}
                  value={shown.draft.message}
                  onChange={(event) =>
                    onEdit({ message: event.currentTarget.value })
                  }
                  disabled={sending}
                />
              </Field>
              {shown.phase === "composing" && shown.error ? (
                <Notice tone="danger">{shown.error}</Notice>
              ) : null}
              <div {...stylex.props(s.actions)}>
                <Button
                  type="button"
                  variant="secondary"
                  size="md"
                  onClick={onCancel}
                  disabled={sending}
                >
                  Cancel
                </Button>
                <Button
                  type="submit"
                  variant="primary"
                  size="md"
                  disabled={sending || shown.draft.message.trim() === ""}
                >
                  {sending ? "Sending…" : "Send"}
                </Button>
              </div>
            </form>
          ) : null}
        </DialogBody>
      </DialogContent>
    </Dialog>
  );
}
