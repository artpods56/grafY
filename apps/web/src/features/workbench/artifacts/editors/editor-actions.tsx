"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { Button } from "@/components/ui/button";
import { Notice } from "@/components/ui/notice";
import { tokens } from "@/lib/stylex/tokens.stylex";

const s = stylex.create({
  bar: {
    display: "flex",
    justifyContent: "flex-end",
    alignItems: "center",
    gap: tokens.space2,
    flexWrap: "wrap",
  },
  notice: {
    flex: "1 1 12rem",
    minWidth: 0,
  },
});

export function ArtifactEditorActions({
  saving = false,
  error = null,
  saveDisabled = false,
  onReset,
  onCancel,
  onSave,
  resetLabel = "Reset",
  extra,
}: {
  saving?: boolean;
  error?: string | null;
  saveDisabled?: boolean;
  onReset?: () => void;
  onCancel: () => void;
  onSave: () => void;
  resetLabel?: string;
  extra?: React.ReactNode;
}) {
  return (
    <div {...stylex.props(s.bar)}>
      {error ? (
        <Notice tone="danger" xstyle={s.notice}>
          {error}
        </Notice>
      ) : null}
      {extra}
      {onReset ? (
        <Button
          type="button"
          variant="ghost"
          size="sm"
          disabled={saving}
          onClick={onReset}
        >
          {resetLabel}
        </Button>
      ) : null}
      <Button
        type="button"
        variant="secondary"
        size="sm"
        disabled={saving}
        onClick={onCancel}
      >
        Cancel
      </Button>
      <Button
        type="button"
        variant="primary"
        size="sm"
        disabled={saving || saveDisabled}
        onClick={onSave}
      >
        {saving ? "Saving…" : "Save"}
      </Button>
    </div>
  );
}
