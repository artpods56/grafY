"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import { ChevronDown } from "lucide-react";

import type { ApplyPythonCodeResponse } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { WorkflowNodeData } from "../../../types";
import { GenericBody } from "../generic-body";
import { nodeInteractionProps } from "../ports";
import { PythonCodeEditor } from "./PythonCodeEditor";

const styles = stylex.create({
  section: {
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorDivider,
    padding: "0 16px 10px",
  },
  summary: {
    minHeight: "34px",
    display: "flex",
    alignItems: "center",
    gap: "8px",
    listStyle: "none",
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: tokens.fontSizeSm,
    fontWeight: 650,
    "::-webkit-details-marker": { display: "none" },
    "::marker": { content: "none" },
  },
  summaryLabel: { flex: "1 1 auto" },
  pending: {
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  chevron: {
    flexShrink: 0,
    color: tokens.colorSubtle,
  },
  editor: {
    overflow: "hidden",
    marginBottom: "8px",
    borderRadius: tokens.radiusMd,
    backgroundColor: tokens.colorSurfaceMuted,
    outline: {
      default: "none",
      ":focus-within": `2px solid ${tokens.colorAccentBorder}`,
    },
  },
  error: {
    margin: "0 0 8px",
    color: tokens.colorDanger,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.4,
  },
  apply: {
    width: "100%",
    minHeight: "29px",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    borderWidth: 0,
    borderRadius: tokens.radiusMd,
    backgroundColor: {
      default: tokens.colorSurfaceRaised,
      ":hover": tokens.colorHover,
      ":disabled": tokens.colorSurfaceMuted,
    },
    color: {
      default: tokens.colorText,
      ":disabled": tokens.colorTextDisabled,
    },
    cursor: { default: "pointer", ":disabled": "not-allowed" },
    fontSize: tokens.fontSizeXs,
    fontWeight: 500,
  },
  applyPending: {
    backgroundColor: {
      default: tokens.colorAccent,
      ":hover": tokens.colorAccentHover,
      ":disabled": tokens.colorSurfaceMuted,
    },
    color: {
      default: tokens.colorOnAccent,
      ":disabled": tokens.colorTextDisabled,
    },
  },
});

export function PythonBody({
  id,
  data,
  ...layoutProps
}: Omit<React.ComponentProps<typeof GenericBody>, "bodyHeight">) {
  const code = typeof data.config.code === "string" ? data.config.code : "";
  const [draft, setDraft] = React.useState(code);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [diagnostics, setDiagnostics] = React.useState<
    ApplyPythonCodeResponse["diagnostics"]
  >([]);
  const [appliedCode, setAppliedCode] = React.useState(code);
  if (appliedCode !== code) {
    setAppliedCode(code);
    setDraft(code);
    setDiagnostics([]);
  }
  const params = data.config.params;
  const paramsConfig =
    typeof params === "object" && params !== null && !Array.isArray(params)
      ? Object.fromEntries(Object.entries(params))
      : {};
  const schema = data.config.params_schema;
  const paramsSchema =
    typeof schema === "object" && schema !== null && !Array.isArray(schema)
      ? Object.fromEntries(Object.entries(schema))
      : {};
  const formData: WorkflowNodeData = {
    ...data,
    spec: { ...data.spec, config_schema: paramsSchema, secret_inputs: [] },
    config: paramsConfig,
    onConfigChange: data.onConfigChange
      ? (_nodeId, name, value) =>
          data.onConfigChange?.(id, "params", {
            ...paramsConfig,
            [name]: value,
          })
      : undefined,
  };
  const unapplied = draft !== code;
  async function apply() {
    if (!data.onApplyPythonCode) return;
    setBusy(true);
    setError(null);
    try {
      const result = await data.onApplyPythonCode(id, draft);
      setDiagnostics(result.diagnostics);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Apply failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <GenericBody id={id} data={formData} bodyHeight={null} {...layoutProps} />
      <details {...nodeInteractionProps(stylex.props(styles.section))}>
        <summary {...stylex.props(styles.summary)}>
          <span {...stylex.props(styles.summaryLabel)}>Code</span>
          {unapplied ? (
            <span {...stylex.props(styles.pending)}>Unapplied changes</span>
          ) : null}
          <ChevronDown
            size={14}
            aria-hidden="true"
            {...stylex.props(styles.chevron)}
          />
        </summary>
        <div {...stylex.props(styles.editor)}>
          <PythonCodeEditor
            code={draft}
            disabled={!data.onApplyPythonCode || busy}
            diagnostics={diagnostics}
            onChange={(value) => {
              setDraft(value);
              setDiagnostics([]);
            }}
          />
        </div>
        {diagnostics.map((diagnostic, index) => (
          <p key={index} role="alert" {...stylex.props(styles.error)}>
            Line {diagnostic.line}: {diagnostic.message}
          </p>
        ))}
        {error ? (
          <p role="alert" {...stylex.props(styles.error)}>
            {error}
          </p>
        ) : null}
        <button
          type="button"
          disabled={busy || !data.onApplyPythonCode}
          onClick={() => void apply()}
          {...stylex.props(
            styles.apply,
            unapplied ? styles.applyPending : null,
          )}
        >
          {busy ? "Applying…" : "Apply"}
        </button>
      </details>
    </>
  );
}
