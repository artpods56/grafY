"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import type { ApplyPythonCodeResponse } from "@/lib/api";
import { tokens } from "@/lib/stylex/tokens.stylex";
import type { WorkflowNodeData } from "../../../types";
import { GenericBody } from "../generic-body";
import { PythonCodeEditor } from "./PythonCodeEditor";

const styles = stylex.create({
  code: { padding: "8px 16px", minWidth: 0 },
  summary: { cursor: "pointer", fontSize: tokens.fontSizeXs },
  error: { color: tokens.colorDanger, fontSize: tokens.fontSizeXs },
  button: {
    marginTop: "8px",
    padding: "4px 8px",
    borderRadius: tokens.radiusSm,
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    backgroundColor: tokens.colorSurface,
    color: tokens.colorText,
    cursor: "pointer",
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
  async function apply() {
    if (!data.onApplyPythonCode) return;
    setBusy(true);
    setError(null);
    try {
      const result = await data.onApplyPythonCode(id, draft);
      setDiagnostics(result.diagnostics);
    } catch (error) {
      setError(error instanceof Error ? error.message : "Apply failed");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <GenericBody id={id} data={formData} bodyHeight={null} {...layoutProps} />
      <details {...stylex.props(styles.code)} className="nodrag nowheel">
        <summary {...stylex.props(styles.summary)}>Code</summary>
        <PythonCodeEditor
          code={draft}
          disabled={!data.onApplyPythonCode || busy}
          diagnostics={diagnostics}
          onChange={(value) => {
            setDraft(value);
            setDiagnostics([]);
          }}
        />
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
          {...stylex.props(styles.button)}
        >
          {busy ? "Applying…" : "Apply"}
        </button>
        {draft !== code ? <span> Unapplied changes</span> : null}
      </details>
    </>
  );
}
