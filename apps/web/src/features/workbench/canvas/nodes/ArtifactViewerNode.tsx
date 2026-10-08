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

import { artifactDownloadUrl, type ArtifactSummary } from "@/lib/api";
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
import { useArtifactTypeCatalog } from "../use-artifact-type-catalog";
import {
  formatArtifactTypeLabel,
  formatArtifactTypeTooltip,
} from "../artifact-type-label";
import {
  WORKFLOW_NODE_TYPE,
  effectivePortShape,
  resolvedPortArtifactType,
} from "../types";
import { ArtifactCardBody } from "./ArtifactCardBody";
import { ArtifactPortPreview } from "./ArtifactsAppendix";
import { presentsArtifacts } from "../artifact-card";
import { rendererCanBrush } from "./artifact-renderers/registry";
import {
  CanvasCardLeftRail,
  CanvasCardRailSlot,
  CanvasCardRightRail,
  useCanvasRailRowHeight,
} from "./CanvasCardLayout";
import {
  type CanvasNodeOverflowItem,
  CanvasNodeHeader,
  canvasNodeInteractionProps,
} from "./CanvasNodeChrome";
import { CanvasNodeShell, useCanvasNodeShell } from "./CanvasNodeShell";
import { LayoutResizeHandle } from "./LayoutResizeHandle";
import { PortBall } from "./PortBall";

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

export default function ArtifactViewerNodeCard(
  props: NodeProps<ArtifactViewerNode>,
) {
  const { id, data, isConnectable, selected, dragging } = props;
  // Artifact mode follows a connected output even before it has a saved ref.
  // Standalone viewers with refs use the same direct canvas presentation.
  if (data.mode === "artifact" || presentsArtifacts(data.artifactRef)) {
    return (
      <ArtifactCardBody
        isConnectable={isConnectable}
        id={id}
        data={data}
        value={data.artifactRef ?? null}
        selected={selected}
        dragging={dragging}
      />
    );
  }

  return <RichArtifactViewerNode {...props} />;
}

