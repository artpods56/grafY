"use client";

import * as stylex from "@stylexjs/stylex";
import { LoaderCircle } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";

import { CanvasNodeHeader } from "../CanvasNodeChrome";
import type { NodeExecutionStatus, WorkflowNodeData } from "../../types";

import { sharedStyles } from "./styles";

const s = stylex.create({
  /** Compact execution status stays visible without adding shell chrome. */
  executionDot: {
    width: "8px",
    height: "8px",
    flexShrink: 0,
    borderRadius: "9999px",
    backgroundColor: tokens.colorMuted,
  },
  executionDotSuccess: { backgroundColor: tokens.colorSuccess },
  executionDotDanger: { backgroundColor: tokens.colorDanger },
  executionSpinner: { flexShrink: 0, color: tokens.colorInfo },
  executionSpinnerWarning: { color: tokens.colorWarning },
  /** The word that says what the dot or spinner means. */
  executionWord: {
    flexShrink: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    whiteSpace: "nowrap",
  },
});

/** The one word a card shows for each status a run publishes about it. */
const EXECUTION_WORDS: Partial<Record<NodeExecutionStatus, string>> = {
  queued: "Waiting",
  running: "Working",
  cancelling: "Stopping",
  succeeded: "Done",
  failed: "Failed",
};

/**
 * One cell of chrome: the title always reads, everything else (about popover
 * with provenance, removal) appears once the node is selected. Execution keeps
 * only a status tell here — the status icon and appendix carry the detail.
 */
export function NodeHeader({
  id,
  data,
  selected,
  onMenuOpenChange,
}: {
  id: string;
  data: WorkflowNodeData;
  selected: boolean;
  onMenuOpenChange?: (open: boolean) => void;
}) {
  const executionIsBusy =
    data.execution.status === "running" ||
    data.execution.status === "cancelling";
  const executionWord = EXECUTION_WORDS[data.execution.status] ?? null;
  const executionName = `${data.spec.title} ${(executionWord ?? data.execution.status).toLowerCase()}`;

  return (
    <CanvasNodeHeader
      title={data.spec.title}
      selected={selected}
      aboutTitle={data.spec.title}
      aboutDescription={
        data.spec.description || "No description is available for this node."
      }
      aboutFooter={
        <span {...stylex.props(sharedStyles.operatorCopy)}>
          {data.spec.operator_id}@{data.spec.operator_version}
        </span>
      }
      onRemove={() => data.onRemoveNode?.(id)}
      onMenuOpenChange={onMenuOpenChange}
      status={
        data.execution.status === "idle" ? null : (
          <span
            role="status"
            aria-label={executionName}
            title={executionName}
            {...stylex.props(s.executionWord)}
          >
            {executionIsBusy ? (
              <LoaderCircle
                size={11}
                aria-hidden="true"
                {...stylex.props(
                  sharedStyles.spinner,
                  s.executionSpinner,
                  data.execution.status === "cancelling"
                    ? s.executionSpinnerWarning
                    : null,
                )}
              />
            ) : (
              <span
                aria-hidden="true"
                {...stylex.props(
                  s.executionDot,
                  data.execution.status === "succeeded"
                    ? s.executionDotSuccess
                    : null,
                  data.execution.status === "failed"
                    ? s.executionDotDanger
                    : null,
                )}
              />
            )}
            {executionWord}
          </span>
        )
      }
    />
  );
}
