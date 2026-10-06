"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  useNodeConnections,
  useUpdateNodeInternals,
  type NodeProps,
} from "@xyflow/react";
import { TriangleAlert, X } from "lucide-react";

import { tokens } from "@/lib/stylex/tokens.stylex";

import { CanvasNodeHeader, nodeChrome } from "../CanvasNodeChrome";
import { artifactTypeKey } from "../../artifact-type-key";
import { schemaFields, validateConfig } from "../../config-schema";
import { nodeSecretInputs } from "../../node-secrets";
import {
  SCHEMA_BUILDER_INPUT_PORT,
  SCHEMA_BUILDER_OPERATOR_ID,
} from "../../schema-builder";
import {
  resolvedBodyHeight,
  resolvedNodeWidth,
  type WorkflowNodeLayout,
} from "../../node-layout";
import {
  ARTIFACT_QUERY_OPERATOR_ID,
  ARTIFACT_QUERY_RELATIONS_PORT,
} from "../../query-artifact-tables";
import {
  GIS_VECTOR_LAYER_OPERATOR_ID,
  portHasInstancePlugs,
  type WorkflowNodeData,
} from "../../types";
import { useOptionalCanvasGridSettings } from "../../canvas-grid-settings";
import { CanvasNodeShell, useCanvasNodeShell } from "../CanvasNodeShell";
import { LayoutResizeHandle } from "../LayoutResizeHandle";
import { NodeExecutionAppendix } from "../NodeExecutionAppendix";
import { VectorLayerStyleBody } from "../VectorLayerStyleBody";

import { ArtifactQueryTablesBody } from "./artifact-query-tables";
import { GenericArtifactTypeState, GenericBody } from "./generic-body";
import { InstancePlugPort } from "./instance-plug";
import { NodeHeader } from "./node-header";
import type { WorkflowNode } from "./node-type";
import { CompatibilityPortRail, PortRail, nodeInteractionProps } from "./ports";
import type { IncompatibleWorkflowNodeCompatibility } from "./ports";
import { SchemaBuilderBody } from "./schema-builder";
import { sharedStyles } from "./styles";

const s = stylex.create({
  compatibilityIcon: {
    color: tokens.colorWarning,
    flexShrink: 0,
  },
  compatibilityBadge: {
    height: "18px",
    display: "inline-flex",
    alignItems: "center",
    gap: "4px",
    flexShrink: 0,
    paddingInline: "6px",
    borderRadius: "9999px",
    backgroundColor: tokens.colorSurfaceSunken,
    color: tokens.colorMuted,
    fontSize: "9px",
    fontWeight: 600,
    letterSpacing: "0.05em",
    lineHeight: 1,
    textTransform: "uppercase",
  },
  compatibilityBody: {
    display: "grid",
    gap: "9px",
    padding: "4px 12px 13px",
  },
  compatibilityIssue: {
    margin: 0,
    color: tokens.colorMuted,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.5,
  },
  compatibilityConfig: {
    overflow: "hidden",
    borderWidth: 1,
    borderStyle: "solid",
    borderColor: tokens.colorBorder,
    borderRadius: "6px",
    backgroundColor: tokens.colorSurface,
  },
  compatibilityConfigSummary: {
    padding: "7px 9px",
    color: tokens.colorSubtle,
    cursor: "pointer",
    fontSize: "10px",
    fontWeight: 600,
  },
  compatibilityConfigValue: {
    maxHeight: "150px",
    overflow: "auto",
    margin: 0,
    padding: "8px 9px",
    borderTopWidth: 1,
    borderTopStyle: "solid",
    borderTopColor: tokens.colorBorder,
    color: tokens.colorMuted,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: "10px",
    lineHeight: 1.45,
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
  },
  header: {
    display: "grid",
    gap: "2px",
    padding: "12px 16px 12px 12px",
  },
  titleRow: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "4px",
  },
  /** Unsupported cards keep a direct remove: removal is the only repair. */
  removeButton: {
    backgroundColor: {
      default: "transparent",
      ":hover": tokens.colorDangerHover,
    },
    color: { default: tokens.colorSubtle, ":hover": tokens.colorDanger },
  },
  operatorRow: {
    minWidth: 0,
    display: "flex",
    alignItems: "center",
    gap: "6px",
    marginLeft: "56px",
  },
  plugPorts: {
    display: "grid",
    gap: "5px",
    paddingBlock: "2px",
  },
  emptyBody: {
    padding: "0 16px 14px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
    lineHeight: 1.45,
  },
  spacer: { minHeight: "4px" },
});

