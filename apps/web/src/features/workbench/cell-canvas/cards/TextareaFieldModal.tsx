"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { Maximize2 } from "lucide-react";

import { Button, IconButton } from "@/components/ui/button";
import { TextArea } from "@/components/ui/field";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { WorkbenchModal } from "../../authoring/WorkbenchModal";
import {
  fieldDisplayTitle,
  type SchemaField,
} from "../../config-ui/config-schema";

/**
 * A prompt, long enough to be worth reading, cannot be written in the 78px box
 * a card's 25px lattice gives it. This is that box's way out: a quiet expand
 * control in the field's label row and the same value in a `WorkbenchModal`
 * wide enough to see a whole prompt in.
 *
 * The card's inline `<TextArea>` stays exactly as it was — quick edits and
 * previews belong there. What the modal adds is room, a length readout, and a
 * dismiss guard: Escape, the backdrop and the Close button ask before throwing
 * an unapplied draft away, while `Cancel` is the explicit way to do it.
 *
 * The draft is the person's, and only the opening of the modal takes it from
 * the stored value. A collaborator's edit or an undo therefore cannot replace
 * a prompt halfway through a sentence; reopening reads the card afresh.
 */
const s = stylex.create({
  /** The editor fills the `bodyLayout="fill"` body and scrolls on its own. */
  editor: {
    flex: 1,
    minHeight: "320px",
    resize: "none",
    paddingBlock: tokens.space3,
    paddingInline: tokens.space3,
    fontSize: tokens.fontSizeSm,
    lineHeight: 1.6,
  },
  footer: {
    minWidth: 0,
    flexGrow: 1,
    flexBasis: 0,
    display: "flex",
    alignItems: "center",
    gap: tokens.space2,
  },
  stats: {
    minWidth: 0,
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontVariantNumeric: "tabular-nums",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  /** What the footer says about a draft the schema will not accept. */
  warning: { color: tokens.colorDanger },
  actions: {
    flexShrink: 0,
    display: "flex",
    alignItems: "center",
    gap: tokens.space2,
  },
});

export interface TextareaFieldModalProps {
  /** The field being edited: its title, description, and length limits. */
  field: SchemaField;
  /** The value the card holds. The modal starts from it every time it opens. */
  value: string;
  /** A card that cannot be edited reads the value in the modal instead. */
  readOnly: boolean;
  /** Writes an applied draft the way the card's inline control does. */
  onApply: (value: string) => void;
}

function lineCount(text: string): number {
  return text === "" ? 0 : text.split("\n").length;
}

/**
 * The expand control and the editor it opens. The call site owns where the
 * control sits; on a canvas card that is the field's label row.
 */
export function TextareaFieldModal({
  field,
  value,
  readOnly,
  onApply,
}: TextareaFieldModalProps) {
  const [open, setOpen] = React.useState(false);
  const [draft, setDraft] = React.useState(value);
  const [wasOpen, setWasOpen] = React.useState(false);
  if (open !== wasOpen) {
    setWasOpen(open);
    // Only the opening reads the card: `value` may have moved underneath a
    // draft in progress, and a prompt must not change while it is being typed.
    if (open) setDraft(value);
  }

  const title = fieldDisplayTitle(field);
  const minLength = field.minLength;
  const maxLength = field.maxLength;
  const tooShort = minLength !== undefined && draft.length < minLength;
  const tooLong = maxLength !== undefined && draft.length > maxLength;
  const dirty = !readOnly && draft !== value;
  const canApply = dirty && !tooShort && !tooLong;

  // Applying an unchanged draft is a no-op, so the shortcut closes as well.
  const commit = () => {
    if (readOnly || tooShort || tooLong) return;
    if (draft !== value) onApply(draft);
    setOpen(false);
  };
  const resetDraft = () => setDraft(value);
  const discardAndClose = () => {
    resetDraft();
    setOpen(false);
  };

  const lines = lineCount(draft);
  const length =
    maxLength === undefined
      ? `${draft.length} characters`
      : `${draft.length}/${maxLength} characters`;
  const tooShortMessage =
    minLength === undefined || draft.length >= minLength
      ? null
      : `At least ${minLength} characters.`;
  const tooLongMessage =
    maxLength === undefined || draft.length <= maxLength
      ? null
      : `At most ${maxLength} characters.`;

  return (
    <>
      <IconButton
        type="button"
        size="2xs"
        variant="ghost"
        className="nodrag nopan"
        label={`Expand ${title}`}
        onClick={() => setOpen(true)}
      >
        <Maximize2 size={11} />
      </IconButton>
      <WorkbenchModal
        open={open}
        onOpenChange={setOpen}
        size="wide"
        bodyLayout="fill"
        title={title}
        description={field.description}
        dirty={dirty}
        onDiscard={resetDraft}
        footer={
          <>
            <span {...stylex.props(s.footer)}>
              <span {...stylex.props(s.stats)}>
                {`${length} · ${lines} ${lines === 1 ? "line" : "lines"}`}
              </span>
              {tooShortMessage || tooLongMessage ? (
                <span role="alert" {...stylex.props(s.stats, s.warning)}>
                  {tooShortMessage ?? tooLongMessage}
                </span>
              ) : null}
            </span>
            <span {...stylex.props(s.actions)}>
              {readOnly ? (
                <Button
                  type="button"
                  variant="primary"
                  size="sm"
                  onClick={discardAndClose}
                >
                  Close
                </Button>
              ) : (
                <>
                  {/* Cancel is the deliberate way out: it drops the draft at
                      once, where Escape and the Close button ask first. */}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={discardAndClose}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="button"
                    variant="primary"
                    size="sm"
                    disabled={!canApply}
                    onClick={commit}
                  >
                    Apply
                  </Button>
                </>
              )}
            </span>
          </>
        }
      >
        <TextArea
          aria-label={title}
          value={draft}
          placeholder={
            typeof field.defaultValue === "string"
              ? field.defaultValue
              : undefined
          }
          minLength={minLength}
          maxLength={maxLength}
          disabled={readOnly}
          xstyle={s.editor}
          onChange={(event) => setDraft(event.currentTarget.value)}
          onKeyDown={(event) => {
            if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
              event.preventDefault();
              commit();
            }
          }}
        />
      </WorkbenchModal>
    </>
  );
}
