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
    minHeight: "16rem",
    resize: "vertical",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
  },
});

export function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2) ?? "";
  } catch {
    return "";
  }
}

export function parseJsonObject(
  text: string,
): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text) as unknown;
  } catch (error) {
    return {
      ok: false,
      error:
        error instanceof SyntaxError
          ? error.message
          : "This is not valid JSON.",
    };
  }
  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    return {
      ok: false,
      error: "JSON must be an object, not an array or value.",
    };
  }
  return { ok: true, value: parsed as Record<string, unknown> };
}

export function JsonArtifactEditor({
  initialPayload,
  saving = false,
  error = null,
  onSave,
  onCancel,
  onDraftChange,
}: ArtifactEditorProps) {
  const initialText = React.useMemo(
    () => prettyJson(initialPayload),
    [initialPayload],
  );
  const [text, setText] = React.useState(initialText);
  const parsed = React.useMemo(() => parseJsonObject(text), [text]);

  const update = (next: string) => {
    setText(next);
    const result = parseJsonObject(next);
    if (result.ok) onDraftChange?.(result.value);
  };

  return (
    <div {...stylex.props(s.root)}>
      <Field
        label="JSON"
        error={parsed.ok ? undefined : parsed.error}
        description={
          parsed.ok ? "An object the artifact stores as-is." : undefined
        }
      >
        <TextArea
          mono
          rows={16}
          value={text}
          spellCheck={false}
          aria-invalid={!parsed.ok}
          xstyle={s.editor}
          onChange={(event) => update(event.target.value)}
        />
      </Field>
      {error ? <Notice tone="danger">{error}</Notice> : null}
      <ArtifactEditorActions
        saving={saving}
        saveDisabled={!parsed.ok}
        onReset={() => update(initialText)}
        onCancel={onCancel}
        onSave={() => {
          if (parsed.ok) void onSave(parsed.value);
        }}
      />
    </div>
  );
}