export function IncompatibleWorkflowNodeCard({
  id,
  data,
  selected,
  dragging,
  compatibility,
}: {
  id: string;
  data: WorkflowNodeData;
  selected: boolean;
  dragging: boolean;
  compatibility: IncompatibleWorkflowNodeCompatibility;
}) {
  const updateNodeInternals = useUpdateNodeInternals();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const grid = useOptionalCanvasGridSettings();
  const allowCornerResize = grid?.settings.allowWorkflowCornerResize ?? false;
  const [draftLayout, setDraftLayout] =
    React.useState<WorkflowNodeLayout | null>(null);
  const layout = draftLayout ?? data.layout;
  const nodeWidth = resolvedNodeWidth(layout);
  const shell = useCanvasNodeShell({
    id,
    selected,
    dragging,
    naturalWidth: nodeWidth,
    updateNodeInternals,
  });
  const { gridWidth, paintWidth, fillMinHeight } = shell;
  const endpointRevision = JSON.stringify({
    inputs: compatibility.inputs,
    outputs: compatibility.outputs,
  });
  const hasProgress = Boolean(data.progress?.entries.length);
  const hasExecutionError = Boolean(data.execution.error);
  const hasMaterialization = (data.run?.outputs ?? []).some(
    (output) => output.artifacts.length > 0,
  );
  const hasSavedHistory = Boolean(data.historyContext?.graphId);

  React.useLayoutEffect(() => {
    updateNodeInternals(id);
  }, [
    endpointRevision,
    fillMinHeight,
    gridWidth,
    hasExecutionError,
    hasMaterialization,
    hasProgress,
    hasSavedHistory,
    id,
    updateNodeInternals,
  ]);

  const commitLayout = React.useCallback(
    (next: WorkflowNodeLayout | null) => {
      setDraftLayout(null);
      data.onLayoutChange?.(id, next);
      window.requestAnimationFrame(() => updateNodeInternals(id));
    },
    [data, id, updateNodeInternals],
  );

  return (
    <CanvasNodeShell
      state={shell}
      selected={selected}
      remoteSelectionColor={data.remoteSelectionColor}
      variant="incompatible"
      ariaLabel={`${data.spec.title} ${compatibility.status} node`}
      menuOpen={menuOpen}
      header={
        <CanvasNodeHeader
          title={data.spec.title}
          selected={selected}
          aboutTitle={data.spec.title}
          aboutDescription={`This node is ${compatibility.status}. Remove it, or restore the plugin release it was saved with.`}
          aboutFooter={
            <span {...stylex.props(sharedStyles.operatorCopy)}>
              {data.spec.operator_id}@{data.spec.operator_version}
            </span>
          }
          onMenuOpenChange={setMenuOpen}
          status={
            <span
              role="status"
              title={`${data.spec.title} is ${compatibility.status}`}
              {...stylex.props(s.compatibilityBadge)}
            >
              <TriangleAlert
                size={11}
                aria-hidden="true"
                {...stylex.props(s.compatibilityIcon)}
              />
              {compatibility.status}
            </span>
          }
        >
          {/* Removal is the only repair, so it stays one click away. */}
          <button
            type="button"
            aria-label={`Remove ${data.spec.title}`}
            title={`Remove ${data.spec.title}`}
            {...nodeInteractionProps(
              stylex.props(nodeChrome.headerButton, s.removeButton),
            )}
            onClick={() => data.onRemoveNode?.(id)}
          >
            <X size={13} />
          </button>
        </CanvasNodeHeader>
      }
      resizeHandle={
        allowCornerResize ? (
          <LayoutResizeHandle
            layout={layout}
            axes={["width"]}
            ariaLabel={`Resize ${data.spec.title}`}
            onDraft={setDraftLayout}
            onCommit={commitLayout}
          />
        ) : undefined
      }
      appendix={
        <NodeExecutionAppendix
          nodeId={id}
          nodeTitle={data.spec.title}
          expanded={selected}
          width={paintWidth}
          execution={data.execution}
          progress={data.progress}
          run={data.run}
          historyContext={data.historyContext}
          onOpenHistory={data.onOpenExecutionHistory}
        />
      }
    >
      <CompatibilityPortRail
        nodeId={id}
        inputs={compatibility.inputs}
        outputs={compatibility.outputs}
      />
      <div {...stylex.props(s.compatibilityBody)}>
        {compatibility.issues.map((issue) => (
          <p key={issue} role="status" {...stylex.props(s.compatibilityIssue)}>
            {issue}
          </p>
        ))}
        <details {...nodeInteractionProps(stylex.props(s.compatibilityConfig))}>
          <summary {...stylex.props(s.compatibilityConfigSummary)}>
            Saved configuration
          </summary>
          <pre {...stylex.props(s.compatibilityConfigValue)}>
            {JSON.stringify(data.config, null, 2)}
          </pre>
        </details>
      </div>
    </CanvasNodeShell>
  );
}

