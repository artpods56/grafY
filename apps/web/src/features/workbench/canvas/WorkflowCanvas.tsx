"use client";

import * as React from "react";
import * as stylex from "@stylexjs/stylex";
import {
  Background,
  BackgroundVariant,
  Controls,
  ReactFlow,
  type EdgeTypes,
  type FitViewOptions,
  type IsValidConnection,
  type NodeTypes,
  type OnConnect,
  type OnConnectEnd,
  type OnEdgesChange,
  type OnNodesChange,
  type ReactFlowInstance,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useTheme } from "@/components/theme";
import { useMediaQuery } from "@/hooks/use-media-query";
import { tokens } from "@/lib/stylex/tokens.stylex";
import { ANNOTATION_NODE_TYPE } from "./annotations";
import {
  ARTIFACT_VIEWER_EDGE_TYPE,
  ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE,
  ARTIFACT_VIEWER_NODE_TYPE,
  type CanvasEdge,
  type CanvasNode,
} from "./artifact-viewer";
import { connectionIsValid } from "./handles";
import ArtifactViewerEdge from "./edges/ArtifactViewerEdge";
import ArtifactViewerInteractionEdge from "./edges/ArtifactViewerInteractionEdge";
import WorkflowEdgeControl from "./edges/WorkflowEdge";
import AnnotationNode from "./nodes/AnnotationNode";
import ArtifactViewerNode from "./nodes/ArtifactViewerNode";
import WorkflowNodeCard from "./nodes/WorkflowNode";
import {
  WORKFLOW_EDGE_TYPE,
  WORKFLOW_NODE_TYPE,
  type WorkflowEdge,
} from "./types";

export const nodeTypes: NodeTypes = {
  [WORKFLOW_NODE_TYPE]: WorkflowNodeCard,
  [ARTIFACT_VIEWER_NODE_TYPE]: ArtifactViewerNode,
  [ANNOTATION_NODE_TYPE]: AnnotationNode,
};

export const edgeTypes: EdgeTypes = {
  [WORKFLOW_EDGE_TYPE]: WorkflowEdgeControl,
  [ARTIFACT_VIEWER_EDGE_TYPE]: ArtifactViewerEdge,
  [ARTIFACT_VIEWER_INTERACTION_EDGE_TYPE]: ArtifactViewerInteractionEdge,
};

const s = stylex.create({
  wrapper: {
    position: "relative",
    width: "100%",
    height: "100%",
    backgroundColor: tokens.colorBg,
  },
});

export interface WorkflowCanvasProps {
  children?: React.ReactNode;
  fitViewOptions?: FitViewOptions<CanvasNode>;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  onNodesChange: OnNodesChange<CanvasNode>;
  onEdgesChange: OnEdgesChange<CanvasEdge>;
  onConnect: OnConnect;
  onConnectEnd?: OnConnectEnd;
  isValidConnection?: IsValidConnection<CanvasEdge>;
  onPaneReady?: (
    instance: ReactFlowInstance<CanvasNode, CanvasEdge>,
  ) => void;
  onPaneClick?: () => void;
  animateEdges?: boolean;
  /** Disable durable canvas gestures while authority or synchronization is unavailable. */
  editable?: boolean;
  /** Unmount nodes and edges outside the viewport. */
  onlyRenderVisibleElements?: boolean;
  /** Background lattice gap in flow units; omit to hide the painted grid. */
  gridGap?: number | null;
}

