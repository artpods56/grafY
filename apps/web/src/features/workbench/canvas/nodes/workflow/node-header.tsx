"use client";

import * as stylex from "@stylexjs/stylex";
import { ArrowUp, ExternalLink, LoaderCircle } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";

import { CanvasNodeHeader } from "../CanvasNodeChrome";
import type { WorkflowNodeData } from "../../types";

import { nodeInteractionProps } from "./ports";
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
  openModuleSource: {
    flexShrink: 0,
    minHeight: "18px",
    display: "inline-flex",
    alignItems: "center",
    gap: "3px",
    paddingInline: "5px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "4px",
    backgroundColor: {
      default: tokens.colorSurface,
      ":hover": tokens.colorHover,
    },
    color: tokens.colorMuted,
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 600,
  },
  upgradeModuleCall: {
    flexShrink: 0,
    minHeight: "22px",
    display: "inline-flex",
    alignItems: "center",
    gap: "3px",
    paddingInline: "6px",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "4px",
    backgroundColor: {
      default: tokens.colorSurface,
      ":hover": tokens.colorHover,
    },
    color: tokens.colorText,
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 600,
  },
});

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
  const executionLabel =
    data.execution.status === "idle" ? null : data.execution.status;
  const executionIsBusy =
    data.execution.status === "running" ||
    data.execution.status === "cancelling";

  return (
    <CanvasNodeHeader
      title={data.spec.title}
      selected={selected}
      aboutTitle={data.spec.title}
      aboutDescription={
        data.spec.description || "No description is available for this node."
      }
      aboutFooter={
        <>
          <span {...stylex.props(sharedStyles.operatorCopy)}>
            {typeof data.spec.module_graph_revision === "number"
              ? `Module · r${data.spec.module_graph_revision}`
              : `${data.spec.operator_id}@${data.spec.operator_version}`}
          </span>
          {data.spec.module_graph_id && data.onOpenModuleSource ? (
            <button
              type="button"
              aria-label={`Open source graph for ${data.spec.title}`}
              title="Open source graph"
              {...nodeInteractionProps(stylex.props(s.openModuleSource))}
              onClick={() => {
                if (!data.spec.module_graph_id) return;
                data.onOpenModuleSource?.(data.spec.module_graph_id);
              }}
            >
              <ExternalLink size={9} />
              Source
            </button>
          ) : null}
        </>
      }
      onRemove={() => data.onRemoveNode?.(id)}
      onMenuOpenChange={onMenuOpenChange}
      status={
        executionLabel ? (
          executionIsBusy ? (
            <LoaderCircle
              size={11}
              role="status"
              aria-label={`Execution ${executionLabel}`}
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
              role="status"
              aria-label={`Execution ${executionLabel}`}
              title={`Execution ${executionLabel}`}
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
          )
        ) : null
      }
    >
      {typeof data.moduleUpgradeRelease === "number" &&
      data.onUpgradeModuleCall ? (
        <button
          type="button"
          aria-label={`Upgrade module call to release ${data.moduleUpgradeRelease}`}
          title={`Upgrade to release ${data.moduleUpgradeRelease}`}
          {...nodeInteractionProps(stylex.props(s.upgradeModuleCall))}
          onClick={() => data.onUpgradeModuleCall?.(id)}
        >
          <ArrowUp size={11} />
          Upgrade to release {data.moduleUpgradeRelease}
        </button>
      ) : null}
      {typeof data.pluginUpgradeRelease === "number" &&
      data.onUpgradePluginRelease ? (
        <button
          type="button"
          aria-label={`Upgrade Plugin to release ${data.pluginUpgradeRelease}`}
          title={`Upgrade Plugin to release ${data.pluginUpgradeRelease}`}
          {...nodeInteractionProps(stylex.props(s.upgradeModuleCall))}
          onClick={() => data.onUpgradePluginRelease?.(id)}
        >
          <ArrowUp size={11} />
          Upgrade Plugin to release {data.pluginUpgradeRelease}
        </button>
      ) : null}
    </CanvasNodeHeader>
  );
}