export function SupportedWorkflowNodeCard({
  id,
  data,
  selected,
  dragging,
}: NodeProps<WorkflowNode>) {
  const fields = schemaFields(data.spec.config_schema);
  const configIssues = validateConfig(data.spec.config_schema, data.config);
  const secretInputs = nodeSecretInputs(data.spec);
  const isSchemaBuilder = data.spec.operator_id === SCHEMA_BUILDER_OPERATOR_ID;
  const isArtifactQuery = data.spec.operator_id === ARTIFACT_QUERY_OPERATOR_ID;
  const isVectorLayer = data.spec.operator_id === GIS_VECTOR_LAYER_OPERATOR_ID;
  const visibleInputPorts = data.spec.inputs.filter((port) => {
    if (isSchemaBuilder && port.name === SCHEMA_BUILDER_INPUT_PORT) {
      return false;
    }
    if (isArtifactQuery && port.name === ARTIFACT_QUERY_RELATIONS_PORT) {
      return false;
    }
    return true;
  });
  const hasConfig =
    fields.length > 0 || secretInputs.length > 0 || configIssues.length > 0;
  const hasExecutionError = Boolean(data.execution.error);
  const hasProgress = Boolean(data.progress?.entries.length);
  const hasMaterialization = (data.run?.outputs ?? []).some(
    (output) => output.artifacts.length > 0,
  );
  const hasSavedHistory = Boolean(data.historyContext?.graphId);
  const inputPlugRevision = data.inputPlugs
    .map((plug) => `${plug.portName}:${plug.id}`)
    .join("|");
  const schemaBuilderRevision = isSchemaBuilder
    ? JSON.stringify(data.config.fields ?? [])
    : "";
  const artifactTypeBindingRevision = Object.entries(data.artifactTypeBindings)
    .map(
      ([variable, artifactType]) =>
        `${variable}:${artifactTypeKey(artifactType)}`,
    )
    .sort()
    .join("|");
  const incidentConnections = useNodeConnections({ id });
  // A wire fixes a generic type, so the choice waits until the node is free.
  const typeLocked = incidentConnections.length > 0;
  const portTypeVariables = new Set(
    [...visibleInputPorts, ...data.spec.outputs].flatMap((port) =>
      port.artifact_type_variable ? [port.artifact_type_variable] : [],
    ),
  );
  const updateNodeInternals = useUpdateNodeInternals();
  const [menuOpen, setMenuOpen] = React.useState(false);
  const grid = useOptionalCanvasGridSettings();
  const allowCornerResize = grid?.settings.allowWorkflowCornerResize ?? false;
  const measuredArtifactTypeBindings = data.artifactTypeBindings;
  const onHandlesMeasured = data.onHandlesMeasured;
  const [draftLayout, setDraftLayout] =
    React.useState<WorkflowNodeLayout | null>(null);
  const layout = draftLayout ?? data.layout;
  const nodeWidth = resolvedNodeWidth(layout);
  const shell = useCanvasNodeShell({
    id,
    selected,
    dragging,
    naturalWidth: nodeWidth,
    updateNodeInternals,
  });
  const { gridWidth, paintWidth, fillMinHeight } = shell;
  const bodyHeight = resolvedBodyHeight(layout);
  const layoutRevision = [layout?.width ?? "", layout?.bodyHeight ?? ""].join(
    ":",
  );
  const commitLayout = (next: WorkflowNodeLayout | null) => {
    setDraftLayout(null);
    data.onLayoutChange?.(id, next);
    window.requestAnimationFrame(() => updateNodeInternals(id));
  };

  React.useLayoutEffect(() => {
    // React Flow measures handles in the animation frame queued here. Queue the
    // readiness callback afterward so a concrete generic handle is registered
    // before Workbench publishes an edge that targets it.
    updateNodeInternals(id);
    const frame = window.requestAnimationFrame(() =>
      onHandlesMeasured?.(id, measuredArtifactTypeBindings),
    );
    return () => window.cancelAnimationFrame(frame);
  }, [
    measuredArtifactTypeBindings,
    data.mappedInputPort,
    artifactTypeBindingRevision,
    inputPlugRevision,
    schemaBuilderRevision,
    layoutRevision,
    data.spec.inputs.length,
    data.spec.outputs.length,
    fields.length,
    fillMinHeight,
    gridWidth,
    secretInputs.length,
    hasExecutionError,
    hasMaterialization,
    hasProgress,
    hasSavedHistory,
    onHandlesMeasured,
    id,
    updateNodeInternals,
  ]);

  return (
    <CanvasNodeShell
      state={shell}
      selected={selected}
      remoteSelectionColor={data.remoteSelectionColor}
      menuOpen={menuOpen}
      header={
        <NodeHeader
          id={id}
          data={data}
          selected={selected ?? false}
          onMenuOpenChange={setMenuOpen}
        />
      }
      resizeHandle={
        allowCornerResize ? (
          <LayoutResizeHandle
            layout={layout}
            axes={["width", "bodyHeight"]}
            ariaLabel={`Resize ${data.spec.title}`}
            onDraft={setDraftLayout}
            onCommit={commitLayout}
          />
        ) : undefined
      }
      appendix={
        <NodeExecutionAppendix
          nodeId={id}
          nodeTitle={data.spec.title}
          expanded={selected}
          width={paintWidth}
          execution={data.execution}
          progress={data.progress}
          run={data.run}
          historyContext={data.historyContext}
          onOpenHistory={data.onOpenExecutionHistory}
        />
      }
    >
      <GenericArtifactTypeState
        id={id}
        data={data}
        resettable={!typeLocked}
        skip={portTypeVariables}
      />
      <PortRail
        id={id}
        data={data}
        inputPorts={visibleInputPorts.filter(
          (port) => !portHasInstancePlugs(port),
        )}
        outputPorts={data.spec.outputs}
        typeLocked={typeLocked}
      />
      {visibleInputPorts.some((port) => portHasInstancePlugs(port)) ? (
        <div {...stylex.props(s.plugPorts)}>
          {visibleInputPorts
            .filter((port) => portHasInstancePlugs(port))
            .map((port) => (
              <InstancePlugPort
                key={`in-${port.name}`}
                id={id}
                data={data}
                port={port}
                typeLocked={typeLocked}
              />
            ))}
        </div>
      ) : null}
      {isSchemaBuilder ? (
        <SchemaBuilderBody id={id} data={data} />
      ) : isArtifactQuery ? (
        <ArtifactQueryTablesBody id={id} data={data} />
      ) : isVectorLayer ? (
        <>
          <GenericBody
            id={id}
            data={data}
            bodyHeight={bodyHeight}
            layout={layout}
            onLayoutDraft={setDraftLayout}
            onLayoutCommit={commitLayout}
          />
          <VectorLayerStyleBody id={id} data={data} />
        </>
      ) : hasConfig ? (
        <GenericBody
          id={id}
          data={data}
          bodyHeight={bodyHeight}
          layout={layout}
          onLayoutDraft={setDraftLayout}
          onLayoutCommit={commitLayout}
        />
      ) : (
        <div {...stylex.props(s.spacer)} aria-hidden />
      )}
      {!isSchemaBuilder &&
      !isArtifactQuery &&
      !hasConfig &&
      !hasExecutionError &&
      !data.spec.inputs.length &&
      !data.spec.outputs.length ? (
        <p {...stylex.props(s.emptyBody)}>
          {data.spec.description || "No configuration for this operator."}
        </p>
      ) : null}
    </CanvasNodeShell>
  );
}
