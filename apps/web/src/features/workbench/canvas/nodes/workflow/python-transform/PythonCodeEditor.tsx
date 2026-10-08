"use client";

import * as React from "react";
import { EditorState } from "@codemirror/state";
import {
  EditorView,
  drawSelection,
  highlightActiveLine,
  highlightSpecialChars,
  keymap,
  lineNumbers,
} from "@codemirror/view";
import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from "@codemirror/commands";
import {
  HighlightStyle,
  bracketMatching,
  indentOnInput,
  syntaxHighlighting,
} from "@codemirror/language";
import { python } from "@codemirror/lang-python";
import { setDiagnostics } from "@codemirror/lint";
import { tags } from "@lezer/highlight";
import type { ApplyPythonCodeResponse } from "@/lib/api";

const ink = "light-dark(#111111, #F5F5F5)";
const muted = "light-dark(#6B6B6B, #8A8A8A)";

const pythonHighlight = HighlightStyle.define([
  { tag: tags.comment, color: muted, fontStyle: "italic" },
  { tag: tags.keyword, color: ink, fontWeight: "600" },
  {
    tag: [
      tags.string,
      tags.special(tags.string),
      tags.number,
      tags.bool,
      tags.null,
    ],
    color: "light-dark(#3F3F3F, #D4D4D4)",
  },
  {
    tag: [tags.function(tags.variableName), tags.className, tags.typeName],
    color: ink,
  },
]);

export function PythonCodeEditor({
  code,
  disabled,
  diagnostics,
  onChange,
}: {
  code: string;
  disabled: boolean;
  diagnostics: ApplyPythonCodeResponse["diagnostics"];
  onChange: (code: string) => void;
}) {
  const host = React.useRef<HTMLDivElement>(null);
  const editor = React.useRef<EditorView | null>(null);
  const latest = React.useRef(onChange);
  React.useEffect(() => {
    latest.current = onChange;
  }, [onChange]);
  React.useEffect(() => {
    if (!host.current) return;
    const view = new EditorView({
      parent: host.current,
      state: EditorState.create({
        doc: code,
        extensions: [
          lineNumbers(),
          highlightSpecialChars(),
          history(),
          drawSelection(),
          indentOnInput(),
          bracketMatching(),
          highlightActiveLine(),
          syntaxHighlighting(pythonHighlight),
          keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
          EditorView.lineWrapping,
          python(),
          EditorState.readOnly.of(disabled),
          EditorView.editable.of(!disabled),
          EditorView.contentAttributes.of({
            "aria-label": "Python transform code",
          }),
          EditorView.theme({
            "&": {
              minHeight: "148px",
              fontSize: "12px",
              color: ink,
              backgroundColor: "transparent",
            },
            "&.cm-focused": { outline: "none" },
            ".cm-scroller": {
              overflow: "auto",
              fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
              lineHeight: "1.45",
            },
            ".cm-content": { padding: "8px 0" },
            ".cm-gutters": {
              backgroundColor: "transparent",
              color: muted,
              border: "none",
            },
            ".cm-activeLine, .cm-activeLineGutter": {
              backgroundColor:
                "light-dark(rgba(17, 17, 17, 0.04), rgba(255, 255, 255, 0.05))",
            },
            ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
              backgroundColor:
                "light-dark(rgba(17, 17, 17, 0.12), rgba(255, 255, 255, 0.16))",
            },
          }),
          EditorView.updateListener.of((update) => {
            if (update.docChanged) latest.current(update.state.doc.toString());
          }),
        ],
      }),
    });
    editor.current = view;
    return () => {
      view.destroy();
      editor.current = null;
    };
    // Draft updates keep the same editor and cursor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [disabled]);
  React.useEffect(() => {
    const view = editor.current;
    if (view && view.state.doc.toString() !== code)
      view.dispatch({
        changes: { from: 0, to: view.state.doc.length, insert: code },
      });
  }, [code]);
  React.useEffect(() => {
    const view = editor.current;
    if (!view) return;
    view.dispatch(
      setDiagnostics(
        view.state,
        diagnostics.map((diagnostic) => {
          const line = view.state.doc.line(
            Math.min(view.state.doc.lines, Math.max(1, diagnostic.line)),
          );
          return {
            from: Math.min(line.to, line.from + diagnostic.column),
            to: line.to,
            severity: "error",
            message: diagnostic.message,
          };
        }),
      ),
    );
  }, [diagnostics, disabled]);
  return <div ref={host} />;
}
