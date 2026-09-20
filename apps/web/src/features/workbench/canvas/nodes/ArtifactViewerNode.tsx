"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  useEdges,
  useNodesData,
  useUpdateNodeInternals,
  type NodeProps,
} from "@xyflow/react";
import { Download, LoaderCircle, TriangleAlert } from "lucide-react";

import {
  artifactDownloadUrl,
  type ArtifactSummary,
} from "@/lib/api";
import { useNodeRegistry } from "@/hooks/use-api";
import { useWorkspaceContext } from "@/features/workspaces/WorkspaceLayout";
import { tokens } from "@/lib/stylex/tokens.stylex";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INPUT_HANDLE,
  ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE,
  ARTIFACT_VIEWER_INTERACTION_INPUT_HANDLE,
  ARTIFACT_VIEWER_INTERACTION_OUTPUT_HANDLE,
  type ArtifactViewerEdge,
  type ArtifactViewerNode,
  type CanvasEdge,
  type CanvasNode,
} from "../artifact-viewer";
import {
  EMPTY_ARTIFACT_KEY_SELECTION,
  type ArtifactViewerInteractionContext,
} from "../artifact-interactions";
import {
  resolvedAppendixHeight,
  resolvedNodeWidth,
  type WorkflowNodeLayout,
} from "../node-layout";
import { artifactTypeColor } from "../nodes.css";
import {
  WORKFLOW_NODE_TYPE,
  effectivePortShape,
  resolvedPortArtifactType,
} from "../types";
import { ArtifactCardBody } from "./ArtifactCardBody";
import { ArtifactPortPreview } from "./ArtifactsAppendix";
import { presentsArtifacts } from "../artifact-card";
import { rendererCanBrush } from "./artifact-renderers";
import {
  type CanvasNodeOverflowItem,
  CanvasNodeHeader,
  CanvasPortRail,
  CanvasPortTab,
  canvasNodeInteractionProps,
} from "./CanvasNodeChrome";
import {
  CanvasNodeShell,
  useCanvasNodeShell,
} from "./CanvasNodeShell";
import { LayoutResizeHandle } from "./LayoutResizeHandle";