export function WorkflowCanvas({
  children,
  fitViewOptions,
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onConnect,
  onConnectEnd,
  isValidConnection = connectionIsValid,
  onPaneReady,
  onPaneClick,
  animateEdges = false,
  editable = true,
  onlyRenderVisibleElements = false,
  gridGap = 54,
}: WorkflowCanvasProps) {
  const { resolved } = useTheme();
  const compactCanvas = useMediaQuery("(max-width: 720px)");
  const backgroundTouch = React.useRef(false);
  const renderedEdges = React.useMemo(
    () => edges.map((edge) => ({
      ...edge,
      animated:
        edge.type === WORKFLOW_EDGE_TYPE &&
        animateEdges &&
        !(edge as WorkflowEdge).data?.compatibilityIssues?.length,
    })),
    [animateEdges, edges],
  );

  return (
    <div {...stylex.props(s.wrapper)}>
      <ReactFlow<CanvasNode, CanvasEdge>
        nodes={nodes}
        edges={renderedEdges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onConnectEnd={onConnectEnd}
        onInit={onPaneReady}
        onPaneClick={onPaneClick}
        isValidConnection={isValidConnection}
        fitView
        fitViewOptions={fitViewOptions ?? { padding: 0.18, maxZoom: 0.98 }}
        minZoom={0.35}
        maxZoom={1.7}
        colorMode={resolved}
        // Click on a handle is owned by port UI (e.g. expand fields); drag still connects.
        connectOnClick={false}
        panOnScroll
        panOnDrag={[1, 2]}
        selectionOnDrag
        onPointerDownCapture={(event) => {
          // React Flow starts box selection on primary pointerdown, including
          // touch. Its pan/zoom handler uses touchstart separately, so let that
          // own background touches without intercepting node or port gestures.
          backgroundTouch.current =
            event.pointerType === "touch" &&
            event.target instanceof Element &&
            event.target.classList.contains("react-flow__pane");
          if (backgroundTouch.current) {
            event.stopPropagation();
          }
        }}
        onClickCapture={(event) => {
          // In selection mode React Flow relies on pointerdown/up for pane
          // clicks. Preserve the native touch tap after skipping pointerdown;
          // pan/zoom prevents the compatibility click once a finger moves.
          if (
            !backgroundTouch.current ||
            !(event.target instanceof Element) ||
            !event.target.classList.contains("react-flow__pane")
          ) {
            return;
          }
          backgroundTouch.current = false;
          onPaneClick?.();
          const selectedNodes = nodes.filter((node) => node.selected);
          const selectedEdges = edges.filter((edge) => edge.selected);
          if (selectedNodes.length) {
            onNodesChange(selectedNodes.map((node) => ({
              id: node.id,
              type: "select",
              selected: false,
            })));
          }
          if (selectedEdges.length) {
            onEdgesChange(selectedEdges.map((edge) => ({
              id: edge.id,
              type: "select",
              selected: false,
            })));
          }
        }}
        multiSelectionKeyCode="Shift"
        zoomOnDoubleClick={false}
        nodesDraggable={editable}
        nodesConnectable={editable}
        edgesReconnectable={editable}
        deleteKeyCode={editable ? ["Backspace", "Delete"] : null}
        onlyRenderVisibleElements={onlyRenderVisibleElements}
        proOptions={{ hideAttribution: true }}
        defaultEdgeOptions={{
          animated: false,
          type: WORKFLOW_EDGE_TYPE,
          style: {
            stroke: tokens.colorAccent,
            strokeWidth: 2,
            opacity: 1,
          },
        }}
        connectionLineStyle={{
          stroke: tokens.colorAccent,
          strokeWidth: 2,
        }}
      >
        {children}
        {gridGap != null && gridGap > 0 ? (
          <Background
            variant={BackgroundVariant.Lines}
            gap={gridGap}
            // XYFlow draws lines at the pattern center and, when offset is 0,
            // falls through `0 || gap/2` to a half-cell shift. Passing gap/2
            // cancels the centered stroke so lines sit on world cell boundaries
            // (same lattice our snap math uses).
            offset={gridGap / 2}
            lineWidth={1}
            color={tokens.colorGrid}
          />
        ) : null}
        {compactCanvas ? null : (
          <Controls
            showInteractive={false}
            showFitView={false}
            style={{
              backgroundColor: tokens.colorFlowControls,
              borderColor: tokens.colorBorderStrong,
              borderRadius: "7px",
              overflow: "hidden",
            }}
          />
        )}
      </ReactFlow>
    </div>
  );
}

export { addEdge, applyNodeChanges, applyEdgeChanges };
