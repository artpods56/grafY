"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";

import { Field, TextArea } from "@/components/ui/field";
import { Notice } from "@/components/ui/notice";
import { tokens } from "@/lib/stylex/tokens.stylex";

import { ArtifactEditorActions } from "./editor-actions";
import type { ArtifactEditorProps } from "./types";

const s = stylex.create({
  root: {
    display: "grid",
    gap: tokens.space3,
    minHeight: 0,
  },
  editor: {
    minHeight: "12rem",
    resize: "vertical",
  },
});

export function textPayloadValue(payload: Record<string, unknown>): string {
  return typeof payload.value === "string" ? payload.value : "";
}

export function textCounts(value: string): {
  characters: number;
  lines: number;
} {
  return {
    characters: value.length,
    lines: value.length === 0 ? 1 : value.split("\n").length,
  };
}

export function TextArtifactEditor({
  initialPayload,
  saving = false,
  error = null,
  onSave,
  onCancel,
  onDraftChange,
}: ArtifactEditorProps) {
  const initialValue = textPayloadValue(initialPayload);
  const [value, setValue] = React.useState(initialValue);
  const counts = textCounts(value);

  const update = (next: string) => {
    setValue(next);
    onDraftChange?.({ value: next });
  };

  return (
    <div {...stylex.props(s.root)}>
      <Field
        label="Text"
        aside={`${counts.characters} characters · ${counts.lines} ${counts.lines === 1 ? "line" : "lines"}`}
      >
        <TextArea
          rows={12}
          value={value}
          xstyle={s.editor}
          onChange={(event) => update(event.target.value)}
        />
      </Field>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <ArtifactEditorActions
        saving={saving}
        onReset={() => update(initialValue)}
        onCancel={onCancel}
        onSave={() => void onSave({ value })}
      />
    </div>
  );
}