function RichArtifactViewerNode({
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
  const sourceNode =
    sourceNodeCandidate?.type === WORKFLOW_NODE_TYPE
      ? sourceNodeCandidate
      : null;
  const sourcePortName = incomingEdge?.data?.sourcePortName ?? null;
  const sourcePort =
    sourceNode && sourcePortName
      ? sourceNode.data.spec.outputs.find(
          (candidate) => candidate.name === sourcePortName,
        )
      : undefined;
  const succeededRun =
    sourceNode?.data.run?.status === "succeeded" ? sourceNode.data.run : null;
  const output =
    succeededRun && sourcePortName
      ? succeededRun.outputs.find(
          (candidate) => candidate.port === sourcePortName,
        )
      : undefined;
  const renderableOutput = output?.artifacts.length ? output : null;
  const firstArtifact = renderableOutput?.artifacts[0];
  const declaredArtifactType =
    sourcePort && sourceNode
      ? resolvedPortArtifactType(
          sourcePort,
          sourceNode.data.artifactTypeBindings,
        )
      : null;
  const artifactTypes = useArtifactTypeCatalog();
  const shownArtifactType = firstArtifact
    ? {
        id: firstArtifact.artifact_type,
        schema_version: firstArtifact.schema_version,
      }
    : declaredArtifactType;
  const artifactTypeLabel = shownArtifactType
    ? formatArtifactTypeLabel(shownArtifactType, artifactTypes)
    : null;
  const artifactTypeTooltip = shownArtifactType
    ? formatArtifactTypeTooltip(shownArtifactType)
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
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [draftLayout, setDraftLayout] =
    React.useState<WorkflowNodeLayout | null>(null);
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
  const outputRevision =
    renderableOutput?.artifacts
      .map((artifact) => artifact.artifact_id)
      .join(":") ?? "";
  const { workspace } = useWorkspaceContext();
  const { data: registry } = useNodeRegistry(workspace.id);
  const [focusedArtifact, setFocusedArtifact] =
    React.useState<ArtifactSummary | null>(null);
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
      onFieldsChange: (fields) => data.onFieldsChange?.(id, fields),
      onSelectionChange: (selection) => data.onSelectionChange?.(id, selection),
      onActivityChange: (activity) => data.onActivityChange?.(id, activity),
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

  return (
    <CanvasNodeShell
      state={shell}
      selected={selected}
      remoteSelectionColor={data.remoteSelectionColor}
      ariaLabel="Artifact viewer"
      testId="artifact-viewer-node"
      menuOpen={menuOpen}
      railRows={showInteractionRow ? 2 : 1}
      header={
        <CanvasNodeHeader
          title="Artifact Viewer"
          selected={selected ?? false}
          onMenuOpenChange={setMenuOpen}
          aboutTitle="Artifact Viewer"
          aboutDescription={
            sourceLabel
              ? `Preview of ${sourceLabel}. The renderer follows the connected artifact type.`
              : "Presentation-only preview. Connect an output and the renderer follows that artifact type."
          }
          aboutFooter={
            artifactContract ? (
              <span
                title={artifactTypeTooltip ?? artifactContract}
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
      }
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
      <ArtifactViewerPortRails
        nodeId={id}
        artifactColor={artifactColor}
        isConnectable={isConnectable}
        showInteractionRow={showInteractionRow}
        openTypeHint={!incomingEdge}
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

/** The Artifact Viewer's rails: unlabeled balls, names on hover. */
function ArtifactViewerPortRails({
  nodeId,
  artifactColor,
  isConnectable,
  showInteractionRow,
  openTypeHint,
}: {
  nodeId: string;
  artifactColor: string;
  isConnectable: boolean;
  showInteractionRow: boolean;
  openTypeHint: boolean;
}) {
  const rowHeight = useCanvasRailRowHeight();

  return (
    <>
      <CanvasCardLeftRail testId="port-rail">
        <CanvasCardRailSlot height={rowHeight}>
          <PortBall
            nodeId={nodeId}
            handleId={ARTIFACT_VIEWER_INPUT_HANDLE}
            side="input"
            color={artifactColor}
            isConnectable={isConnectable}
            open={openTypeHint}
            order={0}
            ariaLabel="Input port Artifact, accepts Any artifact"
            title="Accepts any artifact or artifact sequence. Connect an output here."
            tip={{
              name: "Artifact",
              type: openTypeHint ? "Any artifact" : "Connected",
              hint: "Connect an output here.",
            }}
          />
        </CanvasCardRailSlot>
        {showInteractionRow ? (
          <CanvasCardRailSlot height={rowHeight}>
            <PortBall
              nodeId={nodeId}
              handleId={ARTIFACT_VIEWER_INTERACTION_INPUT_HANDLE}
              side="input"
              color={tokens.colorInfo}
              isConnectable={isConnectable}
              order={1}
              ariaLabel="Follow selection from another Artifact Viewer"
              title="Accept a key selection from another Artifact Viewer."
              tip={{
                name: "Follow selection",
                type: "Selection",
                hint: "Accept a key selection from another Artifact Viewer.",
              }}
            />
          </CanvasCardRailSlot>
        ) : null}
      </CanvasCardLeftRail>
      {showInteractionRow ? (
        <CanvasCardRightRail testId="port-rail-out">
          <CanvasCardRailSlot height={rowHeight}>
            <PortBall
              nodeId={nodeId}
              handleId={ARTIFACT_VIEWER_INTERACTION_OUTPUT_HANDLE}
              side="output"
              color={tokens.colorInfo}
              isConnectable={isConnectable}
              order={0}
              ariaLabel="Selected rows from this Artifact Viewer"
              title="Send this viewer's key selection to another Artifact Viewer."
              tip={{
                name: "Selected rows",
                type: "Selection",
                hint: "Send this viewer's key selection to another Artifact Viewer.",
              }}
            />
          </CanvasCardRailSlot>
        </CanvasCardRightRail>
      ) : null}
    </>
  );
}