const s = stylex.create({
  viewport: {
    minHeight: 0,
    overflow: "hidden",
    padding: "0 12px 10px",
  },
  waiting: {
    minHeight: "32px",
    display: "grid",
    placeItems: "center",
    padding: "6px 12px 10px",
    color: tokens.colorSubtle,
    fontSize: tokens.fontSizeXs,
  },
  aboutMeta: {
    overflow: "hidden",
    color: tokens.colorSubtle,
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: tokens.fontSizeXs,
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  spinner: {
    animationName: "grafy-spin",
    animationDuration: "900ms",
    animationIterationCount: "infinite",
    animationTimingFunction: "linear",
  },
  statusBusy: { flexShrink: 0, color: tokens.colorInfo },
  statusUnavailable: { flexShrink: 0, color: tokens.colorWarning },
});

export default function ArtifactViewerNodeCard({
  id,
  data,
  isConnectable,
  selected,
  dragging,
}: NodeProps<ArtifactViewerNode>) {
  const edges = useEdges<CanvasEdge>();
  const incomingEdge = edges.find(
    (edge): edge is ArtifactViewerEdge =>
      edge.type === ARTIFACT_VIEWER_EDGE_TYPE &&
      edge.target === id &&
      edge.targetHandle === ARTIFACT_VIEWER_INPUT_HANDLE,
  );
  const sourceNodeCandidate = useNodesData<CanvasNode>(
    incomingEdge?.source ?? "",
  );
  const sourceNode = sourceNodeCandidate?.type === WORKFLOW_NODE_TYPE
    ? sourceNodeCandidate
    : null;
  const sourcePortName = incomingEdge?.data?.sourcePortName ?? null;
  const sourcePort = sourceNode && sourcePortName
    ? sourceNode.data.spec.outputs.find(
        (candidate) => candidate.name === sourcePortName,
      )
    : undefined;
  const succeededRun = sourceNode?.data.run?.status === "succeeded"
    ? sourceNode.data.run
    : null;
  const output = succeededRun && sourcePortName
    ? succeededRun.outputs.find(
        (candidate) => candidate.port === sourcePortName,
      )
    : undefined;
  const renderableOutput = output?.artifacts.length ? output : null;
  const firstArtifact = renderableOutput?.artifacts[0];
  const declaredArtifactType = sourcePort && sourceNode
    ? resolvedPortArtifactType(
        sourcePort,
        sourceNode.data.artifactTypeBindings,
      )
    : null;
  const artifactTypeLabel = firstArtifact
    ? `${firstArtifact.artifact_type}@${firstArtifact.schema_version}`
    : declaredArtifactType
      ? `${declaredArtifactType.id}@${declaredArtifactType.schema_version}`
      : null;
  const artifactShapeLabel = output
    ? output.kind
    : sourcePort && sourceNode
      ? effectivePortShape(sourceNode.data, sourcePort) === "many"
        ? "sequence"
        : "single"
      : null;
  const artifactContract = artifactTypeLabel
    ? artifactShapeLabel
      ? `${artifactTypeLabel} · ${artifactShapeLabel}`
      : artifactTypeLabel
    : null;
  const feedLabel = incomingEdge?.data?.projection?.path.length
    ? `${sourcePort?.title ?? sourcePortName ?? "output"}.${incomingEdge.data.projection.path.join(".")}`
    : (sourcePort?.title ?? sourcePortName ?? "output");
  const sourceLabel = incomingEdge
    ? sourceNode
      ? `${sourceNode.data.spec.title} → ${feedLabel}`
      : `${incomingEdge.source} → ${feedLabel}`
    : null;
  const sourceIsBusy =
    sourceNode?.data.execution.status === "queued" ||
    sourceNode?.data.execution.status === "running" ||
    sourceNode?.data.execution.status === "cancelling";
  const hasInteractionEdges = edges.some(
    (edge) =>
      edge.type === ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE &&
      (edge.source === id || edge.target === id),
  );
  const showInteractionRow =
    rendererCanBrush(firstArtifact) || hasInteractionEdges;
  const showPreview = Boolean(renderableOutput);
  const showWaiting = Boolean(incomingEdge) && !renderableOutput;
  const artifactColor = declaredArtifactType
    ? artifactTypeColor(declaredArtifactType.id, tokens.colorAccent)
    : firstArtifact
      ? artifactTypeColor(firstArtifact.artifact_type, tokens.colorAccent)
      : tokens.colorAccent;
  const updateNodeInternals = useUpdateNodeInternals();
  const [draftLayout, setDraftLayout] = React.useState<WorkflowNodeLayout | null>(
    null,
  );
  const layout = draftLayout ?? data.layout;
  const width = resolvedNodeWidth(layout);
  const previewHeight = resolvedAppendixHeight(layout);
  const shell = useCanvasNodeShell({
    id,
    selected,
    dragging,
    naturalWidth: width,
    updateNodeInternals,
  });
  const { gridWidth, fillMinHeight } = shell;
  const outputRevision = renderableOutput?.artifacts
    .map((artifact) => artifact.artifact_id)
    .join(":") ?? "";
  const { workspace } = useWorkspaceContext();
  const { data: registry } = useNodeRegistry(workspace.id);
  const [focusedArtifact, setFocusedArtifact] = React.useState<
    ArtifactSummary | null
  >(null);
  const focusedFormats = focusedArtifact?.download_formats ?? [];
  const overflowItems: CanvasNodeOverflowItem[] =
    focusedFormats.length && showPreview && focusedArtifact
      ? focusedFormats.map((format) => {
          const artifactId = focusedArtifact.artifact_id;
          return {
            id: `download-${format.format}`,
            label: `Download as ${format.format.toUpperCase()}`,
            icon: <Download size={13} />,
            onClick: () => {
              const url = artifactDownloadUrl(
                workspace.id,
                artifactId,
                format.format,
              );
              const anchor = document.createElement("a");
              anchor.href = url;
              anchor.download = "";
              anchor.hidden = true;
              document.body.append(anchor);
              anchor.click();
              anchor.remove();
            },
          };
        })
      : [];
  const interaction = React.useMemo<ArtifactViewerInteractionContext>(
    () => ({
      outgoingFields: data.outgoingFields ?? [],
      selection: data.selection ?? EMPTY_ARTIFACT_KEY_SELECTION,
      incoming: data.incomingBindings ?? [],
      onFieldsChange: (fields) =>
        data.onFieldsChange?.(id, fields),
      onSelectionChange: (selection) =>
        data.onSelectionChange?.(id, selection),
      onActivityChange: (activity) =>
        data.onActivityChange?.(id, activity),
    }),
    [data, id],
  );

  React.useLayoutEffect(() => {
    updateNodeInternals(id);
  }, [
    fillMinHeight,
    gridWidth,
    id,
    incomingEdge?.id,
    outputRevision,
    previewHeight,
    showInteractionRow,
    showPreview,
    showWaiting,
    updateNodeInternals,
  ]);

  const commitLayout = (next: WorkflowNodeLayout | null) => {
    setDraftLayout(null);
    data.onLayoutChange?.(id, next);
    window.requestAnimationFrame(() => updateNodeInternals(id));
  };

  // A viewer that carries artifacts is an artifact on the canvas, so it paints
  // the artifact itself rather than a preview of a connected output.
  if (presentsArtifacts(data.artifactRef)) {
    return <ArtifactCardBody id={id} data={data} value={data.artifactRef} />;
  }

  return (
    <CanvasNodeShell
      state={shell}
      selected={selected}
      remoteSelectionColor={data.remoteSelectionColor}
      ariaLabel="Artifact viewer"
      testId="artifact-viewer-node"
      resizeHandle={
        showPreview ? (
          <LayoutResizeHandle
            layout={layout}
            axes={["width", "appendixHeight"]}
            ariaLabel="Resize artifact viewer"
            onDraft={setDraftLayout}
            onCommit={commitLayout}
          />
        ) : undefined
      }
    >
      <CanvasNodeHeader
        title="Artifact Viewer"
        selected={selected ?? false}
        aboutLabel="About Artifact Viewer"
        aboutTitle="Artifact Viewer"
        aboutDescription={
          sourceLabel
            ? `Preview of ${sourceLabel}. The renderer follows the connected artifact type.`
            : "Presentation-only preview. Connect an output and the renderer follows that artifact type."
        }
        aboutFooter={
          artifactContract ? (
            <span
              title={artifactContract}
              {...stylex.props(s.aboutMeta)}
            >
              {artifactContract}
            </span>
          ) : null
        }
        overflowItems={overflowItems}
        onRemove={() => data.onRemoveNode?.(id)}
        status={
          sourceIsBusy ? (
            <LoaderCircle
              size={11}
              role="status"
              aria-label="Updating"
              {...stylex.props(s.spinner, s.statusBusy)}
            />
          ) : incomingEdge && !sourceNode ? (
            <TriangleAlert
              size={11}
              role="status"
              aria-label="Unavailable"
              {...stylex.props(s.statusUnavailable)}
            />
          ) : null
        }
      />
      <CanvasPortRail
        rows={[
          {
            input: (
              <CanvasPortTab
                nodeId={id}
                label="Artifact"
                hint={incomingEdge ? undefined : "any"}
                direction="input"
                handleId={ARTIFACT_VIEWER_INPUT_HANDLE}
                color={artifactColor}
                isConnectable={isConnectable}
                ariaLabel="Input port Artifact, accepts Any artifact"
                title="Accepts any artifact or artifact sequence. Connect an output here."
              />
            ),
          },
          ...(showInteractionRow
            ? [{
                input: (
                  <CanvasPortTab
                    nodeId={id}
                    label="Follow selection"
                    direction="input"
                    handleId={ARTIFACT_VIEWER_INTERACTION_INPUT_HANDLE}
                    color={tokens.colorInfo}
                    isConnectable={isConnectable}
                    ariaLabel="Follow selection from another Artifact Viewer"
                    title="Accept a key selection from another Artifact Viewer."
                  />
                ),
                output: (
                  <CanvasPortTab
                    nodeId={id}
                    label="Selected rows"
                    direction="output"
                    handleId={ARTIFACT_VIEWER_INTERACTION_OUTPUT_HANDLE}
                    color={tokens.colorInfo}
                    isConnectable={isConnectable}
                    ariaLabel="Selected rows from this Artifact Viewer"
                    title="Send this viewer's key selection to another Artifact Viewer."
                  />
                ),
              }]
            : []),
        ]}
      />
      {showPreview && renderableOutput ? (
        <div
          {...canvasNodeInteractionProps(stylex.props(s.viewport))}
          style={{ height: previewHeight }}
        >
          <ArtifactPortPreview
            key={`${incomingEdge?.source}:${renderableOutput.port}:${outputRevision}:${incomingEdge?.data?.projection?.path.join(".") ?? "whole"}`}
            output={renderableOutput}
            artifactTypes={registry?.artifact_types ?? []}
            previewHeight={Math.max(120, previewHeight - 44)}
            modeChoice={data.mode}
            onModeChoiceChange={(mode) => data.onModeChange?.(id, mode)}
            feedProjection={incomingEdge?.data?.projection ?? null}
            interaction={interaction}
            onFocusedArtifactChange={setFocusedArtifact}
          />
        </div>
      ) : showWaiting ? (
        <div {...stylex.props(s.waiting)}>
          {incomingEdge && !sourceNode
            ? "Source unavailable"
            : "Waiting for artifact"}
        </div>
      ) : null}
    </CanvasNodeShell>
  );
}
